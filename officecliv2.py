발견된 10가지 문제점을 모두 수정하고 문법 및 로직 검증을 마친 완성본 코드입니다.
주요 반영 내역
 * write 명령어 개선: --clear 사용 시에도 stdin이나 --text, --table, --file 입력이 정상적으로 이어서 기록되도록 조건문을 분리했고, CLI에서 표(--table, 2D JSON 배열)와 입력 파일(--file)을 직접 지정할 수 있도록 인자를 추가했습니다.
 * --no-backup 인자 연결: run과 write 서브파서에 --no-backup 플래그를 추가하여 auto_backup 파라미터와 연결했습니다.
 * 이미지 추출 및 캐시 일관성 확보:
   * parse_pdf에서 --extract-images 활성화 시 마크다운 이미지 구문(![...](...))에서 파일 경로를 파싱해 {"type": "image", "data": "절대경로"} 레코드로 반환하도록 수정했습니다.
   * parse_document에서 PDF뿐만 아니라 Word, Excel도 --extract-images 요청 시 기존 캐시에 이미지 레코드가 없으면 캐시를 우회하여 추출하도록 개선했습니다.
   * 이미지 추출이 없는 일반 읽기 시에는 텍스트/표 캐시만 깨끗하게 저장되도록 보호했습니다.
 * 포맷별 --anchor 및 --pos (before / after / replace) 정밀 구현:
   * Word: pos == "replace"일 때 sel.Delete()를 선행 호출하여 텍스트뿐만 아니라 표나 이미지가 삽입될 때도 기존 앵커 텍스트가 깔끔하게 교체되도록 수정했습니다.
   * Excel: pos == "before"일 때 기존 행을 덮어쓰지 않고 필요한 행만큼 Rows.Insert()로 밀어낸 뒤 삽입하며, 단일 값 replace 시 해당 앵커 셀 위치에 정확히 덮어쓰도록 개선했습니다.
   * PPT: 앵커가 포함된 도형(anchor_shape)의 Top 좌표를 추적하여, replace(기존 앵커 텍스트 교체 또는 도형 삭제 후 그 자리에 배치)와 before(앵커 도형 위치에 삽입 후 아래 도형들을 자동 Shift)가 동작하도록 구현했습니다.
   * MD/TXT: _write_md_txt에 clear 파라미터를 연결했습니다.
 * 다중 엑셀 인스턴스 백업 및 복원 일치화: BackupManager에서도 get_all_active_excel_apps()를 사용하여 특정 워크북 이름(Book1.xlsx 등)으로 지정된 활성 엑셀 창을 정확히 찾아 백업 및 복원하도록 통일했습니다.
완성된 officecli.py 전체 코드
# -*- coding: utf-8 -*-
"""
================================================================================
OfficeCLI: 윈도우 11 AI 에이전트 친화적 고성능 오피스 자동화 & 하이브리드 검색 CLI
================================================================================
지원 포맷: Word (.docx, .doc), Excel (.xlsx, .xls, .xlsm, .csv),
          PPT (.pptx, .ppt), HWP (.hwp, .hwpx), PDF (.pdf), Markdown (.md), Text (.txt)
핵심 기능:
1. DispatchEx + PID 스냅샷 기반 백그라운드 완전 격리 읽기 (작업 중인 오피스 창 간섭 0%)
2. 실제 인쇄 쪽번호(wdActiveEndPageNumber) 및 문단-표 실제 순서 100% 보장
3. 셀 병합(Merged Cells) 2D 정규화 & Forward-Fill 값 보존 + CSV 전용 파싱(UTF-8/CP949)
4. PPT 중첩 그룹 도형 재귀 언패킹 & (Top, Left) 시각적 순서 정렬 (도형 형상 제외 텍스트만 추출)
5. PDF pymupdf4llm 초고속 추출 (기본 이미지 배제, --extract-images 시 캐시 우회 및 이미지 레코드 생성)
6. .officecli_cache MD5 기반 JSONL 캐싱 및 300MB 용량 임계치 자동 감지 알림
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
    if sys.stdin and hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
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


# ==============================================================================
# 4. 백그라운드 COM 좀비 프로세스 가드 (ComProcessGuard)
#    - Win32 Job Object 바인딩 (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
#    - Toolhelp32Snapshot 기반 DispatchEx 전후 신규 PID 자동 감지
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
        """현재 실행 중인 특정 실행 파일명의 PID 목록을 스냅샷으로 조회"""
        pids = set()
        if sys.platform != "win32":
            return pids
        try:
            kernel32 = ctypes.windll.kernel32
            h_snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
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
                h_proc = kernel32.OpenProcess(0x0001 | 0x0800, False, pid)  # TERMINATE | SET_QUOTA
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
        """DispatchEx 실행 전후 PID를 스냅샷 비교하여 Hwnd 유무와 무관하게 100% Job Object에 등록"""
        cls.init()
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
def com_safe(max_retries: int = 5, initial_delay: float = 0.2):
    """COM 호출 중 RPC_E_CALL_REJECTED(0x8001010A) 등 발생 시 지수 백오프 자동 재시도"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_err = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    is_rejected = (
                        "-2147417846" in err_str
                        or "0x8001010a" in err_str
                        or "rejected" in err_str
                        or "busy" in err_str
                    )
                    if is_rejected and attempt < max_retries - 1:
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
    # 정수 판별 (음수 포함, 단 '007' 같은 선행 0 문자열은 제외)
    if re.match(r"^-?(?:0|[1-9]\d*)$", s):
        try:
            num = int(s)
            # Excel 정밀도 한계(15자리) 초과 시 텍스트 유지 (사번/바코드 손실 방지)
            if abs(num) < 10**15:
                return num
        except ValueError:
            pass
    # 실수 판별 (예: 3.14, -0.5)
    if re.match(r"^-?(?:0|[1-9]\d*)\.\d+$", s):
        try:
            return float(s)
        except ValueError:
            pass
    return s


def get_dir_size_bytes(dir_path: Path) -> int:
    """디렉터리 내 모든 파일의 총 크기(Byte) 계산"""
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


def check_storage_quota_warning(limit_mb: float = 300.0):
    """
    캐시(.officecli_cache) 및 백업(.officecli_backup) 폴더의 용량이
    지정된 임계치(기본 300MB)를 초과하면 stderr로 경고 알림을 출력.
    (stdout JSONL 파이프라인을 오염시키지 않도록 stderr 사용)
    """
    cache_dir = Path(".officecli_cache").resolve()
    backup_dir = Path(".officecli_backup").resolve()

    cache_bytes = get_dir_size_bytes(cache_dir)
    backup_bytes = get_dir_size_bytes(backup_dir)
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
                f"[알림] 로컬 캐시/백업 용량이 {limit_mb:.0f}MB를 초과했습니다 "
                f"(캐시: {cache_mb}MB, 백업: {backup_mb}MB, 합계: {total_mb}MB). "
                f"'python officecli.py cache clean' 또는 'python officecli.py backup clean' 명령으로 정리하세요."
            )
        }
        print(json.dumps(alert_msg, ensure_ascii=False), file=sys.stderr)


def ensure_window_visible(hwnd: int, default_x: int = 100, default_y: int = 100, width: int = 1100, height: int = 750):
    """
    윈도우 창이 화면에 정상적으로 표시되도록 보장:
    - 듀얼/다중 모니터 배치를 100% 존중하여 어떤 모니터에라도 걸쳐 있다면(MonitorFromWindow != NULL) 위치/크기 유지.
    - 최소화(Iconic) 상태인 경우에만 원래 위치로 복원.
    - 실제 어떤 모니터에도 걸쳐있지 않은 완전 오프스크린(유령 창)인 경우에만 안전 영역으로 이동.
    """
    if not hwnd or not win32com:
        return
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd):
        return

    is_iconic = bool(user32.IsIconic(hwnd))
    if is_iconic:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE

    h_monitor = user32.MonitorFromWindow(hwnd, 0)  # 0 = MONITOR_DEFAULTTONULL

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


