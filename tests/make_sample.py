# -*- coding: utf-8 -*-
"""Deterministic synthetic process dataset for ml_kit smoke/regression tests."""
import sys

import numpy as np
import pandas as pd


def make_sample(path: str, n: int = 120, seed: int = 0) -> str:
    rng = np.random.default_rng(seed)
    temp = rng.uniform(200, 280, n)
    power = rng.uniform(40, 90, n)
    pressure = rng.uniform(1, 5, n)
    catalyst = rng.uniform(0.2, 1.5, n)
    water = rng.uniform(10, 30, n)
    eff = 0.2 * temp + 8 * catalyst - 0.5 * water + 0.1 * power + rng.normal(0, 1.5, n)
    df = pd.DataFrame({
        "반응온도(°C)": temp.round(2),
        "소비전력(kW)": power.round(2),
        "압축압력(bar)": pressure.round(3),
        "촉매비율(wt%)": catalyst.round(3),
        "수분함량(%)": water.round(2),
        "생산효율(%)": eff.round(3),
    })
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


if __name__ == "__main__":
    make_sample(sys.argv[1] if len(sys.argv) > 1 else "sample.csv")
