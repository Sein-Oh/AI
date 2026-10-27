"""atomic-cli 공통 런타임 (pywin32 없이 import 가능).

모든 진입점(excel.py, word.py, ppt.py, outlook.py, reader.py, office.py)이 공유하는 기능:
- ACI 응답 계약: stdout 정확히 1줄 JSON, exit 0/1/2/130, agent_directive VERIFIED:/STOP_RETRY:/ERROR:
- 인자 파서(JsonArgumentParser): 인자 오류도 JSON으로 응답 (exit 2)
- 로그: stderr, 태그 [INFO] [PROGRESS] [WARN] [ERROR] [STATUS] (상세 로그는 ATOMIC_VERBOSE=1일 때만)
- 경로: 설정(config.json), data 폴더, 작업 폴더(_work), 입력/출력 경로 해석
- 텍스트/CSV 입출력: 인코딩 자동 판별, 잠금 파일 대비 저장
- 결과 길이 제한, 이름 추천([추천]), 다음 명령(next_commands) 구성
"""
import argparse
import csv
import datetime as _dt
import difflib
import io
import json
import math
import os
import sys
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(TOOL_DIR, "config.json")

# 결과 길이 기본 상한 (경량 LLM 컨텍스트 보호)
DEFAULT_MAX_ROWS = 200
DEFAULT_MAX_CHARS = 8000
# 작업 폴더 파일 보관 기간 (일)
WORK_RETENTION_DAYS = 7


# ==============================================================================
# 1. 콘솔과 로그
# ==============================================================================

