# -*- coding: utf-8 -*-
"""Classification (--task classification) train -> predict contract tests."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_sample import make_class_sample  # noqa: E402
from test_cli_smoke import run_tool, run_fail, run_raw  # noqa: E402

FEATS = "반응온도,촉매비율,수분함량"


@pytest.fixture(scope="module")
def cls_data(tmp_path_factory):
    work = tmp_path_factory.mktemp("cls")
    return work, make_class_sample(str(work / "proc.csv"))


@pytest.fixture(scope="module")
def multiclass(cls_data):
    work, data = cls_data
    payload = run_tool("ml_train.py", "-f", data, "-x", FEATS, "-y", "품질등급",
                       "--task", "classification", "--desc", "등급 분류", "--tag", "cls_base")
    return work, data, payload


def test_multiclass_train_contract(multiclass):
    work, _, payload = multiclass
    assert payload["task"] == "classification"
    assert payload["primary_metric"] == "val_f1_macro"
    assert 0 < payload["mean_val_score"] <= 1
    assert "mean_val_r2" not in payload
    meta = json.loads((work / "proc_ml_data" / "v1" / "model_품질등급.json").read_text(encoding="utf-8"))
    assert meta["task"] == "classification" and meta["classes"] == ["A등급", "B등급", "C등급"]
    lb = json.loads((work / "proc_ml_data" / "v1" / "leaderboard.json").read_text(encoding="utf-8"))
    champ = lb["targets"]["품질등급"]["champion"]
    assert len(lb["targets"]["품질등급"]["leaderboard"]) == 5
    assert champ["confusion_matrix"]["labels"] == ["A등급", "B등급", "C등급"]
    assert set(champ["per_class"]) == {"A등급", "B등급", "C등급"}


def test_multiclass_predict_inline_probabilities(multiclass):
    work, _, _ = multiclass
    payload = run_tool("ml_predict.py", "-m", str(work / "proc_ml_data" / "v1"),
                       "-i", "반응온도=250,촉매비율=1.0,수분함량=18")
    ps = payload["predictions_summary"]["품질등급"]
    assert ps["task"] == "classification"
    assert ps["predictions"][0] in ps["classes"]
    assert abs(sum(ps["probabilities"][0].values()) - 1.0) < 1e-3
    assert "low_confidence_warning" in payload


def test_multiclass_predict_batch_columns(multiclass):
    import pandas as pd
    work, data, _ = multiclass
    out = work / "pred.csv"
    run_tool("ml_predict.py", "-m", str(work / "proc_ml_data" / "v1"), "-f", data, "-o", str(out))
    df = pd.read_csv(out, encoding="cp949")
    for col in ["pred_품질등급", "conf_품질등급", "proba_품질등급_A등급", "proba_품질등급_C등급"]:
        assert col in df.columns
    assert (df["pred_품질등급"] == df["품질등급"]).mean() > 0.6


def test_binary_integer_labels(cls_data):
    work, data = cls_data
    payload = run_tool("ml_train.py", "-f", data, "-x", FEATS, "-y", "불량여부", "--task", "classification")
    meta = json.loads((work / "proc_ml_data" / payload["version"] / "model_불량여부.json").read_text(encoding="utf-8"))
    assert meta["classes"] == ["0", "1"]  # integer labels normalized to stable strings
    lb = json.loads((work / "proc_ml_data" / payload["version"] / "leaderboard.json").read_text(encoding="utf-8"))
    assert lb["targets"]["불량여부"]["champion"]["roc_auc"] is not None


def test_imbalanced_uses_balanced_weights(tmp_path):
    data = make_class_sample(str(tmp_path / "imb.csv"), n=200, imbalanced=True)
    proc, payload = run_raw("ml_train.py", "-f", data, "-x", FEATS, "-y", "품질등급", "--task", "classification")
    assert payload["status"] == "ok"
    assert "class_weight='balanced'" in proc.stderr
    assert any("불균형" in r for r in payload["recommendations"])


def test_string_target_without_task_hints_classification(cls_data):
    _, data = cls_data
    payload = run_fail("ml_train.py", "-f", data, "-x", FEATS, "-y", "품질등급")
    assert "--task classification" in payload["message"]


def test_single_sample_class_rejected(tmp_path):
    import pandas as pd
    p = tmp_path / "rare.csv"
    make_class_sample(str(p))
    df = pd.read_csv(p, encoding="utf-8-sig")
    df.loc[0, "품질등급"] = "D등급"
    df.to_csv(p, index=False, encoding="utf-8-sig")
    payload = run_fail("ml_train.py", "-f", str(p), "-x", FEATS, "-y", "품질등급", "--task", "classification")
    assert "D등급" in payload["message"]


def test_history_mixed_tasks_compare_within_task(multiclass):
    work, data, _ = multiclass
    run_tool("ml_train.py", "-f", data, "-x", "반응온도,촉매비율", "-y", "수분함량", "-v", "v9")  # regression on same ledger
    hist = run_tool("ml_train.py", "-f", data, "--history")
    tasks = {r["version"]: r["task"] for r in hist["records"]}
    assert tasks["v1"] == "classification" and tasks["v9"] == "regression"
    assert set(hist["best_by_task"]) == {"classification", "regression"}


def test_report_rejects_classification(multiclass):
    pytest.importorskip("docx")
    work, _, _ = multiclass
    payload = run_fail("ml_report.py", "-d", str(work / "proc_ml_data"), "-t", "품질등급")
    assert "분류" in payload["message"]


def test_pre_2_0_model_metadata_is_regression(tmp_path):
    """Models trained before 2.0.0 have no 'task' key and must still predict as regression."""
    from make_sample import make_sample
    data = make_sample(str(tmp_path / "old.csv"))
    run_tool("ml_train.py", "-f", data, "-x", "반응온도,소비전력,압축압력,촉매비율,수분함량", "-y", "생산효율")
    meta_p = tmp_path / "old_ml_data" / "v1" / "model_생산효율(%).json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    for k in ("task", "primary_metric", "val_score"):
        meta.pop(k)
    meta_p.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    payload = run_tool("ml_predict.py", "-m", str(tmp_path / "old_ml_data" / "v1"),
                       "-i", "반응온도=240,소비전력=65,압축압력=3,촉매비율=0.8,수분함량=20")
    assert payload["predictions_summary"]["생산효율(%)"]["task"] == "regression"


def test_delta_compares_same_targets_only(tmp_path):
    """A new target in the same ledger starts from 'base' instead of comparing with another target."""
    data = make_class_sample(str(tmp_path / "dt.csv"))
    run_tool("ml_train.py", "-f", data, "-x", FEATS, "-y", "불량여부", "--task", "classification")
    second = run_tool("ml_train.py", "-f", data, "-x", FEATS, "-y", "품질등급", "--task", "classification")
    assert second["delta_score"] == "base" and second["is_best"] is True
    third = run_tool("ml_train.py", "-f", data, "-x", FEATS, "-y", "품질등급", "--task", "classification", "--seed", "7")
    assert isinstance(third["delta_score"], float)
