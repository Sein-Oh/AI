"""doc-classifier: 폴더 전체 파일 목록화 -> 파일명 분류 -> 표본 확인 -> 요약/엑셀 (Windows 11, 12TB급 대비).

    python doc_classifier.py scan     --root "D:\\자료" [--job 이름] [--resume] [--time-limit 3600]
    python doc_classifier.py classify --job 이름 [--rules rules.json]
    python doc_classifier.py peek     --job 이름 [--per-category 20] [--max-files 500] [--timeout 10]
    python doc_classifier.py summary  --job 이름 [--save 보고서.xlsx]
    python doc_classifier.py list     --job 이름 [--category 회의록] [--ext hwp] [--since 2025-01] [--page 2]
    python doc_classifier.py jobs
"""
import datetime as dt
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _dc_classify as cl  # noqa: E402
import _dc_peek as pk  # noqa: E402
import _dc_report as rp  # noqa: E402
import _dc_rules as ru  # noqa: E402
import _dc_runtime as rt  # noqa: E402
import _dc_scan as sc  # noqa: E402
import _dc_store as st  # noqa: E402

STOP_TEXT = {"max_files": "--max-files 상한", "time_limit": "--time-limit 시간 상한", "interrupted": "사용자 중단"}
EXAMPLE_RULES = os.path.join(rt.TOOL_DIR, "rules.example.json")


def classify_next(job: str) -> List[Dict[str, Any]]:
    """[0] 사용자 규칙 파일로 분류 (경로 필요), [1] 규칙 파일이 없을 때 예시 규칙으로 분류."""
    return [rt.next_command(["classify", "--job", job, "--rules", "<규칙 JSON 경로>"], "사용자 규칙 파일로 파일명 분류",
                            needs_input=True, placeholder="<규칙 JSON 경로>"),
            rt.next_command(["classify", "--job", job], "규칙 파일이 없으면: 예시 규칙(rules.example.json)으로 분류")]


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
        result["next_commands"] = classify_next(job)
        directive = ("VERIFIED: 목록화가 끝났습니다. preview를 사용자에게 보고하세요. 같은 명령을 다시 실행하지 마세요. "
                     "사용자가 분류를 원하면 규칙 파일이 있을 때 next_commands[0], 없으면 next_commands[1]을 실행하세요.")
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
# classify
# ==============================================================================

def _open_scanned(job: str) -> Any:
    con = st.open_job(st.safe_job(job))
    meta = st.get_meta(con)
    if not meta.get("root"):
        con.close()
        raise rt.InputError(f"작업 '{job}'에 목록화 정보가 없습니다. scan부터 실행하세요.")
    return con, meta


def _rules_path(args, meta: Dict[str, Any]) -> str:
    """--rules > 이전 classify에 쓴 규칙 파일 > 예시 규칙."""
    if args.rules:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(args.rules)))
    prev = (meta.get("rules") or {}).get("path")
    if prev and os.path.exists(prev):
        return prev
    return EXAMPLE_RULES


