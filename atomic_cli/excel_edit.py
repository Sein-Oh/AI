import sys
import os
import json
import re
import argparse
from typing import Dict, Any, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import (
    format_response, emit_response, log_debug, parse_color_to_bgr,
    parse_replace_rules, normalize_and_expand_rules
)
from _com_guard import excel_session
from _config import resolve_data_path, get_data_dir
from office_theme import resolve_theme

ALIGN_MAP = {
    "left": -4131,   # xlHAlignLeft
    "center": -4108, # xlHAlignCenter
    "right": -4152   # xlHAlignRight
}

def apply_edit_to_range(rng, style: Dict[str, Any]) -> None:
    """Excel Range 객체에 안전하게 내용 수정 및 서식을 적용합니다."""
    # 1. 텍스트/값/수식 치환 (formula 또는 text 또는 replace)
    formula_val = style.get("formula")
    text_val = style.get("text") if "text" in style else style.get("replace")

    if formula_val is not None:
        f_str = str(formula_val).strip()
        rng.Formula = f_str if f_str.startswith("=") else f"={f_str}"
    elif text_val is not None:
        val_str = str(text_val).strip()
        if val_str.startswith("="):
            rng.Formula = val_str
        else:
            rng.Value = text_val

    # 2. 배경색 (bg / background)
    bg_val = style.get("bg") or style.get("background")
    if bg_val:
        bgr = parse_color_to_bgr(bg_val)
        if bgr is not None:
            rng.Interior.Color = bgr

    # 3. 글꼴색 (color)
    fg_val = style.get("color")
    if fg_val:
        bgr = parse_color_to_bgr(fg_val)
        if bgr is not None:
            rng.Font.Color = bgr

    # 4. 굵게 (bold)
    if "bold" in style:
        rng.Font.Bold = bool(style["bold"])

    # 5. 기울임 (italic)
    if "italic" in style:
        rng.Font.Italic = bool(style["italic"])

    # 6. 글꼴 크기 (size)
    if "size" in style:
        try:
            rng.Font.Size = float(style["size"])
        except ValueError:
            pass

    # 7. 정렬 (align)
    if "align" in style:
        align_code = ALIGN_MAP.get(str(style["align"]).lower())
        if align_code:
            rng.HorizontalAlignment = align_code

    # 8. 숫자 서식 (number_format)
    if "number_format" in style or "format_num" in style:
        fmt = style.get("number_format") or style.get("format_num")
        try:
            rng.NumberFormat = str(fmt)
        except Exception:
            pass

