# -*- coding: utf-8 -*-
"""
End-to-end CLI contract test: train -> predict -> report.

Locks the Agent-Computer Interface: each tool must exit 0 and print exactly
one JSON line on stdout with "status": "ok". Run before and after every
optimization so behavior changes are caught.
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "ml_kit")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_sample import make_sample  # noqa: E402

FEATURES = "반응온도(°C),소비전력(kW),압축압력(bar),촉매비율(wt%),수분함량(%)"
TARGET = "생산효율(%)"


def run_tool(script, *args):
    proc = subprocess.run(
        [sys.executable, os.path.join(KIT, script), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=600,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert proc.returncode == 0, f"{script} failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert len(lines) == 1, f"{script} must print exactly 1 JSON line, got {len(lines)}:\n{proc.stdout}"
    payload = json.loads(lines[0])
    assert payload.get("status") == "ok", payload
    return payload


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    work = tmp_path_factory.mktemp("mlkit")
    data = make_sample(str(work / "sample.csv"))
    payload = run_tool(
        "ml_train.py", "-f", data, "-x", FEATURES, "-y", TARGET,
        "--desc", "smoke test", "--tag", "baseline",
        "--eval", "온도전력비 = 반응온도(°C) / (소비전력(kW) + 1e-6)",
    )
    return work, data, payload


def test_train_creates_version(trained):
    work, _, _ = trained
    data_root = work / "sample_ml_data"
    assert (data_root / "history.jsonl").is_file()
    assert (data_root / "history.json").is_file()
    assert (data_root / "v1").is_dir()
    assert not any(p.name.startswith(".tmp_") for p in data_root.iterdir())


def test_predict_inline(trained):
    work, _, _ = trained
    payload = run_tool(
        "ml_predict.py", "-m", str(work / "sample_ml_data" / "v1"),
        "-i", "반응온도(°C)=240,소비전력(kW)=65,압축압력(bar)=3,촉매비율(wt%)=0.8,수분함량(%)=20",
    )
    assert "agent_directive" in payload


def test_predict_batch(trained):
    work, data, _ = trained
    out = work / "pred.csv"
    run_tool("ml_predict.py", "-m", str(work / "sample_ml_data" / "v1"), "-f", data, "-o", str(out))
    assert out.is_file()


def test_report(trained):
    work, _, _ = trained
    out = work / "report.docx"
    run_tool("ml_report.py", "-d", str(work / "sample_ml_data"), "-t", TARGET, "-o", str(out))
    assert out.is_file()
