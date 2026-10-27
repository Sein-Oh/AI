import sys
import os
import csv
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, run_session_tool
from _config import get_data_dir
from _com_guard import excel_session

def resolve_output_path(file_path: str, default_ext: str = ".csv") -> str:
    """출력 경로를 해석하며, 파일명만 지정된 경우 data_dir 하위로 자동 매핑합니다."""
    if not file_path:
        raise ValueError("출력 파일명(output_file)이 지정되지 않았습니다.")
        
    if not os.path.splitext(file_path)[1]:
        file_path += default_ext

    if os.path.isabs(file_path):
        out_path = file_path
    else:
        out_path = os.path.join(get_data_dir(), file_path)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    return os.path.abspath(out_path)

def extract_columns_from_sheet(ws, col_letters: List[str], start_row: Optional[int] = None, end_row: Optional[int] = None) -> List[List[Any]]:
    """지정된 열들(예: ['A', 'C', 'E'])의 데이터를 UsedRange 행 범위에 맞춰 행별로 결합합니다."""
    used = ws.UsedRange
    if start_row is None:
        start_row = used.Row
    if end_row is None:
        end_row = used.Row + used.Rows.Count - 1

    col_data = []
    for col in col_letters:
        col = col.strip().upper()
        # 단일 열 범위 조회 (예: 'A1:A101')
        rng = ws.Range(f"{col}{start_row}:{col}{end_row}")
        val = rng.Value
        
        row_count = end_row - start_row + 1
        if row_count == 1:
            col_data.append([val if val is not None else ""])
        elif isinstance(val, (list, tuple)):
            col_data.append([r[0] if r is not None else "" for r in val])
        else:
            col_data.append([val if val is not None else ""])

    # 행 단위로 결합
    num_rows = len(col_data[0]) if col_data else 0
    matrix = []
    for r_idx in range(num_rows):
        row_vals = [col_data[c_idx][r_idx] for c_idx in range(len(col_letters))]
        matrix.append(row_vals)
    return matrix

