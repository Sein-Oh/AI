"""office.py 테스트: 차트 전달 방식 대체 순서(DRM 대응), matplotlib 다시 그리기, undo 복원, 워드/PPT -> 엑셀."""
import json
import os

import pytest

import _office as off
import _runtime as rt
import excel
import office
from fake_excel import FakeExcelWorkbook, FakeXlApp
from fake_office import FakeWorkbook, make_win32com


def run(capsys, *argv):
    with pytest.raises(SystemExit) as ei:
        office.main(list(argv))
    out = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(out) == 1, out
    return ei.value.code, json.loads(out[0])


# ---------------------------------------------------------------------------
# 차트 그림
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", [4, 51, 57, 5, 1, 75, -4169])
def test_render_chart_writes_plain_png(tmp_path, kind):
    data = {"type": kind, "title": "사인 2주기", "width": 300, "height": 180,
            "series": [{"name": "sin(x)", "values": [0, 1, 0, -1, 0], "x": [0, 1.57, 3.14, 4.71, 6.28]},
                       {"name": "b", "values": [1, 2, 3, 2, 1], "x": ["가", "나", "다", "라", "마"]}]}
    path = office.render_chart(data, str(tmp_path / "c.png"))
    assert office.is_plain_png(path) and os.path.getsize(path) > 1000


def test_is_plain_png_detects_encrypted(tmp_path):
    enc = tmp_path / "drm.png"
    enc.write_bytes(b"DRMONE" + os.urandom(100))
    assert not office.is_plain_png(str(enc))


def test_method_order_uses_probe_result(monkeypatch):
    monkeypatch.setattr(rt, "load_config", lambda: {"transfer_method": {"ppt": ["relay"]}})
    assert office.method_order("ppt", None) == ["relay", "export", "redraw"]
    assert office.method_order("word", None) == ["export", "redraw", "relay"]
    assert office.method_order("ppt", "redraw") == ["redraw"]


@pytest.fixture
def chart_env(monkeypatch, tmp_path):
    """엑셀 차트가 하나 있는 상태. 삽입 함수와 그림 방식은 기록용 대역."""
    app = FakeXlApp()
    wb = FakeExcelWorkbook(app)
    fake, _ = make_win32com()
    monkeypatch.setattr(off, "win32com", fake)
    monkeypatch.setattr(off, "pythoncom", None)
    monkeypatch.setattr(off, "list_open", lambda kind: [])
    monkeypatch.setattr(off, "get_active", lambda kind: {"name": wb.Name, "path": wb.FullName, "app": app, "doc": wb})
    chart = type("C", (), {"Name": "사인 2주기"})()
    monkeypatch.setattr(excel, "find_chart", lambda t, name, sheet=None: (None, chart))
    monkeypatch.setattr(excel, "_chart_title", lambda obj: "사인 2주기")
    log = {"insert": [], "calls": []}

    def png(name):
        p = tmp_path / name
        p.write_bytes(office.PNG_SIGNATURE + b"x" * 50)
        return str(p)

    def export(obj, stem):
        log["calls"].append("export")
        raise RuntimeError("엑셀이 저장한 PNG가 보안 프로그램으로 암호화되어 다른 앱이 읽을 수 없습니다")

    def redraw(obj, stem):
        log["calls"].append("redraw")
        return png("r.png")

    monkeypatch.setattr(office, "image_by_export", export)
    monkeypatch.setattr(office, "image_by_redraw", redraw)
    monkeypatch.setattr(office, "insert_picture_word", lambda tgt, img, anchor, occurrence=None: log["insert"].append(("word", img)) or {"app": "Word"})
    monkeypatch.setattr(office, "insert_picture_ppt", lambda tgt, img, slide, title: log["insert"].append(("ppt", img)) or {"app": "PowerPoint"})
    monkeypatch.setattr(rt, "load_config", lambda: {})
    return log


