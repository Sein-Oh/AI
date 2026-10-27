# -*- coding: utf-8 -*-
"""
ml_predict.py - Zero-Office Ultra-Fast Standalone ML Inference Engine.
Supports Directory Targeting (v1/, v2/) or Specific Model/Meta File Targeting.
Handles Batch Files (.csv, .xlsx) or Inline Single/Multi Record Inferences.

DEPLOYMENT: this single file + a trained version folder (vX/) is a complete
inference package. It has no dependency on the other ml_kit files.
Requires only NumPy, Pandas, Scikit-learn, Joblib (+ openpyxl for .xlsx).

This file is also the SHARED RUNTIME of ml_kit (section C*): ml_train.py and
ml_report.py import data loading, numeric coercion, the --eval formula engine,
the Agent CLI Protocol and Windows-safe file helpers from here, so training and
inference can never drift apart.

Designed for lightweight 26B-30B LLM agents with 1-turn declarative execution.
"""

import sys
import os
import re
import ast
import glob
import json
import time
import shutil
import difflib
import argparse
import warnings
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Callable

import numpy as np
import pandas as pd
import joblib

warnings.filterwarnings("ignore", category=UserWarning)


# ##############################################################################
# PART C. SHARED RUNTIME (imported by ml_train.py / ml_report.py)
# ##############################################################################

# ==============================================================================
# C1. Console & Agent CLI Protocol (Clean Terminal Principle - No Emojis)
# ==============================================================================

def setup_console() -> None:
    """Forces UTF-8 on stdout/stderr (Windows consoles and pipes default to CP949)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and (stream.encoding or "").lower() != "utf-8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def json_safe(obj: Any) -> Any:
    """Converts NumPy scalars/arrays and NaN/Inf into strict-JSON-compatible values."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [json_safe(v) for v in obj.tolist()]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if np.isfinite(f) else None
    return obj


def dumps_json(obj: Any, indent: Optional[int] = None) -> str:
    return json.dumps(json_safe(obj), ensure_ascii=False, indent=indent)


def emit_json_response(payload: Dict[str, Any]) -> None:
    """Prints standard 1-line JSON response to stdout for LLM consumption."""
    setup_console()
    sys.stdout.write(dumps_json(payload) + "\n")
    sys.stdout.flush()


class InputError(ValueError):
    """User/agent input or data schema problem. Retrying with the same arguments will not help."""


# Exceptions caused by arguments, data schema or environment (not by a bug in the tool)
_STOP_RETRY_ERRORS = (ValueError, KeyError, FileNotFoundError, NotADirectoryError,
                      IsADirectoryError, PermissionError)


def error_payload(exc: BaseException, hint: str = "") -> Dict[str, Any]:
    """Builds the standard error JSON with an agent_directive the LLM can act on deterministically."""
    msg = str(exc) or type(exc).__name__
    if isinstance(exc, KeyboardInterrupt):
        return {
            "status": "error",
            "error_type": "interrupted",
            "message": "사용자 또는 상위 프로세스에 의해 실행이 중단되었습니다. 임시 산출물은 롤백되었습니다.",
            "agent_directive": "STOP_RETRY: Execution was interrupted. Ask the user before running again.",
        }
    if isinstance(exc, _STOP_RETRY_ERRORS):
        return {
            "status": "error",
            "error_type": "input",
            "message": msg,
            "agent_directive": (
                "STOP_RETRY: Argument or data schema validation failed. "
                "If the message contains '[추천]', re-run ONCE with the suggested name; "
                "otherwise report the message to the user." + (f" {hint}" if hint else "")
            ),
        }
    return {
        "status": "error",
        "error_type": "internal",
        "message": f"{type(exc).__name__}: {msg}",
        "agent_directive": "ERROR: Unexpected internal failure. Do not retry; report the message to the user.",
    }