def extract_matrix_from_range(rng) -> List[List[Any]]:
    """Range 객체의 값을 직사각형 2D 파이썬 리스트로 변환합니다."""
    val = rng.Value
    row_count = rng.Rows.Count
    col_count = rng.Columns.Count

    if row_count == 1 and col_count == 1:
        return [[val if val is not None else ""]]
    elif row_count == 1:
        return [[c if c is not None else "" for c in val]]
    elif col_count == 1:
        return [[r[0] if r[0] is not None else ""] for r in val]
    else:
        return [[c if c is not None else "" for c in row] for row in val]

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 호출되는 엑셀 내보내기 엔진."""
    target_sheet_name = params.get("sheet")
    rng_address = (params.get("range") or "").strip()
    cols_param = params.get("columns", "")
    out_arg = params.get("output_file") or params.get("output")
    fmt = (params.get("format") or "").lower()

    if not out_arg:
        return format_response(
            status="error",
            module="excel_export",
            action="export",
            preview="output_file parameter is required",
            agent_directive="STOP_RETRY: Missing output file path."
        )

    try:
        # 1. 대상 워크시트 결정
        target_ws = ws
        if target_sheet_name:
            try:
                target_ws = wb.Worksheets(target_sheet_name)
            except Exception as e:
                return format_response(
                    status="no_match",
                    module="excel_export",
                    action="export",
                    preview=f"Sheet '{target_sheet_name}' not found",
                    agent_directive="STOP_RETRY: Target sheet does not exist."
                )

        # 2. 비연속 열(A, C, E 등) 지정 여부 분석
        target_cols = []
        if cols_param:
            target_cols = [c.strip().upper() for c in cols_param.split(",") if c.strip()]
        elif rng_address and ("," in rng_address or ":" in rng_address):
            parts = [p.strip().upper() for p in rng_address.split(",") if p.strip()]
            # 모든 파트가 'A' 또는 'A:A' 형태인 경우 순수 열 목록으로 해석
            if all(len(p) <= 2 or (":" in p and p.split(":")[0] == p.split(":")[1]) for p in parts):
                target_cols = [p.split(":")[0] for p in parts]

        is_col_mode = len(target_cols) > 0

        # 3. 출력 포맷 결정 (확장자 또는 format 인자)
        out_ext = os.path.splitext(out_arg)[1].lower()
        if fmt:
            out_format = fmt
        elif out_ext in [".csv", ".xlsx"]:
            out_format = out_ext[1:]
        else:
            out_format = "csv"

        final_out_path = resolve_output_path(out_arg, default_ext=f".{out_format}")
        
        # 4. 데이터 매트릭스 추출
        if is_col_mode:
            matrix = extract_columns_from_sheet(target_ws, target_cols)
            row_count = len(matrix)
            col_count = len(target_cols)
            source_desc = f"{target_ws.Name} (열: {', '.join(target_cols)})"
        else:
            target_rng = target_ws.Range(rng_address) if rng_address else target_ws.UsedRange
            matrix = extract_matrix_from_range(target_rng)
            row_count = len(matrix)
            col_count = len(matrix[0]) if row_count > 0 else 0
            source_desc = f"{target_ws.Name}!{target_rng.Address}"

        log_debug(f"Export 대상: {source_desc}, 포맷='{out_format}', 경로='{final_out_path}'")

        # A. CSV 내보내기 (한국어 엑셀 2007~365 완벽 호환 인코딩 지원)
        if out_format == "csv":
            csv_encoding = params.get("encoding") or "cp949"
            try:
                with open(final_out_path, "w", encoding=csv_encoding, newline="") as f:
                    writer = csv.writer(f)
                    for row in matrix:
                        writer.writerow([str(v) if v is not None else "" for v in row])
            except UnicodeEncodeError:
                # 특수문자 등으로 cp949 인코딩 실패 시 utf-8-sig로 자동 폴백
                csv_encoding = "utf-8-sig"
                with open(final_out_path, "w", encoding=csv_encoding, newline="") as f:
                    writer = csv.writer(f)
                    for row in matrix:
                        writer.writerow([str(v) if v is not None else "" for v in row])

            preview_msg = f"Exported {row_count} rows x {col_count} cols ({source_desc}) to CSV ({csv_encoding}): {os.path.basename(final_out_path)}"
            return format_response(
                status="ok",
                module="excel_export",
                action="export_csv",
                preview=preview_msg,
                agent_directive="VERIFIED: CSV exported successfully. Active window preserved.",
                extra={
                    "file_path": final_out_path,
                    "rows": row_count,
                    "cols": col_count,
                    "format": "csv"
                }
            )

        # B. XLSX 내보내기 (기존 활성 창 손상 없이 새 독립 워크북으로 저장)
        elif out_format == "xlsx":
            app = wb.Application
            prev_alerts = app.DisplayAlerts
            new_wb = None
            try:
                app.DisplayAlerts = False
                # 새 워크북 생성 (사용자 화면에 새 창이 뜨지 않도록 즉시 숨김)
                new_wb = app.Workbooks.Add()
                try:
                    new_wb.Windows(1).Visible = False
                except Exception:
                    pass
                new_ws = new_wb.Worksheets(1)
                new_ws.Name = target_ws.Name

                if is_col_mode:
                    from _office_utils import get_target_range_address
                    target_range_addr = get_target_range_address("A1", row_count, col_count)
                    new_ws.Range(target_range_addr).Value = tuple(tuple(r) for r in matrix)
                else:
                    target_rng = target_ws.Range(rng_address) if rng_address else target_ws.UsedRange
                    target_rng.Copy(Destination=new_ws.Range("A1"))

                new_ws.Columns.AutoFit()

                # 숨긴 창 상태가 파일에 저장되어 다음에 열 때 안 보이는 문제 방지
                try:
                    new_wb.Windows(1).Visible = True
                except Exception:
                    pass
                new_wb.SaveAs(final_out_path, FileFormat=51)  # xlOpenXMLWorkbook
            finally:
                # 실패하더라도 임시 워크북이 사용자 Excel에 남지 않도록 항상 닫고 경고 설정 복원
                if new_wb is not None:
                    try:
                        new_wb.Close(SaveChanges=False)
                    except Exception:
                        pass
                try:
                    app.DisplayAlerts = prev_alerts
                except Exception:
                    pass

            preview_msg = f"Exported {source_desc} to new XLSX workbook: {os.path.basename(final_out_path)}"
            return format_response(
                status="ok",
                module="excel_export",
                action="export_xlsx",
                preview=preview_msg,
                agent_directive="VERIFIED: XLSX exported successfully. Active window preserved.",
                extra={
                    "file_path": final_out_path,
                    "sheet": target_ws.Name,
                    "format": "xlsx"
                }
            )

        else:
            raise ValueError(f"지원하지 않는 내보내기 형식입니다: {out_format} (csv 또는 xlsx 지원)")

    except Exception as e:
        return format_response(
            status="error",
            module="excel_export",
            action="export",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Export failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Export Micro Block (CSV & XLSX)")
    parser.add_argument("--target", default="active", help="active 또는 엑셀 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름 (생략 시 활성 시트)")
    parser.add_argument("--range", type=str, help="내보낼 셀 범위 (예: A1:C10, 생략 시 UsedRange)")
    parser.add_argument("--columns", "-c", type=str, help="선택적으로 내보낼 열 목록 (예: A,C,E)")
    parser.add_argument("--output", "-o", required=True, help="저장할 파일명 또는 경로 (.csv 또는 .xlsx)")
    parser.add_argument("--format", choices=["csv", "xlsx"], help="출력 포맷 강제 지정")
    parser.add_argument("--encoding", default="cp949", choices=["cp949", "utf-8-sig", "utf-8"], help="CSV 인코딩 (기본값 cp949: 한국어 엑셀 2007~365 완벽 호환)")
    args = parser.parse_args()

    params = {
        "sheet": args.sheet,
        "range": args.range,
        "columns": args.columns,
        "output_file": args.output,
        "format": args.format,
        "encoding": args.encoding
    }

    is_active = (args.target.lower() == "active")
    file_path = args.target if not is_active else None

    # 원본이 디스크의 CSV 파일인 경우: 엑셀에서 열려 있어도 잠금 충돌 없이 파이썬 엔진으로 0.005초 직접 처리
    if not is_active and file_path and file_path.lower().endswith(".csv") and os.path.exists(file_path):
        from _office_utils import read_csv_table
        matrix = read_csv_table(file_path)
        
        # 범위 슬라이싱 (예: A1:C20)
        rng_str = (args.range or "").strip().upper()
        import re
        m = re.match(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$", rng_str)
        if m:
            start_col, start_row, end_col, end_row = m.groups()
            s_row, e_row = int(start_row) - 1, int(end_row)
            
            def col_to_idx(c_str):
                idx = 0
                for ch in c_str:
                    idx = idx * 26 + (ord(ch) - ord('A') + 1)
                return idx - 1
                
            s_col, e_col = col_to_idx(start_col), col_to_idx(end_col) + 1
            sliced_matrix = [row[s_col:e_col] for row in matrix[s_row:e_row]]
        else:
            sliced_matrix = matrix

        out_path = resolve_output_path(args.output, default_ext=".csv")
        csv_encoding = args.encoding or "cp949"
        
        try:
            with open(out_path, "w", encoding=csv_encoding, newline="") as f:
                writer = csv.writer(f)
                for r in sliced_matrix:
                    writer.writerow([str(v) if v is not None else "" for v in r])
        except UnicodeEncodeError:
            csv_encoding = "utf-8-sig"
            with open(out_path, "w", encoding=csv_encoding, newline="") as f:
                writer = csv.writer(f)
                for r in sliced_matrix:
                    writer.writerow([str(v) if v is not None else "" for v in r])

        row_c = len(sliced_matrix)
        col_c = len(sliced_matrix[0]) if row_c > 0 else 0
        emit_response(format_response(
            status="ok",
            module="excel_export",
            action="export_csv_direct",
            preview=f"Exported {row_c} rows x {col_c} cols ({rng_str or 'All'}) from CSV: {os.path.basename(out_path)}",
            agent_directive="VERIFIED: CSV exported successfully without file lock.",
            extra={
                "file_path": out_path,
                "rows": row_c,
                "cols": col_c,
                "format": "csv"
            }
        ))
        return

    run_session_tool("excel_export", "export",
                     lambda: excel_session(target=args.target, sheet_name=args.sheet),
                     lambda app, wb, ws: execute(wb, ws, params))

if __name__ == "__main__":
    main()
