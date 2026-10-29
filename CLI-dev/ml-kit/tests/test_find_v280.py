# -*- coding: utf-8 -*-
"""
2.8.0: model-based reverse lookup (ml_predict.py --find --vary): all answers (step noise merged), operating windows
from the 90% prediction interval, training-median defaults, measured cross-check, CLI contract.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "CLI", "ml-kit")  # 실행 파일은 CLI\ml-kit
sys.path.insert(0, HERE)
sys.path.insert(0, KIT)
from test_cli_smoke import run_raw, run_tool, run_fail  # noqa: E402

# y = 100 + 8 sin(pi (t - 170) / 25) + 6 (p - 3)^2: at p = 3, y = 105 at t = 175.37 and 189.63 (rises, then falls)
TRUE_105 = (175.37, 189.63)


@pytest.fixture(scope="module")
def hill(tmp_path_factory):
    d = tmp_path_factory.mktemp("find")
    r = np.random.default_rng(5)
    n = 400
    t, p = r.uniform(170, 195, n), r.uniform(2.5, 3.5, n)
    y = 100 + 8 * np.sin((t - 170) / 25 * np.pi) + 6 * (p - 3) ** 2 + r.normal(0, 0.4, n)
    path = d / "hill.csv"
    pd.DataFrame({"반응온도": t, "압축압력": p, "라인": np.where(np.arange(n) % 2, "A", "B"), "생산효율": y,
                  "등급": np.where(y > 104, "상", "하")}).to_csv(path, index=False)
    res = run_tool("ml_train.py", "-f", str(path), "-x", "반응온도,압축압력", "-y", "생산효율")
    return d, path, res["version_dir"]


def test_two_answers_windows_and_measured(hill):
    _, _, vdir = hill
    r = run_tool("ml_predict.py", "-m", vdir, "--find", "생산효율=105", "--vary", "반응온도", "-i", "압축압력=3")
    assert r["count"] == 2 and r["verified"] and r["agent_directive"].startswith("VERIFIED:")
    for ans, truth in zip(r["solutions"], TRUE_105):
        assert abs(ans["반응온도"] - truth) < 1.0
    wins = r["operating_windows"]
    assert wins and all(any(w["from"] <= a["반응온도"] <= w["to"] for w in wins) for a in r["solutions"])
    m = r["measured"]
    assert m["count"] == 2 and all(abs(v - t) < 1.0 for v, t in zip(m["solutions"], TRUE_105))
    assert len(r["nearest_rows"]) == 5 and r["filled_defaults"] == {}
    assert "운전 구간" in r["preview"] and "실측 기준" in r["preview"]


def test_unreachable_and_default_inputs(hill):
    _, _, vdir = hill
    r = run_tool("ml_predict.py", "-m", vdir, "--find", "생산효율=112", "--vary", "반응온도", "-i", "압축압력=3")
    assert r["count"] == 0 and r["solutions"] == [] and r["reachable"]["max"] < 112
    assert "찾은 값 없음" in r["preview"] and "count 0" in r["agent_directive"]
    d = run_tool("ml_predict.py", "-m", vdir, "--find", "생산효율=105", "--vary", "반응온도")   # 압축압력 not given
    assert set(d["filled_defaults"]) == {"압축압력(bar)"} or set(d["filled_defaults"]) == {"압축압력"}
    assert "중앙값" in d["warnings"][0] and d["count"] >= 1


def test_out_of_range_fixed_input_warns(hill):
    _, _, vdir = hill
    r = run_tool("ml_predict.py", "-m", vdir, "--find", "생산효율=105", "--vary", "반응온도", "-i", "압축압력=9")
    assert any("학습 범위" in w for w in r["warnings"])


def test_inputs_errors(hill):
    d, path, vdir = hill
    cat = run_tool("ml_train.py", "-f", str(path), "-x", "반응온도,압축압력,라인", "-y", "생산효율")
    miss = run_fail("ml_predict.py", "-m", cat["version_dir"], "--find", "생산효율=105", "--vary", "반응온도", "-i", "압축압력=3")
    assert "[후보] A, B" in miss["message"]                                        # category never guessed
    ok = run_tool("ml_predict.py", "-m", cat["version_dir"], "--find", "생산효율=105", "--vary", "반응온도",
                  "-i", "압축압력=3,라인=A")
    assert ok["status"] == "ok"
    assert "숫자 입력이 아니라" in run_fail("ml_predict.py", "-m", cat["version_dir"], "--find", "생산효율=105",
                                           "--vary", "라인", "-i", "압축압력=3")["message"]
    cls = run_tool("ml_train.py", "-f", str(path), "-x", "반응온도,압축압력", "-y", "등급", "--task", "classification")
    assert "분류" in run_fail("ml_predict.py", "-m", cls["version_dir"], "--find", "등급=1", "--vary", "반응온도")["message"]
    proc, payload = run_raw("ml_predict.py", "-m", vdir, "--find", "생산효율=105")                 # --vary missing
    assert proc.returncode == 2 and payload["status"] == "error"
    proc, payload = run_raw("ml_predict.py", "-m", vdir, "--find", "생산효율=105", "--vary", "반응온도", "-f", str(path))
    assert proc.returncode == 2


def test_linear_model_exact_answer(tmp_path):
    r = np.random.default_rng(7)
    n = 200
    t, p = r.uniform(170, 195, n), r.uniform(2.5, 3.5, n)
    path = tmp_path / "lin.csv"
    pd.DataFrame({"반응온도": t, "압축압력": p, "생산효율": 0.5 * t + 8 * p + r.normal(0, 0.05, n)}).to_csv(path, index=False)
    v = run_tool("ml_train.py", "-f", str(path), "-x", "반응온도,압축압력", "-y", "생산효율")["version_dir"]
    res = run_tool("ml_predict.py", "-m", v, "--find", "생산효율=114", "--vary", "반응온도", "-i", "압축압력=3")
    assert res["count"] == 1 and res["solutions"][0]["반응온도"] == pytest.approx((114 - 24) / 0.5, abs=0.5)


def test_many_inputs_skip_measured_lookup(tmp_path):
    r = np.random.default_rng(8)
    n = 200
    df = pd.DataFrame({c: r.uniform(0, 1, n) for c in ("a", "b", "c", "d")})
    df["y"] = df.a * 10 + df.b + df.c + df.d
    path = tmp_path / "m.csv"
    df.to_csv(path, index=False)
    v = run_tool("ml_train.py", "-f", str(path), "-x", "a,b,c,d", "-y", "y")["version_dir"]
    res = run_tool("ml_predict.py", "-m", v, "--find", "y=6", "--vary", "a", "-i", "b=0.5,c=0.5,d=0.5")
    assert "생략" in res["measured"]["note"] and len(res["nearest_rows"]) == 5
    assert res["count"] >= 1 and abs(res["solutions"][0]["a"] - 0.45) < 0.1
