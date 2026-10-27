# -*- coding: utf-8 -*-
"""
ml_predict.py - Zero-Office Ultra-Fast Standalone ML Inference Engine.
Supports Directory Targeting (v1/, v2/) or Specific Model/Meta File Targeting.
Handles Batch Files (.csv, .xlsx) or Inline Single/Multi Record Inferences.

100% Standalone: Pure Python, Scikit-learn, Pandas, NumPy, and Joblib.
Designed for lightweight 26B-30B LLM agents with 1-turn declarative execution.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ml_common import (  # noqa: E402
    setup_console, run_cli, JsonArgumentParser, InputError,
    load_json_file, load_data_file, coerce_numeric, apply_eval_expressions,
    build_alias_map, strip_unit, suggest_columns, warn_long_path,
    save_with_lock_fallback, write_csv_excel_compatible,
)

setup_console()

import re
import glob
import json
import argparse
import warnings
from datetime import datetime
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd
import joblib

warnings.filterwarnings("ignore", category=UserWarning)


# ==============================================================================
# 1. Derived Feature Replay (shared AST sandbox, identical to training)
# ==============================================================================

def apply_inference_evals(df: pd.DataFrame, eval_expressions: List[str]) -> pd.DataFrame:
    """Applies derived feature formulas recorded in model metadata prior to inference."""
    df_out, _, _ = apply_eval_expressions(df, eval_expressions, strict=False)
    return df_out


def align_input_columns(df: pd.DataFrame, required: List[str], derived: List[str]) -> Dict[str, str]:
    """
    Renames input columns written without unit suffix to the trained full name
    ('반응온도' -> '반응온도(°C)'), in place. Only unique, unambiguous matches are applied.
    """
    applied: Dict[str, str] = {}
    present = set(str(c) for c in df.columns)
    input_alias = build_alias_map([str(c) for c in df.columns])
    for feat in required:
        if feat in present or feat in derived:
            continue
        key = re.sub(r"\s+", "", strip_unit(feat)).lower()
        src = input_alias.get(key)
        if src is not None and src not in required and strip_unit(src) == src.strip():
            df.rename(columns={src: feat}, inplace=True)
            present.discard(src)
            present.add(feat)
            applied[src] = feat
            sys.stderr.write(f"[INFO] 입력 컬럼명 자동 매칭: '{src}' -> '{feat}'\n")
    return applied


# ==============================================================================
# 4. Target Model Resolution (Directory Mode vs Specific File Mode)
# ==============================================================================

def resolve_target_models(
    target_path: str,
    meta_path: Optional[str] = None,
    filter_targets: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Resolves model and metadata pairs from a directory (v1/, v2/) or specific file.
    Returns a list of dicts:
    [{"target": "생산효율", "joblib_path": "...", "meta_path": "...", "meta": {...}, "pipeline": ...}]
    """
    abs_path = os.path.abspath(target_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"지정한 모델 경로를 찾을 수 없습니다: {abs_path}")

    model_items = []

    if os.path.isdir(abs_path):
        # Directory Mode: discover all model_*.joblib files
        joblib_files = glob.glob(os.path.join(abs_path, "model_*.joblib"))
        if not joblib_files:
            raise FileNotFoundError(f"해당 폴더 내에 'model_*.joblib' 모델 파일이 존재하지 않습니다: {abs_path}")

        for j_path in joblib_files:
            fname = os.path.basename(j_path)
            # Match model_{target}.joblib
            match = re.match(r"^model_(.+)\.joblib$", fname)
            if not match:
                continue
            target_name = match.group(1)

            m_path = os.path.join(abs_path, f"model_{target_name}.json")
            meta_dict = {}
            if os.path.exists(m_path):
                try:
                    with open(m_path, "r", encoding="utf-8") as f:
                        meta_dict = json.load(f)
                except Exception as e:
                    sys.stderr.write(f"[WARN] 메타데이터 로드 실패 ({m_path}): {e}\n")

            display_target = meta_dict.get("target", target_name)
            if filter_targets:
                wanted = set(filter_targets) | {strip_unit(t) for t in filter_targets}
                if not ({display_target, target_name, strip_unit(display_target)} & wanted):
                    continue

            model_items.append({
                "target": display_target,
                "target_safe": target_name,
                "joblib_path": j_path,
                "meta_path": m_path if os.path.exists(m_path) else None,
                "meta": meta_dict
            })

    else:
        # Specific File Mode
        j_path = abs_path
        if not j_path.endswith(".joblib"):
            raise InputError(f"모델 파일은 '.joblib' 확장자여야 합니다: {j_path}")

        fname = os.path.basename(j_path)
        match = re.match(r"^model_(.+)\.joblib$", fname)
        target_name = match.group(1) if match else os.path.splitext(fname)[0]

        # Resolve Meta Path
        m_path = meta_path
        if not m_path:
            cand_m = os.path.join(os.path.dirname(j_path), f"model_{target_name}.json")
            if os.path.exists(cand_m):
                m_path = cand_m
            else:
                cand_m2 = os.path.splitext(j_path)[0] + ".json"
                if os.path.exists(cand_m2):
                    m_path = cand_m2

        meta_dict = {}
        if m_path and os.path.exists(m_path):
            try:
                with open(m_path, "r", encoding="utf-8") as f:
                    meta_dict = json.load(f)
            except Exception as e:
                sys.stderr.write(f"[WARN] 메타데이터 로드 실패 ({m_path}): {e}\n")

        model_items.append({
            "target": meta_dict.get("target", target_name),
            "joblib_path": j_path,
            "meta_path": m_path,
            "meta": meta_dict
        })

    if not model_items:
        raise InputError(f"조건에 일치하는 대상 모델을 찾을 수 없습니다 (filter={filter_targets})")

    # Load Pipelines (warn on scikit-learn version mismatch between training and serving PCs)
    try:
        import sklearn
        sk_now = sklearn.__version__
    except Exception:
        sk_now = None
    for item in model_items:
        sk_train = item["meta"].get("sklearn_version")
        if sk_train and sk_now and sk_train != sk_now:
            sys.stderr.write(
                f"[WARN] scikit-learn 버전 불일치: 학습={sk_train}, 현재={sk_now}. "
                f"폐쇄망 PC 간 동일 버전 wheel 설치를 권장합니다.\n"
            )
        try:
            item["pipeline"] = joblib.load(item["joblib_path"])
        except Exception as e:
            raise InputError(
                f"Joblib 모델 로드 실패 ({item['joblib_path']}): {e}. "
                f"학습 PC와 scikit-learn 버전(학습={sk_train or '미기록'}, 현재={sk_now})이 다르면 동일 버전으로 맞추십시오."
            )

    return model_items