def setup_console() -> None:
    """stdout/stderr를 UTF-8로 고정합니다 (Windows 콘솔과 파이프의 기본값은 CP949)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and (stream.encoding or "").lower() != "utf-8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _verbose() -> bool:
    return os.environ.get("ATOMIC_VERBOSE", "") not in ("", "0", "false", "False")


def log(tag: str, message: str) -> None:
    """stderr 로그. tag는 INFO, PROGRESS, WARN, ERROR, STATUS 중 하나."""
    try:
        sys.stderr.write(f"[{tag}] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


def debug(message: str) -> None:
    """상세 로그. ATOMIC_VERBOSE=1일 때만 [INFO] 태그로 출력합니다."""
    if _verbose():
        log("INFO", message)


# ==============================================================================
# 2. 응답 계약
# ==============================================================================

class InputError(ValueError):
    """인자/대상/데이터 문제. 같은 인자로 재시도해도 소용없음 (STOP_RETRY)."""


class OfficeBusyError(RuntimeError):
    """Office가 편집 중이거나 대화상자가 떠 있어 응답하지 않음 (STOP_RETRY, 사용자 조치 필요)."""


_STOP_RETRY_ERRORS = (InputError, OfficeBusyError, ValueError, KeyError, FileNotFoundError,
                      NotADirectoryError, IsADirectoryError, PermissionError)

# COM HRESULT -> 사용자 안내 (pywintypes.com_error 해석용)
_COM_HINTS = {
    0x800AC472: ("busy", "Excel이 셀 편집 중이거나 대화상자가 열려 있습니다. Esc를 누르거나 대화상자를 닫은 뒤 다시 요청하세요."),
    0x8001010A: ("busy", "Office가 다른 작업으로 바빠 응답하지 않습니다. 대화상자가 떠 있는지 확인하세요."),
    0x80010001: ("busy", "Office가 호출을 거부했습니다. 대화상자가 떠 있는지 확인하세요."),
    0x800706BA: ("gone", "Office 프로그램과의 연결이 끊겼습니다 (창이 닫혔거나 응답 없음)."),
    0x800706BE: ("gone", "Office 프로그램과의 연결이 끊겼습니다 (원격 호출 실패)."),
    0x800401E3: ("gone", "실행 중인 Office 창이나 열린 문서를 찾을 수 없습니다."),
}


def _com_error_info(exc: BaseException) -> Optional[Tuple[int, str, str]]:
    """pywintypes.com_error면 (HRESULT, Office 설명, 분류)를 돌려줍니다."""
    if type(exc).__name__ != "com_error":
        return None
    args = getattr(exc, "args", ())
    if not args or not isinstance(args[0], int):
        return None
    hr = args[0] & 0xFFFFFFFF
    desc = str(args[1]) if len(args) > 1 else ""
    excinfo = args[2] if len(args) > 2 else None
    scode = None
    if excinfo and len(excinfo) >= 6:
        if excinfo[2]:
            desc = str(excinfo[2])
        if isinstance(excinfo[5], int):
            scode = excinfo[5] & 0xFFFFFFFF
    for code in (scode, hr):
        if code in _COM_HINTS:
            kind, hint = _COM_HINTS[code]
            return code, f"{hint} (원문: {desc})", kind
    return hr, desc, "other"


def json_safe(obj: Any) -> Any:
    """COM/파이썬 값을 엄격한 JSON 값으로 바꿉니다 (날짜, NaN, 튜플, 바이트 등)."""
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if hasattr(obj, "isoformat"):  # pywintypes.datetime
        try:
            return obj.isoformat()
        except Exception:
            pass
    try:
        f = float(obj)
        return f if math.isfinite(f) else None
    except Exception:
        return str(obj)


def emit_json(payload: Dict[str, Any]) -> None:
    """stdout에 정확히 1줄 JSON을 출력합니다."""
    setup_console()
    sys.stdout.write(json.dumps(json_safe(payload), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def ok(tool: str, command: str, preview: str, directive: str = "", **fields: Any) -> Dict[str, Any]:
    """성공 응답. directive를 생략하면 'VERIFIED: 완료' 문구를 씁니다."""
    payload: Dict[str, Any] = {"status": "ok", "tool": tool, "command": command, "preview": preview}
    payload.update(fields)
    if not directive:
        directive = "VERIFIED: 작업이 완료되었습니다. 같은 명령을 다시 실행하거나 결과를 다시 조회하지 마세요."
    elif not directive.startswith("VERIFIED:"):
        directive = "VERIFIED: " + directive
    payload["agent_directive"] = directive
    return payload


def error_payload(exc: BaseException, tool: str = "", command: str = "") -> Dict[str, Any]:
    """예외를 표준 오류 응답으로 바꿉니다."""
    base: Dict[str, Any] = {"status": "error", "tool": tool, "command": command}
    if isinstance(exc, KeyboardInterrupt):
        base.update(error_type="interrupted",
                    message="사용자 또는 상위 프로세스에 의해 실행이 중단되었습니다.",
                    agent_directive="STOP_RETRY: 실행이 중단되었습니다. 다시 실행하기 전에 사용자에게 확인하세요.")
        return base

    com = _com_error_info(exc)
    if com is not None:
        code, desc, kind = com
        if kind in ("busy", "gone"):
            base.update(error_type="office_busy" if kind == "busy" else "office_unavailable",
                        message=desc, hresult=f"0x{code:08X}",
                        agent_directive="STOP_RETRY: Office가 응답하지 않습니다. message를 사용자에게 그대로 보고하세요.")
        else:
            base.update(error_type="office", message=f"Office 오류: {desc}", hresult=f"0x{code:08X}",
                        agent_directive="STOP_RETRY: Office 작업이 실패했습니다. 인자(범위, 시트, 슬라이드 번호 등)를 확인할 수 있으면 "
                                        "1회만 고쳐서 다시 실행하고, 아니면 message를 사용자에게 보고하세요.")
        return base

    msg = str(exc) or type(exc).__name__
    if isinstance(exc, _STOP_RETRY_ERRORS):
        base.update(error_type="office_busy" if isinstance(exc, OfficeBusyError) else "input",
                    message=msg,
                    agent_directive="STOP_RETRY: 인자나 대상 확인에 실패했습니다. message에 '[추천]'이 있으면 그 값으로 1회만 "
                                    "다시 실행하고, 없으면 message를 사용자에게 그대로 보고하세요.")
        return base
    base.update(error_type="internal", message=f"{type(exc).__name__}: {msg}",
                agent_directive="ERROR: 예상하지 못한 내부 오류입니다. 재시도하지 말고 message를 사용자에게 보고하세요.")
    return base


def run_cli(tool: str, command: str, execute: Callable[[], Dict[str, Any]]) -> None:
    """도구 본문을 실행하고, 어떤 경우에도 stdout 1줄 JSON과 종료 코드(0/1/130)를 보장합니다."""
    setup_console()
    try:
        result = execute()
    except KeyboardInterrupt as e:
        log("ERROR", "실행 중단 (KeyboardInterrupt)")
        emit_json(error_payload(e, tool, command))
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        log("ERROR", f"{type(e).__name__}: {e}")
        if _verbose():
            import traceback
            sys.stderr.write(traceback.format_exc())
        emit_json(error_payload(e, tool, command))
        sys.exit(1)
    emit_json(result)
    sys.exit(0 if result.get("status") == "ok" else 1)


class JsonArgumentParser(argparse.ArgumentParser):
    """인자 오류를 텍스트 대신 JSON(exit 2)으로 응답하는 ArgumentParser. 서브파서에도 그대로 상속됩니다."""

    tool_name = ""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        emit_json({
            "status": "error",
            "tool": self.tool_name,
            "command": "",
            "error_type": "input",
            "message": f"CLI 인자 오류: {message}",
            "agent_directive": "STOP_RETRY: CLI 인자가 잘못되었습니다. SKILL.md의 명령 형식을 확인하고 사용자에게 보고하세요.",
        })
        sys.exit(2)


def build_parser(tool: str, description: str):
    """서브커맨드 방식 파서를 만듭니다. 반환: (parser, subparsers)."""
    JsonArgumentParser.tool_name = tool
    parser = JsonArgumentParser(prog=f"{tool}.py", description=description)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True
    return parser, subparsers


# ==============================================================================
# 3. 설정과 폴더
# ==============================================================================

_config_cache: Optional[Dict[str, Any]] = None


def load_config() -> Dict[str, Any]:
    """도구 폴더의 config.json (없으면 빈 설정). 프로세스당 한 번만 읽습니다."""
    global _config_cache
    if _config_cache is None:
        cfg: Dict[str, Any] = {}
        if os.path.exists(CONFIG_FILE):
            try:
                cfg = json.loads(read_text_file(CONFIG_FILE))
                if not isinstance(cfg, dict):
                    cfg = {}
            except Exception as e:
                log("WARN", f"config.json을 읽지 못해 기본 설정을 사용합니다: {e}")
                cfg = {}
        _config_cache = cfg
    return _config_cache


def set_config(key: str, value: Any) -> None:
    """설정 값을 저장합니다 (예: transfer 방식 자동 판별 결과)."""
    cfg = dict(load_config())
    cfg[key] = value
    atomic_write_text(CONFIG_FILE, json.dumps(cfg, ensure_ascii=False, indent=2))
    global _config_cache
    _config_cache = cfg


def _dir_setting(env_name: str, cfg_key: str, default: str) -> str:
    path = os.environ.get(env_name) or load_config().get(cfg_key) or default
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(str(path))))
    os.makedirs(path, exist_ok=True)
    return path


def get_data_dir() -> str:
    """사용자 데이터 폴더. 우선순위: ATOMIC_DATA_DIR > config.json data_dir > <도구폴더>/data"""
    return _dir_setting("ATOMIC_DATA_DIR", "data_dir", os.path.join(TOOL_DIR, "data"))


def get_cache_dir() -> str:
    """캐시 폴더 (읽은 문서 텍스트, 색인, 스냅샷). 우선순위: ATOMIC_CACHE_DIR > config.json cache_dir > <도구폴더>/cache"""
    return _dir_setting("ATOMIC_CACHE_DIR", "cache_dir", os.path.join(TOOL_DIR, "cache"))


def get_work_dir() -> str:
    """중간 결과 파일 폴더 (data/_work). 오래된 파일은 자동 정리합니다."""
    path = os.path.join(get_data_dir(), "_work")
    os.makedirs(path, exist_ok=True)
    return path


def cleanup_work_dir(days: int = WORK_RETENTION_DAYS) -> int:
    """작업 폴더에서 보관 기간이 지난 파일을 지웁니다. 지운 개수를 반환 (실패는 무시)."""
    removed = 0
    cutoff = time.time() - days * 86400
    try:
        work = get_work_dir()
        for name in os.listdir(work):
            p = os.path.join(work, name)
            try:
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
                    removed += 1
            except OSError:
                continue
    except OSError:
        pass
    return removed


def timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def resolve_input_path(path: str, kind: str = "입력 파일") -> str:
    """입력 파일 경로를 찾습니다. 순서: 절대경로/현재 폴더 -> data 폴더 -> 작업 폴더.
    없으면 data 폴더의 비슷한 파일명을 [추천]으로 붙여 InputError를 냅니다."""
    if not path:
        raise InputError(f"{kind} 경로가 비어 있습니다.")
    raw = os.path.expandvars(os.path.expanduser(str(path).strip().strip('"')))
    candidates = [raw]
    if not os.path.isabs(raw):
        candidates += [os.path.join(get_data_dir(), raw), os.path.join(get_work_dir(), raw)]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    names: List[str] = []
    for folder in (get_data_dir(), get_work_dir()):
        try:
            names += [n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))]
        except OSError:
            pass
    raise not_found(kind, os.path.basename(raw), names, extra=f" (찾은 위치: {', '.join(candidates)})")


def resolve_output_path(path: Optional[str], default_stem: str, ext: str) -> str:
    """출력 파일 경로를 정합니다.
    - 생략하면 작업 폴더에 '<default_stem>_<시각><ext>'로 만듭니다.
    - 파일명만 주면 data 폴더 아래에 만듭니다.
    - 확장자가 없거나 다르면 ext로 맞춥니다.
    """
    ext = ext if ext.startswith(".") else "." + ext
    if not path:
        cleanup_work_dir()
        return os.path.join(get_work_dir(), f"{default_stem}_{timestamp()}{ext}")
    raw = os.path.expandvars(os.path.expanduser(str(path).strip().strip('"')))
    base, cur_ext = os.path.splitext(raw)
    if cur_ext.lower() != ext.lower():
        raw = (base if cur_ext else raw) + ext
    if not os.path.isabs(raw) and not os.path.dirname(raw):
        raw = os.path.join(get_data_dir(), raw)
    raw = os.path.abspath(raw)
    os.makedirs(os.path.dirname(raw), exist_ok=True)
    return raw


# ==============================================================================
# 4. 파일 입출력
# ==============================================================================

def read_text_file(path: str) -> str:
    """Windows 도구들이 쓰는 인코딩(UTF-8 +/- BOM, UTF-16 BOM, CP949/EUC-KR)을 자동 판별해 읽습니다."""
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


def read_csv_rows(path: str) -> List[List[str]]:
    """CSV/TSV를 2차원 문자열 리스트로 읽습니다 (구분자 자동 판별)."""
    text = read_text_file(path)
    sample = text[:4096]
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        if "\t" in sample and "," not in sample:
            delimiter = "\t"
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def retry_fs(fn: Callable[[], Any], attempts: int = 6, delay: float = 0.5) -> Any:
    """백신/동기화 프로그램의 일시적 잠금에 대비해 파일 작업을 재시도합니다."""
    last: Optional[BaseException] = None
    for i in range(attempts):
        try:
            return fn()
        except (PermissionError, OSError) as e:
            last = e
            time.sleep(delay * (i + 1))
    assert last is not None
    raise last


def atomic_write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    """임시 파일에 쓴 뒤 교체해, 쓰다가 중단돼도 기존 파일이 깨지지 않게 합니다."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp_{os.getpid()}"
    with open(tmp, "w", encoding=encoding, newline="") as f:
        f.write(text)
    retry_fs(lambda: os.replace(tmp, path))


