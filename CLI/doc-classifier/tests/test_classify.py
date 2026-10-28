"""classify 명령 테스트: 분류 결과 기록, 규칙 선택, 재분류, 0.1.0 DB 호환, 중복 후보, 미분류 단어, 계약."""
import json
import os
import sqlite3

import _dc_store as st
from dc_tree import make_tree

SPEC = {
    "계약/2026_공급계약서_최종.hwp": 10,
    "계약/2026_공급계약서_최종 (1).hwp": 10,
    "계약/참고/MOU 초안.DOCX": 20,
    "보고/회의록_0301.docx": 30,
    "보고/결과보고.PDF": 40,
    "도면/A-01.dwg": 50,
    "도면/B-02.DWG": 50,
    "인사/인사발령_2026.hwp": 7,
    "인사/인사발령_2025.hwp": 8,
    "사진/IMG_0001.jpg": 9,
    "중복/a/교육자료.pptx": 100,
    "중복/b/교육자료.pptx": 100,
    "중복/c/교육자료.PPTX": 100,
    "보고/~$회의록_0301.docx": 1,
}
RULES = {"계약서": ["계약", "MOU"], "회의록": ["회의록"], "보고서": ["보고"], "도면": [".dwg"]}


def _rules(tmp_path, rules=RULES, name="rules.json"):
    p = tmp_path / name
    p.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _scan(tmp_path, run, job="c", spec=SPEC):
    root = tmp_path / "자료"
    make_tree(str(root), spec)
    code, out = run("scan", "--root", str(root), "--job", job)
    assert code == 0 and out["complete"]
    return root


def _rows(data_dir, job):
    con = sqlite3.connect(str(data_dir / f"{job}.db"))
    con.row_factory = sqlite3.Row
    return {r["name"]: r for r in con.execute("SELECT * FROM files")}


def test_scan_suggests_classify_with_rules_or_example(tmp_path, run):
    root = tmp_path / "s"
    make_tree(str(root), {"a.txt": 1})
    code, out = run("scan", "--root", str(root), "--job", "s")
    nc = out["next_commands"]
    assert nc[0]["needs_input"] is True and "--rules" in nc[0]["command"] and nc[0]["placeholder"]
    assert nc[1]["needs_input"] is False and nc[1]["command"].endswith("classify --job s")


def test_classify_records_category_kind_and_name_info(tmp_path, run, data_dir):
    _scan(tmp_path, run)
    code, out = run("classify", "--job", "c", "--rules", _rules(tmp_path))
    assert code == 0 and out["status"] == "ok" and out["agent_directive"].startswith("VERIFIED:")
    by = {c["category"]: c for c in out["by_category"]}
    assert by["계약서"]["files"] == 3 and by["도면"]["files"] == 2 and by["보고서"]["files"] == 1
    assert by["회의록"]["files"] == 2                                     # 임시 파일(~$)도 이름상 회의록
    assert by["미분류"]["files"] == 6 and sum(c["files"] for c in out["by_category"]) == len(SPEC)
    rows = _rows(data_dir, "c")
    r = rows["2026_공급계약서_최종 (1).hwp"]
    assert (r["category"], r["confidence"], r["kind"]) == ("계약서", "high", "한글")
    assert (r["name_date"], r["name_version"], r["name_flags"]) == ("2026", "최종", "copy")
    assert json.loads(rows["B-02.DWG"]["matches"]) == [["도면", 3.0, [".dwg@e"]]]
    assert rows["~$회의록_0301.docx"]["kind"] == "임시/시스템" and rows["~$회의록_0301.docx"]["name_flags"] == "temp"
    assert out["keyword_hits"]["계약서"] == {"계약": 3, "MOU": 1}           # 폴더에서 맞은 것도 셈
    assert out["unclassified_words"][:2] == [{"word": "교육자료", "files": 3}, {"word": "인사발령", "files": 2}]
    assert out["duplicates"]["groups"] == 1 and out["duplicates"]["files"] == 3      # 대소문자 무시, 같은 크기
    assert out["duplicates"]["examples"][0]["copies"] == 3 and len(out["duplicates"]["examples"][0]["paths"]) == 3
    assert out["scan_complete"] is True and out["peek_estimate"]["files"] > 0
    cmds = [c["command"] for c in out["next_commands"]]
    assert "peek --job c" in cmds[0] and "summary --job c --save" in cmds[1]


def test_classify_uses_example_rules_then_remembers_last_rules(tmp_path, run):
    _scan(tmp_path, run)
    code, out = run("classify", "--job", "c")
    assert code == 0 and out["rules_file"].endswith("rules.example.json")
    custom = _rules(tmp_path)
    run("classify", "--job", "c", "--rules", custom)
    code, out = run("classify", "--job", "c")                              # --rules 생략: 지난번 규칙 파일
    assert out["rules_file"] == custom


