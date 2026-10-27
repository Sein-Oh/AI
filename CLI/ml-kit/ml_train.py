# -*- coding: utf-8 -*-
"""
ml_train.py - Autonomous Regression / Classification Machine Learning Engine with
Collision-Free AST Feature Engineering, 5-Model Competitive Benchmark,
Atomic Version Packaging, and Single Source of Truth (SSOT) Ledger.

--task regression (default) : champion by Out-of-Fold R2
--task classification       : champion by Out-of-Fold Macro-F1 (Stratified K-Fold)

Shared runtime (data loading, --eval engine, CLI protocol) is imported from ml_predict.py.

Designed for lightweight 26B-30B LLM agents with 1-turn declarative execution.
100% Standalone: Pure Python, Scikit-learn, Pandas, NumPy, and Joblib.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ml_predict import (  # noqa: E402  shared runtime lives in ml_predict.py
    setup_console, emit_json_response, dumps_json, run_cli, JsonArgumentParser,
    InputError, sanitize_filename, normalize_version, warn_long_path,
    read_text_file, load_json_file, resolve_column_names, coerce_numeric,
    load_data_file as _load_table, apply_eval_expressions,
    parse_datetime, normalize_category, prepare_features, date_part_column, input_column_owner, DATE_PARTS,
    strip_unit,
    retry_fs, remove_tree, atomic_write_text, write_csv_excel_compatible,
)

setup_console()

import re
import json
import time
import argparse
import warnings
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd
import joblib

import sklearn
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    r2_score, mean_absolute_error, root_mean_squared_error,
    f1_score, accuracy_score, balanced_accuracy_score, roc_auc_score,
    confusion_matrix, classification_report, make_scorer,
)
from sklearn.inspection import permutation_importance
from sklearn.exceptions import ConvergenceWarning

# 5 Core Regression Algorithms
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor, ExtraTreesRegressor
from sklearn.linear_model import RidgeCV, ElasticNetCV
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.base import clone

# 5 Core Classification Algorithms (--task classification)
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, ExtraTreesClassifier
from sklearn.linear_model import LogisticRegressionCV
from sklearn.neighbors import KNeighborsClassifier

TASK_REGRESSION = "regression"
TASK_CLASSIFICATION = "classification"
PRIMARY_METRIC = {TASK_REGRESSION: "val_r2", TASK_CLASSIFICATION: "val_f1_macro"}
METRIC_LABEL = {TASK_REGRESSION: "Val R2", TASK_CLASSIFICATION: "Val Macro-F1"}

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=ConvergenceWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


# ==============================================================================
# 1. Console Progress & Formatting (Clean Terminal Principle - No Emojis)
# ==============================================================================

def log_progress(percent: int, message: str) -> None:
    """
    Outputs real-time progress to stderr with immediate flush.
    Ensures newline-based streaming in agent environments (OpenCode, CI, Subprocess)
    to prevent idle stream timeouts while maintaining clean formatting.
    """
    bar_len = 20
    filled = int(bar_len * percent / 100)
    bar = "=" * filled + "-" * (bar_len - filled)
    
    # In agent/piped execution (OpenCode, etc.), output with newline so stream readers don't block
    is_interactive = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
    if is_interactive:
        sys.stderr.write(f"\r[PROGRESS {percent:3d}%] [{bar}] {message}")
        if percent >= 100:
            sys.stderr.write("\n")
    else:
        sys.stderr.write(f"[PROGRESS {percent:3d}%] [{bar}] {message}\n")
    
    sys.stderr.flush()


# ==============================================================================
# 2. Bulletproof AST Formula Sandbox & Feature Engineering (--eval)
# ==============================================================================

def run_safe_eval(df: pd.DataFrame, eval_str: str, target_cols: List[str]) -> Tuple[pd.DataFrame, List[str], List[str]]:
    """
    Safely evaluates semicolon-separated derived feature formulas (--eval).
    Column names may be written in full ('반응온도(°C)') or without the unit suffix
    ('반응온도') when unique. Stored expressions always use full column names so that
    ml_predict.py replays them exactly. Target references are blocked (leakage guard).
    """
    if not eval_str or not eval_str.strip():
        return df, [], []
    expressions = [e.strip() for e in eval_str.split(";") if e.strip()]
    return apply_eval_expressions(df, expressions, target_cols=target_cols, strict=True)


# ==============================================================================
# 3. Robust Data Loader & Layout Parser with Auto-Header Sniffing
# ==============================================================================

def parse_feature_or_target_list(input_arg: str, param_name: str = "features") -> List[str]:
    """
    Parses comma-separated string OR file path (.txt, .json, .csv).
    If a valid file path is provided, reads feature/target names:
      - .json: list ["A", "B"] or dict {"features": [...], "targets": [...]}
      - .txt / .csv: line-by-line or comma-separated, ignoring empty lines and # comments
    If not a file, splits the string by comma.
    """
    if not input_arg or not str(input_arg).strip():
        return []

    stripped = str(input_arg).strip()

    # 1. File Path Mode
    if os.path.isfile(stripped):
        ext = os.path.splitext(stripped)[1].lower()
        items: List[str] = []

        if ext == ".json":
            data = load_json_file(stripped)
            if isinstance(data, list):
                items = [str(x).strip() for x in data if str(x).strip()]
            elif isinstance(data, dict) and data:
                cand = (
                    data.get(param_name)
                    or data.get("features")
                    or data.get("targets")
                    or data.get("columns")
                    or list(data.values())[0]
                )
                if isinstance(cand, list):
                    items = [str(x).strip() for x in cand if str(x).strip()]
        else:
            # .txt, .csv, generic text files (UTF-8/UTF-16/CP949 written by Notepad, PowerShell, Excel)
            for line in read_text_file(stripped).splitlines():
                line_str = line.strip()
                if not line_str or line_str.startswith("#"):
                    continue
                # Split line by comma in case multiple features are on the same line
                for part in line_str.split(","):
                    p = part.strip()
                    if p and not p.startswith("#"):
                        items.append(p)

        if not items:
            raise InputError(f"지정하신 파일 '{stripped}'에서 유효한 컬럼명을 추출할 수 없습니다.")
        return items

    # 2. In-line Comma-separated string mode
    return [col.strip() for col in stripped.split(",") if col.strip()]


def load_data_file(
    file_path: str,
    header_row: Optional[int] = None,
    unit_row: Optional[int] = None,
    data_row: Optional[int] = None
) -> Tuple[pd.DataFrame, str]:
    """
    Loads tabular data from CSV (multi-encoding) or Excel (.xlsx) via the shared loader
    (identical parsing in ml_predict.py). Returns (dataframe, file_name).
    """
    df_data = _load_table(file_path, header_row=header_row, unit_row=unit_row, data_row=data_row)
    return df_data, os.path.basename(file_path)


# ==============================================================================
# 4. Fail-Fast Validation & Type Sanitization
# ==============================================================================

def validate_and_sanitize_data(
    df: pd.DataFrame,
    feature_names: List[str],
    target_names: List[str],
    dtypes_arg: Optional[str] = None,
    task: str = "regression"
) -> Tuple[pd.DataFrame, List[str], List[str], Dict[str, str]]:
    """
    Validates explicit feature (X) and target (Y) columns.
    - task='classification': targets keep their labels (normalized to strings), not coerced to float.
    - Exact names first, then unique unit-less aliases ('생산효율' -> '생산효율(%)').
    - Fail-fast with suggestions and the available columns list if spelling fails.
    - Converts every X/Y column to float regardless of pandas version (object / str dtype),
      stripping thousands separators and placeholder strings ('-', 'N/A', '미측정', ...).
    Feature columns are NOT converted here (see infer_feature_schema).
    Returns (df_clean, features, targets, aliases_applied).
    """
    all_available = [str(c) for c in df.columns]

    feature_names, feat_alias = resolve_column_names(feature_names, all_available, "피처(-x)")
    target_names, tgt_alias = resolve_column_names(target_names, all_available, "타겟(-y)")
    feature_names = list(dict.fromkeys(feature_names))
    target_names = list(dict.fromkeys(target_names))

    # Data Leakage Check: Targets in Features
    overlap = [t for t in target_names if t in set(feature_names)]
    if overlap:
        raise InputError(
            f"[DATA LEAKAGE DETECTED] 타겟 변수 '{', '.join(overlap)}'이(가) 피처(-x) 목록에 포함되어 있습니다. "
            f"종속변수는 독립변수로 사용될 수 없습니다."
        )

    df_clean = df.copy()

    # Manual dtypes override if provided (e.g., "colA:float,colB:str")
    if dtypes_arg:
        for pair in dtypes_arg.split(","):
            if ":" in pair:
                c_name, c_type = pair.split(":", 1)
                c_name = c_name.strip()
                c_type = c_type.strip().lower()
                if c_name in df_clean.columns:
                    try:
                        if c_type in ["float", "float64"]:
                            df_clean[c_name] = coerce_numeric(df_clean[c_name]).astype(float)
                        elif c_type in ["int", "int64"]:
                            df_clean[c_name] = coerce_numeric(df_clean[c_name]).fillna(0).astype(int)
                        elif c_type in ["str", "object"]:
                            df_clean[c_name] = df_clean[c_name].astype(str)
                        elif c_type in ["datetime", "date"]:
                            df_clean[c_name] = pd.to_datetime(df_clean[c_name], errors="coerce")
                    except Exception as e:
                        sys.stderr.write(f"[WARN] 타입 변환 실패 ({c_name} -> {c_type}): {e}\n")

    # Targets: numeric for regression (pandas 2 'object' / pandas 3 'str' safe), labels for classification.
    # Features keep their raw values here; infer_feature_schema() decides numeric/categorical/datetime.
    numeric_cols = target_names if task == TASK_REGRESSION else []
    for col in numeric_cols:
        df_clean[col] = coerce_numeric(df_clean[col])

    if task == TASK_CLASSIFICATION:
        for col in target_names:
            df_clean[col] = normalize_labels(df_clean[col])

    all_nan = [c for c in numeric_cols if df_clean[c].notna().sum() == 0]
    if all_nan:
        raise InputError(
            f"컬럼 {all_nan}에 숫자로 변환 가능한 값이 하나도 없습니다. 헤더/데이터 시작 행(--header-row, --data-row)을 확인하십시오."
            + (" 타겟이 범주(라벨)라면 --task classification을 지정하십시오." if any(c in target_names for c in all_nan) else "")
        )
    empty_targets = [c for c in target_names if df_clean[c].notna().sum() == 0]
    if empty_targets:
        raise InputError(f"타겟 컬럼 {empty_targets}에 유효한 값이 없습니다.")

    return df_clean, feature_names, target_names, {**feat_alias, **tgt_alias}


# ==============================================================================
# 4-B. Feature Type Inference (numeric / categorical / datetime)
# ==============================================================================

MAX_CATEGORIES = 200


def infer_feature_schema(
    df: pd.DataFrame,
    feature_names: List[str],
    derived_features: List[str],
    dtypes_arg: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Decides how each feature enters the model, without LLM involvement:
    - numeric     : >= 90% of non-empty values parse as numbers (thousands separators allowed)
    - datetime    : Excel dates or >= 90% 'YYYY-MM-DD[ HH:MM]' strings -> year/month/day/dayofweek/hour
    - categorical : everything else (one-hot encoded). ID-like columns are rejected.
    --dtypes 'col:str' forces categorical, 'col:datetime' forces datetime, 'col:float' forces numeric.
    """
    forced: Dict[str, str] = {}
    if dtypes_arg:
        for pair in dtypes_arg.split(","):
            if ":" in pair:
                c, t = pair.split(":", 1)
                t = t.strip().lower()
                kind = ("categorical" if t in ("str", "object", "category", "cat") else
                        "datetime" if t in ("datetime", "date") else
                        "numeric" if t in ("float", "float64", "int", "int64", "num") else None)
                if kind:
                    forced[c.strip()] = kind

    numeric: List[str] = []
    categorical: Dict[str, List[str]] = {}
    dates: Dict[str, List[str]] = {}

    for col in feature_names:
        raw = df[col]
        kind = forced.get(col)
        if col in derived_features:
            kind = "numeric"
        if kind is None:
            non_null = raw.notna() & (raw.astype(str).str.strip() != "")
            n = int(non_null.sum())
            is_dt_obj = raw.map(lambda v: isinstance(v, (datetime, pd.Timestamp, np.datetime64)))
            if pd.api.types.is_datetime64_any_dtype(raw) or (n and is_dt_obj.sum() >= 0.9 * n):
                kind = "datetime"  # Excel date cells arrive as datetime objects
            elif n == 0 or pd.api.types.is_numeric_dtype(raw):
                kind = "numeric"
            elif coerce_numeric(raw).notna().sum() >= 0.9 * n:
                kind = "numeric"
            elif parse_datetime(raw).notna().sum() >= 0.9 * n:
                kind = "datetime"
            else:
                kind = "categorical"

        if kind == "numeric":
            numeric.append(col)
        elif kind == "datetime":
            dt = parse_datetime(raw)
            if dt.notna().sum() == 0:
                raise InputError(f"컬럼 '{col}'에서 날짜를 읽을 수 없습니다. 'YYYY-MM-DD' 형식인지 확인하십시오.")
            parts = [pt for pt in DATE_PARTS if getattr(dt.dt, pt).nunique(dropna=True) > 1]
            dates[col] = parts or ["year"]
        else:
            cats = normalize_category(raw)
            uniq = sorted(cats.dropna().unique().tolist())
            n_valid = int(cats.notna().sum())
            if len(uniq) > MAX_CATEGORIES or (len(uniq) > 50 and len(uniq) > 0.5 * max(n_valid, 1)):
                raise InputError(
                    f"피처 '{col}'은(는) 문자형 값의 종류가 {len(uniq)}개로 너무 많아 ID/일련번호로 보입니다. "
                    f"-x 목록에서 제외하십시오. 숫자 컬럼인데 잘못 판별되었다면 --dtypes '{col}:float'를 지정하십시오."
                )
            categorical[col] = uniq
            sys.stderr.write(f"[INFO] 범주형 피처 감지: '{col}' ({len(uniq)}개 범주, 원-핫 인코딩)\n")

    for col, parts in dates.items():
        sys.stderr.write(f"[INFO] 날짜 피처 감지: '{col}' -> {[date_part_column(col, p) for p in parts]}\n")

    input_columns = numeric + [date_part_column(c, p) for c, ps in dates.items() for p in ps] + list(categorical)
    return {"numeric": numeric, "categorical": categorical, "datetime": dates, "input_columns": input_columns}