# ==============================================================================
# 5. Core Prediction Engine
# ==============================================================================

def parse_inline_input(input_str: str) -> pd.DataFrame:
    """
    Parses inline input into a DataFrame:
    - path to a .json file (recommended on Windows: no shell quote escaping)
    - JSON object/array string
    - 'k1=v1,k2=v2' pairs
    """
    clean_str = input_str.strip()
    if clean_str.lower().endswith(".json") and os.path.isfile(clean_str):
        obj = load_json_file(clean_str)
        if isinstance(obj, dict):
            return pd.DataFrame([obj])
        if isinstance(obj, list) and obj:
            return pd.DataFrame(obj)
        raise InputError(f"입력 JSON 파일은 객체 또는 객체 배열이어야 합니다: {clean_str}")
    if clean_str.startswith("{") or clean_str.startswith("["):
        try:
            obj = json.loads(clean_str)
        except Exception as e:
            raise InputError(f"인라인 JSON 파싱 실패: {e}. Windows에서는 'k1=v1,k2=v2' 형식이나 .json 파일 경로를 권장합니다.")
        if isinstance(obj, dict):
            return pd.DataFrame([obj])
        if isinstance(obj, list) and obj:
            return pd.DataFrame(obj)
        raise InputError("인라인 JSON은 객체 또는 객체 배열이어야 합니다.")

    # key=val, key2=val2 format
    row_dict = {}
    for pair in clean_str.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            k = k.strip()
            v = v.strip()
            # Try numeric parse
            try:
                v = float(v)
            except Exception:
                pass
            row_dict[k] = v
    if not row_dict:
        raise InputError(f"유효한 인라인 입력 형식이 아닙니다 (JSON 또는 'k1=v1,k2=v2'): '{input_str}'")
    return pd.DataFrame([row_dict])


