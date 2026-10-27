import sys
import os
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, run_session_tool
from _com_guard import excel_session

def inspect_single_worksheet(ws) -> Dict[str, Any]:
    """단일 시트의 사용 범위, 글자 수, 차트 수, 이미지 수를 초고속(인메모리) 계산합니다."""
    sheet_name = ws.Name
    used_range = ws.UsedRange
    rng_address = used_range.Address if used_range is not None else "A1"
    
    # 1. 셀 데이터 한 번에 덤프 (COM 호출 1회로 고속 처리)
    raw_values = used_range.Value if used_range is not None else None
    
    total_chars = 0
    filled_cells = 0
    row_count = used_range.Rows.Count if used_range is not None else 0
    col_count = used_range.Columns.Count if used_range is not None else 0

    preview_rows = []

    if raw_values is not None:
        # 단일 셀 예외 처리
        if row_count == 1 and col_count == 1:
            matrix = [[raw_values]]
        elif row_count == 1:
            matrix = [list(raw_values)]
        elif col_count == 1:
            matrix = [[r[0]] for r in raw_values]
        else:
            matrix = [list(r) for r in raw_values]

        for r_idx, row in enumerate(matrix):
            # 상위 3행 미리보기 수집
            if r_idx < 3:
                preview_rows.append([str(v) if v is not None else "" for v in row[:5]])
                
            for cell_val in row:
                if cell_val is not None and str(cell_val).strip() != "":
                    filled_cells += 1
                    total_chars += len(str(cell_val))

    # 2. 차트 수 및 정보
    charts_info = []
    try:
        chart_count = ws.ChartObjects().Count
        for i in range(1, chart_count + 1):
            ch_obj = ws.ChartObjects(i)
            title_text = ""
            try:
                if ch_obj.Chart.HasTitle:
                    title_text = ch_obj.Chart.ChartTitle.Text
            except Exception:
                pass
            charts_info.append({
                "name": ch_obj.Name,
                "title": title_text
            })
    except Exception:
        chart_count = 0

    # 3. 이미지 및 기타 도형 수
    image_count = 0
    shape_count = 0
    try:
        shape_count = ws.Shapes.Count
        # 순수 그림(Pictures) 수 조회
        try:
            image_count = ws.Pictures().Count
        except Exception:
            # Pictures() 접근 불가 시 Shapes에서 차트 제외한 개수로 추산
            image_count = max(0, shape_count - chart_count)
    except Exception:
        pass

    return {
        "sheet_name": sheet_name,
        "used_range": rng_address,
        "rows": row_count,
        "cols": col_count,
        "filled_cells": filled_cells,
        "character_count": total_chars,
        "chart_count": chart_count,
        "charts": charts_info,
        "image_count": image_count,
        "shape_count": shape_count,
        "preview_sample": preview_rows
    }

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 호출되는 엑셀 상태 검사 엔진."""
    target_sheet = params.get("sheet")
    
    try:
        wb_name = wb.Name
        all_sheet_names = [s.Name for s in wb.Worksheets]

        # 1. 특정 시트만 지정된 경우 (--sheet)
        if target_sheet:
            if target_sheet not in all_sheet_names:
                return format_response(
                    status="no_match",
                    module="excel_inspect",
                    action="inspect_sheet",
                    preview=f"Sheet '{target_sheet}' not found in workbook '{wb_name}'",
                    agent_directive="STOP_RETRY: Target sheet does not exist."
                )
                
            sheet_obj = wb.Worksheets(target_sheet)
            sheet_info = inspect_single_worksheet(sheet_obj)
            
            preview_msg = (
                f"[{target_sheet}] {sheet_info['rows']}행x{sheet_info['cols']}열 "
                f"({sheet_info['used_range']}), 글자: {sheet_info['character_count']}, "
                f"차트: {sheet_info['chart_count']}, 이미지: {sheet_info['image_count']}"
            )
            
            return format_response(
                status="ok",
                module="excel_inspect",
                action="inspect_sheet",
                preview=preview_msg,
                agent_directive="VERIFIED: Single sheet inspected.",
                extra={
                    "workbook": wb_name,
                    "sheet_details": sheet_info
                }
            )

        # 2. 전체 통합 문서 검사 (기본 모드)
        total_chars = 0
        total_filled_cells = 0
        total_charts = 0
        total_images = 0
        sheet_summaries = []

        for s in wb.Worksheets:
            s_info = inspect_single_worksheet(s)
            total_chars += s_info["character_count"]
            total_filled_cells += s_info["filled_cells"]
            total_charts += s_info["chart_count"]
            total_images += s_info["image_count"]
            sheet_summaries.append(s_info)

        active_sheet_name = ""
        try:
            active_sheet_name = wb.ActiveSheet.Name
        except Exception:
            pass

        # 현재 활성 셀 및 선택 범위(Selection) 정보 추출
        selection_info = {}
        try:
            excel_app = getattr(wb, "Application", None)
            if excel_app is not None:
                sel = excel_app.Selection
                act_cell = excel_app.ActiveCell
                sel_addr = str(sel.Address).replace("$", "") if sel is not None else ""
                act_addr = str(act_cell.Address).replace("$", "") if act_cell is not None else ""
                act_val = act_cell.Value if act_cell is not None else None
                act_formula = str(act_cell.Formula) if (act_cell is not None and str(act_cell.Formula).startswith("=")) else ""
                selection_info = {
                    "active_sheet": active_sheet_name,
                    "selected_range": sel_addr,
                    "active_cell": act_addr,
                    "active_cell_value": act_val if act_val is not None else "",
                    "active_cell_formula": act_formula
                }
        except Exception as e:
            log_debug(f"Excel selection info error: {e}")

        # 열려 있는 전체 통합 문서 목록 조회 (모든 Excel 프로세스 전수 조사)
        open_workbooks = []
        try:
            from _com_guard import get_all_running_excel_workbooks
            all_running = get_all_running_excel_workbooks()
            for item in all_running:
                open_workbooks.append({
                    "name": item["name"],
                    "path": item["path"],
                    "saved": item.get("saved", True),
                    "sheets": item.get("sheets", []),
                    "active": (item["name"] == wb_name)
                })
        except Exception as e:
            log_debug(f"전체 열린 문서 조회 실패: {e}")

        if not open_workbooks:
            open_workbooks = [{"name": wb_name, "path": getattr(wb, "FullName", ""), "active": True}]

        open_wb_names = [w["name"] for w in open_workbooks]
        sel_desc = f"선택: {selection_info.get('selected_range') or selection_info.get('active_cell') or '없음'}"
        summary_preview = (
            f"열린 문서: {len(open_workbooks)}개 ({', '.join(open_wb_names)}) | 활성: {wb_name} [{active_sheet_name}] ({sel_desc}) | "
            f"시트 {len(all_sheet_names)}개 ({', '.join(all_sheet_names)}) | "
            f"총 글자 수: {total_chars}자 | 차트: {total_charts}개 | 이미지: {total_images}개"
        )

        return format_response(
            status="ok",
            module="excel_inspect",
            action="inspect_workbook",
            preview=summary_preview,
            agent_directive="VERIFIED: Inspection complete. State verified.",
            extra={
                "workbook": wb_name,
                "open_workbooks": open_workbooks,
                "total_open_workbooks": len(open_workbooks),
                "active_sheet": active_sheet_name,
                "selection": selection_info,
                "sheets": all_sheet_names,
                "total_sheets": len(all_sheet_names),
                "total_character_count": total_chars,
                "total_filled_cells": total_filled_cells,
                "total_charts_count": total_charts,
                "total_images_count": total_images,
                "sheet_summaries": sheet_summaries
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="excel_inspect",
            action="inspect",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Inspection failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Inspection Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 엑셀 파일 경로")
    parser.add_argument("--sheet", type=str, help="검사할 특정 시트 이름 (생략 시 전체 문서 검사)")
    parser.add_argument("--list-workbooks", "--all", dest="list_workbooks", action="store_true", help="실행 중인 모든 Excel 프로세스의 통합 문서 목록만 고속 조회")
    args = parser.parse_args()

    if args.list_workbooks:
        from _com_guard import get_all_running_excel_workbooks
        all_running = get_all_running_excel_workbooks()
        workbooks_summary = []
        for item in all_running:
            workbooks_summary.append({
                "name": item["name"],
                "path": item["path"],
                "saved": item.get("saved", True),
                "sheets": item.get("sheets", []),
                "active": item.get("is_active", False)
            })

        names_preview = ", ".join([f"{w['name']}{' (Active)' if w['active'] else ''}" for w in workbooks_summary])
        res = format_response(
            status="ok",
            module="excel_inspect",
            action="list_workbooks",
            preview=f"총 {len(workbooks_summary)}개의 열린 엑셀 문서 감지: [{names_preview}]",
            agent_directive="VERIFIED: Running workbooks enumerated across all Excel processes.",
            extra={
                "total_count": len(workbooks_summary),
                "workbooks": workbooks_summary
            }
        )
        emit_response(res)
        return

    params = {"sheet": args.sheet}

    run_session_tool("excel_inspect", "inspect",
                     lambda: excel_session(target=args.target, sheet_name=args.sheet),
                     lambda app, wb, ws: execute(wb, ws, params))

if __name__ == "__main__":
    main()
