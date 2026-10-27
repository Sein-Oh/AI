"""peek 테스트: 형식별 앞부분 읽기, DRM/암호 판별, 판정, 표본 고르기, 파일당 시간 상한, 중단/이어서, 계약."""
import json
import os
import sqlite3
import sys

import pytest

import _dc_peek as pk
import _dc_rules as ru
import dc_samples as ds

RULES = {"계약서": ["계약", "협약"], "회의록": ["회의록", "회의"], "견적/발주": ["견적", "단가"],
         "시험성적서": ["성적서"], "사양서": ["사양서"], "도면": [".dwg"]}


def _rules_file(tmp_path, rules=RULES):
    p = tmp_path / "rules.json"
    p.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    return str(p)


def build(root):
    """카테고리마다 실제 형식 파일. 이름과 내용이 맞는 것, 다른 것, 읽을 수 없는 것을 섞습니다."""
    j = lambda *p: os.path.join(str(root), *p)  # noqa: E731
    os.makedirs(j("계약"), exist_ok=True)
    os.makedirs(j("회의"), exist_ok=True)
    os.makedirs(j("기타"), exist_ok=True)
    ds.make_docx(j("계약", "공급계약서.docx"), "물품 공급 계약서", "갑과 을은 계약한다.")
    ds.make_hwp(j("계약", "협약서.hwp"), "업무 협약 본문", preview="업무 협약서")
    ds.make_pdf(j("계약", "계약_스캔.pdf"), "견적 단가 안내 견적서")          # 이름은 계약, 내용은 견적
    ds.make_hwp(j("계약", "계약_암호.hwp"), "x", props=2)                      # 암호 HWP
    with open(j("계약", "계약_DRM.docx"), "wb") as f:                          # DRM 래퍼(ZIP 아님)
        f.write(b"<##SoftCamp DRM##>" + b"\x00" * 200)
    ds.make_hwpx(j("회의", "회의록_0301.hwpx"), preview="주간 회의록 안건")
    ds.make_pptx(j("회의", "회의자료.pptx"), "월간 회의", "안건")
    ds.make_eml(j("회의", "회의 일정.eml"), "회의 일정 안내", "다음 주 회의")
    ds.make_xlsx(j("기타", "견적_2026.xlsx"), "견적", ["품목", "단가"], ["볼트", 100])
    ds.make_doc(j("기타", "성적서.doc"), "시험 성적서 Test report results")
    ds.make_pdf(j("기타", "메모.pdf"), "사양서 개요")                            # 미분류 -> 내용상 사양서
    ds.make_pdf(j("기타", "빈문서.pdf"), " ")                                    # 글자 없음
    with open(j("기타", "A-01.dwg"), "wb") as f:
        f.write(b"AC1027" + b"\x00" * 50)
    with open(j("기타", "가짜.dwg"), "wb") as f:
        f.write(b"not a drawing")
    with open(j("기타", "사진.jpg"), "wb") as f:                                 # 미분류지만 읽지 않는 형식
        f.write(b"\xff\xd8\xff" + b"\x00" * 10)


@pytest.fixture
def job(tmp_path, run):
    root = tmp_path / "자료"
    build(root)
    code, out = run("scan", "--root", str(root), "--job", "pk")
    assert code == 0
    code, out = run("classify", "--job", "pk", "--rules", _rules_file(tmp_path))
    assert code == 0
    return root


def _status(data_dir):
    con = sqlite3.connect(str(data_dir / "pk.db"))
    return {n: (s, c, r, e) for n, s, c, r, e in con.execute(
        "SELECT name, peek_status, peek_category, peek_reason, peek_excerpt FROM files")}


def test_peek_reads_heads_and_judges_each_format(job, run, data_dir):
    code, out = run("peek", "--job", "pk")
    assert code == 0 and out["complete"] is True and out["agent_directive"].startswith("VERIFIED:")
    s = _status(data_dir)
    assert s["공급계약서.docx"][0] == "confirmed" and "물품 공급 계약서" in s["공급계약서.docx"][3]
    assert s["협약서.hwp"][0] == "confirmed" and s["협약서.hwp"][3] == "업무 협약서"          # HWP 미리보기 텍스트
    assert s["계약_스캔.pdf"][:2] == ("changed", "견적/발주")
    assert s["계약_암호.hwp"][0] == "encrypted_or_drm" and "암호" in s["계약_암호.hwp"][2]
    assert s["계약_DRM.docx"][0] == "encrypted_or_drm" and "ZIP" in s["계약_DRM.docx"][2]
    assert s["회의록_0301.hwpx"][0] == "confirmed" and s["회의자료.pptx"][0] == "confirmed"
    assert s["회의 일정.eml"][0] == "confirmed"
    assert s["견적_2026.xlsx"][0] == "confirmed" and "단가" in s["견적_2026.xlsx"][3]
    assert s["성적서.doc"][0] == "confirmed"                                    # 옛 Word: 본문 스트림 글자
    assert s["메모.pdf"][:2] == ("changed", "사양서")                            # 미분류 -> 내용상 사양서
    assert s["빈문서.pdf"][0] == "no_text"
    assert s["A-01.dwg"][0] == "confirmed" and "서명" in s["A-01.dwg"][2]         # 확장자 카테고리는 형식 서명
    assert s["가짜.dwg"][0] == "unreadable"
    assert s["사진.jpg"][0] is None                                              # 읽지 않는 형식은 표본에서 뺌
    stats = {c["category"]: c for c in out["totals"]["by_category"]}
    assert stats["계약서"]["sampled"] == 5 and stats["계약서"]["confirmed"] == 2 and stats["계약서"]["judged"] == 3
    assert stats["계약서"]["suggested"] == {"견적/발주": 1}
    assert stats["미분류"]["changed"] == 1
    assert any(e["suggested"] == "사양서" for e in out["changed_examples"])
    assert "summary --job pk --save" in out["next_commands"][0]["command"]


