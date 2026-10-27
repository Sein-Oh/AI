# -*- coding: utf-8 -*-
"""Unit tests for ml_common shared helpers."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ml_common as mc  # noqa: E402


def test_coerce_numeric_object_and_str_dtypes():
    for dtype in ("object", "string"):
        s = pd.Series(["1,234.5", "-", "N/A", " 7 ", None], dtype=dtype)
        out = mc.coerce_numeric(s)
        assert out.iloc[0] == 1234.5 and out.iloc[3] == 7.0
        assert out.iloc[[1, 2, 4]].isna().all()


def test_compile_formula_alias_and_canonical():
    cols = ["반응온도(°C)", "소비전력(kW)", "log(x)"]
    tok, mapping, canon = mc.compile_formula("log(소비전력) / 반응온도(°C)", cols)
    assert canon == "log(소비전력(kW)) / 반응온도(°C)"
    assert set(mapping.values()) == {"소비전력(kW)", "반응온도(°C)"}


def test_ambiguous_alias_not_resolved():
    with pytest.raises(mc.InputError):
        mc.resolve_column_names(["온도"], ["온도(°C)", "온도(K)"], "피처")


def test_eval_blocks_attribute_access():
    df = pd.DataFrame({"a": [1.0, 2.0]})
    with pytest.raises(mc.InputError):
        mc.apply_eval_expressions(df, ["b = a.__class__"])


def test_json_safe_nan_and_numpy():
    assert mc.dumps_json({"a": np.nan, "b": np.int64(3), "c": [np.float32(1.5)]}) == '{"a": null, "b": 3, "c": [1.5]}'


def test_read_text_file_encodings(tmp_path):
    for enc in ("utf-8", "utf-8-sig", "utf-16", "cp949"):
        p = tmp_path / f"t_{enc}.txt"
        p.write_text("반응온도(°C)", encoding=enc)
        assert mc.read_text_file(str(p)) == "반응온도(°C)"