def build_pipeline(estimator: Any, schema: Dict[str, Any], step_name: str) -> Pipeline:
    """Leakage-free pipeline: numeric -> median impute + scale, categorical -> one-hot (unknown ignored)."""
    num_cols = [c for c in schema["input_columns"] if c not in schema["categorical"]]
    cat_cols = list(schema["categorical"])
    transformers = []
    if num_cols:
        transformers.append(("num", Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]), num_cols))
    if cat_cols:
        transformers.append(("cat", Pipeline([
            ("imputer", SimpleImputer(strategy="constant", fill_value="__missing__")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]), cat_cols))
    pre = ColumnTransformer(transformers, remainder="drop", verbose_feature_names_out=False)
    return Pipeline([("preprocess", pre), (step_name, estimator)])


PERMUTATION_MAX_ROWS = 5000
KNN_MAX_ROWS = 50000


def feature_importance_ranks(
    pipe: Pipeline, X: pd.DataFrame, y: np.ndarray, schema: Dict[str, Any], seed: int, scoring: Optional[str]
) -> List[Dict[str, Any]]:
    """
    Permutation importance on at most PERMUTATION_MAX_ROWS rows (keeps large data fast),
    aggregated back to user-facing columns (date parts are summed into their date column).
    """
    Xs, ys = X, y
    if len(X) > PERMUTATION_MAX_ROWS:
        idx = np.random.default_rng(seed).choice(len(X), PERMUTATION_MAX_ROWS, replace=False)
        Xs, ys = X.iloc[idx], y[idx]
    try:
        res = permutation_importance(pipe, Xs, ys, n_repeats=5, random_state=seed, scoring=scoring)
        raw = np.maximum(res.importances_mean, 0)
    except Exception:
        raw = np.ones(X.shape[1])

    owner = input_column_owner(schema)
    agg: Dict[str, float] = {}
    for col, imp in zip(X.columns, raw):
        agg[owner.get(col, col)] = agg.get(owner.get(col, col), 0.0) + float(imp)
    total = sum(agg.values()) or 1.0
    ranks = [{"feature": f, "importance": round(v, 4), "pct": round(v / total * 100, 1)} for f, v in agg.items()]
    return sorted(ranks, key=lambda r: r["importance"], reverse=True)


def _model_params(pipe: Pipeline) -> Dict[str, Any]:
    """Hyper-parameters chosen by the CV-tuned linear models (for the leaderboard)."""
    est = pipe.steps[-1][1]
    out = {}
    for attr, key in (("alpha_", "alpha"), ("l1_ratio_", "l1_ratio"), ("C_", "C")):
        val = getattr(est, attr, None)
        if val is None:
            continue
        first = np.ravel(np.asarray(val, dtype=object))[0]
        if isinstance(first, (int, float, np.integer, np.floating)):
            out[key] = round(float(first), 6)
    return out


# ==============================================================================
# 5. 5-Model Competitive Regression Pool
# ==============================================================================

LINEAR_ALPHAS = np.logspace(-3, 3, 13)


TREE_SAMPLE_ROWS = 10000


def _bagging_kwargs(n_rows: int) -> Dict[str, Any]:
    """Large data: each tree sees a bootstrap sample of TREE_SAMPLE_ROWS rows (3~5x faster, same accuracy class)."""
    if n_rows > TREE_SAMPLE_ROWS:
        return {"bootstrap": True, "max_samples": TREE_SAMPLE_ROWS / n_rows}
    return {}


def get_regression_models(seed: int = 42, n_rows: int = 0) -> Dict[str, Any]:
    """
    Returns 5 distinct, mathematically diverse regression models:
    1. HistGradientBoostingRegressor (GBDT, non-linear, robust)
    2. RandomForestRegressor (Bagging ensemble, variance reduction)
    3. ExtraTreesRegressor (Extremely randomized trees, tabular smooth)
    4. Ridge (L2 linear; alpha auto-tuned by efficient LOO-CV)
    5. ElasticNet (L1 + L2 linear; alpha / l1_ratio auto-tuned by inner 3-fold CV)
    """
    return {
        "HistGradientBoosting": HistGradientBoostingRegressor(random_state=seed),
        "RandomForest": RandomForestRegressor(n_estimators=100, random_state=seed, n_jobs=-1, **_bagging_kwargs(n_rows)),
        "ExtraTrees": ExtraTreesRegressor(n_estimators=100, random_state=seed, n_jobs=-1, **_bagging_kwargs(n_rows)),
        "Ridge": RidgeCV(alphas=LINEAR_ALPHAS),
        "ElasticNet": ElasticNetCV(l1_ratio=[0.1, 0.5, 0.9], cv=3, max_iter=5000, random_state=seed),
    }


PREDICTION_INTERVAL_LEVEL = 0.90


def train_and_benchmark_models(
    X: pd.DataFrame,
    y_series: pd.Series,
    target_name: str,
    schema: Dict[str, Any],
    seed: int = 42,
    log_offset: int = 20,
    log_weight: int = 50
) -> Tuple[Dict[str, Any], Any, Dict[str, Any]]:
    """
    Performs 5-Fold Leakage-Free Cross-Validation across the 5 models.
    Selects champion model by Out-of-Fold (OOF) R2 score.
    Fits champion model on 100% of data and extracts permutation feature importance.
    Prediction interval: 5%/95% quantiles of the champion's OOF residuals (90% level).
    """
    valid_mask = y_series.notna().values
    row_ids = np.flatnonzero(valid_mask)  # position in the loaded data (reported as 1-based data_row)
    X = X.loc[valid_mask].reset_index(drop=True)
    y = y_series.loc[valid_mask].astype(float).values

    if len(y) < 10:
        raise InputError(f"타겟 '{target_name}'의 유효 학습 샘플 수가 너무 적습니다 ({len(y)}개). 최소 10개 이상 필요합니다.")

    models = get_regression_models(seed=seed, n_rows=int(len(y) * 0.8))
    model_count = len(models)
    # Dynamic K-Fold split: adapts gracefully to small sample sizes (N < 25)
    n_splits = min(5, max(2, len(y) // 3))
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)

    leaderboard = []
    model_oof_map = {}

    for m_idx, (model_name, regressor) in enumerate(models.items()):
        oof_preds = np.zeros(len(y))
        train_r2_list = []
        params = {}

        for fold, (train_idx, val_idx) in enumerate(kf.split(X, y), 1):
            if fold == 1:
                pct = log_offset + int(log_weight * m_idx / model_count)
                log_progress(pct, f"Target '{target_name}' | {model_name} 교차검증 ({n_splits}-fold)...")

            # Leakage-Free Pipeline: fitted ONLY on training fold
            pipe = build_pipeline(clone(regressor), schema, "regressor")
            pipe.fit(X.iloc[train_idx], y[train_idx])
            train_r2_list.append(r2_score(y[train_idx], pipe.predict(X.iloc[train_idx])))
            oof_preds[val_idx] = pipe.predict(X.iloc[val_idx])
            params = _model_params(pipe)
            del pipe  # Explicit memory cleanup per fold

        model_oof_map[model_name] = oof_preds
        val_r2 = float(r2_score(y, oof_preds))
        avg_train_r2 = float(np.mean(train_r2_list))
        entry = {
            "model_name": model_name,
            "val_r2": round(val_r2, 4),
            "train_r2": round(avg_train_r2, 4),
            "overfit_gap": round(avg_train_r2 - val_r2, 4),
            "mae": round(float(mean_absolute_error(y, oof_preds)), 4),
            "rmse": round(float(root_mean_squared_error(y, oof_preds)), 4)
        }
        if params:
            entry["params"] = params
        leaderboard.append(entry)

    # Sort leaderboard by val_r2 descending
    leaderboard.sort(key=lambda item: item["val_r2"], reverse=True)
    champion_entry = leaderboard[0]
    champion_name = champion_entry["model_name"]

    # Mark rank and champion flag
    for rank, entry in enumerate(leaderboard, 1):
        entry["rank"] = rank
        entry["is_champion"] = (rank == 1)

    # Residual diagnostics of Champion Model (OOF -> honest error estimate)
    residuals = y - model_oof_map[champion_name]
    residual_skew = round(float(pd.Series(residuals).skew()), 4)
    alpha = (1 - PREDICTION_INTERVAL_LEVEL) / 2
    interval = {
        "level": PREDICTION_INTERVAL_LEVEL,
        "residual_lower": round(float(np.quantile(residuals, alpha)), 6),
        "residual_upper": round(float(np.quantile(residuals, 1 - alpha)), 6),
        "method": "champion OOF residual quantiles (constant width)",
    }

    # Fit Champion Model on 100% of data
    log_progress(log_offset + log_weight - 4, f"Target '{target_name}' | 1위 챔피언({champion_name}) 전체 데이터 적합 중...")
    final_pipeline = build_pipeline(clone(models[champion_name]), schema, "regressor")
    final_pipeline.fit(X, y)

    log_progress(log_offset + log_weight - 2, f"Target '{target_name}' | 순열 피처 중요도(Feature Importance) 산출 중...")
    feature_ranks = feature_importance_ranks(final_pipeline, X, y, schema, seed, scoring=None)

    champion_summary = {
        "task": TASK_REGRESSION,
        "primary_metric": "val_r2",
        "val_score": champion_entry["val_r2"],
        "champion_model": champion_name,
        "val_r2": champion_entry["val_r2"],
        "train_r2": champion_entry["train_r2"],
        "overfit_gap": champion_entry["overfit_gap"],
        "mae": champion_entry["mae"],
        "rmse": champion_entry["rmse"],
        "residual_skew": residual_skew,
        "prediction_interval": interval,
        "top_features": feature_ranks[:3],
        "weak_features": [f["feature"] for f in feature_ranks if f["pct"] <= 1.0],
        "feature_importances": feature_ranks
    }

    target_benchmark_res = {
        "target": target_name,
        "task": TASK_REGRESSION,
        "sample_count": len(y),
        "champion": champion_summary,
        "leaderboard": leaderboard
    }
    oof_df = pd.DataFrame({
        "data_row": row_ids + 1,
        "actual": y,
        "predicted": np.round(model_oof_map[champion_name], 6),
        "residual": np.round(residuals, 6),
    })
    return target_benchmark_res, final_pipeline, champion_summary, oof_df


# ==============================================================================
# 5-B. 5-Model Competitive Classification Pool (--task classification)
# ==============================================================================

def normalize_labels(series: pd.Series) -> pd.Series:
    """
    Converts class labels to stable strings so the same class never splits by storage type:
    1, 1.0, '1' -> '1'; ' 양품 ' -> '양품'. Placeholder strings become missing.
    """
    def _norm(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        if isinstance(v, (bool, np.bool_)):
            return str(bool(v))
        if isinstance(v, (int, np.integer)):
            return str(int(v))
        if isinstance(v, (float, np.floating)):
            return str(int(v)) if float(v).is_integer() else str(float(v))
        t = str(v).strip()
        if t in ("", "-", "N/A", "n/a", "NA", "null", "NULL", "None", "nan", "NaN", "미측정"):
            return None
        try:
            f = float(t.replace(",", ""))
            if f.is_integer() and re.fullmatch(r"[+-]?[\d,]+(\.0+)?", t):
                return str(int(f))
        except ValueError:
            pass
        return t

    return series.astype("object").map(_norm)


def get_classification_models(seed: int = 42, balanced: bool = False, n_rows: int = 0) -> Dict[str, Any]:
    """
    Returns 5 distinct classifiers:
    1. HistGradientBoostingClassifier (GBDT, non-linear, robust)
    2. RandomForestClassifier (Bagging ensemble)
    3. ExtraTreesClassifier (Extremely randomized trees)
    4. LogisticRegression (linear baseline; C auto-tuned by inner 3-fold CV on Macro-F1)
    5. KNeighborsClassifier (instance-based; skipped above KNN_MAX_ROWS rows for speed)
    balanced=True applies class_weight='balanced' where supported (KNN has no class weights).
    """
    cw = "balanced" if balanced else None
    models = {
        "HistGradientBoosting": HistGradientBoostingClassifier(random_state=seed, class_weight=cw),
        "RandomForest": RandomForestClassifier(n_estimators=100, random_state=seed, n_jobs=-1, class_weight=cw,
                                               **_bagging_kwargs(n_rows)),
        "ExtraTrees": ExtraTreesClassifier(n_estimators=100, random_state=seed, n_jobs=-1, class_weight=cw,
                                           **_bagging_kwargs(n_rows)),
        # make_scorer object (not the "f1_macro" string): the string fails for binary labels in scikit-learn 1.9
        "LogisticRegression": LogisticRegressionCV(Cs=8, cv=3, max_iter=3000, class_weight=cw,
                                                   scoring=make_scorer(f1_score, average="macro")),
        "KNeighbors": KNeighborsClassifier(n_neighbors=5),
    }
    if n_rows > KNN_MAX_ROWS:
        sys.stderr.write(f"[INFO] 데이터 {n_rows}행 > {KNN_MAX_ROWS}행: 속도를 위해 KNeighbors 모델을 경쟁에서 제외\n")
        models.pop("KNeighbors")
    return models


def _roc_auc(y_true: np.ndarray, proba: np.ndarray, classes: List[str]) -> Optional[float]:
    try:
        if len(classes) == 2:
            return float(roc_auc_score(y_true == classes[1], proba[:, 1]))
        return float(roc_auc_score(y_true, proba, multi_class="ovr", average="macro", labels=classes))
    except Exception:
        return None


def best_binary_threshold(y: np.ndarray, proba_pos: np.ndarray, positive: str) -> Tuple[float, Dict[str, float]]:
    """Threshold on P(positive) that maximizes positive-class F1 on OOF probabilities."""
    y_pos = (y == positive)
    best_t, best_f1 = 0.5, -1.0
    for t in np.round(np.arange(0.05, 0.951, 0.01), 2):
        f1 = f1_score(y_pos, proba_pos >= t, zero_division=0)
        if f1 > best_f1 + 1e-12:
            best_t, best_f1 = float(t), float(f1)
    pred = proba_pos >= best_t
    tp = int((pred & y_pos).sum())
    stats = {
        "f1": round(best_f1, 4),
        "precision": round(tp / max(int(pred.sum()), 1), 4),
        "recall": round(tp / max(int(y_pos.sum()), 1), 4),
    }
    return best_t, stats


def train_and_benchmark_classifiers(
    X: pd.DataFrame,
    y_series: pd.Series,
    target_name: str,
    schema: Dict[str, Any],
    seed: int = 42,
    log_offset: int = 20,
    log_weight: int = 50,
    positive_class: Optional[str] = None
) -> Tuple[Dict[str, Any], Any, Dict[str, Any]]:
    """
    Stratified K-Fold competition of 5 classifiers. Champion = highest Out-of-Fold Macro-F1
    (fair under class imbalance). Fits champion on 100% of data and extracts permutation
    importance (scoring = f1_macro). Binary + positive_class: decision threshold tuned on
    OOF probabilities to maximize the positive-class F1.
    """
    valid_mask = y_series.notna().values
    row_ids = np.flatnonzero(valid_mask)  # position in the loaded data (reported as 1-based data_row)
    X = X.loc[valid_mask].reset_index(drop=True)
    y = y_series.loc[valid_mask].astype(str).values

    classes = sorted(pd.unique(y).tolist())
    counts = pd.Series(y).value_counts()
    class_counts = {c: int(counts[c]) for c in classes}
    if len(classes) < 2:
        raise InputError(f"타겟 '{target_name}'의 클래스가 {len(classes)}개뿐입니다. 분류에는 2개 이상의 클래스가 필요합니다.")
    rare = [c for c in classes if class_counts[c] < 2]
    if rare:
        raise InputError(
            f"타겟 '{target_name}'에 샘플이 1개뿐인 클래스 {rare}이(가) 있습니다. "
            f"클래스별 최소 2개 이상 필요합니다. 해당 행을 제외하거나 클래스를 병합하십시오. [클래스별 건수]: {class_counts}"
        )
    if len(classes) > 50:
        raise InputError(
            f"타겟 '{target_name}'의 클래스가 {len(classes)}개로 너무 많습니다. 연속형 수치라면 --task regression을 사용하십시오."
        )
    if len(y) < 10:
        raise InputError(f"타겟 '{target_name}'의 유효 학습 샘플 수가 너무 적습니다 ({len(y)}개). 최소 10개 이상 필요합니다.")
    if positive_class is not None:
        if len(classes) != 2:
            raise InputError(f"--positive-class는 이진 분류(클래스 2개)에서만 사용할 수 있습니다. 타겟 '{target_name}' 클래스: {classes}")
        if positive_class not in classes:
            raise InputError(f"--positive-class '{positive_class}'가 타겟 '{target_name}'의 클래스에 없습니다. [추천] {classes}")

    min_ratio = min(class_counts.values()) / len(y)
    balanced = min_ratio < 0.20
    if balanced:
        sys.stderr.write(
            f"[WARN] 타겟 '{target_name}' 클래스 불균형 감지 (최소 클래스 비율 {min_ratio:.1%}) -> class_weight='balanced' 적용\n"
        )

    models = get_classification_models(seed=seed, balanced=balanced, n_rows=len(y))
    model_count = len(models)
    n_splits = max(2, min(5, min(class_counts.values())))
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)

    leaderboard = []
    model_oof_map: Dict[str, np.ndarray] = {}
    model_proba_map: Dict[str, np.ndarray] = {}

    for m_idx, (model_name, clf) in enumerate(models.items()):
        oof_pred = np.empty(len(y), dtype=object)
        oof_proba = np.zeros((len(y), len(classes)))
        train_f1_list = []
        params = {}

        for fold, (train_idx, val_idx) in enumerate(skf.split(X, y), 1):
            if fold == 1:
                pct = log_offset + int(log_weight * m_idx / model_count)
                log_progress(pct, f"Target '{target_name}' | {model_name} 교차검증 ({n_splits}-fold)...")

            pipe = build_pipeline(clone(clf), schema, "classifier")
            pipe.fit(X.iloc[train_idx], y[train_idx])
            train_f1_list.append(f1_score(y[train_idx], pipe.predict(X.iloc[train_idx]), average="macro", zero_division=0))
            oof_pred[val_idx] = pipe.predict(X.iloc[val_idx])
            proba = pipe.predict_proba(X.iloc[val_idx])
            col_idx = [classes.index(c) for c in pipe.classes_]
            oof_proba[np.ix_(val_idx, col_idx)] = proba
            params = _model_params(pipe)
            del pipe

        oof_pred = oof_pred.astype(str)
        model_oof_map[model_name] = oof_pred
        model_proba_map[model_name] = oof_proba
        val_f1 = float(f1_score(y, oof_pred, average="macro", zero_division=0))
        avg_train_f1 = float(np.mean(train_f1_list))
        auc = _roc_auc(y, oof_proba, classes)
        entry = {
            "model_name": model_name,
            "val_f1_macro": round(val_f1, 4),
            "train_f1_macro": round(avg_train_f1, 4),
            "overfit_gap": round(avg_train_f1 - val_f1, 4),
            "accuracy": round(float(accuracy_score(y, oof_pred)), 4),
            "balanced_accuracy": round(float(balanced_accuracy_score(y, oof_pred)), 4),
            "roc_auc": round(auc, 4) if auc is not None else None,
        }
        if params:
            entry["params"] = params
        leaderboard.append(entry)

    leaderboard.sort(key=lambda item: item["val_f1_macro"], reverse=True)
    for rank, entry in enumerate(leaderboard, 1):
        entry["rank"] = rank
        entry["is_champion"] = (rank == 1)
    champion_entry = leaderboard[0]
    champion_name = champion_entry["model_name"]

    # Binary decision threshold for the chosen positive class (default 0.5 otherwise)
    threshold_info = None
    champion_oof = model_oof_map[champion_name]
    if positive_class is not None:
        pos_idx = classes.index(positive_class)
        thr, stats = best_binary_threshold(y, model_proba_map[champion_name][:, pos_idx], positive_class)
        neg = classes[1 - pos_idx]
        champion_oof = np.where(model_proba_map[champion_name][:, pos_idx] >= thr, positive_class, neg).astype(str)
        threshold_info = {"positive_class": positive_class, "threshold": thr, "oof_positive_metrics": stats}
        sys.stderr.write(f"[INFO] 타겟 '{target_name}' 양성 클래스 '{positive_class}' 판정 기준 확률 = {thr:.2f} (양성 F1 최대화)\n")

    cm = confusion_matrix(y, champion_oof, labels=classes)
    report = classification_report(y, champion_oof, labels=classes, output_dict=True, zero_division=0)
    per_class = {
        c: {
            "precision": round(float(report[c]["precision"]), 4),
            "recall": round(float(report[c]["recall"]), 4),
            "f1": round(float(report[c]["f1-score"]), 4),
            "support": int(report[c]["support"]),
        }
        for c in classes
    }

    log_progress(log_offset + log_weight - 4, f"Target '{target_name}' | 1위 챔피언({champion_name}) 전체 데이터 적합 중...")
    final_pipeline = build_pipeline(clone(models[champion_name]), schema, "classifier")
    final_pipeline.fit(X, y)

    log_progress(log_offset + log_weight - 2, f"Target '{target_name}' | 순열 피처 중요도(Feature Importance) 산출 중...")
    feature_ranks = feature_importance_ranks(final_pipeline, X, y, schema, seed, scoring="f1_macro")

    champion_summary = {
        "task": TASK_CLASSIFICATION,
        "primary_metric": "val_f1_macro",
        "val_score": champion_entry["val_f1_macro"],
        "champion_model": champion_name,
        "val_f1_macro": champion_entry["val_f1_macro"],
        "train_f1_macro": champion_entry["train_f1_macro"],
        "overfit_gap": champion_entry["overfit_gap"],
        "accuracy": champion_entry["accuracy"],
        "balanced_accuracy": champion_entry["balanced_accuracy"],
        "roc_auc": champion_entry["roc_auc"],
        "classes": classes,
        "class_counts": class_counts,
        "class_weight": "balanced" if balanced else None,
        "decision_threshold": threshold_info,
        "per_class": per_class,
        "confusion_matrix": {"labels": classes, "matrix": cm.tolist()},
        "top_features": feature_ranks[:3],
        "weak_features": [f["feature"] for f in feature_ranks if f["pct"] <= 1.0],
        "feature_importances": feature_ranks
    }
    target_benchmark_res = {
        "target": target_name,
        "task": TASK_CLASSIFICATION,
        "sample_count": len(y),
        "champion": champion_summary,
        "leaderboard": leaderboard
    }
    oof_df = pd.DataFrame({"data_row": row_ids + 1, "actual": y, "predicted": champion_oof})
    for i, c in enumerate(classes):
        oof_df[f"proba_{c}"] = np.round(model_proba_map[champion_name][:, i], 6)
    return target_benchmark_res, final_pipeline, champion_summary, oof_df


# ==============================================================================
# 6. Atomic Transaction Guard & Revision Management
# ==============================================================================

class TransactionGuard:
    """
    Manages atomic version folders:
    - Garbage collects broken/abandoned .tmp_* folders on startup.
    - Allocates next version folder (v1, v2, ...).
    - Stages all files in .tmp_vX/.
    - Atomically renames .tmp_vX/ to vX/ upon 100% successful execution.
    - Cleans up .tmp_vX/ immediately if an exception or interrupt occurs.
    """
    def __init__(self, data_root: str, target_version: Optional[str] = None):
        self.data_root = os.path.abspath(data_root)
        os.makedirs(self.data_root, exist_ok=True)
        self.target_version = target_version
        self.version_str = ""
        self.tmp_dir = ""
        self.final_dir = ""
        self.is_committed = False

    def setup(self) -> str:
        # 1. Startup Garbage Collection of broken temporary folders
        self._garbage_collect()

        # 2. Determine Version
        if self.target_version:
            self.version_str = normalize_version(self.target_version)
            if not re.match(r"^v[0-9A-Za-z_.-]+$", self.version_str):
                raise InputError(f"버전명은 영문/숫자만 사용할 수 있습니다 (예: v3): '{self.target_version}'")
        else:
            # Auto-infer next version
            existing_versions = []
            for item in os.listdir(self.data_root):
                p = os.path.join(self.data_root, item)
                if os.path.isdir(p) and re.match(r"^v\d+$", item):
                    try:
                        existing_versions.append(int(item[1:]))
                    except Exception:
                        pass
            next_num = max(existing_versions, default=0) + 1
            self.version_str = f"v{next_num}"

        self.tmp_dir = os.path.join(self.data_root, f".tmp_{self.version_str}")
        self.final_dir = os.path.join(self.data_root, self.version_str)

        # Clean any preexisting tmp folder
        remove_tree(self.tmp_dir)
        os.makedirs(self.tmp_dir, exist_ok=True)

        return self.version_str

    def _garbage_collect(self) -> None:
        """Removes orphaned .tmp_* folders and corrupted version folders without leaderboard.json."""
        for item in os.listdir(self.data_root):
            p = os.path.join(self.data_root, item)
            if os.path.isdir(p):
                # Clean temp folders
                if item.startswith(".tmp_"):
                    try:
                        remove_tree(p)
                        sys.stderr.write(f"[INFO] 고아 임시 폴더 자동 청소: {item}\n")
                    except Exception:
                        pass
                # Check for corrupted version folder (missing leaderboard or dataset)
                elif re.match(r"^v\d+$", item):
                    lead_p = os.path.join(p, "leaderboard.json")
                    ds_p = os.path.join(p, "model_dataset.csv")
                    if not (os.path.exists(lead_p) and os.path.exists(ds_p)):
                        try:
                            remove_tree(p)
                            sys.stderr.write(f"[INFO] 불완전/손상된 버전 폴더 자동 청소: {item}\n")
                        except Exception:
                            pass

    def commit(self) -> str:
        """Atomically renames .tmp_vX to vX (retries transient Windows locks from antivirus/Explorer)."""
        if os.path.exists(self.final_dir):
            # Target version already exists (manual --version override): replace it
            remove_tree(self.final_dir)
        retry_fs(lambda: os.rename(self.tmp_dir, self.final_dir))
        self.is_committed = True
        return self.final_dir

    def rollback(self) -> None:
        """Removes staging directory on failure."""
        if not self.is_committed and self.tmp_dir and os.path.exists(self.tmp_dir):
            try:
                remove_tree(self.tmp_dir)
                sys.stderr.write(f"[WARN] 비정상 중단: 임시 스테이징 폴더 롤백 완료 ({self.tmp_dir})\n")
            except Exception:
                pass


# ==============================================================================
# 7. SSOT Ledger (history.jsonl) Management
# ==============================================================================

def append_history_ledger(ledger_path: str, record: Dict[str, Any]) -> None:
    """Appends one experiment record (one JSON line) to history.jsonl, the single source of truth."""
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(dumps_json(record) + "\n")


def load_history_ledger(ledger_path: str) -> List[Dict[str, Any]]:
    """Loads all records from history.jsonl."""
    if not os.path.exists(ledger_path):
        return []
    records = []
    with open(ledger_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    sys.stderr.write("[WARN] history.jsonl 손상 라인 1건을 건너뜀\n")
    return records


# ==============================================================================
# 7-B. Run Lock, Bounded Correlation, Next Commands
# ==============================================================================

class RunLock:
    """
    Prevents two trainings on the same dataset at once (they would collide on version numbers
    and the startup garbage collection could delete the other run's staging folder).
    Uses an OS file lock, so a crashed process never leaves a stale lock behind.
    """

    def __init__(self, data_root: str):
        self.path = os.path.join(data_root, ".train.lock")
        self.fh = None

    def acquire(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise InputError(
                f"같은 데이터에 대한 다른 학습이 이미 실행 중입니다 ({os.path.dirname(self.path)}). "
                f"동시에 실행할 수 없으니 진행 중인 학습이 끝난 뒤 다시 실행하십시오."
            )
        self.fh = fh

    def release(self) -> None:
        if self.fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.fh.close()
        self.fh = None


CORR_MAX_FEATURES = 30


def bounded_correlation(
    corr_full: pd.DataFrame, importances: List[Dict[str, Any]], schema: Dict[str, Any], targets: List[str]
) -> Tuple[Dict[str, Any], bool]:
    """
    Ledger copy of the correlation matrix: all columns when small, otherwise the
    CORR_MAX_FEATURES most important numeric inputs plus targets (full matrix: vX/correlation.csv).
    """
    inputs = [c for c in corr_full.columns if c not in targets]
    if len(inputs) <= CORR_MAX_FEATURES:
        return corr_full.to_dict(), False
    owner = input_column_owner(schema)
    order = {r["feature"]: i for i, r in enumerate(importances)}
    ranked = sorted(inputs, key=lambda c: order.get(owner.get(c, c), len(order)))
    keep = ranked[:CORR_MAX_FEATURES] + targets
    return corr_full.loc[keep, keep].to_dict(), True


def _q(v: str) -> str:
    return '"' + str(v).replace('"', "'") + '"'


def build_next_commands(
    args: argparse.Namespace, raw_file: str, task: str, positive_class: Optional[str],
    feature_names: List[str], created_features: List[str], applied_evals: List[str],
    target_names: List[str], champion: Dict[str, Any], schema: Dict[str, Any],
    mean_score: float, staging_dir: str, final_dir: str, data_root: str,
) -> List[Dict[str, str]]:
    """
    Ready-to-run follow-up commands so a small LLM does not have to compose arguments:
    deployment/prediction when the goal is met, otherwise feature pruning and an interaction feature.
    Long feature lists are written to <version>/next_features_*.txt and passed by path.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    train_py = _q(os.path.join(here, "ml_train.py"))
    base = [f"python {train_py}", "-f", _q(raw_file)]
    for flag, val in (("--header-row", args.header_row), ("--unit-row", args.unit_row),
                      ("--data-row", args.data_row), ("--dtypes", args.dtypes)):
        if val is not None:
            base += [flag, _q(val)]
    if task == TASK_CLASSIFICATION:
        base += ["--task", TASK_CLASSIFICATION]
        if positive_class is not None:
            base += ["--positive-class", _q(positive_class)]
    base += ["-y", _q(",".join(target_names))]

    def features_arg(feats: List[str], tag: str) -> str:
        if len(feats) <= 15:
            return _q(",".join(feats))
        fname = f"next_features_{tag}.txt"
        with open(os.path.join(staging_dir, fname), "w", encoding="utf-8") as f:
            f.write("\n".join(feats) + "\n")
        return _q(os.path.join(final_dir, fname))

    base_features = [f for f in feature_names if f not in created_features]
    cmds: List[Dict[str, str]] = []

    if mean_score >= 0.90:
        cmds.append({
            "purpose": "목표 성능 달성: 새 데이터 예측 (<새데이터.xlsx>를 실제 파일 경로로 바꿀 것)",
            "command": f"python {_q(os.path.join(here, 'ml_predict.py'))} -m {_q(final_dir)} -f \"<새데이터.xlsx>\"",
        })
        if task == TASK_REGRESSION:
            cmds.append({
                "purpose": "Word 감사 보고서 생성",
                "command": f"python {_q(os.path.join(here, 'ml_report.py'))} -d {_q(data_root)}",
            })
        return cmds

    weak = [w for w in champion.get("weak_features", []) if w in feature_names]
    keep_base = [f for f in base_features if f not in weak]
    keep_evals = [e for e in applied_evals if e.split("=", 1)[0].strip() not in weak]
    if weak and keep_base:
        parts = base + ["-x", features_arg(keep_base, "pruned")]
        if keep_evals:
            parts += ["--eval", _q("; ".join(keep_evals))]
        parts += ["--tag", _q("저기여피처_제외")]
        cmds.append({"purpose": f"기여도 1% 이하 피처 {weak[:5]} 제외 후 재학습", "command": " ".join(parts)})

    numeric_top = [r["feature"] for r in champion.get("top_features", []) if r["feature"] in schema["numeric"]]
    if len(numeric_top) >= 2:
        a, b = numeric_top[0], numeric_top[1]
        new_name = f"{strip_unit(a)}x{strip_unit(b)}"
        existing = set(feature_names) | {e.split("=", 1)[0].strip() for e in applied_evals}
        if new_name not in existing:
            evals = applied_evals + [f"{new_name} = {a} * {b}"]
            parts = base + ["-x", features_arg(base_features, "all"), "--eval", _q("; ".join(evals)),
                            "--tag", _q("교차항_추가")]
            cmds.append({"purpose": f"상위 피처 '{a}', '{b}' 교차항 추가 후 재학습", "command": " ".join(parts)})
    return cmds


# ==============================================================================
# 8. Main Execution Controller
# ==============================================================================

def execute_ml_train(args: argparse.Namespace) -> Dict[str, Any]:
    """Orchestrates 1-Turn declarative regression / classification pipeline."""
    start_time = time.time()
    task = (getattr(args, "task", None) or TASK_REGRESSION).lower()
    positive_class = getattr(args, "positive_class", None)
    if positive_class is not None:
        if task != TASK_CLASSIFICATION:
            raise InputError("--positive-class는 --task classification과 함께 사용해야 합니다.")
        positive_class = normalize_labels(pd.Series([positive_class])).iloc[0]
    primary_metric = PRIMARY_METRIC[task]
    metric_label = METRIC_LABEL[task]
    raw_file = os.path.abspath(args.file)
    if not os.path.exists(raw_file):
        raise FileNotFoundError(f"입력 파일이 존재하지 않습니다: {raw_file}")
    warn_long_path(raw_file)

    file_dir = os.path.dirname(raw_file)
    file_stem = os.path.splitext(os.path.basename(raw_file))[0]
    data_root = os.path.join(file_dir, f"{file_stem}_ml_data")
    ledger_path = os.path.join(data_root, "history.jsonl")

    # One training run per dataset at a time (OS lock is released automatically if the process dies)
    run_lock = RunLock(data_root)
    run_lock.acquire()

    # Transaction Guard Setup
    guard = TransactionGuard(data_root=data_root, target_version=args.version)
    try:
        current_version = guard.setup()
    except BaseException:
        run_lock.release()
        raise

    try:
        log_progress(5, f"입력 데이터 로드 중: {os.path.basename(raw_file)}...")
        df_raw, file_name = load_data_file(
            file_path=raw_file,
            header_row=args.header_row,
            unit_row=args.unit_row,
            data_row=args.data_row
        )

        # Parse Explicit Features & Targets (Supports file path or comma-separated string)
        feature_names = parse_feature_or_target_list(args.features, param_name="features")
        target_names = parse_feature_or_target_list(args.targets, param_name="targets")

        if not feature_names:
            raise InputError("학습에 투입할 독립변수 목록(-x, --features)이 지정되지 않았거나 파일이 비어 있습니다.")
        if not target_names:
            raise InputError("예측할 종속변수 목록(-y, --targets)이 지정되지 않았거나 파일이 비어 있습니다.")

        # Fail-Fast Validation & Type Sanitization
        log_progress(10, "컬럼 유효성 검증 및 타입 정제 중...")
        df_clean, feature_names, target_names, column_aliases = validate_and_sanitize_data(
            df=df_raw,
            feature_names=feature_names,
            target_names=target_names,
            dtypes_arg=args.dtypes,
            task=task
        )

        # Feature Engineering (--eval)
        applied_evals = []
        created_features = []
        if args.eval:
            log_progress(15, "파생변수 계산 중 (--eval)...")
            df_clean, applied_evals, created_features = run_safe_eval(
                df=df_clean,
                eval_str=args.eval,
                target_cols=target_names
            )
            # Add new features to feature_names if not already present
            for c_feat in created_features:
                if c_feat not in feature_names:
                    feature_names.append(c_feat)

        # Feature typing (numeric / categorical / datetime) and model input frame
        feature_schema = infer_feature_schema(df_clean, feature_names, created_features, dtypes_arg=args.dtypes)
        X_all = prepare_features(df_clean, feature_schema)
        empty_numeric = [c for c in feature_schema["numeric"] if X_all[c].notna().sum() == 0]
        if empty_numeric:
            raise InputError(
                f"컬럼 {empty_numeric}에 숫자로 변환 가능한 값이 하나도 없습니다. 헤더/데이터 시작 행(--header-row, --data-row)을 확인하십시오."
            )
        for col in feature_schema["numeric"]:
            df_clean[col] = X_all[col]

        # Correlation (numeric inputs incl. date parts + numeric targets) for SSOT reporting
        log_progress(20, "변수 간 2차원 상관행렬 계산 중...")
        num_inputs = [c for c in feature_schema["input_columns"] if c not in feature_schema["categorical"]]
        target_numeric = target_names if task == TASK_REGRESSION else []
        corr_frame = pd.concat([X_all[num_inputs], df_clean[target_numeric]], axis=1)
        corr_full = corr_frame.corr().round(4)

        # Multi-Target 5-Model Competitive Training (one task per run)
        target_benchmarks = {}
        target_champions = {}
        target_summaries = {}
        all_champion_scores = []
        benchmark_fn = train_and_benchmark_models if task == TASK_REGRESSION else train_and_benchmark_classifiers

        total_targets = len(target_names)
        for t_idx, target_name in enumerate(target_names):
            t_offset = 25 + int(55 * t_idx / total_targets)
            t_weight = int(55 / total_targets)

            log_progress(t_offset, f"타겟 [{t_idx+1}/{total_targets}] '{target_name}' 5대 모델 경쟁 학습 ({task})...")

            extra = {"positive_class": positive_class} if task == TASK_CLASSIFICATION else {}
            t_bench, champion_pipe, champion_info, oof_df = benchmark_fn(
                X=X_all,
                y_series=df_clean[target_name],
                target_name=target_name,
                schema=feature_schema,
                seed=args.seed,
                log_offset=t_offset,
                log_weight=t_weight,
                **extra
            )

            target_benchmarks[target_name] = t_bench
            target_champions[target_name] = {
                "pipeline": champion_pipe,
                "info": champion_info,
                "oof": oof_df
            }
            all_champion_scores.append(champion_info["val_score"])

            # Target statistics
            y_valid = df_clean[target_name].dropna()
            if task == TASK_REGRESSION:
                target_summaries[target_name] = {
                    "mean": round(float(y_valid.mean()), 4),
                    "std": round(float(y_valid.std()), 4),
                    "min": round(float(y_valid.min()), 4),
                    "max": round(float(y_valid.max()), 4)
                }
            else:
                target_summaries[target_name] = {
                    "classes": champion_info["classes"],
                    "class_counts": champion_info["class_counts"],
                    "missing_dropped": int(df_clean[target_name].isna().sum())
                }

        mean_val_score = float(np.mean(all_champion_scores))

        # Check Previous History (same task only) for Delta
        log_progress(85, f"이전 이력 대조 및 성능 변화(Delta {metric_label}) 산출 중...")
        history_records = load_history_ledger(ledger_path)

        # Resolve project description: explicit arg takes precedence, otherwise inherit from previous version
        project_desc = (getattr(args, "description", None) or "").strip()
        if project_desc and os.path.isfile(project_desc):
            project_desc = read_text_file(project_desc).strip()

        if not project_desc and history_records:
            project_desc = history_records[-1].get("description", "")

        # Scores are comparable only for the same task AND the same target set
        same_task = [h for h in history_records
                     if h.get("task", TASK_REGRESSION) == task and sorted(h.get("targets", [])) == sorted(target_names)]

        def _rec_score(h: Dict[str, Any]) -> Optional[float]:
            v = h.get("mean_val_score")
            return float(v) if isinstance(v, (int, float)) else None

        prev_scores = [v for v in (_rec_score(h) for h in same_task) if v is not None]
        last_score = _rec_score(same_task[-1]) if same_task else None
        delta_score: Any = round(mean_val_score - last_score, 4) if last_score is not None else "base"
        is_best = mean_val_score > max(prev_scores, default=-999.0)

        # Generate Actionable Recommendations for 26B-30B LLM (driven by the weakest target)
        min_score = min(all_champion_scores)
        primary_target = min(target_names, key=lambda t: target_champions[t]["info"]["val_score"])
        prim_champ = target_champions[primary_target]["info"]
        top_feats = prim_champ.get("top_features", [])
        weak_feats = prim_champ.get("weak_features", [])
        below = [t for t in target_names if target_champions[t]["info"]["val_score"] < 0.90]

        recommendations = []
        if min_score >= 0.90:
            recommendations.append(f"모든 타겟이 목표 성능({metric_label} >= 0.90)을 달성했습니다. 예측 배포와 보고서 작성이 가능합니다.")
        else:
            if len(target_names) > 1:
                recommendations.append(f"목표({metric_label} >= 0.90) 미달 타겟: {below}. 아래 권고는 가장 낮은 '{primary_target}' 기준입니다.")
            weak_classes = [c for c, m in prim_champ.get("per_class", {}).items() if m["recall"] < 0.70]
            if task == TASK_CLASSIFICATION and weak_classes:
                recommendations.append(
                    f"재현율(Recall)이 0.70 미만인 클래스 {weak_classes[:3]}의 구분력이 부족합니다. "
                    f"해당 클래스를 가르는 피처를 추가하거나 --eval로 비율/차이 파생변수를 만드십시오."
                )
            elif len(top_feats) >= 2:
                f1, f2 = top_feats[0]["feature"], top_feats[1]["feature"]
                recommendations.append(f"주요 기여 피처 '{f1}'와(과) '{f2}'의 교차 상호작용('{f1} * {f2}') 생성을 권장합니다.")
        if task == TASK_CLASSIFICATION and prim_champ.get("class_weight"):
            recommendations.append("클래스 불균형으로 class_weight='balanced'가 적용되었습니다. 소수 클래스 데이터 추가 수집을 권장합니다.")
        if weak_feats:
            recommendations.append(f"기여도가 1% 미만인 피처 {weak_feats[:2]}을(를) 배제하여 노이즈를 감소시키십시오.")

        # Score keys shared by result JSON, leaderboard and ledger
        score_keys: Dict[str, Any] = {
            "task": task,
            "primary_metric": primary_metric,
            "mean_val_score": round(mean_val_score, 4),
            "delta_score": delta_score,
        }

        # Stage Artifacts in .tmp_vX/
        log_progress(90, f"버전 산출물 패키징 중 ({current_version})...")
        staging_dir = guard.tmp_dir

        # 1. Unified leaderboard.json (Single file covering all targets)
        leaderboard_data = {
            "version": current_version,
            "timestamp": datetime.now().isoformat(),
            **score_keys,
            "is_best": is_best,
            "targets": target_benchmarks
        }
        with open(os.path.join(staging_dir, "leaderboard.json"), "w", encoding="utf-8") as f:
            f.write(dumps_json(leaderboard_data, indent=2))

        datetime_stats = {}
        for col in feature_schema["datetime"]:
            dt = parse_datetime(df_clean[col]).dropna()
            if not dt.empty:
                datetime_stats[col] = {"min": dt.min().isoformat(), "max": dt.max().isoformat()}

        # Correlation: full matrix as a file, a bounded matrix in the ledger (keeps history.jsonl small)
        corr_full.to_csv(os.path.join(staging_dir, "correlation.csv"), encoding="utf-8-sig")
        corr_matrix, corr_truncated = bounded_correlation(
            corr_full, target_champions[target_names[0]]["info"]["feature_importances"],
            feature_schema, target_numeric)
        target_correlations = {
            t: {c: v for c, v in corr_full[t].drop(labels=target_numeric).items()} for t in target_numeric
        }

        # 2. Target Models and Metadata
        for target_name, champ_data in target_champions.items():
            pipe = champ_data["pipeline"]
            info = champ_data["info"]
            safe_target = sanitize_filename(target_name)

            # Save Model Joblib with safe filename
            joblib_path = os.path.join(staging_dir, f"model_{safe_target}.joblib")
            joblib.dump(pipe, joblib_path, compress=3)

            # Out-of-fold predictions of the champion (report: actual vs predicted, residuals, ROC)
            champ_data["oof"].to_csv(os.path.join(staging_dir, f"oof_{safe_target}.csv"), index=False, encoding="utf-8-sig")

            # Feature statistics for inference validation (numeric extrapolation guard)
            feat_stats = {}
            for fname in feature_schema["numeric"]:
                s = df_clean[fname].dropna()
                if not s.empty:
                    feat_stats[fname] = {
                        "mean": round(float(s.mean()), 4),
                        "std": round(float(s.std()), 4),
                        "min": round(float(s.min()), 4),
                        "max": round(float(s.max()), 4),
                        "median": round(float(s.median()), 4)
                    }

            # Inference Metadata JSON with safe filename
            meta_json = {
                "version": current_version,
                "target": target_name,
                "target_safe_name": safe_target,
                "task": task,
                "primary_metric": primary_metric,
                "val_score": info["val_score"],
                "description": project_desc,
                "champion_model": info["champion_model"],
            }
            if task == TASK_REGRESSION:
                meta_json.update({
                    "val_r2": info["val_r2"],
                    "mae": info["mae"],
                    "rmse": info["rmse"],
                    "residual_skew": info.get("residual_skew", 0.0),
                    "prediction_interval": info.get("prediction_interval"),
                })
            else:
                meta_json.update({
                    "val_f1_macro": info["val_f1_macro"],
                    "accuracy": info["accuracy"],
                    "balanced_accuracy": info["balanced_accuracy"],
                    "roc_auc": info["roc_auc"],
                    "classes": info["classes"],
                    "class_counts": info["class_counts"],
                    "decision_threshold": info.get("decision_threshold"),
                })
            meta_json.update({
                "features_required": feature_names,
                "feature_count": len(feature_names),
                "feature_stats": feat_stats,
                "datetime_stats": datetime_stats,
                "feature_schema": feature_schema,
                "derived_evals": applied_evals,
                "target_summary": target_summaries.get(target_name, {}),
                "sklearn_version": sklearn.__version__,
                "python_version": sys.version.split()[0]
            })
            with open(os.path.join(staging_dir, f"model_{safe_target}.json"), "w", encoding="utf-8") as f:
                f.write(dumps_json(meta_json, indent=2))

        # 3. Clean Dataset Snapshot (model_dataset.csv)
        dataset_snapshot_cols = [c for c in feature_names + target_names if c in df_clean.columns]
        snapshot_df = df_clean[dataset_snapshot_cols]
        snapshot_path = os.path.join(staging_dir, "model_dataset.csv")

        # Windows 한국어 Excel 호환: cp949 기본, 표현 불가 문자 포함 시 utf-8-sig 자동 폴백
        write_csv_excel_compatible(snapshot_df, snapshot_path, encoding=getattr(args, "encoding", None))

        # 4. Append Record to history.jsonl (SSOT)
        duration_sec = round(time.time() - start_time, 2)
        # Missing feature cells (incl. unparseable strings) that SimpleImputer(median) fills
        missing_imputed = int(X_all.isna().sum().sum())

        owner = input_column_owner(feature_schema)
        feature_missing: Dict[str, int] = {}
        for col, n_miss in X_all.isna().sum().items():
            raw_col = owner.get(col, col)
            feature_missing[raw_col] = max(feature_missing.get(raw_col, 0), int(n_miss))
        data_profile = {
            "source_file": os.path.basename(raw_file),
            "rows_loaded": int(len(df_raw)),
            "columns_loaded": int(df_raw.shape[1]),
            "rows_used": {t: int(target_benchmarks[t]["sample_count"]) for t in target_names},
            "target_missing_rows": {t: int(df_clean[t].isna().sum()) for t in target_names},
            "feature_missing": feature_missing,
            "missing_imputed_cells": missing_imputed,
            "layout": {"header_row": args.header_row, "unit_row": args.unit_row, "data_row": args.data_row},
        }

        history_record = {
            "version": current_version,
            "timestamp": datetime.now().isoformat(),
            "tag": getattr(args, "tag", None) or "",
            "description": project_desc,
            "duration_sec": duration_sec,
            "data_profile": data_profile,
            "targets": target_names,
            "target_summaries": target_summaries,
            "features_used": feature_names,
            "derived_evals": applied_evals,
            **score_keys,
            "is_best": is_best,
            "recommendations": recommendations,
            "targets_benchmark": target_benchmarks,
            "feature_types": {
                "numeric": feature_schema["numeric"],
                "categorical": list(feature_schema["categorical"]),
                "datetime": feature_schema["datetime"],
            },
            "correlation_matrix": corr_matrix,
            "correlation_truncated": corr_truncated,
            "target_correlations": target_correlations
        }
        next_commands = build_next_commands(
            args=args, raw_file=raw_file, task=task, positive_class=positive_class,
            feature_names=feature_names, created_features=created_features, applied_evals=applied_evals,
            target_names=target_names, champion=prim_champ, schema=feature_schema,
            mean_score=min_score, staging_dir=staging_dir, final_dir=guard.final_dir, data_root=data_root,
        )
        history_record["next_commands"] = next_commands
        append_history_ledger(ledger_path, history_record)

        # Commit Transaction: Atomic rename from .tmp_vX to vX
        final_version_dir = guard.commit()
        log_progress(100, f"학습 및 산출물 패키징 완료: {current_version} ({os.path.basename(final_version_dir)}) [소요: {duration_sec}초]")

        # LLM Directive
        short = "R2" if task == TASK_REGRESSION else "F1"
        target_brief = ", ".join([f"{t}({target_champions[t]['info']['champion_model']}: {short}={target_champions[t]['info']['val_score']:.4f})" for t in target_names])
        delta_txt = delta_score if delta_score == "base" else f"{delta_score:+.4f}"
        preview = (
            f"[{current_version} 완료 / {task}] 타겟: [{target_brief}] | "
            f"평균 {metric_label}={mean_val_score:.4f} (Delta: {delta_txt}) | "
            f"소요시간: {duration_sec}s | "
            f"산출물 저장: {final_version_dir}"
        )
        agent_directive = (
            f"VERIFIED: {current_version} competitive training completed. "
            f"Champion models and leaderboard packaged into '{os.path.basename(final_version_dir)}'. "
            f"Task={task}, Mean {metric_label}={mean_val_score:.4f}. "
            f"Next step: run next_commands[0] if the user wants to continue, or proceed to inference."
        )

        result = {
            "status": "ok",
            "version": current_version,
            "tag": getattr(args, "tag", None) or "",
            "description": project_desc,
            "duration_sec": duration_sec,
            "data_root": data_root,
            "version_dir": final_version_dir,
            "targets": target_names,
            **score_keys,
            "is_best": is_best,
            "recommendations": recommendations,
            "next_commands": next_commands,
            "feature_types": history_record["feature_types"],
            "preview": preview,
            "agent_directive": agent_directive
        }
        if column_aliases:
            result["column_aliases"] = column_aliases
        return result

    except BaseException:
        # Includes KeyboardInterrupt (Ctrl+C) so the staging folder never leaks
        guard.rollback()
        raise
    finally:
        run_lock.release()


# ==============================================================================
# 9. CLI Interface & History Mode
# ==============================================================================

def print_history_summary(data_root: str) -> Dict[str, Any]:
    """
    Prints a human-readable summary table of all experiments to stderr and returns
    a compact JSON summary (stdout stays a single JSON line for the agent).
    """
    ledger_path = os.path.join(data_root, "history.jsonl")
    records = load_history_ledger(ledger_path)
    if not records:
        return {
            "status": "no_history",
            "message": f"실험 원장이 존재하지 않습니다: {ledger_path}",
            "agent_directive": "VERIFIED: No experiments yet. Next step: run baseline training (v1).",
        }

    proj_desc = records[-1].get("description", "")
    out = sys.stderr

    out.write("\n" + "=" * 125 + "\n")
    out.write(f" [ML EXPERIMENT HISTORY LEDGER] Root: {data_root}\n")
    if proj_desc:
        out.write(f" [PROJECT DESCRIPTION] {proj_desc}\n")
    out.write("=" * 125 + "\n")
    out.write(f"{'Version':<8} | {'Tag / Memo':<16} | {'Task / Score':<16} | {'Delta':<10} | {'Time':<7} | {'Targets':<22} | {'Status'}\n")
    out.write(f"{'-'*8}-+-{'-'*16}-+-{'-'*16}-+-{'-'*10}-+-{'-'*7}-+-{'-'*22}-+-{'-'*15}\n")

    rows = []
    for r in records:
        ver = r.get("version", "-")
        tag = r.get("tag") or "-"
        task = r.get("task", TASK_REGRESSION)
        score = r.get("mean_val_score")
        delta = r.get("delta_score", "base")
        row = {
            "version": ver, "tag": tag, "task": task,
            "primary_metric": r.get("primary_metric", PRIMARY_METRIC.get(task, "val_r2")),
            "mean_val_score": score, "delta_score": delta,
            "is_best": bool(r.get("is_best")), "targets": r.get("targets", []),
        }
        rows.append(row)

        tag_s = tag if len(tag) <= 15 else tag[:13] + ".."
        short = "R2" if task == TASK_REGRESSION else "F1"
        score_s = f"{short} {score:.4f}" if isinstance(score, (int, float)) else "-"
        delta_str = f"{delta:+.4f}" if isinstance(delta, (int, float)) else str(delta)
        dur = f"{r.get('duration_sec', 0.0):.1f}s" if "duration_sec" in r else "-"
        targets_str = ", ".join(r.get("targets", []))
        if len(targets_str) > 20:
            targets_str = targets_str[:18] + ".."
        status = "[BEST 챔피언]" if r.get("is_best") else "[수렴]"
        out.write(f" {ver:<7} | {tag_s:<16} | {score_s:<16} | {delta_str:<10} | {dur:<7} | {targets_str:<22} | {status}\n")

    out.write("=" * 125 + "\n\n")

    # Scores are only comparable within the same task
    best_by_task: Dict[str, Dict[str, Any]] = {}
    for x in rows:
        if isinstance(x["mean_val_score"], (int, float)):
            cur = best_by_task.get(x["task"])
            if cur is None or x["mean_val_score"] > cur["mean_val_score"]:
                best_by_task[x["task"]] = {"version": x["version"], "mean_val_score": x["mean_val_score"]}
    latest_task = rows[-1]["task"]
    best = best_by_task.get(latest_task)
    return {
        "status": "ok",
        "data_root": data_root,
        "description": proj_desc,
        "record_count": len(rows),
        "best_version": best["version"] if best else None,
        "best_mean_val_score": best["mean_val_score"] if best else None,
        "best_by_task": best_by_task,
        "latest_version": rows[-1]["version"],
        "records": rows,
        "agent_directive": "VERIFIED: History summary returned. Do not read history.jsonl for the same information.",
    }


def main():
    parser = JsonArgumentParser(
        description="Autonomous Regression / Classification ML Engine with 5-Model Competitive Benchmark & Version Lineage"
    )
    parser.add_argument("--file", "-f", help="입력 데이터 파일 경로 (.xlsx, .csv)")
    parser.add_argument("--features", "-x", help="독립변수(피처) 목록 (쉼표 구분 문자열 또는 파일 경로: .txt, .json, .csv)")
    parser.add_argument("--targets", "-y", help="종속변수(타겟) 목록 (쉼표 구분 문자열 또는 파일 경로: .txt, .json, .csv)")
    parser.add_argument("--eval", help="방탄 AST 파생변수 생성 수식 (세미콜론 구분). 컬럼명은 전체 이름 또는 단위를 뺀 고유 이름")
    parser.add_argument("--tag", help="해당 회차 실험 의도 및 변경 사항 메모 태그 (예: '베이스라인_학습', '파생변수2종_추가')")
    parser.add_argument(
        "--description", "--desc", dest="description",
        help="데이터셋 도메인 및 모델링 목적 설명 (문자열 또는 파일 경로 .txt, .md 지원. 미지정 시 이전 회차 설명 자동 상속)"
    )
    parser.add_argument("--header-row", type=int, help="컬럼명 헤더 행 번호 (1-based, 미지정 시 상단 빈 행 자동 건너뜀)")
    parser.add_argument("--unit-row", type=int, help="단위 행 번호 (선택)")
    parser.add_argument("--data-row", type=int, help="데이터 시작 행 번호 (선택)")
    parser.add_argument("--dtypes", help="데이터 타입 수동 오버라이드 (예: '일시:datetime,설비코드:str')")
    parser.add_argument("--encoding", help="model_dataset.csv 저장 인코딩 (기본값: Windows Excel 최적화 cp949, 특수문자 발생 시 utf-8-sig 자동 폴백)")
    parser.add_argument("--version", "-v", help="버전 수동 지정 (미지정 시 자동 계산 v1, v2...)")
    parser.add_argument("--task", choices=[TASK_REGRESSION, TASK_CLASSIFICATION], default=TASK_REGRESSION,
                        help="학습 유형: regression(기본값, 연속 수치 예측) 또는 classification(범주/라벨 예측)")
    parser.add_argument("--positive-class", dest="positive_class",
                        help="이진 분류의 양성 클래스 (예: 불량). 지정 시 양성 F1이 최대가 되도록 판정 기준 확률을 자동 조정")
    parser.add_argument("--seed", type=int, default=42, help="재현용 난수 시드 (기본값: 42)")
    parser.add_argument("--history", action="store_true", help="누적 실험 이력 조회 모드 (표는 stderr, 요약 JSON은 stdout)")

    args = parser.parse_args()

    if args.history:
        if not args.file:
            parser.error("--history 조회 시 --file 인자가 필요합니다.")
        raw_file = os.path.abspath(args.file)
        file_stem = os.path.splitext(os.path.basename(raw_file))[0]
        data_root = os.path.join(os.path.dirname(raw_file), f"{file_stem}_ml_data")
        run_cli(lambda: print_history_summary(data_root))
        return

    if not args.file or not args.targets or not args.features:
        parser.error("--file, --features(-x), --targets(-y)는 모델 학습에 필수적인 인자입니다.")

    run_cli(lambda: execute_ml_train(args), hint="Check column names or formula syntax.")


if __name__ == "__main__":
    main()