def cmd_classify(args) -> Dict[str, Any]:
    job = st.safe_job(args.job)
    con, meta = _open_scanned(job)
    try:
        rules = ru.load_rules(_rules_path(args, meta))
        for w in rules.warnings:
            rt.log("WARN", w)
        with st.JobLock(job):
            rt.log("INFO", f"분류 시작: 작업 {job}, 규칙 {rules.path} (카테고리 {len(rules.categories)}개)")
            try:
                run = cl.run(con, job, rules, meta)
            except KeyboardInterrupt:
                payload = rt.error_payload(KeyboardInterrupt(), "classify")
                payload.update(job=job, preview=f"분류 중단 [{job}]: 다시 실행하면 처음부터 분류합니다 (디스크는 읽지 않음).",
                               next_commands=[rt.next_command(["classify", "--job", job, "--rules", rules.path], "분류 다시 실행")],
                               _exit=130)
                return payload
        meta = st.get_meta(con)
        cats = cl.category_counts(con, rules.names)
        total = sum(c["files"] for c in cats)
        un = next((c["files"] for c in cats if c["category"] == ru.UNCLASSIFIED), 0)
        est = cl.peek_estimate(con, rules)
        scan_complete = meta.get("scan_status") == "complete"
        top = sorted((c for c in cats if c["category"] != ru.UNCLASSIFIED and c["files"]), key=lambda c: -c["files"])[:5]
        preview = f"분류 완료 [{job}]: 파일 {total:,}개 중 {total - un:,}개 분류, 미분류 {un:,}개({un * 100 / max(total, 1):.0f}%)"
        if top:
            preview += ". " + ", ".join(f"{c['category']} {c['files']:,}" for c in top)
        if not scan_complete:
            preview += " (목록화가 끝나지 않은 작업: 지금까지 목록화된 파일만 분류)"
        if run["peek_cleared"]:
            preview += f" 규칙이 바뀌어 이전 확인(peek) 결과 {run['peek_cleared']}개를 지웠습니다."
        nexts = [rt.next_command(["peek", "--job", job], f"분류별 표본 {est['files']}개를 살짝 읽어 확인 (약 {cl.time_text(est['seconds_estimate'])})"),
                 rt.next_command(["summary", "--job", job, "--save"], "요약과 엑셀 보고서")]
        if not scan_complete:
            nexts.insert(0, rt.next_command(sc.resume_args(job), "남은 폴더 이어서 목록화"))
        dups = dict(run["duplicates"])
        dups["examples"] = dups.get("examples", [])[:3]
        return rt.ok("classify", preview,
                     "VERIFIED: 분류가 끝났습니다. preview를 사용자에게 보고하세요. 규칙을 바꿨을 때만 다시 실행합니다. "
                     "내용 확인은 next_commands의 peek, 보고서는 summary.",
                     job=job, db_file=st.db_path(job), rules_file=rules.path, rules_warnings=rules.warnings,
                     scan_complete=scan_complete, this_run={"files": run["files"], "seconds": run["seconds"],
                                                            "files_per_sec": run["files_per_sec"]},
                     by_category=cats, by_kind=cl.kind_counts(con), keyword_hits=run["keyword_hits"],
                     unclassified_words=run["unclassified_words"][:15], duplicates=dups,
                     peek_estimate=est, peak_memory_mb=sc.peak_memory_mb(), next_commands=nexts)
    finally:
        con.close()


# ==============================================================================
# peek
# ==============================================================================