def execute_predict(args: argparse.Namespace) -> Dict[str, Any]:
    """Orchestrates 1-Turn declarative inference."""
    # 1. Resolve Targets & Models
    filter_targets = [t.strip() for t in args.targets.split(",") if t.strip()] if args.targets else None
    model_items = resolve_target_models(
        target_path=args.model,
        meta_path=args.meta,
        filter_targets=filter_targets
    )

    # 2. Resolve Input Data (Batch File or Inline Input)
    if args.input:
        df_input = parse_inline_input(args.input)
        is_inline = True
        source_desc = f"Inline Input ({len(df_input)} record(s))"
    elif args.file:
        df_input = load_data_file(
            file_path=args.file,
            header_row=args.header_row,
            unit_row=args.unit_row,
            data_row=args.data_row
        )
        is_inline = False
        source_desc = os.path.basename(args.file)
    else:
        raise InputError("추론할 입력 데이터(--file 또는 --input)를 지정해야 합니다.")

    df_result = df_input.copy()
    predictions_summary = {}
    drift_warnings: List[str] = []
    column_aliases: Dict[str, str] = {}

    # 3. Perform Inference per Target
    for item in model_items:
        target_name = item["target"]
        pipe = item["pipeline"]
        meta = item["meta"]

        req_features = meta.get("features_required", [])
        derived_evals = meta.get("derived_evals", [])
        feature_stats = meta.get("feature_stats", {})
        if not req_features:
            raise InputError(
                f"타겟 '{target_name}'의 메타데이터(model_*.json)에 features_required가 없습니다. "
                f"모델과 같은 폴더의 .json 파일을 확인하거나 --meta로 지정하십시오."
            )
        derived_names = [e.split("=", 1)[0].strip() for e in derived_evals if "=" in e]

        # Accept unit-less input column names, then replay derived features
        column_aliases.update(align_input_columns(df_input, req_features, derived_names))
        df_evaled = apply_inference_evals(df_input, derived_evals)

        # Check required features
        missing_feats = [f for f in req_features if f not in df_evaled.columns]
        if missing_feats:
            available_cols = [str(c) for c in df_evaled.columns]
            hints = [f"'{m}' -> [추천] {suggest_columns(m, available_cols)}" for m in missing_feats
                     if suggest_columns(m, available_cols)]
            raise InputError(
                f"타겟 '{target_name}' 추론에 필요한 필수 피처 '{', '.join(missing_feats)}'이(가) 입력 데이터에 누락되었습니다. "
                + (" / ".join(hints) + " " if hints else "")
                + f"\n[입력 데이터 컬럼 목록]: {available_cols}"
            )

        # Same numeric parsing as training (thousands separators, '-', 'N/A', pandas 2/3 dtypes)
        X_frame = pd.DataFrame({f: coerce_numeric(df_evaled[f]) for f in req_features}, index=df_evaled.index)

        # Data Drift / Out-of-bounds Check (with quantitative severity ratio)
        if feature_stats:
            for fname in req_features:
                if fname in feature_stats:
                    f_min = feature_stats[fname].get("min")
                    f_max = feature_stats[fname].get("max")
                    if f_min is not None and f_max is not None:
                        col_series = X_frame[fname].dropna()
                        if not col_series.empty:
                            c_min = float(col_series.min())
                            c_max = float(col_series.max())
                            f_range = max(f_max - f_min, 1e-6)
                            n_out = int(((col_series > f_max) | (col_series < f_min)).sum())

                            if c_max > f_max:
                                over_pct = round(float((c_max - f_max) / f_range * 100), 1)
                                drift_warnings.append(
                                    f"피처 '{fname}' 상한 초과 외삽(Extrapolation) 감지: 학습 최대={f_max:.2f}, 입력 최대={c_max:.2f} (범위 대비 +{over_pct}% 초과 이탈, 범위 밖 {n_out}건)"
                                )
                            if c_min < f_min:
                                under_pct = round(float((f_min - c_min) / f_range * 100), 1)
                                drift_warnings.append(
                                    f"피처 '{fname}' 하한 미달 외삽(Extrapolation) 감지: 학습 최소={f_min:.2f}, 입력 최소={c_min:.2f} (범위 대비 -{under_pct}% 미달 이탈, 범위 밖 {n_out}건)"
                                )

        # Execute Prediction
        preds = pipe.predict(X_frame.values)

        pred_col_name = f"pred_{target_name}"
        df_result[pred_col_name] = np.round(preds, 4)

        # Record summary
        desc = meta.get("description", "")
        predictions_summary[target_name] = {
            "model": meta.get("champion_model", type(pipe.named_steps.get("regressor", pipe)).__name__),
            "description": desc,
            "features_used": req_features,
            "mean_pred": round(float(np.mean(preds)), 4),
            "min_pred": round(float(np.min(preds)), 4),
            "max_pred": round(float(np.max(preds)), 4)
        }
        if is_inline and len(preds) <= 5:
            predictions_summary[target_name]["predictions"] = [round(float(p), 4) for p in preds]

    # 4. Save Output if Requested or File-based
    out_path = args.out
    saved_file = None
    if out_path:
        saved_file = os.path.abspath(out_path)
    elif not is_inline and args.file:
        file_dir = os.path.dirname(os.path.abspath(args.file))
        file_stem = os.path.splitext(os.path.basename(args.file))[0]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_file = os.path.join(file_dir, f"{file_stem}_pred_{ts}.csv")

    if saved_file:
        warn_long_path(saved_file)
        os.makedirs(os.path.dirname(saved_file), exist_ok=True)
        ext = os.path.splitext(saved_file)[1].lower()
        if ext in [".xlsx", ".xls"]:
            if ext == ".xls":
                saved_file = os.path.splitext(saved_file)[0] + ".xlsx"
            saved_file = save_with_lock_fallback(
                saved_file, lambda p: df_result.to_excel(p, index=False), what="결과 Excel 파일")
        else:
            # CSV Output with Windows Excel CP949 compatibility (utf-8-sig fallback)
            saved_file = write_csv_excel_compatible(df_result, saved_file, encoding=getattr(args, "encoding", None))

    # 5. Build Response
    drift_warnings = list(dict.fromkeys(drift_warnings))  # same feature is checked once per target
    for w in drift_warnings:
        sys.stderr.write(f"[WARN] Extrapolation detected: {w}\n")

    targets_brief = ", ".join([f"{t}({predictions_summary[t]['mean_pred']})" for t in predictions_summary])
    preview = (
        f"[추론 완료] 소스: {source_desc} | 타겟 평균 예측값: [{targets_brief}] | "
        f"{'저장: ' + os.path.basename(saved_file) if saved_file else '인라인 반환'}"
        + (f" | 외삽 경고 {len(drift_warnings)}건" if drift_warnings else "")
    )
    agent_directive = (
        f"VERIFIED: Prediction completed for {len(model_items)} target(s)"
        + (" with extrapolation warning (inputs outside training range; predictions may be unreliable)" if drift_warnings else "")
        + ". "
        + (f"Output saved to {os.path.basename(saved_file)}. " if saved_file else "Inline predictions returned. ")
        + "Next step: report inference results to user."
    )

    result = {
        "status": "ok",
        "source": source_desc,
        "sample_count": len(df_result),
        "total_rows": len(df_result),
        "targets_predicted": list(predictions_summary.keys()),
        "output_file": saved_file,
        "predictions_summary": predictions_summary,
        "drift_warning": bool(drift_warnings),
        "drift_warnings": drift_warnings,
        "extrapolation_warnings": drift_warnings,
        "preview": preview,
        "agent_directive": agent_directive
    }
    if column_aliases:
        result["column_aliases"] = column_aliases
    return result


