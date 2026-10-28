"""scan(목록화) 테스트: 개수 정확성, 중단/재개(중복 없음), 상한, 제외, 링크/권한 오류, 속성 판정, 잠금, 계약."""
import os
import sqlite3
import sys

import pytest

import _dc_scan as sc
import _dc_store as st
import doc_classifier
from dc_tree import make_tree

SPEC = {
    "계약/2026_공급계약서_최종.hwp": 10,
    "계약/2026_공급계약서_최종 (1).hwp": 10,
    "계약/참고/MOU 초안.DOCX": 20,
    "보고/회의록_0301.docx": 30,
    "보고/결과보고.PDF": 40,
    "도면/A-01.dwg": 50,
    "도면/깊은/a/b/c/d/e/f/g/h/i/j/끝.txt": 5,
    "빈폴더": None,
    "확장자없음": 3,
    "보고/~$회의록_0301.docx": 1,
}


def _db(data_dir, job):
    return sqlite3.connect(str(data_dir / f"{job}.db"))


def _no_duplicates(con):
    total, distinct = con.execute("SELECT COUNT(*), COUNT(DISTINCT dir_id || '/' || name) FROM files").fetchone()
    return total == distinct


def test_scan_lists_every_file_with_metadata(tmp_path, run, data_dir):
    root = tmp_path / "자료"
    n = make_tree(str(root), SPEC)
    code, out = run("scan", "--root", str(root), "--job", "t1")
    assert code == 0 and out["complete"] is True and "classify --job t1" in out["next_commands"][1]["command"]
    assert out["totals"]["files"] == n and out["totals"]["dirs_pending"] == 0 and out["totals"]["dirs_error"] == 0
    assert out["totals"]["bytes"] == sum(v for v in SPEC.values() if v)
    con = _db(data_dir, "t1")
    exts = dict(con.execute("SELECT name, ext FROM files"))
    assert exts["MOU 초안.DOCX"] == ".docx" and exts["결과보고.PDF"] == ".pdf" and exts["확장자없음"] == ""
    assert con.execute("SELECT COUNT(*) FROM dirs WHERE path LIKE '%빈폴더' AND status='done'").fetchone()[0] == 1
    assert con.execute("SELECT MAX(depth) FROM dirs").fetchone()[0] == 12
    mtime, = con.execute("SELECT mtime FROM files WHERE name='A-01.dwg'").fetchone()
    assert abs(mtime - os.path.getmtime(root / "도면" / "A-01.dwg")) < 1
    assert {e["ext"] for e in out["by_extension"]} >= {".hwp", ".docx", ".dwg", "(없음)"}


def test_max_files_then_resume_completes_without_duplicates(tmp_path, run, data_dir):
    root = tmp_path / "많음"
    spec = {f"d{i:02d}/f{j}.txt": 1 for i in range(30) for j in range(5)}
    n = make_tree(str(root), spec)
    code, out = run("scan", "--root", str(root), "--job", "big", "--max-files", "20")
    assert code == 0 and out["complete"] is False and out["stopped_reason"] == "max_files"
    nc = out["next_commands"][0]
    assert nc["needs_input"] is False and "--resume" in nc["command"] and "big" in nc["command"]
    for _ in range(20):
        code, out = run("scan", "--job", "big", "--resume", "--max-files", "20")
        assert code == 0
        if out["complete"]:
            break
    assert out["complete"] is True and out["resumed"] is True and out["totals"]["files"] == n
    assert _no_duplicates(_db(data_dir, "big"))


def test_interrupt_saves_progress_exit_130_and_resume_has_no_duplicates(tmp_path, run, data_dir, monkeypatch):
    root = tmp_path / "중단"
    spec = {f"d{i:02d}/f{j}.txt": 1 for i in range(12) for j in range(4)}
    n = make_tree(str(root), spec)
    real = os.scandir
    calls = {"n": 0}

    class Cut:
        """6번째 폴더를 2개 항목까지 읽은 뒤 Ctrl+C (읽던 폴더의 일부가 기록되면 재개 때 중복이 생김)."""
        def __init__(self, it):
            self.it, self.k = it, 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.it.close()

        def __iter__(self):
            for e in self.it:
                self.k += 1
                if self.k == 3:
                    raise KeyboardInterrupt
                yield e

    def flaky(path):
        calls["n"] += 1
        it = real(path)
        return Cut(it) if calls["n"] == 6 else it
    monkeypatch.setattr(sc.os, "scandir", flaky)
    code, out = run("scan", "--root", str(root), "--job", "cut")
    assert code == 130 and out["status"] == "error" and out["error_type"] == "interrupted"
    assert out["agent_directive"].startswith("STOP_RETRY:") and "--resume" in out["next_commands"][0]["command"]
    assert 0 < out["totals"]["files"] < n                                   # 끝까지 읽은 폴더는 저장됨
    monkeypatch.setattr(sc.os, "scandir", real)
    code, out = run("scan", "--root", str(root), "--resume")              # --job 없이 같은 폴더의 미완료 작업 찾기
    assert code == 0 and out["complete"] is True and out["job"] == "cut" and out["totals"]["files"] == n
    assert _no_duplicates(_db(data_dir, "cut"))


