import sys
import os
import argparse
from typing import Dict, Any, List

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import (
    get_all_running_excel_workbooks,
    get_all_running_word_documents,
    get_all_running_ppt_presentations
)

def list_all_active_office_windows() -> List[Dict[str, Any]]:
    """Excel, Word, PowerPoint에서 열려 있는 모든 창과 문서를 통합 수집합니다."""
    windows = []

    # 1. Excel
    for w in get_all_running_excel_workbooks():
        windows.append({
            "app": "Excel",
            "name": w["name"],
            "path": w["path"],
            "active": w.get("is_active", False),
            "detail": f"Sheets: {len(w.get('sheets', []))}"
        })

    # 2. Word
    for d in get_all_running_word_documents():
        windows.append({
            "app": "Word",
            "name": d["name"],
            "path": d["path"],
            "active": d.get("is_active", False),
            "detail": "Document"
        })

    # 3. PPT
    for p in get_all_running_ppt_presentations():
        windows.append({
            "app": "PowerPoint",
            "name": p["name"],
            "path": p["path"],
            "active": p.get("is_active", False),
            "detail": f"Slides: {p.get('slides_count', 0)}"
        })

    return windows

def focus_office_app(app_name: str) -> bool:
    """지정한 Office 앱을 화면 최상단(포커스)으로 전환합니다."""
    app_lower = app_name.lower()
    try:
        import win32gui
        target_class = "XLMAIN" if "excel" in app_lower else ("OpusApp" if "word" in app_lower else "PPTFrameClass")
        hwnd = win32gui.FindWindow(target_class, None)
        if hwnd:
            win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
            win32gui.SetForegroundWindow(hwnd)
            return True
    except Exception as e:
        log_debug(f"윈도우 포커스 전환 실패: {e}")
    return False

def open_office_document(file_path: str) -> Dict[str, Any]:
    """지정한 Office 문서를 화면 전면에 보이도록(Visible=True) 열고 활성화합니다."""
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {abs_path}")

    ext = os.path.splitext(abs_path)[1].lower()
    import win32com.client
    app_type = ""

    if ext in [".xlsx", ".xls", ".csv"]:
        app = win32com.client.Dispatch("Excel.Application")
        app.Visible = True
        try:
            app.UserControl = True
            app.ScreenUpdating = True
        except Exception:
            pass
        app.Workbooks.Open(abs_path)
        focus_office_app("excel")
        app_type = "Excel"
    elif ext in [".docx", ".doc"]:
        app = win32com.client.Dispatch("Word.Application")
        app.Visible = True
        try:
            app.ScreenUpdating = True
        except Exception:
            pass
        app.Documents.Open(abs_path)
        focus_office_app("word")
        app_type = "Word"
    elif ext in [".pptx", ".ppt"]:
        app = win32com.client.Dispatch("PowerPoint.Application")
        app.Visible = True
        app.Presentations.Open(abs_path)
        focus_office_app("ppt")
        app_type = "PowerPoint"
    else:
        raise ValueError(f"지원하지 않는 Office 파일 형식입니다: {ext}")

    return {
        "opened": True,
        "app": app_type,
        "file": abs_path,
        "name": os.path.basename(abs_path)
    }

