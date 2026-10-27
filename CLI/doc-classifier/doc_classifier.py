"""doc-classifier: 폴더 전체 파일 목록화 -> 파일명 분류 -> 표본 확인 (Windows 11, 12TB급 대비).

현재 구현: scan(목록화), jobs(작업 목록). classify / peek / summary / list는 WORK_PLAN.md 2~4단계.

    python doc_classifier.py scan --root "D:\\자료" [--job 이름] [--resume] [--time-limit 3600]
    python doc_classifier.py jobs
"""
import datetime as dt
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _dc_runtime as rt  # noqa: E402
import _dc_scan as sc  # noqa: E402
import _dc_store as st  # noqa: E402

STOP_TEXT = {"max_files": "--max-files 상한", "time_limit": "--time-limit 시간 상한", "interrupted": "사용자 중단"}


# ==============================================================================
# scan
# ==============================================================================

def _resolve_root(raw: str) -> str:
    root = os.path.abspath(os.path.expandvars(os.path.expanduser(raw)))
    if root.endswith(":"):                       # "D:" -> "D:\"
        root += os.sep
    if not os.path.exists(sc.to_fs(root)):
        raise rt.InputError(f"폴더를 찾을 수 없습니다: {root}")
    if not os.path.isdir(sc.to_fs(root)):
        raise rt.InputError(f"폴더가 아니라 파일입니다: {root}. --root에는 폴더를 지정하세요.")
    return root


