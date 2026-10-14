# -*- coding: utf-8 -*-
"""
================================================================================
OfficeCLI: 윈도우 11 AI 에이전트 친화적 고성능 오피스 자동화 & 하이브리드 검색 CLI
================================================================================
지원 포맷: Word (.docx, .doc), Excel (.xlsx, .xls, .xlsm, .csv),
          PPT (.pptx, .ppt), HWP (.hwp, .hwpx), PDF (.pdf), Markdown (.md), Text (.txt)
핵심 기능:
1. DispatchEx 기반 백그라운드 완전 격리 읽기 (작업 중인 오피스 창 간섭 0%)
2. 실제 인쇄 쪽번호(wdActiveEndPageNumber) 및 문단-표 실제 순서 100% 보장
3. 셀 병합(Merged Cells) 2D 정규화 & Forward-Fill 값 보존
4. PPT 중첩 그룹 도형 재귀 언패킹 & (Top, Left) 시각적 순서 정렬 (도형 형상 제외 텍스트만 추출)
5. PDF pymupdf4llm 초고속 추출 (기본 이미지 배제, --extract-images 시 폴더 저장)
6. .officecli_cache MD5 기반 JSONL 캐싱 (2회차부터 0.01초 내 응답)
7. 경량 하이브리드 검색 엔진 (Regex + 희소 단어 BM25/IDF + 목차 가중치)
8. 스마트 쓰기 (키워드 앵커 탐색, 주변 서식 자동 상속, 엑셀 = 수식 주입)
================================================================================
"""

import sys
import os
import re
import math
import time
import json
import hashlib
import argparse
import ctypes
import shutil
from pathlib import Path
from functools import wraps
from typing import Any, Optional, Union, List, Dict, Generator, Set

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
except ImportError:
    win32com = None
    pythoncom = None



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
        before_pids = cls.get_process_pids(exe_name)
        app = win32com.client.DispatchEx(app_prog_id)
        after_pids = cls.get_process_pids(exe_name)
        new_pids = after_pids - before_pids
        guard_pid = None
        if new_pids:
            guard_pid = list(new_pids)[0]
            cls.register_pid(guard_pid)
        else:
            hwnd = getattr(app, "Hwnd", getattr(app, "HWND", 0))
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
# 4-2. COM 안정성 가드 (@com_safe)
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
    return str(val).strip()