def cmd_peek(args) -> Dict[str, Any]:
    job = st.safe_job(args.job)
    for name in ("per_category", "max_files"):
        if getattr(args, name) < 1:
            raise rt.InputError(f"--{name.replace('_', '-')}는 1 이상이어야 합니다.")
    if args.timeout <= 0:
        raise rt.InputError("--timeout은 0보다 커야 합니다.")
    con, meta = _open_scanned(job)
    try:
        meta = st.require_classified(con, job, "peek")
        rules = rp.rules_from_meta(meta)
        with st.JobLock(job):
            if args.redo:
                con.execute("BEGIN")
                con.execute("UPDATE files SET peek_status=NULL, peek_excerpt=NULL, peek_category=NULL, peek_reason=NULL, "
                            "peek_ms=NULL WHERE peek_status IS NOT NULL")
                con.execute("COMMIT")
            samples = pk.select_samples(con, rules, args.per_category, args.max_files, int(args.max_mb * 1024 * 1024))
            rt.log("INFO", f"표본 {len(samples)}개 확인 시작 (파일당 {args.timeout:g}초, {args.max_mb:g}MB 상한)")
            run = pk.run(con, rules, samples, args.timeout, args.time_limit, args.throttle_ms, rt.log, st.full_path)
            peeked = con.execute("SELECT COUNT(*) FROM files WHERE peek_status IS NOT NULL").fetchone()[0]
            con.execute("BEGIN")
            st.set_meta(con, peek_files=peeked, peeked_at=dt.datetime.now().isoformat(timespec="seconds"),
                        updated_at=dt.datetime.now().isoformat(timespec="seconds"))
            con.execute("COMMIT")
        overview = rp.peek_overview(con, rules)
        stats = overview["by_category"]
        weak = [s["category"] for s in stats if s.get("confirm_rate") is not None and s["judged"] >= 3
                and s["confirm_rate"] < 0.5 and s["category"] != ru.UNCLASSIFIED]
        rate = overview["confirm_rate"]
        preview = (f"표본 확인 [{job}]: 이번 {run['files']}개 읽음({run['seconds']}초), 누적 {peeked}개, "
                   f"확인율 {rp.rate_text(rate)}. "
                   + ", ".join(f"{pk.STATUS_TEXT.get(k, k)} {v}" for k, v in overview["by_status"].items()))
        if weak:
            preview += f". 확인율 낮은 분류: {', '.join(weak)}"
        if not samples and not peeked:
            preview = f"표본 확인 [{job}]: 읽을 수 있는 표본이 없습니다 (문서 형식 파일이 없거나 모두 열지 않을 파일)."
        result = dict(job=job, db_file=st.db_path(job), complete=run["stopped"] is None, peak_memory_mb=sc.peak_memory_mb(),
                      stopped_reason=run["stopped"], this_run=run, totals=overview,
                      changed_examples=rp.changed_examples(con, 10), weak_categories=weak,
                      next_commands=[rt.next_command(["summary", "--job", job, "--save"], "요약과 엑셀 보고서")])
        again = rt.next_command(["peek", "--job", job, "--per-category", args.per_category, "--max-files", args.max_files],
                                "남은 표본 이어서 확인")
        if run["stopped"] == "interrupted":
            payload = rt.error_payload(KeyboardInterrupt(), "peek")
            payload.update(result, preview=preview, next_commands=[again], _exit=130)
            return payload
        if run["stopped"]:
            result["next_commands"].insert(0, again)
            return rt.ok("peek", preview + f" ({STOP_TEXT.get(run['stopped'], run['stopped'])}로 일부만 확인, 저장됨)",
                         "VERIFIED: 시간 상한으로 일부만 확인했습니다(저장됨). 사용자에게 알리고, 계속하려면 next_commands[0]을 실행하세요.",
                         **result)
        return rt.ok("peek", preview,
                     "VERIFIED: 표본 확인이 끝났습니다. preview를 사용자에게 보고하세요. 같은 명령을 다시 실행하지 마세요. "
                     "확인율이 낮은 분류는 규칙을 고친 뒤 classify부터 다시 합니다.", **result)
    finally:
        con.close()


# ==============================================================================
# summary / list
# ==============================================================================

def _default_report_path(job: str) -> str:
    return os.path.join(rt.get_data_dir(), f"{job}_보고서.xlsx")