def create_new_office_document(app_name: str) -> Dict[str, Any]:
    """지정한 Office 애플리케이션의 새 문서를 화면 전면에 보이도록(Visible=True) 생성하고 활성화합니다."""
    app_lower = app_name.lower().strip()
    import win32com.client
    app_type = ""
    doc_name = ""

    if "excel" in app_lower or "xlsx" in app_lower:
        app = win32com.client.Dispatch("Excel.Application")
        app.Visible = True
        try:
            app.UserControl = True
            app.ScreenUpdating = True
        except Exception:
            pass
        wb = app.Workbooks.Add()
        focus_office_app("excel")
        app_type = "Excel"
        doc_name = wb.Name
    elif "word" in app_lower or "docx" in app_lower:
        app = win32com.client.Dispatch("Word.Application")
        app.Visible = True
        try:
            app.ScreenUpdating = True
        except Exception:
            pass
        doc = app.Documents.Add()
        focus_office_app("word")
        app_type = "Word"
        doc_name = doc.Name
    elif "ppt" in app_lower or "powerpoint" in app_lower or "pptx" in app_lower:
        app = win32com.client.Dispatch("PowerPoint.Application")
        app.Visible = True
        prs = app.Presentations.Add()
        try:
            prs.Slides.Add(1, 12)  # ppLayoutBlank
        except Exception:
            pass
        focus_office_app("ppt")
        app_type = "PowerPoint"
        doc_name = prs.Name
    else:
        raise ValueError(f"지원하지 않는 Office 프로그램입니다: {app_name}")

    return {
        "created": True,
        "app": app_type,
        "name": doc_name
    }

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """열린 오피스 창 목록 조회, 포커스 전환, 파일 화면 열기 또는 신규 문서 생성을 수행합니다."""
    action = (params.get("action") or "list").lower()
    focus_target = params.get("focus") or params.get("to")
    open_file = params.get("open")
    new_app = params.get("new") or (params.get("app") if action == "new" else None)

    if action == "new" or new_app:
        target_app = new_app or params.get("app") or "excel"
        try:
            res = create_new_office_document(target_app)
            return format_response(
                status="ok",
                module="office_window",
                action="new",
                preview=f"Created new {res['app']} document on screen: {res['name']}",
                agent_directive="VERIFIED: New document created and visible on screen.",
                extra=res
            )
        except Exception as e:
            return format_response(
                status="error",
                module="office_window",
                action="new",
                preview=str(e),
                agent_directive=f"STOP_RETRY: Failed to create new document: {e}"
            )

    if open_file:
        try:
            res = open_office_document(open_file)
            return format_response(
                status="ok",
                module="office_window",
                action="open",
                preview=f"Opened {res['app']} window: {res['name']}",
                agent_directive="VERIFIED: Document opened and visible on screen.",
                extra=res
            )
        except Exception as e:
            return format_response(
                status="error",
                module="office_window",
                action="open",
                preview=str(e),
                agent_directive=f"STOP_RETRY: Failed to open document: {e}"
            )

    if focus_target:
        success = focus_office_app(focus_target)
        status_str = "Focused" if success else "Focus failed"
        return format_response(
            status="ok" if success else "no_match",
            module="office_window",
            action="focus",
            preview=f"{status_str} window: {focus_target.upper()}",
            agent_directive="VERIFIED: Window focused." if success else "STOP_RETRY: Window not found.",
            extra={"target": focus_target, "success": success}
        )

    all_windows = list_all_active_office_windows()
    preview_parts = [f"{w['app']}:{w['name']}{'(*)' if w['active'] else ''}" for w in all_windows]
    preview_msg = f"총 {len(all_windows)}개 활성 오피스 창: [{', '.join(preview_parts) or '없음'}]"

    return format_response(
        status="ok",
        module="office_window",
        action="list_windows",
        preview=preview_msg,
        agent_directive="VERIFIED: Active Office windows enumerated.",
        extra={
            "total_count": len(all_windows),
            "windows": all_windows
        }
    )

def main():
    parser = argparse.ArgumentParser(description="Unified Office Window Inspection & Focus Micro Block")
    parser.add_argument("--action", choices=["list", "focus", "open", "new"], help="수행할 작업")
    parser.add_argument("--list", "--list-active", dest="list_active", action="store_true", help="열린 모든 Office 창 목록 조회")
    parser.add_argument("--focus", action="store_true", help="대상 앱 창을 화면 최상단으로 전환")
    parser.add_argument("--to", choices=["excel", "word", "ppt"], help="포커스 대상 애플리케이션")
    parser.add_argument("--app", choices=["excel", "word", "ppt"], help="대상 애플리케이션 (new 시)")
    parser.add_argument("--new", choices=["excel", "word", "ppt"], help="새 Office 문서 생성 및 화면 표시")
    parser.add_argument("--open", type=str, help="Office 파일을 화면 전면에 열기 (Visible=True)")
    args = parser.parse_args()

    action = args.action
    if not action:
        if args.new:
            action = "new"
        elif args.open:
            action = "open"
        elif args.focus:
            action = "focus"
        else:
            action = "list"

    params = {
        "action": action,
        "to": args.to,
        "app": args.app or args.new,
        "new": args.new,
        "open": args.open
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
