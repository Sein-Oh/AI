# -*- coding: utf-8 -*-
"""
ml_train.py - Autonomous Regression Machine Learning Engine with
Collision-Free AST Feature Engineering, 5-Model Competitive Benchmark,
Atomic Version Packaging, and Single Source of Truth (SSOT) Ledger.

Designed for lightweight 26B-30B LLM agents with 1-turn declarative execution.
100% Standalone: Pure Python, Scikit-learn, Pandas, NumPy, and Joblib.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ml_common import (  # noqa: E402
    setup_console, emit_json_response, dumps_json, run_cli, JsonArgumentParser,
    InputError, sanitize_filename, normalize_version, warn_long_path,
    read_text_file, load_json_file, resolve_column_names, coerce_numeric,
    load_data_file as _load_table, apply_eval_expressions,
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
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import r2_score, mean_absolute_error, root_mean_squared_error
from sklearn.inspection import permutation_importance
from sklearn.exceptions import ConvergenceWarning

# 5 Core Regression Algorithms
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor, ExtraTreesRegressor
from sklearn.linear_model import Ridge, ElasticNet

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=ConvergenceWarning)


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
    dtypes_arg: Optional[str] = None
) -> Tuple[pd.DataFrame, List[str], List[str], Dict[str, str]]:
    """
    Validates explicit feature (X) and target (Y) columns.
    - Exact names first, then unique unit-less aliases ('생산효율' -> '생산효율(%)').
    - Fail-fast with suggestions and the available columns list if spelling fails.
    - Converts every X/Y column to float regardless of pandas version (object / str dtype),
      stripping thousands separators and placeholder strings ('-', 'N/A', '미측정', ...).
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

    # Sanitize numerical columns (works for pandas 2 'object' and pandas 3 'str' dtypes)
    for col in feature_names + target_names:
        if pd.api.types.is_datetime64_any_dtype(df_clean[col]):
            raise InputError(
                f"컬럼 '{col}'은(는) 날짜/시간 타입이라 회귀 피처로 직접 사용할 수 없습니다. "
                f"-x 목록에서 제외하거나 --eval로 수치 파생변수를 만드십시오."
            )
        df_clean[col] = coerce_numeric(df_clean[col])

    all_nan = [c for c in feature_names + target_names if df_clean[c].notna().sum() == 0]
    if all_nan:
        raise InputError(
            f"컬럼 {all_nan}에 숫자로 변환 가능한 값이 하나도 없습니다. 헤더/데이터 시작 행(--header-row, --data-row)을 확인하십시오."
        )

    return df_clean, feature_names, target_names, {**feat_alias, **tgt_alias}


# ==============================================================================
# 5. 5-Model Competitive Regression Pool
# ==============================================================================

def get_regression_models(seed: int = 42) -> Dict[str, Any]:
    """
    Returns 5 distinct, mathematically diverse regression models:
    1. HistGradientBoostingRegressor (GBDT, non-linear, robust)
    2. RandomForestRegressor (Bagging ensemble, variance reduction)
    3. ExtraTreesRegressor (Extremely randomized trees, tabular smooth)
    4. Ridge (L2 regularized linear, multicollinearity guard)
    5. ElasticNet (L1 + L2 regularized linear, sparse feature selection)
    """
    return {
        "HistGradientBoosting": HistGradientBoostingRegressor(random_state=seed),
        "RandomForest": RandomForestRegressor(n_estimators=100, random_state=seed, n_jobs=-1),
        "ExtraTrees": ExtraTreesRegressor(n_estimators=100, random_state=seed, n_jobs=-1),
        "Ridge": Ridge(alpha=1.0),
        "ElasticNet": ElasticNet(alpha=1.0, l1_ratio=0.5, random_state=seed, max_iter=2000)
    }


