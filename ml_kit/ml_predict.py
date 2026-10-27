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

# Ensure UTF-8 clean terminal output on Windows
try:
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding.lower() != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import re
import ast
import glob
import json
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import joblib

import warnings
warnings.filterwarnings("ignore", category=UserWarning)


# ==============================================================================
# 1. Output & Console Formatting (Clean Terminal Principle - No Emojis)
# ==============================================================================

def emit_json_response(payload: Dict[str, Any]) -> None:
    """Prints standard 1-line JSON response to stdout for LLM consumption."""
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


def sanitize_filename(name: str) -> str:
    r"""Replaces characters forbidden in Windows filenames (\ / : * ? " < > |)."""
    return re.sub(r'[\\/*?:"<>|]', "_", str(name))


# ==============================================================================
# 2. Bulletproof AST Formula Sandbox for Inference
# ==============================================================================

_ALLOWED_AST_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
    ast.Load, ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd
)

def _validate_eval_ast(formula_ast: ast.AST, allowed_identifiers: set) -> None:
    for node in ast.walk(formula_ast):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise ValueError(f"보안 위반: 허용되지 않은 문법 노드 감지: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in allowed_identifiers:
            raise ValueError(f"보안 위반: 알 수 없거나 허용되지 않은 식별자 '{node.id}'")


def apply_inference_evals(df: pd.DataFrame, eval_expressions: List[str]) -> pd.DataFrame:
    """Applies derived feature formulas recorded in model metadata prior to inference."""
    if not eval_expressions:
        return df

    df = df.copy()
    safe_math = {
        "log": lambda x: np.log(np.clip(np.abs(x), 1e-9, None)),
        "log1p": lambda x: np.log1p(np.clip(np.abs(x), 0, None)),
        "log10": lambda x: np.log10(np.clip(np.abs(x), 1e-9, None)),
        "sqrt": lambda x: np.sqrt(np.clip(np.abs(x), 0, None)),
        "exp": lambda x: np.exp(np.clip(x, -50, 50)),
        "abs": np.abs,
        "sin": np.sin,
        "cos": np.cos,
        "tan": np.tan,
        "square": np.square,
        "clip": lambda x, a_min, a_max: np.clip(x, a_min, a_max),
        "pi": np.pi,
        "e": np.e,
        "radians": np.radians,
        "degrees": np.degrees,
    }

    for expr in eval_expressions:
        if "=" not in expr:
            continue
        new_col, formula = expr.split("=", 1)
        new_col = new_col.strip()
        formula = formula.strip()

        token_to_col = {}
        eval_env = dict(safe_math)
        existing_cols = sorted(df.columns, key=len, reverse=True)
        transformed_formula = formula

        for idx, col_name in enumerate(existing_cols):
            token = f"__COL_TOKEN_{idx}__"
            pattern = rf"(?<![가-힣a-zA-Z0-9_]){re.escape(col_name)}(?![가-힣a-zA-Z0-9_])"
            if re.search(pattern, transformed_formula):
                transformed_formula = re.sub(pattern, token, transformed_formula)
                token_to_col[token] = col_name
                eval_env[token] = pd.to_numeric(df[col_name], errors="coerce").astype(float)

        try:
            tree = ast.parse(transformed_formula, mode="eval")
            _validate_eval_ast(tree, set(eval_env.keys()))
            res_val = eval(transformed_formula, {"__builtins__": {}}, eval_env)
            if isinstance(res_val, (pd.Series, np.ndarray, int, float)):
                ser = pd.Series(res_val, index=df.index, dtype=float)
                ser = ser.replace([np.inf, -np.inf], np.nan)
                df[new_col] = ser
        except Exception as ex:
            sys.stderr.write(f"[WARN] 파생변수 연산 생략/실패 ('{expr}'): {ex}\n")

    return df


# ==============================================================================
# 3. Data Loader & Non-standard Layout Parser
# ==============================================================================

def load_data_file(
    file_path: str,
    header_row: Optional[int] = None,
    unit_row: Optional[int] = None,
    data_row: Optional[int] = None
) -> pd.DataFrame:
    """
    Loads inference data from CSV or Excel (.xlsx).
    Includes Auto-Header Sniffing: skips blank top rows automatically if header_row is not explicit.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"추론 대상 데이터 파일을 찾을 수 없습니다: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()

    if ext in [".xlsx", ".xls"]:
        df_raw = pd.read_excel(file_path, header=None)
    elif ext == ".csv":
        encodings = ["utf-8-sig", "utf-8", "cp949", "euc-kr", "latin1"]
        df_raw = None
        last_err = None
        for enc in encodings:
            try:
                df_raw = pd.read_csv(file_path, header=None, encoding=enc, sep=None, engine="python")
                break
            except Exception as e:
                last_err = e
                continue
        if df_raw is None:
            raise ValueError(f"CSV 파일 로드 실패 (지원되는 인코딩 모두 시도 완료): {last_err}")
    else:
        raise ValueError(f"지원하지 않는 데이터 포맷입니다 ({ext}). .xlsx 또는 .csv 파일을 지정하십시오.")

    total_rows = len(df_raw)
    if total_rows == 0:
        raise ValueError("추론 데이터 파일이 비어 있습니다.")

    # Auto-Header Sniffing: If header_row is not specified or 1, skip leading empty rows
    if header_row is not None and header_row > 1:
        header_idx = header_row - 1
    else:
        header_idx = 0
        for r_i in range(min(15, total_rows)):
            row_items = df_raw.iloc[r_i].dropna().tolist()
            if len(row_items) >= 2 and any(isinstance(v, str) and str(v).strip() for v in row_items):
                header_idx = r_i
                break

    if header_idx >= total_rows:
        raise ValueError(f"유효한 헤더 행을 찾을 수 없습니다 (전체 행 수: {total_rows}).")

    raw_headers = df_raw.iloc[header_idx].values
    headers = [str(c).strip() if pd.notna(c) and str(c).strip() else f"col_{i}" for i, c in enumerate(raw_headers)]

    if unit_row is not None and 1 <= unit_row <= total_rows:
        unit_idx = unit_row - 1
        units = df_raw.iloc[unit_idx].values
        combined_headers = []
        for h, u in zip(headers, units):
            u_str = str(u).strip() if pd.notna(u) else ""
            if u_str and u_str not in ["-", "None", "nan"]:
                combined_headers.append(f"{h}({u_str})")
            else:
                combined_headers.append(h)
        headers = combined_headers

    # De-duplicate headers
    seen_headers: Dict[str, int] = {}
    unique_headers: List[str] = []
    for h in headers:
        if h in seen_headers:
            seen_headers[h] += 1
            unique_headers.append(f"{h}_{seen_headers[h]}")
        else:
            seen_headers[h] = 0
            unique_headers.append(h)
    headers = unique_headers

    if data_row is not None:
        start_idx = max(0, data_row - 1)
    else:
        last_meta_idx = header_idx
        if unit_row is not None and 1 <= unit_row <= total_rows:
            last_meta_idx = max(header_idx, unit_row - 1)
        start_idx = last_meta_idx + 1

    if start_idx >= total_rows:
        raise ValueError(f"데이터 시작 행 ({start_idx + 1}) 이후에 유효한 데이터 행이 없습니다.")

    df_data = df_raw.iloc[start_idx:].copy()
    df_data.columns = headers
    df_data = df_data.reset_index(drop=True)
    df_data = df_data.dropna(how="all", axis=0).dropna(how="all", axis=1)

    return df_data


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
            if filter_targets and display_target not in filter_targets and target_name not in filter_targets:
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
            raise ValueError(f"모델 파일은 '.joblib' 확장자여야 합니다: {j_path}")

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
            "target": target_name,
            "joblib_path": j_path,
            "meta_path": m_path,
            "meta": meta_dict
        })

    if not model_items:
        raise ValueError(f"조건에 일치하는 대상 모델을 찾을 수 없습니다 (filter={filter_targets})")

    # Load Pipelines
    for item in model_items:
        try:
            item["pipeline"] = joblib.load(item["joblib_path"])
        except Exception as e:
            raise ValueError(f"Joblib 모델 로드 실패 ({item['joblib_path']}): {e}")

    return model_items


# ==============================================================================
# 5. Core Prediction Engine
# ==============================================================================

def parse_inline_input(input_str: str) -> pd.DataFrame:
    """Parses inline JSON string or key=val pairs into a single-row DataFrame."""
    clean_str = input_str.strip()
    if clean_str.startswith("{") or clean_str.startswith("["):
        try:
            obj = json.loads(clean_str)
            if isinstance(obj, dict):
                return pd.DataFrame([obj])
            elif isinstance(obj, list):
                return pd.DataFrame(obj)
        except Exception as e:
            raise ValueError(f"인라인 JSON 파싱 실패: {e}")

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
        raise ValueError(f"유효한 인라인 입력 형식이 아닙니다 (JSON 또는 'k1=v1,k2=v2'): '{input_str}'")
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
        raise ValueError("추론할 입력 데이터(--file 또는 --input)를 지정해야 합니다.")

    df_result = df_input.copy()
    predictions_summary = {}
    drift_warnings = []

    # 3. Perform Inference per Target
    for item in model_items:
        target_name = item["target"]
        pipe = item["pipeline"]
        meta = item["meta"]

        req_features = meta.get("features_required", [])
        derived_evals = meta.get("derived_evals", [])
        feature_stats = meta.get("feature_stats", {})

        # Apply derived features if specified in metadata
        df_evaled = apply_inference_evals(df_input, derived_evals)

        # Check required features
        missing_feats = [f for f in req_features if f not in df_evaled.columns]
        if missing_feats:
            available_cols = list(df_evaled.columns)
            raise ValueError(
                f"타겟 '{target_name}' 추론에 필요한 필수 피처 '{', '.join(missing_feats)}'이(가) 입력 데이터에 누락되었습니다.\n"
                f"[입력 데이터 컬럼 목록]: {available_cols}"
            )

        # Data Drift / Out-of-bounds Check (with quantitative severity ratio)
        if feature_stats:
            for fname in req_features:
                if fname in df_evaled.columns and fname in feature_stats:
                    f_min = feature_stats[fname].get("min")
                    f_max = feature_stats[fname].get("max")
                    if f_min is not None and f_max is not None:
                        col_series = pd.to_numeric(df_evaled[fname], errors="coerce").dropna()
                        if not col_series.empty:
                            c_min = float(col_series.min())
                            c_max = float(col_series.max())
                            f_range = max(f_max - f_min, 1e-6)

                            if c_max > f_max:
                                over_pct = round(float((c_max - f_max) / f_range * 100), 1)
                                drift_warnings.append(
                                    f"피처 '{fname}' 상한 초과 외삽(Extrapolation) 감지: 학습 최대={f_max:.2f}, 입력 최대={c_max:.2f} (범위 대비 +{over_pct}% 초과 이탈)"
                                )
                            if c_min < f_min:
                                under_pct = round(float((f_min - c_min) / f_range * 100), 1)
                                drift_warnings.append(
                                    f"피처 '{fname}' 하한 미달 외삽(Extrapolation) 감지: 학습 최소={f_min:.2f}, 입력 최소={c_min:.2f} (범위 대비 -{under_pct}% 미달 이탈)"
                                )

        # Execute Prediction
        X_infer = df_evaled[req_features].values
        preds = pipe.predict(X_infer)

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
        os.makedirs(os.path.dirname(saved_file), exist_ok=True)
        ext = os.path.splitext(saved_file)[1].lower()
        if ext in [".xlsx", ".xls"]:
            df_result.to_excel(saved_file, index=False)
        else:
            # CSV Output with Windows Excel CP949 compatibility
            target_encoding = getattr(args, "encoding", None)
            if not target_encoding:
                try:
                    df_result.to_csv(saved_file, index=False, encoding="cp949")
                except (UnicodeEncodeError, LookupError):
                    df_result.to_csv(saved_file, index=False, encoding="utf-8-sig")
            else:
                try:
                    df_result.to_csv(saved_file, index=False, encoding=target_encoding)
                except Exception:
                    df_result.to_csv(saved_file, index=False, encoding="utf-8-sig")

    # 5. Build Response
    targets_brief = ", ".join([f"{t}({predictions_summary[t]['mean_pred']})" for t in predictions_summary])
    preview = (
        f"[추론 완료] 소스: {source_desc} | 타겟 평균 예측값: [{targets_brief}] | "
        f"{'저장: ' + os.path.basename(saved_file) if saved_file else '인라인 반환'}"
    )
    agent_directive = (
        f"VERIFIED: Prediction completed for {len(model_items)} target(s). "
        f"{'Output saved to ' + os.path.basename(saved_file) if saved_file else 'Inline predictions returned'}. "
        f"Next step: report inference results to user."
    )

    return {
        "status": "ok",
        "source": source_desc,
        "sample_count": len(df_result),
        "targets_predicted": list(predictions_summary.keys()),
        "output_file": saved_file,
        "predictions_summary": predictions_summary,
        "drift_warnings": drift_warnings,
        "preview": preview,
        "agent_directive": agent_directive
    }


# ==============================================================================
# 6. CLI Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
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
        help="단일/인라인 추론용 입력 데이터 (JSON 문자열 또는 'k1=v1,k2=v2' 형식)"
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
        emit_json_response({
            "status": "error",
            "message": "추론을 수행하려면 --file (배치 파일) 또는 --input (인라인 데이터) 중 하나를 지정해야 합니다."
        })
        sys.exit(1)

    try:
        res = execute_predict(args)
        emit_json_response(res)
    except Exception as e:
        sys.stderr.write(f"\n[ERROR] {str(e)}\n")
        emit_json_response({
            "status": "error",
            "message": str(e),
            "agent_directive": f"ERROR: Prediction execution failed ({e}). Check model path or feature names."
        })
        sys.exit(1)


if __name__ == "__main__":
    main()
