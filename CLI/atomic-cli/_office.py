"""atomic-cli Office COM 공통 모듈 (excel.py, word.py, ppt.py, office.py가 사용).

- 대상 해석: "active" / 열린 문서 이름 / 파일 경로 -> 실제 문서
- 세션: 사용자가 연 문서는 그대로 사용(닫지 않음), 닫힌 파일은 전용 백그라운드 인스턴스로 열고 정리
- 읽기 세션: 시트/파일을 만들지 않고, 저장하지 않으며, 사용자 화면(활성 시트, 스크롤, 슬라이드)을 움직이지 않음
- 쓰기 세션: 작업 전 스냅샷(되돌리기용), 작업 후 실제로 고친 시트/슬라이드로만 화면 이동(--no-focus로 끔)
- 스냅샷: 원본 문서를 저장하거나 경로를 바꾸지 않음 (Excel/PPT SaveCopyAs, Word 파일 복사 또는 WordOpenXML)
"""
import glob
import hashlib
import json
import os
import shutil
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

import _runtime as rt

try:
    import pythoncom
    import win32com.client
    import win32gui
except ImportError:  # 비 Windows 환경(테스트)에서도 import는 되도록
    pythoncom = None
    win32com = None
    win32gui = None

KINDS = ("excel", "word", "ppt")
APP_LABEL = {"excel": "Excel", "word": "Word", "ppt": "PowerPoint"}
PROG_ID = {"excel": "Excel.Application", "word": "Word.Application", "ppt": "PowerPoint.Application"}
FRAME_CLASS = {"excel": ("XLMAIN",), "word": ("OpusApp",), "ppt": ("PPTFrameClass", "PP12FrameClass")}
DOC_CLASS = {"excel": "EXCEL7", "word": "_WwG", "ppt": "paneClassDC"}
EXTENSIONS = {
    "excel": {".xlsx": 51, ".xlsm": 52, ".xlsb": 50, ".xls": 56},
    "word": {".docx": 16, ".docm": 13, ".doc": 0, ".rtf": 6},
    "ppt": {".pptx": 24, ".pptm": 25, ".ppt": 1},
}
SNAPSHOT_MAX_BYTES = 50 * 1024 * 1024   # 이보다 큰 문서는 스냅샷 생략 (경고만)
SNAPSHOT_KEEP = 5                        # 문서별 보관 개수


def require_com() -> None:
    if win32com is None:
        raise rt.InputError("Office 작업에는 pywin32가 필요합니다 (python -m pip install pywin32). "
                            "Office 없이 파일만 읽으려면 reader.py read --file 을 쓰세요.")


def init_com() -> None:
    if pythoncom is not None:
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass


# ==============================================================================
# 1. 실행 중인 Office 탐색
# ==============================================================================

def _enum_windows(match) -> List[int]:
    """EnumWindows 콜백은 항상 True를 반환합니다 (False 반환 시 pywin32가 예외를 던질 수 있음)."""
    found: List[int] = []

    def _cb(hwnd, _):
        try:
            if match(win32gui.GetClassName(hwnd)):
                found.append(hwnd)
        except Exception:
            pass
        return True
    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    return found


def _enum_children(parent: int, class_name: str) -> List[int]:
    found: List[int] = []

    def _cb(hwnd, _):
        try:
            if win32gui.GetClassName(hwnd) == class_name:
                found.append(hwnd)
        except Exception:
            pass
        return True
    try:
        win32gui.EnumChildWindows(parent, _cb, None)
    except Exception:
        pass
    return found


def _dispatch_from_hwnd(hwnd: int) -> Optional[Any]:
    """문서 창 핸들에서 oleacc로 COM 객체를 얻습니다 (여러 Office 프로세스를 구분하기 위함)."""
    try:
        import ctypes
        ptr = ctypes.c_void_p()
        iid = ctypes.create_string_buffer(bytes(pythoncom.IID_IDispatch))
        if ctypes.windll.oleacc.AccessibleObjectFromWindow(hwnd, 0xFFFFFFF0, iid, ctypes.byref(ptr)) == 0 and ptr.value:
            return win32com.client.Dispatch(pythoncom.ObjectFromAddress(ptr.value, pythoncom.IID_IDispatch))
    except Exception:
        pass
    return None


def _window_pid(hwnd: int) -> Optional[int]:
    try:
        import win32process
        return win32process.GetWindowThreadProcessId(hwnd)[1]
    except Exception:
        return None