def train_and_benchmark_models(
    X_df: pd.DataFrame,
    y_series: pd.Series,
    target_name: str,
    feature_names: List[str],
    seed: int = 42,
    log_offset: int = 20,
    log_weight: int = 50
) -> Tuple[Dict[str, Any], Any, Dict[str, Any]]:
    """
    Performs 5-Fold Leakage-Free Cross-Validation across the 5 models.
    Selects champion model by Out-of-Fold (OOF) R2 score.
    Fits champion model on 100% of data and extracts permutation feature importance.
    """
    valid_mask = y_series.notna()
    X = X_df.loc[valid_mask, feature_names].values
    y = y_series.loc[valid_mask].values

    if len(y) < 10:
        raise InputError(f"타겟 '{target_name}'의 유효 학습 샘플 수가 너무 적습니다 ({len(y)}개). 최소 10개 이상 필요합니다.")

    models = get_regression_models(seed=seed)
    model_count = len(models)
    # Dynamic K-Fold split: adapts gracefully to small sample sizes (N < 25)
    n_splits = min(5, max(2, len(y) // 3))
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)

    leaderboard = []
    model_oof_map = {}

    for m_idx, (model_name, regressor) in enumerate(models.items()):
        oof_preds = np.zeros(len(y))
        train_r2_list = []

        for fold, (train_idx, val_idx) in enumerate(kf.split(X, y), 1):
            pct = log_offset + int(log_weight * (m_idx * n_splits + fold) / (model_count * n_splits))
            log_progress(pct, f"Target '{target_name}' | {model_name} (Fold {fold}/{n_splits})...")

            X_tr, y_tr = X[train_idx], y[train_idx]
            X_va, y_va = X[val_idx], y[val_idx]

            # Leakage-Free Pipeline: fitted ONLY on training fold
            pipe = Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("regressor", regressor)
            ])

            pipe.fit(X_tr, y_tr)
            tr_pred = pipe.predict(X_tr)
            va_pred = pipe.predict(X_va)

            train_r2_list.append(r2_score(y_tr, tr_pred))
            oof_preds[val_idx] = va_pred
            del pipe  # Explicit memory cleanup per fold

        model_oof_map[model_name] = oof_preds
        val_r2 = float(r2_score(y, oof_preds))
        mae = float(mean_absolute_error(y, oof_preds))
        rmse = float(root_mean_squared_error(y, oof_preds))
        avg_train_r2 = float(np.mean(train_r2_list))
        overfit_gap = float(avg_train_r2 - val_r2)

        leaderboard.append({
            "model_name": model_name,
            "val_r2": round(val_r2, 4),
            "train_r2": round(avg_train_r2, 4),
            "overfit_gap": round(overfit_gap, 4),
            "mae": round(mae, 4),
            "rmse": round(rmse, 4)
        })

    # Sort leaderboard by val_r2 descending
    leaderboard.sort(key=lambda item: item["val_r2"], reverse=True)
    champion_entry = leaderboard[0]
    champion_name = champion_entry["model_name"]

    # Mark rank and champion flag
    for rank, entry in enumerate(leaderboard, 1):
        entry["rank"] = rank
        entry["is_champion"] = (rank == 1)

    # Calculate Residual Skewness of Champion Model
    champion_oof = model_oof_map[champion_name]
    residuals = y - champion_oof
    residual_skew = round(float(pd.Series(residuals).skew()), 4)

    # Fit Champion Model on 100% of data
    log_progress(log_offset + log_weight - 4, f"Target '{target_name}' | 1위 챔피언({champion_name}) 전체 데이터 적합 중...")
    champion_model_template = models[champion_name]
    final_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("regressor", champion_model_template)
    ])
    final_pipeline.fit(X, y)

    # Calculate Permutation Feature Importance
    log_progress(log_offset + log_weight - 2, f"Target '{target_name}' | 순열 피처 중요도(Feature Importance) 산출 중...")
    try:
        perm_res = permutation_importance(final_pipeline, X, y, n_repeats=5, random_state=seed)
        raw_importances = np.maximum(perm_res.importances_mean, 0)
    except Exception:
        raw_importances = np.ones(len(feature_names))

    total_imp = float(np.sum(raw_importances)) or 1.0
    feature_ranks = []
    for fname, imp in zip(feature_names, raw_importances):
        pct = round(float(imp / total_imp * 100), 1)
        feature_ranks.append({
            "feature": fname,
            "importance": round(float(imp), 4),
            "pct": pct
        })
    feature_ranks.sort(key=lambda x: x["importance"], reverse=True)

    champion_summary = {
        "champion_model": champion_name,
        "val_r2": champion_entry["val_r2"],
        "train_r2": champion_entry["train_r2"],
        "overfit_gap": champion_entry["overfit_gap"],
        "mae": champion_entry["mae"],
        "rmse": champion_entry["rmse"],
        "residual_skew": residual_skew,
        "top_features": feature_ranks[:3],
        "weak_features": [f["feature"] for f in feature_ranks if f["pct"] <= 1.0],
        "feature_importances": feature_ranks
    }

    target_benchmark_res = {
        "target": target_name,
        "sample_count": len(y),
        "champion": champion_summary,
        "leaderboard": leaderboard
    }

    return target_benchmark_res, final_pipeline, champion_summary


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
    """
    Appends experiment record to history.jsonl and automatically synchronizes
    history.json (standard indented JSON array) as Single Source of Truth (SSOT).
    """
    data_root = os.path.dirname(ledger_path)
    os.makedirs(data_root, exist_ok=True)

    # 1. Append to history.jsonl (streaming ledger)
    with open(ledger_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(dumps_json(record) + "\n")

    # 2. Synchronize history.json (standard formatted JSON array), written atomically
    json_path = os.path.join(data_root, "history.json")
    all_records = load_history_ledger(ledger_path)
    try:
        atomic_write_text(json_path, dumps_json(all_records, indent=2))
    except OSError as e:
        sys.stderr.write(f"[WARN] history.json 동기화 실패 (history.jsonl은 정상 기록됨): {e}\n")


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
# 8. Main Execution Controller
# ==============================================================================

def execute_ml_train(args: argparse.Namespace) -> Dict[str, Any]:
    """Orchestrates 1-Turn declarative regression pipeline."""
    start_time = time.time()
    raw_file = os.path.abspath(args.file)
    if not os.path.exists(raw_file):
        raise FileNotFoundError(f"입력 파일이 존재하지 않습니다: {raw_file}")
    warn_long_path(raw_file)

    file_dir = os.path.dirname(raw_file)
    file_stem = os.path.splitext(os.path.basename(raw_file))[0]
    data_root = os.path.join(file_dir, f"{file_stem}_ml_data")
    ledger_path = os.path.join(data_root, "history.jsonl")

    # Transaction Guard Setup
    guard = TransactionGuard(data_root=data_root, target_version=args.version)
    current_version = guard.setup()

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
            dtypes_arg=args.dtypes
        )

        # Feature Engineering (--eval)
        applied_evals = []
        created_features = []
        if args.eval:
            log_progress(15, "방탄 AST 파생변수 연산 중 (--eval)...")
            df_clean, applied_evals, created_features = run_safe_eval(
                df=df_clean,
                eval_str=args.eval,
                target_cols=target_names
            )
            # Add new features to feature_names if not already present
            for c_feat in created_features:
                if c_feat not in feature_names:
                    feature_names.append(c_feat)

        # Calculate Correlation Matrix (for SSOT reporting)
        log_progress(20, "변수 간 2차원 상관행렬 계산 중...")
        all_train_cols = [c for c in feature_names + target_names if c in df_clean.columns]
        num_df = df_clean[all_train_cols].select_dtypes(include=[np.number])
        corr_matrix = num_df.corr().round(4).to_dict()

        # Multi-Target 5-Model Competitive Training
        target_benchmarks = {}
        target_champions = {}
        target_summaries = {}
        all_champion_val_r2 = []

        total_targets = len(target_names)
        for t_idx, target_name in enumerate(target_names):
            t_offset = 25 + int(55 * t_idx / total_targets)
            t_weight = int(55 / total_targets)

            log_progress(t_offset, f"타겟 [{t_idx+1}/{total_targets}] '{target_name}' 5대 모델 경쟁 학습...")

            t_bench, champion_pipe, champion_info = train_and_benchmark_models(
                X_df=df_clean,
                y_series=df_clean[target_name],
                target_name=target_name,
                feature_names=feature_names,
                seed=args.seed,
                log_offset=t_offset,
                log_weight=t_weight
            )

            target_benchmarks[target_name] = t_bench
            target_champions[target_name] = {
                "pipeline": champion_pipe,
                "info": champion_info
            }
            all_champion_val_r2.append(champion_info["val_r2"])

            # Target statistics
            y_valid = df_clean[target_name].dropna()
            target_summaries[target_name] = {
                "mean": round(float(y_valid.mean()), 4),
                "std": round(float(y_valid.std()), 4),
                "min": round(float(y_valid.min()), 4),
                "max": round(float(y_valid.max()), 4)
            }

        mean_val_r2 = float(np.mean(all_champion_val_r2))

        # Check Previous History for Delta R2
        log_progress(85, "이전 이력 대조 및 성능 변화(Delta R2) 산출 중...")
        history_records = load_history_ledger(ledger_path)

        # Resolve project description: explicit arg takes precedence, otherwise inherit from previous version
        project_desc = (getattr(args, "description", None) or "").strip()
        if project_desc and os.path.isfile(project_desc):
            project_desc = read_text_file(project_desc).strip()

        if not project_desc and history_records:
            project_desc = history_records[-1].get("description", "")

        prev_best_r2 = -999.0
        last_val_r2 = None
        if history_records:
            last_record = history_records[-1]
            last_val_r2 = last_record.get("mean_val_r2", last_record.get("val_r2", None))
            prev_best_r2 = max(
                [h.get("mean_val_r2", h.get("val_r2", -999.0)) for h in history_records],
                default=-999.0
            )

        if last_val_r2 is not None:
            delta_r2 = round(mean_val_r2 - last_val_r2, 4)
        else:
            delta_r2 = "base"

        is_best = (mean_val_r2 > prev_best_r2)

        # Generate Actionable Recommendations for 26B-30B LLM
        primary_target = target_names[0]
        prim_champ = target_champions[primary_target]["info"]
        top_feats = prim_champ.get("top_features", [])
        weak_feats = prim_champ.get("weak_features", [])

        recommendations = []
        if mean_val_r2 >= 0.90:
            recommendations.append(f"사전 목표 성능(Val R2 >= 0.90)을 달성하여 배포 승인 준비가 완료되었습니다.")
        elif len(top_feats) >= 2:
            f1 = top_feats[0]["feature"]
            f2 = top_feats[1]["feature"]
            recommendations.append(f"주요 기여 피처 '{f1}'와(과) '{f2}'의 교차 상호작용('{f1} * {f2}') 또는 다항식 생성을 권장합니다.")
        if weak_feats:
            recommendations.append(f"기여도가 1% 미만인 피처 {weak_feats[:2]}을(를) 배제하여 노이즈를 감소시키십시오.")

        # Stage Artifacts in .tmp_vX/
        log_progress(90, f"버전 산출물 패키징 중 ({current_version})...")
        staging_dir = guard.tmp_dir

        # 1. Unified leaderboard.json (Single file covering all targets)
        leaderboard_data = {
            "version": current_version,
            "timestamp": datetime.now().isoformat(),
            "mean_val_r2": round(mean_val_r2, 4),
            "delta_r2": delta_r2,
            "is_best": is_best,
            "targets": target_benchmarks
        }
        with open(os.path.join(staging_dir, "leaderboard.json"), "w", encoding="utf-8") as f:
            f.write(dumps_json(leaderboard_data, indent=2))

        # 2. Target Models and Metadata
        for target_name, champ_data in target_champions.items():
            pipe = champ_data["pipeline"]
            info = champ_data["info"]
            safe_target = sanitize_filename(target_name)

            # Save Model Joblib with safe filename
            joblib_path = os.path.join(staging_dir, f"model_{safe_target}.joblib")
            joblib.dump(pipe, joblib_path, compress=3)

            # Feature statistics for inference validation
            feat_stats = {}
            for fname in feature_names:
                if fname in df_clean.columns and pd.api.types.is_numeric_dtype(df_clean[fname]):
                    s = df_clean[fname].dropna()
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
                "description": project_desc,
                "champion_model": info["champion_model"],
                "val_r2": info["val_r2"],
                "mae": info["mae"],
                "rmse": info["rmse"],
                "residual_skew": info.get("residual_skew", 0.0),
                "features_required": feature_names,
                "feature_count": len(feature_names),
                "feature_stats": feat_stats,
                "derived_evals": applied_evals,
                "target_summary": target_summaries.get(target_name, {}),
                "sklearn_version": sklearn.__version__,
                "python_version": sys.version.split()[0]
            }
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
        missing_imputed = int(df_clean[feature_names].isna().sum().sum())
        prescription = recommendations[0] if recommendations else "모델 경쟁 학습 및 평가 완료"

        history_record = {
            "version": current_version,
            "timestamp": datetime.now().isoformat(),
            "tag": getattr(args, "tag", None) or "",
            "description": project_desc,
            "duration_sec": duration_sec,
            "data_hygiene": {
                "total_rows": len(df_clean),
                "total_features": len(feature_names),
                "missing_imputed": missing_imputed
            },
            "file": os.path.basename(raw_file),
            "targets": target_names,
            "target_summaries": target_summaries,
            "features_used": feature_names,
            "derived_evals": applied_evals,
            "mean_val_r2": round(mean_val_r2, 4),
            "delta_r2": delta_r2,
            "is_best": is_best,
            "prescription": prescription,
            "recommendations": recommendations,
            "targets_benchmark": target_benchmarks,
            "correlation_matrix": corr_matrix
        }
        append_history_ledger(ledger_path, history_record)

        # Commit Transaction: Atomic rename from .tmp_vX to vX
        final_version_dir = guard.commit()
        log_progress(100, f"학습 및 산출물 패키징 완료: {current_version} ({os.path.basename(final_version_dir)}) [소요: {duration_sec}초]")

        # LLM Directive
        target_brief = ", ".join([f"{t}({target_champions[t]['info']['champion_model']}: R2={target_champions[t]['info']['val_r2']:.4f})" for t in target_names])
        preview = (
            f"[{current_version} 완료] 타겟: [{target_brief}] | "
            f"평균 Val R2={mean_val_r2:.4f} (Delta: {delta_r2 if delta_r2 == 'base' else f'{delta_r2:+.4f}'}) | "
            f"소요시간: {duration_sec}s | "
            f"산출물 저장: {final_version_dir}"
        )
        agent_directive = (
            f"VERIFIED: {current_version} competitive training completed. "
            f"Champion models and leaderboard packaged into '{os.path.basename(final_version_dir)}'. "
            f"Mean Val R2={mean_val_r2:.4f}. Next step: proceed to inference or next iteration."
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
            "mean_val_r2": round(mean_val_r2, 4),
            "delta_r2": delta_r2,
            "is_best": is_best,
            "recommendations": recommendations,
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
    out.write(f"{'Version':<8} | {'Tag / Memo':<16} | {'Mean R2':<9} | {'Delta R2':<10} | {'Time':<7} | {'Targets':<22} | {'Status'}\n")
    out.write(f"{'-'*8}-+-{'-'*16}-+-{'-'*9}-+-{'-'*10}-+-{'-'*7}-+-{'-'*22}-+-{'-'*15}\n")

    rows = []
    for r in records:
        ver = r.get("version", "-")
        tag = r.get("tag") or "-"
        mean_r2 = r.get("mean_val_r2")
        delta = r.get("delta_r2", "base")
        rows.append({
            "version": ver, "tag": tag, "mean_val_r2": mean_r2, "delta_r2": delta,
            "is_best": bool(r.get("is_best")), "targets": r.get("targets", []),
        })

        tag_s = tag if len(tag) <= 15 else tag[:13] + ".."
        r2_s = f"{mean_r2:<9.4f}" if isinstance(mean_r2, (int, float)) else f"{'-':<9}"
        delta_str = f"{delta:+.4f}" if isinstance(delta, (int, float)) else str(delta)
        dur = f"{r.get('duration_sec', 0.0):.1f}s" if "duration_sec" in r else "-"
        targets_str = ", ".join(r.get("targets", []))
        if len(targets_str) > 20:
            targets_str = targets_str[:18] + ".."
        status = "[BEST 챔피언]" if r.get("is_best") else "[수렴]"
        out.write(f" {ver:<7} | {tag_s:<16} | {r2_s} | {delta_str:<10} | {dur:<7} | {targets_str:<22} | {status}\n")

    out.write("=" * 125 + "\n\n")

    scored = [x for x in rows if isinstance(x["mean_val_r2"], (int, float))]
    best = max(scored, key=lambda x: x["mean_val_r2"]) if scored else None
    return {
        "status": "ok",
        "data_root": data_root,
        "description": proj_desc,
        "record_count": len(rows),
        "best_version": best["version"] if best else None,
        "best_mean_val_r2": best["mean_val_r2"] if best else None,
        "latest_version": rows[-1]["version"],
        "records": rows,
        "agent_directive": "VERIFIED: History summary returned. Do not re-read history.json for the same information.",
    }


def main():
    parser = JsonArgumentParser(
        description="Autonomous Regression ML Engine with 5-Model Competitive Benchmark & Version Lineage"
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
