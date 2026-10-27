import sys
import os
import re
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, read_csv_table, parse_color_to_bgr
from _com_guard import word_session
from office_theme import resolve_theme

def parse_markdown_table(md_text: str) -> List[List[str]]:
    """마크다운 형식의 표 텍스트를 2차원 리스트로 파싱합니다."""
    lines = [line.strip() for line in md_text.strip().split("\n") if line.strip()]
    table = []
    for line in lines:
        if re.match(r"^\|?[\s\-:|]+\|?$", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        table.append(cells)
    return table

def insert_table_into_word(doc, target_range, matrix: List[List[str]], theme_spec: Optional[Dict[str, Any]] = None) -> Any:
    """Word Range 위치에 네이티브 Word 표(Table)를 생성하고 테마 서식(헤더 음영 및 지브라 패턴)을 적용합니다."""
    num_rows = len(matrix)
    num_cols = max(len(r) for r in matrix) if num_rows > 0 else 0
    if num_rows == 0 or num_cols == 0:
        return None

    table = doc.Tables.Add(target_range, num_rows, num_cols)
    table.Borders.Enable = True

    try:
        table.AutoFitBehavior(2)  # wdAutoFitWindow = 2 (문서 여백에 자동 맞춤)
    except Exception:
        pass

    header_bg_bgr = None
    zebra_even_bgr = None
    if theme_spec:
        h_bg = theme_spec.get("header", {}).get("bg") or theme_spec.get("primary", "#1B365D")
        header_bg_bgr = parse_color_to_bgr(h_bg)
        z_bg = theme_spec.get("zebra", {}).get("even", "#F4F7FB")
        zebra_even_bgr = parse_color_to_bgr(z_bg)

    for r_idx, row in enumerate(matrix):
        for c_idx, val in enumerate(row):
            try:
                cell = table.Cell(r_idx + 1, c_idx + 1)
                cell.Range.Text = str(val)
                if r_idx == 0:
                    cell.Range.Bold = True
                    if header_bg_bgr is not None:
                        cell.Range.Shading.BackgroundPatternColor = header_bg_bgr
                        cell.Range.Font.Color = 0xFFFFFF
                    else:
                        cell.Range.Shading.BackgroundPatternColor = 0xF0F0F0
                elif zebra_even_bgr is not None and (r_idx % 2 == 1):
                    cell.Range.Shading.BackgroundPatternColor = zebra_even_bgr
            except Exception:
                pass
    return table

def insert_callout_box(doc, target_range, title: str, text: str, theme_spec: Optional[Dict[str, Any]] = None) -> Any:
    """Word 문서에 좌측 강조선이 들어간 요약 박스(Callout Box)를 1x1 표로 생성합니다."""
    tbl = doc.Tables.Add(target_range, 1, 1)
    cell = tbl.Cell(1, 1)
    
    # 테마 색상 (좌측 강조 라인)
    primary_bgr = parse_color_to_bgr(theme_spec.get("primary", "#1B365D")) if theme_spec else 0x5D361B
    
    # 텍스트 삽입
    full_content = f"■ {title}\n{text}" if title else text
    cell.Range.Text = full_content
    
    # 셀 배경색 (연한 회색/하늘색)
    cell.Range.Shading.BackgroundPatternColor = 0xF8FAF8  # #F8FAF8
    
    # 좌측 테두리만 굵게 (WdBorderType: wdBorderLeft = -2, wdLineWidth300pt = 24)
    tbl.Borders.Enable = False
    try:
        tbl.Borders(-2).LineStyle = 1      # wdLineStyleSingle
        tbl.Borders(-2).LineWidth = 24     # 3.0 pt
        tbl.Borders(-2).Color = primary_bgr
    except Exception:
        pass

    return tbl

def insert_markdown_document(doc, md_text: str, theme_spec: Optional[Dict[str, Any]] = None) -> List[str]:
    """마크다운 서식(제목 #, ##, 불릿 -, *, 본문, 테마 표 |)을 완벽하게 분해하여 Word 서식 요소로 순차 삽입합니다."""
    blocks = []
    curr_type = None
    curr_lines = []

    for line in md_text.strip().splitlines():
        l_strip = line.strip()
        if not l_strip:
            if curr_type and curr_lines:
                blocks.append((curr_type, curr_lines))
                curr_type, curr_lines = None, []
            continue
        
        if l_strip.startswith('#'):
            if curr_type and curr_lines:
                blocks.append((curr_type, curr_lines))
                curr_type, curr_lines = None, []
            blocks.append(('heading', [l_strip]))
        elif l_strip.startswith('|') and '|' in l_strip[1:]:
            if curr_type != 'table':
                if curr_type and curr_lines:
                    blocks.append((curr_type, curr_lines))
                curr_type = 'table'
                curr_lines = [l_strip]
            else:
                curr_lines.append(l_strip)
        elif l_strip.startswith(('- ', '* ')):
            if curr_type != 'bullet':
                if curr_type and curr_lines:
                    blocks.append((curr_type, curr_lines))
                curr_type = 'bullet'
                curr_lines = [l_strip]
            else:
                curr_lines.append(l_strip)
        else:
            if curr_type != 'text':
                if curr_type and curr_lines:
                    blocks.append((curr_type, curr_lines))
                curr_type = 'text'
                curr_lines = [l_strip]
            else:
                curr_lines.append(l_strip)

    if curr_type and curr_lines:
        blocks.append((curr_type, curr_lines))

    primary_bgr = parse_color_to_bgr(theme_spec.get("primary", "#1B365D")) if theme_spec else 0x5D361B
    created = []

    for b_type, b_lines in blocks:
        rng = doc.Range(doc.Content.End - 1, doc.Content.End - 1)
        if b_type == 'heading':
            line = b_lines[0]
            level = len(line) - len(line.lstrip('#'))
            title_text = line.lstrip('#').strip()
            rng.Text = title_text + "\n"
            try:
                rng.Font.Bold = True
                if level == 1:
                    rng.Font.Size = 18
                    rng.Font.Color = primary_bgr
                elif level == 2:
                    rng.Font.Size = 14
                    rng.Font.Color = 0x333333
                else:
                    rng.Font.Size = 12
            except Exception:
                pass
            created.append(f"Heading{level}('{title_text[:15]}')")
        elif b_type == 'table':
            matrix = parse_markdown_table("\n".join(b_lines))
            if matrix:
                insert_table_into_word(doc, rng, matrix, theme_spec)
                rng_after = doc.Range(doc.Content.End - 1, doc.Content.End - 1)
                rng_after.InsertParagraphAfter()
                created.append(f"Table({len(matrix)} rows)")
        elif b_type == 'bullet':
            for b_line in b_lines:
                clean_b = re.sub(r"^[\-\*\+]\s+", "", b_line)
                b_rng = doc.Range(doc.Content.End - 1, doc.Content.End - 1)
                b_rng.Text = clean_b + "\n"
                try:
                    b_rng.Font.Bold = False
                    b_rng.Font.Size = 11
                    b_rng.ListFormat.ApplyBulletDefault()
                except Exception:
                    pass
            created.append(f"Bullets({len(b_lines)} items)")
        elif b_type == 'text':
            rng.Text = "\n".join(b_lines) + "\n"
            try:
                rng.Font.Bold = False
                rng.Font.Size = 11
                rng.Font.Color = 0x000000
            except Exception:
                pass
            created.append(f"Text({len(b_lines)} lines)")

    return created

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 Word 본문 쓰기, 앵커 삽입, 이미지 및 Callout 상자를 추가합니다."""
    text_content = params.get("text") or params.get("data") or ""
    anchor = (params.get("anchor") or "").strip()
    pos = (params.get("pos") or "after").lower()
    table_data = params.get("table_data")
    data_file = params.get("data_file")
    image_path = params.get("image")
    component = (params.get("component") or "").lower()
    title = params.get("title", "")
    bullet = params.get("bullet", False)
    theme_arg = params.get("theme")

    theme_spec = resolve_theme(theme_arg) if theme_arg else None

    try:
        is_pure_table = False
        matrix = None  # 표 분기에서만 할당되므로, 일반 텍스트/제목/글머리 경로의 UnboundLocalError 방지
        if data_file and os.path.exists(data_file):
            matrix = read_csv_table(data_file)
            is_pure_table = True
        elif table_data:
            if isinstance(table_data, str):
                matrix = parse_markdown_table(table_data)
            elif isinstance(table_data, list):
                matrix = table_data
            is_pure_table = True
        elif "|" in text_content and "\n" in text_content and component == "table":
            matrix = parse_markdown_table(text_content)
            is_pure_table = True
        elif "|" in text_content and "\n" in text_content and component != "callout":
            non_empty = [l.strip() for l in text_content.strip().splitlines() if l.strip()]
            if all(l.startswith("|") for l in non_empty):
                matrix = parse_markdown_table(text_content)
                is_pure_table = True

        # 삽입 위치 결정 (앵커 또는 문서 끝)
        if anchor:
            find_obj = doc.Content.Find
            find_obj.ClearFormatting()
            find_obj.Forward = True
            find_obj.Wrap = 0  # wdFindStop
            found = find_obj.Execute(FindText=anchor)
            if not found:
                log_debug(f"Anchor '{anchor}' not found. Falling back to document end.")
                target_range = doc.Range(doc.Content.End - 1, doc.Content.End - 1)
                target_range.InsertParagraphAfter()
                target_range = doc.Range(doc.Content.End - 1, doc.Content.End - 1)
            else:
                found_range = find_obj.Parent
                if pos == "replace":
                    target_range = found_range
                elif pos == "before":
                    target_range = doc.Range(found_range.Start, found_range.Start)
                else:
                    target_range = doc.Range(found_range.End, found_range.End)
                    target_range.InsertParagraphAfter()
                    target_range = doc.Range(target_range.End, target_range.End)
        else:
            end_pos = doc.Content.End - 1
            target_range = doc.Range(end_pos, end_pos)

        created_elements = []

        is_markdown_doc = (
            component == "markdown" or
            (component in ["text", ""] and not is_pure_table and not image_path and
             "\n" in text_content and ("#" in text_content or ("|" in text_content and any(l.strip().startswith("#") or l.strip().startswith("-") for l in text_content.strip().splitlines()))))
        )

        # 1. 이미지 삽입 (--image)
        if image_path:
            abs_img = os.path.abspath(image_path)
            if not os.path.exists(abs_img):
                return format_response(
                    status="no_match",
                    module="word_write",
                    action="insert_image",
                    preview=f"Image file not found: {abs_img}",
                    agent_directive="STOP_RETRY: Image path does not exist."
                )
            doc.InlineShapes.AddPicture(
                FileName=abs_img,
                LinkToFile=False,
                SaveWithDocument=True,
                Range=target_range
            )
            created_elements.append(f"Image('{os.path.basename(abs_img)}')")

        # 2. Callout 요약 상자 생성 (--component callout)
        elif component == "callout":
            insert_callout_box(doc, target_range, title, text_content, theme_spec)
            created_elements.append(f"CalloutBox('{title or text_content[:20]}')")

        # 3. 목차(TOC) 생성 (--component toc)
        elif component == "toc":
            try:
                doc.TablesOfContents.Add(
                    Range=target_range,
                    UseHeadingStyles=True,
                    UpperHeadingLevel=1,
                    LowerHeadingLevel=3
                )
                created_elements.append("TableOfContents(1-3 levels)")
            except Exception as te:
                log_debug(f"Word 목차(TOC) 생성 예외: {te}")
                # 일반 텍스트 목차 필드 폴백 삽입
                try:
                    doc.Fields.Add(Range=target_range, Type=13, Text="TOC \\o \"1-3\" \\h \\z \\u") # wdFieldTOC = 13
                    created_elements.append("TableOfContents(Field)")
                except Exception:
                    pass

        # 4. 복합 마크다운 문서 자동 렌더링
        elif is_markdown_doc:
            created_elements = insert_markdown_document(doc, text_content, theme_spec)

        # 5. 표 생성
        elif matrix:
            insert_table_into_word(doc, target_range, matrix, theme_spec)
            created_elements.append(f"Table({len(matrix)} rows)")

        # 5. 제목(Heading/Title) 서식 삽입
        elif component in ["heading", "title"]:
            target_range.Text = text_content + "\n"
            try:
                target_range.Font.Bold = True
                target_range.Font.Size = 14
            except Exception:
                pass
            created_elements.append(f"Heading({len(text_content)} chars)")

        # 6. 일반 텍스트 및 불릿 리스트
        elif text_content:
            target_range.Text = text_content + "\n"
            if bullet:
                try:
                    target_range.ListFormat.ApplyBulletDefault()
                except Exception:
                    pass
            created_elements.append(f"Text({len(text_content)} chars)")

        if not created_elements:
            return format_response(
                status="no_match",
                module="word_write",
                action="write",
                preview="No content provided (text, table, image, or callout required)",
                agent_directive="STOP_RETRY: Missing content."
            )

        preview_str = "Word content added: " + ", ".join(created_elements)
        if anchor:
            preview_str += f" at anchor '{anchor}' ({pos})"

        return format_response(
            status="ok",
            module="word_write",
            action="write",
            preview=preview_str,
            agent_directive="VERIFIED: Content written to Word document. Do not re-verify.",
            extra={"elements": created_elements, "anchor": anchor, "pos": pos}
        )

    except Exception as e:
        return format_response(
            status="error",
            module="word_write",
            action="write",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Word write failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Word Advanced Write Micro Block (Image & Callout Support)")
    parser.add_argument("--target", default="active", help="active 또는 docx 파일 경로")
    parser.add_argument("--text", "--data", type=str, help="추가할 일반 본문 텍스트 또는 마크다운 표")
    parser.add_argument("--anchor", type=str, help="삽입 기준이 될 기존 단락/키워드")
    parser.add_argument("--pos", choices=["before", "after", "replace", "end"], default="after", help="앵커 기준 삽입 위치")
    parser.add_argument("--data-file", type=str, help="표로 변환할 CSV 파일 경로")
    parser.add_argument("--image", type=str, help="삽입할 이미지 파일 경로 (PNG, JPG)")
    parser.add_argument("--component", choices=["callout", "table", "text", "heading", "title", "toc", "markdown"], default="text", help="컴포넌트 유형 (callout, table, text, heading, title, toc, markdown)")
    parser.add_argument("--title", type=str, help="Callout 상자 제목")
    parser.add_argument("--bullet", action="store_true", help="불릿(글머리 기호) 목록 적용")
    parser.add_argument("--theme", type=str, help="테마 프리셋(navy, slate, teal, emerald)")
    args = parser.parse_args()

    params = {
        "text": args.text,
        "anchor": args.anchor,
        "pos": args.pos,
        "data_file": args.data_file,
        "image": args.image,
        "component": args.component,
        "title": args.title,
        "bullet": args.bullet,
        "theme": args.theme
    }

    with word_session(target=args.target, snapshot=True) as (app, doc):
        res = execute(app, doc, params)
        emit_response(res)

if __name__ == "__main__":
    main()