def test_existing_job_requires_resume_or_overwrite(tmp_path, run):
    root = tmp_path / "r"
    make_tree(str(root), {"a/1.txt": 1, "b/2.txt": 1})
    run("scan", "--root", str(root), "--job", "j", "--max-files", "1")
    code, out = run("scan", "--root", str(root), "--job", "j")
    assert code == 1 and "--resume" in out["message"] and "[추천]" in out["message"]
    code, out = run("scan", "--job", "j", "--resume")
    assert code == 0 and out["complete"]
    code, out = run("scan", "--root", str(root), "--job", "j")
    assert code == 1 and "--overwrite" in out["message"]
    code, out = run("scan", "--job", "j", "--resume")
    assert code == 1 and "이미 목록화가 끝났습니다" in out["message"]
    code, out = run("scan", "--root", str(root), "--job", "j", "--overwrite")
    assert code == 0 and out["totals"]["files"] == 2 and out["resumed"] is False
    code, out = run("scan", "--job", "없는작업", "--resume")
    assert code == 1 and "사용 가능한 작업: j" in out["message"]          # 비슷한 이름이 없으면 목록 안내


def test_exclude_and_max_depth_are_recorded(tmp_path, run):
    root = tmp_path / "x"
    make_tree(str(root), {"keep/a.txt": 1, "node_modules/lib/b.js": 1, "keep/deep/deeper/c.txt": 1, "tmp.bak": 1})
    code, out = run("scan", "--root", str(root), "--job", "x", "--exclude", "*node_modules*", "--exclude", "*.bak",
                    "--max-depth", "2")
    assert code == 0 and out["totals"]["files"] == 1                         # keep/a.txt만
    assert out["skipped"]["by_reason"] == {"excluded": 1, "max_depth": 1} and out["this_run"]["excluded_files"] == 1
    assert "제외 *node_modules*, *.bak" in out["options"] and "깊이 2까지" in out["options"]


def test_unreadable_folder_is_error_and_scan_continues(tmp_path, run, monkeypatch):
    root = tmp_path / "권한"
    make_tree(str(root), {"ok/a.txt": 1, "secret/b.txt": 1})
    real = os.scandir

    def guarded(path):
        if str(path).endswith("secret"):
            raise PermissionError(13, "액세스가 거부되었습니다")
        return real(path)
    monkeypatch.setattr(sc.os, "scandir", guarded)
    code, out = run("scan", "--root", str(root), "--job", "p")
    assert code == 0 and out["complete"] and out["totals"]["files"] == 1 and out["totals"]["dirs_error"] == 1
    assert out["errors"]["by_reason"] == {"error": 1} and "secret" in out["errors"]["examples"][0]["path"]


def _make_dir_link(link, target):
    if sys.platform == "win32":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))        # 관리자 권한 없이 만들 수 있는 정션
    else:
        os.symlink(target, link, target_is_directory=True)


def test_link_loop_is_skipped(tmp_path, run):
    root = tmp_path / "링크"
    make_tree(str(root), {"a/b/1.txt": 1})
    _make_dir_link(root / "a" / "b" / "위로", root)             # 조상을 가리키는 고리
    code, out = run("scan", "--root", str(root), "--job", "loop")
    assert code == 0 and out["complete"] and out["totals"]["files"] == 1
    assert out["skipped"]["by_reason"] == {"link": 1}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 긴 경로")
def test_long_paths_over_260_chars(tmp_path, run, data_dir):
    root = tmp_path / "긴경로"
    deep = str(root)
    while len(deep) < 300:
        deep = os.path.join(deep, "가나다라마바사아자차" * 2)
    os.makedirs("\\\\?\\" + deep)
    with open("\\\\?\\" + os.path.join(deep, "보고서.txt"), "w") as f:
        f.write("x")
    code, out = run("scan", "--root", str(root), "--job", "long")
    assert code == 0 and out["totals"]["files"] == 1 and out["totals"]["dirs_error"] == 0
    path, = _db(data_dir, "long").execute("SELECT path FROM dirs ORDER BY depth DESC LIMIT 1").fetchone()
    assert len(path) > 260 and not path.startswith("\\\\?\\")


