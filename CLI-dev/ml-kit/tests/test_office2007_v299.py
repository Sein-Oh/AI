# -*- coding: utf-8 -*-
"""
2.9.9: found on a home PC with Office 2007.
- The report must follow the WordprocessingML schema order and names: Word 2007 refuses w:start/w:end and wrong order.
- The IDW measured-data comparison must not convert the snapshot columns again for every input row (20,000 rows: > 15 min).
"""
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "CLI", "ml-kit")  # 실행 파일은 CLI\ml-kit
sys.path.insert(0, HERE)
sys.path.insert(0, KIT)
import ml_predict  # noqa: E402
import ml_report  # noqa: E402
from docx import Document  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from make_sample import make_sample  # noqa: E402
from test_cli_smoke import run_tool  # noqa: E402


def _names(el):
    return [c.tag.rsplit("}", 1)[-1] for c in el]


def _in_order(names, order):
    pos = [order.index(n) for n in names]
    return pos == sorted(pos)


def test_report_docx_follows_schema_for_word_2007(tmp_path):
    data = tmp_path / "d.csv"
    make_sample(str(data))
    tr = run_tool("ml_train.py", "-f", str(data), "-x", "반응온도,촉매비율,수분함량", "-y", "생산효율")
    rep = run_tool("ml_report.py", "-d", tr["data_root"], "--out", str(tmp_path / "r.docx"))
    body = Document(rep["report_file"]).element.body

    assert not list(body.iter(qn("w:start"))) and not list(body.iter(qn("w:end")))   # Word 2010+ names
    tcprs = list(body.iter(qn("w:tcPr")))
    assert tcprs and list(body.iter(qn("w:tcMar"))) and list(body.iter(qn("w:tcBorders")))
    for tcpr in tcprs:
        assert _in_order(_names(tcpr), ml_report._TCPR_ORDER), _names(tcpr)
    for tblpr in body.iter(qn("w:tblPr")):
        assert _in_order(_names(tblpr), ml_report._TBLPR_ORDER), _names(tblpr)
    for ppr in body.iter(qn("w:pPr")):
        assert _in_order(_names(ppr), ml_report._PPR_ORDER), _names(ppr)
    for box in list(body.iter(qn("w:tcMar"))) + list(body.iter(qn("w:tcBorders"))):
        assert _names(box) == ["top", "left", "bottom", "right"]


def _snapshot(version_dir, n=3000):
    r = np.random.default_rng(1)
    df = pd.DataFrame(r.uniform(0, 1, (n, 4)), columns=list("abcd"))
    df["y"] = df.sum(axis=1)
    df["원본행"] = np.arange(2, n + 2)
    df.to_csv(os.path.join(version_dir, "model_dataset.csv"), index=False, encoding="cp949")
    return df


def test_idw_comparison_converts_snapshot_once_and_keeps_values(tmp_path, monkeypatch):
    df = _snapshot(str(tmp_path))
    meta = {"feature_schema": {}, "input_columns_required": list("abcd")}
    monkeypatch.setattr(ml_predict, "model_raw_inputs", lambda m: list("abcd"))
    rows = df[list("abcd")].iloc[:2000].reset_index(drop=True) + 0.001

    calls = {"n": 0}
    real = ml_predict.coerce_numeric

    def counting(s):
        calls["n"] += 1
        return real(s)

    monkeypatch.setattr(ml_predict, "coerce_numeric", counting)
    t0 = time.time()
    out = ml_predict.compare_with_measured(meta, "y", str(tmp_path), rows, {})
    took = time.time() - t0

    assert calls["n"] < 30                                            # not once per input row
    assert took < 20
    assert np.isfinite(out["values"]).all() and len(out["basis"][0]) == 5

    # same answer as computing the first row by hand
    x = rows.iloc[0].to_numpy()
    K = df[list("abcd")].to_numpy()
    span = K.max(axis=0) - K.min(axis=0)
    d = np.sqrt((((K - x) / span) ** 2).sum(axis=1))
    near = np.argsort(d, kind="stable")[:5]
    w = 1 / d[near]
    assert abs(out["values"][0] - float((w / w.sum()) @ df["y"].to_numpy()[near])) < 1e-9
