# -*- coding: utf-8 -*-
"""
================================================================================
CLI Office: 윈도우 11 AI 에이전트 친화적 고성능 오피스 자동화 & 하이브리드 검색 CLI
================================================================================
지원 포맷: Word (.docx, .doc), Excel (.xlsx, .xls, .xlsm, .csv),
          PPT (.pptx, .ppt), HWP (.hwp, .hwpx), PDF (.pdf), Markdown (.md), Text (.txt)
핵심 기능:
1. DispatchEx + PID 스냅샷 기반 백그라운드 완전 격리 읽기 (작업 중인 오피스 창 간섭 0%)
2. 실제 인쇄 쪽번호(wdActiveEndPageNumber) 및 문단-표 실제 순서 100% 보장
3. 셀 병합(Merged Cells) 2D 정규화 & Forward-Fill 값 보존 + CSV 전용 파싱(UTF-8/CP949)
4. PPT 중첩 그룹 도형 재귀 언패킹 & (Top, Left) 시각적 순서 정렬 (도형 형상 제외 텍스트만 추출)
5. PDF pymupdf4llm 초고속 추출 (기본 이미지 배제, --extract-images 시 캐시 우회 및 이미지 레코드 생성)
6. C:/cli_temp/cache MD5 기반 JSONL 캐싱 및 300MB 용량 임계치 자동 감지 알림
7. 경량 하이브리드 검색 엔진 (Regex + 희소 단어 BM25/IDF + 목차 가중치)
8. 스마트 쓰기 (키워드 앵커 탐색, before/after/replace 정밀 제어, 주변 서식 상속, 엑셀 수식/숫자 자동 주입)
================================================================================
"""

import sys
import os
import re
import csv
import math
import time
import json
import hashlib
import argparse
import ctypes
import shutil
from pathlib import Path
from functools import wraps
from typing import Any, Optional, Union, List, Dict, Generator, Set, Tuple

# 1. Windows 콘솔 UTF-8 입출력 강제 고정
if sys.platform == "win32":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


# 2. Windows 활성 데스크톱 동기화
def sync_desktop_to_default():
    """샌드박스/세션 환경에서도 사용자 화면의 활성 창(WinSta0\\Default)에 접근할 수 있도록 동기화"""
    if sys.platform != "win32":
        return
    try:
        u32 = ctypes.windll.user32
        hdesk = u32.OpenDesktopW("Default", 0, False, 0x01FF)
        if hdesk:
            u32.SetThreadDesktop(hdesk)
    except Exception:
        pass


sync_desktop_to_default()

# 3. 외부 라이브러리 안전 임포트
try:
    import pymupdf
    import pymupdf4llm
except ImportError:
    pymupdf = None
    pymupdf4llm = None

try:
    import win32com.client
    import pythoncom
    import win32gui
except ImportError:
    win32com = None
    pythoncom = None
    win32gui = None

try:
    import olefile
except ImportError:
    olefile = None

import atexit
import signal
import zlib
import struct
import zipfile
import xml.etree.ElementTree as ET

VERIFIED_DIRECTIVE = "VERIFIED: 작업이 화면/파일에 정상 반영되었습니다. 추가 확인/재검증을 하지 말고 사용자에게 즉시 완료 보고하십시오."
STOP_RETRY_DIRECTIVE = "STOP_RETRY: 일치하는 대상을 찾지 못했습니다. 인자를 바꾸어 재시도하지 말고 즉시 다음 단계로 넘어가거나 작업을 완료하십시오."


# ==============================================================================
# 4. 백그라운드 COM 좀비 프로세스 가드 (ComProcessGuard)
# ==============================================================================
if sys.platform == "win32":
    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64)
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * 260)
        ]


class ComProcessGuard:
    """
    Win32 Job Object(JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) 및 PID 추적을 통해
    비정상 종료(Ctrl+C, 강제 Kill) 시에도 COM 좀비 프로세스를 100% 정리
    """
    _registered_pids = set()
    _job_handle = None
    _initialized = False

    @classmethod
    def init(cls):
        if cls._initialized:
            return
        cls._initialized = True
        atexit.register(cls.cleanup_all)

        def _signal_handler(signum, frame):
            cls.cleanup_all()
            sys.exit(128 + signum)

        try:
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)
        except Exception:
            pass

        if sys.platform == "win32":
            try:
                kernel32 = ctypes.windll.kernel32
                h_job = kernel32.CreateJobObjectW(None, None)
                if h_job:
                    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
                    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                    ret = kernel32.SetInformationJobObject(
                        h_job, 9, ctypes.byref(info), ctypes.sizeof(info)
                    )
                    if ret:
                        cls._job_handle = h_job
            except Exception:
                pass

    @classmethod
    def get_process_pids(cls, exe_name: str) -> set:
        pids = set()
        if sys.platform != "win32":
            return pids
        try:
            kernel32 = ctypes.windll.kernel32
            h_snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
            if h_snap and h_snap != -1:
                pe = PROCESSENTRY32W()
                pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
                if kernel32.Process32FirstW(h_snap, ctypes.byref(pe)):
                    target_name = exe_name.lower()
                    while True:
                        if pe.szExeFile.lower() == target_name:
                            pids.add(pe.th32ProcessID)
                        if not kernel32.Process32NextW(h_snap, ctypes.byref(pe)):
                            break
                kernel32.CloseHandle(h_snap)
        except Exception:
            pass
        return pids

    @classmethod
    def register_pid(cls, pid: int) -> Optional[int]:
        cls.init()
        if not pid or sys.platform != "win32":
            return None
        cls._registered_pids.add(pid)
        if cls._job_handle:
            try:
                kernel32 = ctypes.windll.kernel32
                h_proc = kernel32.OpenProcess(0x0001 | 0x0800, False, pid)
                if h_proc:
                    kernel32.AssignProcessToJobObject(cls._job_handle, h_proc)
                    kernel32.CloseHandle(h_proc)
            except Exception:
                pass
        return pid

    @classmethod
    def register(cls, hwnd: int) -> Optional[int]:
        cls.init()
        if not hwnd or sys.platform != "win32":
            return None
        try:
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                return cls.register_pid(pid.value)
        except Exception:
            pass
        return None

    @classmethod
    def dispatch_ex_guarded(cls, app_prog_id: str, exe_name: str):
        cls.init()
        if pythoncom:
            try:
                pythoncom.CoInitialize()
            except Exception:
                pass
        before_pids = cls.get_process_pids(exe_name)
        app = win32com.client.DispatchEx(app_prog_id)
        after_pids = cls.get_process_pids(exe_name)
        new_pids = after_pids - before_pids
        guard_pid = None
        if new_pids:
            guard_pid = list(new_pids)[0]
            cls.register_pid(guard_pid)
        else:
            hwnd = 0
            try:
                hwnd = getattr(app, "Hwnd", getattr(app, "HWND", 0))
            except Exception:
                pass
            if hwnd:
                guard_pid = cls.register(hwnd)
        return app, guard_pid

    @classmethod
    def unregister(cls, pid: Optional[int]):
        if pid and pid in cls._registered_pids:
            cls._registered_pids.discard(pid)

    @classmethod
    def cleanup_all(cls):
        if sys.platform != "win32":
            return
        kernel32 = ctypes.windll.kernel32
        PROCESS_TERMINATE = 0x0001
        for pid in list(cls._registered_pids):
            try:
                h_proc = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
                if h_proc:
                    kernel32.TerminateProcess(h_proc, 1)
                    kernel32.CloseHandle(h_proc)
            except Exception:
                pass
        cls._registered_pids.clear()
        if cls._job_handle:
            try:
                kernel32.CloseHandle(cls._job_handle)
                cls._job_handle = None
            except Exception:
                pass


# ==============================================================================
# 4-2. COM 안정성 가드 (@com_safe) 및 유틸리티
# ==============================================================================
def com_safe(max_retries: int = 5, initial_delay: float = 0.3):
    """
    COM 호출 중 RPC_E_CALL_REJECTED(0x8001010A), RPC_E_SERVERCALL_RETRYLATER(0x80010001)
    발생 시 지수 백오프 자동 재시도 및 ESC 키 전송을 통한 셀 편집 모드 탈출 지원
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if pythoncom:
                try:
                    pythoncom.CoInitialize()
                except Exception:
                    pass
            delay = initial_delay
            last_err = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    is_busy_or_rejected = any(
                        sig in err_str for sig in [
                            "-2147417846", "0x8001010a",
                            "-2147418111", "0x80010001",
                            "0x800706be", "rejected", "busy",
                            "call was rejected by callee"
                        ]
                    )
                    if is_busy_or_rejected and attempt < max_retries - 1:
                        try:
                            if sys.platform == "win32" and win32gui:
                                fg_hwnd = win32gui.GetForegroundWindow()
                                if fg_hwnd and "XLMAIN" in win32gui.GetClassName(fg_hwnd):
                                    VK_ESCAPE = 0x1B
                                    ctypes.windll.user32.keybd_event(VK_ESCAPE, 0, 0, 0)
                                    ctypes.windll.user32.keybd_event(VK_ESCAPE, 0, 2, 0)
                        except Exception:
                            pass
                        time.sleep(delay)
                        delay *= 1.5
                        continue
                    raise e
            if last_err:
                raise last_err
        return wrapper
    return decorator


def sanitize_value(val: Any) -> Any:
    """날짜, Decimal 등 직렬화 곤란한 객체를 안전한 표준 문자열로 살균"""
    if val is None:
        return ""
    if hasattr(val, "strftime"):
        if getattr(val, "hour", 0) or getattr(val, "minute", 0) or getattr(val, "second", 0):
            return val.strftime("%Y-%m-%d %H:%M:%S")
        return val.strftime("%Y-%m-%d")
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val).strip()


def cast_excel_value(val: Any) -> Union[int, float, str]:
    """
    엑셀 셀 주입 시 순수 숫자/실수 문자열을 네이티브 숫자(int/float)로 자동 변환.
    - 수식('='로 시작)이나 선행 0이 포함된 코드/전화번호('010...', '0012')는 문자열 유지.
    """
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return val
    s = str(val).strip()
    if not s or s.startswith("="):
        return s
    if re.match(r"^-?(?:0|[1-9]\d*)$", s):
        try:
            num = int(s)
            if abs(num) < 10**15:
                return num
        except ValueError:
            pass
    if re.match(r"^-?(?:0|[1-9]\d*)\.\d+$", s):
        try:
            return float(s)
        except ValueError:
            pass
    return s


def parse_color_value(color_str: Any) -> Optional[int]:
    """색상명 또는 Hex 코드(#RRGGBB)를 Windows Office COM RGB(BGR) 정수로 변환"""
    if not color_str:
        return None
    if isinstance(color_str, int):
        return color_str
    s = str(color_str).strip().lower()
    NAMED_COLORS = {
        "red": 0x0000FF,
        "blue": 0xFF0000,
        "green": 0x008000,
        "yellow": 0x00FFFF,
        "orange": 0x00A5FF,
        "purple": 0x800080,
        "black": 0x000000,
        "white": 0xFFFFFF,
        "gray": 0x808080,
        "grey": 0x808080,
        "cyan": 0xFFFF00,
        "magenta": 0xFF00FF,
        "lightgray": 0xD3D3D3,
        "lightblue": 0xE6D8AD,
        "lightgreen": 0x90EE90,
        "lightyellow": 0xE0FFFF,
        "pink": 0xCBC0FF,
        "빨강": 0x0000FF,
        "빨간색": 0x0000FF,
        "파랑": 0xFF0000,
        "파란색": 0xFF0000,
        "초록": 0x008000,
        "초록색": 0x008000,
        "녹색": 0x008000,
        "노랑": 0x00FFFF,
        "노란색": 0x00FFFF,
        "주황": 0x00A5FF,
        "주황색": 0x00A5FF,
        "보라": 0x800080,
        "보라색": 0x800080,
        "검정": 0x000000,
        "검정색": 0x000000,
        "흰색": 0xFFFFFF,
        "하양": 0xFFFFFF,
        "회색": 0x808080,
        "연회색": 0xD3D3D3,
        "분홍": 0xCBC0FF,
        "분홍색": 0xCBC0FF,
    }
    if s in NAMED_COLORS:
        return NAMED_COLORS[s]
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 6:
        try:
            r = int(s[0:2], 16)
            g = int(s[2:4], 16)
            b = int(s[4:6], 16)
            return r + (g << 8) + (b << 16)
        except Exception:
            pass
    return None


def parse_style_string(style_str: Optional[str]) -> Dict[str, Any]:
    """'color:red; bold:true; bg:yellow' 형태의 단일 스타일 문자열 파싱"""
    res = {}
    if not style_str:
        return res
    for part in style_str.split(";"):
        part = part.strip()
        if not part:
            continue
        delim = ":" if ":" in part else ("=" if "=" in part else None)
        if delim:
            k, v = part.split(delim, 1)
            k = k.strip().lower()
            v = v.strip()
            if k in ("color", "font-color", "font_color", "색상", "글자색"):
                c_val = parse_color_value(v)
                if c_val is not None:
                    res["color"] = c_val
                    res["color_name"] = v
            elif k in ("bold", "굵게"):
                res["bold"] = v.lower() in ("true", "1", "yes", "on", "참", "예")
            elif k in ("italic", "기울임"):
                res["italic"] = v.lower() in ("true", "1", "yes", "on", "참", "예")
            elif k in ("bg", "background", "background-color", "fill", "배경", "배경색"):
                bg_val = parse_color_value(v)
                if bg_val is not None:
                    res["bg"] = bg_val
                    res["bg_name"] = v
    return res


def normalize_replace_item(val: Any) -> Dict[str, Any]:
    """문자열 또는 딕셔너리 형태의 치환/스타일 명세를 표준 딕셔너리로 정규화"""
    if isinstance(val, str):
        return {"text": val}
    elif isinstance(val, dict):
        res = dict(val)
        # bg 별칭 지원 (fill, background 등)
        for bg_alias in ("fill", "background", "background-color", "배경", "배경색"):
            if bg_alias in res and "bg" not in res:
                res["bg"] = res[bg_alias]
        for col_alias in ("font-color", "font_color", "글자색", "색상"):
            if col_alias in res and "color" not in res:
                res["color"] = res[col_alias]
        if "color" in res and not isinstance(res["color"], int):
            c_val = parse_color_value(res["color"])
            if c_val is not None:
                res["color"] = c_val
        if "bg" in res and not isinstance(res["bg"], int):
            bg_val = parse_color_value(res["bg"])
            if bg_val is not None:
                res["bg"] = bg_val
        return res
    else:
        return {"text": str(val)}


def resolve_target_ext(target: Optional[str]) -> str:
    """파일명이나 앱 키워드로부터 정규화된 문서 확장자 반환"""
    if not target:
        return ""
    t = target.strip().lower()
    base = os.path.basename(t)

    if "." in base:
        file_ext = base.rsplit(".", 1)[-1]
        if file_ext in {"doc", "docx"}:
            return "docx"
        if file_ext in {"xls", "xlsx", "xlsm"}:
            return "xlsx"
        if file_ext in {"ppt", "pptx"}:
            return "pptx"
        if file_ext in {"hwp", "hwpx"}:
            return file_ext
        if file_ext in {"pdf", "csv", "md", "txt", "json", "jsonl"}:
            return file_ext
        return file_ext

    if t in {"word", "doc", "docx"} or t.startswith("문서") or t.startswith("document"):
        return "docx"
    if t in {"excel", "xls", "xlsx", "xlsm"} or t.startswith("book") or "sheet" in t or t.startswith("통합"):
        return "xlsx"
    if t in {"ppt", "pptx", "powerpoint"} or t.startswith("프레젠테이션") or t.startswith("presentation"):
        return "pptx"
    if t in {"hwp", "hwpx"}:
        return t
    if t in {"pdf", "csv", "md", "txt"}:
        return t

    try:
        for e_app in get_all_active_excel_apps():
            try:
                for w in e_app.Workbooks:
                    w_name = w.Name.lower()
                    if w_name == t or w_name.rsplit(".", 1)[0] == t:
                        return "xlsx"
            except Exception:
                pass
        if win32com:
            try:
                w_app = win32com.client.GetActiveObject("Word.Application")
                if w_app:
                    for d in w_app.Documents:
                        d_name = d.Name.lower()
                        if d_name == t or d_name.rsplit(".", 1)[0] == t:
                            return "docx"
            except Exception:
                pass
            try:
                p_app = win32com.client.GetActiveObject("PowerPoint.Application")
                if p_app:
                    for p in p_app.Presentations:
                        p_name = p.Name.lower()
                        if p_name == t or p_name.rsplit(".", 1)[0] == t:
                            return "pptx"
            except Exception:
                pass
    except Exception:
        pass
    return t


def get_dir_size_bytes(dir_path: Path) -> int:
    if not dir_path.exists():
        return 0
    total = 0
    try:
        for entry in dir_path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return total


# ==============================================================================
# 임시 작업 및 저장소 경로 표준화 (C:/cli_temp)
# ==============================================================================
def _resolve_temp_base_dir() -> Path:
    preferred = Path(r"C:/cli_temp")
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        test_file = preferred / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        return preferred
    except Exception:
        fallback = Path.home() / ".cli_temp"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


TEMP_DIR = _resolve_temp_base_dir()
DEFAULT_DATA_DIR = TEMP_DIR / "data"
DEFAULT_CACHE_DIR = TEMP_DIR / "cache"
DEFAULT_BACKUP_DIR = TEMP_DIR / "backup"
DEFAULT_REPORTS_DIR = TEMP_DIR / "reports"


def _ensure_temp_dirs_and_migrate():
    try:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        DEFAULT_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        DEFAULT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        legacy_candidates = [
            (Path(".officecli_cache").resolve(), DEFAULT_CACHE_DIR),
            (Path(".officecli_backup").resolve(), DEFAULT_BACKUP_DIR),
            (Path(".temp").resolve() / "cache", DEFAULT_CACHE_DIR),
            (Path(".temp").resolve() / "backup", DEFAULT_BACKUP_DIR),
            (Path(".temp").resolve() / "reports", DEFAULT_REPORTS_DIR),
        ]
        for src_dir, dst_dir in legacy_candidates:
            if src_dir.exists() and src_dir.is_dir() and src_dir != dst_dir:
                for item in src_dir.iterdir():
                    dest = dst_dir / item.name
                    if not dest.exists():
                        shutil.move(str(item), str(dest))
                try:
                    src_dir.rmdir()
                except Exception:
                    pass

        legacy_temp_root = Path(".temp").resolve()
        if legacy_temp_root.exists() and legacy_temp_root.is_dir() and legacy_temp_root != TEMP_DIR:
            for item in list(legacy_temp_root.iterdir()):
                if item.is_file():
                    dest = TEMP_DIR / item.name
                    if not dest.exists():
                        shutil.move(str(item), str(dest))
            try:
                shutil.rmtree(str(legacy_temp_root), ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass


def check_storage_quota_warning(limit_mb: float = 300.0):
    _ensure_temp_dirs_and_migrate()
    cache_bytes = get_dir_size_bytes(DEFAULT_CACHE_DIR)
    backup_bytes = get_dir_size_bytes(DEFAULT_BACKUP_DIR)
    total_bytes = cache_bytes + backup_bytes

    cache_mb = round(cache_bytes / (1024 * 1024), 2)
    backup_mb = round(backup_bytes / (1024 * 1024), 2)
    total_mb = round(total_bytes / (1024 * 1024), 2)

    if cache_mb >= limit_mb or total_mb >= limit_mb:
        alert_msg = {
            "status": "warning",
            "type": "storage_quota_exceeded",
            "limit_mb": limit_mb,
            "cache_mb": cache_mb,
            "backup_mb": backup_mb,
            "total_mb": total_mb,
            "message": (
                f"[알림] 로컬 임시 저장소({TEMP_DIR}) 용량이 {limit_mb:.0f}MB를 초과했습니다 "
                f"(캐시: {cache_mb}MB, 백업: {backup_mb}MB, 합계: {total_mb}MB). "
                f"'cli_office --clean all' 명령으로 정리하세요."
            )
        }
        print(json.dumps(alert_msg, ensure_ascii=False), file=sys.stderr)


def ensure_window_visible(hwnd: int, default_x: int = 100, default_y: int = 100, width: int = 1100, height: int = 750):
    if not hwnd or not win32com or sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd):
        return

    if bool(user32.IsIconic(hwnd)):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE

    h_monitor = user32.MonitorFromWindow(hwnd, 0)

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rc = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))
    w_width = rc.right - rc.left
    w_height = rc.bottom - rc.top

    if h_monitor == 0 or w_width < 50 or w_height < 50:
        user32.MoveWindow(hwnd, default_x, default_y, width, height, True)

    try:
        cur_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        wnd_thread = user32.GetWindowThreadProcessId(hwnd, None)
        if cur_thread != wnd_thread:
            user32.AttachThreadInput(cur_thread, wnd_thread, True)
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            user32.AttachThreadInput(cur_thread, wnd_thread, False)
        else:
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
    except Exception:
        pass
    time.sleep(0.05)