def cmd_summary(args) -> Dict[str, Any]:
    job = st.safe_job(args.job)
    con, meta = _open_scanned(job)
    try:
        meta = st.require_classified(con, job, "summary")
        s = rp.build_summary(con, job, meta, top=args.top)
        nexts: List[Dict[str, Any]] = []
        if args.save is not None:
            path = os.path.abspath(args.save) if args.save else _default_report_path(job)
            if os.path.splitext(path)[1].lower() != ".xlsx":
                raise rt.InputError(f"보고서는 .xlsx로만 저장합니다: {path}. [추천] {os.path.splitext(path)[0]}.xlsx")
            if os.path.isdir(path):
                raise rt.InputError(f"--save에 폴더를 주었습니다: {path}. 파일 이름(.xlsx)을 지정하세요.")
            s["report"] = rp.write_report(con, job, meta, s, path, args.file_list)
        else:
            nexts.append(rt.next_command(["summary", "--job", job, "--save"], "엑셀 보고서 저장"))
        if not meta.get("peek_files"):
            nexts.append(rt.next_command(["peek", "--job", job], "분류별 표본을 살짝 읽어 분류 확인"))
        biggest = next((c["category"] for c in sorted(s["by_category"], key=lambda c: -c["files"])
                        if c["category"] != ru.UNCLASSIFIED and c["files"]), None)
        nexts.append(rt.next_command(["list", "--job", job, "--category", "<카테고리>"], "한 카테고리의 파일 목록 보기",
                                     needs_input=True, placeholder="<카테고리>"))
        tot = s["totals"]
        un = next((c for c in s["by_category"] if c["category"] == ru.UNCLASSIFIED), {"files": 0, "share": 0})
        top = sorted((c for c in s["by_category"] if c["category"] != ru.UNCLASSIFIED and c["files"]), key=lambda c: -c["files"])[:5]
        preview = f"요약 [{job}]: 파일 {tot['files']:,}개 {tot['size']}, 미분류 {un['files']:,}개({un['share']}%)"
        if top:
            preview += ". " + ", ".join(f"{c['category']} {c['files']:,}개({c['size']})" for c in top)
        if s.get("peek"):
            r = s["peek"]["confirm_rate"]
            preview += f". 표본 확인율 {rp.rate_text(r)}"
        if s.get("report"):
            preview += f". 보고서: {s['report']['report_file']}"
            if s["report"].get("file_list_files"):
                preview += f" (파일 목록은 CSV {len(s['report']['file_list_files'])}개: {s['report']['file_list_files'][0]}"
                preview += " 등)" if len(s["report"]["file_list_files"]) > 1 else ")"
        s["example_category"] = biggest
        s["peak_memory_mb"] = sc.peak_memory_mb()
        s["next_commands"] = nexts
        return rt.ok("summary", preview,
                     "VERIFIED: 요약이 끝났습니다. preview와 recommendations를 사용자에게 보고하세요"
                     + (" (보고서 경로는 file:/// 링크로)." if s.get("report") else ".") + " 같은 명령을 다시 실행하지 마세요.", **s)
    finally:
        con.close()


def cmd_list(args) -> Dict[str, Any]:
    job = st.safe_job(args.job)
    if args.page < 1 or not 1 <= args.page_size <= 1000:
        raise rt.InputError("--page는 1 이상, --page-size는 1~1000이어야 합니다.")
    con, meta = _open_scanned(job)
    try:
        if args.category or args.confidence:
            meta = st.require_classified(con, job, "--category/--confidence 조회")
        known = rp.rules_from_meta(meta).names + [ru.UNCLASSIFIED] if meta.get("rules_text") else [ru.UNCLASSIFIED]
        res = rp.list_files(con, args, known)
        nexts: List[Dict[str, Any]] = []
        if res["page"] < res["pages"]:
            argv = [a for a in (args._argv or []) if a]
            nexts.append(rt.next_command(_with_page(argv, res["page"] + 1), f"다음 페이지 ({res['page'] + 1}/{res['pages']})"))
        reader = os.path.join(os.path.dirname(rt.TOOL_DIR), "atomic-cli", "reader.py")
        if os.path.exists(reader) and res["items"]:
            item = {"purpose": "파일 하나의 내용 읽기 (atomic-cli)", "needs_input": True, "placeholder": "<파일 경로>",
                    "command": f"python {rt.quote_arg(reader)} read --file \"<파일 경로>\""}
            nexts.append(item)
        cond = ", ".join(f"{k}={v}" for k, v in res["filters"].items()) or "조건 없음"
        preview = (f"파일 목록 [{job}] ({cond}): {res['total']:,}개 {res['total_size']}, "
                   f"{res['page']}/{res['pages']}쪽 {len(res['items'])}개")
        return rt.ok("list", preview,
                     "VERIFIED: 목록 조회가 끝났습니다. 사용자에게 필요한 만큼만 보고하세요. 더 보려면 next_commands의 다음 페이지를 실행하세요.",
                     job=job, next_commands=nexts, **res)
    finally:
        con.close()


