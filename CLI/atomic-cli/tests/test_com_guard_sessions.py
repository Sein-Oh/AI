import pytest

import _com_guard
from fake_com import FakeExcelApp, FakeWorkbook, make_fake_win32com


@pytest.fixture
def no_running(monkeypatch):
    monkeypatch.setattr(_com_guard, "get_all_running_excel_workbooks", lambda: [])
    monkeypatch.setattr(_com_guard, "get_all_running_word_documents", lambda: [])
    monkeypatch.setattr(_com_guard, "get_all_running_ppt_presentations", lambda: [])
    monkeypatch.setattr(_com_guard, "pythoncom", None)


def test_excel_file_mode_uses_dedicated_instance_and_readonly_open(tmp_path, monkeypatch, no_running):
    path = tmp_path / "a.xlsx"
    path.write_bytes(b"x")
    app = FakeExcelApp()
    fake, calls = make_fake_win32com(dispatch_ex=app)
    monkeypatch.setattr(_com_guard, "win32com", fake)

    with _com_guard.excel_session(target=str(path)) as (a, wb, ws):
        assert a is app
        wb.Saved = False  # 읽기 세션에서 변경 플래그가 서도 저장하면 안 됨

    assert ("DispatchEx", "Excel.Application") in calls
    assert not any(c[0] == "Dispatch" and c[1] == "Excel.Application" for c in calls)
    assert app.Workbooks.open_kwargs["ReadOnly"] is True
    assert "Save" not in wb.calls
    assert app.quit_called


def test_excel_readonly_missing_file_raises_without_creating(tmp_path, monkeypatch, no_running):
    app = FakeExcelApp()
    fake, _ = make_fake_win32com(dispatch_ex=app)
    monkeypatch.setattr(_com_guard, "win32com", fake)
    missing = tmp_path / "missing.xlsx"
    with pytest.raises(_com_guard.COMError):
        with _com_guard.excel_session(target=str(missing)):
            pass
    assert app.Workbooks.Count == 0


def test_excel_readonly_missing_sheet_raises(tmp_path, monkeypatch, no_running):
    path = tmp_path / "a.xlsx"
    path.write_bytes(b"x")
    app = FakeExcelApp()
    fake, _ = make_fake_win32com(dispatch_ex=app)
    monkeypatch.setattr(_com_guard, "win32com", fake)
    with pytest.raises(_com_guard.COMError):
        with _com_guard.excel_session(target=str(path), sheet_name="오타시트"):
            pass
    wb = app.Workbooks.items[0]
    assert [s.Name for s in wb.Worksheets] == ["Sheet1"]
    assert app.quit_called


def test_excel_sheet_lookup_is_case_insensitive(tmp_path, monkeypatch, no_running):
    path = tmp_path / "a.xlsx"
    path.write_bytes(b"x")
    app = FakeExcelApp()
    fake, _ = make_fake_win32com(dispatch_ex=app)
    monkeypatch.setattr(_com_guard, "win32com", fake)
    with _com_guard.excel_session(target=str(path), sheet_name="sheet1") as (_, wb, ws):
        assert ws.Name == "Sheet1"


def test_excel_write_mode_creates_sheet_and_saves(tmp_path, monkeypatch, no_running):
    path = tmp_path / "a.xlsx"
    path.write_bytes(b"x")
    app = FakeExcelApp()
    fake, _ = make_fake_win32com(dispatch_ex=app)
    monkeypatch.setattr(_com_guard, "win32com", fake)
    with _com_guard.excel_session(target=str(path), sheet_name="보고", readonly=False) as (_, wb, ws):
        assert ws.Name == "보고"
        wb.Saved = False
    assert "Save" in wb.calls
    assert app.Workbooks.open_kwargs["ReadOnly"] is False


def test_excel_active_readonly_does_not_activate_sheet(monkeypatch, no_running):
    app = FakeExcelApp()
    wb = FakeWorkbook("C:/x/book.xlsx", sheets=("A", "B"))
    fake, _ = make_fake_win32com()
    monkeypatch.setattr(_com_guard, "win32com", fake)
    monkeypatch.setattr(_com_guard, "get_active_excel_app_and_wb", lambda enable_jit=True: (app, wb))
    with _com_guard.excel_session(target="active", sheet_name="B") as (_, _wb, ws):
        assert ws.Name == "B"
    assert not ws.activated
    assert ("Close", False) not in wb.calls


class FakePresentations:
    def __init__(self):
        self.open_args = None
        self.Count = 0

    def Open(self, *args):
        self.open_args = args
        self.Count += 1
        return FakePresentation()


class FakePresentation:
    def __init__(self):
        self.Saved = -1
        self.FullName = "C:/x/deck.pptx"
        self.Name = "deck.pptx"
        self.calls = []

    def Save(self):
        self.calls.append("Save")

    def Close(self):
        self.calls.append("Close")


class FakePptApp:
    def __init__(self):
        self.DisplayAlerts = 2
        self.Presentations = FakePresentations()
        self.touched = []
        self.quit_called = False

    def __setattr__(self, key, value):
        if key in ("Visible", "WindowState"):
            self.__dict__.setdefault("touched", []).append(key)
        object.__setattr__(self, key, value)

    def Quit(self):
        self.quit_called = True


def test_ppt_file_mode_does_not_touch_users_running_instance(tmp_path, monkeypatch, no_running):
    path = tmp_path / "deck.pptx"
    path.write_bytes(b"x")
    app = FakePptApp()
    fake, _ = make_fake_win32com(dispatch=app, active=app)
    monkeypatch.setattr(_com_guard, "win32com", fake)
    with _com_guard.ppt_session(target=str(path)) as (_, prs):
        pass
    assert app.touched == []                     # Visible / WindowState 미변경
    assert app.DisplayAlerts == 2                # 원래 경고 설정 복원
    assert app.Presentations.open_args[1] == -1  # 읽기 전용(msoTrue)
    assert app.Presentations.open_args[3] == 0   # WithWindow=msoFalse
    assert "Save" not in prs.calls
    assert not app.quit_called                   # 사용자 인스턴스는 종료하지 않음
