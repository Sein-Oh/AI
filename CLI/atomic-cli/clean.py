import sys
import os
import glob
import shutil
import argparse
from datetime import datetime
from typing import Dict, Any, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_cache_dir
from _cache import get_latest_snapshot, delete_snapshot_files

def preserve_cache_notice() -> str:
    """캐시 폴더는 중요한 검색 인덱스 자산이므로 일체 삭제하지 않고 영구 보존합니다."""
    return "캐시 인덱스는 중요한 검색 자산이므로 비우지 않고 안전하게 영구 보존됩니다."

def fix_office_environment() -> Dict[str, Any]:
    """사용자의 정상 오피스 작업 창은 100% 온전히 보존하며, 실행 중인 Office 인스턴스가 COM으로 응답하는지 점검합니다.
    프로세스는 종료하지 않습니다.
    """
    responsive = {}
    try:
        from _com_guard import attach_user_desktop, find_all_native_excel_apps, find_all_native_word_apps, find_all_native_ppt_apps
        attach_user_desktop()
        for name, finder in (("excel", find_all_native_excel_apps), ("word", find_all_native_word_apps), ("ppt", find_all_native_ppt_apps)):
            count = 0
            for app in finder():
                try:
                    _ = app.Name
                    count += 1
                except Exception:
                    pass
            responsive[name] = count
    except Exception as e:
        log_debug(f"환경 점검 예외: {e}")

    return {
        "killed_count": 0,
        "killed_processes": [],
        "responsive_instances": responsive
    }

def _backup_path(app_name: str, ext: str) -> str:
    cache_dir = get_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    return os.path.normpath(os.path.join(cache_dir, f"undo_backup_{app_name}_{stamp}{ext}"))

def _find_open_document(app_name: str, orig_path: str) -> Optional[Dict[str, Any]]:
    """원본 경로의 문서가 현재 Office에 열려 있으면 해당 항목을 반환합니다."""
    try:
        from _com_guard import (get_all_running_excel_workbooks, get_all_running_word_documents,
                                get_all_running_ppt_presentations)
        lister = {"excel": get_all_running_excel_workbooks, "word": get_all_running_word_documents,
                  "ppt": get_all_running_ppt_presentations}[app_name]
        target = os.path.normcase(os.path.abspath(orig_path))
        for item in lister():
            path = item.get("path") or ""
            if path and os.path.normcase(os.path.abspath(path)) == target:
                return item
    except Exception as e:
        log_debug(f"열린 문서 탐색 예외: {e}")
    return None

def _word_save_flat_xml_as(app, xml_path: str, dest_path: str):
    """Flat OPC(.xml) 스냅샷을 Word로 열어 원본 확장자 형식으로 저장하고, 저장된 문서 객체를 반환합니다."""
    from _com_guard import WD_FILE_FORMATS, _file_format_for
    doc = app.Documents.Open(os.path.normpath(xml_path), ConfirmConversions=False, AddToRecentFiles=False)
    fmt = _file_format_for(dest_path, WD_FILE_FORMATS)
    if fmt is not None:
        doc.SaveAs2(os.path.normpath(dest_path), FileFormat=fmt)
    else:
        doc.SaveAs2(os.path.normpath(dest_path))
    return doc