def _timestamped(path: str) -> str:
    base, ext = os.path.splitext(path)
    return f"{base}_{timestamp()}{ext}"


def save_with_lock_fallback(path: str, writer: Callable[[str], None], what: str = "파일") -> str:
    """writer(path)로 저장합니다. 파일이 Excel/Word 등에서 열려 있어 잠겨 있으면
    시각을 붙인 새 이름으로 저장하고 그 경로를 반환합니다."""
    try:
        writer(path)
        return path
    except PermissionError:
        alt = _timestamped(path)
        writer(alt)
        log("WARN", f"{what}이(가) 다른 프로그램에서 열려 있어 새 이름으로 저장했습니다: {os.path.basename(alt)}")
        return alt


def write_csv_rows(path: str, rows: Iterable[Sequence[Any]], encoding: str = "utf-8-sig") -> str:
    """표를 CSV로 저장합니다 (기본 utf-8-sig: Excel에서 한글이 깨지지 않음). 실제 저장 경로를 반환합니다."""
    data = [["" if v is None else v for v in row] for row in rows]

    def _write(p: str) -> None:
        with open(p, "w", encoding=encoding, newline="") as f:
            csv.writer(f).writerows(data)

    return save_with_lock_fallback(path, _write, "CSV 파일")


def write_text(path: str, text: str) -> str:
    """텍스트(마크다운 등)를 UTF-8로 저장합니다. 실제 저장 경로를 반환합니다."""
    def _write(p: str) -> None:
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return save_with_lock_fallback(path, _write, "텍스트 파일")