def run_cli(execute: Callable[[], Dict[str, Any]], hint: str = "") -> None:
    """Runs a tool body, guaranteeing exactly one JSON line on stdout and exit code 0/1/130."""
    try:
        result = execute()
    except KeyboardInterrupt as e:
        sys.stderr.write("\n[ERROR] 실행 중단 (KeyboardInterrupt)\n")
        emit_json_response(error_payload(e))
        sys.exit(130)
    except Exception as e:
        sys.stderr.write(f"\n[ERROR] {e}\n")
        emit_json_response(error_payload(e, hint))
        sys.exit(1)
    emit_json_response(result)


class JsonArgumentParser(argparse.ArgumentParser):
    """argparse that reports usage errors as Agent CLI Protocol JSON instead of bare text."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        emit_json_response({
            "status": "error",
            "error_type": "input",
            "message": f"CLI 인자 오류: {message}",
            "agent_directive": "STOP_RETRY: Invalid CLI arguments. Check the option names in SKILL.md and report to the user.",
        })
        sys.exit(2)


def sanitize_filename(name: str) -> str:
    r"""
    Replaces characters forbidden in Windows filenames (\ / : * ? " < > |).
    Guarantees targets like '유속(m/s)' or '비용(원/kg)' save safely on Windows filesystem.
    """
    return re.sub(r'[\\/*?:"<>|]', "_", str(name))


def normalize_version(v: Optional[str]) -> Optional[str]:
    """'2', 'V2', ' v2 ' -> 'v2'."""
    if v is None:
        return None
    s = str(v).strip().lower()
    if not s:
        return None
    return s if s.startswith("v") else f"v{s}"


def warn_long_path(path: str) -> None:
    """Windows without LongPathsEnabled fails on paths >= 260 chars."""
    if os.name == "nt" and len(os.path.abspath(path)) > 240:
        sys.stderr.write(
            f"[WARN] 경로 길이가 {len(os.path.abspath(path))}자로 Windows 260자 제한에 근접합니다. "
            f"저장 실패 시 데이터 파일을 더 짧은 경로(예: C:\\work\\)로 옮기십시오.\n"
        )


# ==============================================================================
# C2. Encoding-tolerant File Reading (Windows Notepad / PowerShell / Excel outputs)
# ==============================================================================

def read_text_file(path: str) -> str:
    """Reads text written by any common Windows tool (UTF-8 +/- BOM, UTF-16 BOM, CP949/EUC-KR)."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise InputError(f"텍스트 파일 인코딩 인식 실패 (UTF-8/UTF-16/CP949 아님): {path}")


def load_json_file(path: str) -> Any:
    try:
        return json.loads(read_text_file(path))
    except json.JSONDecodeError as e:
        raise InputError(f"JSON 파일 파싱 실패 ({path}): {e}")


# ==============================================================================
# C3. Column Name Resolution (unit-suffix aliases & typo suggestions)
# ==============================================================================

_UNIT_SUFFIX_RE = re.compile(r"\s*[\(\[][^\(\)\[\]]*[\)\]]\s*$")


def strip_unit(name: str) -> str:
    """'반응온도(°C)' -> '반응온도', '유속 [m/s]' -> '유속'."""
    return _UNIT_SUFFIX_RE.sub("", str(name)).strip()


def _alias_key(name: str) -> str:
    return re.sub(r"\s+", "", strip_unit(name)).lower()


def build_alias_map(columns: List[str]) -> Dict[str, str]:
    """Maps unit-less alias keys to their unique full column name (ambiguous aliases are dropped)."""
    groups: Dict[str, List[str]] = {}
    for c in columns:
        groups.setdefault(_alias_key(c), []).append(c)
    return {k: v[0] for k, v in groups.items() if len(v) == 1 and k}


def suggest_columns(name: str, columns: List[str], n: int = 3) -> List[str]:
    alias_hit = build_alias_map(columns).get(_alias_key(name))
    hits = [alias_hit] if alias_hit else []
    for c in difflib.get_close_matches(str(name), [str(c) for c in columns], n=n, cutoff=0.5):
        if c not in hits:
            hits.append(c)
    return hits[:n]


def resolve_column_names(names: List[str], columns: List[str], kind: str) -> Tuple[List[str], Dict[str, str]]:
    """
    Resolves requested names against real columns. Exact match first, then a unique
    unit-less alias ('생산효율' -> '생산효율(%)'). A name with a different unit
    ('반응온도(C)') is NOT auto-matched. Raises InputError with suggestions otherwise.
    """
    col_list = [str(c) for c in columns]
    col_set = set(col_list)
    alias_map = build_alias_map(col_list)
    resolved: List[str] = []
    applied: Dict[str, str] = {}
    missing: List[str] = []
    for n in names:
        if n in col_set:
            resolved.append(n)
        elif strip_unit(n) == n.strip() and _alias_key(n) in alias_map:
            # Only names written WITHOUT a unit are auto-matched; a different unit is a typo
            full = alias_map[_alias_key(n)]
            resolved.append(full)
            applied[n] = full
        else:
            missing.append(n)
    if missing:
        hints = []
        for m in missing:
            s = suggest_columns(m, col_list)
            hints.append(f"'{m}' -> [추천] {s}" if s else f"'{m}' -> 유사 컬럼 없음")
        raise InputError(
            f"지정하신 {kind} 컬럼 {missing}을(를) 데이터셋에서 찾을 수 없습니다. "
            f"{' / '.join(hints)}\n[사용 가능한 컬럼 목록]: {col_list}"
        )
    for short, full in applied.items():
        sys.stderr.write(f"[INFO] 컬럼명 자동 매칭: '{short}' -> '{full}'\n")
    return resolved, applied


# ==============================================================================
# C4. Robust Data Loader & Layout Parser with Auto-Header Sniffing
# ==============================================================================

_NA_PLACEHOLDERS = ["-", "N/A", "n/a", "NA", "null", "NULL", "미측정", "None", "nan", "NaN", ""]


def coerce_numeric(series: pd.Series) -> pd.Series:
    """
    Converts a column to float regardless of its storage dtype (object in pandas 2,
    'str' in pandas 3). Strips thousands separators and placeholder NaN strings.
    Numeric and datetime columns are returned unchanged.
    """
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
        return series
    s = series.astype("object").where(series.notna(), None)
    s = s.map(lambda v: v.replace(",", "").strip() if isinstance(v, str) else v)
    s = s.replace(_NA_PLACEHOLDERS, np.nan)
    return pd.to_numeric(s, errors="coerce").astype(float)


def load_data_file(
    file_path: str,
    header_row: Optional[int] = None,
    unit_row: Optional[int] = None,
    data_row: Optional[int] = None
) -> pd.DataFrame:
    """
    Loads tabular data from CSV (multi-encoding, auto delimiter) or Excel (.xlsx).
    Handles non-standard header, unit, and data row specifications.
    Includes Auto-Header Sniffing: skips blank/title top rows automatically if header_row is not explicit.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"입력 데이터 파일을 찾을 수 없습니다: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()

    if ext in [".xlsx", ".xlsm"]:
        try:
            df_raw = pd.read_excel(file_path, header=None)
        except ImportError:
            raise InputError("openpyxl 패키지가 설치되어 있지 않아 .xlsx를 읽을 수 없습니다. requirements.txt를 설치하십시오.")
        except PermissionError:
            raise PermissionError(f"파일이 다른 프로그램(Excel 등)에서 잠겨 있습니다. 파일을 닫고 다시 실행하십시오: {file_path}")
    elif ext == ".xls":
        raise InputError("구형 .xls 형식은 지원하지 않습니다. Excel에서 '.xlsx' 또는 '.csv'로 다른 이름으로 저장 후 지정하십시오.")
    elif ext == ".csv":
        encodings = ["utf-8-sig", "cp949", "euc-kr", "latin1"]
        df_raw = None
        last_err: Optional[Exception] = None
        for enc in encodings:
            try:
                df_raw = pd.read_csv(file_path, header=None, encoding=enc, sep=None, engine="python")
                break
            except PermissionError:
                raise PermissionError(f"파일이 다른 프로그램(Excel 등)에서 잠겨 있습니다. 파일을 닫고 다시 실행하십시오: {file_path}")
            except Exception as e:
                last_err = e
                continue
        if df_raw is None:
            raise InputError(f"CSV 파일 로드 실패 (지원되는 인코딩 모두 시도 완료): {last_err}")
    else:
        raise InputError(f"지원하지 않는 데이터 포맷입니다 ({ext}). .xlsx 또는 .csv 파일을 지정하십시오.")

    total_rows = len(df_raw)
    if total_rows == 0:
        raise InputError("입력 데이터 파일이 비어 있습니다.")

    # Auto-Header Sniffing: If header_row is not specified or 1, skip leading empty rows
    if header_row is not None and header_row > 1:
        header_idx = header_row - 1
    else:
        # Sniff first non-empty row containing at least 2 valid string/non-null cells
        header_idx = 0
        for r_i in range(min(15, total_rows)):
            row_items = df_raw.iloc[r_i].dropna().tolist()
            if len(row_items) >= 2 and any(isinstance(v, str) and str(v).strip() for v in row_items):
                header_idx = r_i
                break

    if header_idx >= total_rows:
        raise InputError(f"유효한 헤더 행을 찾을 수 없습니다 (전체 행 수: {total_rows}).")

    raw_headers = df_raw.iloc[header_idx].values
    headers = [str(c).strip() if pd.notna(c) and str(c).strip() else f"col_{i}" for i, c in enumerate(raw_headers)]

    # Handle unit row if provided
    if unit_row is not None and 1 <= unit_row <= total_rows:
        units = df_raw.iloc[unit_row - 1].values
        combined_headers = []
        for h, u in zip(headers, units):
            u_str = str(u).strip() if pd.notna(u) else ""
            if u_str and u_str not in ["-", "None", "nan"]:
                combined_headers.append(f"{h}({u_str})")
            else:
                combined_headers.append(h)
        headers = combined_headers

    # De-duplicate headers (handles accidental duplicate column names in source files)
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

    # Determine data start row
    if data_row is not None:
        start_idx = max(0, data_row - 1)
    else:
        last_meta_idx = header_idx
        if unit_row is not None and 1 <= unit_row <= total_rows:
            last_meta_idx = max(header_idx, unit_row - 1)
        start_idx = last_meta_idx + 1

    if start_idx >= total_rows:
        raise InputError(f"데이터 시작 행 ({start_idx + 1}) 이후에 유효한 데이터 행이 없습니다.")

    df_data = df_raw.iloc[start_idx:].copy()
    df_data.columns = headers
    df_data = df_data.reset_index(drop=True)

    # Clean rows/cols that are entirely NaN
    df_data = df_data.dropna(how="all", axis=0).dropna(how="all", axis=1)
    return df_data


# ==============================================================================
# C5. Bulletproof AST Formula Sandbox (--eval), shared by training and inference
# ==============================================================================

_ALLOWED_AST_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name,
    ast.Load, ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd
)

SAFE_MATH: Dict[str, Any] = {
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

_NAME_BOUNDARY_L = r"(?<![가-힣a-zA-Z0-9_])"
_NAME_BOUNDARY_R = r"(?![가-힣a-zA-Z0-9_])"


def _validate_eval_ast(formula_ast: ast.AST, allowed_identifiers: set, columns: List[str]) -> None:
    """Ensures AST contains only safe arithmetic nodes and declared identifiers."""
    for node in ast.walk(formula_ast):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise InputError(f"보안 위반: 허용되지 않은 문법 노드 감지: {type(node).__name__}")
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in SAFE_MATH):
            raise InputError(f"허용되지 않은 함수 호출입니다. 사용 가능 함수: {sorted(k for k in SAFE_MATH if callable(SAFE_MATH[k]))}")
        if isinstance(node, ast.Name) and node.id not in allowed_identifiers:
            s = suggest_columns(node.id, columns)
            raise InputError(
                f"수식의 식별자 '{node.id}'에 해당하는 컬럼이 없습니다"
                + (f" -> [추천] {s}" if s else "")
                + f". 컬럼명은 데이터의 전체 이름(단위 포함) 또는 단위를 뺀 고유 이름으로 쓰십시오. [사용 가능한 컬럼 목록]: {columns}"
            )


def compile_formula(formula: str, columns: List[str]) -> Tuple[str, Dict[str, str], str]:
    """
    Replaces column names in a formula with internal tokens (prevents collisions with
    function names and lets names contain '(', '%', '/', etc.).
    Full names are matched first (longest first), then unique unit-less aliases.
    Returns (tokenized_formula, token_to_column, canonical_formula_with_full_names).
    """
    col_list = [str(c) for c in columns]
    token_to_col: Dict[str, str] = {}
    transformed = formula
    idx = 0

    candidates: List[Tuple[str, str]] = [(c, c) for c in sorted(col_list, key=len, reverse=True)]
    alias_map = build_alias_map(col_list)
    col_set = set(col_list)
    aliases = [(strip_unit(full), full) for key, full in alias_map.items()]
    aliases = [(a, full) for a, full in aliases if a and a != full and a not in col_set and a not in SAFE_MATH]
    candidates += sorted(aliases, key=lambda t: len(t[0]), reverse=True)

    for name, full in candidates:
        pattern = _NAME_BOUNDARY_L + re.escape(name) + _NAME_BOUNDARY_R
        if re.search(pattern, transformed):
            token = next((t for t, c in token_to_col.items() if c == full), None)
            if token is None:
                token = f"__COL_TOKEN_{idx}__"
                idx += 1
                token_to_col[token] = full
            transformed = re.sub(pattern, lambda _m, t=token: t, transformed)

    canonical = transformed
    for token, col in token_to_col.items():
        canonical = canonical.replace(token, col)
    return transformed, token_to_col, canonical


def apply_eval_expressions(
    df: pd.DataFrame,
    eval_expressions: List[str],
    target_cols: Optional[List[str]] = None,
    strict: bool = True
) -> Tuple[pd.DataFrame, List[str], List[str]]:
    """
    Safely evaluates derived feature formulas 'new = expr' in order (later formulas may
    reference earlier ones).
    - Strictly blocks any reference to target variables (Y) to prevent data leakage.
    - Infinite results become NaN for downstream imputation.
    - strict=False (inference replay): failures are logged as [WARN] and skipped.
    Returns (df, canonical_expressions, created_columns).
    """
    if not eval_expressions:
        return df, [], []

    df = df.copy()
    target_set = set(target_cols or [])
    applied: List[str] = []
    created: List[str] = []

    for expr in eval_expressions:
        try:
            if "=" not in expr:
                raise InputError(f"수식 형식 오류: '=' 기호가 누락되었습니다: '{expr}'")
            new_col, formula = expr.split("=", 1)
            new_col, formula = new_col.strip(), formula.strip()
            if not new_col:
                raise InputError(f"생성할 파생변수명이 지정되지 않았습니다: '{expr}'")

            columns = [str(c) for c in df.columns]
            transformed, token_to_col, canonical = compile_formula(formula, columns)

            leaked = [c for c in token_to_col.values() if c in target_set]
            if leaked:
                raise InputError(
                    f"[DATA LEAKAGE DETECTED] 파생변수 '{new_col}' 수식에 타겟 변수 {leaked}이(가) 포함되어 있습니다. "
                    f"타겟 변수는 독립변수 및 파생변수 생성에 절대 투입될 수 없습니다."
                )

            try:
                tree = ast.parse(transformed, mode="eval")
            except SyntaxError as e:
                raise InputError(f"--eval 수식 문법 오류 ('{expr}'): {e.msg}")

            eval_env = dict(SAFE_MATH)
            for token, col in token_to_col.items():
                eval_env[token] = coerce_numeric(df[col]).astype(float)
            _validate_eval_ast(tree, set(eval_env.keys()), columns)

            with np.errstate(all="ignore"):
                res_val = eval(compile(tree, "<eval>", "eval"), {"__builtins__": {}}, eval_env)
            if not isinstance(res_val, (pd.Series, np.ndarray, int, float)):
                raise InputError("수식 결과가 숫자형 배열이 아닙니다.")
            ser = pd.Series(res_val, index=df.index, dtype=float).replace([np.inf, -np.inf], np.nan)
            df[new_col] = ser
            applied.append(f"{new_col} = {canonical}")
            created.append(new_col)
        except Exception as ex:
            if strict:
                if isinstance(ex, InputError):
                    raise
                raise InputError(f"--eval 파생 수식 연산 실패 ('{expr}'): {ex}")
            sys.stderr.write(f"[WARN] 파생변수 연산 생략/실패 ('{expr}'): {ex}\n")

    return df, applied, created


# ==============================================================================
# C6. Windows-safe File Operations
# ==============================================================================

def retry_fs(fn: Callable[[], Any], attempts: int = 6, delay: float = 0.5) -> Any:
    """Retries a filesystem call that may transiently fail on Windows (antivirus/indexer/Explorer handles)."""
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay * (i + 1))


def _make_writable_and_retry(func, path, _exc_info):
    try:
        os.chmod(path, 0o700)
        func(path)
    except Exception:
        pass


def remove_tree(path: str) -> None:
    """Removes a directory tree, clearing Windows read-only flags; retries on transient locks."""
    if not os.path.exists(path):
        return

    def _rm():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_make_writable_and_retry)
        else:
            shutil.rmtree(path, onerror=_make_writable_and_retry)
        if os.path.exists(path):
            raise PermissionError(f"폴더 삭제 실패 (다른 프로그램이 사용 중): {path}")

    retry_fs(_rm)


def atomic_write_text(path: str, text: str) -> None:
    """Writes to a sibling temp file then os.replace()s it, so readers never see a half-written file."""
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    try:
        retry_fs(lambda: os.replace(tmp, path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _timestamped(path: str) -> str:
    base, ext = os.path.splitext(path)
    return f"{base}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"


def save_with_lock_fallback(path: str, writer: Callable[[str], None], what: str = "파일") -> str:
    """
    Calls writer(path). If the file is locked (opened in Excel/Word), saves to a
    timestamped sibling instead and returns the path actually written.
    """
    try:
        writer(path)
        return path
    except PermissionError:
        alt = _timestamped(path)
        writer(alt)
        sys.stderr.write(
            f"[WARN] {what}이(가) 다른 프로그램(Excel/Word 등)에서 열려 있어 새 파일명으로 저장되었습니다: {os.path.basename(alt)}\n"
        )
        return alt


def write_csv_excel_compatible(df: pd.DataFrame, path: str, encoding: Optional[str] = None) -> str:
    """
    Writes CSV that opens correctly by double-click in Korean Windows Excel:
    CP949 by default, utf-8-sig fallback when characters are not representable.
    Returns the path actually written (may differ if the target was locked).
    """
    def _write(p: str) -> None:
        enc = encoding or "cp949"
        try:
            df.to_csv(p, index=False, encoding=enc)
        except (UnicodeEncodeError, LookupError):
            df.to_csv(p, index=False, encoding="utf-8-sig")

    return save_with_lock_fallback(path, _write, what="CSV 파일")


# ##############################################################################
# PART P. INFERENCE ENGINE
# ##############################################################################

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
    setup_console()
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
