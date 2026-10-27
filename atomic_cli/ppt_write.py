import sys
import os
import re
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, read_csv_table, parse_color_to_bgr
from _com_guard import ppt_session
from office_theme import resolve_theme

MSO_SHAPE_RECTANGLE = 1
MSO_SHAPE_ROUNDED_RECTANGLE = 5

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

def parse_cards_data(raw_cards: str) -> List[Dict[str, str]]:
    """'제목1:설명1|제목2:설명2|제목3:설명3' 형태의 문자열을 카드 리스트로 파싱합니다."""
    cards = []
    items = raw_cards.strip().split("|")
    for item in items:
        if ":" in item:
            title, desc = item.split(":", 1)
            cards.append({"title": title.strip(), "desc": desc.strip()})
        else:
            cards.append({"title": item.strip(), "desc": ""})
    return cards

def execute(app, prs, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 PowerPoint 슬라이드에 텍스트, 표, 이미지 및 비주얼 카드를 주입합니다."""
    slide_idx = int(params.get("slide") or prs.Slides.Count)
    title_text = params.get("title", "")
    body_text = params.get("text") or params.get("body", "")
    table_data = params.get("table_data")
    data_file = params.get("data_file")
    image_path = params.get("image")
    component = (params.get("component") or "").lower()
    cards_input = params.get("cards")
    theme_arg = params.get("theme")

    left = float(params.get("left") if params.get("left") is not None else 50)
    width = float(params.get("width") if params.get("width") is not None else 620)

    user_top = params.get("top")
    user_height = params.get("height")

    if user_height is not None:
        height = float(user_height)
    else:
        height = 160.0 if component == "cards" else (180.0 if component == "table" else 250.0)

    try:
        if prs.Slides.Count == 0:
            prs.Slides.Add(1, 12)  # 빈 슬라이드 추가

        if slide_idx < 1 or slide_idx > prs.Slides.Count:
            slide_idx = prs.Slides.Count

        slide = prs.Slides(slide_idx)

        # Smart Stacking: top이 지정되지 않은 경우 슬라이드 내 기존 요소 아래 20pt로 자동 누적
        if user_top is not None:
            top = float(user_top)
        else:
            max_bottom = 90.0
            try:
                for sh in slide.Shapes:
                    try:
                        s_bottom = sh.Top + sh.Height
                        if s_bottom > max_bottom and s_bottom < 500:
                            max_bottom = s_bottom
                    except Exception:
                        pass
            except Exception:
                pass
            top = max_bottom + 20.0
            log_debug(f"[Smart Stacking] 좌표 자동 산출 완료: Top={top}pt, Height={height}pt")

        created_elements = []

        # 테마 파싱
        theme = resolve_theme(theme_arg) if theme_arg else resolve_theme("navy")
        primary_color_bgr = parse_color_to_bgr(theme.get("primary", "#1B365D"))
        secondary_color_bgr = parse_color_to_bgr(theme.get("secondary", "#4A777A"))

        # 1. 제목 텍스트 상자 추가
        if title_text:
            title_shape = slide.Shapes.AddTextbox(1, 50, 30, 620, 50)
            tf = title_shape.TextFrame
            tf.TextRange.Text = title_text
            tf.TextRange.Font.Size = 24
            tf.TextRange.Font.Bold = True
            if primary_color_bgr is not None:
                tf.TextRange.Font.Color.RGB = primary_color_bgr
            created_elements.append(f"Title('{title_text[:20]}')")

        # 2. 이미지 삽입 (--image)
        if image_path:
            abs_img = os.path.abspath(image_path)
            if not os.path.exists(abs_img):
                return format_response(
                    status="no_match",
                    module="ppt_write",
                    action="insert_image",
                    preview=f"Image file not found: {abs_img}",
                    agent_directive="STOP_RETRY: Image path does not exist."
                )
            # 가로/세로 -1 지정 시 원본 비율 유지
            img_w = width if width != 620 else -1
            img_h = height if height != 320 else -1
            img_shape = slide.Shapes.AddPicture(
                FileName=abs_img,
                LinkToFile=False,
                SaveWithDocument=True,
                Left=left,
                Top=top,
                Width=img_w,
                Height=img_h
            )
            created_elements.append(f"Image('{os.path.basename(abs_img)}')")

        # 3. 비주얼 카드 레이아웃 생성 (--component cards)
        if component in ["cards", "card", "kpi"] and (cards_input or body_text):
            raw_c = cards_input or body_text
            cards = parse_cards_data(raw_c)
            card_count = len(cards)
            if card_count > 0:
                spacing = 15
                total_w = width
                card_w = (total_w - (spacing * (card_count - 1))) / card_count
                card_h = height if height != 320 else 200

                for idx, c_info in enumerate(cards):
                    c_left = left + (idx * (card_w + spacing))
                    card_shape = slide.Shapes.AddShape(MSO_SHAPE_ROUNDED_RECTANGLE, c_left, top, card_w, card_h)
                    
                    # 카드 배경색 (은은한 회색/하늘색)
                    card_shape.Fill.Visible = True
                    card_shape.Fill.ForeColor.RGB = 0xFAFAF8  # #F8FAFA
                    card_shape.Line.Visible = True
                    card_shape.Line.ForeColor.RGB = primary_color_bgr if primary_color_bgr else 0xD0D7DE
                    card_shape.Line.Weight = 1.5

                    # 텍스트 삽입 (제목 16pt Bold + 설명 12pt)
                    tf = card_shape.TextFrame
                    tf.MarginLeft = 12
                    tf.MarginRight = 12
                    tf.MarginTop = 15
                    tf.MarginBottom = 15
                    
                    full_text = f"{c_info['title']}\n\n{c_info['desc']}" if c_info['desc'] else c_info['title']
                    tf.TextRange.Text = full_text
                    
                    # 1행(제목) 볼드 및 테마 색상 부여
                    if len(tf.TextRange.Paragraphs()) >= 1:
                        p1 = tf.TextRange.Paragraphs(1)
                        p1.Font.Bold = True
                        p1.Font.Size = 16
                        if primary_color_bgr is not None:
                            p1.Font.Color.RGB = primary_color_bgr

                created_elements.append(f"Cards({card_count} boxes)")

        # 4. 표 데이터 주입 (CSV 또는 마크다운)
        matrix = None
        if data_file and os.path.exists(data_file):
            matrix = read_csv_table(data_file)
        elif table_data:
            if isinstance(table_data, str):
                matrix = parse_markdown_table(table_data)
            elif isinstance(table_data, list):
                matrix = table_data
        elif "|" in body_text and "\n" in body_text and component not in ["cards", "card"]:
            matrix = parse_markdown_table(body_text)

        if matrix:
            if len(matrix) > 75:
                log_debug(f"PowerPoint 표 행 제한: {len(matrix)}행 -> 75행으로 자름")
                matrix = matrix[:75]
            num_rows = len(matrix)
            num_cols = max(len(r) for r in matrix) if num_rows > 0 else 0
            
            table_shape = slide.Shapes.AddTable(num_rows, num_cols, left, top, width, height)
            tbl = table_shape.Table

            for r_idx, row in enumerate(matrix):
                for c_idx, val in enumerate(row):
                    try:
                        cell = tbl.Cell(r_idx + 1, c_idx + 1)
                        cell.Shape.TextFrame.TextRange.Text = str(val)
                        if r_idx == 0:
                            cell.Shape.TextFrame.TextRange.Font.Bold = True
                            cell.Shape.TextFrame.TextRange.Font.Size = 13
                            if primary_color_bgr is not None:
                                cell.Shape.Fill.ForeColor.RGB = primary_color_bgr
                                cell.Shape.TextFrame.TextRange.Font.Color.RGB = 0xFFFFFF
                        else:
                            cell.Shape.TextFrame.TextRange.Font.Size = 11
                    except Exception:
                        pass
            created_elements.append(f"Table({num_rows}x{num_cols})")

        # 5. 일반 본문 텍스트 상자 (위 요소들이 없을 경우)
        if body_text and not matrix and component not in ["cards", "card"]:
            body_shape = slide.Shapes.AddTextbox(1, left, top, width, height)
            tf = body_shape.TextFrame
            tf.WordWrap = True
            tf.TextRange.Text = body_text
            tf.TextRange.Font.Size = 14
            created_elements.append(f"Text({len(body_text)} chars)")

        if not created_elements:
            return format_response(
                status="no_match",
                module="ppt_write",
                action="write",
                preview="No content provided (title, body, table, image, or cards required)",
                agent_directive="STOP_RETRY: Missing content parameters."
            )

        preview_str = f"Slide {slide_idx}: Added " + ", ".join(created_elements)
        return format_response(
            status="ok",
            module="ppt_write",
            action="write",
            preview=preview_str,
            agent_directive="VERIFIED: Content written to PowerPoint slide. Do not re-verify.",
            extra={"slide": slide_idx, "elements": created_elements}
        )

    except Exception as e:
        return format_response(
            status="error",
            module="ppt_write",
            action="write",
            preview=str(e),
            agent_directive=f"STOP_RETRY: PowerPoint write failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Advanced Write Micro Block (Cards & Image Support)")
    parser.add_argument("--target", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--slide", type=int, help="대상 슬라이드 번호 (생략 시 마지막 슬라이드)")
    parser.add_argument("--title", type=str, help="슬라이드 제목")
    parser.add_argument("--text", "--body", type=str, help="본문 일반 텍스트 또는 마크다운 표")
    parser.add_argument("--data-file", type=str, help="표로 변환할 CSV 파일 경로")
    parser.add_argument("--image", type=str, help="삽입할 이미지 파일 경로 (PNG, JPG)")
    parser.add_argument("--component", choices=["cards", "table", "text", "title"], help="컴포넌트 유형")
    parser.add_argument("--cards", type=str, help="카드 데이터 ('제목1:설명1|제목2:설명2')")
    parser.add_argument("--theme", type=str, help="테마 프리셋(navy, slate, teal, emerald)")
    parser.add_argument("--left", type=float, default=None, help="왼쪽 여백(pt)")
    parser.add_argument("--top", type=float, default=None, help="위쪽 여백(pt, 생략 시 Smart Stacking 자동 계산)")
    parser.add_argument("--width", type=float, default=None, help="너비(pt)")
    parser.add_argument("--height", type=float, default=None, help="높이(pt, 생략 시 컴포넌트별 자동 최적화)")
    args = parser.parse_args()

    params = {
        "slide": args.slide,
        "title": args.title,
        "text": args.text,
        "data_file": args.data_file,
        "image": args.image,
        "component": args.component,
        "cards": args.cards,
        "theme": args.theme,
        "left": args.left,
        "top": args.top,
        "width": args.width,
        "height": args.height
    }

    with ppt_session(target=args.target, snapshot=True) as (app, prs):
        res = execute(app, prs, params)
        emit_response(res)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
