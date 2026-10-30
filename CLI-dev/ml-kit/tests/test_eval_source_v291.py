# -*- coding: utf-8 -*-
"""
2.9.1 regression (실기 2026-10-30): a derived feature whose source column is NOT in -x
(e.g. --eval "A상한 = clip(A, -1e12, 250)" with A left out of -x) trained fine but every prediction failed,
because the model did not record that the user must still provide A. Now the source is recorded
(input_columns_required), kept in model_dataset.csv and in feature_stats, and used by predict/find/export.
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "CLI", "ml-kit")  # 실행 파일은 CLI\ml-kit
sys.path.insert(0, HERE)
sys.path.insert(0, KIT)
from test_cli_smoke import run_tool, run_fail  # noqa: E402


@pytest.fixture(scope="module")
def capped(tmp_path_factory):
    d = tmp_path_factory.mktemp("cap")
    r = np.random.default_rng(9)
    n = 300
    df = pd.DataFrame({"온도(°C)": r.uniform(200, 300, n), "압력": r.uniform(1, 3, n)})
    df["효율"] = 0.3 * np.minimum(df["온도(°C)"], 250) + 5 * df["압력"] + r.normal(0, 0.2, n)
    path = d / "c.csv"
    df.to_csv(path, index=False)
    res = run_tool("ml_train.py", "-f", str(path), "-x", "압력", "--eval", "온도상한 = clip(온도, -1e12, 250)", "-y", "효율")
    return d, res["version_dir"]


def test_source_column_is_recorded(capped):
    _, vdir = capped
    meta = json.load(open(os.path.join(vdir, "model_효율.json"), encoding="utf-8"))
    assert meta["input_columns_required"] == ["압력", "온도(°C)"] and "온도(°C)" in meta["feature_stats"]
    snap = pd.read_csv(os.path.join(vdir, "model_dataset.csv"), encoding="cp949")
    assert "온도(°C)" in snap.columns and "온도상한" in snap.columns


def test_prediction_uses_source_and_caps(capped):
    _, vdir = capped
    hi = run_tool("ml_predict.py", "-m", vdir, "-i", "온도=280,압력=2")["predictions_summary"]["효율"]["predictions"][0]
    cap = run_tool("ml_predict.py", "-m", vdir, "-i", "온도=250,압력=2")["predictions_summary"]["효율"]["predictions"][0]
    assert hi == pytest.approx(cap, abs=1e-6)                                   # above 250 is treated as 250
    miss = run_fail("ml_predict.py", "-m", vdir, "-i", "압력=2")
    assert "'온도(°C)'" in miss["message"] and "원본 입력" in miss["message"]


def test_find_and_export_work_on_the_source(capped, tmp_path):
    _, vdir = capped
    f = run_tool("ml_predict.py", "-m", vdir, "--find", "효율=80", "--vary", "온도", "-i", "압력=2")
    assert f["count"] >= 1 and abs(f["solutions"][0]["온도(°C)"] - (80 - 10) / 0.3) < 2
    e = run_tool("ml_export.py", "-m", vdir, "--inputs", "온도,압력", "--save", str(tmp_path / "c.xlsx"))
    assert e["targets"]["효율"]["inputs"] == ["온도(°C)", "압력"]