def ensure_window_visible(hwnd: int, default_x: int = 100, default_y: int = 100, width: int = 1100, height: int = 750):
    """
    윈도우 창이 최소화되어 있거나, 음수/화면 밖 오프스크린 좌표에 위치한 경우
    주 모니터의 안전 영역으로 즉시 이동 및 포커스 복원
    """
    if not hwnd or not win32com:
        return
    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd):
        return

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rc = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rc))

    # 최소화 상태 또는 비정상/음수/가상 데스크톱 오프스크린 좌표 감지
    is_iconic = bool(user32.IsIconic(hwnd))
    is_offscreen = (rc.top < 0 or rc.left < -100 or rc.top > 2500 or rc.left > 4000 or (rc.right - rc.left) < 100)

    if is_iconic:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    if is_offscreen:
        user32.MoveWindow(hwnd, default_x, default_y, width, height, True)

    user32.ShowWindow(hwnd, 9)
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
    time.sleep(0.15)


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
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        norm_target = (target or "").lower()

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
        entry_id = f"active_{norm_target}_{timestamp}"

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

        elif norm_target in ["excel", "xls", "xlsx"]:
            try:
                app = win32com.client.GetActiveObject("Excel.Application")
                wb = app.ActiveWorkbook
                if wb:
                    backup_file = self.backup_dir / f"excel_active_{timestamp}.xlsx"
                    wb.SaveCopyAs(str(backup_file))
                    entry = {
                        "id": entry_id,
                        "target": "excel",
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
                        # 디스크에 이미 존재하는 원본 파일 복사 폴백
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

        return None

    def list_backups(self) -> List[Dict[str, Any]]:
        return self._load_manifest()

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

        # 1. 파일 복원
        if b_type == "file":
            shutil.copy2(backup_path, orig_target)
            return {"status": "ok", "action": "restored", "target": orig_target, "from": str(backup_path), "snapshot_id": latest_entry["id"]}

        # 2. 활성 창 복원 (Word, Excel, PPT 무손실 네이티브 복원)
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
                    doc = app.Documents.Open(orig_path)
                    restored_path = orig_path
                else:
                    doc = app.Documents.Open(str(backup_path.resolve()))
                    restored_path = str(backup_path.resolve())

            elif norm_tgt in ["excel", "xls", "xlsx"]:
                try:
                    app = win32com.client.GetActiveObject("Excel.Application")
                except Exception:
                    app = win32com.client.Dispatch("Excel.Application")
                app.Visible = True
                orig_path = ""
                try:
                    if app.Workbooks.Count > 0 and app.ActiveWorkbook:
                        orig_path = app.ActiveWorkbook.FullName
                        app.ActiveWorkbook.Close(False)
                except Exception:
                    pass

                if orig_path and os.path.exists(orig_path):
                    shutil.copy2(backup_path, orig_path)
                    wb = app.Workbooks.Open(orig_path)
                    restored_path = orig_path
                else:
                    wb = app.Workbooks.Open(str(backup_path.resolve()))
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
                    prs = app.Presentations.Open(orig_path)
                    restored_path = orig_path
                else:
                    prs = app.Presentations.Open(str(backup_path.resolve()))
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
    # 3글자 이상 복합 조사 및 용언 어미
    r"(에서는|으로부터|에서부터|이라고|이라는|으로써|으로서|에게서|한테서|하다가|하도록|하였다|하셨다|했었다|습니다|합니다|입니다|스러운|스럽게|시키기|시키는|시켜서)",
    # 2글자 조사 및 어미
    r"(에서|에게|한테|부터|까지|마저|조차|보다|처럼|으로|로써|로서|이라|라는|하고|하며|이고|이며|하여|하면|하게|하니|하는|하지|할수|있는|없는|됐다|된다|되면|되어|적인)",
    # 1글자 조사 및 어미
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

        # 1. 어절(raw_tokens) 단위로 다단계 어간(Stem)을 묶어 그룹화 (어절당 최대 1개 점수만 인정)
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

        # 2. 문서 전체 코퍼스 단어 빈도(Document Frequency) 계산 (간이 IDF)
        N = max(1, len(records))
        doc_freq = {}
        for rec in records:
            text = " ".join(str(c) for c in rec["data"]) if isinstance(rec.get("data"), list) else str(rec.get("data", ""))
            text_lower = text.lower()
            for token in all_tokens:
                if token in text_lower:
                    doc_freq[token] = doc_freq.get(token, 0) + 1

        # 토큰별 IDF 계산
        idf = {}
        for token in all_tokens:
            df = doc_freq.get(token, 0)
            idf[token] = math.log(1.0 + (N - df + 0.5) / (df + 0.5))

        # 3. 정규식 컴파일 (실패 시 단순 문자열 매칭)
        regex_pattern = None
        try:
            regex_pattern = re.compile(q_clean, re.IGNORECASE)
        except Exception:
            pass

        # 띄어쓰기 무관 매칭용 공백 제거 쿼리
        q_nospace = re.sub(r"\s+", "", q_clean).lower()

        scored_results = []
        current_table_header = ""

        for rec in records:
            data = rec.get("data", "")
            rec_type = rec.get("type", "")
            coord = str(rec.get("coord", ""))

            # 표 헤더(Row:1) 추적 및 컨텍스트 바인딩
            if rec_type == "table_row":
                if "Row:1" in coord or not current_table_header:
                    current_table_header = " ".join(str(c) for c in data) if isinstance(data, list) else str(data)
            else:
                current_table_header = ""

            base_text = " ".join(str(c) for c in data) if isinstance(data, list) else str(data)
            # 표 데이터 행에는 직전 헤더 컨텍스트를 검색 텍스트에 포함하여 맥락 매칭 지원
            eval_text = f"{base_text} {current_table_header}" if (rec_type == "table_row" and "Row:1" not in coord and current_table_header) else base_text

            section = str(rec.get("section", ""))
            text_lower = eval_text.lower()
            section_lower = section.lower()
            text_nospace = re.sub(r"\s+", "", text_lower)

            score = 0.0

            # (A) 정규식 / 원문 완전 일치 가산점 (+15.0)
            if regex_pattern and regex_pattern.search(base_text):
                score += 15.0
            elif q_clean.lower() in base_text.lower():
                score += 15.0
            # 띄어쓰기 무관 매칭 가산점 (+10.0)
            elif len(q_nospace) >= 4 and q_nospace in text_nospace:
                score += 10.0

            # (B) 어절 그룹별 최고 점수 1회만 인정 (중복 뻥튀기 방지)
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

            # 여러 키워드가 한 문단/행에 동시에 등장할수록 시너지 가산점
            if matched_token_count > 1:
                score += matched_token_count * 2.0

            # (C) 목차(섹션) 가중치 (+5.0)
            for t, stem in token_groups:
                if t in section_lower or (stem and stem in section_lower):
                    score += 5.0
                    break

            if score > 0.0:
                rec_copy = rec.copy()
                rec_copy["score"] = round(score, 2)
                scored_results.append(rec_copy)

        # 점수 내림차순 정렬
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
    - PDF: pymupdf4llm (이미지 배제 기본, --extract-images 지원, 표 2D 파싱)
    - Excel: DispatchEx 백그라운드 격리, UsedRange.Value2 Bulk Read, 병합 Forward-Fill
    - Word: DispatchEx 백그라운드 격리, Range.Start 정렬 문단-표 실제 순서 보장, 병합 복원
    - PPT: DispatchEx 백그라운드 격리, msoGroup 재귀 언패킹, 도형 형상 제외 텍스트만 추출, (Top, Left) 정렬
    - HWP: win32com HwpObject 보안 모듈, KeyIndicator 쪽번호, 순차 스캔
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
        img_dir = None
        if extract_images:
            stem = Path(abs_path).stem
            img_dir = os.path.join(os.path.dirname(abs_path), f"{stem}_images")
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

        for chunk in chunks:
            meta = chunk.get("metadata", {})
            page_num = meta.get("page_number", meta.get("page", 1))
            raw_text = chunk.get("text", "")
            lines = raw_text.splitlines()

            for line_idx, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue

                # 마크다운 이미지 태그 제거
                if stripped.startswith("![") and "](" in stripped:
                    continue

                total_extracted_chars += len(stripped)

                # 마크다운 표 감지 (| col1 | col2 |)
                if stripped.startswith("|") and stripped.endswith("|"):
                    # 표 구분선 (| --- | --- |) 건너뛰기
                    if re.match(r"^\|[\s\-:|]+\|$", stripped):
                        continue
                    cells = [c.strip() for c in stripped.strip("|").split("|")]
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

                # 헤더(#, ##) 감지 시 section 업데이트
                if stripped.startswith("#"):
                    current_section = stripped.lstrip("#").strip()
                    doc_type = "heading"
                else:
                    doc_type = "text"

                records.append({
                    "id": item_id,
                    "src": os.path.basename(abs_path),
                    "ext": "pdf",
                    "page": page_num,
                    "section": current_section,
                    "coord": f"p.{page_num}/L.{line_idx}",
                    "type": doc_type,
                    "data": stripped
                })
                item_id += 1

        # 스캔본(통이미지) 감지 안내
        if total_extracted_chars == 0 and len(chunks) > 0:
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
    # 7-2. Excel 파서 (DispatchEx 백그라운드 격리 또는 활성 창)
    # --------------------------------------------------------------------------
    @staticmethod
    @com_safe()
    def parse_excel(file_path: Optional[str] = None, is_active: bool = False, target_pages: Optional[Set[int]] = None) -> List[Dict[str, Any]]:
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
                try:
                    app = win32com.client.GetActiveObject("Excel.Application")
                except Exception:
                    app = win32com.client.Dispatch("Excel.Application")
                wb = app.ActiveWorkbook
                if not wb:
                    raise RuntimeError("현재 열려 있는 활성 엑셀 통합 문서가 없습니다.")
            else:
                abs_path = os.path.abspath(file_path)
                # DispatchEx로 기존 실행 중인 창과 분리된 신규 독립 프로세스 생성
                app = win32com.client.DispatchEx("Excel.Application")
                guard_pid = ComProcessGuard.register(getattr(app, "Hwnd", 0))
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

                # 2D Bulk Read (계산된 결과값 Value2)
                values = used.Value2
                if values is None:
                    continue
                if not isinstance(values, (tuple, list)):
                    values = ((values,),)

                start_row = used.Row
                start_col = used.Column

                # 시트 전체 병합 셀 존재 여부 선확인 (COM IPC 병목 원천 차단)
                has_merged = False
                try:
                    has_merged = (used.MergeCells is not False)
                except Exception:
                    has_merged = True

                for r_offset, row in enumerate(values):
                    r_num = start_row + r_offset
                    row_data = []

                    # 단일 행 튜플 처리
                    cells_iter = row if isinstance(row, (tuple, list)) else [row]
                    for c_offset, raw_val in enumerate(cells_iter):
                        c_num = start_col + c_offset
                        val = raw_val

                        # 병합 셀이 있는 시트에서 오직 빈 셀일 때만 COM IPC 조회 (수만 번의 COM 병목 99% 제거)
                        if has_merged and (raw_val is None or raw_val == ""):
                            try:
                                c_cell = sheet.Cells(r_num, c_num)
                                if c_cell.MergeCells:
                                    val = c_cell.MergeArea.Cells(1, 1).Value2
                            except Exception:
                                pass

                        row_data.append(sanitize_value(val))

                    # 빈 행 스킵
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
    def parse_word(file_path: Optional[str] = None, is_active: bool = False, target_pages: Optional[Set[int]] = None) -> List[Dict[str, Any]]:
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
                try:
                    app = win32com.client.GetActiveObject("Word.Application")
                except Exception:
                    app = win32com.client.Dispatch("Word.Application")
                doc = app.ActiveDocument
                if not doc:
                    raise RuntimeError("현재 열려 있는 활성 워드 문서가 없습니다.")
            else:
                abs_path = os.path.abspath(file_path)
                # DispatchEx 백그라운드 완전 격리 실행
                app = win32com.client.DispatchEx("Word.Application")
                app.Visible = False
                app.DisplayAlerts = 0
                doc = app.Documents.Open(abs_path, ReadOnly=True)
                need_quit = True

                hwnd = 0
                try:
                    hwnd = getattr(app, "Hwnd", 0)
                    if not hwnd and doc:
                        hwnd = getattr(doc.ActiveWindow, "Hwnd", 0)
                except Exception:
                    pass
                guard_pid = ComProcessGuard.register(hwnd)

            doc_name = doc.Name
            current_section = "General"

            # 1. 문서 내 모든 Table의 범위 및 2D 매트릭스 선추출
            table_items = []
            for t_idx, tbl in enumerate(doc.Tables, start=1):
                t_start = tbl.Range.Start
                t_end = tbl.Range.End
                tbl_page = 1
                try:
                    tbl_page = tbl.Range.Information(3)  # wdActiveEndPageNumber = 3
                except Exception:
                    pass

                # 1차원 셀 순회로 병합 셀(COM 에러 0x800A1767) 원천 방지
                grid = {}
                max_r = 1
                max_c = 1
                try:
                    for cell in tbl.Range.Cells:
                        r = cell.RowIndex
                        c = cell.ColumnIndex
                        max_r = max(max_r, r)
                        max_c = max(max_c, c)
                        txt = cell.Range.Text.replace("\r", "").replace("\x07", "").strip()
                        grid[(r, c)] = txt
                except Exception:
                    pass

                # 2D 배열 정규화 (3열 이상 가로 병합 및 세로 병합 완벽 지원 & 일반 빈 셀 보존)
                rows_2d = []
                for r in range(1, max_r + 1):
                    row_vals = []
                    last_val = None
                    for c in range(1, max_c + 1):
                        val = grid.get((r, c))
                        if val is None:
                            # (r, c) 좌표가 grid에 없으면 병합으로 흡수된 셀
                            if last_val is not None:
                                # 가로 N열 연속 병합 지원 (직전 유효 값 상속)
                                val = last_val
                            elif r > 1 and len(rows_2d) >= (r - 1) and len(rows_2d[r - 2]) >= c:
                                # 세로 병합 지원 (윗줄 동일 열 값 상속)
                                val = rows_2d[r - 2][c - 1]
                            else:
                                val = ""
                        else:
                            last_val = val
                        row_vals.append(val)
                    rows_2d.append(row_vals)

                table_items.append({
                    "start": t_start,
                    "end": t_end,
                    "tbl_idx": t_idx,
                    "page": tbl_page,
                    "rows": rows_2d
                })

            # 2. 문단 순회 및 표와 병합하여 실제 등장 순환 스트림 구성
            table_ptr = 0
            num_tables = len(table_items)

            for p in doc.Paragraphs:
                p_range = p.Range
                p_start = p_range.Start

                # 표 내부 문단(wdWithInTable)은 스킵
                try:
                    if p_range.Information(12):  # wdWithInTable = 12
                        continue
                except Exception:
                    pass

                # 현재 문단보다 앞서 있는 표가 있다면 먼저 출력 (순서 100% 보장)
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

                # 실제 인쇄 쪽번호 (wdActiveEndPageNumber = 3)
                page_num = 1
                try:
                    page_num = p_range.Information(3)
                except Exception:
                    pass

                # 페이지 필터링 push-down
                if target_pages and page_num not in target_pages:
                    continue

                # 제목 스타일 감지
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

            # 남은 표 출력
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
                try:
                    app = win32com.client.GetActiveObject("PowerPoint.Application")
                except Exception:
                    app = win32com.client.Dispatch("PowerPoint.Application")
                prs = app.ActivePresentation
                if not prs:
                    raise RuntimeError("현재 열려 있는 활성 PPT 프레젠테이션이 없습니다.")
            else:
                abs_path = os.path.abspath(file_path)
                app = win32com.client.DispatchEx("PowerPoint.Application")
                guard_pid = ComProcessGuard.register(getattr(app, "HWND", getattr(app, "Hwnd", 0)))
                # PPT는 WithWindow=False로 열어 화면 간섭 배제
                prs = app.Presentations.Open(abs_path, ReadOnly=True, Untitled=False, WithWindow=False)
                need_quit = True

            doc_name = prs.Name

            # 도형 재귀 순회 헬퍼
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

                # 슬라이드 제목 추출
                slide_title = f"Slide {s_idx}"
                try:
                    if slide.Shapes.HasTitle:
                        title_txt = slide.Shapes.Title.TextFrame.TextRange.Text.strip()
                        if title_txt:
                            slide_title = title_txt
                except Exception:
                    pass

                # 슬라이드 내 모든 도형을 언패킹하고 시각적 좌표 (Top, Left) 순서로 정렬
                shape_elements = []
                for shape in unpack_shapes(slide.Shapes):
                    try:
                        top = float(shape.Top)
                        left = float(shape.Left)

                        # (A) 표(Table)인 경우
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

                        # (B) 텍스트가 있는 일반/그룹 도형 (형상 정보는 버리고 순수 텍스트만 취득)
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

                # 사람이 위에서 아래, 왼쪽에서 오른쪽으로 읽는 시각적 순서대로 정렬
                shape_elements.sort(key=lambda s: (round(s["top"], -1), s["left"]))

                # JSONL 레코드화
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
    # 7-5. HWP 파서 (보안 승인 모듈, KeyIndicator 쪽번호, 표 순차 탐색)
    # --------------------------------------------------------------------------
    @staticmethod
    def parse_hwp(file_path: Optional[str] = None, is_active: bool = False) -> List[Dict[str, Any]]:
        """한글(HWP/HWPX) 문서는 Hwp.exe 실행 없이 순수 파이썬(olefile/zipfile)으로 0.01초 만에 백그라운드 파싱"""
        if not file_path or is_active:
            raise ValueError("한글(HWP)은 PDF와 동일하게 '로컬 파일 읽기 전용'으로 지원됩니다. 파일 경로를 지정해 주세요 (--file <경로.hwp>).")

        abs_path = os.path.abspath(file_path)
        doc_name = os.path.basename(file_path)
        ext = abs_path.split(".")[-1].lower()
        records = []
        item_id = 0

        # 1. HWPX (ZIP + XML) 순수 파이썬 파싱 (한글 프로그램 실행 0%)
        if ext == "hwpx":
            try:
                with zipfile.ZipFile(abs_path, "r") as zf:
                    section_names = sorted([n for n in zf.namelist() if n.startswith("Contents/section") and n.endswith(".xml")])
                    current_section = "General"
                    for s_name in section_names:
                        xml_bytes = zf.read(s_name)
                        root = ET.fromstring(xml_bytes)

                        # 표 내부 문단(p) ID를 미리 수집하여 일반 본문과 중복 추출 방지
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

        # 2. HWP (바이너리 5.0 OLE) 순수 파이썬 파싱 (한글 프로그램 실행 0%)
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
                    while pos + 4 <= total_len:
                        header = struct.unpack("<I", decomp[pos:pos+4])[0]
                        tag_id = header & 0x3FF
                        size = (header >> 20) & 0xFFF
                        pos += 4

                        if size == 0xFFF and pos + 4 <= total_len:
                            size = struct.unpack("<I", decomp[pos:pos+4])[0]
                            pos += 4

                        if pos + size > total_len:
                            break

                        record_bytes = decomp[pos:pos+size]
                        pos += size

                        # HWPTAG_PARA_TEXT (67)
                        if tag_id == 67:
                            cleaned = []
                            b_idx = 0
                            b_len = len(record_bytes)
                            while b_idx + 2 <= b_len:
                                code = struct.unpack_from("<H", record_bytes, b_idx)[0]
                                b_idx += 2
                                # 확장 및 인라인 제어 문자 (16바이트 규격: 코드 2바이트 + 추가 바이너리 14바이트 스킵)
                                if code in (1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23):
                                    b_idx += 14
                                    continue
                                if code in (9, 10, 13) or code >= 32:
                                    cleaned.append(chr(code))
                            line_text = "".join(cleaned).strip()

                            for line in line_text.splitlines():
                                l_str = line.strip()
                                if not l_str or not re.search(r"[가-힣a-zA-Z0-9]", l_str):
                                    continue

                                is_table = ("\t" in l_str)
                                if is_table:
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

                ole.close()
                if records:
                    return records
            except Exception:
                pass

        if not records:
            raise RuntimeError(f"한글 문서({doc_name})를 순수 파이썬으로 파싱할 수 없거나 내용이 비어 있습니다. (암호화/배포용 문서 여부 확인 필요)")

        return records

    # --------------------------------------------------------------------------
    # 7-6. Markdown / Text 파서
    # --------------------------------------------------------------------------
    @staticmethod
    def parse_md_txt(file_path: str) -> List[Dict[str, Any]]:
        abs_path = os.path.abspath(file_path)
        ext = abs_path.split(".")[-1].lower()

        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        records = []
        item_id = 0
        current_section = ""

        for line_idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            # 이미지 태그 제거
            if stripped.startswith("![") and "](" in stripped:
                continue

            # 마크다운 표 감지
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
    - 키워드 앵커(--anchor) 탐색 및 상대 위치(--pos before|after|replace) 삽입
    - Word: Selection.Find 이동, 표(Tables.Add) 삽입, 주변 서식 유지
    - Excel: Cells.Find 이동, 수식(=) 감지 시 Formula 주입, 윗줄 서식(xlPasteFormats) 자동 복사
    - PPT: 슬라이드 앵커 탐색 및 텍스트/표 삽입
    - HWP: RepeatFind 앵커 이동 및 텍스트/표 삽입
    """

    @staticmethod
    def write_to_target(
        target: str,
        is_active: bool,
        records: List[Dict[str, Any]],
        anchor: Optional[str] = None,
        pos: str = "after",
        clear: bool = False,
        auto_backup: bool = True
    ) -> Dict[str, Any]:
        # 에이전트 수정/초기화 전 원본 자동 백업 스냅샷
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
        elif ext in ["xlsx", "xls", "excel"]:
            return OfficeWriter._write_excel(target, is_active, records, anchor, pos, clear=clear)
        elif ext in ["pptx", "ppt", "powerpoint"]:
            return OfficeWriter._write_ppt(target, is_active, records, anchor, pos, clear=clear)
        elif ext in ["md", "txt"]:
            return OfficeWriter._write_md_txt(target, records, anchor, pos)
        else:
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
                app = win32com.client.DispatchEx("Word.Application")
                app.Visible = False
                app.DisplayAlerts = 0
                if os.path.exists(abs_target):
                    doc = app.Documents.Open(abs_target)
                    is_new_doc = False
                else:
                    doc = app.Documents.Add()
                    is_new_doc = True
                hwnd = 0
                try:
                    hwnd = getattr(app, "Hwnd", 0)
                    if not hwnd and doc:
                        hwnd = getattr(doc.ActiveWindow, "Hwnd", 0)
                except Exception:
                    pass
                guard_pid = ComProcessGuard.register(hwnd)

            if clear and doc:
                doc.Content.Delete()
                if not records:
                    return {"status": "ok", "action": "cleared", "target": target, "count": 0}

            # 기존 문서 표 스타일 및 앵커 폰트 서식 상속
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
                sel.HomeKey(6)  # wdStory (문서 맨 처음으로 이동)
                found = sel.Find.Execute(anchor)
                if found:
                    try:
                        inherited_font_name = sel.Font.Name
                        inherited_font_size = sel.Font.Size
                    except Exception:
                        pass

                    if pos == "before":
                        sel.Collapse(1)  # wdCollapseStart
                    elif pos == "after":
                        sel.Collapse(0)  # wdCollapseEnd
                        sel.InsertParagraphAfter()
                        sel.Collapse(0)
                    elif pos == "replace":
                        pass
                else:
                    sel.EndKey(6)  # wdStory (앵커 미발견 시 문서 끝 Fallback)
                    sel.InsertParagraphAfter()
                    sel.Collapse(0)
            else:
                sel.EndKey(6)  # wdStory (문서 끝)
                sel.InsertParagraphAfter()
                sel.Collapse(0)

            # 연속된 table_row를 그룹화하여 온전한 하나의 표로 일괄 삽입
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
                            if not applied_style:
                                tbl.Borders.Enable = True
                                tbl.AutoFitBehavior(1)
                                if num_rows >= 1:
                                    try:
                                        tbl.Rows(1).Range.Bold = True
                                        tbl.Rows(1).Range.Shading.BackgroundPatternColor = 15987699
                                    except Exception:
                                        pass
                            for r_idx, r_rec in enumerate(t_rows, start=1):
                                r_data = r_rec.get("data", [])
                                for c_idx, val in enumerate(r_data, start=1):
                                    if c_idx <= max_cols:
                                        tbl.Cell(r_idx, c_idx).Range.Text = str(val)
                            # 표 바로 다음 줄로 커서 유지 (EndKey(6)로 문서 끝으로 튀는 것 방지)
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
    def _write_excel(target: str, is_active: bool, records: List[Dict[str, Any]], anchor: Optional[str], pos: str, clear: bool = False) -> Dict[str, Any]:
        sync_desktop_to_default()
        app = None
        wb = None
        guard_pid = None
        is_new_wb = False
        try:
            if is_active:
                try:
                    app = win32com.client.GetActiveObject("Excel.Application")
                except Exception:
                    app = win32com.client.Dispatch("Excel.Application")
                app.Visible = True
                wb = app.ActiveWorkbook if app.Workbooks.Count > 0 else app.Workbooks.Add()
                try:
                    ensure_window_visible(app.Hwnd)
                except Exception:
                    pass
            else:
                abs_target = os.path.abspath(target)
                app = win32com.client.DispatchEx("Excel.Application")
                guard_pid = ComProcessGuard.register(getattr(app, "Hwnd", 0))
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
                    return {"status": "ok", "action": "cleared", "target": target, "count": 0}

            # 쓰기 시작 행 계산 (UsedRange.Row + UsedRange.Rows.Count 정확 반영)
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

            if anchor:
                found = sheet.Cells.Find(What=anchor)
                if found:
                    start_row = found.Row + (1 if pos == "after" else 0)
                else:
                    start_row = 1 if clear else get_append_row(sheet)
            else:
                start_row = 1 if clear else get_append_row(sheet)

            curr_row = start_row
            written_items = 0
            max_cols_written = 1

            # 2D Bulk Write: 연속 데이터 행을 2D 매트릭스로 묶어 1회 COM 주입
            def flush_data_matrix(matrix: List[List[str]], r_start: int) -> int:
                nonlocal max_cols_written
                if not matrix:
                    return 0
                max_cols = max(len(row) for row in matrix) if matrix else 1
                max_cols_written = max(max_cols_written, max_cols)
                # 열 길이 정규화
                norm_matrix = []
                has_formula = False
                for row in matrix:
                    padded = row + [""] * (max_cols - len(row))
                    for c_val in padded:
                        if isinstance(c_val, str) and c_val.startswith("="):
                            has_formula = True
                    norm_matrix.append(padded)

                r_end = r_start + len(norm_matrix) - 1
                target_rng = sheet.Range(sheet.Cells(r_start, 1), sheet.Cells(r_end, max_cols))
                # 2차원 리스트 또는 튜플 형태로 일괄 주입
                val_tuple = tuple(tuple(r) for r in norm_matrix)
                if has_formula:
                    target_rng.Formula = val_tuple
                else:
                    target_rng.Value2 = val_tuple
                return len(norm_matrix)

            pending_matrix: List[List[str]] = []

            for rec in records:
                if rec.get("type") == "image":
                    if pending_matrix:
                        cnt = flush_data_matrix(pending_matrix, curr_row)
                        curr_row += cnt
                        written_items += cnt
                        pending_matrix = []

                    img_path = os.path.abspath(str(rec.get("data", "")))
                    if os.path.exists(img_path):
                        c_cell = sheet.Cells(curr_row, 1)
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
                    pending_matrix.append([str(c).strip() for c in data])
                else:
                    pending_matrix.append([str(data).strip()])

            if pending_matrix:
                cnt = flush_data_matrix(pending_matrix, curr_row)
                curr_row += cnt
                written_items += cnt
                pending_matrix = []

            # 클립보드 오염 없는 서식 일괄 상속 (Non-clipboard Style Inheritance)
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

            if not is_active:
                if is_new_wb:
                    wb.SaveAs(abs_target)
                else:
                    wb.Save()

            return {"status": "ok", "action": "written", "target": target, "count": written_items}

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
                app = win32com.client.DispatchEx("PowerPoint.Application")
                guard_pid = ComProcessGuard.register(getattr(app, "HWND", getattr(app, "Hwnd", 0)))
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
                    return {"status": "ok", "action": "cleared", "target": target, "count": 0, "slides": 1}

            # 기존 슬라이드에서 폰트 및 폰트 색상 상속
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

            # 앵커 슬라이드 찾기 또는 마지막에 새 슬라이드 추가
            target_slide = None
            if anchor:
                for s_idx in range(1, prs.Slides.Count + 1):
                    s = prs.Slides(s_idx)
                    for shape in s.Shapes:
                        if shape.HasTextFrame and shape.TextFrame.HasText:
                            if anchor in shape.TextFrame.TextRange.Text:
                                target_slide = s
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

            # 슬라이드 크기 계산 (기본 와이드 960x540 또는 표준 720x540)
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

            # target_slide 내 기존 객체들의 최하단 Y 좌표 계산
            current_bottom = top_margin
            for shape in target_slide.Shapes:
                try:
                    sh_bottom = float(shape.Top) + float(shape.Height)
                    if sh_bottom > current_bottom:
                        current_bottom = sh_bottom
                except Exception:
                    pass

            top_offset = current_bottom + 12.0 if current_bottom > top_margin else top_margin

            # 1. 레코드를 표 블록, 텍스트 블록, 이미지 블록으로 그룹화
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

            # 2. 블록 단위 순회 및 높이 초과 시 자동 페이지네이션 (새 슬라이드 분할)
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
                    txt = blk["data"]
                    # 텍스트 박스 높이 초과 시 새 슬라이드 생성
                    if top_offset + item_height > (slide_height - bottom_margin):
                        target_slide = create_new_blank_slide()
                        top_offset = top_margin

                    box = target_slide.Shapes.AddTextbox(1, 50, top_offset, box_width, item_height)
                    try:
                        box.TextFrame.WordWrap = -1  # msoTrue
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
                        # 최소 2행도 안 들어가면 바로 새 슬라이드 생성
                        if available_height < (row_height * 2):
                            target_slide = create_new_blank_slide()
                            top_offset = top_margin
                            available_height = (slide_height - bottom_margin) - top_offset

                        max_rows_for_this_slide = max(1, int(available_height // row_height))
                        chunk = rows[row_idx : row_idx + max_rows_for_this_slide]
                        chunk_len = len(chunk)
                        tbl_h = max(24.0, float(chunk_len * row_height))

                        # PowerPoint 표 객체 생성
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

                        # 표의 다음 행들이 남아 있다면 다음 슬라이드로 전환 준비
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
    def _write_md_txt(target: str, records: List[Dict[str, Any]], anchor: Optional[str], pos: str) -> Dict[str, Any]:
        p = Path(target).resolve()
        content = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""

        insert_lines = []
        for rec in records:
            data = rec.get("data", "")
            if isinstance(data, list):
                insert_lines.append("| " + " | ".join(data) + " |")
            else:
                insert_lines.append(str(data))
        insert_block = "\n".join(insert_lines) + "\n"

        if anchor and anchor in content:
            if pos == "before":
                new_content = content.replace(anchor, insert_block + anchor, 1)
            elif pos == "after":
                new_content = content.replace(anchor, anchor + "\n" + insert_block, 1)
            elif pos == "replace":
                new_content = content.replace(anchor, insert_block, 1)
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
            return DocumentParser.parse_word(is_active=True, target_pages=target_pages)
        elif app_name in ["excel", "xls", "xlsx"]:
            return DocumentParser.parse_excel(is_active=True, target_pages=target_pages)
        elif app_name in ["ppt", "pptx", "powerpoint"]:
            return DocumentParser.parse_ppt(is_active=True, target_pages=target_pages)
        elif app_name in ["hwp", "hwpx"]:
            raise ValueError("한글(HWP) 문서는 PDF와 동일하게 '로컬 파일 읽기 전용'으로 지원됩니다. 파일 경로를 지정해 주세요 (--file <경로.hwp>). 활성 창 제어는 word, excel, ppt만 가능합니다.")
        else:
            raise ValueError(f"지원하지 않는 활성 창 대상입니다: {file_path}. (word, excel, ppt 중 지정)")

    if not file_path:
        raise ValueError("--file 인자가 필요합니다.")

    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {abs_path}")

    # 캐시 확인 (전체 파싱 캐시가 있다면 즉시 메모리 필터링 반환)
    cached = cache_mgr.load(abs_path)
    if cached is not None:
        if target_pages:
            return [r for r in cached if r.get("page") in target_pages]
        return cached

    ext = abs_path.split(".")[-1].lower()

    if ext == "pdf":
        records = DocumentParser.parse_pdf(abs_path, extract_images=extract_images)
        if target_pages:
            records = [r for r in records if r.get("page") in target_pages]
    elif ext in ["xlsx", "xls", "xlsm"]:
        records = DocumentParser.parse_excel(abs_path, is_active=False, target_pages=target_pages)
    elif ext in ["docx", "doc"]:
        records = DocumentParser.parse_word(abs_path, is_active=False, target_pages=target_pages)
    elif ext in ["pptx", "ppt"]:
        records = DocumentParser.parse_ppt(abs_path, is_active=False, target_pages=target_pages)
    elif ext in ["hwp", "hwpx"]:
        records = DocumentParser.parse_hwp(abs_path, is_active=False)
        if target_pages:
            records = [r for r in records if r.get("page") in target_pages]
    elif ext in ["md", "txt", "csv"]:
        records = DocumentParser.parse_md_txt(abs_path)
        if target_pages:
            records = [r for r in records if r.get("page") in target_pages]
    else:
        raise ValueError(f"지원하지 않는 문서 포맷입니다: {ext}")

    # 캐시 저장: 전체 문서 파싱일 때만 캐시 저장 (부분 파싱 결과로 캐시 오염 방지)
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
    run_parser.add_argument("--file", help="원본 문서 경로 (PDF, Word, Excel, PPT, HWP, MD, TXT)")
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
    run_parser.add_argument("--extract-images", action="store_true", help="PDF 파싱 시 {파일명}_images 폴더에 이미지 추출 저장")

    # --------------------------------------------------------------------------
    # (2) info 명령어: 본문 전체 파싱 없이 문서 메타(페이지, 시트, 목차) 0.1초 요약
    # --------------------------------------------------------------------------
    info_parser = subparsers.add_parser("info", help="문서 메타데이터(쪽수, 시트, 목차 등) 고속 요약")
    info_parser.add_argument("--file", required=True, help="문서 파일 경로")
    info_parser.add_argument("--active", action="store_true", help="활성 창 메타데이터 확인 (word, excel, ppt)")

    # --------------------------------------------------------------------------
    # (3) read 명령어: 특정 범위 정밀 추출 (스트리밍 JSONL)
    # --------------------------------------------------------------------------
    read_parser = subparsers.add_parser("read", help="문서 데이터를 표준 JSONL로 추출")
    read_parser.add_argument("--file", help="문서 파일 경로")
    read_parser.add_argument("--active", action="store_true", help="활성 창 데이터 추출 (word, excel, ppt)")
    read_parser.add_argument("--pages", help="추출할 페이지/슬라이드 범위 (예: 1-5, 3)")
    read_parser.add_argument("--extract-images", action="store_true", help="PDF 이미지 추출")

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
    write_parser.add_argument("--image", help="대상 문서에 삽입할 이미지 파일 경로 (PNG, JPG 등)")
    write_parser.add_argument("--text", help="기록할 텍스트 내용")

    # --------------------------------------------------------------------------
    # (5) restore 명령어: 백업 스냅샷으로 원본 복원
    # --------------------------------------------------------------------------
    restore_parser = subparsers.add_parser("restore", help="작업 전 백업 스냅샷으로 대상 문서/창 복원")
    restore_parser.add_argument("--target", required=True, help="복원할 대상 (word, excel, ppt 또는 파일 경로)")
    restore_parser.add_argument("--snapshot", help="특정 백업 스냅샷 ID (생략 시 가장 최근 백업으로 복원)")

    # --------------------------------------------------------------------------
    # (6) backup 명령어: 백업 스냅샷 이력 조회
    # --------------------------------------------------------------------------
    backup_parser = subparsers.add_parser("backup", help="백업 스냅샷 관리 및 이력 조회")
    backup_parser.add_argument("action", choices=["list"], default="list", nargs="?", help="수행할 작업 (기본: list)")

    args = parser.parse_args()

    try:
        # 앱 예약어 판별 헬퍼
        def is_app_keyword(val: Optional[str]) -> bool:
            if not val:
                return False
            return val.lower() in ["word", "excel", "ppt", "doc", "docx", "xls", "xlsx", "pptx", "powerpoint"]

        # ======================================================================
        # Command: run
        # ======================================================================
        if args.command == "run":
            is_read_active = False
            is_write_active = False

            if getattr(args, "active_from", False):
                is_read_active = True
            if getattr(args, "active_to", False):
                is_write_active = True

            # 기존 --active 플래그와의 스마트 하위 호환
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

            # 페이지 범위 파싱 (파서 레벨 Push-Down 연동)
            target_pages = None
            if args.pages:
                target_pages = set()
                for part in args.pages.split(","):
                    part = part.strip()
                    if "-" in part:
                        start_p, end_p = part.split("-", 1)
                        target_pages.update(range(int(start_p), int(end_p) + 1))
                    elif part.isdigit():
                        target_pages.add(int(part))

            records = parse_document(args.file, is_active=is_read_active, extract_images=args.extract_images, target_pages=target_pages)

            if target_pages:
                records = [r for r in records if r.get("page") in target_pages]

            # 검색 수행
            if args.search:
                records = HybridSearcher.search(records, args.search, top_k=args.top)
            elif args.top and args.top > 0:
                records = records[:args.top]

            # 접두사(prefix) 적용
            if getattr(args, "prefix", None):
                for r in records:
                    data = r.get("data", "")
                    if isinstance(data, list):
                        r["data"] = [f"{args.prefix} {c}" if i == 0 else c for i, c in enumerate(data)]
                    else:
                        r["data"] = f"{args.prefix} {data}"

            # 쓰기 대상 지정 시 기록 수행
            if args.to:
                res = OfficeWriter.write_to_target(
                    target=args.to,
                    is_active=is_write_active,
                    records=records,
                    anchor=args.anchor,
                    pos=args.pos,
                    clear=getattr(args, "clear", False)
                )
                print(json.dumps(res, ensure_ascii=False))
            else:
                # 표준 출력 (JSONL)
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
                elif ext in ["xlsx", "xls"] and win32com:
                    # 경량 엑셀 메타 조회 (대용량 시트 셀 순회 배제)
                    app = None
                    wb = None
                    guard_pid = None
                    try:
                        app = win32com.client.DispatchEx("Excel.Application")
                        guard_pid = ComProcessGuard.register(getattr(app, "Hwnd", 0))
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
                    # 경량 PPT 메타 조회 (도형 순회 배제)
                    app = None
                    prs = None
                    guard_pid = None
                    try:
                        app = win32com.client.DispatchEx("PowerPoint.Application")
                        guard_pid = ComProcessGuard.register(getattr(app, "HWND", getattr(app, "Hwnd", 0)))
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
                    # 경량 워드 메타 조회 (문단/표 순회 배제)
                    app = None
                    doc = None
                    guard_pid = None
                    try:
                        app = win32com.client.DispatchEx("Word.Application")
                        app.Visible = False
                        app.DisplayAlerts = 0
                        doc = app.Documents.Open(abs_path, ReadOnly=True)
                        hwnd = getattr(app, "Hwnd", 0)
                        if not hwnd and doc:
                            hwnd = getattr(doc.ActiveWindow, "Hwnd", 0)
                        guard_pid = ComProcessGuard.register(hwnd)
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

                # 위 경량 추출에서 page_count를 못 구했거나 그 외 포맷(HWP/MD 등)인 경우 전체 파싱
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
            target_pages = None
            if args.pages:
                target_pages = set()
                for part in args.pages.split(","):
                    part = part.strip()
                    if "-" in part:
                        start_p, end_p = part.split("-", 1)
                        target_pages.update(range(int(start_p), int(end_p) + 1))
                    elif part.isdigit():
                        target_pages.add(int(part))

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
            if getattr(args, "image", None):
                data_to_write.append({"type": "image", "data": args.image})
            if args.text:
                data_to_write.append({"type": "text", "data": args.text})
            elif not getattr(args, "clear", False) and not getattr(args, "image", None) and not sys.stdin.isatty():
                # stdin 파이프라인 수신
                for line in sys.stdin:
                    line_s = line.strip()
                    if line_s:
                        try:
                            data_to_write.append(json.loads(line_s))
                        except Exception:
                            data_to_write.append({"type": "text", "data": line_s})
            if getattr(args, "prefix", None):
                for r in data_to_write:
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
                clear=getattr(args, "clear", False)
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

    except Exception as e:
        err_out = {"status": "error", "error": type(e).__name__, "message": str(e)}
        print(json.dumps(err_out, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
