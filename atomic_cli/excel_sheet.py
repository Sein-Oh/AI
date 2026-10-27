import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import excel_session

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체로 시트 관리 작업을 수행합니다."""
    action = params.get("action", "select").lower()
    name = params.get("name") or params.get("sheet")
    new_name = params.get("new_name") or params.get("new_sheet")
    
    try:
        sheet_names = [s.Name for s in wb.Worksheets]
        
        if action == "list":
            return format_response(
                status="ok",
                module="excel_sheet",
                action="list",
                preview=f"Sheets: {', '.join(sheet_names)}",
                agent_directive="VERIFIED: Sheet list retrieved.",
                extra={"sheets": sheet_names}
            )
            
        elif action == "ensure":
            # 이미 있으면 활성화, 없으면 새로 생성
            if not name:
                raise ValueError("'name' 파라미터가 필요합니다.")
            if name.lower() in ["active", "current", "현재"]:
                # 모델이 target처럼 'active'를 전달했을 때 빈 시트를 새로 만들지 않고 활성 시트를 유지
                active_ws = wb.ActiveSheet
                return format_response(
                    status="ok",
                    module="excel_sheet",
                    action="ensure",
                    preview=f"Active sheet '{active_ws.Name}' kept as active",
                    agent_directive="VERIFIED: Active sheet ready.",
                    extra={"sheet": active_ws.Name}
                )
            if name in sheet_names:
                target_sheet = wb.Worksheets(name)
                target_sheet.Activate()
                return format_response(
                    status="ok",
                    module="excel_sheet",
                    action="ensure",
                    preview=f"Sheet '{name}' already exists and activated",
                    agent_directive="VERIFIED: Sheet ready."
                )
            else:
                new_sheet = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
                new_sheet.Name = name
                new_sheet.Activate()
                return format_response(
                    status="ok",
                    module="excel_sheet",
                    action="ensure",
                    preview=f"Sheet '{name}' created and activated",
                    agent_directive="VERIFIED: Sheet created."
                )

        elif action == "add":
            new_sheet = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
            if name:
                new_sheet.Name = name
            new_sheet.Activate()
            return format_response(
                status="ok",
                module="excel_sheet",
                action="add",
                preview=f"Sheet '{new_sheet.Name}' added",
                agent_directive="VERIFIED: Sheet added."
            )

        elif action == "rename":
            if not name or not new_name:
                raise ValueError("'name'과 'new_name' 파라미터가 필요합니다.")
            if name not in sheet_names:
                return format_response(
                    status="no_match",
                    module="excel_sheet",
                    action="rename",
                    preview=f"Sheet '{name}' not found",
                    agent_directive="STOP_RETRY: Sheet does not exist."
                )
            wb.Worksheets(name).Name = new_name
            return format_response(
                status="ok",
                module="excel_sheet",
                action="rename",
                preview=f"Sheet '{name}' renamed to '{new_name}'",
                agent_directive="VERIFIED: Sheet renamed."
            )

        elif action == "copy":
            if not name or not new_name:
                raise ValueError("'name'과 'new_name' 파라미터가 필요합니다.")
            src_sheet = wb.Worksheets(name)
            src_sheet.Copy(After=wb.Worksheets(wb.Worksheets.Count))
            copied_sheet = wb.Worksheets(wb.Worksheets.Count)
            copied_sheet.Name = new_name
            return format_response(
                status="ok",
                module="excel_sheet",
                action="copy",
                preview=f"Sheet '{name}' copied to '{new_name}'",
                agent_directive="VERIFIED: Sheet copied."
            )

        elif action == "delete":
            if not name:
                raise ValueError("'name' 파라미터가 필요합니다.")
            if name not in sheet_names:
                return format_response(
                    status="no_match",
                    module="excel_sheet",
                    action="delete",
                    preview=f"Sheet '{name}' not found",
                    agent_directive="STOP_RETRY: Sheet does not exist."
                )
            if wb.Worksheets.Count <= 1:
                raise ValueError("통합 문서에 시트가 1개만 있어 삭제할 수 없습니다.")
            wb.Application.DisplayAlerts = False
            wb.Worksheets(name).Delete()
            wb.Application.DisplayAlerts = True
            return format_response(
                status="ok",
                module="excel_sheet",
                action="delete",
                preview=f"Sheet '{name}' deleted",
                agent_directive="VERIFIED: Sheet deleted."
            )

        elif action == "select":
            if not name:
                raise ValueError("'name' 파라미터가 필요합니다.")
            if name not in sheet_names:
                return format_response(
                    status="no_match",
                    module="excel_sheet",
                    action="select",
                    preview=f"Sheet '{name}' not found",
                    agent_directive="STOP_RETRY: Sheet does not exist."
                )
            wb.Worksheets(name).Activate()
            return format_response(
                status="ok",
                module="excel_sheet",
                action="select",
                preview=f"Sheet '{name}' activated",
                agent_directive="VERIFIED: Sheet activated."
            )

        else:
            raise ValueError(f"알 수 없는 시트 액션입니다: {action}")

    except Exception as e:
        return format_response(
            status="error",
            module="excel_sheet",
            action=action,
            preview=str(e),
            agent_directive=f"STOP_RETRY: Sheet action '{action}' failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Sheet Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--action", default="list", choices=["list", "ensure", "add", "rename", "copy", "delete", "select"])
    parser.add_argument("--name", "--sheet", dest="name", type=str, help="대상 시트 이름")
    parser.add_argument("--new-name", "--new-sheet", dest="new_name", type=str, help="새 시트 이름")
    args = parser.parse_args()

    params = {"action": args.action, "name": args.name, "new_name": args.new_name}
    
    with excel_session(target=args.target, snapshot=True) as (app, wb, ws):
        res = execute(wb, ws, params)
        emit_response(res)

if __name__ == "__main__":
    main()
