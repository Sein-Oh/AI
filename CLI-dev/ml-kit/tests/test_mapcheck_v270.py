# -*- coding: utf-8 -*-
"""
2.7.0: every regression prediction carries a measured-data comparison (map check) computed from the version
folder's model_dataset.csv (<= 3 numeric inputs: table interpolation, more: IDW of the 5 nearest rows).
"""
import os
import shutil
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "CLI", "ml-kit")  # 실행 파일은 CLI\ml-kit
sys.path.insert(0, HERE)
sys.path.insert(0, KIT)
from test_cli_smoke import run_tool  # noqa: E402

N = 200


def _data(path, marks=False):
    r = np.random.default_rng(3)
    t, p, c, w = r.uniform(170, 195, N), r.uniform(2.5, 3.5, N), r.uniform(2, 3, N), r.uniform(0.5, 1.5, N)
    y = 0.5 * t + 8 * p - 3 * c - 2 * w + r.normal(0, 0.5, N)
    df = pd.DataFrame({"라인": np.where(np.arange(N) % 2, "A", "B"), "반응온도": t, "압축압력": p,
                       "촉매비율": c, "수분함량": w, "생산효율": y, "등급": np.where(y > np.median(y), "상", "하")})
    if marks:
        df["제외"] = [""] * N
        df.loc[10, "제외"] = "센서오류"
    df.to_excel(path, index=False)
    return df


@pytest.fixture(scope="module")
def two(tmp_path_factory):
    d = tmp_path_factory.mktemp("mc")
    data = d / "d.xlsx"
    df = _data(data, marks=True)
    res = run_tool("ml_train.py", "-f", str(data), "-x", "반응온도,압축압력", "-y", "생산효율")
    return d, df, res["version_dir"]


def test_snapshot_has_rows_and_exclusions(two):
    _, _, vdir = two
    snap = pd.read_csv(os.path.join(vdir, "model_dataset.csv"), encoding="cp949")
    assert list(snap["원본행"][:3]) == [2, 3, 4]                       # Excel rows (header is row 1)
    assert snap.loc[snap["원본행"] == 12, "학습제외_생산효율"].item() == 1   # '센서오류' on data row 10 = Excel row 12


def test_inline_prediction_has_map_check(two):
    _, df, vdir = two
    res = run_tool("ml_predict.py", "-m", vdir, "-i", "반응온도=180,압축압력=3")
    ps = res["predictions_summary"]["생산효율"]
    mc = ps["map_check"][0]
    assert mc["method"].startswith("둘러싼 실측 3점") and len(mc["basis"]) == 3
    assert all(b["row"] >= 2 and b["row"] != 12 for b in mc["basis"])  # Excel rows; the excluded row is never used
    assert mc["diff"] == pytest.approx(ps["predictions"][0] - mc["value"], abs=1e-3)
    assert not res["map_check_warning"] and ps["map_check_keys"] == ["반응온도", "압축압력"]
    assert "실측 비교값" in res["agent_directive"]


def test_file_prediction_columns_and_extrapolation(two, tmp_path):
    _, _, vdir = two
    new = tmp_path / "new.csv"
    pd.DataFrame({"반응온도": [180, 260, None], "압축압력": [3, 3, 3]}).to_csv(new, index=False)
    res = run_tool("ml_predict.py", "-m", vdir, "-f", str(new))
    out = pd.read_csv(res["output_file"], encoding="cp949")
    assert {"map_생산효율", "map_diff_생산효율", "map_방식_생산효율"} <= set(out.columns)
    assert out["map_방식_생산효율"][1].endswith("[외삽]") and out["map_방식_생산효율"][2].startswith("계산 불가")
    assert out["map_diff_생산효율"][0] == pytest.approx(out["pred_생산효율"][0] - out["map_생산효율"][0], abs=1e-3)
    assert not res["map_check_warning"]                                  # extrapolated comparisons never warn


def test_warning_when_measured_data_disagrees(two, tmp_path):
    _, _, vdir = two
    v2 = tmp_path / "v_tampered"
    shutil.copytree(vdir, v2)
    snap_path = v2 / "model_dataset.csv"
    snap = pd.read_csv(snap_path, encoding="cp949")
    snap["생산효율"] += 10                                                # measured data now 10 above the model
    snap.to_csv(snap_path, index=False, encoding="cp949")
    res = run_tool("ml_predict.py", "-m", str(v2), "-i", "반응온도=180,압축압력=3")
    assert res["map_check_warning"] and "90% 예측 범위 밖" in res["map_check_warnings"][0]
    assert res["predictions_summary"]["생산효율"]["map_check"][0]["outside_interval"]
    assert "실측 비교 경고" in res["preview"]


def test_old_snapshot_and_missing_snapshot(two, tmp_path):
    _, _, vdir = two
    old = tmp_path / "v_old"
    shutil.copytree(vdir, old)
    snap = pd.read_csv(old / "model_dataset.csv", encoding="cp949").drop(columns=["원본행", "학습제외_생산효율"])
    snap.to_csv(old / "model_dataset.csv", index=False, encoding="cp949")
    res = run_tool("ml_predict.py", "-m", str(old), "-i", "반응온도=180,압축압력=3")     # snapshot from before 2.7.0
    assert "map_check" not in res["predictions_summary"]["생산효율"] and "다시 학습" in res["map_check_notes"][0]

    os.remove(old / "model_dataset.csv")
    res = run_tool("ml_predict.py", "-m", str(old), "-i", "반응온도=180,압축압력=3")
    assert "map_check" not in res["predictions_summary"]["생산효율"] and "model_dataset.csv" in res["map_check_notes"][0]
    assert res["predictions_summary"]["생산효율"]["predictions"]           # prediction itself unaffected


def test_many_inputs_use_nearest_rows_and_category(tmp_path):
    data = tmp_path / "d.xlsx"
    _data(data)
    res = run_tool("ml_train.py", "-f", str(data), "-x", "반응온도,압축압력,촉매비율,수분함량,라인", "-y", "생산효율")
    out = run_tool("ml_predict.py", "-m", res["version_dir"], "-i", "반응온도=180,압축압력=3,촉매비율=2.5,수분함량=1,라인=A")
    mc = out["predictions_summary"]["생산효율"]["map_check"][0]
    assert mc["method"].startswith("가까운 실측") and 1 <= len(mc["basis"]) <= 5
    assert sum(b["weight"] for b in mc["basis"]) == pytest.approx(1.0, abs=1e-4)
    assert all(b["row"] % 2 == 1 for b in mc["basis"])                  # 라인 A = odd data rows = odd Excel rows (row = i + 2)


def test_classification_has_no_map_check_and_standalone(two, tmp_path):
    d, _, vdir = two
    cls = run_tool("ml_train.py", "-f", str(d / "d.xlsx"), "-x", "반응온도,압축압력", "-y", "등급", "--task", "classification")
    res = run_tool("ml_predict.py", "-m", cls["version_dir"], "-i", "반응온도=180,압축압력=3")
    assert "map_check" not in res["predictions_summary"]["등급"] and not res["map_check_warning"]

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    shutil.copy(os.path.join(KIT, "ml_predict.py"), deploy / "ml_predict.py")
    shutil.copytree(vdir, deploy / "v1")
    import subprocess
    import json
    proc = subprocess.run([sys.executable, str(deploy / "ml_predict.py"), "-m", str(deploy / "v1"), "-i", "반응온도=180,압축압력=3"],
                          capture_output=True, text=True, encoding="utf-8", cwd=str(deploy))
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["status"] == "ok" and payload["predictions_summary"]["생산효율"]["map_check"][0]["value"] is not None