def test_judge_rules():
    rules = ru.parse_rules(json.dumps(RULES, ensure_ascii=False))
    ok = lambda t: {"status": "ok", "text": t}  # noqa: E731
    assert pk.judge(ok("계약 협약 견적"), "계약서", "text", rules)[0] == "confirmed"       # 2 >= 1
    assert pk.judge(ok("계약 견적 단가"), "계약서", "text", rules)[:2] == ("changed", "견적/발주")
    assert pk.judge(ok("아무 내용"), "계약서", "text", rules)[0] == "no_match"
    assert pk.judge(ok("회의록"), "미분류", "text", rules)[:2] == ("changed", "회의록")
    assert pk.judge(ok("아무 내용"), "미분류", "text", rules)[0] == "no_match"
    assert pk.judge({"status": "timeout", "reason": "느림"}, "계약서", "text", rules) == ("timeout", None, "느림")
    assert pk.judge(ok(""), "도면", "signature", rules)[0] == "confirmed"


def test_samples_per_category_low_confidence_first_and_no_read_excluded(tmp_path, run, data_dir):
    root = tmp_path / "많음"
    os.makedirs(root / "계약", exist_ok=True)
    for i in range(30):
        (root / "계약" / f"계약_{i:02d}.txt").write_text("계약 본문", encoding="utf-8")
    (root / "계약" / "메모.txt").write_text("계약", encoding="utf-8")            # 폴더에서만 맞음 -> medium
    (root / "클라우드_계약.txt").write_text("계약", encoding="utf-8")
    run("scan", "--root", str(root), "--job", "pk")
    con = sqlite3.connect(str(data_dir / "pk.db"))
    con.execute("UPDATE files SET no_read=1 WHERE name='클라우드_계약.txt'")
    con.commit()
    run("classify", "--job", "pk", "--rules", _rules_file(tmp_path))
    code, out = run("peek", "--job", "pk", "--per-category", "5")
    assert code == 0 and out["this_run"]["files"] == 5
    picked = [n for n, in con.execute("SELECT name FROM files WHERE peek_status IS NOT NULL")]
    assert "메모.txt" in picked and "클라우드_계약.txt" not in picked
    code, out = run("peek", "--job", "pk", "--per-category", "5")             # 이미 5개 -> 더 읽지 않음
    assert out["this_run"]["files"] == 0
    code, out = run("peek", "--job", "pk", "--per-category", "8")             # 늘리면 새 표본만 3개
    assert out["this_run"]["files"] == 3 and out["totals"]["files"] == 8
    code, out = run("peek", "--job", "pk", "--per-category", "4", "--redo")    # 지우고 새로
    assert out["totals"]["files"] == 4


def test_max_files_spreads_over_categories(job, run):
    code, out = run("peek", "--job", "pk", "--max-files", "4")
    cats = {c["category"] for c in out["totals"]["by_category"]}
    assert out["this_run"]["files"] == 4 and len(cats) == 4                  # 한 카테고리가 다 차지하지 않음


class FakeWorker(pk.WorkerPool):
    """'멈춤'이 들어간 파일은 응답하지 않고, '죽음'이 들어간 파일에서는 프로세스가 죽는 가짜 작업 프로세스."""
    script = ""

    def command(self):
        return [sys.executable, self.script]


FAKE = r'''
import json, os, sys, time
for line in sys.stdin:
    req = json.loads(line)
    name = os.path.basename(req["path"])
    if "멈춤" in name:
        time.sleep(60)
    if "죽음" in name:
        os._exit(3)
    print(json.dumps({"status": "ok", "text": "계약 본문", "method": "fake"}), flush=True)
'''


