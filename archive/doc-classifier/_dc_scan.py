"""scan: 폴더 트리 목록화 (파일을 열지 않음).

- os.scandir로 폴더를 읽습니다. Windows에서 DirEntry.stat()은 폴더 목록 결과를 그대로 쓰므로
  파일마다 추가 디스크 접근이 없습니다 (크기, 날짜, 속성, 재분석 태그).
- 방문할 폴더 대기열은 DB(dirs.status='pending')에 있습니다. 폴더 하나를 다 읽어야 그 폴더의 파일과
  하위 폴더가 함께 커밋되므로, 어느 시점에 끊겨도 다시 실행하면 중복 없이 이어집니다.
- 정션/심볼릭 링크 폴더(무한 반복, 중복 집계), 클라우드 자리표시자 폴더, 시스템 폴더는 들어가지 않고 이유를 기록합니다.
- 클라우드 자리표시자/오프라인/링크 파일은 목록에는 넣되 no_read=1 (peek에서 절대 열지 않음).
"""
import fnmatch
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import _dc_runtime as rt
import _dc_store as st

# Windows 파일 속성
FA_READONLY = 0x1
FA_HIDDEN = 0x2
FA_SYSTEM = 0x4
FA_DIRECTORY = 0x10
FA_REPARSE_POINT = 0x400
FA_OFFLINE = 0x1000
FA_RECALL_ON_OPEN = 0x40000
FA_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ATTRS = FA_OFFLINE | FA_RECALL_ON_OPEN | FA_RECALL_ON_DATA_ACCESS

# 재분석 태그: 정션/심볼릭 링크만 '링크'로 보고 건너뜀 (클라우드 동기화 폴더의 태그는 링크가 아님)
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
IO_REPARSE_TAG_SYMLINK = 0xA000000C
LINK_TAGS = (IO_REPARSE_TAG_MOUNT_POINT, IO_REPARSE_TAG_SYMLINK)

# 어느 깊이에서든 들어가지 않는 폴더 (소문자)
ALWAYS_SKIP = {"$recycle.bin", "system volume information", "$windows.~bt", "$windows.~ws", "$sysreset",
               "config.msi", "msocache", "$getcurrent", "windowsapps"}
# 드라이브 바로 아래에 있을 때만 건너뛰는 시스템/프로그램 폴더 (--include-system으로 포함)
DRIVE_ROOT_SKIP = {"windows", "program files", "program files (x86)", "programdata", "perflogs", "recovery",
                   "onedrivetemp", "intel", "amd", "nvidia"}

FLUSH_SECONDS = 1.0
FLUSH_ROWS = 20000
PROGRESS_SECONDS = 2.0
DIR_BATCH = 200


def to_fs(path: str) -> str:
    """Windows 긴 경로(260자 안팎 초과)는 \\\\?\\ 접두어로 접근합니다. DB에는 접두어 없는 경로를 저장."""
    if sys.platform != "win32" or len(path) < 240 or path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def file_flags(attrs: int, name: str, reparse_tag: int = 0) -> Tuple[str, int]:
    """(flags 문자열, no_read). no_read=1이면 열면 안 되는 파일 (내려받기 시작, 링크 등)."""
    flags: List[str] = []
    if attrs & FA_HIDDEN or (sys.platform != "win32" and name.startswith(".")):
        flags.append("hidden")
    if attrs & FA_SYSTEM:
        flags.append("system")
    if attrs & FA_READONLY:
        flags.append("readonly")
    if attrs & FA_OFFLINE:
        flags.append("offline")
    if attrs & (FA_RECALL_ON_OPEN | FA_RECALL_ON_DATA_ACCESS):
        flags.append("cloud")
    if reparse_tag in LINK_TAGS:
        flags.append("link")
    no_read = 1 if (attrs & CLOUD_ATTRS or reparse_tag in LINK_TAGS) else 0
    return ",".join(flags), no_read


def _is_drive_root(path: str) -> bool:
    drive, rest = os.path.splitdrive(os.path.normpath(path))
    return bool(drive) and rest in ("\\", "/", "")


