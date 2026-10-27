# -*- coding: utf-8 -*-
"""
ml_common.py - Shared runtime for ml_kit CLI tools (ml_train / ml_predict / ml_report).

Single implementation of everything that must behave identically at training
and inference time (data loading, numeric coercion, --eval formula engine),
plus the Agent CLI Protocol helpers (1-line JSON stdout, error directives)
and Windows-safe file operations (lock fallback, retrying rename/remove).

Pure standard library + NumPy + Pandas. No network access.
"""

import sys
import os
import re
import ast
import json
import time
import shutil
import difflib
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Callable

import numpy as np
import pandas as pd


# ==============================================================================
# 1. Console & Agent CLI Protocol (Clean Terminal Principle - No Emojis)
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
# 2. Encoding-tolerant File Reading (Windows Notepad / PowerShell / Excel outputs)
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
# 3. Column Name Resolution (unit-suffix aliases & typo suggestions)
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
# 4. Robust Data Loader & Layout Parser with Auto-Header Sniffing
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
# 5. Bulletproof AST Formula Sandbox (--eval), shared by training and inference
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
# 6. Windows-safe File Operations
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
