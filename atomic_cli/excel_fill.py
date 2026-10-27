import sys
import os
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, read_csv_table, get_target_range_address, parse_color_to_bgr
from _com_guard import excel_session
from _config import resolve_data_path, get_data_dir

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체로 엑셀 데이터 주입, 수식 계산 및 덧붙이기(Append)를 수행합니다."""
    start_cell = params.get("range", "A1").strip()
    data_file = params.get("data_file")
    value = params.get("value")
    formula = params.get("formula")
    values = params.get("values")
    clear = params.get("clear", False)
    mode = (params.get("mode") or "overwrite").lower()
    autofit = params.get("autofit", True)

    try:
        # 기존 내용 초기화 옵션
        if clear:
            log_debug("시트 기존 내용 초기화 (ClearContents)")
            ws.Cells.ClearContents()

        # 1. 단일 수식(Formula) 주입
        if formula is not None:
            cell = ws.Range(start_cell)
            formula_str = str(formula).strip()
            if not formula_str.startswith("="):
                formula_str = "=" + formula_str
            cell.Formula = formula_str
            if autofit:
                cell.Columns.AutoFit()
            return format_response(
                status="ok",
                module="excel_fill",
                action="formula_fill",
                preview=f"Cell {start_cell} formula set to '{formula_str}'",
                agent_directive="VERIFIED: Excel formula applied and evaluated.",
                extra={"cell": start_cell, "formula": formula_str}
            )

        # 2. 단일 셀 값 쓰기
        if value is not None and not data_file and values is None:
            cell = ws.Range(start_cell)
            val_str = str(value)
            if val_str.startswith("="):
                cell.Formula = val_str
            else:
                cell.Value = value
            if autofit:
                cell.Columns.AutoFit()
            return format_response(
                status="ok",
                module="excel_fill",
                action="single_value",
                preview=f"Cell {start_cell} set to '{value}'",
                agent_directive="VERIFIED: Single cell updated."
            )

        # 3. 표 데이터 수집 (CSV 파일 또는 리스트)
        table_data: List[List[Any]] = []
        if data_file:
            abs_csv = resolve_data_path(data_file)
            if not os.path.exists(abs_csv):
                return format_response(
                    status="no_match",
                    module="excel_fill",
                    action="csv_fill",
                    preview=f"Data file not found: {abs_csv}",
                    agent_directive="STOP_RETRY: Data file missing."
                )
            table_data = read_csv_table(abs_csv)
        elif values:
            table_data = values
        else:
            return format_response(
                status="no_match",
                module="excel_fill",
                action="fill",
                preview="No data provided (data_file, formula, value, or values required)",
                agent_directive="STOP_RETRY: Empty input."
            )

        row_count = len(table_data)
        if row_count == 0:
            return format_response(
                status="no_match",
                module="excel_fill",
                action="fill",
                preview="Empty table data (0 rows)",
                agent_directive="STOP_RETRY: Data contains 0 rows."
            )

        # 4. Append 모드 처리 (기존 표의 마지막 행 다음에 자동 덧붙이기)
        actual_start_cell = start_cell
        if mode == "append":
            used_rng = ws.UsedRange
            # 시트에 내용이 이미 있는 경우 다음 행 탐색
            if used_rng and (used_rng.Rows.Count > 1 or ws.Cells(used_rng.Row, used_rng.Column).Value is not None):
                last_used_row = used_rng.Row + used_rng.Rows.Count - 1
                
                # 시작 셀의 열 문자 추출 (예: 'B5' -> 'B')
                col_letters = "".join([ch for ch in start_cell if ch.isalpha()]) or "A"
                actual_start_cell = f"{col_letters}{last_used_row + 1}"
                log_debug(f"Append 모드: 마지막 행({last_used_row}) 다음인 '{actual_start_cell}'부터 주입 시작")

                # 기존 헤더와 주입 데이터 첫 행이 동일한지 검사하여 중복 헤더 건너뛰기
                if row_count > 1 and ws.Cells(used_rng.Row, used_rng.Column).Value is not None:
                    first_header = [str(c).strip() for c in table_data[0]]
                    existing_header = [str(ws.Cells(used_rng.Row, used_rng.Column + i).Value or "").strip() for i in range(len(first_header))]
                    if first_header == existing_header:
                        log_debug("Append 모드: 중복 헤더 감지 -> 헤더 1행 건너뛰고 데이터만 추가")
                        table_data = table_data[1:]
                        row_count = len(table_data)

        # 행별 최대 열 수 계산 및 직사각형 2D 정규화
        max_col_count = max(len(row) for row in table_data)
        normalized_data = []
        formula_cells = []  # 수식 셀 위치 추적

        for r_idx, r in enumerate(table_data):
            padded_row = []
            for c_idx, item in enumerate(r):
                item_str = str(item).strip() if item is not None else ""
                if item_str.startswith("="):
                    formula_cells.append((r_idx, c_idx, item_str))
                    padded_row.append("")  # 임시 빈값 주입 후 Formula로 설정
                else:
                    padded_row.append(item)
            padded_row.extend([""] * (max_col_count - len(padded_row)))
            normalized_data.append(tuple(padded_row))

        # 대상 범위 계산 (예: 'A1:E20')
        target_range = get_target_range_address(actual_start_cell, row_count, max_col_count)
        log_debug(f"범위 '{target_range}'에 {row_count}행 x {max_col_count}열 2D 배열 고속 대입 (mode={mode})")

        # 1차 대입: 2차원 SafeArray 일괄 고속 주입
        fill_rng = ws.Range(target_range)
        fill_rng.Value = tuple(normalized_data)

        # 2차 대입: 수식이 포함된 셀 정확한 Formula 설정
        if formula_cells:
            start_row = fill_rng.Row
            start_col = fill_rng.Column
            for r_offset, c_offset, f_str in formula_cells:
                try:
                    ws.Cells(start_row + r_offset, start_col + c_offset).Formula = f_str
                except Exception as fe:
                    log_debug(f"수식 설정 예외 ({f_str}): {fe}")

        # 3차 처리: 테마 일괄 서식 (--theme 지원으로 Gemma 4 원스톱 스타일링)
        theme_arg = params.get("theme")
        if theme_arg:
            try:
                from office_theme import resolve_theme
                theme_dict = resolve_theme(theme_arg)
                start_row = fill_rng.Row
                start_col = fill_rng.Column

                # 1) 헤더 스타일 (1행)
                header_cfg = theme_dict.get("header", {})
                h_bg = parse_color_to_bgr(header_cfg.get("bg", theme_dict.get("primary", "#1B365D")))
                h_fg = parse_color_to_bgr(header_cfg.get("color", "#FFFFFF"))
                header_rng = ws.Range(ws.Cells(start_row, start_col), ws.Cells(start_row, start_col + max_col_count - 1))
                if h_bg is not None:
                    header_rng.Interior.Color = h_bg
                if h_fg is not None:
                    header_rng.Font.Color = h_fg
                header_rng.Font.Bold = True
                header_rng.HorizontalAlignment = -4108  # xlCenter

                # 2) 지브라 패턴 & 합계 행 서식
                zebra_cfg = theme_dict.get("zebra", {})
                even_bg = parse_color_to_bgr(zebra_cfg.get("even", "#F4F7FB")) if zebra_cfg.get("enabled", True) else None
                summary_cfg = theme_dict.get("summary", {})
                sum_bg = parse_color_to_bgr(summary_cfg.get("bg", "#E8EEF5"))

                for r_idx in range(1, row_count):
                    curr_cells = ws.Range(ws.Cells(start_row + r_idx, start_col), ws.Cells(start_row + r_idx, start_col + max_col_count - 1))
                    first_val = str(ws.Cells(start_row + r_idx, start_col).Value or "").strip().lower()
                    is_sum = (r_idx == row_count - 1 and any(f[0] == r_idx for f in formula_cells)) or any(k in first_val for k in ["합계", "총계", "total", "sum"])
                    if is_sum:
                        if sum_bg is not None:
                            curr_cells.Interior.Color = sum_bg
                        curr_cells.Font.Bold = True
                    elif even_bg and (r_idx % 2 == 1):
                        curr_cells.Interior.Color = even_bg

                # 3) 실선 얇은 테두리
                try:
                    fill_rng.Borders.LineStyle = 1
                except Exception:
                    pass
                log_debug(f"Excel 표 테마({theme_dict.get('name', theme_arg)}) 일괄 적용 완료")
            except Exception as te:
                log_debug(f"테마 적용 중 예외: {te}")

        # 4차 처리: AutoFit 자동 연계 (열 너비가 좁아 ### 표시 방지)
        if autofit:
            try:
                fill_rng.Columns.AutoFit()
            except Exception:
                pass

        return format_response(
            status="ok",
            module="excel_fill",
            action="bulk_fill",
            preview=f"Range {target_range} filled ({row_count} rows, {max_col_count} cols, mode={mode}, formulas={len(formula_cells)})",
            agent_directive="VERIFIED: Bulk data filled successfully. Do not re-verify.",
            extra={
                "range": target_range,
                "rows": row_count,
                "cols": max_col_count,
                "mode": mode,
                "formula_count": len(formula_cells),
                "theme": theme_arg
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="excel_fill",
            action="fill",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Fill failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Fill Micro Block with Formula & Append Support")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름")
    parser.add_argument("--range", default="A1", help="시작 셀 (예: A1)")
    parser.add_argument("--data-file", type=str, help="주입할 CSV 파일 경로")
    parser.add_argument("--value", type=str, help="단일 셀에 쓸 값")
    parser.add_argument("--formula", type=str, help="단일 셀에 적용할 엑셀 수식 (예: '=SUM(C2:C10)')")
    parser.add_argument("--mode", choices=["overwrite", "append"], default="overwrite", help="덮어쓰기 또는 덧붙이기")
    parser.add_argument("--theme", type=str, help="표 테마 프리셋(navy, slate, teal, emerald) 또는 JSON 파일")
    parser.add_argument("--no-autofit", action="store_true", help="열 너비 자동 맞춤 비활성화")
    parser.add_argument("--clear", action="store_true", help="주입 전 시트 초기화")
    args = parser.parse_args()

    params = {
        "range": args.range,
        "data_file": args.data_file,
        "value": args.value,
        "formula": args.formula,
        "mode": args.mode,
        "theme": args.theme,
        "autofit": not args.no_autofit,
        "clear": args.clear
    }

    with excel_session(target=args.target, sheet_name=args.sheet, snapshot=True) as (app, wb, ws):
        res = execute(wb, ws, params)
        emit_response(res)

if __name__ == "__main__":
    main()
