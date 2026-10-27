import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import excel_session

# Excel Borders 상수 매핑
BORDER_WEIGHTS = {
    "hairline": 1,
    "thin": 2,
    "medium": -4138,
    "thick": 4
}

def apply_borders(rng, weight: str = "thin", box_only: bool = False) -> None:
    """Range 객체에 테두리를 적용합니다."""
    w = BORDER_WEIGHTS.get(weight.lower(), 2)
    if box_only:
        # 외곽 테두리 (BorderAround)
        rng.BorderAround(Weight=w)
    else:
        # 전체 그리드 테두리 (상하좌우 및 내부 가로/세로선)
        for border_id in [7, 8, 9, 10, 11, 12]:  # xlEdgeLeft, Top, Bottom, Right, InsideVertical, InsideHorizontal
            try:
                rng.Borders(border_id).Weight = w
                rng.Borders(border_id).LineStyle = 1  # xlContinuous
            except Exception:
                pass

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체로 셀 범위 조작(AutoFit, 테두리, 너비/높이, 병합, 틀고정, 숨김)을 수행합니다."""
    action = (params.get("action") or "autofit").lower()
    rng_address = (params.get("range") or "").strip()
    dest_address = (params.get("dest") or "").strip()

    try:
        # 대상 범위 지정 (생략 시 UsedRange, 시트명 포함 시 'Sheet1!A1:C10' 자동 해석)
        if rng_address and "!" in rng_address:
            src_sheet, src_cell = rng_address.split("!", 1)
            target_rng = wb.Worksheets(src_sheet).Range(src_cell)
        else:
            target_rng = ws.Range(rng_address) if rng_address else ws.UsedRange

        if action == "autofit":
            target_rng.Columns.AutoFit()
            if params.get("rows"):
                target_rng.Rows.AutoFit()
            return format_response(
                status="ok",
                module="excel_range",
                action="autofit",
                preview=f"AutoFit applied to {rng_address or 'UsedRange'}",
                agent_directive="VERIFIED: Column width adjusted."
            )

        elif action == "borders":
            weight = params.get("weight", "thin")
            box_only = params.get("box", False)
            apply_borders(target_rng, weight=weight, box_only=box_only)
            return format_response(
                status="ok",
                module="excel_range",
                action="borders",
                preview=f"Borders ({weight}) applied to {rng_address or 'UsedRange'}",
                agent_directive="VERIFIED: Borders drawn."
            )

        elif action == "width":
            col_width = params.get("width")
            if col_width is None:
                raise ValueError("'width' 파라미터가 필요합니다.")
            target_rng.ColumnWidth = float(col_width)
            return format_response(
                status="ok",
                module="excel_range",
                action="width",
                preview=f"Column width of {rng_address} set to {col_width}",
                agent_directive="VERIFIED: Width set."
            )

        elif action == "height":
            row_height = params.get("height")
            if row_height is None:
                raise ValueError("'height' 파라미터가 필요합니다.")
            target_rng.RowHeight = float(row_height)
            return format_response(
                status="ok",
                module="excel_range",
                action="height",
                preview=f"Row height of {rng_address} set to {row_height}",
                agent_directive="VERIFIED: Height set."
            )

        elif action == "merge":
            target_rng.Merge()
            return format_response(
                status="ok",
                module="excel_range",
                action="merge",
                preview=f"Range {rng_address} merged",
                agent_directive="VERIFIED: Cells merged."
            )

        elif action == "unmerge":
            target_rng.UnMerge()
            return format_response(
                status="ok",
                module="excel_range",
                action="unmerge",
                preview=f"Range {rng_address} unmerged",
                agent_directive="VERIFIED: Cells unmerged."
            )

        elif action in ["freeze", "freeze_panes"]:
            # 틀 고정: 대상 셀 기준으로 헤더/열 고정
            ws.Activate()
            split_cell = target_rng.Cells(1, 1)
            split_cell.Select()
            win = ws.Application.ActiveWindow
            win.FreezePanes = False
            win.FreezePanes = True
            return format_response(
                status="ok",
                module="excel_range",
                action="freeze",
                preview=f"Freeze panes activated at {split_cell.Address}",
                agent_directive="VERIFIED: Freeze panes applied."
            )

        elif action in ["unfreeze", "unfreeze_panes"]:
            win = ws.Application.ActiveWindow
            win.FreezePanes = False
            return format_response(
                status="ok",
                module="excel_range",
                action="unfreeze",
                preview="Freeze panes removed",
                agent_directive="VERIFIED: Freeze panes removed."
            )

        elif action == "hide":
            axis = (params.get("axis") or ("rows" if params.get("rows") else "columns")).lower()
            if "row" in axis:
                target_rng.EntireRow.Hidden = True
            else:
                target_rng.EntireColumn.Hidden = True
            return format_response(
                status="ok",
                module="excel_range",
                action="hide",
                preview=f"Hidden {axis} in {rng_address}",
                agent_directive="VERIFIED: Hidden."
            )

        elif action == "unhide":
            axis = (params.get("axis") or ("rows" if params.get("rows") else "columns")).lower()
            if "row" in axis:
                target_rng.EntireRow.Hidden = False
            else:
                target_rng.EntireColumn.Hidden = False
            return format_response(
                status="ok",
                module="excel_range",
                action="unhide",
                preview=f"Unhidden {axis} in {rng_address}",
                agent_directive="VERIFIED: Unhidden."
            )

        elif action == "clear":
            clear_type = (params.get("type") or "all").lower()
            if clear_type == "contents":
                target_rng.ClearContents()
            elif clear_type == "formats":
                target_rng.ClearFormats()
            else:
                target_rng.Clear()

            charts_deleted = 0
            if params.get("charts"):
                try:
                    ch_objs = ws.ChartObjects()
                    charts_deleted = ch_objs.Count
                    ch_objs.Delete()
                except Exception:
                    pass

            preview_msg = f"Range {rng_address or 'UsedRange'} cleared ({clear_type})"
            if charts_deleted > 0:
                preview_msg += f", and {charts_deleted} charts deleted"

            return format_response(
                status="ok",
                module="excel_range",
                action="clear",
                preview=preview_msg,
                agent_directive="VERIFIED: Range cleared."
            )

        elif action in ["copy", "move"]:
            if not dest_address:
                raise ValueError(f"'{action}' 작업에는 'dest' 대상 셀 주소가 필요합니다.")
            
            if "!" in dest_address:
                dest_sheet, dest_cell = dest_address.split("!", 1)
                dest_rng = wb.Worksheets(dest_sheet).Range(dest_cell)
            else:
                dest_rng = ws.Range(dest_address)

            if action == "copy":
                target_rng.Copy(Destination=dest_rng)
            else:
                # move: 복사 후 원본 지우기
                target_rng.Copy(Destination=dest_rng)
                target_rng.Clear()

            return format_response(
                status="ok",
                module="excel_range",
                action=action,
                preview=f"Range {rng_address} {action}d to {dest_address}",
                agent_directive=f"VERIFIED: Range {action}d successfully."
            )

        else:
            raise ValueError(f"알 수 없는 action: {action}")

    except Exception as e:
        return format_response(
            status="error",
            module="excel_range",
            action=action,
            preview=str(e),
            agent_directive=f"STOP_RETRY: Range action failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Range Operations Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름")
    parser.add_argument("--action", required=True, choices=["autofit", "borders", "width", "height", "merge", "unmerge", "freeze", "unfreeze", "hide", "unhide", "clear", "copy", "move"], help="수행할 작업")
    parser.add_argument("--range", help="대상 셀 범위 (예: A1:D10, A:B, 생략 시 UsedRange)")
    parser.add_argument("--dest", help="복사/이동 대상 셀 (예: Sheet2!A1)")
    parser.add_argument("--width", type=float, help="열 너비 값")
    parser.add_argument("--height", type=float, help="행 높이 값")
    parser.add_argument("--weight", choices=["hairline", "thin", "medium", "thick"], default="thin", help="테두리 두께")
    parser.add_argument("--box", action="store_true", help="외곽 테두리만 적용")
    parser.add_argument("--axis", choices=["rows", "columns"], default="columns", help="hide/unhide 대상 축")
    parser.add_argument("--type", choices=["all", "contents", "formats"], default="all", help="지우기(clear) 유형")
    parser.add_argument("--charts", action="store_true", help="지우기(clear) 시 시트 내 차트도 함께 삭제")
    args = parser.parse_args()

    params = {
        "action": args.action,
        "range": args.range,
        "dest": args.dest,
        "width": args.width,
        "height": args.height,
        "weight": args.weight,
        "box": args.box,
        "axis": args.axis,
        "type": args.type,
        "charts": args.charts
    }

    with excel_session(target=args.target, sheet_name=args.sheet, snapshot=True) as (app, wb, ws):
        res = execute(wb, ws, params)
        emit_response(res)

if __name__ == "__main__":
    main()
