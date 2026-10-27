import sys
import os
import hashlib
import json
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import excel_session
from _cache import get_file_cache, save_file_cache

def read_cells_to_matrix(rng) -> List[List[Any]]:
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

def execute(wb=None, ws=None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체 또는 캐시를 통해 엑셀 데이터를 고속 조회합니다."""
    if params is None and isinstance(wb, dict):
        params = wb
        wb = None
        ws = None
    if params is None:
        params = {}

    rng_address = (params.get("range") or "").strip()
    search_keyword = (params.get("search") or "").strip()
    search_color = (params.get("color") or "").strip().lower()
    output_format = (params.get("format") or "table").lower()
    
    file_path = params.get("file_path") or (params.get("target") if params.get("target", "active").lower() != "active" else None)
    is_active = (params.get("target", "active").lower() == "active") and (not file_path)

    # 1. 파일 대상이고 캐시 유효 시 (Active OFF vs File ON)
    if not is_active and file_path and os.path.exists(file_path):
        cached_payload = get_file_cache(file_path, sub_key=f"{rng_address}_{output_format}")
        if cached_payload:
            return format_response(
                status="ok",
                module="excel_read",
                action="read_cached",
                preview=f"Read from cache ({len(cached_payload.get('data', []))} rows)",
                agent_directive="VERIFIED: Data retrieved from disk cache.",
                extra=cached_payload
            )

    # 2. 순수 CSV 파일인 경우: COM 없이 초고속 읽기
    if not is_active and file_path and file_path.lower().endswith(".csv") and os.path.exists(file_path):
        from _office_utils import read_csv_table
        matrix = read_csv_table(file_path)
        row_count = len(matrix)
        col_count = len(matrix[0]) if row_count > 0 else 0
        items = []
        for r_idx, row in enumerate(matrix):
            row_str = " | ".join(str(c) for c in row if c is not None and str(c).strip() != "")
            if row_str.strip():
                items.append({"loc": f"Row {r_idx + 1}", "row": r_idx + 1, "text": row_str})
        result_payload = {
            "range": f"A1:{row_count}x{col_count}",
            "rows": row_count,
            "cols": col_count,
            "items": items,
            "data": matrix if output_format == "table" else []
        }
        save_file_cache(file_path, result_payload, sub_key=f"{rng_address}_{output_format}", max_keep=2)
        return format_response(
            status="ok",
            module="excel_read",
            action="read_csv_direct",
            preview=f"Read {row_count} rows x {col_count} cols from CSV: {os.path.basename(file_path)}",
            agent_directive="VERIFIED: CSV read successfully without Excel COM overhead.",
            extra=result_payload
        )

    # 3. COM 객체가 주어지지 않은 경우 excel_session으로 열기
    if ws is None:
        target_name = file_path if (file_path and os.path.exists(file_path)) else "active"
        with excel_session(target=target_name, sheet_name=params.get("sheet")) as (s_app, s_wb, s_ws):
            return execute(s_wb, s_ws, params)

    # 4. 실시간 COM 조회 (활성창이거나 캐시 미스)
    try:
        target_rng = ws.Range(rng_address) if rng_address else ws.UsedRange
        matrix = read_cells_to_matrix(target_rng)
        row_count = len(matrix)
        col_count = len(matrix[0]) if row_count > 0 else 0

        # 검색 키워드가 있는 경우 필터링
        matched_cells = []
        if search_keyword:
            kw = search_keyword.lower()
            for r_idx, row in enumerate(matrix):
                for c_idx, val in enumerate(row):
                    if kw in str(val).lower():
                        matched_cells.append({"row": r_idx + 1, "col": c_idx + 1, "value": val})

        # 배경색 필터링 (search_color)
        color_matches = []
        if search_color:
            try:
                cell_count = target_rng.CountLarge if hasattr(target_rng, "CountLarge") else target_rng.Count
                scan_rng = target_rng if cell_count <= 2500 else ws.Range("A1:Z50")
                for cell in scan_rng.Cells:
                    try:
                        int_color = int(cell.Interior.Color)
                        has_fill = (cell.Interior.ColorIndex != -4142) and (cell.Interior.Pattern != -4142)
                        if has_fill:
                            r = int_color & 0xFF
                            g = (int_color >> 8) & 0xFF
                            b = (int_color >> 16) & 0xFF
                            hex_color = f"#{r:02X}{g:02X}{b:02X}"
                            addr = str(cell.Address).replace("$", "")
                            is_red = (r > 180 and g < 70 and b < 70)
                            match = False
                            if search_color in ("red", "빨강", "빨간색", "#ff0000") and is_red:
                                match = True
                            elif search_color in hex_color.lower():
                                match = True
                            elif search_color in ("any", "all", "*"):
                                match = True

                            if match:
                                color_matches.append({
                                    "address": addr,
                                    "color": hex_color,
                                    "rgb": [r, g, b],
                                    "value": cell.Value
                                })
                    except Exception:
                        pass
            except Exception as e:
                log_debug(f"Color scan error: {e}")

        items = []
        for r_idx, row in enumerate(matrix):
            row_str = " | ".join(str(c) for c in row if c is not None and str(c).strip() != "")
            if row_str.strip():
                items.append({"loc": f"Row {r_idx + 1}", "row": r_idx + 1, "text": row_str})

        result_payload = {
            "range": rng_address or ws.UsedRange.Address,
            "rows": row_count,
            "cols": col_count,
            "items": items,
            "data": matrix if output_format == "table" else []
        }

        if row_count == 1 and col_count == 1:
            try:
                formula_val = target_rng.Formula
                if formula_val and str(formula_val).startswith("="):
                    result_payload["formula"] = str(formula_val)
            except Exception:
                pass

        if search_keyword:
            result_payload["matched"] = matched_cells
            if len(matched_cells) == 0:
                return format_response(
                    status="no_match",
                    module="excel_read",
                    action="search",
                    preview=f"Found 0 cells matching '{search_keyword}'",
                    agent_directive=f"STOP_RETRY: Keyword '{search_keyword}' not found.",
                    extra=result_payload
                )
            preview_msg = f"Found {len(matched_cells)} cells matching '{search_keyword}'"
        elif search_color:
            result_payload["colored_cells"] = color_matches
            if len(color_matches) == 0:
                return format_response(
                    status="no_match",
                    module="excel_read",
                    action="search_color",
                    preview=f"Found 0 cells with color '{search_color}'",
                    agent_directive=f"STOP_RETRY: No cells found with color '{search_color}'.",
                    extra=result_payload
                )
            matched_addrs = ", ".join(c["address"] for c in color_matches[:12])
            preview_msg = f"Found {len(color_matches)} cells matching color '{search_color}': {matched_addrs}"
        else:
            preview_msg = f"Read {row_count} rows x {col_count} cols ({result_payload['range']})"

        # 파일 대상인 경우 캐시 파일 생성 (최근 2개 유지 정책 적용)
        if not is_active and file_path and os.path.exists(file_path):
            save_file_cache(file_path, result_payload, sub_key=f"{rng_address}_{output_format}", max_keep=2)

        return format_response(
            status="ok",
            module="excel_read",
            action="read",
            preview=preview_msg,
            agent_directive="VERIFIED: Data read successfully.",
            extra=result_payload
        )

    except Exception as e:
        return format_response(
            status="error",
            module="excel_read",
            action="read",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Read failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Read Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름")
    parser.add_argument("--range", type=str, help="조회할 범위 (생략 시 UsedRange)")
    parser.add_argument("--search", type=str, help="검색할 키워드")
    parser.add_argument("--color", type=str, help="검색할 셀 배경색 (예: red, #FF0000, any)")
    parser.add_argument("--format", default="table", choices=["table", "summary"])
    args = parser.parse_args()

    is_active = (args.target.lower() == "active")
    file_path = args.target if not is_active else None

    # 1. 초고속 캐시 선조회 (캐시 히트 시 프로세스 실행 일체 없이 0.005초 반환)
    sub_key = f"{(args.range or '').strip()}_{args.format}"
    if not is_active and file_path and os.path.exists(file_path):
        cached_payload = get_file_cache(file_path, sub_key=sub_key)
        if cached_payload:
            emit_response(format_response(
                status="ok",
                module="excel_read",
                action="read_cached",
                preview=f"Read from cache ({len(cached_payload.get('data', []))} rows)",
                agent_directive="VERIFIED: Data retrieved from disk cache.",
                extra=cached_payload
            ))
            return

    # 2. 순수 CSV 파일인 경우: 엑셀 COM을 띄우지 않고 파이썬 엔진으로 0.001초 무결성 고속 읽기
    if not is_active and file_path and file_path.lower().endswith(".csv") and os.path.exists(file_path):
        from _office_utils import read_csv_table
        matrix = read_csv_table(file_path)
        row_count = len(matrix)
        col_count = len(matrix[0]) if row_count > 0 else 0
        
        result_payload = {
            "range": f"A1:{row_count}x{col_count}",
            "rows": row_count,
            "cols": col_count,
            "data": matrix if args.format == "table" else []
        }
        
        # 캐시 저장 (최근 2개 유지)
        save_file_cache(file_path, result_payload, sub_key=sub_key, max_keep=2)
        
        emit_response(format_response(
            status="ok",
            module="excel_read",
            action="read_csv_direct",
            preview=f"Read {row_count} rows x {col_count} cols from CSV: {os.path.basename(file_path)}",
            agent_directive="VERIFIED: CSV read successfully without Excel COM overhead.",
            extra=result_payload
        ))
        return

    params = {
        "range": args.range,
        "search": args.search,
        "color": args.color,
        "format": args.format,
        "target": args.target,
        "file_path": file_path
    }

    with excel_session(target=args.target, sheet_name=args.sheet) as (app, wb, ws):
        res = execute(wb, ws, params)
        emit_response(res)

if __name__ == "__main__":
    main()