def set_background_priority() -> bool:
    """프로세스 CPU·디스크 I/O 우선순위를 백그라운드로 낮춥니다 (Windows). 공유 사용자와 업무를 방해하지 않기 위함."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p          # 64비트 핸들 (기본 int로 두면 호출이 실패함)
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00100000))   # PROCESS_MODE_BACKGROUND_BEGIN
    except Exception:
        return False


def peak_memory_mb() -> Optional[float]:
    """이 프로세스의 최대 메모리 사용량(작업 집합, MB). Windows만."""
    if sys.platform != "win32":
        try:
            import resource
            return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
        except Exception:
            return None
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return round(pmc.PeakWorkingSetSize / 1048576, 1)
    except Exception:
        pass
    return None


class Scanner:
    def __init__(self, con: Any, options: Dict[str, Any], max_files: Optional[int] = None,
                 time_limit: Optional[float] = None, throttle_ms: int = 0):
        self.con = con
        self.exclude = [p.lower() for p in options.get("exclude") or []]
        self.max_depth = options.get("max_depth")
        self.include_system = bool(options.get("include_system"))
        self.include_cloud = bool(options.get("include_cloud"))
        self.max_files = max_files
        self.time_limit = time_limit
        self.throttle = max(0, int(throttle_ms or 0)) / 1000.0
        self.start = time.time()
        self.run = {"dirs": 0, "files": 0, "bytes": 0, "entry_errors": 0, "excluded_files": 0}
        self._dir_updates: List[Tuple[Any, ...]] = []
        self._new_dirs: List[Tuple[Any, ...]] = []
        self._files: List[Tuple[Any, ...]] = []
        self._last_flush = time.time()
        self._last_progress = time.time()

    # --- 판정 ---------------------------------------------------------------
    def _excluded(self, path: str) -> bool:
        low = path.lower()
        return any(fnmatch.fnmatch(low, p) for p in self.exclude)

    def skip_reason(self, parent: str, path: str, name: str, depth: int, attrs: int, tag: int,
                    is_link: bool) -> Optional[str]:
        low = name.lower()
        if is_link or tag in LINK_TAGS:
            return "link: 정션/심볼릭 링크 (반복·중복 방지)"
        if attrs & CLOUD_ATTRS and not self.include_cloud:
            return "cloud: 클라우드 자리표시자/오프라인 폴더 (열면 내려받기)"
        if low in ALWAYS_SKIP:
            return "system: 시스템 폴더"
        if not self.include_system:
            if low in DRIVE_ROOT_SKIP and _is_drive_root(parent):
                return "system: 드라이브 바로 아래 시스템/프로그램 폴더"
            if attrs & FA_HIDDEN and attrs & FA_SYSTEM:
                return "system: 숨김+시스템 폴더"
        if self.exclude and self._excluded(path):
            return "excluded: --exclude 패턴"
        if self.max_depth is not None and depth > self.max_depth:
            return "max_depth: --max-depth 초과"
        return None

    # --- 폴더 하나 ----------------------------------------------------------
    def scan_dir(self, dir_id: int, path: str, depth: int) -> None:
        try:
            it = os.scandir(to_fs(path))
        except OSError as e:
            self._dir_updates.append(("error", f"error: {type(e).__name__}: {e.strerror or e}", 0, 0, dir_id))
            return
        files = nbytes = 0
        new_dirs: List[Tuple[Any, ...]] = []        # 폴더를 끝까지 읽은 뒤에만 버퍼로 (중간에 끊기면 버림 -> 재개 시 중복 없음)
        rows: List[Tuple[Any, ...]] = []
        with it:
            for entry in it:
                try:
                    name = entry.name
                    full = os.path.join(path, name)
                    info = entry.stat(follow_symlinks=False)
                    attrs = int(getattr(info, "st_file_attributes", 0) or 0)
                    tag = int(getattr(info, "st_reparse_tag", 0) or 0)
                    is_link = entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction())
                    is_dir = entry.is_dir(follow_symlinks=False) or bool(attrs & FA_DIRECTORY) \
                        or (is_link and entry.is_dir(follow_symlinks=True))
                    if is_dir:
                        reason = self.skip_reason(path, full, name, depth + 1, attrs, tag, is_link)
                        new_dirs.append((dir_id, full, depth + 1, "skipped" if reason else "pending", reason))
                        continue
                    if self.exclude and self._excluded(full):
                        self.run["excluded_files"] += 1
                        continue
                    ext = os.path.splitext(name)[1].lower()
                    flags, no_read = file_flags(attrs, name, tag)
                    if is_link and "link" not in flags:
                        flags, no_read = (flags + ",link").strip(","), 1
                    size = int(info.st_size)
                    ctime = getattr(info, "st_birthtime", None)
                    rows.append((dir_id, name, ext, size, info.st_mtime, ctime, attrs, flags, no_read))
                    files += 1
                    nbytes += size
                except OSError as e:
                    self.run["entry_errors"] += 1
                    rt.debug(f"항목 읽기 실패: {path} / {getattr(entry, 'name', '?')}: {e}")
        self._new_dirs.extend(new_dirs)
        self._files.extend(rows)
        self._dir_updates.append(("done", None, files, nbytes, dir_id))
        self.run["dirs"] += 1
        self.run["files"] += files
        self.run["bytes"] += nbytes

    # --- 기록 -------------------------------------------------------------
    def flush(self) -> None:
        if not (self._dir_updates or self._new_dirs or self._files):
            return
        con = self.con
        con.execute("BEGIN")
        try:
            if self._files:
                con.executemany("INSERT INTO files(dir_id, name, ext, size, mtime, ctime, attrs, flags, no_read) "
                                "VALUES (?,?,?,?,?,?,?,?,?)", self._files)
            if self._new_dirs:
                con.executemany("INSERT OR IGNORE INTO dirs(parent_id, path, depth, status, reason) VALUES (?,?,?,?,?)",
                                self._new_dirs)
            con.executemany("UPDATE dirs SET status=?, reason=?, files=?, bytes=? WHERE id=?", self._dir_updates)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        self._dir_updates, self._new_dirs, self._files = [], [], []
        self._last_flush = time.time()

    def _maybe_flush(self) -> None:
        if time.time() - self._last_flush >= FLUSH_SECONDS or len(self._files) >= FLUSH_ROWS:
            self.flush()

    def _progress(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_progress < PROGRESS_SECONDS:
            return
        self._last_progress = now
        el = max(now - self.start, 1e-6)
        rt.log("PROGRESS", f"폴더 {self.run['dirs']:,}개, 파일 {self.run['files']:,}개, {rt.human_size(self.run['bytes'])}, "
                           f"초당 {self.run['files'] / el:,.0f}개 ({el:.0f}초)")

    def limit_reached(self) -> Optional[str]:
        if self.max_files is not None and self.run["files"] >= self.max_files:
            return "max_files"
        if self.time_limit is not None and time.time() - self.start >= self.time_limit:
            return "time_limit"
        return None

    # --- 전체 -------------------------------------------------------------
    def run_until_done(self) -> Optional[str]:
        """대기 중인 폴더가 없을 때까지 읽습니다. 상한에 걸리면 그 이유를 돌려줍니다 (None이면 완료)."""
        while True:
            batch = self.con.execute("SELECT id, path, depth FROM dirs WHERE status='pending' ORDER BY id LIMIT ?",
                                     (DIR_BATCH,)).fetchall()
            if not batch:
                self.flush()
                return None
            for dir_id, path, depth in batch:
                self.scan_dir(dir_id, path, depth)
                self._maybe_flush()
                self._progress()
                if self.throttle:
                    time.sleep(self.throttle)
                reason = self.limit_reached()
                if reason:
                    self.flush()
                    return reason
            self.flush()        # 다음 묶음 조회 전에 새 하위 폴더를 DB에 반영


def elapsed(scanner: Scanner) -> float:
    return round(time.time() - scanner.start, 1)


def option_snapshot(args: Any) -> Dict[str, Any]:
    return {"exclude": list(args.exclude or []), "max_depth": args.max_depth,
            "include_system": bool(args.include_system), "include_cloud": bool(args.include_cloud)}


def describe_options(opts: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if opts.get("exclude"):
        out.append("제외 " + ", ".join(opts["exclude"]))
    if opts.get("max_depth") is not None:
        out.append(f"깊이 {opts['max_depth']}까지")
    if opts.get("include_system"):
        out.append("시스템 폴더 포함")
    if opts.get("include_cloud"):
        out.append("클라우드 폴더 포함")
    return out


def resume_args(job: str, extra: Sequence[str] = ()) -> List[str]:
    return ["scan", "--job", job, "--resume", *extra]
