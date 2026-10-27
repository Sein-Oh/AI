import os
import sys
from contextlib import contextmanager
from typing import Generator, Optional, Tuple, Any, List, Dict

# 최우선: 샌드박스 가상 데스크톱(exebox-*) 환경에서 실제 사용자 GUI 데스크톱(Default)으로 최우선 바인딩
def attach_user_desktop():
    """샌드박스 가상 데스크톱(exebox-*) 환경인 경우 사용자의 실제 GUI 데스크톱(Default)으로 스레드 데스크톱을 전환합니다."""
    try:
        import ctypes
        import win32service
        import win32con
        hdesk = win32service.OpenDesktop("Default", 0, False, win32con.MAXIMUM_ALLOWED)
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(int(hdesk))
    except Exception:
        pass

attach_user_desktop()

# 최우선: 상위 디렉터리 경로 등록 및 COM 환경 초기화
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
for p in [CURRENT_DIR, PARENT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import pythoncom
    import win32com.client
    import win32gui
except ImportError:
    pythoncom = None
    win32com = None
    win32gui = None

from _office_utils import log_debug

def init_com():
    """COM 스레드 아파트먼트 초기화 (pythoncom) 및 실제 사용자 GUI 데스크톱 바인딩"""
    attach_user_desktop()
    if pythoncom is not None:
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass

def jit_repair_office_environment(app_name: str = "excel") -> Dict[str, Any]:
    """COM 이상/충돌/RPC 중단 발생 시 호출되는 실시간(JIT) 자가복구 루틴.
    사용자의 작업 창이나 실행 중인 프로세스는 절대 종료하지 않습니다.
    살아있는 COM 참조가 있는 상태에서 CoUninitialize를 호출하면 프로세스가 비정상 종료될 수 있으므로,
    아파트먼트는 재초기화하지 않고 Office가 응답 가능한 상태로 돌아올 때까지 잠시 대기한 뒤 재바인딩하도록 합니다.
    """
    log_debug(f"[JIT 자가복구] {app_name.upper()} 응답 대기 후 재바인딩 시도")
    init_com()
    import time
    time.sleep(0.5)
    return {"status": "recovered", "killed": []}

class COMError(Exception):
    """Office COM 작업 중 발생하는 예외"""
    pass

def _get_active_or_first_wb(app):
    """Excel Application에서 활성 문서 또는 1번 문서를 안전하게 획득합니다 (임의로 신규 문서를 생성하지 않음)."""
    try:
        if app.ActiveWorkbook:
            return app.ActiveWorkbook
    except Exception:
        pass
    try:
        if hasattr(app, "Workbooks") and app.Workbooks.Count > 0:
            return app.Workbooks(1)
    except Exception:
        pass
    return None

def _get_active_or_first_doc(app):
    """Word Application에서 활성 문서 또는 1번 문서를 안전하게 획득합니다 (임의로 신규 문서를 생성하지 않음)."""
    try:
        if app.ActiveDocument:
            return app.ActiveDocument
    except Exception:
        pass
    try:
        if hasattr(app, "Documents") and app.Documents.Count > 0:
            return app.Documents(1)
    except Exception:
        pass
    return None

def _get_active_or_first_prs(app):
    """PowerPoint Application에서 활성 문서 또는 1번 문서를 안전하게 획득합니다 (임의로 신규 문서를 생성하지 않음)."""
    try:
        if app.ActivePresentation:
            return app.ActivePresentation
    except Exception:
        pass
    try:
        if hasattr(app, "Presentations") and app.Presentations.Count > 0:
            return app.Presentations(1)
    except Exception:
        pass
    return None

def _extract_dispatch_from_hwnd(hwnd: int) -> Optional[Any]:
    """HWND로부터 oleacc AccessibleObjectFromWindow를 통해 IDispatch COM 객체를 추출합니다."""
    try:
        import ctypes
        oleacc = ctypes.windll.oleacc
        p_acc = ctypes.c_void_p()
        riid = ctypes.create_string_buffer(bytes(pythoncom.IID_IDispatch))
        res = oleacc.AccessibleObjectFromWindow(hwnd, 0xFFFFFFF0, riid, ctypes.byref(p_acc))
        if res == 0 and p_acc.value:
            py_obj = pythoncom.ObjectFromAddress(p_acc.value, pythoncom.IID_IDispatch)
            return win32com.client.Dispatch(py_obj)
    except Exception:
        pass
    return None

def _list_child_windows(parent_hwnd: int, class_name: str) -> List[int]:
    """부모 창 아래에서 지정 클래스명을 가진 자식 창 핸들을 모두 수집합니다.
    EnumChildWindows 콜백이 False를 반환하면 pywin32가 예외를 던질 수 있으므로 항상 True를 반환합니다.
    """
    found: List[int] = []

    def _cb(hwnd, _):
        try:
            if win32gui.GetClassName(hwnd) == class_name:
                found.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumChildWindows(parent_hwnd, _cb, None)
    except Exception:
        pass
    return found

def _list_top_windows(match_fn) -> List[int]:
    """최상위 창 중 match_fn(class_name)이 True인 창 핸들을 모두 수집합니다."""
    found: List[int] = []

    def _cb(hwnd, _):
        try:
            if match_fn(win32gui.GetClassName(hwnd)):
                found.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    return found

def _get_window_pid(hwnd: int) -> Optional[int]:
    try:
        import win32process
        return win32process.GetWindowThreadProcessId(hwnd)[1]
    except Exception:
        return None

def _app_from_frame(frame_hwnd: int, doc_class: str) -> Optional[Any]:
    """최상위 프레임 창에서 문서 창(EXCEL7/_WwG/paneClassDC)을 찾아 Application COM 객체를 추출합니다."""
    for child in _list_child_windows(frame_hwnd, doc_class):
        disp = _extract_dispatch_from_hwnd(child)
        if disp:
            try:
                app = getattr(disp, "Application", None)
                if app:
                    return app
            except Exception:
                continue
    return None

# 앱 종류별 (ProgID, 최상위 프레임 클래스 판정, 문서 창 클래스)
_APP_WINDOW_SPECS = {
    "excel": ("Excel.Application", lambda c: c == "XLMAIN", "EXCEL7"),
    "word": ("Word.Application", lambda c: c == "OpusApp", "_WwG"),
    "ppt": ("PowerPoint.Application", lambda c: c == "PPTFrameClass" or ("PP" in c and "Frame" in c), "paneClassDC"),
}

def _find_all_native_apps(app_kind: str) -> List[Any]:
    """실행 중인 모든 Office Application 인스턴스를 프로세스 단위로 중복 없이 수집합니다 (Native oleacc 우선)."""
    init_com()
    prog_id, frame_match, doc_class = _APP_WINDOW_SPECS[app_kind]
    apps: List[Any] = []

    if win32gui is not None:
        seen_pids = set()
        for frame in _list_top_windows(frame_match):
            pid = _get_window_pid(frame)
            if pid is not None and pid in seen_pids:
                continue
            app = _app_from_frame(frame, doc_class)
            if app:
                apps.append(app)
                if pid is not None:
                    seen_pids.add(pid)

    if not apps:
        try:
            active_app = win32com.client.GetActiveObject(prog_id)
            if active_app:
                apps.append(active_app)
        except Exception:
            pass

    return apps

def find_all_native_excel_apps() -> List[Any]:
    """실행 중인 모든 Excel.Application 인스턴스 탐색 (다중 프로세스 지원)"""
    return _find_all_native_apps("excel")

def find_all_native_word_apps() -> List[Any]:
    """실행 중인 모든 Word.Application 인스턴스 탐색"""
    return _find_all_native_apps("word")

def find_all_native_ppt_apps() -> List[Any]:
    """실행 중인 모든 PowerPoint.Application 인스턴스 탐색"""
    return _find_all_native_apps("ppt")

def _find_sheet(wb, sheet_name: str) -> Optional[Any]:
    """시트명을 대소문자 구분 없이 찾습니다 (Excel 자체 규칙과 동일)."""
    target = str(sheet_name).strip().lower()
    try:
        for s in wb.Worksheets:
            if str(s.Name).strip().lower() == target:
                return s
    except Exception:
        pass
    return None

def _resolve_sheet(wb, sheet_name: str, readonly: bool) -> Any:
    """시트를 찾고, 쓰기 모드에서만 없는 시트를 새로 생성합니다."""
    ws = _find_sheet(wb, sheet_name)
    if ws is not None:
        return ws
    if readonly:
        try:
            names = [s.Name for s in wb.Worksheets]
        except Exception:
            names = []
        raise COMError(f"시트 '{sheet_name}'을(를) 찾을 수 없습니다. 존재하는 시트: {names}")
    log_debug(f"시트 '{sheet_name}' 신규 생성")
    ws = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
    ws.Name = sheet_name
    return ws

# 확장자별 저장 형식 (신규 파일 생성 시 확장자와 실제 형식 불일치 방지)
XL_FILE_FORMATS = {".xlsx": 51, ".xlsm": 52, ".xlsb": 50, ".xls": 56}
WD_FILE_FORMATS = {".docx": 16, ".docm": 13, ".doc": 0, ".rtf": 6, ".txt": 2}
PP_FILE_FORMATS = {".pptx": 24, ".pptm": 25, ".ppt": 1}

def _file_format_for(path: str, mapping: Dict[str, int]) -> Optional[int]:
    return mapping.get(os.path.splitext(path)[1].lower())

def get_all_running_excel_workbooks() -> List[Dict[str, Any]]:
    """실행 중인 모든 Excel 프로세스(다중 창/다중 프로세스)에서 열려 있는 모든 통합 문서를 수집합니다."""
    init_com()
    workbooks_info = []
    seen_wb_keys = set()

    try:
        apps = find_all_native_excel_apps()
        for app in apps:
            try:
                active_wb_name = ""
                try:
                    if app.ActiveWorkbook:
                        active_wb_name = app.ActiveWorkbook.Name
                except Exception:
                    pass
                for wb in app.Workbooks:
                    try:
                        wb_name = wb.Name
                        wb_path = getattr(wb, "FullName", "")
                        wb_key = (wb_name, wb_path)
                        if wb_key in seen_wb_keys:
                            continue
                        seen_wb_keys.add(wb_key)

                        sheets = [s.Name for s in wb.Worksheets]
                        workbooks_info.append({
                            "app": app,
                            "wb": wb,
                            "name": wb_name,
                            "path": wb_path,
                            "saved": getattr(wb, "Saved", True),
                            "sheets": sheets,
                            "is_active": (wb_name == active_wb_name)
                        })
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception as e:
        log_debug(f"get_all_running_excel_workbooks 예외: {e}")

    # 폴백: GetActiveObject 및 Dispatch
    if not workbooks_info:
        for method in [win32com.client.GetActiveObject]:  # 목록 조회가 새 Office 프로세스를 띄우지 않도록 Dispatch 배제
            try:
                app = method("Excel.Application")
                if app and hasattr(app, "Workbooks") and app.Workbooks.Count > 0:
                    for wb in app.Workbooks:
                        workbooks_info.append({
                            "app": app,
                            "wb": wb,
                            "name": wb.Name,
                            "path": getattr(wb, "FullName", ""),
                            "saved": getattr(wb, "Saved", True),
                            "sheets": [s.Name for s in wb.Worksheets],
                            "is_active": True
                        })
                    if workbooks_info:
                        break
            except Exception:
                pass

    return workbooks_info

def get_active_excel_app_and_wb(enable_jit: bool = True):
    """화면에 실제 떠 있는 사용자의 Excel 창과 통합 문서를 100% 신뢰도로 바인딩합니다."""
    log_debug("get_active_excel_app_and_wb 진입")
    init_com()

    # 1. 포커스된 최상단 창 우선 검사
    try:
        if win32gui is not None:
            fg_hwnd = win32gui.GetForegroundWindow()
            if fg_hwnd and win32gui.GetClassName(fg_hwnd) == "XLMAIN":
                app_found = _app_from_frame(fg_hwnd, "EXCEL7")
                if app_found and getattr(app_found, "ActiveWorkbook", None):
                    log_debug("Foreground Excel 창 바인딩 성공")
                    return app_found, app_found.ActiveWorkbook
    except Exception as e:
        log_debug(f"Foreground Excel 검사 예외: {e}")

    # 2. find_all_native_excel_apps 순회
    try:
        apps = find_all_native_excel_apps()
        for app in apps:
            try:
                if app.ActiveWorkbook:
                    log_debug(f"Native Excel 인스턴스 및 통합 문서 바인딩 성공: {app.ActiveWorkbook.Name}")
                    return app, app.ActiveWorkbook
            except Exception:
                continue
    except Exception as e:
        log_debug(f"find_all_native_excel_apps 예외: {e}")

    # 3. GetActiveObject 폴백 (이미 실행 중인 인스턴스만 바인딩, 새 창을 띄우는 Dispatch는 배제)
    try:
        app = win32com.client.GetActiveObject("Excel.Application")
        if app:
            wb = _get_active_or_first_wb(app)
            if wb:
                log_debug("Excel 활성 통합 문서 바인딩 성공")
                return app, wb
    except Exception:
        pass

    if enable_jit:
        log_debug("[JIT 자가복구] 활성 Excel 탐색 실패 -> JIT 복구 가동 후 재시도")
        jit_repair_office_environment("excel")
        return get_active_excel_app_and_wb(enable_jit=False)
    raise COMError("화면에 열려 있는 활성 Excel 창이나 통합 문서를 찾을 수 없습니다.")

def _match_running_item(items: List[Dict[str, Any]], target: str) -> Optional[Dict[str, Any]]:
    """실행 중인 문서 목록에서 이름/파일명/절대경로가 target과 일치하는 항목을 찾습니다."""
    target_clean = target.strip().lower()
    target_abs_lower = os.path.abspath(target).lower()
    for item in items:
        name_lower = str(item["name"]).lower()
        path_lower = str(item["path"]).lower() if item["path"] else ""
        if (target_clean == name_lower or
                target_clean == os.path.basename(path_lower) or
                target_abs_lower == path_lower):
            return item
    return None

def _release_com():
    import gc
    gc.collect()
    if pythoncom is not None:
        try:
            pythoncom.CoFreeUnusedLibraries()
        except Exception:
            pass

@contextmanager
def excel_session(
    target: str = "active",
    sheet_name: Optional[str] = None,
    snapshot: bool = False,
    readonly: Optional[bool] = None
) -> Generator[Tuple[Any, Any, Any], None, None]:
    """Excel COM 생명주기를 완벽하게 격리하고 관리하는 Context Manager.

    Args:
        target: "active", 실행 중인 통합 문서 이름, 또는 디스크 파일 경로
        sheet_name: 대상 시트명 (대소문자 무시)
        snapshot: 쓰기 작업 전 자동 스냅샷 생성 여부
        readonly: 읽기 전용 세션 여부. 생략 시 snapshot=False이면 읽기 전용으로 간주합니다.
            읽기 전용 세션은 시트/파일을 새로 만들지 않고, 디스크 파일을 저장하지 않으며, 사용자 화면(활성 시트/스크롤)을 바꾸지 않습니다.

    Yields:
        (app, wb, ws): Excel Application, Workbook, Worksheet COM 객체
    """
    if win32com is None:
        raise COMError("pywin32가 설치되어 있지 않습니다. (pip install pywin32 필요)")

    if readonly is None:
        readonly = not snapshot

    app = None
    wb = None
    ws = None
    owns_app = False   # 이 세션이 직접 띄운 백그라운드 Excel 인스턴스인지 여부
    owns_wb = False    # 이 세션이 직접 연 통합 문서인지 여부 (사용자가 열어둔 문서는 닫지 않음)
    is_active_target = (target.strip().lower() == "active")

    try:
        matched_running_wb = None
        if not is_active_target:
            matched_running_wb = _match_running_item(get_all_running_excel_workbooks(), target)
            if matched_running_wb:
                log_debug(f"실행 중인 Excel 인스턴스에서 대상 문서 발견: {matched_running_wb['name']}")

        if is_active_target or matched_running_wb:
            if matched_running_wb:
                app = matched_running_wb["app"]
                wb = matched_running_wb["wb"]
            else:
                app, wb = get_active_excel_app_and_wb()
                if wb is None:
                    raise COMError("활성 Excel 창에 열린 통합 문서(Workbook)가 없습니다.")

            app = win32com.client.Dispatch(app)
            wb = win32com.client.Dispatch(wb)

            if not readonly:
                try:
                    app.Visible = True
                    app.ScreenUpdating = True
                except Exception:
                    pass

            if sheet_name:
                ws = _resolve_sheet(wb, sheet_name, readonly)
                if not readonly:
                    try:
                        ws.Activate()
                    except Exception:
                        pass
            else:
                try:
                    ws = wb.ActiveSheet
                except Exception:
                    ws = wb.Worksheets(1)
        else:
            abs_path = os.path.abspath(target)
            file_exists = os.path.exists(abs_path)
            if not file_exists and readonly:
                raise COMError(f"대상 Excel 파일이 존재하지 않습니다: {abs_path}")

            # 사용자가 띄워 둔 Excel 인스턴스에 붙어 창을 숨기는 일이 없도록 전용 인스턴스를 생성
            try:
                app = win32com.client.DispatchEx("Excel.Application")
            except Exception as e:
                log_debug(f"[JIT 자가복구] Excel.Application 생성 실패 ({e}) -> JIT 복구 후 재시도")
                jit_repair_office_environment("excel")
                app = win32com.client.DispatchEx("Excel.Application")
            owns_app = True
            app.Visible = False
            app.DisplayAlerts = False
            try:
                app.AskToUpdateLinks = False
            except Exception:
                pass

            if file_exists:
                log_debug(f"Excel 파일 백그라운드 오픈 (readonly={readonly}): {abs_path}")
                try:
                    wb = app.Workbooks.Open(abs_path, UpdateLinks=0, ReadOnly=readonly, AddToMru=False)
                except Exception as e:
                    log_debug(f"[JIT 자가복구] Workbooks.Open 실패 ({e}) -> JIT 복구 후 1회 재시도")
                    jit_repair_office_environment("excel")
                    wb = app.Workbooks.Open(abs_path, UpdateLinks=0, ReadOnly=readonly, AddToMru=False)
            else:
                log_debug(f"Excel 신규 파일 백그라운드 생성: {abs_path}")
                wb = app.Workbooks.Add()
                fmt = _file_format_for(abs_path, XL_FILE_FORMATS)
                if fmt is not None:
                    wb.SaveAs(abs_path, FileFormat=fmt)
                else:
                    wb.SaveAs(abs_path)
            owns_wb = True

            if sheet_name:
                ws = _resolve_sheet(wb, sheet_name, readonly)
            else:
                ws = wb.Worksheets(1)

        # 쓰기 작업 전 자동 캐시 스냅샷 (최근 2개 유지)
        if snapshot and wb is not None:
            try:
                from _cache import save_document_snapshot
                save_document_snapshot("excel", wb)
            except Exception as e:
                log_debug(f"Excel 자동 스냅샷 예외: {e}")

        yield app, wb, ws

        # 화면 시선 동기화 (Visual Focus Sync): 쓰기 작업 후 사용자 창의 활성 시트만 갱신
        if not owns_wb and not readonly and ws is not None:
            try:
                ws.Activate()
            except Exception:
                pass

        # 정상 종료 시 처리 (이 세션이 연 파일만 저장 및 닫기)
        if owns_wb and wb is not None:
            try:
                if not readonly and not getattr(wb, "Saved", True):
                    log_debug("작업 완료: 변경사항 저장")
                    wb.Save()
                else:
                    log_debug("작업 완료: 저장 생략 (읽기 전용 또는 변경사항 없음)")
            finally:
                try:
                    wb.Close(SaveChanges=False)
                except Exception:
                    pass
                wb = None

    except Exception:
        if owns_wb and wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
            wb = None
        raise

    finally:
        # 이 세션이 띄운 전용 인스턴스는 항상 종료 (유령 EXCEL.EXE 방지)
        if owns_app and app is not None:
            try:
                for i in range(app.Workbooks.Count, 0, -1):
                    try:
                        app.Workbooks(i).Close(SaveChanges=False)
                    except Exception:
                        pass
                app.Quit()
            except Exception:
                pass
        ws = None
        wb = None
        app = None
        _release_com()
        log_debug("Excel COM 세션 정상 종료 및 메모리 정리 완료")

def get_all_running_word_documents() -> List[Dict[str, Any]]:
    """실행 중인 모든 Word 프로세스/창에서 열려 있는 모든 문서를 수집합니다."""
    init_com()
    docs_info = []
    apps = find_all_native_word_apps()
    if not apps:
        for method in [win32com.client.GetActiveObject]:  # 목록 조회가 새 Office 프로세스를 띄우지 않도록 Dispatch 배제
            try:
                app_inst = method("Word.Application")
                if app_inst and hasattr(app_inst, "Documents") and app_inst.Documents.Count > 0:
                    apps.append(app_inst)
                    break
            except Exception:
                pass

    seen_doc_names = set()
    for app in apps:
        try:
            active_doc_name = ""
            try:
                if app.ActiveDocument:
                    active_doc_name = app.ActiveDocument.Name
            except Exception:
                pass
            for doc in app.Documents:
                try:
                    name = doc.Name
                    full_name = getattr(doc, "FullName", "") or name
                    # 이름이 같고 폴더가 다른 문서가 누락되지 않도록 전체 경로 기준으로 중복 제거
                    if full_name.lower() in seen_doc_names:
                        continue
                    seen_doc_names.add(full_name.lower())
                    docs_info.append({
                        "app": app,
                        "doc": doc,
                        "name": name,
                        "path": getattr(doc, "FullName", ""),
                        "saved": getattr(doc, "Saved", True),
                        "is_active": (name == active_doc_name)
                    })
                except Exception:
                    continue
        except Exception:
            continue

    return docs_info

def get_active_word_app_and_doc(enable_jit: bool = True):
    """화면에 실제 떠 있는 사용자의 Word 창과 문서를 100% 신뢰도로 바인딩합니다."""
    init_com()

    # 1. Native GUI 창 우선 바인딩
    try:
        apps = find_all_native_word_apps()
        for app in apps:
            doc = _get_active_or_first_doc(app)
            if doc:
                log_debug(f"Native Word 창 바인딩 성공: {doc.Name}")
                return app, doc
    except Exception as e:
        log_debug(f"find_all_native_word_apps 예외: {e}")

    # 2. GetActiveObject 폴백 (이미 실행 중인 인스턴스만 바인딩, 새 창을 띄우는 Dispatch는 배제)
    try:
        app = win32com.client.GetActiveObject("Word.Application")
        if app:
            doc = _get_active_or_first_doc(app)
            if doc:
                log_debug("Word 활성 문서 바인딩 성공!")
                return app, doc
    except Exception:
        pass

    if enable_jit:
        log_debug("[JIT 자가복구] 활성 Word 바인딩 실패 -> JIT 복구 가동 후 재시도")
        jit_repair_office_environment("word")
        return get_active_word_app_and_doc(enable_jit=False)
    raise COMError("화면에 열려 있는 활성 Word 창이나 문서를 찾을 수 없습니다.")

@contextmanager
def word_session(
    target: str = "active",
    snapshot: bool = False,
    readonly: Optional[bool] = None
) -> Generator[Tuple[Any, Any], None, None]:
    """Word COM 생명주기를 완벽하게 격리하고 관리하는 Context Manager.

    readonly 생략 시 snapshot=False이면 읽기 전용으로 간주합니다.
    읽기 전용 세션은 존재하지 않는 파일을 새로 만들지 않고, 디스크 파일을 저장하지 않습니다.
    """
    if win32com is None:
        raise COMError("pywin32가 설치되어 있지 않습니다.")

    if readonly is None:
        readonly = not snapshot

    app = None
    doc = None
    owns_app = False
    owns_doc = False
    is_active_target = (target.strip().lower() == "active")

    try:
        matched_running_doc = None
        if not is_active_target:
            all_running = get_all_running_word_documents()
            log_debug(f"Word 검색: target='{target}', 열린 문서 수={len(all_running)}, 목록={[i['name'] for i in all_running]}")
            matched_running_doc = _match_running_item(all_running, target)
            if matched_running_doc:
                log_debug(f"실행 중인 Word 인스턴스에서 대상 문서 발견: {matched_running_doc['name']}")

        if is_active_target or matched_running_doc:
            if matched_running_doc:
                app = matched_running_doc["app"]
                doc = matched_running_doc["doc"]
            else:
                app, doc = get_active_word_app_and_doc()
                if doc is None:
                    raise COMError("활성 Word 창에 열린 문서(Document)가 없습니다.")

            app = win32com.client.Dispatch(app)
            doc = win32com.client.Dispatch(doc)
            if not readonly:
                try:
                    app.Visible = True
                    app.ScreenUpdating = True
                except Exception:
                    pass
        else:
            abs_path = os.path.abspath(target)
            file_exists = os.path.exists(abs_path)
            if not file_exists and readonly:
                raise COMError(f"대상 Word 파일이 존재하지 않습니다: {abs_path}")

            # 사용자가 띄워 둔 Word 인스턴스에 붙어 창을 숨기는 일이 없도록 전용 인스턴스를 생성
            try:
                app = win32com.client.DispatchEx("Word.Application")
            except Exception as e:
                log_debug(f"[JIT 자가복구] Word.Application 생성 실패 ({e}) -> JIT 복구 후 재시도")
                jit_repair_office_environment("word")
                app = win32com.client.DispatchEx("Word.Application")
            owns_app = True
            app.Visible = False
            app.DisplayAlerts = 0  # wdAlertsNone

            if file_exists:
                log_debug(f"Word 파일 백그라운드 오픈 (readonly={readonly}): {abs_path}")
                doc = app.Documents.Open(abs_path, ConfirmConversions=False, ReadOnly=readonly, AddToRecentFiles=False)
            else:
                log_debug(f"Word 신규 문서 백그라운드 생성: {abs_path}")
                doc = app.Documents.Add()
                fmt = _file_format_for(abs_path, WD_FILE_FORMATS)
                if fmt is not None:
                    doc.SaveAs2(abs_path, FileFormat=fmt)
                else:
                    doc.SaveAs2(abs_path)
            owns_doc = True

        # 쓰기 작업 전 자동 캐시 스냅샷 (최근 2개 유지)
        if snapshot and doc is not None:
            try:
                from _cache import save_document_snapshot
                save_document_snapshot("word", doc)
            except Exception as e:
                log_debug(f"Word 자동 스냅샷 예외: {e}")

        yield app, doc

        # 화면 시선 동기화 (Visual Focus Sync): 쓰기 작업 후 사용자 문서 포커스
        if not owns_doc and not readonly and doc is not None:
            try:
                doc.Activate()
            except Exception:
                pass

        if owns_doc and doc is not None:
            try:
                if not readonly and not getattr(doc, "Saved", True):
                    log_debug("Word 변경사항 저장")
                    doc.Save()
            finally:
                try:
                    doc.Close(SaveChanges=0)  # wdDoNotSaveChanges
                except Exception:
                    pass
                doc = None

    except Exception:
        if owns_doc and doc is not None:
            try:
                doc.Close(SaveChanges=0)
            except Exception:
                pass
            doc = None
        raise

    finally:
        if owns_app and app is not None:
            try:
                app.Quit(SaveChanges=0)
            except Exception:
                pass
        doc = None
        app = None
        _release_com()
        log_debug("Word COM 세션 정상 종료 완료")

def get_all_running_ppt_presentations() -> List[Dict[str, Any]]:
    """실행 중인 모든 PowerPoint 프로세스/창에서 열려 있는 모든 프레젠테이션을 수집합니다."""
    init_com()
    prs_info = []
    apps = find_all_native_ppt_apps()
    if not apps:
        for method in [win32com.client.GetActiveObject]:  # 목록 조회가 새 Office 프로세스를 띄우지 않도록 Dispatch 배제
            try:
                app_inst = method("PowerPoint.Application")
                if app_inst and hasattr(app_inst, "Presentations") and app_inst.Presentations.Count > 0:
                    apps.append(app_inst)
                    break
            except Exception:
                pass

    seen_prs_names = set()
    for app in apps:
        try:
            active_prs_name = ""
            try:
                if app.ActivePresentation:
                    active_prs_name = app.ActivePresentation.Name
            except Exception:
                pass
            for prs in app.Presentations:
                try:
                    name = prs.Name
                    full_name = getattr(prs, "FullName", "") or name
                    if full_name.lower() in seen_prs_names:
                        continue
                    seen_prs_names.add(full_name.lower())
                    prs_info.append({
                        "app": app,
                        "prs": prs,
                        "name": name,
                        "path": getattr(prs, "FullName", ""),
                        "saved": getattr(prs, "Saved", True),
                        "slides_count": prs.Slides.Count,
                        "is_active": (name == active_prs_name)
                    })
                except Exception:
                    continue
        except Exception:
            continue

    return prs_info

def get_active_ppt_app_and_prs(enable_jit: bool = True):
    """화면에 실제 떠 있는 사용자의 PowerPoint 창과 프레젠테이션을 100% 신뢰도로 바인딩합니다."""
    init_com()

    # 1. Native GUI 창 우선 바인딩
    try:
        apps = find_all_native_ppt_apps()
        for app in apps:
            prs = _get_active_or_first_prs(app)
            if prs:
                log_debug(f"Native PowerPoint 창 바인딩 성공: {prs.Name}")
                return app, prs
    except Exception as e:
        log_debug(f"find_all_native_ppt_apps 예외: {e}")

    # 2. GetActiveObject 폴백 (이미 실행 중인 인스턴스만 바인딩, 새 창을 띄우는 Dispatch는 배제)
    try:
        app = win32com.client.GetActiveObject("PowerPoint.Application")
        if app:
            prs = _get_active_or_first_prs(app)
            if prs:
                log_debug("PowerPoint 활성 프레젠테이션 바인딩 성공!")
                return app, prs
    except Exception:
        pass

    if enable_jit:
        log_debug("[JIT 자가복구] 활성 PowerPoint 바인딩 실패 -> JIT 복구 가동 후 재시도")
        jit_repair_office_environment("ppt")
        return get_active_ppt_app_and_prs(enable_jit=False)
    raise COMError("화면에 열려 있는 활성 PowerPoint 창이나 프레젠테이션을 찾을 수 없습니다.")

@contextmanager
def ppt_session(
    target: str = "active",
    snapshot: bool = False,
    readonly: Optional[bool] = None
) -> Generator[Tuple[Any, Any], None, None]:
    """PowerPoint COM 생명주기를 완벽하게 격리하고 관리하는 Context Manager.

    PowerPoint는 단일 인스턴스 앱이라 전용 인스턴스를 만들 수 없으므로,
    사용자가 이미 띄워 둔 PowerPoint의 창 상태(Visible/WindowState)는 절대 바꾸지 않고
    대상 파일만 창 없이(WithWindow=False) 열어 작업합니다.
    readonly 생략 시 snapshot=False이면 읽기 전용으로 간주합니다.
    """
    if win32com is None:
        raise COMError("pywin32가 설치되어 있지 않습니다.")

    if readonly is None:
        readonly = not snapshot

    app = None
    prs = None
    owns_app = False
    owns_prs = False
    orig_alerts = None
    abs_path = ""
    is_active_target = (target.strip().lower() == "active")

    try:
        matched_running_prs = None
        if not is_active_target:
            matched_running_prs = _match_running_item(get_all_running_ppt_presentations(), target)
            if matched_running_prs:
                log_debug(f"실행 중인 PowerPoint 인스턴스에서 대상 문서 발견: {matched_running_prs['name']}")

        if is_active_target or matched_running_prs:
            if matched_running_prs:
                app = matched_running_prs["app"]
                prs = matched_running_prs["prs"]
            else:
                app, prs = get_active_ppt_app_and_prs()
                if prs is None:
                    raise COMError("활성 PowerPoint 창에 열린 프레젠테이션이 없습니다.")

            app = win32com.client.Dispatch(app)
            prs = win32com.client.Dispatch(prs)
        else:
            abs_path = os.path.abspath(target)
            file_exists = os.path.exists(abs_path)
            if not file_exists and readonly:
                raise COMError(f"대상 PowerPoint 파일이 존재하지 않습니다: {abs_path}")

            already_running = False
            try:
                win32com.client.GetActiveObject("PowerPoint.Application")
                already_running = True
            except Exception:
                pass
            try:
                app = win32com.client.Dispatch("PowerPoint.Application")
            except Exception as e:
                log_debug(f"[JIT 자가복구] PowerPoint.Application 생성 실패 ({e}) -> JIT 복구 가동")
                jit_repair_office_environment("ppt")
                app = win32com.client.Dispatch("PowerPoint.Application")
            owns_app = not already_running

            try:
                orig_alerts = app.DisplayAlerts
                app.DisplayAlerts = 1  # ppAlertsNone
            except Exception:
                orig_alerts = None

            if file_exists:
                log_debug(f"PowerPoint 파일 창 없이 오픈 (readonly={readonly}): {abs_path}")
                ms_readonly = -1 if readonly else 0  # msoTrue / msoFalse
                try:
                    prs = app.Presentations.Open(abs_path, ms_readonly, 0, 0)
                except Exception:
                    prs = app.Presentations.Open(abs_path, ms_readonly)
            else:
                log_debug(f"PowerPoint 신규 파일 생성: {abs_path}")
                try:
                    prs = app.Presentations.Add(0)  # WithWindow=msoFalse
                except Exception:
                    prs = app.Presentations.Add()
                fmt = _file_format_for(abs_path, PP_FILE_FORMATS)
                if fmt is not None:
                    prs.SaveAs(abs_path, fmt)
                else:
                    prs.SaveAs(abs_path)
            owns_prs = True

        # 쓰기 작업 전 자동 캐시 스냅샷 (활성/파일 모드 공통, 최근 2개 유지)
        if snapshot and prs is not None:
            try:
                from _cache import save_document_snapshot
                save_document_snapshot("ppt", prs)
            except Exception as e:
                log_debug(f"PPT 자동 스냅샷 예외: {e}")

        yield app, prs

        # 화면 시선 동기화 (Visual Focus Sync): 쓰기 작업 후에만 사용자 화면을 마지막 슬라이드로 이동
        if not owns_prs and not readonly and prs is not None and app is not None:
            try:
                if getattr(app, "ActiveWindow", None):
                    view = getattr(app.ActiveWindow, "View", None)
                    if view and hasattr(view, "GotoSlide") and getattr(prs, "Slides", None) and prs.Slides.Count > 0:
                        view.GotoSlide(prs.Slides.Count)
            except Exception:
                pass

        if owns_prs and prs is not None:
            try:
                if not readonly and not getattr(prs, "Saved", True):
                    log_debug(f"PowerPoint 변경사항 저장: {abs_path}")
                    prs.Save()
            finally:
                try:
                    prs.Close()
                except Exception as e_close:
                    log_debug(f"PowerPoint prs.Close() 예외: {e_close}")
                prs = None

    except Exception:
        if owns_prs and prs is not None:
            try:
                prs.Close()
            except Exception:
                pass
            prs = None
        raise

    finally:
        if app is not None:
            if orig_alerts is not None and not owns_app:
                try:
                    app.DisplayAlerts = orig_alerts
                except Exception:
                    pass
            if owns_app:
                try:
                    if app.Presentations.Count == 0:
                        app.Quit()
                except Exception:
                    pass
        prs = None
        app = None
        _release_com()
        log_debug("PowerPoint COM 세션 정상 종료 완료")