# ==============================================================================
# 5. LLM 친화 도우미
# ==============================================================================

def suggest(name: str, candidates: Iterable[str], n: int = 3) -> List[str]:
    """오타로 보이는 이름에 대해 비슷한 후보를 찾습니다 (대소문자/공백 무시, 부분 일치 우선)."""
    cands = [str(c) for c in candidates]
    key = str(name).strip().lower().replace(" ", "")
    if not key:
        return []
    norm = {c: c.strip().lower().replace(" ", "") for c in cands}
    exact = [c for c in cands if norm[c] == key]
    if exact:
        return exact[:n]
    partial = [c for c in cands if key in norm[c] or (norm[c] and norm[c] in key)]
    close = difflib.get_close_matches(key, list(norm.values()), n=n, cutoff=0.5)
    by_norm = {v: k for k, v in norm.items()}
    result: List[str] = []
    for c in partial + [by_norm[v] for v in close]:
        if c not in result:
            result.append(c)
    return result[:n]


def find_name(name: str, candidates: Iterable[str]) -> Optional[str]:
    """대소문자/앞뒤 공백을 무시하고 정확히 같은 이름을 찾습니다."""
    key = str(name).strip().lower()
    for c in candidates:
        if str(c).strip().lower() == key:
            return str(c)
    return None