def find_apps(kind: str) -> List[Any]:
    """실행 중인 Office 인스턴스를 프로세스 단위로 중복 없이 모읍니다. 포그라운드 창의 앱이 맨 앞."""
    require_com()
    init_com()
    apps: List[Any] = []
    if win32gui is not None:
        frames = _enum_windows(lambda c: c in FRAME_CLASS[kind])
        try:
            fg = win32gui.GetForegroundWindow()
            frames.sort(key=lambda h: 0 if h == fg else 1)
        except Exception:
            pass
        seen = set()
        for frame in frames:
            pid = _window_pid(frame)
            if pid is not None and pid in seen:
                continue
            for child in _enum_children(frame, DOC_CLASS[kind]):
                disp = _dispatch_from_hwnd(child)
                app = getattr(disp, "Application", None) if disp is not None else None
                if app is not None:
                    apps.append(win32com.client.Dispatch(app))
                    if pid is not None:
                        seen.add(pid)
                    break
    if not apps:
        try:
            apps.append(win32com.client.GetActiveObject(PROG_ID[kind]))
        except Exception:
            pass
    return apps


def _collection(app: Any, kind: str) -> Any:
    return getattr(app, {"excel": "Workbooks", "word": "Documents", "ppt": "Presentations"}[kind])


def _active_doc(app: Any, kind: str) -> Optional[Any]:
    attr = {"excel": "ActiveWorkbook", "word": "ActiveDocument", "ppt": "ActivePresentation"}[kind]
    try:
        doc = getattr(app, attr)
        if doc is not None:
            return doc
    except Exception:
        pass
    try:
        coll = _collection(app, kind)
        if coll.Count > 0:
            return coll(1)
    except Exception:
        pass
    return None


def _is_saved(doc: Any) -> bool:
    saved = getattr(doc, "Saved", True)
    return saved != 0 if isinstance(saved, int) and not isinstance(saved, bool) else bool(saved)


def list_open(kind: str) -> List[Dict[str, Any]]:
    """열린 문서 목록 [{name, path, saved, active, app, doc}] (전체 경로 기준으로 중복 제거)."""
    docs: List[Dict[str, Any]] = []
    seen = set()
    for app in find_apps(kind):
        try:
            active = _active_doc(app, kind)
            active_full = str(active.FullName) if active is not None else ""
            coll = _collection(app, kind)
            for i in range(1, coll.Count + 1):
                doc = coll(i)
                full = str(getattr(doc, "FullName", "") or doc.Name)
                if full.lower() in seen:
                    continue
                seen.add(full.lower())
                docs.append({"name": str(doc.Name), "path": full if os.path.isabs(full) else "",
                             "saved": _is_saved(doc),
                             "active": full == active_full, "app": app, "doc": doc})
        except Exception as e:
            rt.debug(f"{APP_LABEL[kind]} 문서 목록 수집 예외: {e}")
    return docs


def get_active(kind: str) -> Dict[str, Any]:
    """사용자가 보고 있는 문서. 포그라운드 앱의 활성 문서를 우선합니다."""
    for app in find_apps(kind):
        doc = _active_doc(app, kind)
        if doc is not None:
            full = str(getattr(doc, "FullName", "") or doc.Name)
            return {"name": str(doc.Name), "path": full if os.path.isabs(full) else "", "app": app, "doc": doc}
    raise rt.InputError(f"열려 있는 {APP_LABEL[kind]} 문서가 없습니다. 문서를 열거나 --target에 파일 경로를 지정하세요.")