def test_file_flags_mark_cloud_offline_and_links_as_no_read():
    assert sc.file_flags(0, "a.txt") == ("", 0)
    assert sc.file_flags(sc.FA_HIDDEN | sc.FA_SYSTEM | sc.FA_READONLY, "a.txt") == ("hidden,system,readonly", 0)
    flags, no_read = sc.file_flags(sc.FA_RECALL_ON_DATA_ACCESS, "OneDrive.docx")
    assert "cloud" in flags and no_read == 1
    assert sc.file_flags(sc.FA_OFFLINE, "a")[1] == 1 and "offline" in sc.file_flags(sc.FA_OFFLINE, "a")[0]
    assert sc.file_flags(0, "l", sc.IO_REPARSE_TAG_SYMLINK) == ("link", 1)
    assert sc.file_flags(0, "c", 0x9000001A)[1] == 0           # 클라우드 동기화 태그 자체는 링크가 아님


def test_skip_reasons_for_system_and_cloud_folders():
    s = sc.Scanner(None, {})
    assert s.skip_reason("x", "x/$Recycle.Bin", "$Recycle.Bin", 1, 0, 0, False).startswith("system")
    assert s.skip_reason("x", "x/c", "c", 1, sc.FA_RECALL_ON_OPEN, 0, False).startswith("cloud")
    assert s.skip_reason("x", "x/c", "c", 1, sc.FA_HIDDEN | sc.FA_SYSTEM, 0, False).startswith("system")
    assert s.skip_reason("x", "x/c", "c", 1, 0, sc.IO_REPARSE_TAG_MOUNT_POINT, False).startswith("link")
    assert s.skip_reason("x", "x/작업", "작업", 1, 0, 0, False) is None
    if sys.platform == "win32":
        assert s.skip_reason("C:\\", "C:\\Windows", "Windows", 1, 0, 0, False).startswith("system")
        assert s.skip_reason("D:\\자료", "D:\\자료\\Windows", "Windows", 2, 0, 0, False) is None   # 드라이브 바로 아래만
    inc = sc.Scanner(None, {"include_system": True, "include_cloud": True})
    assert inc.skip_reason("x", "x/c", "c", 1, sc.FA_RECALL_ON_OPEN, 0, False) is None


def test_concurrent_scan_of_same_job_is_refused(tmp_path, run):
    root = tmp_path / "잠금"
    make_tree(str(root), {"a.txt": 1})
    with st.JobLock("busy"):
        code, out = run("scan", "--root", str(root), "--job", "busy")
    assert code == 1 and "다른 곳에서 실행 중" in out["message"]


def test_jobs_and_contract_errors(tmp_path, run):
    code, out = run("jobs")
    assert code == 0 and out["jobs"] == []
    root = tmp_path / "j"
    make_tree(str(root), {"a.txt": 1})
    run("scan", "--root", str(root), "--job", "하나")
    code, out = run("jobs")
    assert [j["job"] for j in out["jobs"]] == ["하나"] and out["jobs"][0]["scan_status"] == "complete"
    code, out = run("scan", "--root", str(tmp_path / "없는폴더"))
    assert code == 1 and out["error_type"] == "input" and "찾을 수 없습니다" in out["message"]
    code, out = run("scan", "--root", str(root / "a.txt"))
    assert code == 1 and "파일입니다" in out["message"]
    code, out = run("scan", "--없는옵션")
    assert code == 2 and out["status"] == "error"
    code, out = run("scan", "--root", str(root), "--resume", "--overwrite")
    assert code == 1


def test_default_job_name_from_folder_or_drive():
    assert st.job_name_for(r"D:\자료\2026 계약").startswith("2026_계약_")
    assert st.job_name_for("D:\\").startswith("D드라이브_")
    assert st.job_name_for("D:\\자료\\보고서\\").startswith("보고서_")      # 끝 구분자
    assert st.job_name_for("D:/자료/보고서").startswith("보고서_")              # 슬래시 구분자


def test_failures_are_appended_to_error_log(tmp_path, run, data_dir, monkeypatch):
    log = data_dir / "logs" / "errors.txt"
    run("jobs")
    assert not log.exists()                                                  # 성공은 기록하지 않음
    run("scan", "--root", str(tmp_path / "없는폴더"))
    run("scan", "--없는옵션")
    monkeypatch.setattr(doc_classifier, "cmd_jobs", lambda args: 1 / 0)     # 내부 오류는 traceback까지
    code, out = run("jobs")
    assert code == 1 and out["error_type"] == "internal"
    text = log.read_text(encoding="utf-8")
    assert text.count("=====") == 3 and "doc_classifier 0.9." in text
    assert "명령: scan --root" in text and "찾을 수 없습니다" in text
    assert "명령: scan --없는옵션" in text and "CLI 인자 오류" in text
    assert "ZeroDivisionError" in text and "traceback:" in text and text.count("traceback:") == 1