def not_found(kind: str, name: str, candidates: Iterable[str], extra: str = "") -> InputError:
    """'찾을 수 없음' InputError. 비슷한 이름이 있으면 [추천]을, 없으면 전체 목록 일부를 붙입니다."""
    cands = [str(c) for c in candidates]
    hints = suggest(name, cands)
    if hints:
        tail = f" [추천] {hints[0]}" + (f" (그 외 후보: {', '.join(hints[1:])})" if len(hints) > 1 else "")
    elif cands:
        shown = ", ".join(cands[:15]) + (" ..." if len(cands) > 15 else "")
        tail = f" 사용 가능한 {kind}: {shown}"
    else:
        tail = ""
    return InputError(f"{kind} '{name}'을(를) 찾을 수 없습니다.{extra}{tail}")


def clamp_rows(rows: List[List[Any]], max_rows: int = DEFAULT_MAX_ROWS,
               max_chars: int = DEFAULT_MAX_CHARS) -> Tuple[List[List[Any]], bool]:
    """행 수와 대략적인 글자 수 상한으로 표를 자릅니다. (잘린 표, 잘렸는지 여부)"""
    out: List[List[Any]] = []
    used = 0
    for row in rows:
        if len(out) >= max_rows:
            return out, True
        size = sum(len(str(v)) + 1 for v in row)
        if out and used + size > max_chars:
            return out, True
        out.append(row)
        used += size
    return out, False


def clamp_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> Tuple[str, bool]:
    """글자 수 상한으로 텍스트를 자릅니다. (잘린 텍스트, 잘렸는지 여부)"""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def quote_arg(value: Any) -> str:
    """명령 문자열에 넣을 인자를 Windows cmd 기준으로 따옴표 처리합니다."""
    s = str(value)
    if s and all(ch not in s for ch in ' \t"&|<>^()%,;='):
        return s
    return '"' + s.replace('"', '\\"') + '"'


def next_command(script: str, args: Sequence[Any], purpose: str) -> Dict[str, str]:
    """next_commands 항목 하나를 만듭니다. script는 도구 폴더 기준 파일명 (예: 'office.py')."""
    parts = [f"python {quote_arg(os.path.join(TOOL_DIR, script))}"] + [quote_arg(a) for a in args]
    return {"purpose": purpose, "command": " ".join(parts)}