def test_chart_transfer_falls_back_from_encrypted_export_to_redraw(chart_env, capsys):
    code, out = run(capsys, "transfer", "--from", "excel", "--chart", "사인 2주기", "--to", "word,ppt")
    assert code == 0, out
    assert out["results"]["word"]["method"] == "redraw" and out["results"]["ppt"]["method"] == "redraw"
    assert chart_env["calls"].count("redraw") == 1                     # 한 번 그린 그림을 두 앱에 재사용
    assert [k for k, _ in chart_env["insert"]] == ["word", "ppt"]


def test_chart_transfer_all_methods_fail_suggests_probe(chart_env, capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("실패")
    monkeypatch.setattr(office, "image_by_redraw", boom)
    monkeypatch.setattr(office, "relay_chart", boom)
    code, out = run(capsys, "transfer", "--from", "excel", "--chart", "사인 2주기", "--to", "ppt")
    assert code == 1 and "--probe" in out["message"]


def test_transfer_argument_rules(capsys):
    code, out = run(capsys, "transfer", "--from", "excel", "--to", "word")
    assert code == 1 and "--chart" in out["message"]
    code, out = run(capsys, "transfer", "--from", "word", "--to", "ppt")
    assert code == 1 and "read --save" in out["message"]
    code, out = run(capsys, "transfer", "--from", "엑셀", "--to", "엑셀", "--range", "A1")
    assert code == 1
    code, out = run(capsys, "transfer", "--from", "hwp", "--to", "word")
    assert code == 1 and "[추천]" in out["message"] or "사용 가능한" in out["message"]


# ---------------------------------------------------------------------------
# 워드/PPT -> 엑셀
# ---------------------------------------------------------------------------

def test_word_text_to_new_excel_sheet_with_unique_name(monkeypatch, capsys):
    app = FakeXlApp()
    wb = FakeExcelWorkbook(app, sheets=("Sheet1", "Word 내용"))
    fake, _ = make_win32com()
    monkeypatch.setattr(off, "win32com", fake)
    monkeypatch.setattr(off, "pythoncom", None)
    monkeypatch.setattr(off, "list_open", lambda kind: [])
    monkeypatch.setattr(off, "get_active", lambda kind: {"name": wb.Name, "path": wb.FullName, "app": app, "doc": wb})
    monkeypatch.setattr(off, "save_snapshot", lambda *a, **k: None)
    rows = [["번호", "구분", "상위 제목", "내용"], [1, "제목1", "배경", "배경"], [2, "본문", "배경", "내용입니다"]]
    monkeypatch.setattr(office, "_word_rows", lambda args: (rows, "계획.docx"))
    code, out = run(capsys, "transfer", "--from", "word", "--to", "excel")
    assert code == 0 and out["sheet"] == "Word 내용 2" and out["rows"] == 3
    ws = wb.Worksheets("Word 내용 2")
    assert ws.values[(3, 4)] == "내용입니다"


def test_transfer_to_existing_excel_sheet_does_not_overwrite(monkeypatch, capsys):
    app = FakeXlApp()
    wb = FakeExcelWorkbook(app, sheets=("Sheet1", "결과"))
    fake, _ = make_win32com()
    monkeypatch.setattr(off, "win32com", fake)
    monkeypatch.setattr(off, "pythoncom", None)
    monkeypatch.setattr(off, "list_open", lambda kind: [])
    monkeypatch.setattr(off, "get_active", lambda kind: {"name": wb.Name, "path": wb.FullName, "app": app, "doc": wb})
    monkeypatch.setattr(off, "save_snapshot", lambda *a, **k: None)
    wb.Worksheets("결과").values[(1, 1)] = "기존"
    monkeypatch.setattr(office, "_word_rows", lambda args: ([["a", "b"], [1, 2]], "계획.docx"))
    code, out = run(capsys, "transfer", "--from", "word", "--to", "excel", "--sheet", "결과")
    assert code == 1 and out["message"].endswith("[추천] 결과 2") and "--overwrite" in out["message"]
    assert wb.Worksheets("결과").values[(1, 1)] == "기존"
    code, out = run(capsys, "transfer", "--from", "word", "--to", "excel", "--sheet", "결과", "--overwrite")
    assert code == 0 and out["sheet"] == "결과" and wb.Worksheets("결과").values[(1, 1)] == "a"
    code, out = run(capsys, "transfer", "--from", "word", "--to", "excel", "--sheet", "새 결과")
    assert code == 0 and out["sheet"] == "새 결과"                       # --sheet는 새 시트 이름: 없으면 만듦


def test_chart_transfer_stops_on_ambiguous_anchor_without_trying_other_methods(chart_env, capsys, monkeypatch):
    calls = []

    def ambiguous_anchor(tgt, img, anchor, occurrence=None):
        calls.append(img)
        raise rt.ambiguous("'계획'이(가) 단락 2개에 있어 어느 곳인지 고를 수 없습니다.", ["1: 계획 A", "2: 계획 B"])
    monkeypatch.setattr(office, "insert_picture_word", ambiguous_anchor)
    code, out = run(capsys, "transfer", "--from", "excel", "--chart", "사인 2주기", "--to", "word", "--anchor", "계획")
    assert code == 1 and out["error_type"] == "ambiguous" and out["candidates"] == ["1: 계획 A", "2: 계획 B"]
    assert len(calls) == 1                                                # 다른 방식으로 넘어가지 않음


# ---------------------------------------------------------------------------
# undo
# ---------------------------------------------------------------------------

def test_undo_closed_file_restores_backs_up_and_consumes(tmp_path, monkeypatch, capsys):
    fake, _ = make_win32com()
    monkeypatch.setattr(off, "win32com", fake)
    monkeypatch.setattr(off, "pythoncom", None)
    monkeypatch.setattr(off, "match_open", lambda kind, target, docs=None: None)
    orig = tmp_path / "a.xlsx"
    orig.write_bytes(b"current")
    off.save_snapshot("excel", FakeWorkbook(str(orig)), "excel", "write")      # 스냅샷 내용: snapshot-of-a.xlsx
    code, out = run(capsys, "undo", "--list")
    assert out["snapshots"][0]["by"] == "excel write"
    code, out = run(capsys, "undo")
    assert code == 0 and out["restored_as"] == "file_replaced"
    assert orig.read_bytes() == b"snapshot-of-a.xlsx"
    assert open(out["pre_undo_backup"], "rb").read() == b"current"
    code, out = run(capsys, "undo")
    assert code == 0 and out["restored"] is False                         # 소비되어 더 없음


def test_undo_pick_out_of_range(tmp_path, monkeypatch, capsys):
    orig = tmp_path / "a.xlsx"
    orig.write_bytes(b"x")
    off.save_snapshot("excel", FakeWorkbook(str(orig)))
    code, out = run(capsys, "undo", "--pick", "5")
    assert code == 1 and "--list" in out["message"]


def test_windows_lists_documents(monkeypatch, capsys):
    monkeypatch.setattr(off, "open_documents_summary",
                        lambda: [{"app": "Excel", "name": "a.xlsx", "path": "", "saved": True, "active": True}])
    monkeypatch.setattr(off, "running_office_caps", lambda: {})
    code, out = run(capsys, "windows")
    assert code == 0 and out["preview"] == "Excel 1개" and out["office"] == {}


def test_windows_reports_office_version_and_missing_pdf(monkeypatch, capsys):
    monkeypatch.setattr(off, "open_documents_summary",
                        lambda: [{"app": "Word", "name": "a.docx", "path": "", "saved": True, "active": True}])
    monkeypatch.setattr(off, "running_office_caps",
                        lambda: {"Word": {"version": "12.0", "major": 12, "pdf_export": False}})
    code, out = run(capsys, "windows")
    assert code == 0 and out["office"]["Word"]["pdf_export"] is False
    assert "Office 12.0" in out["preview"] and "PDF 내보내기 불가: Word" in out["preview"]