def test_changed_rules_reclassify_and_clear_old_peek_results(tmp_path, run, data_dir):
    _scan(tmp_path, run)
    path = _rules(tmp_path)
    run("classify", "--job", "c", "--rules", path)
    con = sqlite3.connect(str(data_dir / "c.db"))
    con.execute("UPDATE files SET peek_status='confirmed' WHERE category='계약서'")
    con.commit()
    code, out = run("classify", "--job", "c", "--rules", path)             # 같은 규칙: peek 결과 유지
    assert out["this_run"]["files"] == len(SPEC) and "지웠습니다" not in out["preview"]
    assert out["peek_cleared"] == 0 and out["applied"] == []
    assert con.execute("SELECT COUNT(*) FROM files WHERE peek_status IS NOT NULL").fetchone()[0] == 3
    rules = dict(RULES, 계약서={"keywords": ["계약", "MOU"], "exclude": ["초안"]})     # exclude만 바뀌어도 규칙 변경
    code, out = run("classify", "--job", "c", "--rules", _rules(tmp_path, rules))
    assert "지웠습니다" in out["preview"]
    con.execute("UPDATE files SET peek_status='confirmed' WHERE category='계약서'")
    con.commit()
    rules = dict(RULES, 인사=["인사발령"])
    code, out = run("classify", "--job", "c", "--rules", _rules(tmp_path, rules))
    assert code == 0 and "2개를 지웠습니다" in out["preview"]
    assert out["peek_cleared"] == 2 and out["applied"][0].startswith("삭제: 확인(peek) 결과 2개")
    assert {c["category"]: c["files"] for c in out["by_category"]}["인사"] == 2
    assert con.execute("SELECT COUNT(*) FROM files WHERE peek_status IS NOT NULL").fetchone()[0] == 0


def test_bad_rules_file_is_stop_retry_with_location(tmp_path, run):
    _scan(tmp_path, run)
    p = tmp_path / "bad.json"
    p.write_text('{"계약서": ["계약",\n  "협약" "MOU"]}', encoding="utf-8")
    code, out = run("classify", "--job", "c", "--rules", str(p))
    assert code == 1 and out["agent_directive"].startswith("STOP_RETRY:") and "2번째 줄" in out["message"]
    code, out = run("classify", "--job", "c", "--rules", str(tmp_path / "없음.json"))
    assert code == 1 and "[추천]" in out["message"]
    code, out = run("classify", "--job", "없는작업")
    assert code == 1 and "찾을 수 없습니다" in out["message"]


def test_partial_scan_can_be_classified_and_new_files_are_reported(tmp_path, run):
    root = tmp_path / "부분"
    make_tree(str(root), {f"d{i}/계약_{i}.hwp": 1 for i in range(6)})
    run("scan", "--root", str(root), "--job", "p", "--max-files", "2")
    code, out = run("classify", "--job", "p", "--rules", _rules(tmp_path))
    assert code == 0 and out["scan_complete"] is False and "목록화가 끝나지 않은" in out["preview"]
    assert "--resume" in out["next_commands"][0]["command"]
    run("scan", "--job", "p", "--resume")
    code, out = run("summary", "--job", "p")
    assert out["classify"]["not_classified_files"] == 4
    assert any("classify를 다시" in r for r in out["recommendations"])


def test_jobs_db_from_0_1_0_is_upgraded_in_place(tmp_path, run, data_dir):
    """0.1.0(스키마 1)으로 목록화한 DB를 다시 scan하지 않고 classify할 수 있어야 합니다."""
    _scan(tmp_path, run, job="old")
    con = sqlite3.connect(str(data_dir / "old.db"))
    con.executescript("""
        CREATE TABLE f2 AS SELECT id, dir_id, name, ext, size, mtime, ctime, attrs, flags, no_read, kind, category,
            confidence, matches, peek_status, peek_excerpt FROM files;
        DROP TABLE files; ALTER TABLE f2 RENAME TO files;
        CREATE TABLE d2 AS SELECT id, parent_id, path, depth, status, reason, files, bytes FROM dirs;
        DROP TABLE dirs; ALTER TABLE d2 RENAME TO dirs;
    """)
    con.close()
    code, out = run("classify", "--job", "old", "--rules", _rules(tmp_path))
    assert code == 0 and {c["category"]: c["files"] for c in out["by_category"]}["계약서"] == 3
    cols = {r[1] for r in sqlite3.connect(str(data_dir / "old.db")).execute("PRAGMA table_info(files)")}
    assert {"name_date", "peek_category", "peek_ms"} <= cols


def test_classify_refuses_while_same_job_is_running(tmp_path, run):
    _scan(tmp_path, run)
    with st.JobLock("c"):
        code, out = run("classify", "--job", "c", "--rules", _rules(tmp_path))
    assert code == 1 and "다른 곳에서 실행 중" in out["message"]


def test_peek_summary_list_require_classify_first(tmp_path, run):
    _scan(tmp_path, run)
    for cmd in (["peek", "--job", "c"], ["summary", "--job", "c"], ["list", "--job", "c", "--category", "계약서"]):
        code, out = run(*cmd)
        assert code == 1 and "classify" in out["message"] and "[추천]" in out["message"], cmd
    code, out = run("list", "--job", "c", "--ext", "hwp")                  # 분류 전에도 확장자 조회는 가능
    assert code == 0 and out["total"] == 4


def test_jobs_shows_classify_state(tmp_path, run):
    _scan(tmp_path, run)
    run("classify", "--job", "c", "--rules", _rules(tmp_path))
    code, out = run("jobs")
    assert out["jobs"][0]["classify_status"] == "complete"


def test_top_folder_ids(tmp_path, run, data_dir):
    _scan(tmp_path, run)
    run("classify", "--job", "c", "--rules", _rules(tmp_path))
    con = sqlite3.connect(str(data_dir / "c.db"))
    rows = dict(con.execute("SELECT d.path, t.path FROM dirs d JOIN dirs t ON t.id = d.top_id"))
    root = str(tmp_path / "자료")
    assert rows[os.path.join(root, "계약", "참고")] == os.path.join(root, "계약")
    assert rows[os.path.join(root, "중복", "a")] == os.path.join(root, "중복")
    assert rows[root] == root
