import os

import _cache
import clean
from fake_com import FakeWorkbook


class FakeWordDoc:
    def __init__(self, full_name, saved):
        self.FullName = full_name
        self.Name = os.path.basename(full_name)
        self.Saved = saved
        self.WordOpenXML = "<?xml version='1.0'?><pkg:package/>"

    def Save(self):
        raise AssertionError("스냅샷이 원본 문서를 저장하면 안 됨")

    def SaveAs(self, *a, **k):
        raise AssertionError("스냅샷이 원본 문서 경로를 바꾸면 안 됨")

    SaveAs2 = SaveAs


def test_word_snapshot_with_unsaved_changes_uses_flat_xml(tmp_path):
    orig = tmp_path / "보고서.docx"
    orig.write_bytes(b"docx-on-disk")
    snap = _cache.save_document_snapshot("word", FakeWordDoc(str(orig), saved=False))
    assert snap.endswith(".xml")
    assert "pkg:package" in open(snap, encoding="utf-8").read()
    meta = _cache.get_latest_snapshot("word")
    assert meta["snapshot_format"] == "flat_xml"
    assert orig.read_bytes() == b"docx-on-disk"


def test_word_snapshot_saved_doc_copies_file(tmp_path):
    orig = tmp_path / "a.docx"
    orig.write_bytes(b"saved-content")
    snap = _cache.save_document_snapshot("word", FakeWordDoc(str(orig), saved=True))
    assert snap.endswith(".docx")
    assert open(snap, "rb").read() == b"saved-content"


def test_excel_snapshot_keeps_original_extension(tmp_path):
    orig = tmp_path / "macro.xlsm"
    orig.write_bytes(b"x")
    snap = _cache.save_document_snapshot("excel", FakeWorkbook(str(orig)))
    assert snap.endswith(".xlsm")


def test_snapshot_rotation_keeps_two(tmp_path):
    orig = tmp_path / "a.xlsx"
    orig.write_bytes(b"x")
    for _ in range(4):
        _cache.save_document_snapshot("excel", FakeWorkbook(str(orig)))
    cache_dir = os.environ["ATOMIC_CACHE_DIR"]
    files = os.listdir(cache_dir)
    assert len([f for f in files if f.endswith(".json")]) == 2
    assert len([f for f in files if f.endswith(".xlsx")]) == 2


def test_undo_closed_file_backs_up_current_and_consumes_snapshot(tmp_path, monkeypatch):
    orig = tmp_path / "a.xlsx"
    orig.write_bytes(b"current")
    _cache.save_document_snapshot("excel", FakeWorkbook(str(orig)))  # 스냅샷 내용: b"snapshot"
    monkeypatch.setattr(clean, "_find_open_document", lambda app, path: None)

    res = clean.undo_latest_backup("excel")

    assert res["status"] == "ok"
    assert orig.read_bytes() == b"snapshot"
    assert open(res["pre_undo_backup"], "rb").read() == b"current"
    assert _cache.get_latest_snapshot("excel") is None


def test_undo_failure_reports_error(tmp_path, monkeypatch):
    orig = tmp_path / "a.xlsx"
    orig.write_bytes(b"current")
    _cache.save_document_snapshot("excel", FakeWorkbook(str(orig)))
    monkeypatch.setattr(clean, "_find_open_document", lambda app, path: None)

    def boom(*a, **k):
        raise PermissionError("locked")
    monkeypatch.setattr(clean, "_restore_closed_document", boom)

    res = clean.execute({"action": "undo", "app": "excel"})
    assert res["status"] == "error"
    assert _cache.get_latest_snapshot("excel") is not None  # 실패 시 스냅샷 보존


def test_undo_without_snapshot_is_no_match():
    assert clean.undo_latest_backup("ppt")["status"] == "no_match"