def test_error_log_rotates_and_never_breaks_output(tmp_path, run, data_dir, monkeypatch):
    import _dc_runtime as rt
    monkeypatch.setattr(rt, "ERROR_LOG_MAX", 10)
    run("scan", "--root", str(tmp_path / "없음1"))
    run("scan", "--root", str(tmp_path / "없음2"))
    logs = data_dir / "logs"
    assert (logs / "errors.old.txt").exists() and "없음2" in (logs / "errors.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(rt, "error_log_path", lambda: str(tmp_path / "없는" / "\0잘못된경로"))
    code, out = run("scan", "--root", str(tmp_path / "없음3"))               # 기록에 실패해도 JSON 응답은 그대로
    assert code == 1 and out["error_type"] == "input"


def test_resume_by_root_refuses_to_guess_between_unfinished_jobs(tmp_path, run, data_dir):
    """AGENTS.md 복구 금지(후보가 둘 이상인 추측): 같은 폴더의 미완료 작업이 둘이면 고르지 않고 [후보]."""
    root = tmp_path / "둘"
    make_tree(str(root), {f"d{i}/f.txt": 1 for i in range(4)})
    run("scan", "--root", str(root), "--job", "첫째", "--max-files", "1")
    run("scan", "--root", str(root), "--job", "둘째", "--max-files", "1")
    code, out = run("scan", "--root", str(root), "--resume")
    assert code == 1 and out["agent_directive"].startswith("STOP_RETRY:") and "재시도하지 말고" in out["agent_directive"]
    assert sorted(out["candidates"]) == ["둘째", "첫째"] and "[후보]" in out["message"] and "[추천]" not in out["message"]
    for job in ("첫째", "둘째"):                                                # 아무 작업도 이어서 하지 않음
        assert st.job_summary(job)["files"] == 1
    code, out = run("scan", "--job", "둘째", "--resume")                       # 사용자가 고르면 그대로
    assert code == 0 and out["complete"] and out["job"] == "둘째"
    code, out = run("scan", "--root", str(root), "--resume")                   # 하나만 남으면 그것을 이어서
    assert code == 0 and out["job"] == "첫째"


def test_scan_dry_run_changes_nothing(tmp_path, run, data_dir):
    root = tmp_path / "미리"
    make_tree(str(root), {"a/1.txt": 1, "b/2.txt": 1})
    code, out = run("scan", "--root", str(root), "--job", "m", "--dry-run")
    assert code == 0 and out["dry_run"] is True and out["planned"] == [f"새 파일: m.db (대상 {root})"]
    assert not (data_dir / "m.db").exists()
    assert out["next_commands"][0]["command"].endswith("scan --root " + rt_quote(str(root)) + " --job m")
    run("scan", "--root", str(root), "--job", "m")
    db = data_dir / "m.db"
    before = (db.stat().st_size, db.stat().st_mtime)
    code, out = run("scan", "--root", str(root), "--job", "m", "--overwrite", "--dry-run")
    assert out["planned"][0].startswith("삭제: m.db (이전 작업: 파일 2개, 목록화 complete") and len(out["planned"]) == 2
    assert (db.stat().st_size, db.stat().st_mtime) == before and st.job_summary("m")["files"] == 2
    code, out = run("scan", "--root", str(root), "--job", "m", "--overwrite")   # 실제 삭제는 applied로 보고
    assert code == 0 and out["applied"] == [out["applied"][0]] and out["applied"][0].startswith("삭제: m.db (이전 작업")
    code, out = run("scan", "--root", str(root), "--job", "새것")
    assert out["applied"] == []


def test_overwrite_does_not_delete_db_of_running_job(tmp_path, run, data_dir):
    """--overwrite는 작업 잠금을 잡은 뒤에만 지웁니다 (다른 곳에서 목록화 중인 DB를 지우지 않음)."""
    root = tmp_path / "잠금2"
    make_tree(str(root), {"a.txt": 1})
    run("scan", "--root", str(root), "--job", "busy2")
    with st.JobLock("busy2"):
        code, out = run("scan", "--root", str(root), "--job", "busy2", "--overwrite")
    assert code == 1 and "실행 중" in out["message"] and st.job_summary("busy2")["files"] == 1


def rt_quote(s):
    import _dc_runtime as rt
    return rt.quote_arg(s)


def test_overwrite_replaces_unreadable_db(tmp_path, run, data_dir):
    root = tmp_path / "깨짐"
    make_tree(str(root), {"a.txt": 1})
    (data_dir / "broken.db").write_bytes(b"this is not sqlite" * 100)
    code, out = run("scan", "--root", str(root), "--job", "broken", "--overwrite", "--dry-run")
    assert out["planned"][0] == "삭제: broken.db (이전 작업: 열 수 없는 DB)"
    code, out = run("scan", "--root", str(root), "--job", "broken", "--overwrite")
    assert code == 0 and out["totals"]["files"] == 1 and out["applied"] == ["삭제: broken.db (이전 작업: 열 수 없는 DB)"]