def _restore_open_document(app_name: str, item: Dict[str, Any], snap: Dict[str, Any], orig_path: str) -> str:
    """열려 있는 문서를 현재 상태로 백업한 뒤 닫고, 스냅샷으로 교체한 다음 같은 앱에서 다시 엽니다."""
    import win32com.client
    app = win32com.client.Dispatch(item["app"])
    snap_file = snap["snapshot_file"]
    ext = os.path.splitext(orig_path)[1]

    if app_name == "excel":
        wb = item["wb"]
        backup = _backup_path(app_name, ext)
        wb.SaveCopyAs(backup)
        wb.Close(SaveChanges=False)
        shutil.copy2(snap_file, orig_path)
        app.Workbooks.Open(os.path.normpath(orig_path))
    elif app_name == "ppt":
        prs = item["prs"]
        backup = _backup_path(app_name, ext)
        prs.SaveCopyAs(backup)
        prs.Close()
        shutil.copy2(snap_file, orig_path)
        app.Presentations.Open(os.path.normpath(orig_path))
    else:
        doc = item["doc"]
        backup = _backup_path(app_name, ".xml")
        with open(backup, "w", encoding="utf-8") as f:
            f.write(doc.WordOpenXML)
        doc.Close(SaveChanges=0)
        if snap.get("snapshot_format") == "flat_xml":
            _word_save_flat_xml_as(app, snap_file, orig_path)
        else:
            shutil.copy2(snap_file, orig_path)
            app.Documents.Open(os.path.normpath(orig_path))
    return backup

def _restore_closed_document(app_name: str, snap: Dict[str, Any], orig_path: str) -> str:
    """닫혀 있는 원본 파일을 백업한 뒤 스냅샷으로 교체합니다."""
    backup = ""
    if os.path.exists(orig_path):
        backup = _backup_path(app_name, os.path.splitext(orig_path)[1])
        shutil.copy2(orig_path, backup)

    if app_name == "word" and snap.get("snapshot_format") == "flat_xml":
        from _com_guard import init_com
        import win32com.client
        init_com()
        app = win32com.client.DispatchEx("Word.Application")
        try:
            app.Visible = False
            app.DisplayAlerts = 0
            doc = _word_save_flat_xml_as(app, snap["snapshot_file"], orig_path)
            doc.Close(SaveChanges=0)
        finally:
            try:
                app.Quit(SaveChanges=0)
            except Exception:
                pass
    else:
        shutil.copy2(snap["snapshot_file"], orig_path)
    return backup

def _open_snapshot_as_new_document(app_name: str, snap: Dict[str, Any]) -> None:
    """저장된 적 없는 문서의 스냅샷을 사용자 Office에서 '제목 없는 새 문서'로 엽니다 (캐시 파일 자체를 열지 않음)."""
    from _com_guard import get_active_excel_app_and_wb, get_active_word_app_and_doc, get_active_ppt_app_and_prs
    import win32com.client
    snap_file = os.path.normpath(snap["snapshot_file"])
    if app_name == "excel":
        app, _ = get_active_excel_app_and_wb()
        win32com.client.Dispatch(app).Workbooks.Add(snap_file)
    elif app_name == "ppt":
        app, _ = get_active_ppt_app_and_prs()
        win32com.client.Dispatch(app).Presentations.Open(snap_file, 0, -1, -1)  # Untitled=msoTrue, WithWindow=msoTrue
    else:
        app, _ = get_active_word_app_and_doc()
        win32com.client.Dispatch(app).Documents.Add(Template=snap_file)

