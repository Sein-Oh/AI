"""메모리 셀 격자로 동작하는 가짜 Excel (excel.py 명령 로직 테스트용).

지원: Range("A1:B2" / "A1:B2,A4:B4") / Range(cell, cell) / Cells(r, c), Value(읽기/쓰기, 스칼라 채우기),
Formula(쓰기 시 상대참조 문자열 그대로 저장), Row/Column/Rows.Count/Columns.Count/Address, UsedRange,
End(xlUp), 서식 속성 기록(Interior/Font/Borders/NumberFormat ...), ChartObjects, Cut/Copy/Merge.
"""
import re


def col_num(s):
    n = 0
    for ch in s.upper():
        n = n * 26 + ord(ch) - 64
    return n


def col_let(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class Props:
    """임의 속성을 기록하는 객체 (Interior.Color, Font.Bold 등)."""

    def __init__(self):
        object.__setattr__(self, "_d", {})

    def __getattr__(self, k):
        d = object.__getattribute__(self, "_d")
        if k not in d:
            d[k] = Props()
        return d[k]

    def __setattr__(self, k, v):
        object.__getattribute__(self, "_d")[k] = v

    def get(self, k, default=None):
        return object.__getattribute__(self, "_d").get(k, default)


class Count:
    def __init__(self, n):
        self.Count = n


class FakeFormatConditions:
    def __init__(self):
        self.items = []

    def Add(self, **kw):
        fc = Props()
        fc.kw = kw
        self.items.append(fc)
        return fc

    def Delete(self):
        self.items.clear()


class FakeRange:
    def __init__(self, ws, areas):
        self.ws = ws
        self.areas = areas          # [(r1, c1, r2, c2)]

    # --- 위치 ---
    @property
    def Row(self):
        return self.areas[0][0]

    @property
    def Column(self):
        return self.areas[0][1]

    @property
    def Rows(self):
        r1, c1, r2, c2 = self.areas[0]
        rng = Count(r2 - r1 + 1)
        rng.AutoFit = lambda: self.ws.log.append(("RowsAutoFit", self.Address))
        return rng

    @property
    def Columns(self):
        r1, c1, r2, c2 = self.areas[0]
        rng = Count(c2 - c1 + 1)
        rng.AutoFit = lambda: self.ws.log.append(("AutoFit", self.Address))
        return rng

    @property
    def Address(self):
        parts = []
        for r1, c1, r2, c2 in self.areas:
            a = f"${col_let(c1)}${r1}"
            if (r1, c1) != (r2, c2):
                a += f":${col_let(c2)}${r2}"
            parts.append(a)
        return ",".join(parts)

    @property
    def Worksheet(self):
        return self.ws

    @property
    def Left(self):
        return (self.Column - 1) * 48.0

    @property
    def Top(self):
        return (self.Row - 1) * 15.0

    def Cells(self, r, c):
        return FakeRange(self.ws, [(self.Row + r - 1, self.Column + c - 1) * 2])

    def cells(self):
        for r1, c1, r2, c2 in self.areas:
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    yield r, c

    # --- 값 ---
    @property
    def Value(self):
        r1, c1, r2, c2 = self.areas[0]
        if (r1, c1) == (r2, c2):
            return self.ws.values.get((r1, c1))
        return tuple(tuple(self.ws.values.get((r, c)) for c in range(c1, c2 + 1)) for r in range(r1, r2 + 1))

    @Value.setter
    def Value(self, v):
        r1, c1, r2, c2 = self.areas[0]
        if isinstance(v, tuple):
            for i, row in enumerate(v):
                for j, x in enumerate(row):
                    self.ws.set(r1 + i, c1 + j, x)
        else:
            for r, c in self.cells():
                self.ws.set(r, c, v)

    @property
    def Formula(self):
        r1, c1, r2, c2 = self.areas[0]

        def f(r, c):
            return self.ws.formulas.get((r, c), self.ws.values.get((r, c)) if self.ws.values.get((r, c)) is not None else "")
        if (r1, c1) == (r2, c2):
            return f(r1, c1)
        return tuple(tuple(f(r, c) for c in range(c1, c2 + 1)) for r in range(r1, r2 + 1))

    @Formula.setter
    def Formula(self, v):
        for r, c in self.cells():
            self.ws.formulas[(r, c)] = v
            self.ws.values[(r, c)] = f"<{v}>"
        self.ws.log.append(("Formula", self.Address, v))

    # --- 서식/조작 ---
    def __getattr__(self, name):
        if name in ("Interior", "Font", "Borders_"):
            return self.ws.props(self.Address, name)
        raise AttributeError(name)

    def __setattr__(self, k, v):
        if k in ("ws", "areas", "Value", "Formula"):
            object.__setattr__(self, k, v)
        else:
            self.ws.log.append(("set", self.Address, k, v))

    def Borders(self, i):
        return self.ws.props(self.Address, f"Border{i}")

    @property
    def FormatConditions(self):
        return self.ws.fcs.setdefault(self.Address, FakeFormatConditions())

    def End(self, direction):
        r1, c1, _, _ = self.areas[0]
        filled = [r for (r, c) in self.ws.values if c == c1 and self.ws.values[(r, c)] is not None]
        last = max(filled) if filled else 1
        return FakeRange(self.ws, [(last, c1, last, c1)])

    def Cut(self, Destination=None):
        self.ws.log.append(("Cut", self.Address, Destination.Address))

    def Copy(self, Destination=None):
        self.ws.log.append(("Copy", self.Address, Destination.Address if Destination else None))

    def Merge(self):
        self.ws.log.append(("Merge", self.Address, self.ws.app.DisplayAlerts))

    def UnMerge(self):
        self.ws.log.append(("UnMerge", self.Address))

    def ClearFormats(self):
        self.ws.log.append(("ClearFormats", self.Address))

    def ClearContents(self):
        for k in list(self.cells()):
            self.ws.values.pop(k, None)

    def Clear(self):
        self.ClearContents()

    def Select(self):
        self.ws.log.append(("Select", self.Address))


class FakeChartObject:
    def __init__(self, ws, name):
        self.ws = ws
        self.Name = name
        self.Chart = Props()
        self.Chart.HasTitle = False
        self.series = []
        chart = self.Chart

        def set_source(rng):
            ncols = rng.Columns.Count
            self.series = [Props() for _ in range(max(1, ncols - 1))]
        chart.SetSourceData = set_source
        chart.SeriesCollection = self._series
        chart.ApplyDataLabels = lambda: None

    def _series(self, i=None):
        if i is None:
            obj = Count(len(self.series))
            obj.__class__ = type("S", (Count,), {"__call__": lambda s, k: self.series[k - 1]})
            return obj
        return self.series[i - 1]

    def Delete(self):
        self.ws.charts.remove(self)


class FakeChartObjects:
    def __init__(self, ws):
        self.ws = ws

    @property
    def Count(self):
        return len(self.ws.charts)

    def Item(self, i):
        return self.ws.charts[i - 1]

    def Add(self, left, top, width, height):
        obj = FakeChartObject(self.ws, f"Chart {len(self.ws.charts) + 1}")
        self.ws.charts.append(obj)
        return obj

    def Delete(self):
        self.ws.charts.clear()


class FakeWorksheet:
    def __init__(self, app, wb, name):
        self.app = app
        self.wb = wb
        self.Name = name
        self.values = {}
        self.formulas = {}
        self.styles = {}
        self.fcs = {}
        self.log = []
        self.charts = []
        self.activated = 0
        self.Shapes = Count(0)
        self.Rows = Count(1048576)

    def set(self, r, c, v):
        self.values[(r, c)] = v
        self.formulas.pop((r, c), None)

    def props(self, address, name):
        return self.styles.setdefault((address, name), Props())

    def _parse(self, ref):
        areas = []
        for part in ref.replace("$", "").split(","):
            m = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", part.strip().upper())
            if not m:
                raise Exception(f"bad address {ref}")
            r1, c1 = int(m.group(2)), col_num(m.group(1))
            r2, c2 = (int(m.group(4)), col_num(m.group(3))) if m.group(3) else (r1, c1)
            areas.append((r1, c1, r2, c2))
        return areas

    def Range(self, a, b=None):
        if b is not None:
            return FakeRange(self, [(a.Row, a.Column, b.Row, b.Column)])
        return FakeRange(self, self._parse(a))

    def Cells(self, r, c):
        return FakeRange(self, [(r, c, r, c)])

    @property
    def UsedRange(self):
        keys = [k for k, v in self.values.items() if v is not None]
        if not keys:
            return FakeRange(self, [(1, 1, 1, 1)])
        r1 = min(r for r, _ in keys)
        c1 = min(c for _, c in keys)
        r2 = max(r for r, _ in keys)
        c2 = max(c for _, c in keys)
        return FakeRange(self, [(r1, c1, r2, c2)])

    def ChartObjects(self):
        return FakeChartObjects(self)

    def Activate(self):
        self.activated += 1
        self.wb.active = self

    def Delete(self):
        self.wb.sheets.remove(self)

    def Copy(self, After=None):
        clone = FakeWorksheet(self.app, self.wb, self.Name + " (2)")
        clone.values = dict(self.values)
        self.wb.sheets.append(clone)


class FakeSheetsColl:
    def __init__(self, wb):
        self.wb = wb

    @property
    def Count(self):
        return len(self.wb.sheets)

    def __call__(self, key):
        if isinstance(key, int):
            return self.wb.sheets[key - 1]
        for s in self.wb.sheets:
            if s.Name == key:
                return s
        raise Exception("no sheet")

    def Add(self, After=None):
        ws = FakeWorksheet(self.wb.app, self.wb, f"Sheet{len(self.wb.sheets) + 1}")
        self.wb.sheets.append(ws)
        return ws


class FakeExcelWorkbook:
    def __init__(self, app, name="Book1.xlsx", sheets=("Sheet1",)):
        self.app = app
        self.Name = name
        self.FullName = "C:\\docs\\" + name
        self.Saved = True
        self.sheets = [FakeWorksheet(app, self, n) for n in sheets]
        self.active = self.sheets[0]
        self.Worksheets = FakeSheetsColl(self)

    @property
    def ActiveSheet(self):
        return self.active

    def SaveCopyAs(self, path):
        open(path, "wb").close()


class FakeXlApp:
    def __init__(self):
        self.DisplayAlerts = True
        self.ScreenUpdating = True
        self.EnableEvents = True
        self.Calculation = -4105
        self.Selection = Props()
        self.Selection.Address = "$A$1"
