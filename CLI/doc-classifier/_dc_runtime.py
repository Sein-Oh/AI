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
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

TOOL = "doc_classifier"
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))


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
    return payload


INTERRUPTED_DIRECTIVE = ("STOP_RETRY: 실행이 중단되었습니다. 지금까지 결과는 저장되어 있습니다. "
                         "이어서 하려면 사용자에게 확인한 뒤 next_commands[0]을 실행하세요.")


def error_payload(exc: BaseException, command: str = "") -> Dict[str, Any]:
    base: Dict[str, Any] = {"status": "error", "tool": TOOL, "command": command}
    if isinstance(exc, KeyboardInterrupt):
        base.update(error_type="interrupted", message="사용자 또는 상위 프로세스에 의해 실행이 중단되었습니다.",
                    agent_directive=INTERRUPTED_DIRECTIVE)
        return base
    msg = str(exc) or type(exc).__name__
    if isinstance(exc, _STOP_RETRY_ERRORS):
        base.update(error_type="input", message=msg,
                    agent_directive="STOP_RETRY: 인자나 대상 확인에 실패했습니다. message에 '[추천]'이 있으면 그 값으로 1회만 "
                                    "다시 실행하고, 없으면 message를 사용자에게 그대로 보고하세요.")
        return base
    base.update(error_type="internal", message=f"{type(exc).__name__}: {msg}",
                agent_directive="ERROR: 예상하지 못한 내부 오류입니다. 재시도하지 말고 message를 사용자에게 보고하세요.")
    return base


def run_cli(command: str, execute: Callable[[], Dict[str, Any]]) -> None:
    """본문을 실행하고, 어떤 경우에도 stdout 1줄 JSON과 종료 코드(0/1/130)를 보장합니다.
    본문이 결과에 "_exit"를 넣으면 그 종료 코드를 씁니다 (예: 중단 후 저장까지 마친 경우 130)."""
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
        log("ERROR", f"{type(e).__name__}: {e}")
        if _verbose():
            import traceback
            sys.stderr.write(traceback.format_exc())
        emit_json(error_payload(e, command))
        sys.exit(1)
    code = result.pop("_exit", None)
    emit_json(result)
    sys.exit(code if code is not None else (0 if result.get("status") == "ok" else 1))


class JsonArgumentParser(argparse.ArgumentParser):
    """인자 오류를 JSON(exit 2)으로 응답하는 ArgumentParser."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        emit_json({"status": "error", "tool": TOOL, "command": "", "error_type": "input",
                   "message": f"CLI 인자 오류: {message}",
                   "agent_directive": "STOP_RETRY: CLI 인자가 잘못되었습니다. SKILL.md의 명령 형식을 확인하고 사용자에게 보고하세요."})
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


def next_command(args: Sequence[Any], purpose: str, needs_input: bool = False,
                 placeholder: str = "") -> Dict[str, Any]:
    """next_commands 항목. 자리표시자가 있으면 needs_input=True (ml-kit 2.1.1과 같은 규칙)."""
    parts = [f"python {quote_arg(os.path.join(TOOL_DIR, TOOL + '.py'))}"] + [quote_arg(a) for a in args]
    item: Dict[str, Any] = {"purpose": purpose, "command": " ".join(parts), "needs_input": needs_input}
    if placeholder:
        item["placeholder"] = placeholder
    return item