def _with_page(argv: List[str], page: int) -> List[str]:
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a == "--page":
            skip = True
            continue
        if a.startswith("--page="):
            continue
        out.append(a)
    return out + ["--page", str(page)]


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

    p = sub.add_parser("classify", help="파일명/확장자/폴더명 규칙으로 분류 (디스크를 읽지 않음)")
    p.add_argument("--job", required=True, help="작업 이름 (jobs로 확인)")
    p.add_argument("--rules", help='규칙 JSON {"카테고리": ["키워드", ".확장자"]} (생략 시 지난번 규칙, 없으면 rules.example.json)')

    p = sub.add_parser("peek", help="분류별 표본만 앞부분을 읽어 분류 확인")
    p.add_argument("--job", required=True, help="작업 이름")
    p.add_argument("--per-category", type=int, default=20, help="카테고리마다 확인할 표본 수 (기본 20, 미분류 포함)")
    p.add_argument("--max-files", type=int, default=500, help="이번 실행 전체 표본 상한 (기본 500)")
    p.add_argument("--timeout", type=float, default=10.0, help="파일당 시간 상한(초, 기본 10). 넘으면 건너뜀")
    p.add_argument("--max-mb", type=float, default=200.0, help="이보다 큰 파일은 표본에서 뺌 (기본 200MB)")
    p.add_argument("--time-limit", type=float, help="이번 실행 시간 상한(초). 넘으면 멈춤 (다시 실행하면 이어서)")
    p.add_argument("--throttle-ms", type=int, default=0, help="파일마다 쉬는 시간(ms)")
    p.add_argument("--redo", action="store_true", help="이전 확인 결과를 지우고 표본을 새로 고름")

    p = sub.add_parser("summary", help="분류별 개수·용량·확인 결과 요약, 엑셀 보고서")
    p.add_argument("--job", required=True, help="작업 이름")
    p.add_argument("--save", nargs="?", const="", help="엑셀 보고서 저장 (경로 생략 시 data\\<작업>_보고서.xlsx)")
    p.add_argument("--file-list", choices=["auto", "xlsx", "csv", "none"], default="auto",
                   help="보고서의 전체 파일 목록 (auto: 10만 개 이하는 엑셀 시트, 넘으면 104만 행씩 나눈 CSV)")
    p.add_argument("--top", type=int, default=10, help="JSON에 넣을 상위 폴더 수 (기본 10)")

    p = sub.add_parser("list", help="조건으로 파일 목록 조회 (페이지 단위)")
    p.add_argument("--job", required=True, help="작업 이름")
    p.add_argument("--category", help="카테고리 (쉼표로 여러 개, 미분류 가능)")
    p.add_argument("--ext", help="확장자 (쉼표로 여러 개, 예: hwp,hwpx)")
    p.add_argument("--kind", help="형식 (문서, 표, 발표, PDF, 한글, 메일, 이미지, 도면, 압축 ...)")
    p.add_argument("--confidence", choices=["high", "medium", "low"], help="분류 신뢰도")
    p.add_argument("--peek", choices=["any", "confirmed", "changed", "no_match", "no_text", "encrypted_or_drm",
                                      "unreadable", "timeout", "missing", "skipped", "not_checked"], help="확인 결과")
    p.add_argument("--since", help="수정일 시작 (2025, 2025-03, 2025-03-15)")
    p.add_argument("--until", help="수정일 끝 (그 기간 포함)")
    p.add_argument("--folder", help="폴더 (절대 경로면 그 폴더와 하위, 아니면 경로에 포함된 글자)")
    p.add_argument("--name", help="파일명에 포함된 글자")
    p.add_argument("--min-size", help="최소 크기 (예: 100MB)")
    p.add_argument("--flag", choices=["copy", "temp"], help="파일명 표시 (copy: 사본, temp: 임시)")
    p.add_argument("--sort", choices=list(rp.SORTS), default="path", help="정렬 (기본 path)")
    p.add_argument("--desc", action="store_true", help="내림차순")
    p.add_argument("--page", type=int, default=1, help="페이지 (1부터)")
    p.add_argument("--page-size", type=int, default=100, help="페이지당 행 수 (기본 100, 최대 1000)")

    sub.add_parser("jobs", help="작업 목록과 진행 상태")
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    rt.setup_console()
    args = build_cli().parse_args(argv)
    args._argv = list(argv) if argv is not None else sys.argv[1:]
    handler = {"scan": cmd_scan, "classify": cmd_classify, "peek": cmd_peek, "summary": cmd_summary, "list": cmd_list,
               "jobs": cmd_jobs}[args.command]
    rt.run_cli(args.command, lambda: handler(args))


if __name__ == "__main__":
    main()