# ==============================================================================
# 6. CLI Entry Point
# ==============================================================================

def main():
    parser = JsonArgumentParser(
        description="Zero-Office Ultra-Fast Standalone ML Inference Engine (Folder or Specific Files)"
    )
    parser.add_argument(
        "--model", "-m", required=True,
        help="학습 산출물 버전 폴더 경로(예: sample_v2_ml_data/v1/) 또는 개별 .joblib 파일 경로"
    )
    parser.add_argument(
        "--meta",
        help="개별 .joblib 지정 시 동반할 .json 메타데이터 파일 경로 (생략 시 동일 폴더 자동 탐지)"
    )
    parser.add_argument(
        "--targets", "-y",
        help="예측할 특정 타겟 목록 (쉼표 구분, 폴더 모드에서 생략 시 폴더 내 모든 타겟 모델 자동 추론)"
    )
    parser.add_argument(
        "--file", "-f",
        help="배치 추론 대상 데이터 파일 경로 (.xlsx, .csv)"
    )
    parser.add_argument(
        "--input", "-i",
        help="단일/인라인 추론용 입력 데이터 ('k1=v1,k2=v2' 형식, JSON 문자열, 또는 .json 파일 경로)"
    )
    parser.add_argument(
        "--out", "-o",
        help="예측 결과 저장 파일 경로 (.csv, .xlsx, 생략 시 원본 파일 위치에 pred_*.csv 자동 생성)"
    )
    parser.add_argument("--header-row", type=int, help="컬럼명 헤더 행 번호 (1-based, 미지정 시 상단 빈 행 자동 건너뜀)")
    parser.add_argument("--unit-row", type=int, help="단위 행 번호 (선택)")
    parser.add_argument("--data-row", type=int, help="데이터 시작 행 번호 (선택)")
    parser.add_argument("--encoding", help="결과 CSV 저장 인코딩 (기본값: Windows Excel 최적화 cp949)")

    args = parser.parse_args()

    if not args.file and not args.input:
        parser.error("추론을 수행하려면 --file (배치 파일) 또는 --input (인라인 데이터) 중 하나를 지정해야 합니다.")

    run_cli(lambda: execute_predict(args), hint="Check model path or feature names.")


if __name__ == "__main__":
    main()