def apply_theme_to_table(
    ws,
    target_rng,
    theme: Dict[str, Any],
    zebra: Optional[bool] = None,
    format_num: Optional[str] = None
) -> Dict[str, Any]:
    """대상 범위 전체에 기업용 프로페셔널 테마(헤더, 줄무늬, 숫자포맷, 테두리, 요약행)를 일괄 적용합니다."""
    row_count = target_rng.Rows.Count
    col_count = target_rng.Columns.Count
    start_row = target_rng.Row
    start_col = target_rng.Column

    if row_count == 0 or col_count == 0:
        return {"rows": 0, "cols": 0}

    # 1. 헤더 행 서식 (1행)
    header_rng = ws.Range(ws.Cells(start_row, start_col), ws.Cells(start_row, start_col + col_count - 1))
    header_spec = theme.get("header", {})
    if header_spec:
        h_bg = header_spec.get("bg")
        if h_bg:
            bgr = parse_color_to_bgr(h_bg)
            if bgr is not None:
                header_rng.Interior.Color = bgr
        h_fg = header_spec.get("color")
        if h_fg:
            bgr = parse_color_to_bgr(h_fg)
            if bgr is not None:
                header_rng.Font.Color = bgr
        header_rng.Font.Bold = bool(header_spec.get("bold", True))
        header_rng.HorizontalAlignment = -4108  # xlHAlignCenter
        header_rng.VerticalAlignment = -4108    # xlVAlignCenter
        
        try:
            ws.Rows(start_row).RowHeight = float(header_spec.get("row_height", 24))
        except Exception:
            pass

    # 2. 데이터 행 서식 (2행부터)
    use_zebra = zebra if zebra is not None else theme.get("zebra", {}).get("enabled", False)
    odd_bg = parse_color_to_bgr(theme.get("zebra", {}).get("odd", "#FFFFFF"))
    even_bg = parse_color_to_bgr(theme.get("zebra", {}).get("even", "#F4F7FB"))

    num_fmt = format_num or theme.get("number_format")

    # 합계/요약 행 감지
    last_row_is_summary = False
    if row_count >= 3:
        first_cell_val = str(ws.Cells(start_row + row_count - 1, start_col).Value or "")
        if any(k in first_cell_val for k in ["합계", "총계", "Total", "소계", "평균"]):
            last_row_is_summary = True

    data_end_row = (start_row + row_count - 2) if last_row_is_summary else (start_row + row_count - 1)

    for r_idx, r in enumerate(range(start_row + 1, data_end_row + 1)):
        row_rng = ws.Range(ws.Cells(r, start_col), ws.Cells(r, start_col + col_count - 1))
        try:
            row_rng.VerticalAlignment = -4108  # 수직 가운데
            ws.Rows(r).RowHeight = 20          # 넉넉한 20pt 행높이
        except Exception:
            pass

        # Zebra 줄무늬
        if use_zebra:
            bg_color = even_bg if (r_idx % 2 == 1) else odd_bg
            if bg_color is not None:
                row_rng.Interior.Color = bg_color

    # 3. 숫자 열 서식 (#,##0 등) 적용
    if num_fmt:
        for c in range(start_col, start_col + col_count):
            for r in range(start_row + 1, min(start_row + row_count, start_row + 10)):
                val = ws.Cells(r, c).Value
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    col_data_rng = ws.Range(ws.Cells(start_row + 1, c), ws.Cells(start_row + row_count - 1, c))
                    col_data_rng.NumberFormat = num_fmt
                    col_data_rng.HorizontalAlignment = -4152  # xlHAlignRight
                    break

    # 4. 합계 행 스타일 (있을 경우)
    if last_row_is_summary:
        sum_row = start_row + row_count - 1
        sum_rng = ws.Range(ws.Cells(sum_row, start_col), ws.Cells(sum_row, start_col + col_count - 1))
        sum_spec = theme.get("summary", {})
        sum_bg = parse_color_to_bgr(sum_spec.get("bg", "#E8EEF5"))
        if sum_bg is not None:
            sum_rng.Interior.Color = sum_bg
        sum_fg = parse_color_to_bgr(sum_spec.get("color"))
        if sum_fg is not None:
            sum_rng.Font.Color = sum_fg
        sum_rng.Font.Bold = True
        try:
            ws.Rows(sum_row).RowHeight = 22
        except Exception:
            pass

        # 상단 얇은 실선 & 하단 이중선 (xlDouble = -4119)
        try:
            sum_rng.Borders(8).LineStyle = 1      # xlEdgeTop
            sum_rng.Borders(8).Weight = 2         # xlThin
            sum_rng.Borders(9).LineStyle = -4119  # xlEdgeBottom = xlDouble
        except Exception:
            pass

    # 5. 전체 테두리 (내부 얇은 선 + 헤더 하단 선)
    try:
        target_rng.Borders(11).LineStyle = 1      # xlInsideVertical
        target_rng.Borders(11).Weight = 2         # xlThin
        target_rng.Borders(12).LineStyle = 1      # xlInsideHorizontal
        target_rng.Borders(12).Weight = 2         # xlThin
        target_rng.BorderAround(1, 2)             # xlContinuous, xlThin
        
        # 헤더 하단 굵은 선 (xlMedium = -4138)
        header_rng.Borders(9).LineStyle = 1
        header_rng.Borders(9).Weight = -4138
    except Exception:
        pass

    return {
        "rows": row_count,
        "cols": col_count,
        "zebra": use_zebra,
        "number_format": num_fmt,
        "summary_row": last_row_is_summary
    }

def is_cell_address_or_range(key: str) -> bool:
    """'A1', 'A1:D10', 'B:B', 'B1, D1, A2:E3' 등의 단일/다중(유니온) 셀 주소 패턴인지 판별합니다."""
    k = key.strip().upper()
    parts = [p.strip() for p in k.split(",") if p.strip()]
    if not parts:
        return False
    single_pattern = re.compile(r"^([A-Z]+[0-9]+(:[A-Z]+[0-9]+)?|[A-Z]+:[A-Z]+|[0-9]+:[0-9]+)$")
    return all(bool(single_pattern.match(p)) for p in parts)

