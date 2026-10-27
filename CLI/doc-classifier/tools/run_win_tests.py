"""doc-classifier Windows 실기 테스트 러너 (현재: scan 목록화)

사용법 (CLI/doc-classifier 폴더에서 실행):
    python tools/run_win_tests.py                          # 전체 (실제 드라이브는 D:\\)
    python tools/run_win_tests.py --drive E:\\ --drive-limit 1800
    python tools/run_win_tests.py --only S1,S3 --files 200000

오프라인 pytest가 다루지 못하는 실제 NTFS 동작을 확인합니다.
    S1 대량 트리 속도/정확도        S2 파일 수가 늘어도 메모리 일정    S3 강제 종료 후 재개(중복 없음)
    S4 정션 고리 건너뜀             S5 260자 초과 경로                 S6 다른 프로세스가 독점 중인 파일도 목록에 포함
    S7 실제 드라이브 전체(시스템 폴더 건너뜀, 권한 오류 계속)         S8 시스템 드라이브(C:\\) 시간 상한 후 재개
    S9 모든 호출의 stdout 1줄 JSON
작업 DB는 테스트 폴더의 jobs\\ 에 만들고(DOCCLS_DATA_DIR), 결과는 report_*.txt로 저장합니다.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
CONTRACT = []


class Ctx:
    def __init__(self, args):
        self.args = args
        self.dir = os.path.abspath(args.dir)
        self.jobs = os.path.join(self.dir, "jobs")
        self.results = []

    def path(self, *parts):
        return os.path.join(self.dir, *parts)


def log(msg):
    print(msg, flush=True)


def _parse(proc_out, proc_err, code, label):
    out = proc_out.decode("utf-8", errors="replace")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if len(lines) != 1:
        CONTRACT.append((label, f"stdout {len(lines)}줄"))
    data = None
    if lines:
        try:
            data = json.loads(lines[-1])
        except Exception:
            CONTRACT.append((label, "stdout 마지막 줄이 JSON이 아님"))
    return data, code, proc_err.decode("utf-8", errors="replace")[-1500:]


def env_for(ctx):
    return dict(os.environ, PYTHONIOENCODING="utf-8", DOCCLS_DATA_DIR=ctx.jobs)


def dc(ctx, *args, timeout=7200):
    cmd = [PY, os.path.join(ROOT, "doc_classifier.py")] + [str(a) for a in args]
    log("    $ python doc_classifier.py " + " ".join(str(a) for a in args))
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=timeout, env=env_for(ctx))
    return _parse(p.stdout, p.stderr, p.returncode, "doc_classifier " + (args[0] if args else ""))


def record(ctx, tid, title, ok, detail="", data=None, code=None, err=""):
    status = "PASS" if ok else "FAIL"
    entry = {"id": tid, "title": title, "status": status, "detail": detail, "exit_code": code,
             "json": "" if data is None else json.dumps(data, ensure_ascii=False)[:500]}
    if not ok and err:
        entry["stderr_tail"] = err.strip()[-600:]
    ctx.results.append(entry)
    log(f"  => [{status}] {tid} {title} - {detail}")


def run_test(ctx, tid, title, fn):
    log(f"\n[{tid}] {title}")
    try:
        fn()
    except Exception as e:
        ctx.results.append({"id": tid, "title": title, "status": "ERROR", "detail": f"{type(e).__name__}: {e}",
                            "trace": traceback.format_exc()[-1000:]})
        log(f"  => [ERROR] {tid} {e}")


def ok_(d):
    return (d or {}).get("status") == "ok"


def make_tree(base, n_files, per_dir=100):
    """n_files개 빈 파일을 폴더당 per_dir개, 3단 깊이로 만듭니다. (만든 파일 수)"""
    names = ["보고서", "회의록", "계약서", "견적", "data", "도면", "사양서"]
    exts = [".hwp", ".docx", ".xlsx", ".pdf", ".pptx", ".dwg", ".txt"]
    made = 0
    d = 0
    while made < n_files:
        folder = os.path.join(base, f"부서{d // 100:02d}", f"프로젝트{(d // 10) % 10}", f"폴더{d % 10}_{d}")
        os.makedirs(folder, exist_ok=True)
        for i in range(min(per_dir, n_files - made)):
            k = (made + i) % len(exts)
            with open(os.path.join(folder, f"{names[k]}_{made + i:07d}{exts[k]}"), "wb"):
                pass
        made += min(per_dir, n_files - made)
        d += 1
    return made


def db_check(ctx, job):
    con = sqlite3.connect(os.path.join(ctx.jobs, f"{job}.db"))
    total, distinct = con.execute("SELECT COUNT(*), COUNT(DISTINCT dir_id || '/' || name) FROM files").fetchone()
    con.close()
    return total, distinct


def test_all(ctx, only):
    a = ctx.args
    state = {}

    def s1():
        base = ctx.path("트리_대량")
        t0 = time.time()
        n = make_tree(base, a.files)
        log(f"    (트리 생성 {n:,}개 {time.time() - t0:.0f}초)")
        d, c, e = dc(ctx, "scan", "--root", base, "--job", "s1")
        tot = (d or {}).get("totals", {})
        run = (d or {}).get("this_run", {})
        total, distinct = db_check(ctx, "s1") if ok_(d) else (None, None)
        state["s1_mem"] = d.get("peak_memory_mb") if d else None
        ok = ok_(d) and d.get("complete") and tot.get("files") == n and total == distinct and d.get("priority") == "background"
        record(ctx, "S1", f"대량 트리 {n:,}개 목록화 (개수, 중복 없음, 백그라운드 우선순위)", ok,
               f"파일 {tot.get('files')}, {run.get('seconds')}초, 초당 {run.get('files_per_sec')}개, 최대 메모리 {d.get('peak_memory_mb') if d else None}MB, "
               f"우선순위 {d.get('priority') if d else None}", d, c, e)
        state["base"] = base
        state["n"] = n

    def s2():
        small = ctx.path("트리_소량")
        make_tree(small, max(1000, a.files // 10))
        d, c, e = dc(ctx, "scan", "--root", small, "--job", "s2")
        m_small, m_big = (d or {}).get("peak_memory_mb"), state.get("s1_mem")
        ok = ok_(d) and m_small and m_big and m_big < 200 and m_big < m_small * 2.5
        record(ctx, "S2", "파일 수 10배여도 메모리 일정 (200MB 미만, 2.5배 미만)", ok,
               f"소량 {m_small}MB -> 대량 {m_big}MB", d, c, e)

    def s3():
        base, n = state.get("base"), state.get("n")
        if not base:
            base = ctx.path("트리_대량")
            n = make_tree(base, a.files)
        cmd = [PY, os.path.join(ROOT, "doc_classifier.py"), "scan", "--root", base, "--job", "s3", "--throttle-ms", "3"]
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env_for(ctx))
        time.sleep(3)
        p.kill()                                      # 작업 관리자 '작업 끝내기'와 같은 강제 종료 (자신이 띄운 프로세스)
        p.communicate()
        partial, _ = db_check(ctx, "s3")
        d, c, e = dc(ctx, "scan", "--job", "s3", "--resume")
        total, distinct = db_check(ctx, "s3")
        ok = ok_(d) and d.get("complete") and d.get("resumed") and total == n and total == distinct and 0 < partial < n
        record(ctx, "S3", "목록화 중 강제 종료 -> 재개해 중복 없이 완료", ok,
               f"종료 시점 기록 {partial:,}개 -> 재개 후 {total:,}개 (고유 {distinct:,}, 기대 {n:,})", d, c, e)

    def s4():
        base = ctx.path("정션")
        os.makedirs(os.path.join(base, "a", "b"), exist_ok=True)
        open(os.path.join(base, "a", "b", "1.txt"), "w").close()
        import _winapi
        _winapi.CreateJunction(base, os.path.join(base, "a", "b", "위로"))
        d, c, e = dc(ctx, "scan", "--root", base, "--job", "s4", timeout=120)
        ok = ok_(d) and d["totals"]["files"] == 1 and d["skipped"]["by_reason"] == {"link": 1}
        record(ctx, "S4", "정션 고리(조상을 가리킴) 건너뜀", ok,
               f"파일 {(d or {}).get('totals', {}).get('files')}, 건너뜀 {(d or {}).get('skipped', {}).get('by_reason')}", d, c, e)

    def s5():
        base = ctx.path("긴경로")
        deep = base
        while len(deep) < 320:
            deep = os.path.join(deep, "가나다라마바사아자차카타파하" * 2)
        os.makedirs("\\\\?\\" + deep, exist_ok=True)
        open("\\\\?\\" + os.path.join(deep, "긴 경로 보고서.hwp"), "w").close()
        d, c, e = dc(ctx, "scan", "--root", base, "--job", "s5", timeout=120)
        ok = ok_(d) and d["totals"]["files"] == 1 and d["totals"]["dirs_error"] == 0
        record(ctx, "S5", f"260자 초과 경로({len(deep)}자) 목록화", ok,
               f"파일 {(d or {}).get('totals', {}).get('files')}, 오류 폴더 {(d or {}).get('totals', {}).get('dirs_error')}", d, c, e)

    def s6():
        base = ctx.path("잠긴파일")
        os.makedirs(base, exist_ok=True)
        target = os.path.join(base, "사용중_계약서.docx")
        open(target, "wb").write(b"x" * 1234)
        import win32file
        h = win32file.CreateFile(target, win32file.GENERIC_READ, 0, None, win32file.OPEN_EXISTING, 0, None)   # 공유 없음(독점)
        try:
            d, c, e = dc(ctx, "scan", "--root", base, "--job", "s6", timeout=120)
        finally:
            h.Close()
        ok = ok_(d) and d["totals"]["files"] == 1 and d["totals"]["bytes"] == 1234 and d["this_run"]["entry_errors"] == 0
        record(ctx, "S6", "다른 프로세스가 독점 중인 파일도 목록에 포함 (파일을 열지 않음)", ok,
               f"파일 {(d or {}).get('totals', {}).get('files')}, 크기 {(d or {}).get('totals', {}).get('bytes')}", d, c, e)

    def s7():
        drive = a.drive
        d, c, e = dc(ctx, "scan", "--root", drive, "--job", "s7", "--time-limit", a.drive_limit)
        tot = (d or {}).get("totals", {})
        run = (d or {}).get("this_run", {})
        ok = ok_(d) and (d.get("peak_memory_mb") or 0) < 300
        record(ctx, "S7", f"실제 드라이브 {drive} 목록화 (시간 상한 {a.drive_limit}초)", ok,
               f"완료={d.get('complete') if d else None}, 파일 {tot.get('files')}, {tot.get('size')}, 폴더 {tot.get('dirs_done')}, "
               f"{run.get('seconds')}초, 초당 {run.get('files_per_sec')}개, 메모리 {d.get('peak_memory_mb') if d else None}MB, "
               f"건너뜀 {(d or {}).get('skipped', {}).get('by_reason')}, 오류 {(d or {}).get('errors', {}).get('by_reason')}, "
               f"열지 않을 파일 {tot.get('no_read_files')}", d, c, e)

    def s8():
        d, c, e = dc(ctx, "scan", "--root", "C:\\", "--job", "s8", "--time-limit", "20")
        first_files = (d or {}).get("totals", {}).get("files")
        stopped = (d or {}).get("stopped_reason")
        d2, c2, e2 = dc(ctx, "scan", "--job", "s8", "--resume", "--time-limit", "20")
        skipped = (d2 or {}).get("skipped", {}).get("examples", [])
        sys_skipped = (d2 or {}).get("skipped", {}).get("by_reason", {}).get("system", 0)
        ok = ok_(d) and stopped == "time_limit" and ok_(d2) and (d2 or {}).get("totals", {}).get("files", 0) > first_files \
            and sys_skipped >= 3 and (d2 or {}).get("resumed")
        record(ctx, "S8", "C:\\ 20초 상한 -> 재개로 이어짐, 시스템 폴더(Windows, Program Files 등) 건너뜀", ok,
               f"1차 {first_files}개({stopped}) -> 2차 {(d2 or {}).get('totals', {}).get('files')}개, 시스템 건너뜀 {sys_skipped}개, "
               f"예: {[x['path'] for x in skipped[:4]]}", d2, c2, e2)

    def s9():
        bad = [f"{label}: {problem}" for label, problem in CONTRACT]
        record(ctx, "S9", "모든 호출의 stdout 1줄 JSON", not bad, "위반 없음" if not bad else "; ".join(bad[:10]))

    tests = [("S1", "대량 트리", s1), ("S2", "메모리 일정", s2), ("S3", "강제 종료 후 재개", s3), ("S4", "정션 고리", s4),
             ("S5", "긴 경로", s5), ("S6", "독점 중인 파일", s6), ("S7", "실제 드라이브", s7), ("S8", "C: 상한과 재개", s8),
             ("S9", "출력 계약", s9)]
    for tid, title, fn in tests:
        if only and tid not in only and tid != "S9":
            continue
        run_test(ctx, tid, title, fn)


def write_report(ctx):
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = ctx.path(f"report_{stamp}.txt")
    counts = {}
    for r in ctx.results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = [f"doc-classifier Windows 테스트 보고서 ({stamp})", f"Python {sys.version.split()[0]} / 테스트 폴더 {ctx.dir}",
             "요약: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())), ""]
    for r in ctx.results:
        lines.append(f"[{r['status']}] {r['id']} {r['title']}")
        for key, label in (("detail", "내용"), ("exit_code", "종료코드"), ("json", "JSON"), ("stderr_tail", "stderr(끝부분)"),
                           ("trace", "trace")):
            if r.get(key) not in (None, ""):
                lines.append(f"    {label}: " + str(r[key]).replace("\n", "\n        "))
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path, counts


def main():
    parser = argparse.ArgumentParser(description="doc-classifier Windows 실기 테스트 러너")
    parser.add_argument("--dir", default=r"C:\dc_test", help="테스트 폴더 (실행 때마다 새로 만듦)")
    parser.add_argument("--only", help="실행할 항목 (예: S1,S3)")
    parser.add_argument("--files", type=int, default=100000, help="S1 대량 트리 파일 수 (기본 10만)")
    parser.add_argument("--drive", default="D:\\", help="S7 실제 드라이브 (기본 D:\\)")
    parser.add_argument("--drive-limit", type=int, default=1800, help="S7 시간 상한(초)")
    args = parser.parse_args()
    ctx = Ctx(args)
    shutil.rmtree(ctx.dir, ignore_errors=True)
    os.makedirs(ctx.jobs, exist_ok=True)
    only = {x.strip().upper() for x in args.only.split(",")} if args.only else None
    log("=" * 70)
    log(f" doc-classifier Windows 테스트 / 테스트 폴더: {ctx.dir}")
    log("=" * 70)
    test_all(ctx, only)
    path, counts = write_report(ctx)
    log("\n" + "=" * 70)
    log(" 결과 요약: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for r in ctx.results:
        if r["status"] != "PASS":
            log(f"   [{r['status']}] {r['id']} {r['title']} {r.get('detail', '')}")
    log(f" 보고서: {path}")
    log("=" * 70)


if __name__ == "__main__":
    main()
