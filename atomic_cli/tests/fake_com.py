"""COM 없이 세션/스냅샷 로직을 검증하기 위한 최소한의 가짜 Office 객체."""
import types


class FakeSheet:
    def __init__(self, name):
        self.Name = name
        self.activated = False

    def Activate(self):
        self.activated = True


class FakeSheets:
    def __init__(self, names):
        self._items = [FakeSheet(n) for n in names]

    def __iter__(self):
        return iter(list(self._items))

    @property
    def Count(self):
        return len(self._items)

    def __call__(self, key):
        if isinstance(key, int):
            return self._items[key - 1]
        for s in self._items:
            if s.Name == key:
                return s
        raise Exception("sheet not found")

    def Add(self, After=None):
        s = FakeSheet(f"Sheet{len(self._items) + 1}")
        self._items.append(s)
        return s


class FakeWorkbook:
    def __init__(self, full_name="", sheets=("Sheet1",)):
        self.FullName = full_name
        self.Name = full_name.replace("\\", "/").split("/")[-1] if full_name else "Book1"
        self.Saved = True
        self.Worksheets = FakeSheets(sheets)
        self.calls = []

    @property
    def ActiveSheet(self):
        return self.Worksheets(1)

    def Save(self):
        self.calls.append("Save")
        self.Saved = True

    def SaveAs(self, path, **kw):
        self.calls.append(("SaveAs", path, kw))
        self.FullName = path

    def SaveCopyAs(self, path):
        self.calls.append(("SaveCopyAs", path))
        with open(path, "wb") as f:
            f.write(b"snapshot")

    def Close(self, SaveChanges=None):
        self.calls.append(("Close", SaveChanges))


class FakeWorkbooks:
    def __init__(self, app):
        self.app = app
        self.open_kwargs = None
        self.items = []

    @property
    def Count(self):
        return len(self.items)

    def __call__(self, i):
        return self.items[i - 1]

    def Open(self, path, **kw):
        self.open_kwargs = kw
        wb = FakeWorkbook(path)
        self.items.append(wb)
        return wb

    def Add(self):
        wb = FakeWorkbook("")
        self.items.append(wb)
        return wb


class FakeExcelApp:
    def __init__(self):
        self.Visible = True
        self.DisplayAlerts = True
        self.AskToUpdateLinks = True
        self.Workbooks = FakeWorkbooks(self)
        self.quit_called = False

    def Quit(self):
        self.quit_called = True


def make_fake_win32com(dispatch_ex=None, dispatch=None, active=None):
    """win32com 모듈 대역. DispatchEx/Dispatch/GetActiveObject 반환값과 호출 기록을 제어합니다."""
    calls = []

    def _dispatch_ex(prog_id):
        calls.append(("DispatchEx", prog_id))
        return dispatch_ex

    def _dispatch(obj):
        calls.append(("Dispatch", obj if isinstance(obj, str) else type(obj).__name__))
        if isinstance(obj, str):
            return dispatch
        return obj

    def _get_active(prog_id):
        calls.append(("GetActiveObject", prog_id))
        if active is None:
            raise Exception("not running")
        return active

    client = types.SimpleNamespace(DispatchEx=_dispatch_ex, Dispatch=_dispatch, GetActiveObject=_get_active)
    return types.SimpleNamespace(client=client), calls
