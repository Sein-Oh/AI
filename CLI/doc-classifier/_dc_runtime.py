"""doc-classifier 공통 런타임 (표준 라이브러리만 사용, pywin32 없이 import 가능).

- ACI 응답 계약: stdout 정확히 1줄 JSON, exit 0/1/2/130, agent_directive VERIFIED:/STOP_RETRY:/ERROR:
- 인자 파서(JsonArgumentParser): 인자 오류도 JSON으로 응답 (exit 2)
- 로그: stderr, 태그 [INFO] [PROGRESS] [WARN] [ERROR] [STATUS] (상세 로그는 DOCCLS_VERBOSE=1일 때만)
- 경로: data 폴더, 다음 명령(next_commands) 구성, 이름 추천([추천])
도구 폴더를 단독으로 복사해 쓸 수 있도록 다른 도구의 런타임을 import하지 않습니다 (계약은 office-cli와 같음).
"""
import argparse
import datetime as _dt
import difflib
import json
import math
import os
import re
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

TOOL = "doc_classifier"
VERSION = "0.9.3"
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
ERROR_LOG_MAX = 2 * 1024 * 1024          # 오류 로그가 이보다 커지면 errors.old.txt로 넘기고 새로 시작
CURRENT_ARGV: Optional[List[str]] = None  # 진입점이 채움 (인자 오류 기록에도 실제 명령을 남기려고)


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
    return os.environ.get("DOCCLS_VERBOSE", "") not in ("", "0", "false", "False")


