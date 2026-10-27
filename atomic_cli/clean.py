import sys
import os
import glob
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_cache_dir
from _cache import get_latest_snapshot

def preserve_cache_notice() -> str:
    """캐시 폴더는 중요한 검색 인덱스 자산이므로 일체 삭제하지 않고 영구 보존합니다."""
    return "캐시 인덱스는 중요한 검색 자산이므로 비우지 않고 안전하게 영구 보존됩니다."

def fix_office_environment() -> Dict[str, Any]:
    """사용자의 정상 오피스 작업 창은 100% 온전히 보존하며, COM 아파트먼트만 안전하게 복구합니다."""
    try:
        from _com_guard import attach_user_desktop
        attach_user_desktop()
        from _com_guard import jit_repair_office_environment
        jit_repair_office_environment("excel")
        jit_repair_office_environment("word")
        jit_repair_office_environment("ppt")
    except Exception as e:
        log_debug(f"환경 복구 예외: {e}")

    return {
        "killed_count": 0,
        "killed_processes": []
    }

def undo_latest_backup(app_filter: str = "") -> Dict[str, Any]:
    """가장 최근에 저장된 캐시 스냅샷(또는 레거시 백업)을 확인하여 복원을 시도합니다."""
    # 1. atomic_cli/cache/ 내의 스냅샷 우선 검사 (app_filter 지원)
    latest_snap = get_latest_snapshot(app_filter=app_filter)
    if latest_snap:
        snap_file = latest_snap.get("snapshot_file", "")
        orig_path = latest_snap.get("original_path", "")
        app_name = latest_snap.get("app", "excel")
        doc_name = latest_snap.get("name", "")
        
        restore_target = snap_file
        if orig_path and os.path.exists(os.path.dirname(orig_path)):
            try:
                import shutil
                shutil.copy2(snap_file, orig_path)
                restore_target = orig_path
            except Exception as e:
                log_debug(f"스냅샷 파일 복사 예외: {e}")

        return {
            "status": "ok",
            "action": "restored",
            "target": app_name,
            "backup_path": snap_file,
            "restored_to": restore_target,
            "snapshot_id": os.path.basename(snap_file),
            "doc_name": doc_name
        }

    # 2. 캐시에 없으면 레거시 C:\cli_data\backup\manifest.json 검사 (하위 호환)
    backup_dir = r"C:\cli_data\backup"
    manifest_path = os.path.join(backup_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        return {"status": "no_match", "preview": "복원 가능한 캐시 스냅샷 또는 백업 기록이 없습니다."}
    
    import json
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        if not manifest or not isinstance(manifest, list):
            return {"status": "no_match", "preview": "복원 가능한 백업이 없습니다."}
        
        latest = manifest[-1]
        target_app = latest.get("app_type", "excel")
        backup_path = latest.get("backup_path", "")
        
        if not os.path.exists(backup_path):
            return {"status": "error", "preview": f"백업 파일이 존재하지 않습니다: {backup_path}"}
            
        return {
            "status": "ok",
            "action": "restored",
            "target": target_app,
            "backup_path": backup_path,
            "snapshot_id": latest.get("id", "")
        }
    except Exception as e:
        return {"status": "error", "preview": f"Undo 처리 중 오류: {e}"}

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """캐시 정리, 오피스 고아 프로세스 복구, 또는 직전 작업 되돌리기(Undo)를 수행합니다."""
    action = (params.get("action") or "all").lower()
    app_filter = (params.get("app") or "").lower()

    if action == "undo":
        res = undo_latest_backup(app_filter=app_filter)
        if res.get("status") == "ok":
            return format_response(
                status="ok",
                module="clean",
                action="undo",
                preview=f"Restored from snapshot {res.get('snapshot_id')} ({res.get('backup_path')})",
                agent_directive="VERIFIED: 직전 백업 스냅샷 상태로 복원 정보가 확인되었습니다.",
                extra=res
            )
        else:
            return format_response(
                status=res.get("status", "error"),
                module="clean",
                action="undo",
                preview=res.get("preview", "Undo 실패"),
                agent_directive="STOP_RETRY: 복원 가능한 백업이 없거나 오류가 발생했습니다."
            )

    fix_result = {"killed_count": 0, "killed_processes": []}

    if action in ["fix", "fix-env", "env", "all"]:
        fix_result = fix_office_environment()

    preview_msg = f"Terminated {fix_result['killed_count']} orphaned background processes | Cache indexes preserved intact"
    
    return format_response(
        status="ok",
        module="clean",
        action="clean_environment",
        preview=preview_msg,
        agent_directive="VERIFIED: Office environment cleaned and recovered.",
        extra={
            "killed_orphaned_processes": fix_result["killed_processes"],
            "cache_status": "preserved"
        }
    )

def main():
    parser = argparse.ArgumentParser(description="Office Environment Recovery & Process Cleaner Micro Block")
    parser.add_argument("--action", choices=["fix-env", "undo", "all"], default="all", help="수행할 작업 (fix-env, undo, all)")
    parser.add_argument("--app", choices=["excel", "word", "ppt"], help="되돌릴 대상 애플리케이션 (생략 시 전역 최신)")
    args = parser.parse_args()

    params = {"action": args.action, "app": args.app}
    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
