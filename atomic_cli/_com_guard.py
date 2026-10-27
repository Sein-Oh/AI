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
    사용자의 작업 창이나 실행 중인 프로세스는 절대 종료하지 않고, COM 아파트먼트만 안전하게 재초기화합니다.
    """
    log_debug(f"[JIT 자가복구] {app_name.upper()} COM 아파트먼트 재초기화 시작")
    try:
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
            pythoncom.CoInitialize()
            log_debug("[JIT 자가복구] COM 아파트먼트 재초기화 완료")
    except Exception as e:
        log_debug(f"[JIT 자가복구] COM 재초기화 예외: {e}")

    import time
    time.sleep(0.3)
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

def _get_excel_app_from_hwnd(hwnd: int) -> Optional[Any]:
    """EXCEL7 윈도우 핸들로부터 oleacc를 통해 Excel.Application COM 객체 추출"""
    disp = _extract_dispatch_from_hwnd(hwnd)
    if disp:
        try:
            return getattr(disp, "Application", None)
        except Exception:
            pass
    return None

def _get_word_app_from_hwnd(hwnd: int) -> Optional[Any]:
    """_WwG 윈도우 핸들로부터 oleacc를 통해 Word.Application COM 객체 추출"""
    disp = _extract_dispatch_from_hwnd(hwnd)
    if disp:
        try:
            return getattr(disp, "Application", None)
        except Exception:
            pass
    return None

def _get_ppt_app_from_hwnd(hwnd: int) -> Optional[Any]:
    """paneClassDC 윈도우 핸들로부터 oleacc를 통해 PowerPoint.Application COM 객체 추출"""
    disp = _extract_dispatch_from_hwnd(hwnd)
    if disp:
        try:
            return getattr(disp, "Application", None)
        except Exception:
            pass
    return None

def find_all_native_excel_apps() -> List[Any]:
    """실행 중인 모든 Excel.Application 인스턴스 탐색 (Native oleacc 우선)"""
    init_com()
    apps = []

    try:
        if win32gui is not None:
            found = False
            def enum_child(hwnd, extra):
                nonlocal found
                if win32gui.GetClassName(hwnd) == "EXCEL7":
                    app = _get_excel_app_from_hwnd(hwnd)
                    if app:
                        apps.append(app)
                        found = True
                        return False
                return True

            def enum_top(hwnd, extra):
                nonlocal found
                if win32gui.GetClassName(hwnd) == "XLMAIN":
                    win32gui.EnumChildWindows(hwnd, enum_child, None)
                    if found:
                        return False
                return True

            win32gui.EnumWindows(enum_top, None)
    except Exception:
        pass

    if not apps:
        try:
            active_app = win32com.client.GetActiveObject("Excel.Application")
            if active_app:
                apps.append(active_app)
        except Exception:
            pass

    return apps

def find_all_native_word_apps() -> List[Any]:
    """실행 중인 모든 Word.Application 인스턴스 탐색 (Native oleacc 우선)"""
    init_com()
    apps = []

    try:
        if win32gui is not None:
            found = False
            def enum_child(hwnd, extra):
                nonlocal found
                if win32gui.GetClassName(hwnd) == "_WwG":
                    app = _get_word_app_from_hwnd(hwnd)
                    if app:
                        apps.append(app)
                        found = True
                        return False
                return True

            def enum_top(hwnd, extra):
                nonlocal found
                if win32gui.GetClassName(hwnd) == "OpusApp":
                    win32gui.EnumChildWindows(hwnd, enum_child, None)
                    if found:
                        return False
                return True

            win32gui.EnumWindows(enum_top, None)
    except Exception:
        pass

    if not apps:
        try:
            active_app = win32com.client.GetActiveObject("Word.Application")
            if active_app:
                apps.append(active_app)
        except Exception:
            pass

    return apps

def find_all_native_ppt_apps() -> List[Any]:
    """실행 중인 모든 PowerPoint.Application 인스턴스 탐색 (Native oleacc 우선)"""
    init_com()
    apps = []

    try:
        if win32gui is not None:
            found = False
            def enum_child(hwnd, extra):
                nonlocal found
                if win32gui.GetClassName(hwnd) == "paneClassDC":
                    app = _get_ppt_app_from_hwnd(hwnd)
                    if app:
                        apps.append(app)
                        found = True
                        return False
                return True

            def enum_top(hwnd, extra):
                nonlocal found
                c = win32gui.GetClassName(hwnd)
                if ("PP" in c and "Frame" in c) or c == "PPTFrameClass":
                    win32gui.EnumChildWindows(hwnd, enum_child, None)
                    if found:
                        return False
                return True

            win32gui.EnumWindows(enum_top, None)
    except Exception:
        pass

    if not apps:
        try:
            active_app = win32com.client.GetActiveObject("PowerPoint.Application")
            if active_app:
                apps.append(active_app)
        except Exception:
            pass

    return apps

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
        for method in [win32com.client.GetActiveObject, win32com.client.Dispatch]:
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
                app_found = None
                def _c(h, _):
                    nonlocal app_found
                    if win32gui.GetClassName(h) == "EXCEL7":
                        app_found = _get_excel_app_from_hwnd(h)
                    return app_found is None
                win32gui.EnumChildWindows(fg_hwnd, _c, None)
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

@contextmanager
def excel_session(
    target: str = "active",
    sheet_name: Optional[str] = None,
    snapshot: bool = False
) -> Generator[Tuple[Any, Any, Any], None, None]:
    """Excel COM 생명주기를 완벽하게 격리하고 관리하는 Context Manager.
    
    Yields:
        (app, wb, ws): Excel Application, Workbook, Worksheet COM 객체
    """
    if win32com is None:
        raise COMError("pywin32가 설치되어 있지 않습니다. (pip install pywin32 필요)")

    app = None
    wb = None
    ws = None
    is_active_target = (target.strip().lower() == "active")
    
    try:
        # 이미 실행 중인 Excel에서 대상 문서가 열려 있는지 선제 확인
        matched_running_wb = None
        if not is_active_target:
            target_clean = target.strip().lower()
            all_running = get_all_running_excel_workbooks()
            for item in all_running:
                wb_name_lower = item["name"].lower()
                wb_path_lower = item["path"].lower() if item["path"] else ""
                target_abs_lower = os.path.abspath(target).lower()
                if (target_clean == wb_name_lower or 
                    target_clean == os.path.basename(wb_path_lower) or
                    target_abs_lower == wb_path_lower):
                    matched_running_wb = item
                    log_debug(f"실행 중인 Excel 인스턴스에서 대상 문서 발견: {item['name']}")
                    break

        if is_active_target or matched_running_wb:
            if matched_running_wb:
                app = matched_running_wb["app"]
                wb = matched_running_wb["wb"]
                is_active_target = True  # 사용자가 열어둔 창이므로 세션 종료 시 닫지 않음
            else:
                app, wb = get_active_excel_app_and_wb()
                if wb is None:
                    raise COMError("활성 Excel 창에 열린 통합 문서(Workbook)가 없습니다.")

            # COM 인터페이스 안전 디스패치 래핑
            app = win32com.client.Dispatch(app)
            wb = win32com.client.Dispatch(wb)

            # 사용자가 보고 있는 창을 화면 최상단으로 강제 갱신
            try:
                app.Visible = True
                app.ScreenUpdating = True
            except Exception:
                pass

            if sheet_name:
                try:
                    ws = wb.Worksheets(sheet_name)
                    ws.Activate()
                except Exception:
                    log_debug(f"시트 '{sheet_name}' 생성 및 활성화")
                    ws = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
                    ws.Name = sheet_name
                    ws.Activate()
            else:
                try:
                    ws = app.ActiveSheet
                except Exception:
                    ws = wb.Worksheets(1)
                    
        else:
            # 디스크 파일 대상 (독립 STA 초기화)
            if pythoncom is not None:
                try:
                    pythoncom.CoInitialize()
                except Exception:
                    pass
            abs_path = os.path.abspath(target)
            file_exists = os.path.exists(abs_path)
            
            try:
                app = win32com.client.Dispatch("Excel.Application")
            except Exception as e:
                log_debug(f"[JIT 자가복구] Excel.Application 생성 실패 ({e}) -> JIT 복구 가동")
                jit_repair_office_environment("excel")
                app = win32com.client.Dispatch("Excel.Application")

            app.Visible = False
            app.DisplayAlerts = False
            
            if file_exists:
                log_debug(f"Excel 파일 백그라운드 오픈: {abs_path}")
                try:
                    wb = app.Workbooks.Open(abs_path)
                except Exception as e:
                    log_debug(f"[JIT 자가복구] Workbooks.Open 실패 ({e}) -> JIT 복구 후 재시도")
                    jit_repair_office_environment("excel")
                    app = win32com.client.Dispatch("Excel.Application")
                    app.Visible = False
                    app.DisplayAlerts = False
                    wb = app.Workbooks.Open(abs_path)
            else:
                log_debug(f"Excel 신규 파일 백그라운드 생성: {abs_path}")
                wb = app.Workbooks.Add()
                wb.SaveAs(abs_path)
            
            if sheet_name:
                try:
                    ws = wb.Worksheets(sheet_name)
                except Exception:
                    # 시트가 없으면 새로 추가
                    ws = wb.Worksheets.Add()
                    ws.Name = sheet_name
            else:
                ws = wb.Worksheets(1)

        # 쓰기 작업 전 자동 캐시 스냅샷 (최근 2개 유지)
        if snapshot and wb is not None:
            try:
                from _cache import save_document_snapshot
                save_document_snapshot("excel", wb)
            except Exception as e:
                log_debug(f"Excel 자동 스냅샷 예외: {e}")

        # 2. 살아있는 엑셀 COM 객체 주입
        yield app, wb, ws

        # 화면 시선 동기화 (Visual Focus Sync): 활성 시트 즉시 포커스
        if is_active_target and ws is not None:
            try:
                ws.Activate()
            except Exception:
                pass
            try:
                if app is not None and getattr(app, "ActiveWindow", None):
                    app.ActiveWindow.ScrollRow = 1
                    app.ActiveWindow.ScrollColumn = 1
            except Exception:
                pass
        
        # 3. 정상 종료 시 처리 (파일 모드만 저장 및 닫기)
        if not is_active_target and wb is not None:
            try:
                # 변경 사항이 있을 때만 Save 호출 (단순 읽기 시 mtime 변경 방지)
                if not getattr(wb, "Saved", True):
                    log_debug("작업 완료: 변경사항 저장 및 닫기")
                    wb.Save()
                else:
                    log_debug("작업 완료: 변경사항 없음 (Save 생략)")
                wb.Close(SaveChanges=False)
            except Exception:
                pass
            wb = None
            
    except Exception:
        # 예외 발생 시 파일 모드라면 저장하지 않고 안전 종료
        if not is_active_target and wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
            wb = None
        raise
        
    finally:
        # 4. 프로세스 정리 및 COM 참조 해제
        if not is_active_target and app is not None:
            try:
                # 사용자가 열어둔 다른 통합 문서가 남아 있다면 Excel.Quit() 호출 금지
                if hasattr(app, "Workbooks") and app.Workbooks.Count == 0:
                    app.Quit()
            except Exception:
                pass
            app = None
            
        ws = None
        wb = None
        app = None
        import gc
        gc.collect()
        if pythoncom is not None:
            try:
                pythoncom.CoFreeUnusedLibraries()
            except Exception:
                pass
        log_debug("Excel COM 세션 정상 종료 및 메모리 정리 완료")

def get_all_running_word_documents() -> List[Dict[str, Any]]:
    """실행 중인 모든 Word 프로세스/창에서 열려 있는 모든 문서를 수집합니다."""
    init_com()
    docs_info = []
    apps = find_all_native_word_apps()
    if not apps:
        for method in [win32com.client.GetActiveObject, win32com.client.Dispatch]:
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
                    if name in seen_doc_names:
                        continue
                    seen_doc_names.add(name)
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
    snapshot: bool = False
) -> Generator[Tuple[Any, Any], None, None]:
    """Word COM 생명주기를 완벽하게 격리하고 관리하는 Context Manager."""
    if win32com is None:
        raise COMError("pywin32가 설치되어 있지 않습니다.")

    app = None
    doc = None
    is_active_target = (target.strip().lower() == "active")

    try:
        # 이미 실행 중인 Word에서 대상 문서가 열려 있는지 선제 확인
        matched_running_doc = None
        if not is_active_target:
            target_clean = target.strip().lower()
            all_running = get_all_running_word_documents()
            log_debug(f"Word 검색: target='{target_clean}', 열린 문서 수={len(all_running)}, 목록={[i['name'] for i in all_running]}")
            for item in all_running:
                doc_name_lower = item["name"].lower()
                doc_path_lower = item["path"].lower() if item["path"] else ""
                target_abs_lower = os.path.abspath(target).lower()
                if (target_clean == doc_name_lower or 
                    target_clean == os.path.basename(doc_path_lower) or
                    target_abs_lower == doc_path_lower):
                    matched_running_doc = item
                    log_debug(f"실행 중인 Word 인스턴스에서 대상 문서 발견: {item['name']}")
                    break

        if is_active_target or matched_running_doc:
            if matched_running_doc:
                app = matched_running_doc["app"]
                doc = matched_running_doc["doc"]
                is_active_target = True  # 사용자가 열어둔 창이므로 세션 종료 시 닫지 않음
            else:
                app, doc = get_active_word_app_and_doc()
                if doc is None:
                    raise COMError("활성 Word 창에 열린 문서(Document)가 없습니다.")

            app = win32com.client.Dispatch(app)
            doc = win32com.client.Dispatch(doc)
            try:
                app.Visible = True
                app.ScreenUpdating = True
            except Exception:
                pass
        else:
            if pythoncom is not None:
                try:
                    pythoncom.CoInitialize()
                except Exception:
                    pass
            abs_path = os.path.abspath(target)
            file_exists = os.path.exists(abs_path)
            try:
                app = win32com.client.Dispatch("Word.Application")
            except Exception as e:
                log_debug(f"[JIT 자가복구] Word.Application 생성 실패 ({e}) -> JIT 복구 가동")
                jit_repair_office_environment("word")
                app = win32com.client.Dispatch("Word.Application")

            app.Visible = False
            app.DisplayAlerts = 0  # wdAlertsNone

            if file_exists:
                log_debug(f"Word 파일 백그라운드 오픈: {abs_path}")
                doc = app.Documents.Open(abs_path)
            else:
                log_debug(f"Word 신규 문서 백그라운드 생성: {abs_path}")
                doc = app.Documents.Add()
                doc.SaveAs(abs_path)

        # 쓰기 작업 전 자동 캐시 스냅샷 (최근 2개 유지)
        if snapshot and doc is not None:
            try:
                from _cache import save_document_snapshot
                save_document_snapshot("word", doc)
            except Exception as e:
                log_debug(f"Word 자동 스냅샷 예외: {e}")

        yield app, doc

        # 화면 시선 동기화 (Visual Focus Sync): 활성 문서 포커스
        if is_active_target and doc is not None:
            try:
                doc.Activate()
            except Exception:
                pass

        if not is_active_target and doc is not None:
            if not getattr(doc, "Saved", True):
                log_debug("Word 변경사항 저장 및 닫기")
                doc.Save()
            doc.Close(SaveChanges=False)
            doc = None

    except Exception:
        if not is_active_target and doc is not None:
            try:
                doc.Close(SaveChanges=False)
            except Exception:
                pass
            doc = None
        raise

    finally:
        if not is_active_target:
            if app is not None:
                try:
                    # 사용자가 열어둔 다른 문서가 남아 있다면 Word.Quit() 호출 금지
                    if hasattr(app, "Documents") and app.Documents.Count == 0:
                        app.Quit()
                except Exception:
                    pass
                app = None
        doc = None
        app = None
        import gc
        gc.collect()
        if pythoncom is not None:
            try:
                pythoncom.CoFreeUnusedLibraries()
            except Exception:
                pass
        log_debug("Word COM 세션 정상 종료 완료")

def get_all_running_ppt_presentations() -> List[Dict[str, Any]]:
    """실행 중인 모든 PowerPoint 프로세스/창에서 열려 있는 모든 프레젠테이션을 수집합니다."""
    init_com()
    prs_info = []
    apps = find_all_native_ppt_apps()
    if not apps:
        for method in [win32com.client.GetActiveObject, win32com.client.Dispatch]:
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
                    if name in seen_prs_names:
                        continue
                    seen_prs_names.add(name)
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
    snapshot: bool = False
) -> Generator[Tuple[Any, Any], None, None]:
    """PowerPoint COM 생명주기를 완벽하게 격리하고 관리하는 Context Manager."""
    if win32com is None:
        raise COMError("pywin32가 설치되어 있지 않습니다.")

    app = None
    prs = None
    file_exists = False
    is_active_target = (target.strip().lower() == "active")

    try:
        # 이미 실행 중인 PowerPoint에서 대상 프레젠테이션이 열려 있는지 선제 확인
        matched_running_prs = None
        if not is_active_target:
            target_clean = target.strip().lower()
            all_running = get_all_running_ppt_presentations()
            for item in all_running:
                prs_name_lower = item["name"].lower()
                prs_path_lower = item["path"].lower() if item["path"] else ""
                target_abs_lower = os.path.abspath(target).lower()
                if (target_clean == prs_name_lower or 
                    target_clean == os.path.basename(prs_path_lower) or
                    target_abs_lower == prs_path_lower):
                    matched_running_prs = item
                    log_debug(f"실행 중인 PowerPoint 인스턴스에서 대상 문서 발견: {item['name']}")
                    break

        if is_active_target or matched_running_prs:
            if matched_running_prs:
                app = matched_running_prs["app"]
                prs = matched_running_prs["prs"]
                is_active_target = True  # 사용자가 열어둔 창이므로 세션 종료 시 닫지 않음
            else:
                app, prs = get_active_ppt_app_and_prs()
                if prs is None:
                    raise COMError("활성 PowerPoint 창에 열린 프레젠테이션이 없습니다.")

            app = win32com.client.Dispatch(app)
            prs = win32com.client.Dispatch(prs)
            try:
                app.Visible = True
            except Exception:
                pass
        else:
            if pythoncom is not None:
                try:
                    pythoncom.CoInitialize()
                except Exception:
                    pass
            abs_path = os.path.abspath(target)
            file_exists = os.path.exists(abs_path)
            try:
                app = win32com.client.Dispatch("PowerPoint.Application")
            except Exception as e:
                log_debug(f"[JIT 자가복구] PowerPoint.Application 생성 실패 ({e}) -> JIT 복구 가동")
                jit_repair_office_environment("ppt")
                app = win32com.client.Dispatch("PowerPoint.Application")
            try:
                app.DisplayAlerts = 1  # ppAlertsNone
                app.Visible = False
                app.WindowState = 2    # ppWindowMinimized (화면 깜빡임 방지)
            except Exception:
                pass
            # WithWindow=0으로 창 없이 백그라운드 오픈
            if file_exists:
                log_debug(f"PowerPoint 파일 오픈: {abs_path}")
                try:
                    prs = app.Presentations.Open(abs_path, 0, 0, 0)
                except Exception:
                    prs = app.Presentations.Open(abs_path)
            else:
                log_debug(f"PowerPoint 신규 파일 생성: {abs_path}")
                try:
                    prs = app.Presentations.Add(1)
                except Exception:
                    prs = app.Presentations.Add()

        # 쓰기 작업 전 자동 캐시 스냅샷 (최근 2개 유지)
        if snapshot and prs is not None and file_exists:
            try:
                from _cache import save_document_snapshot
                save_document_snapshot("ppt", prs)
            except Exception as e:
                log_debug(f"PPT 자동 스냅샷 예외: {e}")

        yield app, prs

        # 화면 시선 동기화 (Visual Focus Sync): 활성 슬라이드 즉시 포커스
        if is_active_target and prs is not None and app is not None:
            try:
                if getattr(app, "ActiveWindow", None):
                    view = getattr(app.ActiveWindow, "View", None)
                    if view and hasattr(view, "GotoSlide") and getattr(prs, "Slides", None) and prs.Slides.Count > 0:
                        view.GotoSlide(prs.Slides.Count)
            except Exception:
                pass

        if not is_active_target and prs is not None:
            log_debug(f"PowerPoint 세션 종료 단계 진입: {abs_path}")
            try:
                log_debug("PowerPoint prs.Save() 호출 직전")
                prs.Save()
                log_debug("PowerPoint prs.Save() 성공")
            except Exception as e_save:
                log_debug(f"PowerPoint prs.Save() 예외: {e_save}")
                try:
                    log_debug("PowerPoint prs.SaveCopyAs() 시도 직전")
                    prs.SaveCopyAs(abs_path)
                    log_debug("PowerPoint prs.SaveCopyAs() 성공")
                except Exception as e_copy:
                    log_debug(f"PowerPoint SaveCopyAs 예외: {e_copy}")
            try:
                log_debug("PowerPoint prs.Close() 호출 직전")
                prs.Close()
                log_debug("PowerPoint prs.Close() 성공")
            except Exception as e_close:
                log_debug(f"PowerPoint prs.Close() 예외: {e_close}")
            prs = None

    except Exception:
        if not is_active_target and prs is not None:
            try:
                prs.Close()
            except Exception:
                pass
            prs = None
        raise

    finally:
        if not is_active_target and app is not None:
            try:
                if hasattr(app, "Presentations") and app.Presentations.Count == 0:
                    app.Quit()
            except Exception:
                pass
            app = None
        prs = None
        app = None
        import gc
        gc.collect()
        if pythoncom is not None:
            try:
                pythoncom.CoFreeUnusedLibraries()
            except Exception:
                pass
        log_debug("PowerPoint COM 세션 정상 종료 완료")