def log(tag: str, message: str) -> None:
    """stderr 로그. tag는 INFO, PROGRESS, WARN, ERROR, STATUS 중 하나. 줄 단위로 바로 내보냅니다."""
    try:
        sys.stderr.write(f"[{tag}] {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


def debug(message: str) -> None:
    if _verbose():
        log("INFO", message)


# ==============================================================================
# 2. 응답 계약
# ==============================================================================

class InputError(ValueError):
    """인자/대상/데이터 문제. 같은 인자로 재시도해도 소용없음 (STOP_RETRY)."""


class CandidatesError(InputError):
    """후보가 둘 이상이라 도구가 고르지 않는 경우 (CLI/README.md R8 [후보]). 응답에 candidates 키를 붙입니다."""

    def __init__(self, message: str, candidates: Sequence[str]):
        self.candidates = list(candidates)[:10]
        super().__init__(f"{message} [후보] {', '.join(self.candidates)}")


# 실행 중 JIT 복구 기록 (CLI/README.md R3). 진입점이 실행마다 reset_run_state()로 비웁니다.
_RECOVERED: List[str] = []


def reset_run_state() -> None:
    _RECOVERED.clear()


def note_recovered(msg: str) -> None:
    """복구한 일을 stderr [WARN]으로 알리고, 응답 JSON의 recovered 배열에 담습니다 (200자 이하, 경로는 파일 이름만)."""
    msg = msg[:200]
    log("WARN", msg)
    _RECOVERED.append(msg)


def _attach_recovered(payload: Dict[str, Any]) -> Dict[str, Any]:
    if _RECOVERED:
        payload["recovered"] = list(_RECOVERED)
    return payload


_STOP_RETRY_ERRORS = (InputError, ValueError, KeyError, FileNotFoundError, NotADirectoryError,
                      IsADirectoryError, PermissionError)


def json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return str(obj)


def emit_json(payload: Dict[str, Any]) -> None:
    """stdout에 정확히 1줄 JSON을 출력합니다."""
    setup_console()
    sys.stdout.write(json.dumps(json_safe(payload), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def ok(command: str, preview: str, directive: str = "", **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": "ok", "tool": TOOL, "command": command, "preview": preview}
    payload.update(fields)
    if not directive:
        directive = "VERIFIED: 작업이 완료되었습니다. 같은 명령을 다시 실행하지 마세요."
    elif not directive.startswith("VERIFIED:"):
        directive = "VERIFIED: " + directive
    payload["agent_directive"] = directive
    return _attach_recovered(payload)


INTERRUPTED_DIRECTIVE = ("STOP_RETRY: 실행이 중단되었습니다. 지금까지 결과는 저장되어 있습니다. "
                         "이어서 하려면 사용자에게 확인한 뒤 next_commands[0]을 실행하세요.")


def error_payload(exc: BaseException, command: str = "") -> Dict[str, Any]:
    base: Dict[str, Any] = {"status": "error", "tool": TOOL, "command": command}
    _attach_recovered(base)
    if isinstance(exc, KeyboardInterrupt):
        base.update(error_type="interrupted", message="사용자 또는 상위 프로세스에 의해 실행이 중단되었습니다.",
                    agent_directive=INTERRUPTED_DIRECTIVE)
        return base
    msg = str(exc) or type(exc).__name__
    if isinstance(exc, CandidatesError):
        base.update(error_type="input", message=msg, candidates=exc.candidates,
                    agent_directive="STOP_RETRY: 후보가 둘 이상이라 도구가 고르지 않았습니다. 재시도하지 말고 [후보](candidates)를 "
                                    "사용자에게 보여 주고 하나를 고르게 한 뒤, 고른 값으로 실행하세요.")
        return base
    if isinstance(exc, _STOP_RETRY_ERRORS):
        base.update(error_type="input", message=msg,
                    agent_directive="STOP_RETRY: 인자나 대상 확인에 실패했습니다. message에 '[추천]'이 있으면 그 값으로 1회만 "
                                    "다시 실행하고, 없으면 message를 사용자에게 그대로 보고하세요.")
        return base
    base.update(error_type="internal", message=f"{type(exc).__name__}: {msg}",
                agent_directive="ERROR: 예상하지 못한 내부 오류입니다. 재시도하지 말고 message를 사용자에게 보고하세요.")
    return base


def error_log_path() -> str:
    return os.path.join(get_data_dir(), "logs", "errors.txt")


def write_error_log(command: str, argv: Optional[Sequence[str]], payload: Dict[str, Any], trace: str = "") -> None:
    """실패한 실행을 data\\logs\\errors.txt에 자동으로 덧붙입니다 (실기 결과를 나중에 읽고 판단하기 위한 기록).
    기록 실패가 응답 계약(stdout 1줄 JSON)을 깨면 안 되므로 어떤 오류도 삼킵니다."""
    try:
        import platform
        path = error_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > ERROR_LOG_MAX:
            os.replace(path, path[:-4] + ".old.txt")
        if argv is None:
            argv = CURRENT_ARGV if CURRENT_ARGV is not None else sys.argv[1:]
        args = " ".join(quote_arg(a) for a in argv)
        lines = [f"===== {_dt.datetime.now().isoformat(timespec='seconds')} | {TOOL} {VERSION} | "
                 f"Python {platform.python_version()} | {platform.platform()}",
                 f"명령: {args}",
                 f"결과: {payload.get('error_type')} | {payload.get('message')}"]
        if trace:
            lines.append("traceback:\n" + trace.rstrip())
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")
    except Exception:
        pass


def run_cli(command: str, execute: Callable[[], Dict[str, Any]], argv: Optional[Sequence[str]] = None) -> None:
    """본문을 실행하고, 어떤 경우에도 stdout 1줄 JSON과 종료 코드(0/1/130)를 보장합니다.
    본문이 결과에 "_exit"를 넣으면 그 종료 코드를 씁니다 (예: 중단 후 저장까지 마친 경우 130).
    실패(exit 1)는 data\\logs\\errors.txt에 자동 기록합니다 (사용자 중단은 기록하지 않음)."""
    setup_console()
    try:
        result = execute()
    except KeyboardInterrupt as e:
        log("ERROR", "실행 중단 (KeyboardInterrupt)")
        emit_json(error_payload(e, command))
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        log("ERROR", f"{type(e).__name__}: {e}")
        if _verbose():
            sys.stderr.write(trace)
        payload = error_payload(e, command)
        write_error_log(command, argv, payload, trace if payload.get("error_type") == "internal" else "")
        emit_json(payload)
        sys.exit(1)
    code = result.pop("_exit", None)
    emit_json(result)
    sys.exit(code if code is not None else (0 if result.get("status") == "ok" else 1))


class JsonArgumentParser(argparse.ArgumentParser):
    """인자 오류를 JSON(exit 2)으로 응답하는 ArgumentParser."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        payload = {"status": "error", "tool": TOOL, "command": "", "error_type": "input",
                   "message": f"CLI 인자 오류: {message}",
                   "agent_directive": "STOP_RETRY: CLI 인자가 잘못되었습니다. SKILL.md의 명령 형식을 확인하고 사용자에게 보고하세요."}
        write_error_log("", None, payload)
        emit_json(payload)
        sys.exit(2)


def build_parser(description: str):
    parser = JsonArgumentParser(prog=f"{TOOL}.py", description=description)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True
    return parser, subparsers


# ==============================================================================
# 3. 폴더, 표시
# ==============================================================================

def get_data_dir() -> str:
    """작업 DB 폴더. 우선순위: DOCCLS_DATA_DIR > <도구폴더>/data"""
    path = os.path.abspath(os.environ.get("DOCCLS_DATA_DIR") or os.path.join(TOOL_DIR, "data"))
    os.makedirs(path, exist_ok=True)
    return path


def timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def read_text_file(path: str) -> str:
    """텍스트 파일 읽기: UTF-8(BOM 포함), UTF-16(BOM), CP949를 자동으로 판별합니다."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


_STAMP_TAIL = re.compile(r"_\d{8}_\d{6}(_\d+)?$")


def timestamped_path(path: str) -> str:
    """'<이름>_<YYYYMMDD_HHMMSS><확장자>'. 이름이 이미 시각으로 끝나면 바꿔 붙이고(두 번 붙이지 않음),
    같은 이름이 있으면 _2, _3 ...을 붙입니다."""
    stem, ext = os.path.splitext(os.path.abspath(path))
    base = f"{_STAMP_TAIL.sub('', stem)}_{timestamp()}"
    cand, n = base + ext, 2
    while os.path.exists(cand):
        cand, n = f"{base}_{n}{ext}", n + 1
    return cand


def save_with_lock_fallback(path: str, write: Callable[[str], None]) -> str:
    """임시 파일에 쓴 뒤 바꿔 넣습니다. 대상이 열려 있어 잠겼으면(엑셀) 이름 뒤에 시각을 붙여 따로 저장합니다.
    실제로 저장한 경로를 돌려줍니다."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(os.path.abspath(path))
    tmp = f"{stem}.saving{ext}"
    try:
        write(tmp)
        try:
            os.replace(tmp, path)
            return os.path.abspath(path)
        except PermissionError:
            alt = timestamped_path(path)
            os.replace(tmp, alt)
            note_recovered(f"{os.path.basename(path)} 잠김(열려 있음) -> {os.path.basename(alt)}로 저장")
            return alt
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def human_size(n: Optional[float]) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# ==============================================================================
# 4. LLM 친화 도우미
# ==============================================================================

def suggest(name: str, candidates: Iterable[str], n: int = 3) -> List[str]:
    cands = [str(c) for c in candidates]
    key = str(name).strip().lower().replace(" ", "")
    if not key:
        return []
    norm = {c: c.strip().lower().replace(" ", "") for c in cands}
    partial = [c for c in cands if key in norm[c] or (norm[c] and norm[c] in key)]
    close = difflib.get_close_matches(key, list(norm.values()), n=n, cutoff=0.5)
    by_norm = {v: k for k, v in norm.items()}
    result: List[str] = []
    for c in partial + [by_norm[v] for v in close]:
        if c not in result:
            result.append(c)
    return result[:n]


def not_found(kind: str, name: str, candidates: Iterable[str]) -> InputError:
    cands = [str(c) for c in candidates]
    hints = suggest(name, cands)
    if hints:
        tail = f" [추천] {hints[0]}" + (f" (그 외 후보: {', '.join(hints[1:])})" if len(hints) > 1 else "")
    elif cands:
        tail = f" 사용 가능한 {kind}: " + ", ".join(cands[:15]) + (" ..." if len(cands) > 15 else "")
    else:
        tail = ""
    return InputError(f"{kind} '{name}'을(를) 찾을 수 없습니다.{tail}")


def quote_arg(value: Any) -> str:
    """명령 문자열에 넣을 인자를 Windows cmd 기준으로 따옴표 처리합니다."""
    s = str(value)
    if s and all(ch not in s for ch in ' \t"&|<>^()%,;='):
        return s
    return '"' + s.replace('"', '\\"') + '"'


def without_flag(argv: Sequence[str], flag: str) -> List[str]:
    return [a for a in argv if a != flag]


def dry_run_result(command: str, preview: str, planned: List[str], argv: Sequence[str], **fields: Any) -> Dict[str, Any]:
    """--dry-run 응답 (CLI/README.md R8): 바꾼 것 없이 planned만 보여 주고, next_commands[0]은 --dry-run을 뺀 같은 명령."""
    return ok(command, preview,
              "VERIFIED: 미리보기만 했습니다(변경 없음). planned를 사용자에게 보여주고 확인을 받은 뒤 next_commands[0]을 실행하세요.",
              dry_run=True, planned=planned,
              next_commands=[next_command(without_flag(argv, "--dry-run"), "미리보기한 작업 실제로 실행")], **fields)


def next_command(args: Sequence[Any], purpose: str, needs_input: bool = False,
                 placeholder: str = "") -> Dict[str, Any]:
    """next_commands 항목. 자리표시자가 있으면 needs_input=True (ml-kit 2.1.1과 같은 규칙)."""
    parts = [f"python {quote_arg(os.path.join(TOOL_DIR, TOOL + '.py'))}"] + [quote_arg(a) for a in args]
    item: Dict[str, Any] = {"purpose": purpose, "command": " ".join(parts), "needs_input": needs_input}
    if placeholder:
        item["placeholder"] = placeholder
    return item