def get_all_active_excel_apps() -> List[Any]:
    """
    Windows에 실행 중인 모든 엑셀 인스턴스(별도 창/프로세스)의 Application COM 객체를 전수 수집.
    GetActiveObject가 1개만 잡는 한계를 극복하고, AccessibleObjectFromWindow로 모든 창 연결.
    """
    apps = []
    seen_hwnds = set()

    # 1. 표준 GetActiveObject
    try:
        app_std = win32com.client.GetActiveObject("Excel.Application")
        if app_std and getattr(app_std, "Hwnd", 0) not in seen_hwnds:
            apps.append(app_std)
            seen_hwnds.add(app_std.Hwnd)
    except Exception:
        pass

    # 2. 모든 XLMAIN 탑레벨 윈도우 전수 조사 (AccessibleObjectFromWindow)
    if sys.platform == "win32" and win32gui and pythoncom:
        sync_desktop_to_default()
        pythoncom.CoInitialize()
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
    """실행 중인 모든 Excel 인스턴스에서 대상 워크북(또는 기본 활성 워크북)을 탐색하여 (app, wb) 반환"""
    all_apps = get_all_active_excel_apps()
    app = None
    wb = None
    clean_name = (target_wb_name or "").strip()

    if clean_name and clean_name.lower() not in ["excel", "xls", "xlsx"]:
        for a in all_apps:
            try:
                for w in a.Workbooks:
                    if w.Name.lower() == clean_name.lower() or w.Name.lower() == f"{clean_name.lower()}.xlsx":
                        return a, w
            except Exception:
                pass

    if all_apps:
        app = all_apps[0]
    if not app and win32com:
        try:
            app = win32com.client.GetActiveObject("Excel.Application")
        except Exception:
            pass

    if app:
        try:
            if app.Workbooks.Count > 0:
                wb = app.ActiveWorkbook
        except Exception:
            pass

    return app, wb


# ==============================================================================
# 5. 캐시 매니저 (CacheManager)
# ==============================================================================
class CacheManager:
    """문서 파싱 결과를 로컬 JSONL로 캐싱하여 대용량 파일 재검색 속도 극대화 (0.01초 로드)"""
    def __init__(self, cache_dir: str = ".officecli_cache"):
        self.cache_dir = Path(cache_dir).resolve()
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
        """캐시 디렉터리 전체 비우기"""
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


# ==============================================================================
# 5-2. 백업 및 복원 매니저 (BackupManager)
# ==============================================================================
class BackupManager:
    """
    에이전트가 문서를 수정하거나 삭제하기 전 원본 상태를 자동 백업하고,
    언제든 이전 상태로 복구(Restore)할 수 있는 안전 매니저
    """
    def __init__(self, backup_dir: str = ".officecli_backup"):
        self.backup_dir = Path(backup_dir).resolve()
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
        """쓰기/초기화 작업 직전 원본 스냅샷 자동 생성"""
        sync_desktop_to_default()
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        norm_target = (target or "").strip().lower()

        # 1. 오프라인 파일 기반 백업 (전체 파일 복사)
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

        # 2. 실시간 활성 창 백업 (SaveCopyAs 또는 네이티브 스냅샷)
        manifest = self._load_manifest()
        safe_id_name = re.sub(r"[^a-zA-Z0-9가-힣_-]", "_", norm_target) or "active"
        entry_id = f"active_{safe_id_name}_{timestamp}"

        if norm_target in ["word", "doc", "docx"]:
            try:
                app = win32com.client.GetActiveObject("Word.Application")
                doc = app.ActiveDocument
                if doc:
                    backup_file = self.backup_dir / f"word_active_{timestamp}.docx"
                    doc.SaveCopyAs(str(backup_file))
                    entry = {
                        "id": entry_id,
                        "target": "word",
                        "type": "active_file",
                        "backup_path": str(backup_file),
                        "created_at": timestamp
                    }
                    manifest.append(entry)
                    self._save_manifest(manifest)
                    return entry_id
            except Exception:
                pass

        elif norm_target in ["ppt", "pptx", "powerpoint"]:
            try:
                app = win32com.client.GetActiveObject("PowerPoint.Application")
                prs = app.ActivePresentation
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
            # Excel 활성 창 또는 특정 워크북 이름(예: Book1, 매출현황.xlsx) 대상 백업
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
        """백업 파일 정리 (keep_latest > 0 이면 최근 N개만 남기고 삭제, 0이면 전체 삭제)"""
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
    def restore(self, target: str, snapshot_id: Optional[str] = None) -> Dict[str, Any]:
        """지정한 백업 스냅샷을 원본 파일 또는 활성 창에 복원"""
        manifest = self._load_manifest()
        norm_target = (target or "").lower()

        target_abs = os.path.abspath(target).lower() if target else ""
        target_base = Path(target).name.lower() if target else ""

        candidates = [e for e in manifest if snapshot_id and e.get("id") == snapshot_id]
        if not candidates:
            candidates = [
                e for e in manifest
                if (norm_target and norm_target in e.get("target", "").lower())
                or (norm_target and norm_target == e.get("app_type", "").lower())
                or (target_abs and target_abs == e.get("target", "").lower())
                or (target_base and target_base in Path(e.get("target", "")).name.lower())
                or (snapshot_id and snapshot_id in e.get("id", ""))
            ]
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
            return {"status": "ok", "action": "restored", "target": orig_target, "from": str(backup_path), "snapshot_id": latest_entry["id"]}

        if b_type == "active_file":
            norm_tgt = (orig_target or "").lower()
            restored_path = None
            if norm_tgt in ["word", "doc", "docx"]:
                try:
                    app = win32com.client.GetActiveObject("Word.Application")
                except Exception:
                    app = win32com.client.Dispatch("Word.Application")
                app.Visible = True
                orig_path = ""
                try:
                    if app.Documents.Count > 0 and app.ActiveDocument:
                        orig_path = app.ActiveDocument.FullName
                        app.ActiveDocument.Close(False)
                except Exception:
                    pass

                if orig_path and os.path.exists(orig_path):
                    shutil.copy2(backup_path, orig_path)
                    app.Documents.Open(orig_path)
                    restored_path = orig_path
                else:
                    app.Documents.Open(str(backup_path.resolve()))
                    restored_path = str(backup_path.resolve())

            elif norm_tgt in ["ppt", "pptx", "powerpoint"]:
                try:
                    app = win32com.client.GetActiveObject("PowerPoint.Application")
                except Exception:
                    app = win32com.client.Dispatch("PowerPoint.Application")
                app.Visible = True
                orig_path = ""
                try:
                    if app.Presentations.Count > 0 and app.ActivePresentation:
                        orig_path = app.ActivePresentation.FullName
                        app.ActivePresentation.Close()
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
                "snapshot_id": latest_entry["id"]
            }

        return {"status": "error", "message": "알 수 없는 백업 형식입니다."}


# 다단계 한국어 조사/어미 패턴 (길이 우선 정규화)
_KO_SUFFIX_PATTERNS = [
    r"(에서는|으로부터|에서부터|이라고|이라는|으로써|으로서|에게서|한테서|하다가|하도록|하였다|하셨다|했었다|습니다|합니다|입니다|스러운|스럽게|시키기|시키는|시켜서)",
    r"(에서|에게|한테|부터|까지|마저|조차|보다|처럼|으로|로써|로서|이라|라는|하고|하며|이고|이며|하여|하면|하게|하니|하는|하지|할수|있는|없는|됐다|된다|되면|되어|적인)",
    r"(은|는|이|가|을|를|의|에|로|와|과|도|만|뿐|한|할|된|될|해)"
]
_KO_SUFFIX_RES = [re.compile(p + r"$") for p in _KO_SUFFIX_PATTERNS]

