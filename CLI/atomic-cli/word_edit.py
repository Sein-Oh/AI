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
from _com_guard import word_session
from _config import resolve_data_path

# Word WdColorIndex 형광펜(Highlight) 매핑
WORD_HIGHLIGHT_MAP = {
    "yellow": 7,     # wdYellow
    "green": 4,      # wdBrightGreen
    "blue": 9,       # wdBlue
    "red": 6,        # wdRed
    "pink": 5,       # wdPink
    "gray": 16,      # wdGray25
    "none": 0        # wdNoHighlight
}

def apply_word_find_and_replace(doc, find_text: str, style_or_replace: Any) -> int:
    """Word 문서 전체에서 특정 텍스트를 검색하여 치환 및 서식을 적용합니다."""
    if not find_text:
        return 0

    replace_text = find_text
    bold = None
    italic = None
    color_bgr = None
    highlight_code = None

    if isinstance(style_or_replace, dict):
        if "text" in style_or_replace:
            replace_text = str(style_or_replace["text"])
        elif "replace" in style_or_replace:
            replace_text = str(style_or_replace["replace"])
        if "bold" in style_or_replace:
            bold = bool(style_or_replace["bold"])
        if "italic" in style_or_replace:
            italic = bool(style_or_replace["italic"])
        if "color" in style_or_replace:
            color_bgr = parse_color_to_bgr(style_or_replace["color"])
        if "bg" in style_or_replace or "highlight" in style_or_replace:
            hl = str(style_or_replace.get("bg") or style_or_replace.get("highlight")).lower()
            highlight_code = WORD_HIGHLIGHT_MAP.get(hl, 7)
    elif isinstance(style_or_replace, str):
        replace_text = style_or_replace

    matched_count = 0
    rng = doc.Content
    find_obj = rng.Find
    find_obj.ClearFormatting()
    find_obj.Forward = True
    find_obj.Wrap = 0  # wdFindStop (0): 문서 끝 도달 시 순환 검색 원천 차단

    max_loops = 5000
    loop_count = 0
    last_end = -1

    # 반복 검색하며 개별 매칭 범위에 치환 및 서식 적용
    while find_obj.Execute(FindText=find_text):
        loop_count += 1
        if loop_count > max_loops:
            log_debug(f"Word 검색 치환 최대 루프 한도({max_loops}) 초과로 안전 중단: '{find_text}'")
            break

        # 순환 검색(wrap-around) 또는 이전 위치 역행 방어
        if rng.Start < last_end:
            break

        matched_count += 1
        if replace_text != find_text:
            rng.Text = replace_text
        if bold is not None:
            rng.Bold = bold
        if italic is not None:
            rng.Italic = italic
        if color_bgr is not None:
            rng.Font.Color = color_bgr
        if highlight_code is not None:
            rng.HighlightColorIndex = highlight_code
        
        last_end = rng.End
        # 다음 검색을 위해 포인터를 치환 완료된 텍스트 뒤로 이동
        rng.Collapse(0)  # wdCollapseEnd

    return matched_count

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 Word 다중 치환, 서식 적용 및 내용 초기화(clear)를 수행합니다."""
    action = str(params.get("action") or "replace").lower()
    if action in ["clear", "delete_all"]:
        try:
            doc.Content.Delete()
            return format_response(
                status="ok",
                module="word_edit",
                action="clear",
                preview="Word 문서 내용이 전체 초기화(삭제)되었습니다.",
                agent_directive="VERIFIED: Word document cleared. Do not re-verify."
            )
        except Exception as e:
            return format_response(
                status="error",
                module="word_edit",
                action="clear",
                preview=f"Word 문서 내용 지우기 실패: {e}",
                agent_directive=f"STOP_RETRY: Failed to clear Word content: {e}"
            )

    mapping_file = params.get("mapping_file") or params.get("replace_map")
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
            module="word_edit",
            action="apply_edit",
            preview="No replacement or edit rules provided",
            agent_directive="STOP_RETRY: Empty edit rules."
        )

    total_applied = 0
    for target_word, rule in rules.items():
        cnt = apply_word_find_and_replace(doc, str(target_word), rule)
        total_applied += cnt
        log_debug(f"Word 단어 치환/서식 적용: '{target_word}' -> {cnt}건")

    if total_applied == 0:
        return format_response(
            status="no_match",
            module="word_edit",
            action="apply_edit",
            preview="0 matches found for edit rules",
            agent_directive="STOP_RETRY: Target words not found in document. Proceed."
        )

    return format_response(
        status="ok",
        module="word_edit",
        action="apply_edit",
        preview=f"{total_applied} replacements/styles successfully applied",
        agent_directive="VERIFIED: Word edits applied. Do not re-verify.",
        extra={"applied_count": total_applied}
    )

def main():
    parser = argparse.ArgumentParser(description="Word Edit & Style Micro Block")
    parser.add_argument("--action", default="replace", choices=["replace", "clear"], help="수행할 작업 (replace=치환/서식, clear=문서 전체 비우기)")
    parser.add_argument("--target", default="active", help="active 또는 docx 파일 경로")
    parser.add_argument("--replace-map", type=str, help="styles.json 또는 edit_rules.json 경로")
    parser.add_argument("--find", type=str, help="검색 단어")
    parser.add_argument("--replace", type=str, help="치환할 단어")
    parser.add_argument("--bold", action="store_true", help="굵게")
    parser.add_argument("--color", type=str, help="글자색")
    parser.add_argument("--highlight", type=str, help="형광펜 색상 (yellow, green, pink 등)")
    args = parser.parse_args()

    style = {}
    if args.bold: style["bold"] = True
    if args.color: style["color"] = args.color
    if args.highlight: style["highlight"] = args.highlight

    params = {
        "action": args.action,
        "mapping_file": args.replace_map,
        "find": args.find,
        "replace": args.replace,
        "style": style
    }

    with word_session(target=args.target, snapshot=True) as (app, doc):
        res = execute(app, doc, params)
        emit_response(res)

if __name__ == "__main__":
    main()