@com_safe()
def export_document(src_target: str, export_path: str, is_active: bool = False, pages: Optional[str] = None) -> Dict[str, Any]:
    """열려 있는 활성 창이나 로컬 문서를 PDF 또는 다른 포맷(CSV 등)으로 초고속 네이티브 변환/내보내기"""
    sync_desktop_to_default()
    clean_src = (src_target or "").strip()
    abs_out = os.path.abspath(export_path)
    out_dir = os.path.dirname(abs_out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    out_ext = abs_out.lower().rsplit(".", 1)[-1] if "." in abs_out else "pdf"
    src_ext = resolve_target_ext(clean_src)

    # 1. Word -> PDF 변환
    if src_ext in ["docx", "doc", "word"]:
        app, doc = find_active_word_document(clean_src) if is_active else (None, None)
        need_quit = False
        guard_pid = None
        try:
            if not doc:
                abs_src = os.path.abspath(clean_src)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Word.Application", "WINWORD.EXE")
                app.Visible = False
                app.DisplayAlerts = 0
                doc = app.Documents.Open(abs_src, ConfirmConversions=False, ReadOnly=True, PasswordDocument="")
                need_quit = True
            if out_ext == "pdf":
                doc.ExportAsFixedFormat(abs_out, ExportFormat=17, OpenAfterExport=False, OptimizeFor=0)
            else:
                doc.SaveAs2(abs_out)
            return {"status": "ok", "action": "exported", "from": clean_src, "output": abs_out, "format": out_ext, "agent_directive": VERIFIED_DIRECTIVE}
        finally:
            if doc and need_quit:
                try: doc.Close(False)
                except Exception: pass
            if app and need_quit:
                try: app.Quit()
                except Exception: pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

    # 2. PowerPoint -> PDF 변환
    elif src_ext in ["pptx", "ppt", "powerpoint"]:
        app, prs = find_active_ppt_presentation(clean_src) if is_active else (None, None)
        need_quit = False
        guard_pid = None
        try:
            if not prs:
                abs_src = os.path.abspath(clean_src)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("PowerPoint.Application", "POWERPNT.EXE")
                prs = app.Presentations.Open(abs_src, ReadOnly=True, WithWindow=False)
                need_quit = True
            if out_ext == "pdf":
                prs.SaveAs(abs_out, 32)
            else:
                prs.SaveAs(abs_out)
            return {"status": "ok", "action": "exported", "from": clean_src, "output": abs_out, "format": out_ext, "agent_directive": VERIFIED_DIRECTIVE}
        finally:
            if prs and need_quit:
                try: prs.Close()
                except Exception: pass
            if app and need_quit:
                try: app.Quit()
                except Exception: pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

    # 3. Excel -> PDF 또는 CSV 변환
    elif src_ext in ["xlsx", "xls", "xlsm", "excel"] or is_active:
        app, wb = find_active_excel_workbook(clean_src) if is_active else (None, None)
        need_quit = False
        guard_pid = None
        try:
            if not wb:
                abs_src = os.path.abspath(clean_src)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Excel.Application", "EXCEL.EXE")
                app.Visible = False
                app.DisplayAlerts = False
                wb = app.Workbooks.Open(abs_src, UpdateLinks=0, ReadOnly=True, Password="")
                need_quit = True
            target_obj = wb
            if pages:
                for ws in wb.Worksheets:
                    if ws.Name.lower() == pages.strip().lower():
                        target_obj = ws
                        break
            if out_ext == "pdf":
                try:
                    target_obj.ExportAsFixedFormat(0, abs_out)
                except Exception as ex:
                    raise RuntimeError(f"Excel PDF 내보내기 실패: {ex}")
            elif out_ext == "csv":
                ws_to_export = target_obj if hasattr(target_obj, "UsedRange") else wb.ActiveSheet
                used = ws_to_export.UsedRange
                vals = used.Value2 if used else None
                if vals is None:
                    rows = []
                elif not isinstance(vals, (tuple, list)):
                    rows = [[sanitize_value(vals)]]
                else:
                    rows = [
                        [sanitize_value(c) for c in (r if isinstance(r, (tuple, list)) else [r])]
                        for r in vals
                    ]
                with open(abs_out, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerows(rows)
            else:
                target_obj.SaveAs(Filename=abs_out)
            return {"status": "ok", "action": "exported", "from": clean_src, "output": abs_out, "format": out_ext, "agent_directive": VERIFIED_DIRECTIVE}
        finally:
            if wb and need_quit:
                try: wb.Close(False)
                except Exception: pass
            if app and need_quit:
                try: app.Quit()
                except Exception: pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

    raise NotImplementedError(f"'{src_ext}' 문서의 내보내기는 지원되지 않습니다.")


@com_safe()
def manage_excel_range(target: str, action: str, range_str: str, dest_str: Optional[str] = None, is_active: bool = True) -> Dict[str, Any]:
    """Excel 네이티브 셀 범위 이동(Cut), 복사(Copy), 지우기(Clear) 조작"""
    sync_desktop_to_default()
    app, wb = find_active_excel_workbook(target) if is_active else (None, None)
    if not wb:
        return {"status": "error", "message": f"활성 엑셀 통합문서를 찾을 수 없습니다: '{target}'", "agent_directive": STOP_RETRY_DIRECTIVE}

    clean_act = action.lower().strip()
    clean_range = range_str.strip()

    if "!" in clean_range:
        src_sheet_name, src_cell_range = clean_range.split("!", 1)
        try:
            src_ws = wb.Worksheets(src_sheet_name.strip().strip("'"))
        except Exception:
            return {"status": "error", "message": f"원본 시트를 찾을 수 없습니다: '{src_sheet_name}'", "agent_directive": STOP_RETRY_DIRECTIVE}
    else:
        src_ws = wb.ActiveSheet
        src_cell_range = clean_range

    try:
        rng = src_ws.Range(src_cell_range)
    except Exception as ex:
        return {"status": "error", "message": f"유효하지 않은 원본 셀 범위입니다 '{src_cell_range}': {ex}", "agent_directive": STOP_RETRY_DIRECTIVE}

    if clean_act == "clear":
        rng.Clear()
        return {"status": "ok", "action": "range_cleared", "source": f"{src_ws.Name}!{src_cell_range}", "agent_directive": VERIFIED_DIRECTIVE}

    if not dest_str:
        return {"status": "error", "message": f"범위 {clean_act} 작업 시 --dest (예: 'Sheet3!A1')가 필요합니다."}

    clean_dest = dest_str.strip()
    if "!" in clean_dest:
        dest_sheet_name, dest_cell = clean_dest.split("!", 1)
        dest_sheet_clean = dest_sheet_name.strip().strip("'")
        try:
            dest_ws = wb.Worksheets(dest_sheet_clean)
        except Exception:
            try:
                dest_ws = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
                dest_ws.Name = dest_sheet_clean
            except Exception as e_add:
                return {"status": "error", "message": f"대상 시트 '{dest_sheet_clean}'를 찾거나 생성할 수 없습니다: {e_add}"}
    else:
        dest_ws = src_ws
        dest_cell = clean_dest

    try:
        dest_rng = dest_ws.Range(dest_cell)
    except Exception as ex:
        return {"status": "error", "message": f"유효하지 않은 대상 셀입니다 '{dest_cell}': {ex}"}

    if clean_act in ["move", "cut"]:
        rng.Cut(Destination=dest_rng)
        return {"status": "ok", "action": "range_moved", "from": f"{src_ws.Name}!{src_cell_range}", "to": f"{dest_ws.Name}!{dest_cell}", "agent_directive": VERIFIED_DIRECTIVE}
    elif clean_act == "copy":
        rng.Copy(Destination=dest_rng)
        return {"status": "ok", "action": "range_copied", "from": f"{src_ws.Name}!{src_cell_range}", "to": f"{dest_ws.Name}!{dest_cell}", "agent_directive": VERIFIED_DIRECTIVE}
    else:
        return {"status": "error", "message": f"지원하지 않는 range-action입니다: '{action}' (move, copy, clear 중 선택)"}


@com_safe()
def manage_excel_sheet(target: str, action: str, sheet_name: str, new_name: Optional[str] = None, is_active: bool = True) -> Dict[str, Any]:
    """Excel 워크북 내 시트 관리 (생성, 복사, 이름 변경, 삭제)"""
    sync_desktop_to_default()
    act = (action or "").strip().lower()
    app, wb = find_active_excel_workbook(target)
    if not wb:
        raise RuntimeError(f"열려 있는 Excel 창을 찾을 수 없습니다: '{target}'")

    s_name = (sheet_name or "").strip()
    n_name = (new_name or "").strip()

    if act == "add":
        if s_name:
            for ws in wb.Worksheets:
                if ws.Name.lower() == s_name.lower():
                    ws.Activate()
                    return {"status": "ok", "action": "sheet_reused", "target": wb.Name, "sheet": ws.Name, "message": "이미 존재하는 시트이므로 재사용 활성화합니다.", "agent_directive": VERIFIED_DIRECTIVE}
        new_sheet = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
        if s_name:
            new_sheet.Name = s_name
        return {"status": "ok", "action": "sheet_add", "target": wb.Name, "sheet": new_sheet.Name, "agent_directive": VERIFIED_DIRECTIVE}

    elif act == "copy":
        target_ws = None
        for ws in wb.Worksheets:
            if ws.Name.lower() == s_name.lower():
                target_ws = ws
                break
        if not target_ws:
            raise RuntimeError(f"복사할 원본 시트를 찾을 수 없습니다: '{s_name}'")
        target_ws.Copy(After=target_ws)
        copied_ws = wb.ActiveSheet
        if n_name:
            copied_ws.Name = n_name
        return {"status": "ok", "action": "sheet_copy", "target": wb.Name, "source": s_name, "copied": copied_ws.Name, "agent_directive": VERIFIED_DIRECTIVE}

    elif act == "rename":
        if not n_name:
            raise ValueError("--new-name (새 시트 이름) 인자가 필요합니다.")
        for ws in wb.Worksheets:
            if ws.Name.lower() == s_name.lower():
                ws.Name = n_name
                return {"status": "ok", "action": "sheet_rename", "target": wb.Name, "old_name": s_name, "new_name": n_name, "agent_directive": VERIFIED_DIRECTIVE}
        raise RuntimeError(f"이름을 변경할 시트를 찾을 수 없습니다: '{s_name}'")

    elif act == "delete":
        if wb.Worksheets.Count <= 1:
            raise RuntimeError("통합 문서에 시트가 1개뿐이므로 삭제할 수 없습니다.")
        for ws in wb.Worksheets:
            if ws.Name.lower() == s_name.lower():
                app.DisplayAlerts = False
                try:
                    ws.Delete()
                finally:
                    app.DisplayAlerts = True
                return {"status": "ok", "action": "sheet_delete", "target": wb.Name, "deleted_sheet": s_name, "agent_directive": VERIFIED_DIRECTIVE}
        raise RuntimeError(f"삭제할 시트를 찾을 수 없습니다: '{s_name}'")

    raise ValueError(f"지원하지 않는 시트 작업입니다: '{action}'. (add, copy, rename, delete 중 선택)")


def focus_office_window(target: str) -> Dict[str, Any]:
    """실행 중인 대상 오피스 창을 화면 최상위 포그라운드로 활성화하고 포커스를 부여"""
    sync_desktop_to_default()
    if sys.platform != "win32":
        return {"status": "error", "message": "Windows 환경에서만 창 포커스가 지원됩니다."}

    user32 = ctypes.windll.user32
    clean_target = (target or "").strip()
    norm = clean_target.lower()
    hwnd = 0

    if norm in ["excel", "xls", "xlsx"] or not norm:
        apps = get_all_active_excel_apps()
        if apps:
            hwnd = getattr(apps[0], "Hwnd", 0)
    else:
        try:
            _, wb = find_active_excel_workbook(clean_target)
            if wb:
                hwnd = getattr(wb.Application, "Hwnd", 0)
        except Exception:
            pass

    if not hwnd:
        try:
            _, doc = find_active_word_document(clean_target)
            if doc:
                hwnd = getattr(doc.Application.ActiveWindow, "Hwnd", 0)
        except Exception:
            pass

    if not hwnd:
        try:
            _, prs = find_active_ppt_presentation(clean_target)
            if prs:
                hwnd = getattr(prs.Application.ActiveWindow, "HWND", 0)
        except Exception:
            pass

    if hwnd and user32.IsWindow(hwnd):
        ensure_window_visible(hwnd)
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        return {"status": "ok", "action": "focused", "target": clean_target, "hwnd": hwnd, "agent_directive": VERIFIED_DIRECTIVE}

    return {"status": "error", "message": f"활성화할 오피스 창을 찾을 수 없습니다: '{clean_target}'"}


def fix_office_environment(kill_hidden_only: bool = True) -> Dict[str, Any]:
    """[자가 복구 엔진] 오피스 실행 환경 진단 및 충돌 복구"""
    res = {
        "status": "ok",
        "action": "fix_office_environment",
        "terminated_pids": [],
        "cleaned_temps": [],
        "errors": []
    }
    if sys.platform != "win32":
        res["message"] = "Windows 환경이 아니므로 건너뜁니다."
        return res

    try:
        ComProcessGuard.cleanup_all()
    except Exception as e:
        res["errors"].append(f"ComProcessGuard cleanup error: {e}")

    target_exes = ["EXCEL.EXE", "WINWORD.EXE", "POWERPNT.EXE"]
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    PROCESS_TERMINATE = 0x0001

    visible_pids = set()

    def _enum_windows_proc(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                visible_pids.add(pid.value)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    enum_proc_inst = WNDENUMPROC(_enum_windows_proc)
    user32.EnumWindows(enum_proc_inst, 0)

    for exe in target_exes:
        pids = ComProcessGuard.get_process_pids(exe)
        for pid in pids:
            if kill_hidden_only and pid in visible_pids:
                continue
            try:
                h_proc = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
                if h_proc:
                    kernel32.TerminateProcess(h_proc, 1)
                    kernel32.CloseHandle(h_proc)
                    res["terminated_pids"].append({"exe": exe, "pid": pid})
            except Exception as pe:
                res["errors"].append(f"Kill pid {pid} error: {pe}")

    try:
        for tmp_file in Path(".").glob("~$*.*"):
            try:
                tmp_file.unlink(missing_ok=True)
                res["cleaned_temps"].append(str(tmp_file))
            except Exception:
                pass
        if TEMP_DIR.exists():
            for tmp_file in TEMP_DIR.glob("**/_temp_*.*"):
                try:
                    tmp_file.unlink(missing_ok=True)
                    res["cleaned_temps"].append(str(tmp_file))
                except Exception:
                    pass
    except Exception:
        pass

    res["message"] = (
        f"오피스 환경 점검 및 복구 완료. 좀비 프로세스 {len(res['terminated_pids'])}개 종료, "
        f"임시 잠금 파일 {len(res['cleaned_temps'])}개 정리됨."
    )
    return res


def get_all_active_excel_apps() -> List[Any]:
    """Windows에 실행 중인 모든 엑셀 인스턴스의 Application COM 객체를 전수 수집"""
    apps = []
    seen_hwnds = set()

    if win32com:
        try:
            app_std = win32com.client.GetActiveObject("Excel.Application")
            if app_std and getattr(app_std, "Hwnd", 0) not in seen_hwnds:
                apps.append(app_std)
                seen_hwnds.add(app_std.Hwnd)
        except Exception:
            pass

    if sys.platform == "win32" and win32gui and pythoncom:
        sync_desktop_to_default()
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
        oleacc = getattr(ctypes.oledll, "oleacc", None)
        if oleacc:
            class GUID_STRUCT(ctypes.Structure):
                _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort), ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]
            iid_disp = GUID_STRUCT(0x00020400, 0x0000, 0x0000, (ctypes.c_ubyte * 8)(0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))

            def enum_xl(hwnd, _):
                cls = win32gui.GetClassName(hwnd)
                if "XLMAIN" in cls:
                    h_children = []
                    win32gui.EnumChildWindows(hwnd, lambda ch, _: h_children.append(ch) if win32gui.GetClassName(ch) == "EXCEL7" else None, None)
                    if h_children:
                        h7 = h_children[0]
                        p_acc = ctypes.c_void_p()
                        res = oleacc.AccessibleObjectFromWindow(h7, ctypes.c_uint32(0xFFFFFFF0), ctypes.byref(iid_disp), ctypes.byref(p_acc))
                        if res == 0 and p_acc.value:
                            try:
                                ptr = pythoncom.ObjectFromAddress(p_acc.value)
                                disp_obj = ptr.QueryInterface(pythoncom.IID_IDispatch)
                                disp = win32com.client.Dispatch(disp_obj)
                                app_inst = disp.Application
                                if app_inst and app_inst.Hwnd not in seen_hwnds:
                                    apps.append(app_inst)
                                    seen_hwnds.add(app_inst.Hwnd)
                            except Exception:
                                pass
            try:
                win32gui.EnumWindows(enum_xl, None)
            except Exception:
                pass

    return apps


def find_active_excel_workbook(target_wb_name: Optional[str] = None) -> Tuple[Optional[Any], Optional[Any]]:
    all_apps = get_all_active_excel_apps()
    clean_name = (target_wb_name or "").strip()
    norm_name = clean_name.lower()

    if clean_name and norm_name not in ["excel", "xls", "xlsx", "xlsm"]:
        for a in all_apps:
            try:
                for w in a.Workbooks:
                    w_low = w.Name.lower()
                    w_stem = w_low.rsplit(".", 1)[0]
                    if w_low == norm_name or w_stem == norm_name or norm_name in w_low:
                        return a, w
            except Exception:
                pass
        raise RuntimeError(f"열려 있는 Excel 창 중에서 '{clean_name}' 통합 문서를 찾을 수 없습니다. 'cli_office --list-active'로 정확한 창 이름을 확인하세요.")

    app = all_apps[0] if all_apps else None
    if not app and win32com:
        try:
            app = win32com.client.GetActiveObject("Excel.Application")
        except Exception:
            pass
    wb = app.ActiveWorkbook if (app and app.Workbooks.Count > 0) else None
    return app, wb


def find_active_word_document(target_doc_name: Optional[str] = None) -> Tuple[Optional[Any], Optional[Any]]:
    sync_desktop_to_default()
    app = None
    doc = None
    clean_name = (target_doc_name or "").strip()
    norm_name = clean_name.lower()

    if win32com:
        try:
            app = win32com.client.GetActiveObject("Word.Application")
        except Exception:
            pass

    if clean_name and norm_name not in ["word", "doc", "docx"]:
        if not app or app.Documents.Count == 0:
            raise RuntimeError(f"실행 중인 Word 프로그램이나 열려 있는 문서를 찾을 수 없습니다: '{clean_name}'")
        for d in app.Documents:
            d_low = d.Name.lower()
            d_stem = d_low.rsplit(".", 1)[0]
            if d_low == norm_name or d_stem == norm_name:
                return app, d
        for d in app.Documents:
            d_low = d.Name.lower()
            if norm_name in d_low:
                return app, d
        raise RuntimeError(f"열려 있는 Word 창 중에서 '{clean_name}' 문서를 찾을 수 없습니다. 'cli_office --list-active'로 정확한 창 이름을 확인하세요.")

    if app and app.Documents.Count > 0:
        try:
            doc = app.ActiveDocument if app.Documents.Count > 0 else app.Documents(1)
        except Exception:
            pass

    return app, doc


def find_active_ppt_presentation(target_prs_name: Optional[str] = None) -> Tuple[Optional[Any], Optional[Any]]:
    sync_desktop_to_default()
    app = None
    prs = None
    clean_name = (target_prs_name or "").strip()
    norm_name = clean_name.lower()

    if win32com:
        try:
            app = win32com.client.GetActiveObject("PowerPoint.Application")
        except Exception:
            pass

    if clean_name and norm_name not in ["ppt", "pptx", "powerpoint"]:
        if not app or app.Presentations.Count == 0:
            raise RuntimeError(f"실행 중인 PowerPoint 프로그램이나 열려 있는 프레젠테이션을 찾을 수 없습니다: '{clean_name}'")
        for p in app.Presentations:
            p_low = p.Name.lower()
            p_stem = p_low.rsplit(".", 1)[0]
            if p_low == norm_name or p_stem == norm_name:
                return app, p
        for p in app.Presentations:
            p_low = p.Name.lower()
            if norm_name in p_low:
                return app, p
        raise RuntimeError(f"열려 있는 PowerPoint 창 중에서 '{clean_name}' 프레젠테이션을 찾을 수 없습니다. 'cli_office --list-active'로 정확한 창 이름을 확인하세요.")

    if app and app.Presentations.Count > 0:
        try:
            prs = app.ActivePresentation if app.Presentations.Count > 0 else app.Presentations(1)
        except Exception:
            pass

    return app, prs


def list_active_office_windows() -> List[Dict[str, Any]]:
    """현재 화면에 열려 있는 모든 Office(Excel, Word, PowerPoint) 활성 창/문서 목록을 반환"""
    sync_desktop_to_default()
    results = []

    try:
        excel_apps = get_all_active_excel_apps()
        for app in excel_apps:
            try:
                act_name = getattr(app.ActiveWorkbook, "Name", "") if app.Workbooks.Count > 0 else ""
                for w in app.Workbooks:
                    sheet_names = [ws.Name for ws in w.Worksheets]
                    results.append({
                        "app": "excel",
                        "name": w.Name,
                        "full_path": getattr(w, "FullName", ""),
                        "active": (w.Name == act_name),
                        "sheets": sheet_names,
                        "details": f"{w.Sheets.Count} sheets ({', '.join(sheet_names[:5])})"
                    })
            except Exception:
                pass
    except Exception:
        pass

    try:
        if win32com:
            w_app = win32com.client.GetActiveObject("Word.Application")
            if w_app:
                act_name = getattr(w_app.ActiveDocument, "Name", "") if w_app.Documents.Count > 0 else ""
                for d in w_app.Documents:
                    p_count = 1
                    try:
                        p_count = d.ComputeStatistics(2)
                    except Exception:
                        pass
                    results.append({
                        "app": "word",
                        "name": d.Name,
                        "full_path": getattr(d, "FullName", ""),
                        "active": (d.Name == act_name),
                        "details": f"{p_count} pages"
                    })
    except Exception:
        pass

    try:
        if win32com:
            p_app = win32com.client.GetActiveObject("PowerPoint.Application")
            if p_app:
                act_name = getattr(p_app.ActivePresentation, "Name", "") if p_app.Presentations.Count > 0 else ""
                for p in p_app.Presentations:
                    results.append({
                        "app": "ppt",
                        "name": p.Name,
                        "full_path": getattr(p, "FullName", ""),
                        "active": (p.Name == act_name),
                        "details": f"{p.Slides.Count} slides"
                    })
    except Exception:
        pass

    return results


# ==============================================================================
# 5. 캐시 매니저 (CacheManager)
# ==============================================================================
class CacheManager:
    def __init__(self, cache_dir: Optional[str] = None):
        _ensure_temp_dirs_and_migrate()
        self.cache_dir = Path(cache_dir).resolve() if cache_dir else DEFAULT_CACHE_DIR
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def get_cache_path(self, file_path: str) -> Path:
        abs_path = os.path.abspath(file_path)
        mtime = os.path.getmtime(abs_path) if os.path.exists(abs_path) else 0
        hash_key = hashlib.md5(f"{abs_path}_{mtime}".encode("utf-8")).hexdigest()
        return self.cache_dir / f"{hash_key}.jsonl"

    def load(self, file_path: str) -> Optional[List[Dict[str, Any]]]:
        path = self.get_cache_path(file_path)
        if path.exists():
            try:
                records = []
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line_s = line.strip()
                        if line_s:
                            records.append(json.loads(line_s))
                return records
            except Exception:
                return None
        return None

    def save(self, file_path: str, records: List[Dict[str, Any]]) -> None:
        path = self.get_cache_path(file_path)
        try:
            with open(path, "w", encoding="utf-8", errors="replace") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def clean(self) -> Dict[str, Any]:
        freed_bytes = get_dir_size_bytes(self.cache_dir)
        removed_files = 0
        if self.cache_dir.exists():
            for f in self.cache_dir.glob("*"):
                if f.is_file():
                    try:
                        f.unlink()
                        removed_files += 1
                    except Exception:
                        pass
                elif f.is_dir():
                    try:
                        shutil.rmtree(f)
                        removed_files += 1
                    except Exception:
                        pass
        return {
            "status": "ok",
            "action": "cache_cleaned",
            "removed_items": removed_files,
            "freed_mb": round(freed_bytes / (1024 * 1024), 2)
        }

    def status(self, limit_mb: float = 300.0) -> Dict[str, Any]:
        size_bytes = get_dir_size_bytes(self.cache_dir)
        jsonl_count = len(list(self.cache_dir.glob("*.jsonl"))) if self.cache_dir.exists() else 0
        img_dirs = len([d for d in self.cache_dir.glob("*_images") if d.is_dir()]) if self.cache_dir.exists() else 0
        used_mb = round(size_bytes / (1024 * 1024), 2)
        return {
            "status": "ok",
            "cache_dir": str(self.cache_dir),
            "cached_documents": jsonl_count,
            "image_folders": img_dirs,
            "used_mb": used_mb,
            "limit_mb": limit_mb
        }


# ==============================================================================
# 5-2. 백업 및 복원 매니저 (BackupManager)
# ==============================================================================
class BackupManager:
    def __init__(self, backup_dir: Optional[str] = None):
        _ensure_temp_dirs_and_migrate()
        self.backup_dir = Path(backup_dir).resolve() if backup_dir else DEFAULT_BACKUP_DIR
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_file = self.backup_dir / "manifest.json"

    def _load_manifest(self) -> List[Dict[str, Any]]:
        if self.manifest_file.exists():
            try:
                return json.loads(self.manifest_file.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save_manifest(self, manifest: List[Dict[str, Any]]):
        self.manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    @com_safe()
    def backup_target(self, target: str, is_active: bool) -> Optional[str]:
        sync_desktop_to_default()
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        norm_target = (target or "").strip().lower()

        if not is_active:
            abs_path = os.path.abspath(target)
            if os.path.exists(abs_path):
                ext = abs_path.split(".")[-1]
                backup_name = f"{Path(abs_path).stem}_{timestamp}.{ext}"
                backup_path = self.backup_dir / backup_name
                shutil.copy2(abs_path, backup_path)

                entry = {
                    "id": f"{Path(abs_path).stem}_{timestamp}",
                    "target": abs_path,
                    "type": "file",
                    "backup_path": str(backup_path),
                    "created_at": timestamp
                }
                manifest = self._load_manifest()
                manifest.append(entry)
                self._save_manifest(manifest)
                return entry["id"]
            return None

        manifest = self._load_manifest()
        safe_id_name = re.sub(r"[^a-zA-Z0-9가-힣_-]", "_", norm_target) or "active"
        entry_id = f"active_{safe_id_name}_{timestamp}"

        res_ext = resolve_target_ext(target)
        if res_ext in ["docx", "doc", "word"]:
            try:
                app, doc = find_active_word_document(target)
                if doc:
                    backup_file = self.backup_dir / f"word_active_{timestamp}.docx"
                    saved_ok = False
                    orig_full = getattr(doc, "FullName", "")
                    if getattr(doc, "Path", "") and getattr(doc, "Saved", False) and os.path.exists(orig_full):
                        try:
                            shutil.copy2(orig_full, str(backup_file))
                            saved_ok = True
                        except Exception:
                            pass
                    if not saved_ok:
                        temp_doc = None
                        try:
                            temp_doc = app.Documents.Add(Visible=False)
                            temp_doc.Content.FormattedText = doc.Content.FormattedText
                            temp_doc.SaveAs2(str(backup_file.resolve()), FileFormat=16)
                            saved_ok = True
                        except Exception:
                            if orig_full and os.path.exists(orig_full):
                                try:
                                    shutil.copy2(orig_full, str(backup_file))
                                    saved_ok = True
                                except Exception:
                                    pass
                        finally:
                            if temp_doc:
                                try:
                                    temp_doc.Close(False)
                                except Exception:
                                    pass
                    if saved_ok and backup_file.exists():
                        entry = {
                            "id": entry_id,
                            "target": target if norm_target not in ["word", "doc", "docx"] else "word",
                            "app_type": "word",
                            "type": "active_file",
                            "backup_path": str(backup_file),
                            "created_at": timestamp
                        }
                        manifest.append(entry)
                        self._save_manifest(manifest)
                        return entry_id
            except Exception:
                pass

        elif res_ext in ["pptx", "ppt", "powerpoint"]:
            try:
                app, prs = find_active_ppt_presentation(target)
                if prs:
                    backup_file = self.backup_dir / f"ppt_active_{timestamp}.pptx"
                    saved = False
                    try:
                        prs.SaveCopyAs(str(backup_file))
                        saved = True
                    except Exception:
                        try:
                            orig_path = getattr(prs, "FullName", "")
                            if orig_path and os.path.exists(orig_path):
                                shutil.copy2(orig_path, str(backup_file))
                                saved = True
                        except Exception:
                            pass

                    if saved and backup_file.exists():
                        entry = {
                            "id": entry_id,
                            "target": "ppt",
                            "app_type": "ppt",
                            "type": "active_file",
                            "backup_path": str(backup_file),
                            "created_at": timestamp
                        }
                        manifest.append(entry)
                        self._save_manifest(manifest)
                        return entry_id
            except Exception:
                pass

        else:
            try:
                _, wb = find_active_excel_workbook(target)
                if wb:
                    backup_file = self.backup_dir / f"excel_{safe_id_name}_{timestamp}.xlsx"
                    wb.SaveCopyAs(str(backup_file))
                    entry = {
                        "id": entry_id,
                        "target": target if norm_target not in ["excel", "xls", "xlsx"] else "excel",
                        "app_type": "excel",
                        "type": "active_file",
                        "backup_path": str(backup_file),
                        "created_at": timestamp
                    }
                    manifest.append(entry)
                    self._save_manifest(manifest)
                    return entry_id
            except Exception:
                pass

        return None

    def list_backups(self) -> List[Dict[str, Any]]:
        return self._load_manifest()

    def clean(self, keep_latest: int = 0) -> Dict[str, Any]:
        manifest = self._load_manifest()
        before_bytes = get_dir_size_bytes(self.backup_dir)

        if keep_latest > 0 and len(manifest) > keep_latest:
            to_delete = manifest[:-keep_latest]
            to_keep = manifest[-keep_latest:]
        elif keep_latest > 0:
            to_delete = []
            to_keep = manifest
        else:
            to_delete = manifest
            to_keep = []

        removed_count = 0
        for item in to_delete:
            b_path = Path(item.get("backup_path", ""))
            if b_path.exists():
                try:
                    b_path.unlink()
                    removed_count += 1
                except Exception:
                    pass

        if keep_latest == 0:
            for f in self.backup_dir.glob("*"):
                if f.is_file() and f.name != "manifest.json":
                    try:
                        f.unlink()
                        removed_count += 1
                    except Exception:
                        pass

        self._save_manifest(to_keep)
        after_bytes = get_dir_size_bytes(self.backup_dir)
        return {
            "status": "ok",
            "action": "backup_cleaned",
            "removed_snapshots": removed_count,
            "remaining_snapshots": len(to_keep),
            "freed_mb": round(max(0, before_bytes - after_bytes) / (1024 * 1024), 2)
        }

    @com_safe()
    def restore(self, target: Optional[str] = None, snapshot_id: Optional[str] = None) -> Dict[str, Any]:
        manifest = self._load_manifest()
        if not manifest:
            raise RuntimeError("복원 가능한 백업 스냅샷이 존재하지 않습니다.")

        candidates = []
        if snapshot_id:
            candidates = [e for e in manifest if e.get("id") == snapshot_id or snapshot_id in e.get("id", "")]
        elif target:
            norm_target = (target or "").strip().lower()
            target_abs = os.path.abspath(target).lower()
            target_base = Path(target).name.lower()
            candidates = [
                e for e in manifest
                if (norm_target and norm_target in e.get("target", "").lower())
                or (norm_target and norm_target == e.get("app_type", "").lower())
                or (target_abs and target_abs == e.get("target", "").lower())
                or (target_base and target_base in Path(e.get("target", "")).name.lower())
            ]
        else:
            candidates = [manifest[-1]]

        if not candidates:
            raise RuntimeError(f"복원 가능한 백업 스냅샷을 찾을 수 없습니다: target={target}, snapshot_id={snapshot_id}")

        latest_entry = candidates[-1]
        backup_path = Path(latest_entry["backup_path"])
        if not backup_path.exists():
            raise FileNotFoundError(f"백업 파일이 존재하지 않습니다: {backup_path}")

        b_type = latest_entry["type"]
        orig_target = latest_entry["target"]
        app_type = latest_entry.get("app_type", "").lower()

        if b_type == "file":
            shutil.copy2(backup_path, orig_target)
            return {"status": "ok", "action": "restored", "target": orig_target, "from": str(backup_path), "snapshot_id": latest_entry["id"], "agent_directive": VERIFIED_DIRECTIVE}

        if b_type == "active_file":
            norm_tgt = (orig_target or "").lower()
            restored_path = None
            if norm_tgt in ["word", "doc", "docx"] or app_type == "word":
                app, doc = find_active_word_document(orig_target)
                if not app:
                    try:
                        app = win32com.client.GetActiveObject("Word.Application")
                    except Exception:
                        app = win32com.client.Dispatch("Word.Application")
                app.Visible = True
                orig_path = ""
                try:
                    target_doc = doc if doc else (app.ActiveDocument if app.Documents.Count > 0 else None)
                    if target_doc:
                        orig_path = target_doc.FullName
                        target_doc.Close(False)
                except Exception:
                    pass

                if orig_path and os.path.exists(orig_path):
                    shutil.copy2(backup_path, orig_path)
                    app.Documents.Open(orig_path)
                    restored_path = orig_path
                else:
                    app.Documents.Open(str(backup_path.resolve()))
                    restored_path = str(backup_path.resolve())

            elif norm_tgt in ["ppt", "pptx", "powerpoint"] or app_type == "ppt":
                app, prs = find_active_ppt_presentation(orig_target)
                if not app:
                    try:
                        app = win32com.client.GetActiveObject("PowerPoint.Application")
                    except Exception:
                        app = win32com.client.Dispatch("PowerPoint.Application")
                app.Visible = True
                orig_path = ""
                try:
                    target_prs = prs if prs else (app.ActivePresentation if app.Presentations.Count > 0 else None)
                    if target_prs:
                        orig_path = target_prs.FullName
                        target_prs.Close()
                except Exception:
                    pass

                if orig_path and os.path.exists(orig_path):
                    shutil.copy2(backup_path, orig_path)
                    app.Presentations.Open(orig_path)
                    restored_path = orig_path
                else:
                    app.Presentations.Open(str(backup_path.resolve()))
                    restored_path = str(backup_path.resolve())

            elif norm_tgt in ["excel", "xls", "xlsx"] or app_type == "excel":
                app, wb = find_active_excel_workbook(orig_target)
                if not app:
                    try:
                        app = win32com.client.GetActiveObject("Excel.Application")
                    except Exception:
                        app = win32com.client.Dispatch("Excel.Application")
                app.Visible = True
                orig_path = ""
                try:
                    target_wb = wb if wb else (app.ActiveWorkbook if app.Workbooks.Count > 0 else None)
                    if target_wb:
                        orig_path = target_wb.FullName
                        target_wb.Close(False)
                except Exception:
                    pass

                if orig_path and os.path.exists(orig_path):
                    shutil.copy2(backup_path, orig_path)
                    app.Workbooks.Open(orig_path)
                    restored_path = orig_path
                else:
                    app.Workbooks.Open(str(backup_path.resolve()))
                    restored_path = str(backup_path.resolve())
            else:
                raise RuntimeError(f"지원되지 않는 활성 파일 복원 대상입니다: {orig_target}")

            return {
                "status": "ok",
                "action": "restored",
                "target": orig_target,
                "from": str(backup_path),
                "restored_to": restored_path,
                "snapshot_id": latest_entry["id"],
                "agent_directive": VERIFIED_DIRECTIVE
            }

        return {"status": "error", "message": "알 수 없는 백업 형식입니다."}


_KO_SUFFIX_PATTERNS = [
    r"(에서는|으로부터|에서부터|이라고|이라는|으로써|으로서|에게서|한테서|하다가|하도록|하였다|하셨다|했었다|습니다|합니다|입니다|스러운|스럽게|시키기|시키는|시켜서)",
    r"(에서|에게|한테|부터|까지|마저|조차|보다|처럼|으로|로써|로서|이라|라는|하고|하며|이고|이며|하여|하면|하게|하니|하는|하지|할수|있는|없는|됐다|된다|되면|되어|적인)",
    r"(은|는|이|가|을|를|의|에|로|와|과|도|만|뿐|한|할|된|될|해)"
]
_KO_SUFFIX_RES = [re.compile(p + r"$") for p in _KO_SUFFIX_PATTERNS]


def _strip_ko_stem(token: str) -> str:
    curr = token
    for _ in range(3):
        changed = False
        for pattern_re in _KO_SUFFIX_RES:
            sub = pattern_re.sub("", curr)
            if sub and sub != curr and len(sub) >= 2:
                curr = sub
                changed = True
                break
        if not changed:
            break
    return curr


# ==============================================================================
# 6. 경량 하이브리드 검색 엔진 (HybridSearcher)
# ==============================================================================
class HybridSearcher:
    @staticmethod
    def search(records: List[Dict[str, Any]], query: str, top_k: int = 0) -> List[Dict[str, Any]]:
        if not query or not query.strip():
            return records

        q_clean = query.strip()
        raw_tokens = [t.lower() for t in re.split(r"\s+", q_clean) if t]
        if not raw_tokens:
            return records

        token_groups = []
        seen_raw = set()
        all_tokens = set()
        for t in raw_tokens:
            if t not in seen_raw:
                seen_raw.add(t)
                all_tokens.add(t)
                stem = None
                if len(t) >= 2:
                    s = _strip_ko_stem(t)
                    if s and s != t:
                        stem = s
                        all_tokens.add(s)
                token_groups.append((t, stem))

        N = max(1, len(records))
        doc_freq = {}
        for rec in records:
            text = " ".join(str(c) for c in rec["data"]) if isinstance(rec.get("data"), list) else str(rec.get("data", ""))
            text_lower = text.lower()
            for token in all_tokens:
                if token in text_lower:
                    doc_freq[token] = doc_freq.get(token, 0) + 1

        idf = {}
        for token in all_tokens:
            df = doc_freq.get(token, 0)
            idf[token] = math.log(1.0 + (N - df + 0.5) / (df + 0.5))

        regex_pattern = None
        try:
            regex_pattern = re.compile(q_clean, re.IGNORECASE)
        except Exception:
            pass

        q_nospace = re.sub(r"\s+", "", q_clean).lower()

        scored_results = []
        current_table_header = ""

        for rec in records:
            data = rec.get("data", "")
            rec_type = rec.get("type", "")
            coord = str(rec.get("coord", ""))

            if rec_type == "table_row":
                if "Row:1" in coord or not current_table_header:
                    current_table_header = " ".join(str(c) for c in data) if isinstance(data, list) else str(data)
            else:
                current_table_header = ""

            base_text = " ".join(str(c) for c in data) if isinstance(data, list) else str(data)
            eval_text = f"{base_text} {current_table_header}" if (rec_type == "table_row" and "Row:1" not in coord and current_table_header) else base_text

            section = str(rec.get("section", ""))
            text_lower = eval_text.lower()
            section_lower = section.lower()
            text_nospace = re.sub(r"\s+", "", text_lower)

            score = 0.0

            if regex_pattern and regex_pattern.search(base_text):
                score += 15.0
            elif q_clean.lower() in base_text.lower():
                score += 15.0
            elif len(q_nospace) >= 4 and q_nospace in text_nospace:
                score += 10.0

            doc_len = max(10, len(text_lower))
            len_norm = 0.75 + 0.25 * (doc_len / 150.0)

            matched_token_count = 0
            for t, stem in token_groups:
                candidates = [t]
                if stem:
                    candidates.append(stem)

                best_group_score = 0.0
                group_matched = False

                for token in candidates:
                    token_idf = idf.get(token, 1.0)
                    count = text_lower.count(token)
                    curr_score = 0.0
                    if count > 0:
                        group_matched = True
                        tf = (count * 2.2) / (count + 1.2 * len_norm)
                        curr_score = tf * (token_idf + 1.0) * 3.0
                    elif len(token) >= 4:
                        bigrams = [token[i:i+2] for i in range(len(token) - 1)]
                        if bigrams:
                            matched_bigrams = sum(1 for bg in bigrams if bg in text_lower)
                            if (matched_bigrams / len(bigrams)) >= 0.7:
                                group_matched = True
                                curr_score = token_idf * 1.5

                    if curr_score > best_group_score:
                        best_group_score = curr_score

                if group_matched:
                    matched_token_count += 1
                    score += best_group_score

            if matched_token_count > 1:
                score += matched_token_count * 2.0

            for t, stem in token_groups:
                if t in section_lower or (stem and stem in section_lower):
                    score += 5.0
                    break

            if score > 0.0:
                rec_copy = rec.copy()
                rec_copy["score"] = round(score, 2)
                scored_results.append(rec_copy)

        scored_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        if top_k and top_k > 0:
            return scored_results[:top_k]
        return scored_results


# ==============================================================================
# 7. 통합 문서 파서 (DocumentParser)
# ==============================================================================
class DocumentParser:
    @staticmethod
    def parse_pdf(file_path: str, extract_images: bool = False) -> List[Dict[str, Any]]:
        if not pymupdf4llm:
            raise RuntimeError("pymupdf4llm 패키지가 설치되지 않았습니다. (pip install pymupdf4llm)")

        abs_path = os.path.abspath(file_path)
        pdf_dir = os.path.dirname(abs_path)
        img_dir = None
        if extract_images:
            stem = Path(abs_path).stem
            img_dir = os.path.join(pdf_dir, f"{stem}_images")
            os.makedirs(img_dir, exist_ok=True)

        chunks = pymupdf4llm.to_markdown(
            abs_path,
            page_chunks=True,
            write_images=bool(extract_images),
            image_path=img_dir if extract_images else None,
            embed_images=False
        )

        records = []
        item_id = 0
        current_section = ""
        total_extracted_chars = 0
        added_image_paths = set()

        for chunk in chunks:
            meta = chunk.get("metadata", {})
            page_num = meta.get("page_number", meta.get("page", 1))
            raw_text = chunk.get("text", "")
            lines = raw_text.splitlines()

            for line_idx, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue

                if stripped.startswith("![") and "](" in stripped:
                    if extract_images:
                        m = re.search(r"!\[[^\]]*\]\(([^)]+)\)", stripped)
                        if m:
                            raw_img_ref = m.group(1).strip()
                            candidates = [
                                os.path.abspath(raw_img_ref),
                                os.path.abspath(os.path.join(pdf_dir, raw_img_ref)),
                            ]
                            if img_dir:
                                candidates.append(os.path.abspath(os.path.join(img_dir, os.path.basename(raw_img_ref))))
                            resolved_img = next((c for c in candidates if os.path.exists(c)), candidates[0])
                            if resolved_img not in added_image_paths:
                                added_image_paths.add(resolved_img)
                                records.append({
                                    "id": item_id,
                                    "src": os.path.basename(abs_path),
                                    "ext": "pdf",
                                    "page": page_num,
                                    "section": current_section or "Media",
                                    "coord": f"p.{page_num}/Img.{len(added_image_paths)}",
                                    "type": "image",
                                    "data": resolved_img
                                })
                                item_id += 1
                    continue

                total_extracted_chars += len(stripped)

                if stripped.startswith("|") and stripped.endswith("|"):
                    if re.match(r"^\|[\s\-:|]+\|$", stripped):
                        continue
                    inner = stripped[1:-1]
                    raw_cells = re.split(r"(?<!\\)\|", inner)
                    cells = []
                    for c in raw_cells:
                        txt = c.strip().replace(r"\|", "|")
                        txt = re.sub(r"<br\s*/?>", "\n", txt, flags=re.I)
                        txt = re.sub(r"\*\*([^*]+)\*\*", r"\1", txt)
                        txt = re.sub(r"\*([^*]+)\*", r"\1", txt)
                        txt = re.sub(r"</?[a-zA-Z0-9]+[^>]*>", "", txt)
                        cells.append(txt.strip())
                    records.append({
                        "id": item_id,
                        "src": os.path.basename(abs_path),
                        "ext": "pdf",
                        "page": page_num,
                        "section": current_section,
                        "coord": f"p.{page_num}/L.{line_idx}",
                        "type": "table_row",
                        "data": cells
                    })
                    item_id += 1
                    continue

                if stripped.startswith("#"):
                    current_section = stripped.lstrip("#").strip()
                    doc_type = "heading"
                    clean_text = stripped.lstrip("#").strip()
                else:
                    doc_type = "text"
                    clean_text = stripped

                clean_text = re.sub(r"<br\s*/?>", "\n", clean_text, flags=re.I)
                clean_text = re.sub(r"\*\*([^*]+)\*\*", r"\1", clean_text)
                clean_text = re.sub(r"\*([^*]+)\*", r"\1", clean_text)
                clean_text = re.sub(r"</?[a-zA-Z0-9]+[^>]*>", "", clean_text)

                records.append({
                    "id": item_id,
                    "src": os.path.basename(abs_path),
                    "ext": "pdf",
                    "page": page_num,
                    "section": current_section,
                    "coord": f"p.{page_num}/L.{line_idx}",
                    "type": doc_type,
                    "data": clean_text.strip()
                })
                item_id += 1

        if extract_images and img_dir and os.path.exists(img_dir):
            for img_f in sorted(Path(img_dir).glob("*")):
                if img_f.is_file() and str(img_f.resolve()) not in added_image_paths:
                    added_image_paths.add(str(img_f.resolve()))
                    records.append({
                        "id": item_id,
                        "src": os.path.basename(abs_path),
                        "ext": "pdf",
                        "page": 1,
                        "section": "Media",
                        "coord": f"Img:{len(added_image_paths)}",
                        "type": "image",
                        "data": str(img_f.resolve())
                    })
                    item_id += 1

        if total_extracted_chars == 0 and len(chunks) > 0 and not added_image_paths:
            records.append({
                "id": 0,
                "src": os.path.basename(abs_path),
                "ext": "pdf",
                "page": 1,
                "section": "System",
                "coord": "Warning",
                "type": "text",
                "data": f"경고: 이 PDF(총 {len(chunks)}페이지)는 추출 가능한 텍스트 레이어가 없는 스캔/이미지 기반 문서입니다."
            })

        return records

    @staticmethod
    @com_safe()
    def parse_excel(file_path: Optional[str] = None, is_active: bool = False, extract_images: bool = False, target_pages: Optional[Set[Union[int, str]]] = None) -> List[Dict[str, Any]]:
        if not win32com:
            raise RuntimeError("pywin32가 설치되지 않았습니다.")

        sync_desktop_to_default()
        records = []
        item_id = 0

        app = None
        wb = None
        need_quit = False
        guard_pid = None

        try:
            if is_active:
                app, wb = find_active_excel_workbook(file_path)
                if not app:
                    try:
                        app = win32com.client.Dispatch("Excel.Application")
                    except Exception:
                        pass
                if not app or app.Workbooks.Count == 0 or not wb:
                    raise RuntimeError("현재 열려 있는 활성 엑셀 통합 문서가 없습니다.")
            else:
                abs_path = os.path.abspath(file_path)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Excel.Application", "EXCEL.EXE")
                app.Visible = False
                app.DisplayAlerts = False
                wb = app.Workbooks.Open(abs_path, UpdateLinks=0, ReadOnly=True, IgnoreReadOnlyRecommended=True, Password="")
                need_quit = True

            doc_name = wb.Name

            for sheet_idx in range(1, wb.Sheets.Count + 1):
                sheet = wb.Sheets(sheet_idx)
                sheet_name = sheet.Name
                if target_pages:
                    match_page = (sheet_idx in target_pages) or any(str(p).lower() == sheet_name.lower() for p in target_pages)
                    if not match_page:
                        continue
                used = sheet.UsedRange
                if not used or used.Rows.Count == 0:
                    continue

                try:
                    values = used.Value
                except Exception:
                    values = used.Value2
                if values is None:
                    continue
                if not isinstance(values, (tuple, list)):
                    values = ((values,),)

                start_row = used.Row
                start_col = used.Column

                has_merged = False
                try:
                    has_merged = (used.MergeCells is not False)
                except Exception:
                    has_merged = True

                for r_offset, row in enumerate(values):
                    r_num = start_row + r_offset
                    row_data = []

                    cells_iter = row if isinstance(row, (tuple, list)) else [row]
                    for c_offset, raw_val in enumerate(cells_iter):
                        c_num = start_col + c_offset
                        val = raw_val

                        if has_merged and (raw_val is None or raw_val == ""):
                            try:
                                c_cell = sheet.Cells(r_num, c_num)
                                if c_cell.MergeCells:
                                    val = c_cell.MergeArea.Cells(1, 1).Value2
                            except Exception:
                                pass

                        row_data.append(sanitize_value(val))

                    if any(row_data):
                        records.append({
                            "id": item_id,
                            "src": doc_name,
                            "ext": "xlsx",
                            "page": sheet_idx,
                            "section": sheet_name,
                            "coord": f"Row:{r_num}",
                            "type": "table_row",
                            "data": row_data
                        })
                        item_id += 1

            if extract_images:
                stem = Path(doc_name).stem
                img_dir = DEFAULT_CACHE_DIR / f"{stem}_images"
                img_dir.mkdir(parents=True, exist_ok=True)
                for s_i in range(1, wb.Sheets.Count + 1):
                    sh = wb.Sheets(s_i)
                    if target_pages and s_i not in target_pages and sh.Name.lower() not in {str(p).lower() for p in target_pages}:
                        continue
                    for c_i in range(1, sh.ChartObjects().Count + 1):
                        ch_obj = sh.ChartObjects(c_i)
                        out_img = img_dir / f"chart_{s_i}_{c_i}.png"
                        try:
                            ch_obj.Chart.Export(str(out_img.resolve()), "PNG")
                            records.append({
                                "id": item_id,
                                "src": doc_name,
                                "ext": "xlsx",
                                "page": s_i,
                                "section": sh.Name,
                                "coord": f"Chart:{c_i}",
                                "type": "image",
                                "data": str(out_img.resolve())
                            })
                            item_id += 1
                        except Exception:
                            pass

        finally:
            if wb and need_quit:
                try: wb.Close(False)
                except Exception: pass
            if app and need_quit:
                try: app.Quit()
                except Exception: pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

        return records

    @staticmethod
    @com_safe()
    def parse_word(file_path: Optional[str] = None, is_active: bool = False, extract_images: bool = False, target_pages: Optional[Set[Union[int, str]]] = None) -> List[Dict[str, Any]]:
        if not win32com:
            raise RuntimeError("pywin32가 설치되지 않았습니다.")

        sync_desktop_to_default()
        records = []
        item_id = 0

        app = None
        doc = None
        need_quit = False
        guard_pid = None

        try:
            if is_active:
                app, doc = find_active_word_document(file_path)
                if not app or app.Documents.Count == 0 or not doc:
                    raise RuntimeError("현재 열려 있는 활성 워드 문서가 없습니다.")
            else:
                abs_path = os.path.abspath(file_path)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Word.Application", "WINWORD.EXE")
                app.Visible = False
                app.DisplayAlerts = 0
                doc = app.Documents.Open(abs_path, ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False, PasswordDocument="")
                need_quit = True

            doc_name = doc.Name
            current_section = "General"

            table_items = []
            for t_idx, tbl in enumerate(doc.Tables, start=1):
                t_start = tbl.Range.Start
                t_end = tbl.Range.End
                tbl_page = 1
                try:
                    tbl_page = tbl.Range.Information(3)
                except Exception:
                    pass

                row_cells = {}
                cell_widths = []
                try:
                    for cell in tbl.Range.Cells:
                        r = cell.RowIndex
                        c = cell.ColumnIndex
                        w = cell.Width
                        txt = cell.Range.Text.replace("\r", "").replace("\x07", "").strip()
                        cell_widths.append(w)
                        if r not in row_cells:
                            row_cells[r] = []
                        row_cells[r].append((c, w, txt))
                except Exception:
                    pass

                min_w = min(cell_widths) if cell_widths else 100.0
                max_c = 1
                for r, cells in row_cells.items():
                    total_span = sum(max(1, round(w / min_w)) for _, w, _ in cells)
                    max_c = max(max_c, total_span)

                rows_2d = []
                for r in sorted(row_cells.keys()):
                    row_arr = [""] * max_c
                    curr_c = 0
                    covered_cols = set()
                    for col_idx, w, txt in row_cells[r]:
                        span = max(1, round(w / min_w))
                        target_col = max(curr_c, col_idx - 1)
                        for s in range(span):
                            idx = target_col + s
                            if idx < max_c:
                                row_arr[idx] = txt
                                covered_cols.add(idx)
                        curr_c = target_col + span

                    if rows_2d:
                        for c in range(max_c):
                            if c not in covered_cols and len(rows_2d[-1]) > c:
                                row_arr[c] = rows_2d[-1][c]
                    rows_2d.append(row_arr)

                table_items.append({
                    "start": t_start,
                    "end": t_end,
                    "tbl_idx": t_idx,
                    "page": tbl_page,
                    "rows": rows_2d
                })

            table_ptr = 0
            num_tables = len(table_items)

            for p in doc.Paragraphs:
                p_range = p.Range
                p_start = p_range.Start

                try:
                    if p_range.Information(12):
                        continue
                except Exception:
                    pass

                while table_ptr < num_tables and table_items[table_ptr]["start"] <= p_start:
                    t_info = table_items[table_ptr]
                    t_page = t_info.get("page", 1)
                    if not target_pages or t_page in target_pages:
                        for r_i, r_data in enumerate(t_info["rows"], start=1):
                            records.append({
                                "id": item_id,
                                "src": doc_name,
                                "ext": "docx",
                                "page": t_page,
                                "section": current_section,
                                "coord": f"Tbl:{t_info['tbl_idx']}/Row:{r_i}",
                                "type": "table_row",
                                "data": r_data
                            })
                            item_id += 1
                    table_ptr += 1

                p_text = p_range.Text.replace("\r", "").replace("\x07", "").strip()
                if not p_text:
                    continue

                page_num = 1
                try:
                    page_num = p_range.Information(3)
                except Exception:
                    pass

                if target_pages and page_num not in target_pages:
                    continue

                style_name = ""
                try:
                    style_name = str(p.Style)
                except Exception:
                    pass

                if "heading" in style_name.lower() or "제목" in style_name:
                    current_section = p_text
                    doc_type = "heading"
                else:
                    doc_type = "text"

                records.append({
                    "id": item_id,
                    "src": doc_name,
                    "ext": "docx",
                    "page": page_num,
                    "section": current_section,
                    "coord": f"Para:{item_id}",
                    "type": doc_type,
                    "data": p_text
                })
                item_id += 1

            while table_ptr < num_tables:
                t_info = table_items[table_ptr]
                t_page = t_info.get("page", 1)
                if not target_pages or t_page in target_pages:
                    for r_i, r_data in enumerate(t_info["rows"], start=1):
                        records.append({
                            "id": item_id,
                            "src": doc_name,
                            "ext": "docx",
                            "page": t_page,
                            "section": current_section,
                            "coord": f"Tbl:{t_info['tbl_idx']}/Row:{r_i}",
                            "type": "table_row",
                            "data": r_data
                        })
                        item_id += 1
                table_ptr += 1

        finally:
            if doc and need_quit:
                try: doc.Close(False)
                except Exception: pass
            if app and need_quit:
                try: app.Quit()
                except Exception: pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

        return records

    @staticmethod
    @com_safe()
    def parse_ppt(file_path: Optional[str] = None, is_active: bool = False, target_pages: Optional[Set[Union[int, str]]] = None) -> List[Dict[str, Any]]:
        if not win32com:
            raise RuntimeError("pywin32가 설치되지 않았습니다.")

        sync_desktop_to_default()
        records = []
        item_id = 0

        app = None
        prs = None
        need_quit = False
        guard_pid = None

        try:
            if is_active:
                app, prs = find_active_ppt_presentation(file_path)
                if not app or app.Presentations.Count == 0 or not prs:
                    raise RuntimeError("현재 열려 있는 활성 PPT 프레젠테이션이 없습니다.")
            else:
                abs_path = os.path.abspath(file_path)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("PowerPoint.Application", "POWERPNT.EXE")
                prs = app.Presentations.Open(abs_path, ReadOnly=True, Untitled=False, WithWindow=False)
                need_quit = True

            doc_name = prs.Name

            def unpack_shapes(shapes_col) -> Generator[Any, None, None]:
                for shape in shapes_col:
                    try:
                        if shape.Type == 6:
                            yield from unpack_shapes(shape.GroupItems)
                        else:
                            yield shape
                    except Exception:
                        pass

            for s_idx in range(1, prs.Slides.Count + 1):
                if target_pages and s_idx not in target_pages:
                    continue

                slide = prs.Slides(s_idx)
                slide_title = f"Slide {s_idx}"
                try:
                    if slide.Shapes.HasTitle:
                        title_txt = slide.Shapes.Title.TextFrame.TextRange.Text.strip()
                        if title_txt:
                            slide_title = title_txt
                except Exception:
                    pass

                shape_elements = []
                for shape in unpack_shapes(slide.Shapes):
                    try:
                        top = float(shape.Top)
                        left = float(shape.Left)

                        if shape.HasTable:
                            tbl = shape.Table
                            rows_data = []
                            for r in range(1, tbl.Rows.Count + 1):
                                row_vals = []
                                for c in range(1, tbl.Columns.Count + 1):
                                    c_txt = tbl.Cell(r, c).Shape.TextFrame.TextRange.Text.strip()
                                    row_vals.append(c_txt)
                                rows_data.append(row_vals)
                            shape_elements.append({
                                "top": top,
                                "left": left,
                                "type": "table",
                                "data": rows_data
                            })

                        elif shape.HasTextFrame:
                            if shape.TextFrame.HasText:
                                txt = shape.TextFrame.TextRange.Text.strip()
                                if txt:
                                    shape_elements.append({
                                        "top": top,
                                        "left": left,
                                        "type": "text",
                                        "data": txt
                                    })
                    except Exception:
                        pass

                shape_elements.sort(key=lambda s: (round(s["top"], -1), s["left"]))

                for elem in shape_elements:
                    if elem["type"] == "table":
                        for r_idx, r_data in enumerate(elem["data"], start=1):
                            records.append({
                                "id": item_id,
                                "src": doc_name,
                                "ext": "pptx",
                                "page": s_idx,
                                "section": slide_title,
                                "coord": f"Tbl/Row:{r_idx}",
                                "type": "table_row",
                                "data": r_data
                            })
                            item_id += 1
                    else:
                        records.append({
                            "id": item_id,
                            "src": doc_name,
                            "ext": "pptx",
                            "page": s_idx,
                            "section": slide_title,
                            "coord": f"Shape:{item_id}",
                            "type": "text",
                            "data": elem["data"]
                        })
                        item_id += 1

        finally:
            if prs and need_quit:
                try: prs.Close()
                except Exception: pass
            if app and need_quit:
                try: app.Quit()
                except Exception: pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

        return records

    @staticmethod
    def parse_hwp(file_path: Optional[str] = None, is_active: bool = False) -> List[Dict[str, Any]]:
        if not file_path or is_active:
            raise ValueError("한글(HWP)은 로컬 파일 읽기 전용으로 지원됩니다. 파일 경로를 지정해 주세요 (--from <경로.hwp>).")

        abs_path = os.path.abspath(file_path)
        doc_name = os.path.basename(file_path)
        ext = abs_path.split(".")[-1].lower()
        records = []
        item_id = 0

        if ext == "hwpx":
            try:
                with zipfile.ZipFile(abs_path, "r") as zf:
                    section_names = sorted([n for n in zf.namelist() if n.startswith("Contents/section") and n.endswith(".xml")])
                    current_section = "General"
                    for s_name in section_names:
                        xml_bytes = zf.read(s_name)
                        root = ET.fromstring(xml_bytes)

                        tbl_p_ids = set()
                        for tbl in root.iter():
                            if tbl.tag.split("}")[-1] == "tbl":
                                for p in tbl.iter():
                                    if p.tag.split("}")[-1] == "p":
                                        tbl_p_ids.add(id(p))

                        for elem in root.iter():
                            tag = elem.tag.split("}")[-1]
                            if tag == "tbl":
                                for tr in elem.iter():
                                    if tr.tag.split("}")[-1] == "tr":
                                        row_cells = []
                                        for tc in tr:
                                            if tc.tag.split("}")[-1] == "tc":
                                                tc_text = "".join(t.text for t in tc.iter() if t.tag.split("}")[-1] == "t" and t.text).strip()
                                                row_cells.append(tc_text)
                                        if any(row_cells):
                                            records.append({
                                                "id": item_id,
                                                "src": doc_name,
                                                "ext": "hwpx",
                                                "page": 1,
                                                "section": current_section,
                                                "coord": f"Tbl:{item_id}",
                                                "type": "table_row",
                                                "data": row_cells
                                            })
                                            item_id += 1
                            elif tag == "p":
                                if id(elem) in tbl_p_ids:
                                    continue
                                p_texts = [t.text for t in elem.iter() if t.tag.split("}")[-1] == "t" and t.text]
                                raw_text = "".join(p_texts).strip()
                                if raw_text:
                                    if raw_text.startswith(("[", "<", "1.", "2.", "3.", "제", "#", "□")) and len(raw_text) < 40:
                                        current_section = raw_text
                                        doc_type = "heading"
                                    else:
                                        doc_type = "text"
                                    records.append({
                                        "id": item_id,
                                        "src": doc_name,
                                        "ext": "hwpx",
                                        "page": 1,
                                        "section": current_section,
                                        "coord": f"Para:{item_id}",
                                        "type": doc_type,
                                        "data": raw_text
                                    })
                                    item_id += 1
                if records:
                    return records
            except Exception:
                pass

        if ext == "hwp" and olefile and olefile.isOleFile(abs_path):
            try:
                ole = olefile.OleFileIO(abs_path)
                dirs = ole.listdir()
                sections = [d for d in dirs if d[0] == "BodyText" and d[1].startswith("Section")]
                current_section = "General"

                for s in sections:
                    stream_data = ole.openstream("/".join(s)).read()
                    try:
                        decomp = zlib.decompress(stream_data, -15)
                    except Exception:
                        decomp = stream_data

                    pos = 0
                    total_len = len(decomp)
                    in_table = False
                    tbl_rows, tbl_cols = 0, 0
                    tbl_grid: Dict[Tuple[int, int], List[str]] = {}
                    tbl_spans: Dict[Tuple[int, int], Tuple[int, int]] = {}
                    cur_cell: Optional[Tuple[int, int]] = None

                    def flush_current_table():
                        nonlocal in_table, tbl_rows, tbl_cols, tbl_grid, tbl_spans, cur_cell, item_id
                        if not in_table or tbl_rows <= 0 or tbl_cols <= 0:
                            in_table = False
                            tbl_rows, tbl_cols = 0, 0
                            tbl_grid = {}
                            tbl_spans = {}
                            cur_cell = None
                            return

                        full_grid: Dict[Tuple[int, int], str] = {}
                        for (r, c), lines in tbl_grid.items():
                            val = " ".join(lines).strip()
                            colspan, rowspan = tbl_spans.get((r, c), (1, 1))
                            for dr in range(rowspan):
                                for dc in range(colspan):
                                    full_grid[(r + dr, c + dc)] = val

                        for r in range(tbl_rows):
                            row_vals = [full_grid.get((r, c), "") for c in range(tbl_cols)]
                            if any(row_vals):
                                records.append({
                                    "id": item_id,
                                    "src": doc_name,
                                    "ext": "hwp",
                                    "page": 1,
                                    "section": current_section,
                                    "coord": f"TblRow:{item_id}",
                                    "type": "table_row",
                                    "data": row_vals
                                })
                                item_id += 1

                        in_table = False
                        tbl_rows, tbl_cols = 0, 0
                        tbl_grid = {}
                        tbl_spans = {}
                        cur_cell = None

                    while pos + 4 <= total_len:
                        header = struct.unpack("<I", decomp[pos:pos+4])[0]
                        tag_id = header & 0x3FF
                        level = (header >> 10) & 0x3FF
                        size = (header >> 20) & 0xFFF
                        pos += 4

                        if size == 0xFFF and pos + 4 <= total_len:
                            size = struct.unpack("<I", decomp[pos:pos+4])[0]
                            pos += 4

                        if pos + size > total_len:
                            break

                        record_bytes = decomp[pos:pos+size]
                        pos += size

                        if level == 0 and tag_id == 66:
                            flush_current_table()

                        if tag_id == 77 and len(record_bytes) >= 8:
                            flush_current_table()
                            try:
                                n_rows, n_cols = struct.unpack_from("<HH", record_bytes, 4)
                                if 1 <= n_rows <= 1000 and 1 <= n_cols <= 100:
                                    in_table = True
                                    tbl_rows = n_rows
                                    tbl_cols = n_cols
                                    tbl_grid = {}
                                    tbl_spans = {}
                                    cur_cell = None
                            except Exception:
                                pass
                            continue

                        if in_table and tag_id == 72 and len(record_bytes) >= 16:
                            col, row, colspan, rowspan = struct.unpack_from("<HHHH", record_bytes, 8)
                            if row < tbl_rows and col < tbl_cols:
                                cur_cell = (row, col)
                                if cur_cell not in tbl_grid:
                                    tbl_grid[cur_cell] = []
                                tbl_spans[cur_cell] = (max(1, colspan), max(1, rowspan))
                            continue

                        if tag_id == 67:
                            cleaned = []
                            b_idx = 0
                            b_len = len(record_bytes)

                            while b_idx + 2 <= b_len:
                                code = struct.unpack_from("<H", record_bytes, b_idx)[0]
                                b_idx += 2
                                if code in (1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23):
                                    b_idx += 14
                                    continue
                                if code in (9, 10, 13) or code >= 32:
                                    cleaned.append(chr(code))

                            line_text = "".join(cleaned).strip()

                            if in_table and cur_cell is not None:
                                if line_text:
                                    tbl_grid[cur_cell].append(line_text)
                                continue

                            for line in line_text.splitlines():
                                l_str = line.strip()
                                if not l_str or not re.search(r"[가-힣a-zA-Z0-9]", l_str):
                                    continue

                                if "\t" in l_str:
                                    cells = [c.strip() for c in l_str.split("\t") if c.strip()]
                                    records.append({
                                        "id": item_id,
                                        "src": doc_name,
                                        "ext": "hwp",
                                        "page": 1,
                                        "section": current_section,
                                        "coord": f"Para:{item_id}",
                                        "type": "table_row",
                                        "data": cells
                                    })
                                else:
                                    if l_str.startswith(("[", "<", "1.", "2.", "3.", "제", "#", "□")) and len(l_str) < 40:
                                        current_section = l_str
                                        doc_type = "heading"
                                    else:
                                        doc_type = "text"
                                    records.append({
                                        "id": item_id,
                                        "src": doc_name,
                                        "ext": "hwp",
                                        "page": 1,
                                        "section": current_section,
                                        "coord": f"Para:{item_id}",
                                        "type": doc_type,
                                        "data": l_str
                                    })
                                item_id += 1

                    flush_current_table()

                ole.close()
                if records:
                    return records
            except Exception:
                pass

        if not records:
            raise RuntimeError(f"한글 문서({doc_name})를 파싱할 수 없거나 내용이 비어 있습니다.")

        return records

    @staticmethod
    def parse_csv(file_path: str) -> List[Dict[str, Any]]:
        abs_path = os.path.abspath(file_path)
        doc_name = os.path.basename(abs_path)

        raw_text = None
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                with open(abs_path, "r", encoding=enc) as f:
                    raw_text = f.read()
                break
            except UnicodeDecodeError:
                continue

        if raw_text is None:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                raw_text = f.read()

        records = []
        item_id = 0
        reader = csv.reader(raw_text.splitlines())

        for row_idx, row in enumerate(reader, start=1):
            cleaned_row = [c.strip() for c in row]
            if any(cleaned_row):
                records.append({
                    "id": item_id,
                    "src": doc_name,
                    "ext": "csv",
                    "page": 1,
                    "section": "CSV",
                    "coord": f"Row:{row_idx}",
                    "type": "table_row",
                    "data": cleaned_row
                })
                item_id += 1

        return records

    @staticmethod
    def parse_md_txt(file_path: str) -> List[Dict[str, Any]]:
        abs_path = os.path.abspath(file_path)
        ext = abs_path.split(".")[-1].lower()

        raw_lines = None
        for enc in ("utf-8-sig", "cp949"):
            try:
                with open(abs_path, "r", encoding=enc) as f:
                    raw_lines = f.readlines()
                break
            except UnicodeDecodeError:
                continue

        if raw_lines is None:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                raw_lines = f.readlines()

        records = []
        item_id = 0
        current_section = ""

        for line_idx, line in enumerate(raw_lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("![") and "](" in stripped:
                continue

            if stripped.startswith("|") and stripped.endswith("|"):
                if re.match(r"^\|[\s\-:|]+\|$", stripped):
                    continue
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                records.append({
                    "id": item_id,
                    "src": os.path.basename(abs_path),
                    "ext": ext,
                    "page": 1,
                    "section": current_section,
                    "coord": f"Line:{line_idx}",
                    "type": "table_row",
                    "data": cells
                })
                item_id += 1
                continue

            if stripped.startswith("#"):
                current_section = stripped.lstrip("#").strip()
                doc_type = "heading"
            else:
                doc_type = "text"

            records.append({
                "id": item_id,
                "src": os.path.basename(abs_path),
                "ext": ext,
                "page": 1,
                "section": current_section,
                "coord": f"Line:{line_idx}",
                "type": doc_type,
                "data": stripped
            })
            item_id += 1

        return records


# ==============================================================================
# 8. 스마트 오피스 쓰기 엔진 (OfficeWriter)
# ==============================================================================
class OfficeWriter:
    @staticmethod
    def write_to_target(
        target: str,
        is_active: bool,
        records: List[Dict[str, Any]],
        anchor: Optional[str] = None,
        pos: str = "after",
        clear: bool = False,
        auto_backup: bool = True,
        chart: Optional[str] = None,
        chart_title: Optional[str] = None,
        pages: Optional[str] = None,
        replace_map: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if auto_backup:
            try:
                bm = BackupManager()
                bm.backup_target(target, is_active)
            except Exception:
                pass

        ext = resolve_target_ext(target)

        res = None
        if ext in ["hwp", "hwpx"]:
            raise NotImplementedError("한글(HWP) 문서는 읽기 전용으로만 지원됩니다.")
        elif ext in ["docx", "doc", "word"]:
            res = OfficeWriter._write_word(target, is_active, records, anchor, pos, clear=clear, replace_map=replace_map)
        elif ext in ["xlsx", "xls", "xlsm", "excel"] or (is_active and (target.lower().startswith("book") or "sheet" in target.lower())):
            res = OfficeWriter._write_excel(target, is_active, records, anchor, pos, clear=clear, chart=chart, chart_title=chart_title, pages=pages, replace_map=replace_map)
        elif ext in ["pptx", "ppt", "powerpoint"]:
            res = OfficeWriter._write_ppt(target, is_active, records, anchor, pos, clear=clear, pages=pages, replace_map=replace_map)
        elif ext in ["md", "txt"]:
            res = OfficeWriter._write_md_txt(target, records, anchor, pos, clear=clear, replace_map=replace_map)
        else:
            if is_active:
                try:
                    _, d = find_active_word_document(target)
                    if d:
                        res = OfficeWriter._write_word(target, is_active, records, anchor, pos, clear=clear, replace_map=replace_map)
                except Exception:
                    pass
                if not res:
                    try:
                        _, p = find_active_ppt_presentation(target)
                        if p:
                            res = OfficeWriter._write_ppt(target, is_active, records, anchor, pos, clear=clear, pages=pages, replace_map=replace_map)
                    except Exception:
                        pass
                if not res:
                    try:
                        res = OfficeWriter._write_excel(target, is_active, records, anchor, pos, clear=clear, chart=chart, chart_title=chart_title, pages=pages, replace_map=replace_map)
                    except Exception:
                        pass
            if not res:
                raise NotImplementedError(f"지원하지 않거나 감지되지 않는 오피스 대상입니다: {target}")

        if chart and ext not in ["xlsx", "xls", "xlsm", "excel"]:
            if isinstance(res, dict):
                res["warning"] = f"차트(--chart {chart}) 생성은 Excel 대상에서만 지원되므로 무시되었습니다."

        return res

    @staticmethod
    @com_safe()
    def _write_word(target: str, is_active: bool, records: List[Dict[str, Any]], anchor: Optional[str], pos: str, clear: bool = False, replace_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        sync_desktop_to_default()
        app = None
        doc = None
        guard_pid = None
        is_new_doc = False
        try:
            if is_active:
                app, doc = find_active_word_document(target)
                if not app:
                    try:
                        app = win32com.client.Dispatch("Word.Application")
                    except Exception:
                        pass
                try:
                    app.Visible = True
                except Exception:
                    pass
                if not doc:
                    doc = app.ActiveDocument if (app and app.Documents.Count > 0) else (app.Documents.Add() if app else None)
                try:
                    ensure_window_visible(app.ActiveWindow.Hwnd)
                except Exception:
                    pass
            else:
                abs_target = os.path.abspath(target)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Word.Application", "WINWORD.EXE")
                app.Visible = False
                app.DisplayAlerts = 0
                if os.path.exists(abs_target):
                    doc = app.Documents.Open(abs_target, ConfirmConversions=False, ReadOnly=False, AddToRecentFiles=False, PasswordDocument="")
                    is_new_doc = False
                else:
                    doc = app.Documents.Add()
                    is_new_doc = True

            if replace_map and doc:
                sorted_map = dict(sorted(replace_map.items(), key=lambda item: len(str(item[0])), reverse=True))
                total_replacements = 0
                for old_s, spec_raw in sorted_map.items():
                    if not old_s:
                        continue
                    spec = normalize_replace_item(spec_raw)
                    new_s = spec.get("text")
                    color = spec.get("color")
                    bold = spec.get("bold")
                    italic = spec.get("italic")
                    bg = spec.get("bg")

                    try:
                        rng = doc.Content.Duplicate
                        f_obj = rng.Find
                        f_obj.ClearFormatting()
                        safety_counter = 0
                        while safety_counter < 5000 and f_obj.Execute(FindText=old_s, MatchCase=False, MatchWholeWord=False, MatchWildcards=False, Forward=True, Wrap=0):
                            safety_counter += 1
                            if new_s is not None and str(new_s) != old_s:
                                rng.Text = str(new_s)
                            if color is not None:
                                rng.Font.Color = color
                            if bold is not None:
                                rng.Font.Bold = -1 if bold else 0
                            if italic is not None:
                                rng.Font.Italic = -1 if italic else 0
                            if bg is not None:
                                try:
                                    rng.Shading.BackgroundPatternColor = bg
                                except Exception:
                                    pass
                            total_replacements += 1
                            next_start = rng.End
                            doc_end = doc.Content.End
                            if next_start >= doc_end:
                                break
                            rng.SetRange(next_start, doc_end)
                            f_obj = rng.Find
                            f_obj.ClearFormatting()
                    except Exception:
                        pass

                def _replace_in_word_shape(sh) -> int:
                    s_count = 0
                    try:
                        if getattr(sh, "Type", None) == 6:
                            for sub in sh.GroupItems:
                                s_count += _replace_in_word_shape(sub)
                            return s_count
                    except Exception:
                        pass
                    try:
                        if getattr(sh, "TextFrame", None) and sh.TextFrame.HasText:
                            tr = sh.TextFrame.TextRange
                            for old_s, spec_raw in sorted_map.items():
                                if not old_s or old_s not in tr.Text:
                                    continue
                                spec = normalize_replace_item(spec_raw)
                                new_s = spec.get("text")
                                color = spec.get("color")
                                bold = spec.get("bold")
                                italic = spec.get("italic")
                                bg = spec.get("bg")

                                try:
                                    sh_rng = tr.Duplicate
                                    f_sh = sh_rng.Find
                                    f_sh.ClearFormatting()
                                    safety_c = 0
                                    while safety_c < 1000 and f_sh.Execute(FindText=old_s, MatchCase=False, MatchWholeWord=False, MatchWildcards=False, Forward=True, Wrap=0):
                                        safety_c += 1
                                        if new_s is not None and str(new_s) != old_s:
                                            sh_rng.Text = str(new_s)
                                        if color is not None:
                                            sh_rng.Font.Color = color
                                        if bold is not None:
                                            sh_rng.Font.Bold = -1 if bold else 0
                                        if italic is not None:
                                            sh_rng.Font.Italic = -1 if italic else 0
                                        if bg is not None:
                                            try:
                                                sh_rng.Shading.BackgroundPatternColor = bg
                                            except Exception:
                                                pass
                                        s_count += 1
                                        next_pos = sh_rng.End
                                        end_pos = tr.End
                                        if next_pos >= end_pos:
                                            break
                                        sh_rng.SetRange(next_pos, end_pos)
                                        f_sh = sh_rng.Find
                                        f_sh.ClearFormatting()
                                except Exception:
                                    if new_s is not None and str(new_s) != old_s:
                                        tr.Text = tr.Text.replace(old_s, str(new_s))
                                        s_count += 1
                    except Exception:
                        pass
                    return s_count

                try:
                    for sh in doc.Shapes:
                        total_replacements += _replace_in_word_shape(sh)
                except Exception:
                    pass

                if not is_active:
                    doc.SaveAs(abs_target) if is_new_doc else doc.Save()

                if total_replacements == 0:
                    return {
                        "status": "no_match",
                        "action": "replaced",
                        "target": target,
                        "replacements": 0,
                        "agent_directive": STOP_RETRY_DIRECTIVE
                    }

                return {
                    "status": "ok",
                    "action": "replaced",
                    "target": target,
                    "replacements": total_replacements,
                    "keys_count": len(sorted_map),
                    "agent_directive": VERIFIED_DIRECTIVE
                }

            if clear and doc:
                doc.Content.Delete()
                if not records:
                    if not is_active:
                        doc.SaveAs(abs_target) if is_new_doc else doc.Save()
                    return {"status": "ok", "action": "cleared", "target": target, "count": 0, "agent_directive": VERIFIED_DIRECTIVE}

            inherited_font_name = None
            inherited_font_size = None
            inherited_table_style = None

            try:
                if doc.Tables.Count > 0:
                    inherited_table_style = doc.Tables(doc.Tables.Count).Style
            except Exception:
                pass

            sel = app.Selection
            if anchor:
                sel.HomeKey(6)
                found = sel.Find.Execute(anchor)
                if not found:
                    stripped_anchor = anchor.strip()
                    if stripped_anchor and stripped_anchor != anchor:
                        sel.HomeKey(6)
                        found = sel.Find.Execute(stripped_anchor)
                    if not found and len(stripped_anchor) > 2:
                        no_spaces = stripped_anchor.replace(" ", "")
                        sel.HomeKey(6)
                        found = sel.Find.Execute(no_spaces)
                if found:
                    try:
                        inherited_font_name = sel.Font.Name
                        inherited_font_size = sel.Font.Size
                    except Exception:
                        pass

                    if pos == "before":
                        try:
                            p_start = sel.Paragraphs(1).Range.Start
                            sel.SetRange(p_start, p_start)
                        except Exception:
                            sel.Collapse(1)
                    elif pos == "after":
                        try:
                            p_end = sel.Paragraphs(1).Range.End
                            sel.SetRange(p_end, p_end)
                        except Exception:
                            sel.Collapse(0)
                            sel.InsertParagraphAfter()
                            sel.Collapse(0)
                    elif pos == "replace":
                        try:
                            sel.Delete()
                        except Exception:
                            pass
                else:
                    sel.EndKey(6)
                    sel.InsertParagraphAfter()
                    sel.Collapse(0)
            else:
                sel.EndKey(6)
                if doc.Content.End > 1:
                    sel.InsertParagraphAfter()
                    sel.Collapse(0)

            grouped = []
            curr_table = []
            for rec in records:
                if rec.get("type") == "table_row" and isinstance(rec.get("data"), list):
                    curr_table.append(rec)
                else:
                    if curr_table:
                        grouped.append(("table", curr_table))
                        curr_table = []
                    grouped.append(("item", rec))
            if curr_table:
                grouped.append(("table", curr_table))

            written_items = 0
            for g_type, g_val in grouped:
                if g_type == "table":
                    t_rows = g_val
                    num_rows = len(t_rows)
                    max_cols = max(len(r.get("data", [])) for r in t_rows)
                    if num_rows > 0 and max_cols > 0:
                        try:
                            tbl = doc.Tables.Add(sel.Range, num_rows, max_cols)
                            applied_style = False
                            if inherited_table_style:
                                try:
                                    tbl.Style = inherited_table_style
                                    applied_style = True
                                except Exception:
                                    pass
                            try:
                                tbl.Borders.Enable = True
                                tbl.Borders.OutsideLineStyle = 1
                                tbl.Borders.InsideLineStyle = 1
                            except Exception:
                                pass
                            try:
                                tbl.AutoFitBehavior(1)
                            except Exception:
                                pass
                            if not applied_style and num_rows >= 1:
                                try:
                                    tbl.Rows(1).Range.Bold = True
                                    tbl.Rows(1).Range.Shading.BackgroundPatternColor = 15987699
                                except Exception:
                                    pass
                            for r_idx, r_rec in enumerate(t_rows, start=1):
                                r_data = r_rec.get("data", [])
                                for c_idx, val in enumerate(r_data, start=1):
                                    if c_idx <= max_cols:
                                        val_str = str(val) if val is not None else ""
                                        val_str = re.sub(r"<br\s*/?>", "\r", val_str, flags=re.I)
                                        val_str = re.sub(r"\*\*([^*]+)\*\*", r"\1", val_str)
                                        val_str = re.sub(r"</?[a-zA-Z0-9]+[^>]*>", "", val_str)
                                        tbl.Cell(r_idx, c_idx).Range.Text = val_str
                            sel.Start = tbl.Range.End
                            sel.Collapse(0)
                            sel.InsertParagraphAfter()
                            sel.Collapse(0)
                        except Exception:
                            for r_rec in t_rows:
                                sel.TypeText(" | ".join(str(c) for c in r_rec.get("data", [])) + "\n")
                    written_items += num_rows
                else:
                    rec = g_val
                    if rec.get("type") == "image":
                        img_path = os.path.abspath(str(rec.get("data", "")))
                        if os.path.exists(img_path):
                            pic = doc.InlineShapes.AddPicture(FileName=img_path, Range=sel.Range)
                            sel.Start = pic.Range.End
                            sel.Collapse(0)
                            sel.InsertParagraphAfter()
                            sel.Collapse(0)
                            written_items += 1
                    else:
                        data = rec.get("data", "")
                        text_val = " ".join(str(c) for c in data) if isinstance(data, list) else str(data)
                        if inherited_font_name:
                            try:
                                sel.Font.Name = inherited_font_name
                                if inherited_font_size:
                                    sel.Font.Size = inherited_font_size
                            except Exception:
                                pass
                        if anchor and pos == "replace" and len(grouped) == 1:
                            sel.TypeText(text_val)
                        else:
                            sel.TypeText(text_val + "\n")
                        written_items += 1

            if not is_active:
                doc.SaveAs(abs_target) if is_new_doc else doc.Save()

            return {"status": "ok", "action": "written", "target": target, "count": written_items, "agent_directive": VERIFIED_DIRECTIVE}

        finally:
            if not is_active:
                if doc:
                    try: doc.Close(False)
                    except Exception: pass
                if app:
                    try: app.Quit()
                    except Exception: pass
                if guard_pid:
                    ComProcessGuard.unregister(guard_pid)

    @staticmethod
    @com_safe()
    def _write_excel(target: str, is_active: bool, records: List[Dict[str, Any]], anchor: Optional[str], pos: str, clear: bool = False, chart: Optional[str] = None, chart_title: Optional[str] = None, pages: Optional[str] = None, replace_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        sync_desktop_to_default()
        app = None
        wb = None
        guard_pid = None
        is_new_wb = False
        try:
            if is_active:
                app, wb = find_active_excel_workbook(target)
                if not app:
                    try:
                        app = win32com.client.Dispatch("Excel.Application")
                    except Exception:
                        pass
                try:
                    app.Visible = True
                except Exception:
                    pass
                if not wb:
                    wb = app.ActiveWorkbook if app.Workbooks.Count > 0 else app.Workbooks.Add()
                try:
                    ensure_window_visible(app.Hwnd)
                except Exception:
                    pass
            else:
                abs_target = os.path.abspath(target)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Excel.Application", "EXCEL.EXE")
                app.Visible = False
                app.DisplayAlerts = False
                if os.path.exists(abs_target):
                    wb = app.Workbooks.Open(abs_target, UpdateLinks=0, ReadOnly=False, IgnoreReadOnlyRecommended=True, Password="")
                    is_new_wb = False
                else:
                    wb = app.Workbooks.Add()
                    is_new_wb = True

            sheet = wb.ActiveSheet
            target_sheet = None
            if pages and wb:
                p_str = pages.strip()
                for ws in wb.Worksheets:
                    if ws.Name.lower() == p_str.lower():
                        target_sheet = ws
                        break
                if not target_sheet and p_str.isdigit():
                    s_idx = int(p_str)
                    if 1 <= s_idx <= wb.Worksheets.Count:
                        target_sheet = wb.Worksheets(s_idx)
                if not target_sheet:
                    try:
                        target_sheet = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
                        if not p_str.isdigit():
                            target_sheet.Name = p_str
                    except Exception:
                        target_sheet = wb.ActiveSheet
                if target_sheet:
                    sheet = target_sheet
                    try:
                        sheet.Activate()
                    except Exception:
                        pass

            if replace_map and wb:
                sorted_map = dict(sorted(replace_map.items(), key=lambda item: len(str(item[0])), reverse=True))
                total_replacements = 0
                sheets_to_process = [sheet] if target_sheet else [wb.Worksheets(i) for i in range(1, wb.Worksheets.Count + 1)]

                def _replace_in_excel_shape(sh) -> int:
                    sub_count = 0
                    try:
                        sh_type = getattr(sh, "Type", None)
                        if sh_type == 6:
                            for sub in sh.GroupItems:
                                sub_count += _replace_in_excel_shape(sub)
                            return sub_count
                        if sh_type not in (1, 14, 17):
                            return 0
                    except Exception:
                        return 0

                    try:
                        if getattr(sh, "TextFrame2", None) and getattr(sh.TextFrame2, "HasText", False):
                            tr = sh.TextFrame2.TextRange
                            for old_s, spec_raw in sorted_map.items():
                                if not old_s:
                                    continue
                                spec = normalize_replace_item(spec_raw)
                                new_s = spec.get("text")
                                color = spec.get("color")
                                bold = spec.get("bold")
                                italic = spec.get("italic")

                                target_txt = old_s
                                if new_s is not None and old_s in tr.Text:
                                    tr.Text = tr.Text.replace(old_s, str(new_s))
                                    target_txt = str(new_s)
                                    sub_count += 1
                                if (color is not None or bold is not None or italic is not None) and target_txt in tr.Text:
                                    try:
                                        full_t = tr.Text
                                        s_idx = 0
                                        while True:
                                            idx = full_t.lower().find(target_txt.lower(), s_idx)
                                            if idx == -1:
                                                break
                                            try:
                                                sub_tr = tr.Characters(idx + 1, len(target_txt))
                                                if color is not None: sub_tr.Font.Fill.ForeColor.RGB = color
                                                if bold is not None: sub_tr.Font.Bold = -1 if bold else 0
                                                if italic is not None: sub_tr.Font.Italic = -1 if italic else 0
                                            except Exception:
                                                if color is not None: tr.Font.Fill.ForeColor.RGB = color
                                                if bold is not None: tr.Font.Bold = -1 if bold else 0
                                                if italic is not None: tr.Font.Italic = -1 if italic else 0
                                            sub_count += 1
                                            s_idx = idx + len(target_txt)
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                    return sub_count

                for ws in sheets_to_process:
                    try:
                        used = ws.UsedRange
                        if used:
                            r_start, c_start = used.Row, used.Column
                            vals = used.Value2
                            formulas = None
                            try:
                                formulas = used.Formula
                            except Exception:
                                pass
                            if vals is not None:
                                if not isinstance(vals, (tuple, list)):
                                    vals = ((vals,),)
                                    formulas = ((formulas,),) if formulas is not None else None
                                for r_idx, row in enumerate(vals):
                                    row_iter = row if isinstance(row, (tuple, list)) else [row]
                                    f_row_iter = (formulas[r_idx] if isinstance(formulas[r_idx], (tuple, list)) else [formulas[r_idx]]) if formulas else None
                                    for c_idx, cell_val in enumerate(row_iter):
                                        val_str = str(sanitize_value(cell_val))
                                        if not val_str:
                                            continue
                                        cell_formula = str(f_row_iter[c_idx]) if (f_row_iter and c_idx < len(f_row_iter) and f_row_iter[c_idx] is not None) else ""
                                        is_formula_cell = cell_formula.startswith("=")

                                        for old_s, spec_raw in sorted_map.items():
                                            target_txt = str(old_s)
                                            if not target_txt:
                                                continue
                                            spec = normalize_replace_item(spec_raw)
                                            new_s = spec.get("text")
                                            color = spec.get("color")
                                            bold = spec.get("bold")
                                            italic = spec.get("italic")
                                            bg = spec.get("bg")

                                            # 숫자이거나 1글자 단어(예: 요일 '일', '월')는 정확 일치 우선 매칭하여 오탐 방지
                                            if target_txt.isdigit() or len(target_txt) == 1:
                                                is_match = (val_str.strip().lower() == target_txt.lower())
                                            else:
                                                is_match = (target_txt.lower() in val_str.lower())

                                            if is_match:
                                                c_obj = ws.Cells(r_start + r_idx, c_start + c_idx)
                                                try:
                                                    if new_s is not None and str(new_s) != target_txt and not is_formula_cell:
                                                        if val_str.strip().lower() == target_txt.lower():
                                                            c_obj.Value = cast_excel_value(new_s)
                                                            val_str = str(new_s)
                                                        else:
                                                            pattern = re.compile(re.escape(target_txt), re.IGNORECASE)
                                                            updated_str = pattern.sub(str(new_s), val_str)
                                                            c_obj.Value = cast_excel_value(updated_str)
                                                            val_str = updated_str
                                                    if color is not None: c_obj.Font.Color = color
                                                    if bold is not None: c_obj.Font.Bold = bool(bold)
                                                    if italic is not None: c_obj.Font.Italic = bool(italic)
                                                    if bg is not None: c_obj.Interior.Color = bg
                                                    total_replacements += 1
                                                except Exception:
                                                    pass
                    except Exception:
                        pass

                    try:
                        for sh in ws.Shapes:
                            total_replacements += _replace_in_excel_shape(sh)
                    except Exception:
                        pass

                if not is_active:
                    wb.SaveAs(abs_target) if is_new_wb else wb.Save()

                if total_replacements == 0:
                    return {
                        "status": "no_match",
                        "action": "replaced",
                        "target": target,
                        "replacements": 0,
                        "agent_directive": STOP_RETRY_DIRECTIVE
                    }

                return {
                    "status": "ok",
                    "action": "replaced",
                    "target": target,
                    "replacements": total_replacements,
                    "keys_count": len(sorted_map),
                    "sheets_processed": len(sheets_to_process),
                    "agent_directive": VERIFIED_DIRECTIVE
                }

            if clear and sheet:
                sheet.Cells.Clear()
                if not records:
                    if not is_active:
                        wb.SaveAs(abs_target) if is_new_wb else wb.Save()
                    return {"status": "ok", "action": "cleared", "target": target, "count": 0, "agent_directive": VERIFIED_DIRECTIVE}

            def get_append_row(ws):
                try:
                    used = ws.UsedRange
                    if used is None or used.Rows.Count == 0:
                        return 1
                    if used.Rows.Count == 1 and used.Columns.Count == 1 and used.Cells(1, 1).Value2 is None:
                        return 1
                    return used.Row + used.Rows.Count
                except Exception:
                    return 1

            found_cell = None
            start_col = 1
            if anchor:
                try:
                    found_cell = sheet.Cells.Find(What=anchor)
                except Exception:
                    found_cell = None
                if not found_cell:
                    stripped_anchor = anchor.strip()
                    if stripped_anchor and stripped_anchor != anchor:
                        try:
                            found_cell = sheet.Cells.Find(What=stripped_anchor)
                        except Exception:
                            pass
                    if not found_cell and len(stripped_anchor) > 2:
                        no_spaces = stripped_anchor.replace(" ", "")
                        try:
                            found_cell = sheet.Cells.Find(What=no_spaces)
                        except Exception:
                            pass
                if found_cell:
                    if pos == "before":
                        start_row = found_cell.Row
                        non_chart_count = sum(1 for r in records if r.get("type") not in ("chart", "image"))
                        if non_chart_count > 0:
                            try:
                                insert_rng = sheet.Range(sheet.Rows(start_row), sheet.Rows(start_row + non_chart_count - 1))
                                insert_rng.Insert(-4121)
                            except Exception:
                                pass
                    elif pos == "replace":
                        start_row = found_cell.Row
                        start_col = found_cell.Column
                    else:
                        start_row = found_cell.Row + 1
                else:
                    start_row = 1 if clear else get_append_row(sheet)
            else:
                start_row = 1 if clear else get_append_row(sheet)

            curr_row = start_row
            written_items = 0
            max_cols_written = 1

            def flush_data_matrix(matrix: List[List[Any]], r_start: int, c_start: int = 1) -> int:
                nonlocal max_cols_written
                if not matrix:
                    return 0
                max_cols = max(len(row) for row in matrix) if matrix else 1
                max_cols_written = max(max_cols_written, c_start + max_cols - 1)
                norm_matrix = []
                has_formula = False
                for row in matrix:
                    casted_row = [cast_excel_value(c) for c in row]
                    padded = casted_row + [""] * (max_cols - len(casted_row))
                    for c_val in padded:
                        if isinstance(c_val, str) and c_val.startswith("="):
                            has_formula = True
                    norm_matrix.append(padded)

                r_end = r_start + len(norm_matrix) - 1
                c_end = c_start + max_cols - 1
                target_rng = sheet.Range(sheet.Cells(r_start, c_start), sheet.Cells(r_end, c_end))
                val_tuple = tuple(tuple(r) for r in norm_matrix)
                if has_formula:
                    target_rng.Formula = val_tuple
                else:
                    target_rng.Value2 = val_tuple
                return len(norm_matrix)

            pending_matrix: List[List[Any]] = []
            effective_col = start_col if (pos == "replace" and len(records) == 1 and not isinstance(records[0].get("data"), list)) else 1

            for rec in records:
                if rec.get("type") == "chart":
                    continue
                if rec.get("type") == "image":
                    if pending_matrix:
                        cnt = flush_data_matrix(pending_matrix, curr_row, effective_col)
                        curr_row += cnt
                        written_items += cnt
                        pending_matrix = []

                    img_path = os.path.abspath(str(rec.get("data", "")))
                    if os.path.exists(img_path):
                        c_cell = sheet.Cells(curr_row, effective_col)
                        sheet.Shapes.AddPicture(
                            Filename=img_path,
                            LinkToFile=False,
                            SaveWithDocument=True,
                            Left=float(c_cell.Left),
                            Top=float(c_cell.Top),
                            Width=480,
                            Height=280
                        )
                        curr_row += 15
                        written_items += 1
                    continue

                data = rec.get("data", "")
                if isinstance(data, list):
                    pending_matrix.append(data)
                else:
                    pending_matrix.append([data])

            if pending_matrix:
                cnt = flush_data_matrix(pending_matrix, curr_row, effective_col)
                curr_row += cnt
                written_items += cnt
                pending_matrix = []

            if curr_row > start_row and start_row > 1 and max_cols_written > 0:
                try:
                    ref_rng = sheet.Range(sheet.Cells(start_row - 1, 1), sheet.Cells(start_row - 1, max_cols_written))
                    target_rng = sheet.Range(sheet.Cells(start_row, 1), sheet.Cells(curr_row - 1, max_cols_written))
                    target_rng.Font.Name = ref_rng.Font.Name
                    target_rng.Font.Size = ref_rng.Font.Size
                    target_rng.Font.Bold = False
                    target_rng.Interior.Color = ref_rng.Interior.Color
                    target_rng.NumberFormat = ref_rng.NumberFormat
                except Exception:
                    pass

            for rec in records:
                if rec.get("type") == "chart":
                    chart = rec.get("chart_type") or chart or "line"
                    if rec.get("title"):
                        chart_title = rec.get("title")

            chart_created = False
            if chart and curr_row > start_row and max_cols_written >= 1:
                try:
                    excel_chart_types = {
                        "line": 4,
                        "line_markers": 65,
                        "smooth": 72,
                        "scatter": -4169,
                        "scatter_smooth": 72,
                        "scatter_lines": 74,
                        "column": 51,
                        "bar": 57,
                        "pie": 5,
                        "area": 1,
                    }
                    c_type_lower = str(chart).lower().strip()
                    xl_type = excel_chart_types.get(c_type_lower, 4)
                    data_rng = sheet.Range(sheet.Cells(start_row, 1), sheet.Cells(curr_row - 1, max_cols_written))

                    try:
                        c_cell = sheet.Cells(start_row, max_cols_written + 2)
                        c_left = float(c_cell.Left)
                        c_top = float(c_cell.Top)
                    except Exception:
                        c_left = 320.0
                        c_top = 20.0

                    chart_obj = sheet.ChartObjects().Add(c_left, c_top, 500, 300)
                    ch = chart_obj.Chart
                    ch.ChartType = xl_type
                    ch.SetSourceData(data_rng)
                    if chart_title:
                        ch.HasTitle = True
                        ch.ChartTitle.Text = str(chart_title)
                    chart_created = True
                except Exception:
                    pass

            if not is_active:
                wb.SaveAs(abs_target) if is_new_wb else wb.Save()

            res_data = {
                "status": "ok",
                "action": "written",
                "target": target,
                "sheet": sheet.Name,
                "count": written_items,
                "preview": [r.get("data") for r in records[:3]],
                "agent_directive": VERIFIED_DIRECTIVE
            }
            if chart_created:
                res_data["chart"] = chart
            return res_data

        finally:
            if not is_active:
                if wb:
                    try: wb.Close(False)
                    except Exception: pass
                if app:
                    try: app.Quit()
                    except Exception: pass
                if guard_pid:
                    ComProcessGuard.unregister(guard_pid)

    @staticmethod
    @com_safe()
    def _write_ppt(target: str, is_active: bool, records: List[Dict[str, Any]], anchor: Optional[str], pos: str, clear: bool = False, pages: Optional[str] = None, replace_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        sync_desktop_to_default()
        app = None
        prs = None
        guard_pid = None
        is_new_prs = False
        try:
            if is_active:
                app, prs = find_active_ppt_presentation(target)
                if not app:
                    try:
                        app = win32com.client.Dispatch("PowerPoint.Application")
                    except Exception:
                        pass
                if not prs:
                    prs = app.ActivePresentation if (app and app.Presentations.Count > 0) else (app.Presentations.Add(WithWindow=True) if app else None)
                try:
                    app.Visible = True
                    if app.Windows.Count > 0:
                        app.Windows(1).Activate()
                        ensure_window_visible(app.ActiveWindow.HWND)
                except Exception:
                    pass
            else:
                abs_target = os.path.abspath(target)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("PowerPoint.Application", "POWERPNT.EXE")
                if os.path.exists(abs_target):
                    prs = app.Presentations.Open(abs_target, WithWindow=False)
                    is_new_prs = False
                else:
                    prs = app.Presentations.Add(WithWindow=False)
                    is_new_prs = True

            target_slide = None
            anchor_shape = None

            target_slide_idx = None
            if pages and pages.strip().isdigit():
                target_slide_idx = int(pages.strip())
                if 1 <= target_slide_idx <= prs.Slides.Count:
                    target_slide = prs.Slides(target_slide_idx)

            if replace_map and prs:
                sorted_map = dict(sorted(replace_map.items(), key=lambda item: len(str(item[0])), reverse=True))
                total_replacements = 0
                slides_to_process = [target_slide] if target_slide else [prs.Slides(i) for i in range(1, prs.Slides.Count + 1)]

                def _apply_text_and_style_to_tr(tr, parent_shape=None) -> int:
                    changes = 0
                    for old_s, spec_raw in sorted_map.items():
                        if not old_s:
                            continue
                        spec = normalize_replace_item(spec_raw)
                        new_s = spec.get("text")
                        color = spec.get("color")
                        bold = spec.get("bold")
                        italic = spec.get("italic")
                        bg = spec.get("bg")

                        if new_s is not None and str(new_s) != old_s:
                            try:
                                safety_c = 0
                                found = tr.Replace(FindWhat=old_s, ReplaceWhat=str(new_s), MatchCase=False)
                                while found and safety_c < 500:
                                    safety_c += 1
                                    if color is not None:
                                        found.Font.Color.RGB = color
                                    if bold is not None:
                                        found.Font.Bold = -1 if bold else 0
                                    if italic is not None:
                                        found.Font.Italic = -1 if italic else 0
                                    if bg is not None and parent_shape is not None:
                                        try:
                                            parent_shape.Fill.Solid()
                                            parent_shape.Fill.ForeColor.RGB = bg
                                        except Exception:
                                            pass
                                    changes += 1
                                    after_idx = found.Start + found.Length - 1
                                    if after_idx >= tr.Length:
                                        break
                                    found = tr.Replace(FindWhat=old_s, ReplaceWhat=str(new_s), After=after_idx, MatchCase=False)
                            except Exception:
                                if old_s in tr.Text:
                                    tr.Text = tr.Text.replace(old_s, str(new_s))
                                    changes += 1
                        elif any(v is not None for v in (color, bold, italic, bg)) and old_s.lower() in tr.Text.lower():
                            try:
                                safety_c = 0
                                found = tr.Find(FindWhat=old_s, MatchCase=False)
                                while found and safety_c < 500:
                                    safety_c += 1
                                    if color is not None:
                                        found.Font.Color.RGB = color
                                    if bold is not None:
                                        found.Font.Bold = -1 if bold else 0
                                    if italic is not None:
                                        found.Font.Italic = -1 if italic else 0
                                    if bg is not None and parent_shape is not None:
                                        try:
                                            parent_shape.Fill.Solid()
                                            parent_shape.Fill.ForeColor.RGB = bg
                                        except Exception:
                                            pass
                                    changes += 1
                                    after_idx = found.Start + found.Length - 1
                                    if after_idx >= tr.Length:
                                        break
                                    found = tr.Find(FindWhat=old_s, After=after_idx, MatchCase=False)
                            except Exception:
                                pass
                    return changes

                def _replace_in_shape(sh) -> int:
                    sub_count = 0
                    try:
                        if getattr(sh, "Type", None) == 6:
                            for sub in sh.GroupItems:
                                sub_count += _replace_in_shape(sub)
                            return sub_count
                    except Exception:
                        pass

                    try:
                        if getattr(sh, "HasTable", False):
                            tbl = sh.Table
                            for r in range(1, tbl.Rows.Count + 1):
                                for c in range(1, tbl.Columns.Count + 1):
                                    cell_sh = tbl.Cell(r, c).Shape
                                    if cell_sh.HasTextFrame and cell_sh.TextFrame.HasText:
                                        sub_count += _apply_text_and_style_to_tr(cell_sh.TextFrame.TextRange, parent_shape=cell_sh)
                            return sub_count
                    except Exception:
                        pass

                    try:
                        if getattr(sh, "HasTextFrame", False) and sh.TextFrame.HasText:
                            sub_count += _apply_text_and_style_to_tr(sh.TextFrame.TextRange, parent_shape=sh)
                    except Exception:
                        pass

                    return sub_count

                for sl in slides_to_process:
                    for sh in sl.Shapes:
                        total_replacements += _replace_in_shape(sh)

                if not is_active:
                    prs.SaveAs(abs_target) if is_new_prs else prs.Save()

                if total_replacements == 0:
                    return {
                        "status": "no_match",
                        "action": "replaced",
                        "target": target,
                        "replacements": 0,
                        "agent_directive": STOP_RETRY_DIRECTIVE
                    }

                return {
                    "status": "ok",
                    "action": "replaced",
                    "target": target,
                    "replacements": total_replacements,
                    "keys_count": len(sorted_map),
                    "slides_processed": len(slides_to_process),
                    "agent_directive": VERIFIED_DIRECTIVE
                }

            if clear and prs:
                if target_slide:
                    for shape_idx in range(target_slide.Shapes.Count, 0, -1):
                        try:
                            target_slide.Shapes(shape_idx).Delete()
                        except Exception:
                            pass
                    if not records:
                        if not is_active:
                            prs.SaveAs(abs_target) if is_new_prs else prs.Save()
                        return {"status": "ok", "action": "cleared", "target": target, "count": 0, "slide": target_slide_idx, "agent_directive": VERIFIED_DIRECTIVE}
                else:
                    prs.Slides.Add(prs.Slides.Count + 1, 12)
                    while prs.Slides.Count > 1:
                        prs.Slides(1).Delete()
                    for shape_idx in range(prs.Slides(1).Shapes.Count, 0, -1):
                        try:
                            prs.Slides(1).Shapes(shape_idx).Delete()
                        except Exception:
                            pass
                    if not records:
                        if not is_active:
                            prs.SaveAs(abs_target) if is_new_prs else prs.Save()
                        return {"status": "ok", "action": "cleared", "target": target, "count": 0, "slides": 1, "agent_directive": VERIFIED_DIRECTIVE}

            ref_font_name = None
            ref_font_color = None
            try:
                for s in prs.Slides:
                    for sh in s.Shapes:
                        if sh.HasTextFrame and sh.TextFrame.HasText:
                            ref_font_name = sh.TextFrame.TextRange.Font.Name
                            try:
                                ref_font_color = sh.TextFrame.TextRange.Font.Color.RGB
                            except Exception:
                                pass
                            break
                    if ref_font_name:
                        break
            except Exception:
                pass

            if not target_slide:
                anchor_shape = None
            if anchor:
                clean_anchor = anchor.strip()
                no_space_anchor = clean_anchor.replace(" ", "")

                def _find_shape_recursive(parent_shape):
                    try:
                        if getattr(parent_shape, "Type", None) == 6:
                            for sub in parent_shape.GroupItems:
                                f = _find_shape_recursive(sub)
                                if f: return f
                    except Exception:
                        pass
                    if getattr(parent_shape, "HasTextFrame", False) and parent_shape.TextFrame.HasText:
                        sh_text = parent_shape.TextFrame.TextRange.Text
                        if anchor in sh_text or clean_anchor in sh_text or (len(no_space_anchor) > 2 and no_space_anchor in sh_text.replace(" ", "")):
                            return (parent_shape, "shape", parent_shape)
                    if getattr(parent_shape, "HasTable", False):
                        tbl = parent_shape.Table
                        for r_i in range(1, tbl.Rows.Count + 1):
                            for c_i in range(1, tbl.Columns.Count + 1):
                                cell = tbl.Cell(r_i, c_i)
                                if cell.Shape.HasTextFrame and cell.Shape.TextFrame.HasText:
                                    c_text = cell.Shape.TextFrame.TextRange.Text
                                    if anchor in c_text or clean_anchor in c_text or (len(no_space_anchor) > 2 and no_space_anchor in c_text.replace(" ", "")):
                                        return (parent_shape, "cell", cell.Shape)
                    return None

                for s_idx in range(1, prs.Slides.Count + 1):
                    s = prs.Slides(s_idx)
                    for shape in s.Shapes:
                        found_res = _find_shape_recursive(shape)
                        if found_res:
                            target_slide = s
                            _, _, target_text_sh = found_res
                            anchor_shape = target_text_sh
                            break
                    if target_slide:
                        break

            def create_new_blank_slide():
                s = prs.Slides.Add(prs.Slides.Count + 1, 12)
                for shape_idx in range(s.Shapes.Count, 0, -1):
                    try:
                        sh = s.Shapes(shape_idx)
                        if getattr(sh, "Type", None) == 14:
                            sh.Delete()
                    except Exception:
                        pass
                return s

            if not target_slide:
                target_slide = prs.Slides(prs.Slides.Count) if prs.Slides.Count > 0 else create_new_blank_slide()

            if anchor_shape is not None and pos == "replace" and all(r.get("type") not in ("image", "table_row") and not isinstance(r.get("data"), list) for r in records):
                new_txt = "\n".join(str(r.get("data", "")) for r in records)
                orig_txt = anchor_shape.TextFrame.TextRange.Text
                if anchor in orig_txt:
                    anchor_shape.TextFrame.TextRange.Text = orig_txt.replace(anchor, new_txt)
                elif anchor.strip() in orig_txt:
                    anchor_shape.TextFrame.TextRange.Text = orig_txt.replace(anchor.strip(), new_txt)
                else:
                    anchor_shape.TextFrame.TextRange.Text = new_txt
                if not is_active:
                    prs.SaveAs(abs_target) if is_new_prs else prs.Save()
                return {"status": "ok", "action": "written", "target": target, "count": len(records), "agent_directive": VERIFIED_DIRECTIVE}

            try:
                slide_height = float(prs.PageSetup.SlideHeight)
                slide_width = float(prs.PageSetup.SlideWidth)
            except Exception:
                slide_height = 540.0
                slide_width = 960.0

            top_margin = 50.0
            bottom_margin = 50.0
            item_height = 32.0
            box_width = max(200.0, slide_width - 100.0)

            if anchor_shape is not None:
                a_top = float(anchor_shape.Top)
                a_height = float(anchor_shape.Height)
                if pos == "replace":
                    top_offset = a_top
                    try:
                        anchor_shape.Delete()
                    except Exception:
                        pass
                elif pos == "before":
                    top_offset = a_top
                    est_shift = max(40.0, len(records) * 32.0)
                    for sh in target_slide.Shapes:
                        try:
                            if float(sh.Top) >= a_top - 2.0:
                                sh.Top = float(sh.Top) + est_shift
                        except Exception:
                            pass
                else:
                    top_offset = a_top + a_height + 12.0
            else:
                current_bottom = top_margin
                for shape in target_slide.Shapes:
                    try:
                        sh_bottom = float(shape.Top) + float(shape.Height)
                        if sh_bottom > current_bottom:
                            current_bottom = sh_bottom
                    except Exception:
                        pass
                top_offset = current_bottom + 12.0 if current_bottom > top_margin else top_margin

            blocks = []
            current_table_rows = []
            for rec in records:
                data = rec.get("data", "")
                if rec.get("type") == "image":
                    if current_table_rows:
                        blocks.append({"type": "table", "rows": current_table_rows})
                        current_table_rows = []
                    blocks.append({"type": "image", "data": str(data)})
                elif rec.get("type") == "table_row" or isinstance(data, list):
                    row_vals = data if isinstance(data, list) else [str(data)]
                    current_table_rows.append([str(c) for c in row_vals])
                else:
                    if current_table_rows:
                        blocks.append({"type": "table", "rows": current_table_rows})
                        current_table_rows = []
                    blocks.append({"type": "text", "data": str(data)})
            if current_table_rows:
                blocks.append({"type": "table", "rows": current_table_rows})

            written_items = 0
            row_height = 24.0

            for blk in blocks:
                if blk["type"] == "image":
                    img_path = os.path.abspath(blk["data"])
                    if os.path.exists(img_path):
                        img_w = min(box_width, 560.0)
                        img_h = 280.0
                        if top_offset + img_h > (slide_height - bottom_margin):
                            target_slide = create_new_blank_slide()
                            top_offset = top_margin
                        target_slide.Shapes.AddPicture(
                            FileName=img_path,
                            LinkToFile=False,
                            SaveWithDocument=True,
                            Left=50,
                            Top=top_offset,
                            Width=img_w,
                            Height=img_h
                        )
                        top_offset += img_h + 12.0
                        written_items += 1

                elif blk["type"] == "text":
                    txt = blk["data"].strip()
                    if not txt or txt == "/":
                        continue
                    if top_offset + item_height > (slide_height - bottom_margin):
                        target_slide = create_new_blank_slide()
                        top_offset = top_margin

                    box = target_slide.Shapes.AddTextbox(1, 50, top_offset, box_width, item_height)
                    try:
                        box.TextFrame.WordWrap = -1
                    except Exception:
                        pass
                    box.TextFrame.TextRange.Text = txt
                    if ref_font_name:
                        try:
                            box.TextFrame.TextRange.Font.Name = ref_font_name
                            if ref_font_color is not None:
                                box.TextFrame.TextRange.Font.Color.RGB = ref_font_color
                        except Exception:
                            pass

                    actual_h = item_height
                    try:
                        actual_h = max(item_height, float(box.Height))
                    except Exception:
                        pass

                    top_offset += actual_h + 6.0
                    written_items += 1

                elif blk["type"] == "table":
                    rows = blk["rows"]
                    num_cols = max(len(r) for r in rows) if rows else 1
                    row_idx = 0
                    total_rows = len(rows)

                    while row_idx < total_rows:
                        available_height = (slide_height - bottom_margin) - top_offset
                        if available_height < (row_height * 2):
                            target_slide = create_new_blank_slide()
                            top_offset = top_margin
                            available_height = (slide_height - bottom_margin) - top_offset

                        max_rows_for_this_slide = max(1, int(available_height // row_height))
                        chunk = rows[row_idx: row_idx + max_rows_for_this_slide]
                        chunk_len = len(chunk)
                        tbl_h = max(24.0, float(chunk_len * row_height))

                        tbl_shape = target_slide.Shapes.AddTable(chunk_len, num_cols, 50, top_offset, box_width, tbl_h)
                        for r_i, r_data in enumerate(chunk, start=1):
                            for c_i in range(1, num_cols + 1):
                                val = r_data[c_i - 1] if c_i - 1 < len(r_data) else ""
                                try:
                                    cell_obj = tbl_shape.Table.Cell(r_i, c_i).Shape
                                    cell_obj.TextFrame.TextRange.Text = str(val)
                                    cell_obj.TextFrame.TextRange.Font.Size = 11
                                    if ref_font_name:
                                        try:
                                            cell_obj.TextFrame.TextRange.Font.Name = ref_font_name
                                            if ref_font_color is not None:
                                                cell_obj.TextFrame.TextRange.Font.Color.RGB = ref_font_color
                                        except Exception:
                                            pass
                                    cell_obj.TextFrame.MarginTop = 3
                                    cell_obj.TextFrame.MarginBottom = 3
                                except Exception:
                                    pass

                        actual_tbl_h = tbl_h
                        try:
                            actual_tbl_h = max(tbl_h, float(tbl_shape.Height))
                        except Exception:
                            pass

                        top_offset += actual_tbl_h + 12.0
                        written_items += chunk_len
                        row_idx += chunk_len

                        if row_idx < total_rows:
                            target_slide = create_new_blank_slide()
                            top_offset = top_margin

            if not is_active:
                prs.SaveAs(abs_target) if is_new_prs else prs.Save()

            return {"status": "ok", "action": "written", "target": target, "count": written_items, "agent_directive": VERIFIED_DIRECTIVE}

        finally:
            if not is_active:
                if prs:
                    try: prs.Close()
                    except Exception: pass
                if app:
                    try: app.Quit()
                    except Exception: pass
                if guard_pid:
                    ComProcessGuard.unregister(guard_pid)

    @staticmethod
    def _write_md_txt(target: str, records: List[Dict[str, Any]], anchor: Optional[str], pos: str, clear: bool = False, replace_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        p = Path(target).resolve()
        if replace_map:
            if not p.exists():
                raise FileNotFoundError(f"대상 파일이 존재하지 않습니다: {target}")
            content = p.read_text(encoding="utf-8", errors="replace")
            sorted_map = dict(sorted(replace_map.items(), key=lambda item: len(str(item[0])), reverse=True))
            rep_count = 0
            for k, v in sorted_map.items():
                spec = normalize_replace_item(v)
                new_s = spec.get("text")
                if new_s is not None and k in content:
                    content = content.replace(k, str(new_s))
                    rep_count += 1
            p.write_text(content, encoding="utf-8")
            return {
                "status": "ok",
                "action": "replaced",
                "target": target,
                "replacements": rep_count,
                "keys_count": len(sorted_map),
                "agent_directive": VERIFIED_DIRECTIVE
            }

        if clear:
            content = ""
            if not records:
                p.write_text("", encoding="utf-8")
                return {"status": "ok", "action": "cleared", "target": target, "count": 0, "agent_directive": VERIFIED_DIRECTIVE}
        else:
            content = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""

        insert_lines = []
        for rec in records:
            data = rec.get("data", "")
            if isinstance(data, list):
                insert_lines.append("| " + " | ".join(str(c) for c in data) + " |")
            else:
                insert_lines.append(str(data))
        insert_block = "\n".join(insert_lines) + "\n"

        matched_anchor = None
        if anchor:
            if anchor in content:
                matched_anchor = anchor
            elif anchor.strip() in content:
                matched_anchor = anchor.strip()
            elif len(anchor.strip().replace(" ", "")) > 2:
                clean = re.escape(anchor.strip().replace(" ", ""))
                pattern = r"\s*".join(list(clean))
                m = re.search(pattern, content)
                if m:
                    matched_anchor = m.group(0)

        if matched_anchor:
            if pos == "before":
                new_content = content.replace(matched_anchor, insert_block + matched_anchor, 1)
            elif pos == "after":
                new_content = content.replace(matched_anchor, matched_anchor + "\n" + insert_block, 1)
            elif pos == "replace":
                new_content = content.replace(matched_anchor, insert_block.rstrip("\n"), 1)
            else:
                new_content = content + "\n" + insert_block
        else:
            new_content = content + ("\n" if content and not content.endswith("\n") else "") + insert_block

        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new_content, encoding="utf-8")
        return {"status": "ok", "action": "written", "target": target, "count": len(records), "agent_directive": VERIFIED_DIRECTIVE}


# ==============================================================================
# 9. 문서 파싱 라우터 (로드 / 캐시 연동)
# ==============================================================================
def parse_document(file_path: Optional[str], is_active: bool = False, extract_images: bool = False, target_pages: Optional[Set[Union[int, str]]] = None) -> List[Dict[str, Any]]:
    cache_mgr = CacheManager()

    if is_active:
        ext = resolve_target_ext(file_path)
        if ext in ["docx", "doc", "word"]:
            return DocumentParser.parse_word(file_path=file_path, is_active=True, extract_images=extract_images, target_pages=target_pages)
        elif ext in ["xlsx", "xls", "xlsm", "excel"] or (file_path and (file_path.lower().startswith("book") or "sheet" in file_path.lower())):
            return DocumentParser.parse_excel(file_path=file_path, is_active=True, extract_images=extract_images, target_pages=target_pages)
        elif ext in ["pptx", "ppt", "powerpoint"]:
            return DocumentParser.parse_ppt(file_path=file_path, is_active=True, target_pages=target_pages)
        elif ext in ["hwp", "hwpx"]:
            raise ValueError("한글(HWP) 및 PDF는 파일 기반 오프라인 읽기 전용으로 지원됩니다.")
        else:
            try:
                _, d = find_active_word_document(file_path)
                if d:
                    return DocumentParser.parse_word(file_path=file_path, is_active=True, extract_images=extract_images, target_pages=target_pages)
            except Exception:
                pass
            try:
                _, p = find_active_ppt_presentation(file_path)
                if p:
                    return DocumentParser.parse_ppt(file_path=file_path, is_active=True, target_pages=target_pages)
            except Exception:
                pass
            try:
                return DocumentParser.parse_excel(file_path=file_path, is_active=True, extract_images=extract_images, target_pages=target_pages)
            except Exception:
                raise ValueError(f"지원하지 않거나 감지되지 않는 활성 창 대상입니다: {file_path}")

    if not file_path:
        raise ValueError("--from/--file 인자가 필요합니다.")

    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {abs_path}")

    ext = resolve_target_ext(abs_path)

    # JSON / JSONL 입력 파일은 캐싱 대상이 아니며 멀티라인 JSON 및 줄 단위 JSONL을 모두 지원
    if ext in ["jsonl", "json"]:
        records = []
        raw_content = Path(abs_path).read_text(encoding="utf-8-sig", errors="replace").strip()
        if not raw_content:
            return []

        # 1차: 전체 파일을 단일 JSON 배열/객체로 파싱 시도 (Pretty-printed 멀티라인 JSON 완벽 방어)
        parsed_whole = False
        if (raw_content.startswith("[") and raw_content.endswith("]")) or (raw_content.startswith("{") and raw_content.endswith("}")):
            try:
                whole_obj = json.loads(raw_content)
                if isinstance(whole_obj, list):
                    for idx, item in enumerate(whole_obj):
                        if isinstance(item, dict):
                            if "data" in item and isinstance(item["data"], list) and "type" not in item:
                                item["type"] = "table_row"
                            records.append(item)
                        elif isinstance(item, list):
                            records.append({"id": idx, "type": "table_row", "data": item})
                        else:
                            records.append({"id": idx, "type": "text", "data": str(item)})
                    parsed_whole = True
                elif isinstance(whole_obj, dict):
                    if "data" in whole_obj and isinstance(whole_obj["data"], list) and "type" not in whole_obj:
                        whole_obj["type"] = "table_row"
                    records.append(whole_obj)
                    parsed_whole = True
            except Exception:
                parsed_whole = False

        # 2차: 줄 단위 JSONL 파싱
        if not parsed_whole:
            for line_idx, line in enumerate(raw_content.splitlines()):
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    obj = json.loads(line_str)
                    if isinstance(obj, dict):
                        if "data" in obj and isinstance(obj["data"], list) and "type" not in obj:
                            obj["type"] = "table_row"
                        records.append(obj)
                    elif isinstance(obj, list):
                        records.append({"id": line_idx, "type": "table_row", "data": obj})
                    else:
                        records.append({"id": line_idx, "type": "text", "data": str(obj)})
                except Exception:
                    records.append({"id": line_idx, "type": "text", "data": line_str})

        if target_pages:
            records = [r for r in records if r.get("page") in target_pages or r.get("section") in target_pages]
        return records

    cached = cache_mgr.load(abs_path)
    if cached is not None:
        bypass_cache = False
        if extract_images and ext in ["pdf", "docx", "doc", "xlsx", "xls", "xlsm"]:
            has_valid_images = any(
                r.get("type") == "image" and os.path.exists(str(r.get("data", "")))
                for r in cached
            )
            if not has_valid_images:
                bypass_cache = True

        if not bypass_cache:
            if not extract_images:
                cached = [r for r in cached if r.get("type") != "image"]
            if target_pages:
                return [
                    r for r in cached
                    if r.get("page") in target_pages or str(r.get("section", "")).lower() in {str(p).lower() for p in target_pages}
                ]
            return cached

    if ext == "pdf":
        records = DocumentParser.parse_pdf(abs_path, extract_images=extract_images)
        if target_pages:
            records = [r for r in records if r.get("page") in target_pages]
    elif ext in ["xlsx", "xls", "xlsm"]:
        records = DocumentParser.parse_excel(abs_path, is_active=False, extract_images=extract_images, target_pages=target_pages)
    elif ext == "csv":
        records = DocumentParser.parse_csv(abs_path)
    elif ext in ["docx", "doc"]:
        records = DocumentParser.parse_word(abs_path, is_active=False, extract_images=extract_images, target_pages=target_pages)
    elif ext in ["pptx", "ppt"]:
        records = DocumentParser.parse_ppt(abs_path, is_active=False, target_pages=target_pages)
    elif ext in ["hwp", "hwpx"]:
        records = DocumentParser.parse_hwp(abs_path, is_active=False)
    elif ext in ["md", "txt"]:
        records = DocumentParser.parse_md_txt(abs_path)
    else:
        raise ValueError(f"지원하지 않는 문서 포맷입니다: {ext}")

    if not target_pages:
        cache_mgr.save(abs_path, records)
    return records


# ==============================================================================
# 10. 스마트 데이터 파서 및 메인 CLI 진입점
# ==============================================================================
def parse_smart_data(raw_data: str) -> List[Dict[str, Any]]:
    """입력 문자열(--data)을 분석해 이미지, 표(마크다운/JSON/JSONL/TSV), 일반 텍스트로 자동 변환"""
    if not raw_data or not raw_data.strip():
        return []
    s = raw_data.strip()

    m_img = re.match(r"^!\[.*?\]\((.+?)\)$", s)
    img_candidate = m_img.group(1).strip() if m_img else s
    if os.path.exists(img_candidate) and img_candidate.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")):
        return [{"type": "image", "data": os.path.abspath(img_candidate)}]

    if s.startswith("[") and s.endswith("]"):
        try:
            obj = json.loads(s)
            if isinstance(obj, list) and obj:
                if all(isinstance(r, dict) for r in obj):
                    parsed_rows = []
                    for r in obj:
                        if r.get("type") == "table_row" and isinstance(r.get("data"), list):
                            parsed_rows.append({"type": "table_row", "data": r["data"]})
                        elif "data" in r and isinstance(r["data"], list):
                            parsed_rows.append({"type": "table_row", "data": r["data"]})
                        elif "type" in r and "data" in r:
                            parsed_rows.append(r)
                    if parsed_rows:
                        return parsed_rows
                if all(isinstance(r, list) for r in obj):
                    return [{"type": "table_row", "data": r} for r in obj]
                return [{"type": "table_row", "data": obj}]
        except Exception:
            pass

    records = []
    lines = s.replace("\\n", "\n").splitlines()
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue

        if line_s.startswith("{") and line_s.endswith("}"):
            try:
                j_obj = json.loads(line_s)
                if isinstance(j_obj, dict):
                    if j_obj.get("type") == "table_row" and isinstance(j_obj.get("data"), list):
                        records.append({"type": "table_row", "data": j_obj["data"]})
                        continue
                    elif "data" in j_obj and isinstance(j_obj["data"], list):
                        records.append({"type": "table_row", "data": j_obj["data"]})
                        continue
                    elif "type" in j_obj and "data" in j_obj:
                        records.append(j_obj)
                        continue
            except Exception:
                pass

        line_img = re.match(r"^!\[.*?\]\((.+?)\)$", line_s)
        if line_img:
            cand = line_img.group(1).strip()
            if os.path.exists(cand) and cand.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")):
                records.append({"type": "image", "data": os.path.abspath(cand)})
                continue
        if os.path.exists(line_s) and line_s.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")):
            records.append({"type": "image", "data": os.path.abspath(line_s)})
            continue

        if line_s.startswith("|") and line_s.endswith("|"):
            if re.match(r"^\|[\s\-:|]+\|$", line_s):
                continue
            cells = [c.strip() for c in line_s.strip("|").split("|")]
            records.append({"type": "table_row", "data": cells})
        elif "\t" in line_s:
            cells = [c.strip() for c in line_s.split("\t")]
            records.append({"type": "table_row", "data": cells})
        else:
            records.append({"type": "text", "data": line_s})
    return records


def is_active_target(val: Optional[str], is_write: bool = False, explicit_flag: bool = False) -> bool:
    if explicit_flag:
        return True
    if not val:
        return False
    v = val.strip().lower()
    if v in {"word", "excel", "ppt", "doc", "docx", "xls", "xlsx", "xlsm", "pptx", "powerpoint"}:
        return True
    if os.path.exists(val):
        return False
    if "/" in val or "\\" in val:
        return False

    target_ext = resolve_target_ext(v)
    if target_ext in {"pdf", "hwp", "hwpx", "csv", "md", "txt", "json", "jsonl"}:
        return False

    if not is_write:
        return True

    if "." not in os.path.basename(v):
        return True

    try:
        for a in get_all_active_excel_apps():
            try:
                for w in a.Workbooks:
                    w_name = w.Name.lower()
                    if w_name == v or w_name == f"{v}.xlsx" or w_name.rsplit(".", 1)[0] == v:
                        return True
            except Exception:
                pass
        if win32com:
            try:
                w_app = win32com.client.GetActiveObject("Word.Application")
                if w_app:
                    for d in w_app.Documents:
                        d_name = d.Name.lower()
                        if d_name == v or d_name == f"{v}.docx" or d_name.rsplit(".", 1)[0] == v:
                            return True
            except Exception:
                pass
            try:
                p_app = win32com.client.GetActiveObject("PowerPoint.Application")
                if p_app:
                    for p in p_app.Presentations:
                        p_name = p.Name.lower()
                        if p_name == v or p_name == f"{v}.pptx" or p_name.rsplit(".", 1)[0] == v:
                            return True
            except Exception:
                pass
    except Exception:
        pass

    return False


def get_document_info(target: str, is_active: bool = False) -> Dict[str, Any]:
    """본문 전체 파싱 없이 문서의 쪽수, 시트/슬라이드/섹션 목차(TOC)를 0.1초 내 초고속 요약 추출"""
    clean_target = (target or "").strip()
    ext = resolve_target_ext(clean_target)
    src_name = clean_target
    mode = "active_window" if is_active else "file"

    if not is_active:
        abs_path = os.path.abspath(clean_target)
        src_name = os.path.basename(abs_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {abs_path}")

        cache_mgr = CacheManager()
        cached = cache_mgr.load(abs_path)
        if cached:
            pages = set(r.get("page") for r in cached if r.get("page") is not None)
            toc = []
            for r in cached:
                sec = r.get("section")
                if sec and sec not in toc:
                    toc.append(sec)
            return {
                "status": "ok",
                "src": src_name,
                "mode": mode,
                "ext": ext,
                "page_count": max(pages) if pages else 1,
                "total_records": len(cached),
                "toc": toc[:20],
                "sections": toc[:20]
            }

    if ext == "pdf" and not is_active and pymupdf:
        try:
            doc = pymupdf.open(abs_path)
            p_count = doc.page_count
            raw_toc = doc.get_toc()
            toc = [item[1].strip() for item in raw_toc if len(item) > 1 and item[1].strip()][:20]
            doc.close()
            return {
                "status": "ok",
                "src": src_name,
                "mode": mode,
                "ext": ext,
                "page_count": p_count,
                "toc": toc,
                "sections": toc
            }
        except Exception:
            pass

    if ext == "xlsx":
        app = None
        wb = None
        need_quit = False
        guard_pid = None
        try:
            if is_active:
                app, wb = find_active_excel_workbook(clean_target)
                if not wb and app and app.Workbooks.Count > 0:
                    wb = app.ActiveWorkbook
            else:
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Excel.Application", "EXCEL.EXE")
                app.Visible = False
                app.DisplayAlerts = False
                wb = app.Workbooks.Open(abs_path, UpdateLinks=0, ReadOnly=True, IgnoreReadOnlyRecommended=True, Password="")
                need_quit = True

            if wb:
                p_count = wb.Sheets.Count
                toc = []
                for s_i in range(1, p_count + 1):
                    sh = wb.Sheets(s_i)
                    r_count = 0
                    try:
                        r_count = sh.UsedRange.Rows.Count
                    except Exception:
                        pass
                    toc.append(f"{sh.Name} ({r_count} rows)")
                return {
                    "status": "ok",
                    "src": wb.Name if wb else src_name,
                    "mode": mode,
                    "ext": ext,
                    "page_count": p_count,
                    "toc": toc,
                    "sections": toc
                }
        except Exception:
            pass
        finally:
            if wb and need_quit:
                try: wb.Close(False)
                except Exception: pass
            if app and need_quit:
                try: app.Quit()
                except Exception: pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

    if ext == "pptx":
        app = None
        prs = None
        need_quit = False
        guard_pid = None
        try:
            if is_active:
                app, prs = find_active_ppt_presentation(clean_target)
                if not prs and app and app.Presentations.Count > 0:
                    prs = app.ActivePresentation
            else:
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("PowerPoint.Application", "POWERPNT.EXE")
                prs = app.Presentations.Open(abs_path, ReadOnly=True, Untitled=False, WithWindow=False)
                need_quit = True

            if prs:
                p_count = prs.Slides.Count
                toc = []
                for s_i in range(1, p_count + 1):
                    s = prs.Slides(s_i)
                    title = f"Slide {s_i}"
                    try:
                        if s.Shapes.HasTitle and s.Shapes.Title.TextFrame.HasText:
                            t_txt = s.Shapes.Title.TextFrame.TextRange.Text.strip()
                            if t_txt:
                                title = t_txt
                    except Exception:
                        pass
                    toc.append(title)
                return {
                    "status": "ok",
                    "src": prs.Name if prs else src_name,
                    "mode": mode,
                    "ext": ext,
                    "page_count": p_count,
                    "toc": toc[:20],
                    "sections": toc[:20]
                }
        except Exception:
            pass
        finally:
            if prs and need_quit:
                try: prs.Close()
                except Exception: pass
            if app and need_quit:
                try: app.Quit()
                except Exception: pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

    if ext == "docx":
        app = None
        doc = None
        need_quit = False
        guard_pid = None
        try:
            if is_active:
                app, doc = find_active_word_document(clean_target)
                if not doc and app and app.Documents.Count > 0:
                    doc = app.ActiveDocument
            else:
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Word.Application", "WINWORD.EXE")
                app.Visible = False
                app.DisplayAlerts = 0
                doc = app.Documents.Open(abs_path, ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False, PasswordDocument="")
                need_quit = True

            if doc:
                p_count = 1
                try:
                    p_count = doc.ComputeStatistics(2)
                except Exception:
                    pass
                toc = []
                for p in doc.Paragraphs:
                    try:
                        st = str(p.Style).lower()
                        if "heading" in st or "제목" in st:
                            txt = p.Range.Text.replace("\r", "").replace("\x07", "").strip()
                            if txt and txt not in toc:
                                toc.append(txt)
                                if len(toc) >= 20:
                                    break
                    except Exception:
                        pass
                return {
                    "status": "ok",
                    "src": doc.Name if doc else src_name,
                    "mode": mode,
                    "ext": ext,
                    "page_count": p_count,
                    "toc": toc,
                    "sections": toc
                }
        except Exception:
            pass
        finally:
            if doc and need_quit:
                try: doc.Close(False)
                except Exception: pass
            if app and need_quit:
                try: app.Quit()
                except Exception: pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

    records = parse_document(clean_target, is_active=is_active)
    pages = set(r.get("page") for r in records if r.get("page") is not None)
    sections = []
    for r in records:
        sec = r.get("section")
        if sec and sec not in sections:
            sections.append(sec)
    return {
        "status": "ok",
        "src": src_name,
        "mode": mode,
        "ext": ext,
        "page_count": max(pages) if pages else 1,
        "total_records": len(records),
        "toc": sections[:20],
        "sections": sections[:20]
    }


TOOL_RECIPES = {
    "excel": """================================================================================
 [Excel (엑셀) 세부 도구 선택 메뉴]
================================================================================
  1. 표 데이터 주입 / 차트 생성 : cli_office excel write --help
  2. 셀 범위 이동/복사/지우기   : cli_office excel range --help
  3. 시트 관리 (추가/복제/삭제)  : cli_office excel sheet --help
  4. 셀 배경색 / 글자 서식 강조 : cli_office excel style --help
  5. 엑셀을 CSV 또는 PDF로 저장 : cli_office excel export --help
================================================================================
 [대표 원라이너 레시피]
  • 표 주입 (C:\\cli_temp\\data\\input.jsonl 작성 후):
    cli_office --from "C:\\cli_temp\\data\\input.jsonl" --to excel --active-to
  • 다중 서식 지정 (C:\\cli_temp\\data\\styles.json 작성 후):
    cli_office --to excel --active --replace-map "C:\\cli_temp\\data\\styles.json"
  • 시트 추가:
    cli_office --sheet-action add --sheet-name "2026_상반기" --to excel
""",
    "excel_write": """================================================================================
 [Excel 세부 도구: Write (표 데이터 주입 및 차트 생성)]
================================================================================
  • 표준 표 데이터 주입:
    cli_office --from "C:\\cli_temp\\data\\input.jsonl" --to excel --active-to
  • 특정 시트(Sheet2) 초기화 후 표 주입:
    cli_office --from "C:\\cli_temp\\data\\input.jsonl" --to excel --active-to --pages "Sheet2" --clear
  • 표 주입과 동시에 차트 생성:
    cli_office --from "C:\\cli_temp\\data\\input.jsonl" --to excel --active-to --chart column --chart-title "실적"
""",
    "excel_range": """================================================================================
 [Excel 세부 도구: Range (셀 범위 이동, 복사, 지우기)]
================================================================================
  • 범위 이동 (Cut & Paste):
    cli_office --range-action move --range "A9:C16" --dest "Sheet3!A1" --to excel
  • 범위 복사 (Copy & Paste):
    cli_office --range-action copy --range "Sheet1!A1:D20" --dest "Sheet2!A1" --to excel
  • 범위 비우기 (Clear):
    cli_office --range-action clear --range "A9:C16" --to excel
""",
    "excel_sheet": """================================================================================
 [Excel 세부 도구: Sheet (시트 추가, 복제, 이름변경, 삭제)]
================================================================================
  • 새 시트 추가: cli_office --sheet-action add --sheet-name "새시트" --to excel
  • 시트 복제:    cli_office --sheet-action copy --sheet-name "양식" --new-name "복사본" --to excel
  • 이름 변경:    cli_office --sheet-action rename --sheet-name "Sheet1" --new-name "요약" --to excel
  • 시트 삭제:    cli_office --sheet-action delete --sheet-name "임시" --to excel
""",
    "excel_style": """================================================================================
 [Excel 세부 도구: Style (셀 배경색 및 글자 서식 지정)]
================================================================================
  • 다중 셀 서식 일괄 적용 (권장):
    cli_office --to excel --active --replace-map "C:\\cli_temp\\data\\styles.json"
  • 단일 셀 서식 적용:
    cli_office --to excel --active --find "합계" --style "bg:yellow; color:black; bold:true"
""",
    "word": """================================================================================
 [Word (워드) 세부 도구 메뉴]
================================================================================
  • 마크다운 표/텍스트 쓰기:
    cli_office --to word --active --data "| 품목 | 수량 |\\n| 사과 | 10 |"
  • 다중 단어 치환 및 서식:
    cli_office --to word --active --replace-map "C:\\cli_temp\\data\\styles.json"
  • 단일 단어 치환 및 강조:
    cli_office --to word --active --find "[미정]" --replace "확정" --style "color:blue; bold:true"
""",
    "word_write": """================================================================================
 [Word 세부 도구: Write (텍스트 및 마크다운 표 쓰기)]
================================================================================
  • 마크다운 표 쓰기: cli_office --to word --active --data "| 품목 | 수량 |\\n| 사과 | 10 |"
  • 초기화 후 쓰기:   cli_office --to word --active --clear --data "새로운 보고서 내용"
  • 앵커 위치 삽입:   cli_office --to word --active --data "추가 내용" --anchor "[붙임]" --pos before
""",
    "word_style": """================================================================================
 [Word 세부 도구: Style (단어 제자리 치환 및 글자 서식)]
================================================================================
  • 일괄 치환/서식: cli_office --to word --active --replace-map "C:\\cli_temp\\data\\styles.json"
  • 단일 치환/서식: cli_office --to word --active --find "[미정]" --replace "확정" --style "color:blue; bold:true"
""",
    "ppt": """================================================================================
 [PowerPoint (파워포인트) 세부 도구 메뉴]
================================================================================
  • 슬라이드별 단어 강조:
    cli_office --to ppt --active --pages 2 --find "Category" --style "color:red; bold:true"
  • 다중 일괄 치환/서식:
    cli_office --to ppt --active --replace-map "C:\\cli_temp\\data\\styles.json"
""",
    "pdf": """================================================================================
 [문서 도구: PDF 파일] 고속 요약, 본문 읽기, 키워드 검색
================================================================================
  • 0.1초 요약:      cli_office --info "문서.pdf"
  • 하이브리드 검색: cli_office --from "문서.pdf" --search "예산 편성" --top 10
  • 페이지 추출:     cli_office --from "문서.pdf" --pages "1-3"
""",
    "hwp": """================================================================================
 [문서 도구: 한글 (HWP / HWPX 파일)] 고속 요약, 본문 읽기, 키워드 검색
================================================================================
  • 요약 확인:       cli_office --info "기안서.hwp"
  • 하이브리드 검색: cli_office --from "기안서.hwp" --search "추진 일정" --top 10
  • 워드로 전송:     cli_office --from "기안서.hwp" --search "예산" --to word --active-to
""",
    "window": """================================================================================
 [공통 도구: Window (창 탐색 및 포커스)]
================================================================================
  • 열린 창 목록: cli_office --list-active
  • 창 포커스:    cli_office --focus --to excel
""",
    "export": """================================================================================
 [공통 도구: Export (PDF 및 CSV 내보내기)]
================================================================================
  • Word -> PDF:  cli_office --export "보고서.pdf" --from word --active
  • Excel -> CSV: cli_office --export "데이터.csv" --from excel --active
""",
    "clean": """================================================================================
 [공통 도구: Clean / Undo (작업 되돌리기 및 복구)]
================================================================================
  • 직전 작업 취소: cli_office --undo
  • 캐시/백업 정리: cli_office --clean all
  • 오피스 복구:    cli_office --fix-env
"""
}

MAIN_MENU_HELP = """================================================================================
 CLI Office 프로그램별 & 도구별 맞춤 헬프 메뉴판
================================================================================
  1. Excel (표 주입, 시트 관리, 셀 배경색, 차트) : cli_office excel --help
  2. Word  (텍스트 쓰기, 마크다운 표, 단어 치환)  : cli_office word --help
  3. PPT   (슬라이드별 치환, 다국어 매핑, 서식)  : cli_office ppt --help
  4. PDF 파일 전용 (요약, 읽기, 키워드 검색)     : cli_office pdf --help
  5. 한글 (HWP/HWPX) 전용 (요약, 읽기, 검색)    : cli_office hwp --help
  6. 활성 창 탐색 / 화면 맨 앞으로 띄우기        : cli_office window --help
  7. PDF / CSV 원클릭 내보내기                  : cli_office export --help
  8. 작업 되돌리기(Undo) 및 캐시/좀비 정리       : cli_office clean --help
================================================================================
"""


def handle_targeted_help() -> bool:
    """
    도구별 맞춤형 레시피 헬프 인터셉트.
    [중요 수정] '--undo excel'이나 '--info word' 같은 실제 실행 플래그가 있을 때는
    절대 헬프로 가로채지 않고 정상 실행되도록 보장합니다.
    """
    args = sys.argv[1:]

    if not args or args in (["--help"], ["-h"], ["help"], ["/?"]):
        print(MAIN_MENU_HELP)
        sys.exit(0)

    is_help_requested = any(h in args for h in ["--help", "-h", "help", "/?"])
    has_action_flags = any(a.startswith("-") and a not in ("--help", "-h", "/?") for a in args)

    # 실제 실행 옵션(--to, --from, --undo, --info 등)이 있고 --help 요청이 없다면 즉시 통과!
    if has_action_flags and not is_help_requested:
        return False

    clean_tokens = [a.lower().strip() for a in args if not a.startswith("-") and a not in ("help", "/?")]
    if not clean_tokens:
        if is_help_requested:
            print(MAIN_MENU_HELP)
            sys.exit(0)
        return False

    # --help가 명시적으로 요청되었거나, 플래그 없이 순수 토픽 단어(예: cli_office excel sheet)만 입력된 경우
    if is_help_requested or not has_action_flags:
        token_set = set(clean_tokens)

        if "excel" in token_set or "엑셀" in token_set:
            if any(t in token_set for t in ["range", "move", "cut", "범위", "이동"]):
                print(TOOL_RECIPES["excel_range"])
            elif any(t in token_set for t in ["write", "table", "data", "chart", "표", "쓰기"]):
                print(TOOL_RECIPES["excel_write"])
            elif any(t in token_set for t in ["sheet", "sheets", "시트"]):
                print(TOOL_RECIPES["excel_sheet"])
            elif any(t in token_set for t in ["style", "format", "find", "replace", "서식", "배경"]):
                print(TOOL_RECIPES["excel_style"])
            elif any(t in token_set for t in ["export", "csv", "pdf", "내보내기"]):
                print(TOOL_RECIPES["export"])
            else:
                print(TOOL_RECIPES["excel"])
            sys.exit(0)

        if "word" in token_set or "워드" in token_set or "doc" in token_set or "docx" in token_set:
            if any(t in token_set for t in ["write", "table", "data", "표", "쓰기"]):
                print(TOOL_RECIPES["word_write"])
            elif any(t in token_set for t in ["style", "format", "find", "replace", "서식"]):
                print(TOOL_RECIPES["word_style"])
            elif any(t in token_set for t in ["export", "pdf", "내보내기"]):
                print(TOOL_RECIPES["export"])
            else:
                print(TOOL_RECIPES["word"])
            sys.exit(0)

        if any(t in token_set for t in ["ppt", "pptx", "파포", "피피티", "powerpoint"]):
            if any(t in token_set for t in ["export", "pdf", "내보내기"]):
                print(TOOL_RECIPES["export"])
            else:
                print(TOOL_RECIPES["ppt"])
            sys.exit(0)

        if any(t in token_set for t in ["pdf", "피디에프"]):
            print(TOOL_RECIPES["pdf"])
            sys.exit(0)

        if any(t in token_set for t in ["hwp", "hwpx", "한글", "아래아한글"]):
            print(TOOL_RECIPES["hwp"])
            sys.exit(0)

        if any(t in token_set for t in ["window", "win", "focus", "active", "창"]):
            print(TOOL_RECIPES["window"])
            sys.exit(0)
        if any(t in token_set for t in ["export", "csv", "내보내기", "변환"]):
            print(TOOL_RECIPES["export"])
            sys.exit(0)
        if any(t in token_set for t in ["clean", "undo", "backup", "cache", "fix", "되돌리기", "복원"]):
            print(TOOL_RECIPES["clean"])
            sys.exit(0)
        if any(t in token_set for t in ["sheet", "sheets", "시트"]):
            print(TOOL_RECIPES["excel_sheet"])
            sys.exit(0)

        if is_help_requested:
            print(MAIN_MENU_HELP)
            sys.exit(0)

    return False


def main():
    handle_targeted_help()

    parser = argparse.ArgumentParser(
        prog="cli_office",
        description="CLI Office: Gemma 4 에이전트 친화적 고성능 윈도우 오피스 자동화 & 하이브리드 검색 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--from", "--file", dest="from_path", help="읽을 원본 파일(문서, CSV, JSONL) 또는 활성 창 앱 ('word', 'excel', 'ppt')")
    parser.add_argument("--to", "--target", dest="to_path", help="기록/복원 대상 파일 경로 또는 활성 창 앱 ('word', 'excel', 'ppt')")
    parser.add_argument("--search", help="문서 내 검색할 키워드 또는 정규식")
    parser.add_argument("--data", "--text", dest="data", help="기록할 내용 (단순 텍스트/마크다운 표)")
    parser.add_argument("--anchor", help="기록 위치 기준 키워드 (생략 시 문서 끝 추가)")
    parser.add_argument("--pos", default="after", choices=["before", "after", "replace"], help="앵커 기준 삽입 위치")
    parser.add_argument("--top", type=int, default=None, help="상위 N개 레코드 제한")
    parser.add_argument("--pages", help="추출/기록할 페이지 또는 시트/슬라이드 범위 (예: '1-3', 'Sheet2')")
    parser.add_argument("--from-pages", help="원본(--from)에서만 읽을 페이지 또는 시트 이름 지정")
    parser.add_argument("--prefix", help="각 출력/기록 레코드 앞단에 붙일 접두사")
    parser.add_argument("--clear", action="store_true", help="기록 전 대상 문서/활성 창의 기존 내용 전체 삭제")
    parser.add_argument("--no-backup", action="store_true", help="쓰기 작업 전 자동 백업 비활성화")
    parser.add_argument("--chart", help="엑셀 전용 차트 자동 생성 ('line', 'column', 'bar', 'pie' 등)")
    parser.add_argument("--chart-title", help="생성할 엑셀 차트 상단 제목")
    parser.add_argument("--extract-images", action="store_true", help="PDF 등 문서 내 이미지 추출 활성화")

    parser.add_argument("--find", help="제자리(In-Place) 문자열 검색/치환/서식 변경 시 찾을 텍스트")
    parser.add_argument("--replace", help="--find로 찾은 텍스트를 대체할 새 문자열")
    parser.add_argument("--style", help="--find로 찾은 텍스트에 적용할 서식 (예: 'bg:yellow; color:red; bold:true')")
    parser.add_argument("--replace-map", help="제자리 일괄 치환 및 서식 지정을 위한 JSON 파일 경로 또는 JSON 문자열")

    parser.add_argument("--active", action="store_true", help="원본 및 대상 모두 현재 화면의 활성 오피스 창으로 강제 지정")
    parser.add_argument("--active-from", action="store_true", help="원본(--from)만 활성 창 모드로 강제 지정")
    parser.add_argument("--active-to", action="store_true", help="대상(--to)만 활성 창 모드로 강제 지정")

    parser.add_argument("--info", help="문서 메타데이터(쪽수, 시트/슬라이드 목록, 목차) 0.1초 요약 조회")
    parser.add_argument("--export", help="열려 있는 문서나 대상 파일을 PDF, CSV 등 지정 경로로 내보내기")
    parser.add_argument("--range-action", choices=["move", "cut", "copy", "clear"], help="Excel 네이티브 셀 범위 이동/복사/지우기")
    parser.add_argument("--range", help="--range-action 수행 대상 셀 범위 (예: 'A9:C16' 또는 'Sheet1!A9:C16')")
    parser.add_argument("--dest", help="--range-action move/copy 시 대상 위치 (예: 'Sheet3!A1')")
    parser.add_argument("--sheet-action", choices=["add", "copy", "rename", "delete"], help="Excel 시트 조작")
    parser.add_argument("--sheet-name", help="--sheet-action 수행 시 대상 시트 이름")
    parser.add_argument("--new-name", help="--sheet-action rename 또는 copy 시 지정할 새 시트 이름")
    parser.add_argument("--focus", action="store_true", help="지정된 오피스 창을 화면 최상위 포그라운드로 활성화")
    parser.add_argument("--clean", nargs="?", const="all", choices=["cache", "backup", "all"], help="임시 캐시 및 백업 정리")
    parser.add_argument("--undo", nargs="?", const="__LATEST__", help="이전 상태로 복원")
    parser.add_argument("--snapshot", help="특정 백업 스냅샷 ID를 지정하여 복원")
    parser.add_argument("--backup-list", action="store_true", help="생성된 백업 스냅샷 목록 확인")
    parser.add_argument("--backup-clean", action="store_true", help="백업 스냅샷 정리")
    parser.add_argument("--keep", type=int, default=0, help="--backup-clean 실행 시 보존할 최근 백업 개수")
    parser.add_argument("--cache-status", action="store_true", help="로컬 캐시 사용량 조회")
    parser.add_argument("--cache-clean", action="store_true", help="로컬 캐시 전체 정리")
    parser.add_argument("--fix-env", action="store_true", help="오피스 좀비 프로세스 및 임시 파일 정리")
    parser.add_argument("--list-active", action="store_true", help="현재 실행 중인 모든 MS Office 활성 창 목록 조회")

    args = parser.parse_args()

    try:
        if args.focus:
            f_target = args.to_path or args.from_path or (args.undo if args.undo and args.undo != "__LATEST__" else None) or "excel"
            res = focus_office_window(f_target)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return

        if args.clean:
            clean_mode = args.clean.lower()
            res_clean = {"status": "ok", "action": "clean", "target": clean_mode}
            if clean_mode in ["cache", "all"]:
                res_clean["cache"] = CacheManager().clean()
            if clean_mode in ["backup", "all"]:
                res_clean["backup"] = BackupManager().clean(keep_latest=args.keep)
            print(json.dumps(res_clean, ensure_ascii=False, indent=2))
            return

        if args.range_action:
            if not args.range:
                print(json.dumps({"status": "error", "message": "--range-action 실행 시 --range (예: 'A9:C16')가 필요합니다."}, ensure_ascii=False))
                return
            r_target = args.to_path or args.from_path or "excel"
            if not args.no_backup:
                try:
                    BackupManager().backup_target(r_target, is_active=True)
                except Exception:
                    pass
            res = manage_excel_range(
                target=r_target,
                action=args.range_action,
                range_str=args.range,
                dest_str=args.dest,
                is_active=True
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return

        if args.sheet_action:
            sh_target = args.to_path or args.from_path or "excel"
            if not args.no_backup and args.sheet_action in ["delete", "rename"]:
                try:
                    BackupManager().backup_target(sh_target, is_active=True)
                except Exception:
                    pass
            res = manage_excel_sheet(
                target=sh_target,
                action=args.sheet_action,
                sheet_name=args.sheet_name or args.pages,
                new_name=args.new_name,
                is_active=True
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return

        if args.export:
            exp_src = args.from_path or args.to_path or "word"
            is_exp_act = bool(args.active or args.active_from or is_active_target(exp_src, is_write=False, explicit_flag=bool(args.active or args.active_from)))
            res = export_document(
                src_target=exp_src,
                export_path=args.export,
                is_active=is_exp_act,
                pages=args.from_pages or args.pages
            )
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return

        if args.fix_env:
            fix_res = fix_office_environment(kill_hidden_only=True)
            print(json.dumps(fix_res, ensure_ascii=False, indent=2))
            return

        if args.list_active:
            active_windows = list_active_office_windows()
            print(json.dumps(active_windows, ensure_ascii=False, indent=2))
            return

        if args.cache_status:
            print(json.dumps(CacheManager().status(), ensure_ascii=False, indent=2))
            return

        if args.cache_clean:
            print(json.dumps(CacheManager().clean(), ensure_ascii=False, indent=2))
            return

        if args.backup_list:
            print(json.dumps(BackupManager().list_backups(), ensure_ascii=False, indent=2))
            return

        if args.backup_clean:
            print(json.dumps(BackupManager().clean(keep_latest=args.keep), ensure_ascii=False, indent=2))
            return

        if args.undo is not None or args.snapshot:
            bm = BackupManager()
            target_val = None
            if args.undo and args.undo != "__LATEST__":
                target_val = args.undo
            elif args.to_path:
                target_val = args.to_path
            res = bm.restore(target=target_val, snapshot_id=args.snapshot)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return

        if args.info:
            is_act = bool(args.active or args.active_from or is_active_target(args.info, is_write=False, explicit_flag=bool(args.active or args.active_from)))
            info_res = get_document_info(args.info, is_active=is_act)
            print(json.dumps(info_res, ensure_ascii=False, indent=2))
            return

        target_pages = None
        target_page_src = args.from_pages if (args.from_pages and args.to_path) else args.pages
        if target_page_src:
            target_pages = set()
            for part in target_page_src.split(","):
                part = part.strip()
                if "-" in part and not any(c.isalpha() for c in part):
                    sp, ep = part.split("-", 1)
                    if sp.strip().isdigit() and ep.strip().isdigit():
                        target_pages.update(range(int(sp), int(ep) + 1))
                elif part.isdigit():
                    target_pages.add(int(part))
                elif part:
                    target_pages.add(part)

        # --from이 로컬에 존재하는 파일(.jsonl 등)일 때는 --active 플래그가 켜져 있어도 파일로 읽도록 보호
        from_exists_on_disk = bool(args.from_path and os.path.exists(args.from_path))
        is_src_active = False if from_exists_on_disk else bool(args.active or args.active_from or is_active_target(args.from_path, is_write=False, explicit_flag=bool(args.active or args.active_from)))
        is_tgt_active = bool(args.active or args.active_to or is_active_target(args.to_path, is_write=True, explicit_flag=bool(args.active or args.active_to)))

        replace_map = None
        if args.find or args.replace_map or args.style:
            replace_map = {}
            if args.find:
                style_dict = parse_style_string(args.style)
                item_spec = {}
                if args.replace is not None:
                    item_spec["text"] = args.replace
                if style_dict:
                    item_spec.update(style_dict)
                replace_map[args.find] = item_spec if item_spec else {"text": args.find}
            if args.replace_map:
                try:
                    if os.path.exists(args.replace_map):
                        with open(args.replace_map, "r", encoding="utf-8-sig") as f:
                            file_map = json.load(f)
                            if isinstance(file_map, dict):
                                replace_map.update(file_map)
                    else:
                        json_map = json.loads(args.replace_map)
                        if isinstance(json_map, dict):
                            replace_map.update(json_map)
                except Exception as e:
                    raise ValueError(f"--replace-map JSON 파싱 실패: {e}")

        records = []

        if args.from_path:
            parse_pages = target_pages if (not args.to_path or args.from_pages) else None
            records = parse_document(
                args.from_path,
                is_active=is_src_active,
                extract_images=args.extract_images,
                target_pages=parse_pages
            )
            if args.search:
                top_k = args.top if args.top is not None else 30
                records = HybridSearcher.search(records, args.search, top_k=top_k)
            elif args.top is not None and args.top > 0:
                records = records[:args.top]

        if args.data:
            data_records = parse_smart_data(args.data)
            records.extend(data_records)

        if args.prefix and records:
            for r in records:
                if r.get("type") == "image":
                    continue
                data = r.get("data", "")
                if isinstance(data, list):
                    r["data"] = [f"{args.prefix} {c}" if i == 0 else c for i, c in enumerate(data)]
                else:
                    r["data"] = f"{args.prefix} {data}"

        target_path = args.to_path
        if not target_path and replace_map:
            if args.from_path and not from_exists_on_disk:
                target_path = args.from_path
                is_tgt_active = is_src_active or bool(args.active or args.active_to)
            elif args.active:
                detected_target = None
                try:
                    e_apps = get_all_active_excel_apps()
                    if e_apps and e_apps[0].Workbooks.Count > 0:
                        detected_target = "excel"
                except Exception:
                    pass
                if not detected_target and win32com:
                    try:
                        w_app = win32com.client.GetActiveObject("Word.Application")
                        if w_app and w_app.Documents.Count > 0:
                            detected_target = "word"
                    except Exception:
                        pass
                if not detected_target and win32com:
                    try:
                        p_app = win32com.client.GetActiveObject("PowerPoint.Application")
                        if p_app and p_app.Presentations.Count > 0:
                            detected_target = "ppt"
                    except Exception:
                        pass
                target_path = detected_target or "excel"
                is_tgt_active = True

        if target_path:
            if not records and not args.clear and not replace_map:
                raise ValueError("기록할 데이터가 없습니다. (--from 검색 결과가 없거나 --data가 비어 있습니다)")

            res = OfficeWriter.write_to_target(
                target=target_path,
                is_active=is_tgt_active,
                records=records,
                anchor=args.anchor,
                pos=args.pos,
                clear=args.clear,
                auto_backup=not args.no_backup,
                chart=args.chart,
                chart_title=args.chart_title,
                pages=args.pages,
                replace_map=replace_map
            )
            print(json.dumps(res, ensure_ascii=False))
        else:
            if not args.from_path and not args.data and not args.clear:
                print(MAIN_MENU_HELP)
                return
            for r in records:
                print(json.dumps(r, ensure_ascii=False))

        check_storage_quota_warning(limit_mb=300.0)

    except Exception as e:
        err_msg = str(e)
        err_type = type(e).__name__
        err_lower = err_msg.lower()

        recovery_hint = "명령어 파라미터를 확인하고 다시 시도하지 마십시오."
        suggested_command = None

        if any(sig in err_lower for sig in ["rejected", "busy", "0x8001010a", "0x80010001", "-2147417846"]):
            recovery_hint = "오피스 프로그램이 모달 대화상자(팝업)를 띄웠거나 셀 편집 상태입니다. cli_office --fix-env를 1회 실행하거나 사용자에게 알리십시오."
            suggested_command = "cli_office --fix-env"
        elif "permission" in err_lower or "access is denied" in err_lower or "used by another" in err_lower:
            recovery_hint = "대상 파일이 열려 있거나 잠겨 있습니다. --active 옵션을 사용하거나 cli_office --fix-env를 실행하십시오."
            suggested_command = "cli_office --fix-env"
        elif "찾을 수 없습니다" in err_msg or "not found" in err_lower:
            recovery_hint = "열려 있는 창 이름이나 파일 경로가 정확한지 'cli_office --list-active'로 확인하십시오."
            suggested_command = "cli_office --list-active"

        err_out = {
            "status": "error",
            "error": err_type,
            "message": err_msg,
            "recovery_hint": recovery_hint,
            "agent_directive": STOP_RETRY_DIRECTIVE
        }
        if suggested_command:
            err_out["suggested_command"] = suggested_command

        # OpenCode 등 에이전트 러너가 stdout만 캡처하는 경우를 대비해 stdout으로 에러 JSON 출력
        print(json.dumps(err_out, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()