def _strip_ko_stem(token: str) -> str:
    """한국어 단어에서 조사 및 용언 어미를 최대 3단계 반복 박리하여 순수 어간(Stem) 추출"""
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
    """
    무거운 외부 모델/형태소 분석기 없이 순수 파이썬 내장 모듈 기반 초경량 하이브리드 검색
    - 한국어 다단계 조사/용언 어미 박리 (최대 3회 반복)
    - 띄어쓰기 무관 완전 일치 가산점
    - 복합명사 2-gram 부분 매칭 & BM25 길이 정규화
    - 표 헤더(Row:1) 텍스트를 후속 데이터 행의 검색 컨텍스트로 바인딩
    """
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
    """
    7대 문서 포맷 초정밀 파서
    - PDF: pymupdf4llm (이미지 배제 기본, --extract-images 시 이미지 레코드 생성 및 표 2D 파싱)
    - Excel: dispatch_ex_guarded 백그라운드 격리, UsedRange.Value2 Bulk Read, 병합 Forward-Fill
    - CSV: 내장 csv 모듈 기반 2D 파싱 (UTF-8 및 CP949 인코딩 자동 폴백)
    - Word: dispatch_ex_guarded 백그라운드 격리, Range.Start 정렬 문단-표 실제 순서 보장, 병합 복원
    - PPT: dispatch_ex_guarded 백그라운드 격리, msoGroup 재귀 언패킹, (Top, Left) 정렬
    - HWP: 순수 파이썬(olefile/zipfile) 고속 추출 + 0x000B 표 제어문자 컨텍스트 감지
    - MD/TXT: 경량 정규식 기반 헤더 및 표 파싱
    """

    # --------------------------------------------------------------------------
    # 7-1. PDF 파서
    # --------------------------------------------------------------------------
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

                # 마크다운 이미지 구문 처리
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

        # 폴더에 저장되었으나 마크다운 링크로 잡히지 않은 잔여 이미지 보완 수집
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

    # --------------------------------------------------------------------------
    # 7-2. Excel 파서 (dispatch_ex_guarded 백그라운드 격리 또는 활성 창)
    # --------------------------------------------------------------------------
    @staticmethod
    @com_safe()
    def parse_excel(file_path: Optional[str] = None, is_active: bool = False, extract_images: bool = False, target_pages: Optional[Set[int]] = None) -> List[Dict[str, Any]]:
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
                    raise RuntimeError("현재 열려 있는 활성 엑셀 통합 문서가 없습니다. 엑셀 문서를 열어둔 뒤 다시 시도해 주세요.")
            else:
                abs_path = os.path.abspath(file_path)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Excel.Application", "EXCEL.EXE")
                app.Visible = False
                app.DisplayAlerts = False
                wb = app.Workbooks.Open(abs_path, ReadOnly=True)
                need_quit = True

            doc_name = wb.Name

            for sheet_idx in range(1, wb.Sheets.Count + 1):
                if target_pages and sheet_idx not in target_pages:
                    continue

                sheet = wb.Sheets(sheet_idx)
                sheet_name = sheet.Name
                used = sheet.UsedRange
                if not used or used.Rows.Count == 0:
                    continue

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

            # 차트 이미지 추출 (extract_images=True)
            if extract_images:
                stem = Path(doc_name).stem
                img_dir = Path(".officecli_cache") / f"{stem}_images"
                img_dir.mkdir(parents=True, exist_ok=True)
                for s_i in range(1, wb.Sheets.Count + 1):
                    if target_pages and s_i not in target_pages:
                        continue
                    sh = wb.Sheets(s_i)
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
                try:
                    wb.Close(False)
                except Exception:
                    pass
            if app and need_quit:
                try:
                    app.Quit()
                except Exception:
                    pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

        return records

    # --------------------------------------------------------------------------
    # 7-3. Word 파서 (문단-표 순서 100% 보장 & 1차원 셀 순회 병합 복원)
    # --------------------------------------------------------------------------
    @staticmethod
    @com_safe()
    def parse_word(file_path: Optional[str] = None, is_active: bool = False, extract_images: bool = False, target_pages: Optional[Set[int]] = None) -> List[Dict[str, Any]]:
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
                spawned = False
                try:
                    app = win32com.client.GetActiveObject("Word.Application")
                except Exception:
                    app = win32com.client.Dispatch("Word.Application")
                    spawned = True
                if not app or app.Documents.Count == 0:
                    if spawned and app:
                        try:
                            app.Quit()
                        except Exception:
                            pass
                    raise RuntimeError("현재 열려 있는 활성 워드 문서가 없습니다. 문서를 열어둔 뒤 다시 시도해 주세요.")
                doc = app.ActiveDocument
            else:
                abs_path = os.path.abspath(file_path)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Word.Application", "WINWORD.EXE")
                app.Visible = False
                app.DisplayAlerts = 0
                doc = app.Documents.Open(abs_path, ReadOnly=True)
                need_quit = True

            doc_name = doc.Name
            current_section = "General"

            table_items = []
            for t_idx, tbl in enumerate(doc.Tables, start=1):
                t_start = tbl.Range.Start
                t_end = tbl.Range.End
                tbl_page = 1
                try:
                    tbl_page = tbl.Range.Information(3)  # wdActiveEndPageNumber = 3
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
                    if p_range.Information(12):  # wdWithInTable = 12
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

            # Word 내 이미지 추출 (extract_images=True)
            if extract_images:
                try:
                    stem = Path(doc_name).stem
                    img_dir = Path(".officecli_cache") / f"{stem}_images"
                    img_dir.mkdir(parents=True, exist_ok=True)
                    temp_docx = None
                    docx_target = None
                    if is_active:
                        temp_docx = img_dir / f"_temp_{int(time.time() * 1000)}.docx"
                        temp_doc = None
                        try:
                            try:
                                temp_doc = app.Documents.Add(Visible=False)
                            except Exception:
                                temp_doc = app.Documents.Add()
                            doc.Range().Copy()
                            temp_doc.Range().Paste()
                            temp_doc.SaveAs(FileName=str(temp_docx.resolve()), FileFormat=16)
                            temp_doc.Close(False)
                            temp_doc = None
                            docx_target = temp_docx
                        except Exception:
                            if temp_doc:
                                try:
                                    temp_doc.Close(False)
                                except Exception:
                                    pass
                            if getattr(doc, "Path", None) and (Path(doc.Path) / doc.Name).exists():
                                docx_target = Path(doc.Path) / doc.Name
                    else:
                        docx_target = Path(abs_path)

                    if docx_target and docx_target.exists():
                        with zipfile.ZipFile(str(docx_target.resolve()), "r") as z:
                            media_files = [f for f in z.namelist() if f.startswith("word/media/")]
                            for m_idx, mf in enumerate(media_files, start=1):
                                ext_img = mf.split(".")[-1]
                                out_img_path = img_dir / f"img_{m_idx}.{ext_img}"
                                out_img_path.write_bytes(z.read(mf))
                                records.append({
                                    "id": item_id,
                                    "src": doc_name,
                                    "ext": "docx",
                                    "page": 1,
                                    "section": "Media",
                                    "coord": f"Image:{m_idx}",
                                    "type": "image",
                                    "data": str(out_img_path.resolve())
                                })
                                item_id += 1
                        if is_active and temp_docx and temp_docx.exists():
                            try:
                                temp_docx.unlink()
                            except Exception:
                                pass

                    # Fallback: active document InlineShapes direct capture
                    if is_active and not any(r.get("type") == "image" for r in records):
                        try:
                            for is_idx in range(1, doc.InlineShapes.Count + 1):
                                sh = doc.InlineShapes(is_idx)
                                sh.Select()
                                app.Selection.CopyAsPicture()
                                time.sleep(0.2)
                                from PIL import ImageGrab
                                img = ImageGrab.grabclipboard()
                                if img:
                                    out_img_path = img_dir / f"inlineshape_{is_idx}.png"
                                    img.save(str(out_img_path.resolve()), "PNG")
                                    records.append({
                                        "id": item_id,
                                        "src": doc_name,
                                        "ext": "docx",
                                        "page": 1,
                                        "section": "Media",
                                        "coord": f"InlineShape:{is_idx}",
                                        "type": "image",
                                        "data": str(out_img_path.resolve())
                                    })
                                    item_id += 1
                        except Exception:
                            pass
                except Exception:
                    pass

        finally:
            if doc and need_quit:
                try:
                    doc.Close(False)
                except Exception:
                    pass
            if app and need_quit:
                try:
                    app.Quit()
                except Exception:
                    pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

        return records

    # --------------------------------------------------------------------------
    # 7-4. PPT 파서 (그룹 도형 재귀 언패킹 & 형상 제외 순수 텍스트 추출 & Top/Left 정렬)
    # --------------------------------------------------------------------------
    @staticmethod
    @com_safe()
    def parse_ppt(file_path: Optional[str] = None, is_active: bool = False, target_pages: Optional[Set[int]] = None) -> List[Dict[str, Any]]:
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
                spawned = False
                try:
                    app = win32com.client.GetActiveObject("PowerPoint.Application")
                except Exception:
                    app = win32com.client.Dispatch("PowerPoint.Application")
                    spawned = True
                if not app or app.Presentations.Count == 0:
                    if spawned and app:
                        try:
                            app.Quit()
                        except Exception:
                            pass
                    raise RuntimeError("현재 열려 있는 활성 PPT 프레젠테이션이 없습니다. 프레젠테이션을 열어둔 뒤 다시 시도해 주세요.")
                prs = app.ActivePresentation
            else:
                abs_path = os.path.abspath(file_path)
                app, guard_pid = ComProcessGuard.dispatch_ex_guarded("PowerPoint.Application", "POWERPNT.EXE")
                prs = app.Presentations.Open(abs_path, ReadOnly=True, Untitled=False, WithWindow=False)
                need_quit = True

            doc_name = prs.Name

            def unpack_shapes(shapes_col) -> Generator[Any, None, None]:
                for shape in shapes_col:
                    try:
                        if shape.Type == 6:  # msoGroup = 6
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
                try:
                    prs.Close()
                except Exception:
                    pass
            if app and need_quit:
                try:
                    app.Quit()
                except Exception:
                    pass
            if guard_pid:
                ComProcessGuard.unregister(guard_pid)

        return records

    # --------------------------------------------------------------------------
    # 7-5. HWP 파서 (순수 파이썬 백그라운드 파싱 + 0x000B 표 제어문자 컨텍스트 감지)
    # --------------------------------------------------------------------------
    @staticmethod
    def parse_hwp(file_path: Optional[str] = None, is_active: bool = False) -> List[Dict[str, Any]]:
        if not file_path or is_active:
            raise ValueError("한글(HWP)은 PDF와 동일하게 '로컬 파일 읽기 전용'으로 지원됩니다. 파일 경로를 지정해 주세요 (--file <경로.hwp>).")

        abs_path = os.path.abspath(file_path)
        doc_name = os.path.basename(file_path)
        ext = abs_path.split(".")[-1].lower()
        records = []
        item_id = 0

        # 1. HWPX (ZIP + XML) 순수 파이썬 파싱
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
                                p_texts = []
                                for t in elem.iter():
                                    if t.tag.split("}")[-1] == "t" and t.text:
                                        p_texts.append(t.text)
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

        # 2. HWP (바이너리 5.0 OLE) 순수 파이썬 파싱
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
            raise RuntimeError(f"한글 문서({doc_name})를 순수 파이썬으로 파싱할 수 없거나 내용이 비어 있습니다. (암호화/배포용 문서 여부 확인 필요)")

        return records

    # --------------------------------------------------------------------------
    # 7-6. CSV 전용 파서 (UTF-8 및 CP949 자동 폴백)
    # --------------------------------------------------------------------------
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

    # --------------------------------------------------------------------------
    # 7-7. Markdown / Text 파서
    # --------------------------------------------------------------------------
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
    """
    오피스 스마트 쓰기 엔진
    - 키워드 앵커(--anchor) 탐색 및 상대 위치(--pos before|after|replace) 정밀 삽입
    - Word: Selection.Find 이동, replace 시 기존 선택 영역 제거 후 표/이미지/텍스트 삽입
    - Excel: Cells.Find 이동, before 시 행 삽입(Insert), replace 시 셀/행 교체, 수식/숫자 자동 캐스팅
    - PPT: 슬라이드 및 앵커 도형 좌표 탐색, replace/before/after 위치 제어 및 자동 페이지네이션
    """

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
        chart_title: Optional[str] = None
    ) -> Dict[str, Any]:
        if auto_backup:
            try:
                bm = BackupManager()
                bm.backup_target(target, is_active)
            except Exception:
                pass

        ext = target.split(".")[-1].lower() if not is_active else target.lower()

        if ext in ["hwp", "hwpx"]:
            raise NotImplementedError("한글(HWP) 문서는 PDF와 동일하게 '읽기 전용(Read-Only)'으로 지원됩니다. 쓰기 대상은 Word, Excel, PowerPoint 및 Markdown/Text만 가능합니다.")
        elif ext in ["docx", "doc", "word"]:
            return OfficeWriter._write_word(target, is_active, records, anchor, pos, clear=clear)
        elif ext in ["xlsx", "xls", "excel"] or (is_active and (ext.startswith("book") or "sheet" in ext)):
            return OfficeWriter._write_excel(target, is_active, records, anchor, pos, clear=clear, chart=chart, chart_title=chart_title)
        elif ext in ["pptx", "ppt", "powerpoint"]:
            return OfficeWriter._write_ppt(target, is_active, records, anchor, pos, clear=clear)
        elif ext in ["md", "txt"]:
            return OfficeWriter._write_md_txt(target, records, anchor, pos, clear=clear)
        else:
            if is_active:
                try:
                    return OfficeWriter._write_excel(target, is_active, records, anchor, pos, clear=clear, chart=chart, chart_title=chart_title)
                except Exception:
                    pass
            raise NotImplementedError(f"지원하지 않는 쓰기 대상 포맷입니다: {target}")

    @staticmethod
    @com_safe()
    def _write_word(target: str, is_active: bool, records: List[Dict[str, Any]], anchor: Optional[str], pos: str, clear: bool = False) -> Dict[str, Any]:
        sync_desktop_to_default()
        app = None
        doc = None
        guard_pid = None
        is_new_doc = False
        try:
            if is_active:
                try:
                    app = win32com.client.GetActiveObject("Word.Application")
                except Exception:
                    app = win32com.client.Dispatch("Word.Application")
                app.Visible = True
                doc = app.ActiveDocument if app.Documents.Count > 0 else app.Documents.Add()
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
                    doc = app.Documents.Open(abs_target)
                    is_new_doc = False
                else:
                    doc = app.Documents.Add()
                    is_new_doc = True

            if clear and doc:
                doc.Content.Delete()
                if not records:
                    if not is_active:
                        doc.SaveAs(abs_target) if is_new_doc else doc.Save()
                    return {"status": "ok", "action": "cleared", "target": target, "count": 0}

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
                sel.HomeKey(6)  # wdStory
                found = sel.Find.Execute(anchor)
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
                            sel.Collapse(1)  # wdCollapseStart
                    elif pos == "after":
                        try:
                            p_end = sel.Paragraphs(1).Range.End
                            sel.SetRange(p_end, p_end)
                        except Exception:
                            sel.Collapse(0)  # wdCollapseEnd
                            sel.InsertParagraphAfter()
                            sel.Collapse(0)
                    elif pos == "replace":
                        # 표/이미지/텍스트 어떤 요소가 오더라도 기존 앵커 텍스트가 남지 않도록 삭제
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
            for idx_g, (g_type, g_val) in enumerate(grouped):
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
                                tbl.Borders.OutsideLineStyle = 1  # wdLineStyleSingle
                                tbl.Borders.InsideLineStyle = 1   # wdLineStyleSingle
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
                        # replace 모드이면서 단일 텍스트 교체인 경우 불필요한 줄바꿈 없이 인플레이스 교체
                        if anchor and pos == "replace" and len(grouped) == 1:
                            sel.TypeText(text_val)
                        else:
                            sel.TypeText(text_val + "\n")
                        written_items += 1

            if not is_active:
                if is_new_doc:
                    doc.SaveAs(abs_target)
                else:
                    doc.Save()

            return {"status": "ok", "action": "written", "target": target, "count": written_items}

        finally:
            if not is_active:
                if doc:
                    try:
                        doc.Close(False)
                    except Exception:
                        pass
                if app:
                    try:
                        app.Quit()
                    except Exception:
                        pass
                if guard_pid:
                    ComProcessGuard.unregister(guard_pid)

    @staticmethod
    @com_safe()
    def _write_excel(target: str, is_active: bool, records: List[Dict[str, Any]], anchor: Optional[str], pos: str, clear: bool = False, chart: Optional[str] = None, chart_title: Optional[str] = None) -> Dict[str, Any]:
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
                app.Visible = True
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
                    wb = app.Workbooks.Open(abs_target)
                    is_new_wb = False
                else:
                    wb = app.Workbooks.Add()
                    is_new_wb = True
            sheet = wb.ActiveSheet

            if clear and sheet:
                sheet.Cells.Clear()
                if not records:
                    if not is_active:
                        wb.SaveAs(abs_target) if is_new_wb else wb.Save()
                    return {"status": "ok", "action": "cleared", "target": target, "count": 0}

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
                found_cell = sheet.Cells.Find(What=anchor)
                if found_cell:
                    if pos == "before":
                        start_row = found_cell.Row
                        # 기존 행 덮어쓰기 방지를 위해 삽입될 데이터 행 수만큼 빈 행 Insert
                        non_chart_count = sum(1 for r in records if r.get("type") not in ("chart", "image"))
                        if non_chart_count > 0:
                            try:
                                insert_rng = sheet.Range(sheet.Rows(start_row), sheet.Rows(start_row + non_chart_count - 1))
                                insert_rng.Insert(-4121)  # xlDown = -4121
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

            # 2D Bulk Write (네이티브 int/float 캐스팅 및 수식 자동 주입)
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
            # 단일 텍스트 replace가 아닌 다중 열 표 데이터 replace인 경우 1열부터 정렬 기록
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

            # 차트 레코드 감지
            for rec in records:
                if rec.get("type") == "chart":
                    chart = rec.get("chart_type") or chart or "line"
                    if rec.get("title"):
                        chart_title = rec.get("title")

            # 차트 생성 (데이터 영역 우측에 자동 배치)
            chart_created = False
            if chart and curr_row > start_row and max_cols_written >= 1:
                try:
                    excel_chart_types = {
                        "line": 4,             # xlLine
                        "line_markers": 65,    # xlLineMarkers
                        "smooth": 72,          # xlXYScatterSmooth
                        "scatter": -4169,      # xlXYScatter
                        "scatter_smooth": 72,  # xlXYScatterSmooth
                        "scatter_lines": 74,   # xlXYScatterLines
                        "column": 51,          # xlColumnClustered
                        "bar": 57,             # xlBarClustered
                        "pie": 5,              # xlPie
                        "area": 1,             # xlArea
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
                if is_new_wb:
                    wb.SaveAs(abs_target)
                else:
                    wb.Save()

            res_data = {"status": "ok", "action": "written", "target": target, "count": written_items}
            if chart_created:
                res_data["chart"] = chart
            return res_data

        finally:
            if not is_active:
                if wb:
                    try:
                        wb.Close(False)
                    except Exception:
                        pass
                if app:
                    try:
                        app.Quit()
                    except Exception:
                        pass
                if guard_pid:
                    ComProcessGuard.unregister(guard_pid)

    @staticmethod
    @com_safe()
    def _write_ppt(target: str, is_active: bool, records: List[Dict[str, Any]], anchor: Optional[str], pos: str, clear: bool = False) -> Dict[str, Any]:
        sync_desktop_to_default()
        app = None
        prs = None
        guard_pid = None
        is_new_prs = False
        try:
            if is_active:
                try:
                    app = win32com.client.GetActiveObject("PowerPoint.Application")
                except Exception:
                    app = win32com.client.Dispatch("PowerPoint.Application")
                prs = app.ActivePresentation if app.Presentations.Count > 0 else app.Presentations.Add(WithWindow=True)
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

            if clear and prs:
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
                    return {"status": "ok", "action": "cleared", "target": target, "count": 0, "slides": 1}

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

            target_slide = None
            anchor_shape = None
            if anchor:
                for s_idx in range(1, prs.Slides.Count + 1):
                    s = prs.Slides(s_idx)
                    for shape in s.Shapes:
                        if shape.HasTextFrame and shape.TextFrame.HasText:
                            if anchor in shape.TextFrame.TextRange.Text:
                                target_slide = s
                                anchor_shape = shape
                                break
                    if target_slide:
                        break

            def create_new_blank_slide():
                s = prs.Slides.Add(prs.Slides.Count + 1, 12)  # ppLayoutBlank = 12
                for shape_idx in range(s.Shapes.Count, 0, -1):
                    try:
                        sh = s.Shapes(shape_idx)
                        if getattr(sh, "Type", None) == 14:  # msoPlaceholder
                            sh.Delete()
                    except Exception:
                        pass
                return s

            if not target_slide:
                target_slide = create_new_blank_slide()

            # 앵커 도형 텍스트 인플레이스 교체 (단일 텍스트 레코드 + pos=="replace" 인 경우)
            if anchor_shape is not None and pos == "replace" and len(records) == 1 and records[0].get("type") not in ("image", "table_row") and not isinstance(records[0].get("data"), list):
                new_txt = str(records[0].get("data", ""))
                orig_txt = anchor_shape.TextFrame.TextRange.Text
                anchor_shape.TextFrame.TextRange.Text = orig_txt.replace(anchor, new_txt) if anchor in orig_txt else new_txt
                if not is_active:
                    prs.SaveAs(abs_target) if is_new_prs else prs.Save()
                return {"status": "ok", "action": "written", "target": target, "count": 1}

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

            # pos (before / replace / after)에 따른 시작 Y좌표(top_offset) 산정
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
                    # 앵커 및 그 아래 도형들을 아래로 밀어 공간 확보
                    est_shift = max(40.0, len(records) * 32.0)
                    for sh in target_slide.Shapes:
                        try:
                            if float(sh.Top) >= a_top - 2.0:
                                sh.Top = float(sh.Top) + est_shift
                        except Exception:
                            pass
                else:  # after
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
                        chunk = rows[row_idx : row_idx + max_rows_for_this_slide]
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
                if is_new_prs:
                    prs.SaveAs(abs_target)
                else:
                    prs.Save()

            return {"status": "ok", "action": "written", "target": target, "count": written_items}

        finally:
            if not is_active:
                if prs:
                    try:
                        prs.Close()
                    except Exception:
                        pass
                if app:
                    try:
                        app.Quit()
                    except Exception:
                        pass
                if guard_pid:
                    ComProcessGuard.unregister(guard_pid)

    @staticmethod
    def _write_md_txt(target: str, records: List[Dict[str, Any]], anchor: Optional[str], pos: str, clear: bool = False) -> Dict[str, Any]:
        p = Path(target).resolve()
        if clear:
            content = ""
            if not records:
                p.write_text("", encoding="utf-8")
                return {"status": "ok", "action": "cleared", "target": target, "count": 0}
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

        if anchor and anchor in content:
            if pos == "before":
                new_content = content.replace(anchor, insert_block + anchor, 1)
            elif pos == "after":
                new_content = content.replace(anchor, anchor + "\n" + insert_block, 1)
            elif pos == "replace":
                new_content = content.replace(anchor, insert_block.rstrip("\n"), 1)
            else:
                new_content = content + "\n" + insert_block
        else:
            new_content = content + ("\n" if content and not content.endswith("\n") else "") + insert_block

        p.write_text(new_content, encoding="utf-8")
        return {"status": "ok", "action": "written", "target": target, "count": len(records)}


# ==============================================================================
# 9. 문서 파싱 라우터 (로드 / 캐시 연동)
# ==============================================================================
def parse_document(file_path: Optional[str], is_active: bool = False, extract_images: bool = False, target_pages: Optional[Set[int]] = None) -> List[Dict[str, Any]]:
    cache_mgr = CacheManager()

    # 활성 창은 항상 실시간 메모리에서 읽음 (캐시 미사용)
    if is_active:
        app_name = (file_path or "").lower()
        if app_name in ["word", "doc", "docx"]:
            return DocumentParser.parse_word(file_path=file_path, is_active=True, extract_images=extract_images, target_pages=target_pages)
        elif app_name in ["excel", "xls", "xlsx"] or app_name.startswith("book") or "sheet" in app_name:
            return DocumentParser.parse_excel(file_path=file_path, is_active=True, extract_images=extract_images, target_pages=target_pages)
        elif app_name in ["ppt", "pptx", "powerpoint"]:
            return DocumentParser.parse_ppt(is_active=True, target_pages=target_pages)
        elif app_name in ["hwp", "hwpx"]:
            raise ValueError("한글(HWP) 문서는 PDF와 동일하게 '로컬 파일 읽기 전용'으로 지원됩니다. 파일 경로를 지정해 주세요 (--file <경로.hwp>). 활성 창 제어는 word, excel, ppt만 가능합니다.")
        else:
            try:
                return DocumentParser.parse_excel(file_path=file_path, is_active=True, extract_images=extract_images, target_pages=target_pages)
            except Exception:
                raise ValueError(f"지원하지 않는 활성 창 대상입니다: {file_path}. (word, excel, ppt 중 지정)")

    if not file_path:
        raise ValueError("--file 인자가 필요합니다.")

    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {abs_path}")

    ext = abs_path.split(".")[-1].lower()

    # 캐시 로드 및 --extract-images 우회 검증 (PDF, Word, Excel 공통)
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
                return [r for r in cached if r.get("page") in target_pages]
            return cached

    if ext == "pdf":
        records = DocumentParser.parse_pdf(abs_path, extract_images=extract_images)
        if target_pages:
            records = [r for r in records if r.get("page") in target_pages]
    elif ext in ["xlsx", "xls", "xlsm"]:
        records = DocumentParser.parse_excel(abs_path, is_active=False, extract_images=extract_images, target_pages=target_pages)
    elif ext == "csv":
        records = DocumentParser.parse_csv(abs_path)
        if target_pages:
            records = [r for r in records if r.get("page") in target_pages]
    elif ext in ["docx", "doc"]:
        records = DocumentParser.parse_word(abs_path, is_active=False, extract_images=extract_images, target_pages=target_pages)
    elif ext in ["pptx", "ppt"]:
        records = DocumentParser.parse_ppt(abs_path, is_active=False, target_pages=target_pages)
    elif ext in ["hwp", "hwpx"]:
        records = DocumentParser.parse_hwp(abs_path, is_active=False)
        if target_pages:
            records = [r for r in records if r.get("page") in target_pages]
    elif ext in ["md", "txt"]:
        records = DocumentParser.parse_md_txt(abs_path)
        if target_pages:
            records = [r for r in records if r.get("page") in target_pages]
    elif ext in ["jsonl", "json"]:
        records = []
        with open(abs_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f):
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    obj = json.loads(line_str)
                    if isinstance(obj, dict):
                        records.append(obj)
                    elif isinstance(obj, list):
                        records.append({"id": line_idx, "type": "table_row", "data": obj})
                    else:
                        records.append({"id": line_idx, "type": "text", "data": str(obj)})
                except Exception:
                    records.append({"id": line_idx, "type": "text", "data": line_str})
        if target_pages:
            records = [r for r in records if r.get("page") in target_pages]
    else:
        raise ValueError(f"지원하지 않는 문서 포맷입니다: {ext}")

    # 캐시 저장: 전체 페이지 파싱일 때만 캐시 저장
    if not target_pages:
        cache_mgr.save(abs_path, records)
    return records


# ==============================================================================
# 10. 메인 CLI 진입점
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="OfficeCLI: 윈도우 11 AI 에이전트 친화적 오피스 자동화 & 하이브리드 검색 도구"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --------------------------------------------------------------------------
    # (1) run 명령어: [읽기/캐시] -> [하이브리드 검색] -> [출력 또는 쓰기]
    # --------------------------------------------------------------------------
    run_parser = subparsers.add_parser("run", help="문서 읽기, 캐시, 검색 및 대상 문서 쓰기 통합 실행")
    run_parser.add_argument("--file", help="원본 문서 경로 (PDF, Word, Excel, CSV, PPT, HWP, MD, TXT)")
    run_parser.add_argument("--search", help="검색할 키워드 또는 정규식 패턴")
    run_parser.add_argument("--top", type=int, default=0, help="하이브리드 검색 상위 N개 결과 제한 (기본: 전체)")
    run_parser.add_argument("--pages", help="추출/기록할 페이지 또는 슬라이드 범위 (예: 1-2, 3)")
    run_parser.add_argument("--to", help="결과를 기록할 대상 파일 경로 또는 앱 (word, excel, ppt)")
    run_parser.add_argument("--active", action="store_true", help="화면에 열려 있는 활성 창 제어 여부")
    run_parser.add_argument("--active-from", action="store_true", help="읽기 원본이 활성 창인 경우 명시 (word, excel, ppt)")
    run_parser.add_argument("--active-to", action="store_true", help="쓰기 대상이 활성 창인 경우 명시 (word, excel, ppt)")
    run_parser.add_argument("--anchor", help="기록할 위치를 찾을 기준 키워드")
    run_parser.add_argument("--pos", default="after", choices=["before", "after", "replace"], help="앵커 기준 상대 위치")
    run_parser.add_argument("--prefix", help="기록할 내용 앞에 붙일 접두사 (예: '[from 기안서]')")
    run_parser.add_argument("--clear", action="store_true", help="기록 전 대상 시트/문서 내용 전체 삭제")
    run_parser.add_argument("--no-backup", action="store_true", help="쓰기 작업 전 자동 백업 스냅샷 생성 비활성화")
    run_parser.add_argument("--chart", help="엑셀에 생성할 차트 종류 (line, smooth, scatter, column, bar, pie)")
    run_parser.add_argument("--chart-title", help="엑셀 차트 상단 제목")
    run_parser.add_argument("--extract-images", action="store_true", help="문서 내 이미지/차트를 추출하여 폴더 저장 및 레코드에 포함")

    # --------------------------------------------------------------------------
    # (2) info 명령어: 본문 전체 파싱 없이 문서 메타(페이지, 시트, 목차) 0.1초 요약
    # --------------------------------------------------------------------------
    info_parser = subparsers.add_parser("info", help="문서 메타데이터(쪽수, 시트, 목차 등) 고속 요약")
    info_parser.add_argument("--file", required=True, help="문서 파일 경로 또는 활성 앱 이름(word, excel, ppt)")
    info_parser.add_argument("--active", action="store_true", help="활성 창 메타데이터 확인 (word, excel, ppt)")

    # --------------------------------------------------------------------------
    # (3) read 명령어: 특정 범위 정밀 추출 (스트리밍 JSONL)
    # --------------------------------------------------------------------------
    read_parser = subparsers.add_parser("read", help="문서 데이터를 표준 JSONL로 추출")
    read_parser.add_argument("--file", help="문서 파일 경로 또는 활성 앱 이름(word, excel, ppt)")
    read_parser.add_argument("--active", action="store_true", help="활성 창 데이터 추출 (word, excel, ppt)")
    read_parser.add_argument("--pages", help="추출할 페이지/슬라이드 범위 (예: 1-5, 3)")
    read_parser.add_argument("--extract-images", action="store_true", help="문서 내 이미지/차트 추출")

    # --------------------------------------------------------------------------
    # (4) write 명령어: 독립 쓰기 명령
    # --------------------------------------------------------------------------
    write_parser = subparsers.add_parser("write", help="대상 문서에 데이터 직접 기록")
    write_parser.add_argument("--to", required=True, help="대상 파일 또는 앱 (word, excel, ppt)")
    write_parser.add_argument("--active", action="store_true", help="활성 창 대상 쓰기")
    write_parser.add_argument("--anchor", help="기록할 앵커 키워드")
    write_parser.add_argument("--pos", default="after", choices=["before", "after", "replace"], help="앵커 상대 위치")
    write_parser.add_argument("--prefix", help="기록할 내용 앞에 붙일 접두사 (예: '[from 발췌]')")
    write_parser.add_argument("--clear", action="store_true", help="기록 전 대상 시트/문서 내용 전체 삭제")
    write_parser.add_argument("--no-backup", action="store_true", help="쓰기 작업 전 자동 백업 스냅샷 생성 비활성화")
    write_parser.add_argument("--chart", help="엑셀에 생성할 차트 종류 (line, smooth, scatter, column, bar, pie)")
    write_parser.add_argument("--chart-title", help="엑셀 차트 상단 제목")
    write_parser.add_argument("--image", help="대상 문서에 삽입할 이미지 파일 경로 (PNG, JPG 등)")
    write_parser.add_argument("--text", help="기록할 텍스트 내용")
    write_parser.add_argument("--table", help="기록할 표 데이터 (JSON 2차원 배열 문자열, 예: '[[\"항목\",\"값\"],[\"A\",100]]')")
    write_parser.add_argument("--file", help="기록할 원본 JSONL/텍스트 파일 경로")

    # --------------------------------------------------------------------------
    # (5) restore 명령어: 백업 스냅샷으로 원본 복원
    # --------------------------------------------------------------------------
    restore_parser = subparsers.add_parser("restore", help="작업 전 백업 스냅샷으로 대상 문서/창 복원")
    restore_parser.add_argument("--target", required=True, help="복원할 대상 (word, excel, ppt 또는 파일 경로)")
    restore_parser.add_argument("--snapshot", help="특정 백업 스냅샷 ID (생략 시 가장 최근 백업으로 복원)")

    # --------------------------------------------------------------------------
    # (6) backup 명령어: 백업 스냅샷 이력 조회 및 정리
    # --------------------------------------------------------------------------
    backup_parser = subparsers.add_parser("backup", help="백업 스냅샷 관리, 이력 조회 및 용량 정리")
    backup_parser.add_argument("action", choices=["list", "clean"], default="list", nargs="?", help="수행할 작업 (list | clean)")
    backup_parser.add_argument("--keep", type=int, default=0, help="clean 시 최근 N개의 백업만 남기고 삭제 (기본: 0=전체삭제)")

    # --------------------------------------------------------------------------
    # (7) cache 명령어: 캐시 상태 조회 및 정리
    # --------------------------------------------------------------------------
    cache_parser = subparsers.add_parser("cache", help="캐시 용량 조회 및 정리")
    cache_parser.add_argument("action", choices=["status", "clean"], default="status", nargs="?", help="수행할 작업 (status | clean)")

    args = parser.parse_args()

    try:
        def is_app_keyword(val: Optional[str]) -> bool:
            if not val:
                return False
            return val.lower() in ["word", "excel", "ppt", "doc", "docx", "xls", "xlsx", "pptx", "powerpoint"]

        def parse_pages_arg(pages_str: Optional[str]) -> Optional[Set[int]]:
            if not pages_str:
                return None
            res = set()
            for part in pages_str.split(","):
                part = part.strip()
                if "-" in part:
                    start_p, end_p = part.split("-", 1)
                    if start_p.strip().isdigit() and end_p.strip().isdigit():
                        res.update(range(int(start_p), int(end_p) + 1))
                elif part.isdigit():
                    res.add(int(part))
            return res if res else None

        # ======================================================================
        # Command: run
        # ======================================================================
        if args.command == "run":
            is_read_active = bool(getattr(args, "active_from", False))
            is_write_active = bool(getattr(args, "active_to", False))

            if args.active:
                if is_app_keyword(args.file):
                    is_read_active = True
                if is_app_keyword(args.to):
                    is_write_active = True
                if not is_read_active and not is_write_active:
                    if args.to:
                        is_write_active = True
                    else:
                        is_read_active = True

            target_pages = parse_pages_arg(args.pages)

            records = parse_document(args.file, is_active=is_read_active, extract_images=args.extract_images, target_pages=target_pages)

            if target_pages:
                records = [r for r in records if r.get("page") in target_pages]

            if args.search:
                records = HybridSearcher.search(records, args.search, top_k=args.top)
            elif args.top and args.top > 0:
                records = records[:args.top]

            if getattr(args, "prefix", None):
                for r in records:
                    if r.get("type") == "image":
                        continue
                    data = r.get("data", "")
                    if isinstance(data, list):
                        r["data"] = [f"{args.prefix} {c}" if i == 0 else c for i, c in enumerate(data)]
                    else:
                        r["data"] = f"{args.prefix} {data}"

            if args.to:
                res = OfficeWriter.write_to_target(
                    target=args.to,
                    is_active=is_write_active,
                    records=records,
                    anchor=args.anchor,
                    pos=args.pos,
                    clear=getattr(args, "clear", False),
                    auto_backup=not getattr(args, "no_backup", False),
                    chart=getattr(args, "chart", None),
                    chart_title=getattr(args, "chart_title", None)
                )
                print(json.dumps(res, ensure_ascii=False))
            else:
                for r in records:
                    print(json.dumps(r, ensure_ascii=False))

        # ======================================================================
        # Command: info
        # ======================================================================
        elif args.command == "info":
            if args.active:
                records = parse_document(args.file, is_active=True)
                doc_name = records[0]["src"] if records else (args.file or "ActiveDoc")
                ext = records[0]["ext"] if records else "active"
                pages = set(r.get("page") for r in records if r.get("page") is not None)
                sections = []
                for r in records:
                    sec = r.get("section")
                    if sec and sec not in sections:
                        sections.append(sec)
                info_res = {
                    "src": doc_name,
                    "ext": ext,
                    "mode": "active_window",
                    "page_count": max(pages) if pages else 1,
                    "sections": sections[:10],
                    "total_records": len(records)
                }
                print(json.dumps(info_res, ensure_ascii=False, indent=2))
            else:
                abs_path = os.path.abspath(args.file)
                if not os.path.exists(abs_path):
                    raise FileNotFoundError(f"파일을 찾을 수 없습니다: {abs_path}")
                ext = abs_path.split(".")[-1].lower()
                info_res = {"src": os.path.basename(abs_path), "ext": ext, "size_kb": round(os.path.getsize(abs_path) / 1024, 1)}

                cache_mgr = CacheManager()
                cached_records = cache_mgr.load(abs_path)

                if ext == "pdf" and pymupdf:
                    doc = pymupdf.open(abs_path)
                    info_res["page_count"] = len(doc)
                    toc = doc.get_toc()
                    info_res["toc"] = [item[1] for item in toc[:10]] if toc else []
                    doc.close()
                elif cached_records is not None:
                    pages = set(r.get("page") for r in cached_records if r.get("page") is not None)
                    sections = []
                    for r in cached_records:
                        sec = r.get("section")
                        if sec and sec not in sections:
                            sections.append(sec)
                    info_res["page_count"] = max(pages) if pages else 1
                    info_res["sections"] = sections[:10]
                    info_res["total_records"] = len(cached_records)
                    info_res["cached"] = True
                elif ext in ["xlsx", "xls", "xlsm"] and win32com:
                    app = None
                    wb = None
                    guard_pid = None
                    try:
                        app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Excel.Application", "EXCEL.EXE")
                        app.Visible = False
                        app.DisplayAlerts = False
                        wb = app.Workbooks.Open(abs_path, ReadOnly=True)
                        sheets = [wb.Sheets(i).Name for i in range(1, wb.Sheets.Count + 1)]
                        info_res["page_count"] = len(sheets)
                        info_res["sections"] = sheets[:10]
                    except Exception:
                        pass
                    finally:
                        if wb:
                            try:
                                wb.Close(False)
                            except Exception:
                                pass
                        if app:
                            try:
                                app.Quit()
                            except Exception:
                                pass
                        if guard_pid:
                            ComProcessGuard.unregister(guard_pid)
                elif ext in ["pptx", "ppt"] and win32com:
                    app = None
                    prs = None
                    guard_pid = None
                    try:
                        app, guard_pid = ComProcessGuard.dispatch_ex_guarded("PowerPoint.Application", "POWERPNT.EXE")
                        prs = app.Presentations.Open(abs_path, ReadOnly=True, Untitled=False, WithWindow=False)
                        info_res["page_count"] = prs.Slides.Count
                    except Exception:
                        pass
                    finally:
                        if prs:
                            try:
                                prs.Close()
                            except Exception:
                                pass
                        if app:
                            try:
                                app.Quit()
                            except Exception:
                                pass
                        if guard_pid:
                            ComProcessGuard.unregister(guard_pid)
                elif ext in ["docx", "doc"] and win32com:
                    app = None
                    doc = None
                    guard_pid = None
                    try:
                        app, guard_pid = ComProcessGuard.dispatch_ex_guarded("Word.Application", "WINWORD.EXE")
                        app.Visible = False
                        app.DisplayAlerts = 0
                        doc = app.Documents.Open(abs_path, ReadOnly=True)
                        info_res["page_count"] = doc.ComputeStatistics(2)  # wdStatisticPages = 2
                    except Exception:
                        pass
                    finally:
                        if doc:
                            try:
                                doc.Close(False)
                            except Exception:
                                pass
                        if app:
                            try:
                                app.Quit()
                            except Exception:
                                pass
                        if guard_pid:
                            ComProcessGuard.unregister(guard_pid)

                if "page_count" not in info_res:
                    records = parse_document(abs_path, is_active=False)
                    pages = set(r.get("page") for r in records if r.get("page") is not None)
                    sections = []
                    for r in records:
                        sec = r.get("section")
                        if sec and sec not in sections:
                            sections.append(sec)
                    info_res["page_count"] = max(pages) if pages else 1
                    info_res["sections"] = sections[:10]
                    info_res["total_records"] = len(records)

                print(json.dumps(info_res, ensure_ascii=False, indent=2))

        # ======================================================================
        # Command: read
        # ======================================================================
        elif args.command == "read":
            target_pages = parse_pages_arg(args.pages)
            records = parse_document(args.file, is_active=args.active, extract_images=args.extract_images, target_pages=target_pages)

            if target_pages:
                records = [r for r in records if r.get("page") in target_pages]

            for r in records:
                print(json.dumps(r, ensure_ascii=False))

        # ======================================================================
        # Command: write
        # ======================================================================
        elif args.command == "write":
            data_to_write = []

            def append_parsed_line(line_s: str):
                if not line_s:
                    return
                try:
                    obj = json.loads(line_s)
                    if isinstance(obj, dict) and "data" in obj:
                        data_to_write.append(obj)
                    elif isinstance(obj, list):
                        if obj and all(isinstance(row, list) for row in obj):
                            for row in obj:
                                data_to_write.append({"type": "table_row", "data": row})
                        else:
                            data_to_write.append({"type": "table_row", "data": obj})
                    else:
                        data_to_write.append({"type": "text", "data": str(obj)})
                except Exception:
                    data_to_write.append({"type": "text", "data": line_s})

            if getattr(args, "file", None):
                src_recs = parse_document(args.file, is_active=False)
                data_to_write.extend(src_recs)

            if getattr(args, "table", None):
                try:
                    tbl_obj = json.loads(args.table)
                    if isinstance(tbl_obj, list):
                        if tbl_obj and all(isinstance(row, list) for row in tbl_obj):
                            for row in tbl_obj:
                                data_to_write.append({"type": "table_row", "data": row})
                        else:
                            data_to_write.append({"type": "table_row", "data": tbl_obj})
                    else:
                        raise ValueError("--table 인자는 JSON 배열 형식이어야 합니다.")
                except Exception as e:
                    raise ValueError(f"--table JSON 파싱 실패: {e}")

            if getattr(args, "image", None):
                data_to_write.append({"type": "image", "data": args.image})

            if getattr(args, "text", None):
                data_to_write.append({"type": "text", "data": args.text})

            # --clear 여부와 상관없이 명시적 입력 인자가 없고 stdin 파이프 입력이 있으면 읽어 들임
            if not data_to_write and not sys.stdin.isatty():
                for line in sys.stdin:
                    append_parsed_line(line.strip())

            if getattr(args, "prefix", None):
                for r in data_to_write:
                    if r.get("type") == "image":
                        continue
                    data = r.get("data", "")
                    if isinstance(data, list):
                        r["data"] = [f"{args.prefix} {c}" if i == 0 else c for i, c in enumerate(data)]
                    else:
                        r["data"] = f"{args.prefix} {data}"

            res = OfficeWriter.write_to_target(
                target=args.to,
                is_active=args.active,
                records=data_to_write,
                anchor=args.anchor,
                pos=args.pos,
                clear=getattr(args, "clear", False),
                auto_backup=not getattr(args, "no_backup", False),
                chart=getattr(args, "chart", None),
                chart_title=getattr(args, "chart_title", None)
            )
            print(json.dumps(res, ensure_ascii=False))

        # ======================================================================
        # Command: restore
        # ======================================================================
        elif args.command == "restore":
            bm = BackupManager()
            res = bm.restore(target=args.target, snapshot_id=args.snapshot)
            print(json.dumps(res, ensure_ascii=False, indent=2))

        # ======================================================================
        # Command: backup
        # ======================================================================
        elif args.command == "backup":
            bm = BackupManager()
            if args.action == "list":
                backups = bm.list_backups()
                print(json.dumps(backups, ensure_ascii=False, indent=2))
            elif args.action == "clean":
                res = bm.clean(keep_latest=args.keep)
                print(json.dumps(res, ensure_ascii=False, indent=2))

        # ======================================================================
        # Command: cache
        # ======================================================================
        elif args.command == "cache":
            cm = CacheManager()
            if args.action == "status":
                c_bytes = get_dir_size_bytes(cm.cache_dir)
                b_bytes = get_dir_size_bytes(Path(".officecli_backup").resolve())
                files_cnt = len(list(cm.cache_dir.glob("*.jsonl"))) if cm.cache_dir.exists() else 0
                status_res = {
                    "status": "ok",
                    "cache_dir": str(cm.cache_dir),
                    "cached_files": files_cnt,
                    "cache_mb": round(c_bytes / (1024 * 1024), 2),
                    "backup_mb": round(b_bytes / (1024 * 1024), 2),
                    "total_mb": round((c_bytes + b_bytes) / (1024 * 1024), 2),
                    "quota_limit_mb": 300.0
                }
                print(json.dumps(status_res, ensure_ascii=False, indent=2))
            elif args.action == "clean":
                res = cm.clean()
                print(json.dumps(res, ensure_ascii=False, indent=2))

        # 작업 완료 후 300MB 캐시/백업 용량 임계치 점검 및 알림 (clean 명령 시 제외)
        if not (args.command in ("cache", "backup") and getattr(args, "action", "") == "clean"):
            check_storage_quota_warning(limit_mb=300.0)

    except Exception as e:
        err_out = {"status": "error", "error": type(e).__name__, "message": str(e)}
        print(json.dumps(err_out, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

