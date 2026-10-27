"""작업(job) 저장소: SQLite 파일 하나 = 작업 하나.

- 메모리가 파일 수와 무관하도록 모든 목록은 DB에 묶음 단위로 기록합니다.
- 방문할 폴더 대기열도 DB(dirs.status='pending')에 두어, 폴더가 수백만 개여도 메모리가 일정하고
  어느 시점에 끊겨도 커밋된 지점부터 이어서 할 수 있습니다.
- classify/peek 단계가 채울 열(kind, category ...)도 미리 만들어 둡니다 (스키마 변경 없이 단계 추가).
"""
import json
import ntpath
import os
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional

import _dc_runtime as rt

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS dirs (
    id INTEGER PRIMARY KEY,
    parent_id INTEGER,
    path TEXT NOT NULL UNIQUE,
    depth INTEGER NOT NULL,
    status TEXT NOT NULL,            -- pending | done | skipped | error
    reason TEXT,                     -- skipped/error 이유
    files INTEGER DEFAULT 0,
    bytes INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS dirs_status ON dirs(status, id);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    dir_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    ext TEXT NOT NULL,               -- 소문자, 점 포함 (".pdf"), 없으면 ""
    size INTEGER,
    mtime REAL,
    ctime REAL,                      -- 만든 날짜 (Windows)
    attrs INTEGER,                   -- Windows 파일 속성 원값
    flags TEXT,                      -- hidden,system,readonly,offline,cloud,reparse (쉼표 구분)
    no_read INTEGER DEFAULT 0,       -- 1이면 peek에서 절대 열지 않음 (클라우드 자리표시자, 오프라인, 링크)
    kind TEXT, category TEXT, confidence TEXT, matches TEXT,          -- classify 단계
    peek_status TEXT, peek_excerpt TEXT                                -- peek 단계
);
CREATE INDEX IF NOT EXISTS files_dir ON files(dir_id);
"""

_JOB_RE = re.compile(r'[\\/:*?"<>|\s]+')


def job_name_for(root: str) -> str:
    """기본 작업 이름: 대상 폴더 이름(드라이브면 'D드라이브') + 날짜.

    운영 환경은 Windows이므로 호스트 OS와 무관하게 Windows 경로 규칙(ntpath)으로 자른다.
    """
    base = ntpath.basename(ntpath.normpath(root))
    if not base:
        drive = ntpath.splitdrive(root)[0].rstrip(":")
        base = f"{drive}드라이브" if drive else "root"
    return f"{safe_job(base)}_{rt.timestamp()[:8]}"


def safe_job(name: str) -> str:
    name = _JOB_RE.sub("_", str(name).strip()).strip("._")
    if not name:
        raise rt.InputError("--job 이름이 비어 있습니다.")
    return name[:80]


def db_path(job: str) -> str:
    return os.path.join(rt.get_data_dir(), f"{safe_job(job)}.db")


def list_jobs() -> List[str]:
    return sorted(f[:-3] for f in os.listdir(rt.get_data_dir()) if f.endswith(".db"))


def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30, isolation_level=None)   # 트랜잭션은 직접 BEGIN/COMMIT
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute("PRAGMA cache_size=-20000")       # 약 20MB
    con.executescript(SCHEMA)
    return con


def open_job(job: str, must_exist: bool = True) -> sqlite3.Connection:
    path = db_path(job)
    if must_exist and not os.path.exists(path):
        raise rt.not_found("작업", job, list_jobs())
    return connect(path)


def get_meta(con: sqlite3.Connection) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in con.execute("SELECT key, value FROM meta"):
        try:
            out[k] = json.loads(v)
        except Exception:
            out[k] = v
    return out


def set_meta(con: sqlite3.Connection, **values: Any) -> None:
    con.executemany("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    [(k, json.dumps(v, ensure_ascii=False)) for k, v in values.items()])


class JobLock:
    """같은 작업을 두 프로세스가 동시에 돌리지 못하게 하는 OS 파일 잠금 (프로세스가 죽으면 자동 해제)."""

    def __init__(self, job: str):
        self.path = db_path(job) + ".lock"
        self.fh = None

    def __enter__(self) -> "JobLock":
        self.fh = open(self.path, "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            raise rt.InputError("같은 작업이 다른 곳에서 실행 중입니다. 끝난 뒤 다시 실행하세요.")
        return self

    def __exit__(self, *exc: Any) -> None:
        if self.fh is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self.fh.close()
            try:
                os.remove(self.path)
            except OSError:
                pass


def scan_counts(con: sqlite3.Connection) -> Dict[str, Any]:
    """폴더 상태별 수, 파일 수와 용량, 열지 말아야 할 파일 수."""
    dirs = {s: n for s, n in con.execute("SELECT status, COUNT(*) FROM dirs GROUP BY status")}
    files, size, no_read = con.execute("SELECT COUNT(*), COALESCE(SUM(size), 0), COALESCE(SUM(no_read), 0) FROM files").fetchone()
    return {"dirs_done": dirs.get("done", 0), "dirs_pending": dirs.get("pending", 0),
            "dirs_skipped": dirs.get("skipped", 0), "dirs_error": dirs.get("error", 0),
            "files": files, "bytes": size, "size": rt.human_size(size), "no_read_files": no_read}


def by_extension(con: sqlite3.Connection, top: int = 15) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT ext, COUNT(*) AS n, COALESCE(SUM(size), 0) FROM files GROUP BY ext ORDER BY n DESC LIMIT ?",
                       (top,)).fetchall()
    return [{"ext": e or "(없음)", "files": n, "size": rt.human_size(b)} for e, n, b in rows]


def dir_samples(con: sqlite3.Connection, status: str, limit: int = 5) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT path, reason FROM dirs WHERE status=? ORDER BY id LIMIT ?", (status, limit)).fetchall()
    return [{"path": p, "reason": r} for p, r in rows]


def reason_counts(con: sqlite3.Connection, status: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for reason, n in con.execute("SELECT reason, COUNT(*) FROM dirs WHERE status=? GROUP BY reason", (status,)):
        key = (reason or "").split(":")[0] or "기타"
        out[key] = out.get(key, 0) + n
    return out


def job_summary(job: str) -> Optional[Dict[str, Any]]:
    """jobs 목록용 요약 (DB를 열 수 없으면 None)."""
    try:
        con = connect(db_path(job))
    except sqlite3.Error:
        return None
    try:
        meta = get_meta(con)
        c = scan_counts(con)
        return {"job": job, "root": meta.get("root"), "scan_status": meta.get("scan_status"),
                "files": c["files"], "size": c["size"], "dirs_pending": c["dirs_pending"],
                "updated_at": meta.get("updated_at"), "db_file": db_path(job)}
    finally:
        con.close()