def _same_path(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a and b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _find_resumable(root: str) -> Optional[str]:
    """같은 폴더를 대상으로 끝나지 않은 가장 최근 작업."""
    found = []
    for job in st.list_jobs():
        s = st.job_summary(job)
        if s and _same_path(s.get("root"), root) and s.get("scan_status") != "complete":
            found.append((s.get("updated_at") or "", job))
    return max(found)[1] if found else None


def _remove_db(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass


def _prepare_job(args) -> Dict[str, Any]:
    """작업 이름/DB를 정하고 새로 시작할지 이어서 할지 판단합니다."""
    root = _resolve_root(args.root) if args.root else None
    job = st.safe_job(args.job) if args.job else None
    if args.resume and not job:
        if not root:
            raise rt.InputError("--resume에는 --job 또는 --root가 필요합니다.")
        job = _find_resumable(root)
        if not job:
            raise rt.InputError(f"이어서 할 작업이 없습니다 ({root}). --resume 없이 새로 시작하세요.")
    if not job:
        if not root:
            raise rt.InputError("--root(목록을 만들 폴더)를 지정하세요.")
        job = st.job_name_for(root)
    path = st.db_path(job)
    exists = os.path.exists(path)

    if args.resume:
        if not exists:
            raise rt.not_found("작업", job, st.list_jobs())
        con = st.connect(path)
        meta = st.get_meta(con)
        if root and not _same_path(meta.get("root"), root):
            con.close()
            raise rt.InputError(f"작업 '{job}'의 대상 폴더는 {meta.get('root')}입니다 (--root {root}와 다름).")
        if meta.get("scan_status") == "complete":
            con.close()
            raise rt.InputError(f"작업 '{job}'은(는) 이미 목록화가 끝났습니다. 다시 하려면 --overwrite를 쓰세요.")
        return {"job": job, "path": path, "con": con, "root": meta["root"], "options": meta.get("options") or {},
                "resumed": True}

    if exists and not args.overwrite:
        con = st.connect(path)
        meta = st.get_meta(con)
        con.close()
        if meta.get("scan_status") != "complete":
            err = rt.InputError(f"작업 '{job}'이(가) 끝나지 않은 채 있습니다. 이어서 하려면 --resume, 처음부터 하려면 --overwrite를 쓰세요. "
                                f"[추천] {rt.next_command(sc.resume_args(job), '이어서 목록화')['command']}")
        else:
            err = rt.InputError(f"작업 '{job}'이(가) 이미 있습니다. 다시 하려면 --overwrite, 따로 두려면 다른 --job 이름을 쓰세요.")
        raise err
    if not root:
        raise rt.InputError("새 작업에는 --root(목록을 만들 폴더)가 필요합니다.")
    if exists:
        _remove_db(path)
    con = st.connect(path)
    options = sc.option_snapshot(args)
    con.execute("BEGIN")
    st.set_meta(con, schema_version=st.SCHEMA_VERSION, job=job, root=root, options=options, scan_status="scanning",
                created_at=dt.datetime.now().isoformat(timespec="seconds"))
    con.execute("INSERT INTO dirs(parent_id, path, depth, status) VALUES (NULL, ?, 0, 'pending')", (root,))
    con.execute("COMMIT")
    return {"job": job, "path": path, "con": con, "root": root, "options": options, "resumed": False}


def _scan_result(prep: Dict[str, Any], scanner: sc.Scanner, stopped: Optional[str], priority: bool) -> Dict[str, Any]:
    con, job = prep["con"], prep["job"]
    complete = stopped is None
    con.execute("BEGIN")
    st.set_meta(con, scan_status="complete" if complete else "partial", stopped_reason=stopped,
                updated_at=dt.datetime.now().isoformat(timespec="seconds"))
    con.execute("COMMIT")
    counts = st.scan_counts(con)
    secs = sc.elapsed(scanner)
    run = dict(scanner.run, seconds=secs, files_per_sec=round(scanner.run["files"] / secs) if secs else None,
               size=rt.human_size(scanner.run["bytes"]))
    result: Dict[str, Any] = {
        "job": job, "db_file": prep["path"], "root": prep["root"], "resumed": prep["resumed"],
        "complete": complete, "stopped_reason": stopped, "this_run": run, "totals": counts,
        "by_extension": st.by_extension(con),
        "skipped": {"by_reason": st.reason_counts(con, "skipped"), "examples": st.dir_samples(con, "skipped")},
        "errors": {"by_reason": st.reason_counts(con, "error"), "examples": st.dir_samples(con, "error")},
        "options": sc.describe_options(prep["options"]),
        "priority": "background" if priority else "normal", "peak_memory_mb": sc.peak_memory_mb(),
    }
    if complete:
        preview = (f"목록화 완료 [{job}]: 파일 {counts['files']:,}개, {counts['size']}, 폴더 {counts['dirs_done']:,}개 "
                   f"(건너뜀 {counts['dirs_skipped']:,}, 오류 {counts['dirs_error']:,}), {secs}초")
        if counts["no_read_files"]:
            preview += f", 열지 않을 파일 {counts['no_read_files']:,}개(클라우드/링크)"
        result["next_commands"] = []
        directive = ("VERIFIED: 목록화가 끝났습니다. preview를 사용자에게 보고하세요. "
                     "분류(classify)는 아직 구현 전입니다.")
        return rt.ok("scan", preview, directive, **result)
    result["next_commands"] = [rt.next_command(sc.resume_args(job), "남은 폴더 이어서 목록화")]
    preview = (f"목록화 일부 완료 [{job}] ({STOP_TEXT.get(stopped, stopped)}): 파일 {counts['files']:,}개, {counts['size']}, "
               f"남은 폴더 {counts['dirs_pending']:,}개")
    if stopped == "interrupted":
        payload = rt.error_payload(KeyboardInterrupt(), "scan")
        payload.update(result, preview=preview, _exit=130)
        return payload
    directive = ("VERIFIED: 상한에 걸려 일부만 목록화했습니다(저장됨). 사용자에게 알리고, 계속하려면 next_commands[0]을 실행하세요.")
    return rt.ok("scan", preview, directive, **result)


def cmd_scan(args) -> Dict[str, Any]:
    if args.resume and args.overwrite:
        raise rt.InputError("--resume과 --overwrite는 함께 쓸 수 없습니다.")
    for name in ("max_files", "time_limit", "max_depth"):
        v = getattr(args, name)
        if v is not None and v < 0:
            raise rt.InputError(f"--{name.replace('_', '-')}는 0 이상이어야 합니다.")
    prep = _prepare_job(args)
    with st.JobLock(prep["job"]):
        priority = sc.set_background_priority() if args.priority == "background" else False
        scanner = sc.Scanner(prep["con"], prep["options"], max_files=args.max_files,
                             time_limit=args.time_limit, throttle_ms=args.throttle_ms)
        rt.log("INFO", f"{'이어서 ' if prep['resumed'] else ''}목록화 시작: {prep['root']} (작업 {prep['job']})")
        try:
            stopped = scanner.run_until_done()
        except KeyboardInterrupt:
            scanner.flush()             # 끝까지 읽은 폴더만 기록 (읽던 폴더는 다음에 다시)
            stopped = "interrupted"
        scanner._progress(force=True)
        try:
            return _scan_result(prep, scanner, stopped, priority)
        finally:
            prep["con"].close()


# ==============================================================================
# jobs
# ==============================================================================

def cmd_jobs(args) -> Dict[str, Any]:
    items = [s for s in (st.job_summary(j) for j in st.list_jobs()) if s]
    preview = f"작업 {len(items)}개" + (": " + ", ".join(f"{s['job']}({s['scan_status']}, 파일 {s['files']:,})"
                                                       for s in items[:5]) if items else "")
    return rt.ok("jobs", preview, jobs=items, data_dir=rt.get_data_dir())


# ==============================================================================
# 진입점
# ==============================================================================

def build_cli():
    parser, sub = rt.build_parser("폴더 전체 파일 목록화와 분류")
    p = sub.add_parser("scan", help="폴더 트리 목록화 (파일을 열지 않음)")
    p.add_argument("--root", help="목록을 만들 폴더 (예: D:\\자료, D:)")
    p.add_argument("--job", help="작업 이름 (생략 시 폴더명_날짜)")
    p.add_argument("--resume", action="store_true", help="끝나지 않은 작업을 이어서")
    p.add_argument("--overwrite", action="store_true", help="같은 이름의 작업을 지우고 처음부터")
    p.add_argument("--exclude", action="append", help="제외할 경로 패턴 (여러 번 지정 가능, 예: *\\node_modules*)")
    p.add_argument("--max-depth", type=int, help="이 깊이까지만 (대상 폴더 = 0)")
    p.add_argument("--max-files", type=int, help="이번 실행에서 이 파일 수에 도달하면 멈춤 (이어서 가능)")
    p.add_argument("--time-limit", type=float, help="이번 실행 시간 상한(초). 넘으면 멈춤 (이어서 가능)")
    p.add_argument("--throttle-ms", type=int, default=0, help="폴더마다 쉬는 시간(ms). 디스크 부하를 더 줄일 때")
    p.add_argument("--include-system", action="store_true", help="드라이브 바로 아래 Windows/Program Files 등도 포함")
    p.add_argument("--include-cloud", action="store_true", help="클라우드 자리표시자 폴더도 들어감 (파일은 여전히 열지 않음)")
    p.add_argument("--priority", choices=["background", "normal"], default="background",
                   help="프로세스·디스크 우선순위 (기본 background: 업무와 공유 사용자를 방해하지 않음)")
    sub.add_parser("jobs", help="작업 목록과 진행 상태")
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    rt.setup_console()
    args = build_cli().parse_args(argv)
    handler = {"scan": cmd_scan, "jobs": cmd_jobs}[args.command]
    rt.run_cli(args.command, lambda: handler(args))


if __name__ == "__main__":
    main()