def test_timeout_and_crash_skip_file_and_restart_worker(tmp_path, run, data_dir, monkeypatch):
    root = tmp_path / "느림"
    os.makedirs(root, exist_ok=True)
    for n in ("계약_1.txt", "계약_멈춤.txt", "계약_2.txt", "계약_죽음.txt", "계약_3.txt"):
        (root / n).write_text("x", encoding="utf-8")
    script = tmp_path / "fake_worker.py"
    script.write_text(FAKE, encoding="utf-8")
    FakeWorker.script = str(script)
    monkeypatch.setattr(pk, "WorkerPool", FakeWorker)
    run("scan", "--root", str(root), "--job", "pk")
    run("classify", "--job", "pk", "--rules", _rules_file(tmp_path))
    code, out = run("peek", "--job", "pk", "--timeout", "1.5")
    assert code == 0 and out["complete"]
    s = _status(data_dir)
    assert s["계약_멈춤.txt"][0] == "timeout" and "1.5초" in s["계약_멈춤.txt"][2]
    assert s["계약_죽음.txt"][0] == "unreadable" and "비정상 종료" in s["계약_죽음.txt"][2]
    assert [s[f"계약_{i}.txt"][0] for i in (1, 2, 3)] == ["confirmed"] * 3      # 그 뒤 파일도 계속 읽음
    assert out["this_run"]["worker_restarts"] >= 2


def test_interrupt_keeps_results_and_rerun_continues(tmp_path, run, data_dir, monkeypatch):
    root = tmp_path / "중단"
    os.makedirs(root, exist_ok=True)
    for i in range(6):
        (root / f"계약_{i}.txt").write_text("계약", encoding="utf-8")
    run("scan", "--root", str(root), "--job", "pk")
    run("classify", "--job", "pk", "--rules", _rules_file(tmp_path))
    real = pk.WorkerPool.ask
    calls = {"n": 0}

    def ask(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 4:
            raise KeyboardInterrupt
        return real(self, *a, **k)
    monkeypatch.setattr(pk.WorkerPool, "ask", ask)
    code, out = run("peek", "--job", "pk")
    assert code == 130 and out["error_type"] == "interrupted" and out["totals"]["files"] == 3
    assert "peek --job pk" in out["next_commands"][0]["command"]
    monkeypatch.setattr(pk.WorkerPool, "ask", real)
    code, out = run("peek", "--job", "pk")
    assert code == 0 and out["this_run"]["files"] == 3 and out["totals"]["files"] == 6


def test_time_limit_stops_and_offers_continue(job, run):
    code, out = run("peek", "--job", "pk", "--time-limit", "0")
    assert code == 0 and out["complete"] is False and out["stopped_reason"] == "time_limit"
    assert "peek --job pk" in out["next_commands"][0]["command"]


def test_peek_argument_errors(job, run):
    assert run("peek", "--job", "pk", "--per-category", "0")[0] == 1
    assert run("peek", "--job", "pk", "--timeout", "0")[0] == 1
    assert run("peek", "--job", "pk", "--per-category", "x")[0] == 2


def test_read_head_never_opens_cloud_placeholder(tmp_path, monkeypatch):
    p = tmp_path / "계약.docx"
    p.write_bytes(b"PK\x03\x04")

    class S:
        st_size, st_file_attributes = 10, pk.FA_RECALL_ON_DATA_ACCESS
    monkeypatch.setattr(pk.os, "stat", lambda path: S())
    opened = []
    monkeypatch.setattr("builtins.open", lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(AssertionError("열면 안 됨")))
    assert pk.read_head(str(p), ".docx", "text")["status"] == "skipped" and not opened


def test_read_head_missing_and_empty(tmp_path):
    assert pk.read_head(str(tmp_path / "없음.docx"), ".docx", "text")["status"] == "missing"
    (tmp_path / "빈.txt").write_bytes(b"")
    assert pk.read_head(str(tmp_path / "빈.txt"), ".txt", "text")["status"] == "no_text"


def test_text_head_decodes_cp949_and_cut_utf8(tmp_path):
    (tmp_path / "a.txt").write_bytes("회의록 내용".encode("cp949"))
    assert pk.read_head(str(tmp_path / "a.txt"), ".txt", "text")["text"] == "회의록 내용"
    (tmp_path / "b.txt").write_bytes(("가" * 5000).encode("utf-8"))          # 8KB에서 글자 중간이 잘림
    r = pk.read_head(str(tmp_path / "b.txt"), ".txt", "text")
    assert r["status"] == "ok" and set(r["text"]) == {"가"}


def test_worker_stdout_is_protocol_only(tmp_path):
    """작업 프로세스는 라이브러리가 stdout에 써도 통신 줄이 깨지지 않아야 합니다."""
    ds.make_docx(str(tmp_path / "a.docx"), "계약 본문")
    pool = pk.WorkerPool()
    try:
        r = pool.ask(str(tmp_path / "a.docx"), ".docx", "text", 30)
        assert r == {"status": "ok", "text": "계약 본문", "method": "docx"}
        r = pool.ask(str(tmp_path / "없음.docx"), ".docx", "text", 30)
        assert r["status"] == "missing"
    finally:
        pool.close()