def undo_latest_backup(app_filter: str = "") -> Dict[str, Any]:
    """가장 최근에 저장된 캐시 스냅샷으로 원본 문서를 복원합니다.

    - 복원 직전의 현재 상태는 cache/undo_backup_* 로 먼저 백업합니다 (복원 자체도 되돌릴 수 있도록).
    - 원본이 Office에 열려 있으면 닫고 교체한 뒤 같은 앱에서 다시 엽니다.
    - 복원에 성공한 스냅샷은 소비(삭제)되어, 다음 undo는 그 이전 스냅샷으로 진행됩니다.
    """
    snap = get_latest_snapshot(app_filter=app_filter)
    if not snap:
        return {"status": "no_match", "preview": "복원 가능한 캐시 스냅샷이 없습니다."}

    app_name = snap.get("app", "excel")
    orig_path = snap.get("original_path", "")
    doc_name = snap.get("name", "")
    snap_file = snap.get("snapshot_file", "")
    restored_as = ""
    backup = ""

    try:
        if not orig_path:
            _open_snapshot_as_new_document(app_name, snap)
            restored_as = "new_untitled_document"
        else:
            if not os.path.isdir(os.path.dirname(orig_path)):
                return {"status": "error", "preview": f"원본 폴더가 존재하지 않습니다: {os.path.dirname(orig_path)}"}
            open_item = _find_open_document(app_name, orig_path)
            if open_item:
                backup = _restore_open_document(app_name, open_item, snap, orig_path)
                restored_as = "reopened_in_office"
            else:
                backup = _restore_closed_document(app_name, snap, orig_path)
                restored_as = "file_replaced"
    except Exception as e:
        log_debug(f"Undo 복원 예외: {e}")
        return {"status": "error", "preview": f"스냅샷 복원 실패 ({doc_name}): {e}"}

    try:
        delete_snapshot_files(snap["meta_file"])
    except Exception as e:
        log_debug(f"사용한 스냅샷 정리 실패: {e}")

    return {
        "status": "ok",
        "app": app_name,
        "doc_name": doc_name,
        "snapshot_id": os.path.basename(snap_file),
        "restored_to": orig_path or "(새 문서)",
        "restored_as": restored_as,
        "pre_undo_backup": backup
    }

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """오피스 COM 응답 점검 또는 직전 작업 되돌리기(Undo)를 수행합니다."""
    action = (params.get("action") or "all").lower()
    app_filter = (params.get("app") or "").lower()

    if action == "undo":
        res = undo_latest_backup(app_filter=app_filter)
        if res.get("status") == "ok":
            extra = {k: v for k, v in res.items() if k != "status"}
            return format_response(
                status="ok",
                module="clean",
                action="undo",
                preview=f"Restored '{res.get('doc_name')}' from snapshot {res.get('snapshot_id')} ({res.get('restored_as')})",
                agent_directive="VERIFIED: 직전 스냅샷 상태로 복원했습니다. 복원 전 상태는 pre_undo_backup에 보관되어 있습니다.",
                extra=extra
            )
        return format_response(
            status=res.get("status", "error"),
            module="clean",
            action="undo",
            preview=res.get("preview", "Undo 실패"),
            agent_directive="STOP_RETRY: 복원 가능한 스냅샷이 없거나 복원 중 오류가 발생했습니다. 사용자에게 보고하세요."
        )

    fix_result = fix_office_environment()
    resp = fix_result.get("responsive_instances", {})
    preview_msg = ("COM 응답 점검 완료 (프로세스 종료 없음): "
                   + ", ".join(f"{k}={v}" for k, v in resp.items()) + " | 캐시 인덱스 보존")

    return format_response(
        status="ok",
        module="clean",
        action="fix_env",
        preview=preview_msg,
        agent_directive="INFO: 실행 중인 Office 인스턴스의 COM 응답 여부만 점검했습니다. 종료된 프로세스는 없습니다.",
        extra={
            "responsive_instances": resp,
            "killed_orphaned_processes": [],
            "cache_status": "preserved"
        }
    )

def main():
    parser = argparse.ArgumentParser(description="Office Environment Recovery & Process Cleaner Micro Block")
    parser.add_argument("--action", choices=["fix-env", "undo", "all"], default="all", help="수행할 작업 (fix-env, undo, all)")
    parser.add_argument("--app", choices=["excel", "word", "ppt"], help="되돌릴 대상 애플리케이션 (생략 시 전역 최신)")
    args = parser.parse_args()

    params = {"action": args.action, "app": args.app}
    try:
        res = execute(params)
    except Exception as e:
        res = format_response("error", "clean", args.action, preview=f"clean 실행 오류: {e}",
                              agent_directive="STOP_RETRY: 사용자에게 오류를 보고하세요.")
    emit_response(res)
    sys.exit(0 if res.get("status") in ("ok", "no_match") else 1)

if __name__ == "__main__":
    main()