def match_open(kind: str, target: str, docs: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """열린 문서 중 이름/파일명/전체 경로가 target과 같은 것 (대소문자 무시)."""
    docs = list_open(kind) if docs is None else docs
    t = target.strip().strip('"')
    t_low = t.lower()
    t_abs = os.path.normcase(os.path.abspath(t)) if (os.sep in t or "/" in t or ":" in t) else None
    for d in docs:
        if d["name"].lower() == t_low or (d["path"] and os.path.basename(d["path"]).lower() == t_low):
            return d
        if t_abs and d["path"] and os.path.normcase(d["path"]) == t_abs:
            return d
    return None


# ==============================================================================
# 2. 스냅샷 (되돌리기)
# ==============================================================================

def _snapshot_dir() -> str:
    path = os.path.join(rt.get_cache_dir(), "snapshots")
    os.makedirs(path, exist_ok=True)
    return path


def save_snapshot(kind: str, doc: Any, tool: str = "", command: str = "") -> Optional[str]:
    """쓰기 직전 문서 상태를 저장합니다. 원본 문서는 저장하거나 경로를 바꾸지 않습니다. 실패해도 작업은 계속합니다."""
    try:
        name = str(doc.Name)
        full = str(getattr(doc, "FullName", "") or "")
        path = full if os.path.isabs(full) else ""
        if path and os.path.exists(path) and os.path.getsize(path) > SNAPSHOT_MAX_BYTES:
            rt.log("WARN", f"문서가 커서({os.path.getsize(path) // 1048576}MB) 되돌리기용 스냅샷을 만들지 않았습니다.")
            return None
        key = hashlib.sha1((path or name).lower().encode("utf-8")).hexdigest()[:10]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")   # 연속 쓰기에도 이름이 겹치지 않도록 마이크로초까지
        base = os.path.join(_snapshot_dir(), f"{kind}_{key}_{stamp}")
        ext = (os.path.splitext(path)[1].lower() if path else "") or {"excel": ".xlsx", "word": ".docx", "ppt": ".pptx"}[kind]
        fmt = "native"
        data_file = base + ext
        if kind in ("excel", "ppt"):
            doc.SaveCopyAs(os.path.normpath(data_file))
        elif path and os.path.exists(path) and bool(getattr(doc, "Saved", False)):
            shutil.copy2(path, data_file)
        else:
            data_file = base + ".xml"
            fmt = "flat_xml"
            with open(data_file, "w", encoding="utf-8") as f:
                f.write(doc.WordOpenXML)
        if not os.path.exists(data_file):
            return None
        meta = {"app": kind, "name": name, "original_path": path, "snapshot_file": data_file,
                "snapshot_format": fmt, "created_at": stamp, "by": f"{tool} {command}".strip()}
        rt.atomic_write_text(base + ".json", json.dumps(meta, ensure_ascii=False))
        _rotate_snapshots(kind, key)
        rt.debug(f"스냅샷 저장: {os.path.basename(data_file)}")
        return data_file
    except Exception as e:
        rt.log("WARN", f"되돌리기용 스냅샷을 만들지 못했습니다 (작업은 계속): {e}")
        return None


def delete_snapshot(meta_file: str) -> None:
    base = os.path.splitext(meta_file)[0]
    for f in glob.glob(glob.escape(base) + ".*"):
        try:
            os.remove(f)
        except OSError:
            pass


def _rotate_snapshots(kind: str, key: str) -> None:
    metas = sorted(glob.glob(os.path.join(_snapshot_dir(), f"{kind}_{key}_*.json")), reverse=True)  # 이름의 시각 순
    for old in metas[SNAPSHOT_KEEP:]:
        delete_snapshot(old)


def list_snapshots(kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """최신순 스냅샷 목록. 각 항목에 meta_file 포함."""
    pattern = f"{kind}_*.json" if kind else "*.json"
    result = []
    files = glob.glob(os.path.join(_snapshot_dir(), pattern))
    for mf in sorted(files, key=lambda f: os.path.basename(f).split("_", 2)[-1], reverse=True):  # 문서 무관 시각 순
        try:
            meta = json.loads(rt.read_text_file(mf))
            if os.path.exists(meta.get("snapshot_file", "")):
                meta["meta_file"] = mf
                result.append(meta)
        except Exception:
            continue
    return result


# ==============================================================================
# 3. 세션
# ==============================================================================

class OfficeTarget:
    """세션이 넘겨주는 대상 문서. 도구는 doc/app을 쓰고, 고친 위치를 set_focus로 알려 줍니다."""

    def __init__(self, kind: str, app: Any, doc: Any, source: str, readonly: bool):
        self.kind = kind
        self.app = app
        self.doc = doc
        self.source = source          # active | open | file | new
        self.readonly = readonly
        self.focus_sheet: Optional[Any] = None
        self.focus_slide: Optional[int] = None
        self.changed = False

    @property
    def name(self) -> str:
        return str(self.doc.Name)

    @property
    def path(self) -> str:
        full = str(getattr(self.doc, "FullName", "") or "")
        return full if os.path.isabs(full) else ""

    def resolved(self) -> Dict[str, Any]:
        """결과 JSON의 target_resolved 값 (LLM이 실제 작업 대상을 알 수 있도록)."""
        info: Dict[str, Any] = {"app": APP_LABEL[self.kind], "name": self.name, "path": self.path, "source": self.source}
        if self.focus_sheet is not None:
            try:
                info["sheet"] = str(self.focus_sheet.Name)
            except Exception:
                pass
        if self.focus_slide is not None:
            info["slide"] = self.focus_slide
        return info

    # --- Excel ---
    def sheet(self, name: Optional[str] = None, create: bool = False) -> Any:
        """시트를 찾습니다 (대소문자 무시). 없으면 쓰기 세션 + create=True일 때만 만들고, 아니면 [추천]과 함께 오류."""
        sheets = self.doc.Worksheets
        if not name:
            try:
                ws = self.doc.ActiveSheet
                _ = ws.UsedRange          # 차트 시트에는 UsedRange가 없음 -> 첫 워크시트 사용
                return ws
            except Exception:
                return sheets(1)
        names = [str(sheets(i).Name) for i in range(1, sheets.Count + 1)]
        exact = rt.find_name(name, names)
        if exact is not None:
            return sheets(exact)
        if create and not self.readonly:
            ws = sheets.Add(After=sheets(sheets.Count))
            ws.Name = name
            self.changed = True
            return ws
        raise rt.not_found("시트", name, names)

    def set_focus(self, sheet: Any = None, slide: Optional[int] = None) -> None:
        """쓰기 후 사용자 화면을 이동할 위치를 기록합니다 (세션 종료 시 적용)."""
        if sheet is not None:
            self.focus_sheet = sheet
        if slide is not None:
            self.focus_slide = int(slide)
        self.changed = True

    def apply_focus(self) -> None:
        if self.readonly or self.source not in ("active", "open"):
            return
        try:
            if self.kind == "excel" and self.focus_sheet is not None:
                self.focus_sheet.Activate()
            elif self.kind == "ppt" and self.focus_slide is not None:
                view = self.app.ActiveWindow.View
                if self.app.ActiveWindow.Presentation.FullName == self.doc.FullName:
                    view.GotoSlide(self.focus_slide)
            elif self.kind == "word":
                self.doc.Activate()
        except Exception as e:
            rt.debug(f"화면 이동 생략: {e}")


def _new_instance(kind: str) -> Any:
    """전용 백그라운드 인스턴스. Excel/Word는 DispatchEx로 사용자 창과 분리됩니다."""
    if kind == "ppt":   # PowerPoint는 단일 인스턴스 앱: 사용자 창 상태는 건드리지 않음
        return win32com.client.Dispatch(PROG_ID[kind])
    app = win32com.client.DispatchEx(PROG_ID[kind])
    app.Visible = False
    if kind == "excel":
        app.DisplayAlerts = False
        try:
            app.AskToUpdateLinks = False
        except Exception:
            pass
    else:
        app.DisplayAlerts = 0
    return app


def _ppt_running() -> bool:
    try:
        win32com.client.GetActiveObject(PROG_ID["ppt"])
        return True
    except Exception:
        return False


def _open_file(kind: str, app: Any, path: str, readonly: bool) -> Any:
    if kind == "excel":
        return app.Workbooks.Open(path, UpdateLinks=0, ReadOnly=readonly, AddToMru=False)
    if kind == "word":
        return app.Documents.Open(path, ConfirmConversions=False, ReadOnly=readonly, AddToRecentFiles=False, Visible=False)
    return app.Presentations.Open(path, -1 if readonly else 0, 0, 0)   # ReadOnly, Untitled, WithWindow=False


def _create_file(kind: str, app: Any, path: str) -> Any:
    fmt = EXTENSIONS[kind].get(os.path.splitext(path)[1].lower())
    if kind == "excel":
        doc = app.Workbooks.Add()
        doc.SaveAs(path, FileFormat=fmt) if fmt is not None else doc.SaveAs(path)
    elif kind == "word":
        doc = app.Documents.Add(Visible=False)
        doc.SaveAs2(path, FileFormat=fmt) if fmt is not None else doc.SaveAs2(path)
    else:
        doc = app.Presentations.Add(0)
        doc.SaveAs(path, fmt) if fmt is not None else doc.SaveAs(path)
    return doc


@contextmanager
def open_target(kind: str, target: str = "active", readonly: bool = True, snapshot: Optional[bool] = None,
                focus: bool = True, create: bool = False, tool: str = "", command: str = "") -> Iterator[OfficeTarget]:
    """대상 문서를 열어 OfficeTarget을 넘겨줍니다.

    target: "active" | 열린 문서 이름 | 파일 경로
    readonly: 읽기 세션 (저장/생성/화면 이동 없음)
    snapshot: 쓰기 전 스냅샷 (기본: 쓰기 세션이면 True)
    focus: 쓰기 후 고친 위치로 화면 이동 (--no-focus면 False)
    create: 파일이 없을 때 새로 만들지 (쓰기 세션 전용)
    """
    require_com()
    init_com()
    if snapshot is None:
        snapshot = not readonly
    target = (target or "active").strip()

    app = doc = None
    owns_app = owns_doc = False
    restore_alerts = None
    t: Optional[OfficeTarget] = None
    try:
        if target.lower() == "active":
            info = get_active(kind)
            t = OfficeTarget(kind, info["app"], info["doc"], "active", readonly)
        else:
            docs = list_open(kind)
            hit = match_open(kind, target, docs)
            if hit is not None:
                t = OfficeTarget(kind, hit["app"], hit["doc"], "open", readonly)
            else:
                path = os.path.abspath(os.path.expandvars(target.strip('"')))
                exists = os.path.isfile(path)
                if not exists and not os.path.isabs(target) and os.path.isfile(os.path.join(rt.get_data_dir(), target)):
                    path, exists = os.path.join(rt.get_data_dir(), target), True
                if not exists and (readonly or not create):
                    raise rt.not_found(f"{APP_LABEL[kind]} 문서", target, [d["name"] for d in docs],
                                       extra=" (열린 문서 이름도 아니고 파일도 없음)")
                ext = os.path.splitext(path)[1].lower()
                if ext not in EXTENSIONS[kind]:
                    raise rt.InputError(f"{APP_LABEL[kind]} 파일 확장자가 아닙니다: {ext} (지원: {', '.join(EXTENSIONS[kind])})")
                ppt_was_running = _ppt_running() if kind == "ppt" else False
                app = _new_instance(kind)
                owns_app = kind != "ppt" or not ppt_was_running
                if kind == "ppt":
                    try:
                        restore_alerts = app.DisplayAlerts
                        app.DisplayAlerts = 1  # ppAlertsNone
                    except Exception:
                        restore_alerts = None
                rt.log("PROGRESS", f"{APP_LABEL[kind]} 파일 {'여는' if exists else '만드는'} 중 (백그라운드): {os.path.basename(path)}")
                doc = _open_file(kind, app, path, readonly) if exists else _create_file(kind, app, path)
                owns_doc = True
                t = OfficeTarget(kind, app, doc, "file" if exists else "new", readonly)

        if snapshot and not readonly and t.source != "new":
            save_snapshot(kind, t.doc, tool, command)

        yield t

        if not readonly and focus:
            t.apply_focus()
        if owns_doc and not readonly and not _is_saved(t.doc):
            rt.log("PROGRESS", "변경사항 저장 중")
            t.doc.Save()
    finally:
        if owns_doc and t is not None:
            try:
                if kind == "word":
                    t.doc.Close(SaveChanges=0)
                elif kind == "excel":
                    t.doc.Close(SaveChanges=False)
                else:
                    t.doc.Close()
            except Exception:
                pass
        if app is not None:
            if restore_alerts is not None and not owns_app:
                try:
                    app.DisplayAlerts = restore_alerts
                except Exception:
                    pass
            if owns_app:
                try:
                    if kind == "word":
                        app.Quit(SaveChanges=0)
                    elif kind == "excel" or app.Presentations.Count == 0:
                        app.Quit()
                except Exception:
                    pass
        t = None
        app = doc = None
        import gc
        gc.collect()


@contextmanager
def excel_batch(app: Any) -> Iterator[None]:
    """Excel 대량 쓰기 동안 화면 갱신/자동 계산/이벤트를 끄고, 끝나면 원래대로 되돌립니다."""
    saved = {}
    for attr, value in (("ScreenUpdating", False), ("EnableEvents", False), ("Calculation", -4135)):  # xlCalculationManual
        try:
            saved[attr] = getattr(app, attr)
            setattr(app, attr, value)
        except Exception:
            pass
    try:
        yield
    finally:
        for attr in ("Calculation", "EnableEvents", "ScreenUpdating"):
            if attr in saved:
                try:
                    setattr(app, attr, saved[attr])
                except Exception:
                    pass


def range_to_matrix(values: Any) -> List[List[Any]]:
    """Range.Value/Formula 결과를 항상 2차원 리스트로 (단일 셀은 스칼라, 여러 셀은 한 행이어도 튜플의 튜플)."""
    if not isinstance(values, (tuple, list)):
        return [[values]]
    return [list(row) if isinstance(row, (tuple, list)) else [row] for row in values]


def open_documents_summary() -> List[Dict[str, Any]]:
    """세 앱의 열린 문서를 한 목록으로 (office.py windows, *.py info --all 용)."""
    result = []
    for kind in KINDS:
        try:
            for d in list_open(kind):
                result.append({"app": APP_LABEL[kind], "name": d["name"], "path": d["path"],
                               "saved": d["saved"], "active": d["active"]})
        except rt.InputError:
            raise
        except Exception as e:
            rt.debug(f"{APP_LABEL[kind]} 목록 실패: {e}")
    return result
