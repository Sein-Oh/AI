import excel_range


class FakeRange:
    def __init__(self, addr):
        self.addr = addr
        self.calls = []

    def Cut(self, Destination=None):
        self.calls.append(("Cut", Destination.addr))

    def Copy(self, Destination=None):
        self.calls.append(("Copy", Destination.addr))

    def Clear(self):
        self.calls.append("Clear")


class FakeWs:
    def __init__(self, name):
        self.name = name
        self.ranges = {}

    def Range(self, addr):
        return self.ranges.setdefault(addr, FakeRange(f"{self.name}!{addr}"))


class FakeWb:
    def __init__(self, sheets):
        self.sheets = sheets

    def Worksheets(self, name):
        return self.sheets[name]


def test_resolve_quoted_sheet_name():
    ws = FakeWs("Sheet1")
    wb = FakeWb({"My Sheet": FakeWs("My Sheet"), "Sheet1": ws})
    assert excel_range.resolve_sheet_range(wb, ws, "'My Sheet'!A1").addr == "My Sheet!A1"
    assert excel_range.resolve_sheet_range(wb, ws, "B2").addr == "Sheet1!B2"


def test_move_uses_cut_not_copy_clear():
    ws = FakeWs("Sheet1")
    wb = FakeWb({"Sheet1": ws})
    res = excel_range.execute(wb, ws, {"action": "move", "range": "A1:B2", "dest": "B2"})
    assert res["status"] == "ok"
    src = ws.Range("A1:B2")
    assert src.calls == [("Cut", "Sheet1!B2")]


def test_merge_requires_range():
    ws = FakeWs("Sheet1")
    res = excel_range.execute(FakeWb({}), ws, {"action": "merge"})
    assert res["status"] == "error"