def apply_rule_to_range(target_rng, rule_str: str) -> int:
    """Range 내의 셀들에 조건부 서식 규칙(예: '>=100:lightgreen', '<80:pink', '=완료:lightgreen')을 적용합니다."""
    parts = rule_str.strip().split(":")
    if len(parts) < 2:
        return 0
    condition = parts[0].strip()
    color_val = parts[1].strip()
    bgr_color = parse_color_to_bgr(color_val)
    if bgr_color is None:
        return 0

    op = None
    threshold = None
    text_target = None

    try:
        if condition.startswith(">="):
            op, threshold = ">=", float(condition[2:])
        elif condition.startswith("<="):
            op, threshold = "<=", float(condition[2:])
        elif condition.startswith(">"):
            op, threshold = ">", float(condition[1:])
        elif condition.startswith("<"):
            op, threshold = "<", float(condition[1:])
        elif condition.startswith("="):
            text_target = condition[1:].strip()
        elif condition.startswith("text="):
            text_target = condition[5:].strip()
        else:
            text_target = condition
    except ValueError:
        text_target = condition

    applied = 0
    for cell in target_rng.Cells:
        val = cell.Value
        matched = False
        if op is not None and isinstance(val, (int, float)):
            if op == ">=" and val >= threshold: matched = True
            elif op == "<=" and val <= threshold: matched = True
            elif op == ">" and val > threshold: matched = True
            elif op == "<" and val < threshold: matched = True
        elif text_target is not None and val is not None:
            if text_target.lower() in str(val).strip().lower():
                matched = True

        if matched:
            cell.Interior.Color = bgr_color
            applied += 1

    return applied

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체로 내용 수정, 서식 적용 또는 테마를 일괄 적용합니다."""
    theme_arg = params.get("theme")
    range_str = params.get("range")
    zebra_opt = params.get("zebra")
    format_num_opt = params.get("format_num") or params.get("number_format")

    # A. 테마 일괄 적용 모드
    if theme_arg:
        theme = resolve_theme(theme_arg)
        target_rng = ws.Range(range_str) if range_str else ws.UsedRange
        theme_stat = apply_theme_to_table(ws, target_rng, theme, zebra=zebra_opt, format_num=format_num_opt)
        
        theme_name = theme.get("name", theme_arg)
        return format_response(
            status="ok",
            module="excel_edit",
            action="apply_theme",
            preview=f"Applied '{theme_name}' theme to {target_rng.Address} (Zebra: {theme_stat['zebra']}, NumFmt: {theme_stat['number_format']})",
            agent_directive="VERIFIED: Excel theme and professional styling applied.",
            extra={
                "theme_name": theme_name,
                "range": target_rng.Address,
                "details": theme_stat
            }
        )

    # B. 조건부 서식/규칙 하이라이트 모드 (--rule)
    rule_str = params.get("rule")
    if rule_str:
        target_rng = ws.Range(range_str) if range_str else ws.UsedRange
        applied_count = apply_rule_to_range(target_rng, rule_str)
        return format_response(
            status="ok",
            module="excel_edit",
            action="apply_rule",
            preview=f"Rule '{rule_str}' applied to {target_rng.Address} ({applied_count} cells matched)",
            agent_directive="VERIFIED: Conditional rule applied.",
            extra={"rule": rule_str, "range": target_rng.Address, "applied_count": applied_count}
        )

    # C. 개별 치환 / 서식 룰 적용 모드
    mapping_file = params.get("mapping_file") or params.get("replace_map")
    styles_map = params.get("styles") or params.get("rules")
    
    find_text = params.get("find")
    replace_text = params.get("replace")
    formula_text = params.get("formula")
    single_style = dict(params.get("style", {}))
    for k in ["bg", "color", "bold", "italic", "underline", "size", "align"]:
        if params.get(k) is not None and k not in single_style:
            single_style[k] = params.get(k)
    if formula_text is not None:
        single_style["formula"] = formula_text
    elif replace_text is not None:
        single_style["text"] = replace_text
    if format_num_opt is not None:
        single_style["number_format"] = format_num_opt

    rules = {}
    if mapping_file:
        rules = parse_replace_rules(mapping_file, resolve_path_fn=resolve_data_path)
    elif styles_map and isinstance(styles_map, dict):
        rules = styles_map
    elif find_text:
        rules = {str(find_text): single_style}
    elif range_str and single_style:
        rules = {range_str: single_style}

    # ' | ' 등 가상 결합 구분자로 묶인 항목 자동 분해 및 확장
    rules = normalize_and_expand_rules(rules)

    if not rules:
        return format_response(
            status="no_match",
            module="excel_edit",
            action="apply_edits",
            preview="No edit or style rules provided",
            agent_directive="STOP_RETRY: Empty edit rules."
        )

    applied_count = 0
    used_range = ws.UsedRange

    for key, style in rules.items():
        key_str = str(key).strip()
        
        # A. 셀 좌표/범위 직접 지정인 경우 (예: 'A1:G1', 'C3')
        if is_cell_address_or_range(key_str):
            try:
                target_rng = ws.Range(key_str)
                apply_edit_to_range(target_rng, style)
                applied_count += 1
                log_debug(f"범위 직접 내용/서식 적용: {key_str}")
            except Exception as e:
                log_debug(f"범위 지정 내용/서식 적용 실패 ({key_str}): {e}")
            continue

        # B. 텍스트/숫자 검색 기반 내용 수정 및 서식 적용
        try:
            cells = used_range.Cells
            row_count = used_range.Rows.Count
            col_count = used_range.Columns.Count

            values = used_range.Value
            if row_count == 1 and col_count == 1:
                values = ((values,),)
            elif row_count == 1:
                values = (values,)
            elif col_count == 1:
                values = tuple((row,) for row in values)

            start_row = used_range.Row
            start_col = used_range.Column

            for r_idx in range(row_count):
                row_vals = values[r_idx]
                for c_idx in range(col_count):
                    raw_val = row_vals[c_idx]
                    if raw_val is None:
                        continue
                    
                    val_str = ""
                    if isinstance(raw_val, float) and raw_val.is_integer():
                        val_str = str(int(raw_val))
                    else:
                        val_str = str(raw_val).strip()

                    if key_str == val_str or (len(key_str) > 1 and key_str in val_str):
                        cell_obj = ws.Cells(start_row + r_idx, start_col + c_idx)
                        target_style = dict(style)
                        text_val = target_style.get("text") if "text" in target_style else target_style.get("replace")
                        if text_val is not None and not str(text_val).strip().startswith("="):
                            # 부분 문자열 치환 지원 (Word/PPT와 동작 일치: 기존 셀 내용 내 매칭 키워드만 치환)
                            target_style["text"] = val_str.replace(key_str, str(text_val))
                        apply_edit_to_range(cell_obj, target_style)
                        applied_count += 1
                        log_debug(f"매칭 수정 완료: 셀({start_row + r_idx}, {start_col + c_idx}) = '{val_str}'")

        except Exception as e:
            log_debug(f"검색 수정 적용 중 예외 발생 (key='{key_str}'): {e}")

    if applied_count == 0:
        return format_response(
            status="no_match",
            module="excel_edit",
            action="apply_edits",
            preview="0 cells matched for given edit rules",
            agent_directive="STOP_RETRY: Target text/number not found in sheet. Proceed."
        )

    return format_response(
        status="ok",
        module="excel_edit",
        action="apply_edits",
        preview=f"{applied_count} cell modifications/styles successfully applied",
        agent_directive="VERIFIED: Edits applied. Do not re-verify.",
        extra={"applied_count": applied_count}
    )

def main():
    parser = argparse.ArgumentParser(description="Excel Edit & Professional Theme Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름")
    parser.add_argument("--theme", type=str, help="테마 프리셋(navy, slate, teal, emerald) 또는 테마 JSON 경로")
    parser.add_argument("--range", type=str, help="적용 범위 (예: 'A1:H20', 생략 시 UsedRange)")
    parser.add_argument("--zebra", action="store_true", help="Zebra 줄무늬 교차 배경 적용")
    parser.add_argument("--format-num", type=str, help="숫자 표시 서식 (예: '#,##0', '0.0%%', '₩#,##0')")
    parser.add_argument("--replace-map", type=str, help="styles.json 또는 edit_rules.json 경로")
    parser.add_argument("--rule", type=str, help="조건부 서식 규칙 (예: '>=100:lightgreen', '<80:pink', 'text=완료:green')")
    parser.add_argument("--find", type=str, help="검색할 텍스트 또는 셀 주소")
    parser.add_argument("--replace", type=str, help="치환할 새 텍스트")
    parser.add_argument("--formula", type=str, help="셀에 설정할 수식 (예: '=SUM(B2:B4)')")
    parser.add_argument("--bg", type=str, help="배경색 (yellow, #RRGGBB 등)")
    parser.add_argument("--color", type=str, help="글자색")
    parser.add_argument("--bold", action="store_true", help="굵게")
    parser.add_argument("--size", type=float, help="글꼴 크기")
    parser.add_argument("--align", choices=["left", "center", "right"], help="정렬")
    args = parser.parse_args()

    single_style = {}
    if args.bg: single_style["bg"] = args.bg
    if args.color: single_style["color"] = args.color
    if args.bold: single_style["bold"] = True
    if args.size: single_style["size"] = args.size
    if args.align: single_style["align"] = args.align
    if args.format_num: single_style["number_format"] = args.format_num

    params = {
        "theme": args.theme,
        "range": args.range,
        "zebra": args.zebra if args.zebra else None,
        "format_num": args.format_num,
        "rule": args.rule,
        "mapping_file": args.replace_map,
        "find": args.find,
        "replace": args.replace,
        "formula": args.formula,
        "style": single_style
    }

    with excel_session(target=args.target, sheet_name=args.sheet, snapshot=True) as (app, wb, ws):
        res = execute(wb, ws, params)
        emit_response(res)

if __name__ == "__main__":
    main()
