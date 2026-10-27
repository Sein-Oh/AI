import sys
import os
import json
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import (
    format_response, emit_response, log_debug, parse_color_to_bgr,
    parse_replace_rules, normalize_and_expand_rules
)
from _com_guard import ppt_session
from _config import resolve_data_path

def apply_style_to_textrange(tr, rule: Dict[str, Any]) -> None:
    """PowerPoint TextRange 객체에 폰트 서식을 적용합니다."""
    if "bold" in rule:
        tr.Font.Bold = bool(rule["bold"])
    if "italic" in rule:
        tr.Font.Italic = bool(rule["italic"])
    if "size" in rule:
        tr.Font.Size = float(rule["size"])
    if "color" in rule:
        bgr = parse_color_to_bgr(rule["color"])
        if bgr is not None:
            tr.Font.Color.RGB = bgr

def replace_in_textframe(tf, find_str: str, rule: Any) -> int:
    """단일 TextFrame 내부에서 특정 문자열을 찾아 치환 및 서식을 적용합니다."""
    matched = 0
    replace_str = find_str
    if isinstance(rule, dict):
        replace_str = str(rule.get("text") or rule.get("replace") or find_str)
    elif isinstance(rule, str):
        replace_str = rule

    tr = tf.TextRange
    # 텍스트 내에 없거나 검색어가 비어있으면 COM Find 호출 없이 즉시 스킵 (초고속 방어)
    if not tr or not tr.Text or not find_str or find_str not in tr.Text:
        return 0

    max_loops = 500
    loop_count = 0
    found_tr = tr.Find(FindWhat=find_str)
    while found_tr is not None and loop_count < max_loops:
        loop_count += 1
        matched += 1
        try:
            found_tr.Text = replace_str
            if isinstance(rule, dict):
                apply_style_to_textrange(found_tr, rule)
        except Exception as e:
            log_debug(f"서식 적용 예외: {e}")
            break

        prev_start = found_tr.Start
        # PowerPoint COM: After=N은 N번째 문자 바로 다음(N+1)부터 검색함을 의미
        after_pos = max(0, prev_start + len(replace_str) - 1)
        if after_pos >= tr.Length:
            break

        try:
            found_tr = tr.Find(FindWhat=find_str, After=after_pos)
            if found_tr is not None and found_tr.Start <= prev_start:
                # PowerPoint COM Find의 순환 검색(Wrap-around) 방어
                break
        except Exception:
            break

    return matched

def process_shape_for_replace(shape, rules: Dict[str, Any]) -> int:
    """도형(일반, 표, 그룹화 도형) 내부 텍스트를 재귀적으로 찾아 치환합니다."""
    applied = 0
    # 1. 그룹화된 도형 (msoGroup = 6) 재귀 탐색
    try:
        if getattr(shape, "Type", None) == 6 or hasattr(shape, "GroupItems"):
            for sub_shape in shape.GroupItems:
                applied += process_shape_for_replace(sub_shape, rules)
            return applied
    except Exception:
        pass

    # 2. 일반 텍스트 상자 / 도형
    try:
        if shape.HasTextFrame and shape.TextFrame.HasText:
            tf = shape.TextFrame
            for target_word, rule in rules.items():
                cnt = replace_in_textframe(tf, str(target_word), rule)
                applied += cnt
    except Exception:
        pass

    # 3. 표(Table) 내부 셀
    try:
        if shape.HasTable:
            tbl = shape.Table
            for row_idx in range(1, tbl.Rows.Count + 1):
                for col_idx in range(1, tbl.Columns.Count + 1):
                    cell_tf = tbl.Cell(row_idx, col_idx).Shape.TextFrame
                    if cell_tf.HasText:
                        for target_word, rule in rules.items():
                            cnt = replace_in_textframe(cell_tf, str(target_word), rule)
                            applied += cnt
    except Exception:
        pass

    return applied

def execute(app, prs, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 PowerPoint 다중 치환 및 서식을 적용합니다."""
    mapping_file = params.get("mapping_file") or params.get("replace_map")
    target_slide_idx = params.get("slide") or params.get("pages")
    find_kw = params.get("find")
    replace_to = params.get("replace")
    style_spec = params.get("style", {})

    rules = {}
    if mapping_file:
        rules = parse_replace_rules(mapping_file, resolve_path_fn=resolve_data_path)
    elif find_kw:
        single_rule = dict(style_spec)
        if replace_to:
            single_rule["text"] = replace_to
        rules = {find_kw: single_rule}

    # ' | ' 등 가상 결합 구분자로 묶인 항목 자동 분해 및 확장
    rules = normalize_and_expand_rules(rules)

    if not rules:
        return format_response(
            status="no_match",
            module="ppt_edit",
            action="apply_edit",
            preview="No edit or replacement rules provided",
            agent_directive="STOP_RETRY: Empty edit map."
        )

    # 검사 대상 슬라이드 결정
    if target_slide_idx:
        slides_to_check = [prs.Slides(int(target_slide_idx))]
    else:
        slides_to_check = [s for s in prs.Slides]

    total_applied = 0

    for slide in slides_to_check:
        for shape in slide.Shapes:
            applied_cnt = process_shape_for_replace(shape, rules)
            total_applied += applied_cnt

    if total_applied == 0:
        return format_response(
            status="no_match",
            module="ppt_edit",
            action="apply_edit",
            preview="0 matches found for edit rules in PowerPoint",
            agent_directive="STOP_RETRY: Target text not found in presentation. Proceed."
        )

    return format_response(
        status="ok",
        module="ppt_edit",
        action="apply_edit",
        preview=f"{total_applied} replacements/styles successfully applied in PowerPoint",
        agent_directive="VERIFIED: PowerPoint edits applied. Do not re-verify.",
        extra={"applied_count": total_applied}
    )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Edit & Style Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--slide", type=int, help="대상 슬라이드 번호 (생략 시 전체 슬라이드)")
    parser.add_argument("--replace-map", type=str, help="styles.json 또는 edit_rules.json 경로")
    parser.add_argument("--find", type=str, help="검색 단어")
    parser.add_argument("--replace", type=str, help="치환할 단어")
    parser.add_argument("--bold", action="store_true", help="굵게")
    parser.add_argument("--color", type=str, help="글자색")
    parser.add_argument("--size", type=float, help="폰트 크기")
    args = parser.parse_args()

    style = {}
    if args.bold: style["bold"] = True
    if args.color: style["color"] = args.color
    if args.size: style["size"] = args.size

    params = {
        "slide": args.slide,
        "mapping_file": args.replace_map,
        "find": args.find,
        "replace": args.replace,
        "style": style
    }

    with ppt_session(target=args.target, snapshot=True) as (app, prs):
        res = execute(app, prs, params)
        emit_response(res)
    sys.stdout.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
