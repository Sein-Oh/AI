import sys
import os
import argparse
from typing import Dict, Any, List

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, run_session_tool
from _com_guard import ppt_session

def inspect_shape_recursive(shape):
    """도형(그룹 포함)의 문자수, 표수, 차트수, 그림수를 재귀적으로 계산합니다."""
    chars = 0
    tables = 0
    charts = 0
    pics = 0
    title = ""

    # 1. 그룹화된 도형 (msoGroup = 6)
    try:
        if getattr(shape, "Type", None) == 6 or hasattr(shape, "GroupItems"):
            for sub in shape.GroupItems:
                c, t, ch, p, ttl = inspect_shape_recursive(sub)
                chars += c
                tables += t
                charts += ch
                pics += p
                if not title and ttl:
                    title = ttl
            return chars, tables, charts, pics, title
    except Exception:
        pass

    # 2. 일반 텍스트
    try:
        if shape.HasTextFrame and shape.TextFrame.HasText:
            txt = shape.TextFrame.TextRange.Text.strip()
            chars += len(txt)
            if not title and len(txt) > 0:
                title = txt[:40]
    except Exception:
        pass

    # 3. 표
    try:
        if shape.HasTable:
            tables += 1
            tbl = shape.Table
            for r in range(1, tbl.Rows.Count + 1):
                for c in range(1, tbl.Columns.Count + 1):
                    cell_tf = tbl.Cell(r, c).Shape.TextFrame
                    if cell_tf.HasText:
                        chars += len(cell_tf.TextRange.Text.strip())
    except Exception:
        pass

    # 4. 차트 및 그림
    try:
        if getattr(shape, "Type", None) == 3 or getattr(shape, "HasChart", False):
            charts += 1
        elif getattr(shape, "Type", None) in [11, 13]:
            pics += 1
    except Exception:
        pass

    return chars, tables, charts, pics, title

def execute(app, prs, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 PowerPoint 프레젠테이션 상태를 초고속 진단합니다."""
    try:
        # 활성 슬라이드 인덱스 저장
        original_slide_idx = None
        try:
            original_slide_idx = app.ActiveWindow.View.Slide.SlideIndex
        except Exception:
            pass

        prs_name = prs.Name
        total_slides = prs.Slides.Count
        slides_summary = []
        total_chars = 0
        total_tables = 0
        total_charts = 0
        total_pictures = 0

        for i in range(1, total_slides + 1):
            slide = prs.Slides(i)
            shape_count = slide.Shapes.Count
            slide_chars = 0
            slide_tables = 0
            slide_charts = 0
            slide_pictures = 0
            title_text = ""

            for shape in slide.Shapes:
                c, t, ch, p, ttl = inspect_shape_recursive(shape)
                slide_chars += c
                slide_tables += t
                slide_charts += ch
                slide_pictures += p
                if not title_text and ttl:
                    title_text = ttl

            total_chars += slide_chars
            total_tables += slide_tables
            total_charts += slide_charts
            total_pictures += slide_pictures

            slides_summary.append({
                "slide_index": i,
                "title": title_text or "(제목 없음)",
                "shapes_count": shape_count,
                "tables_count": slide_tables,
                "charts_count": slide_charts,
                "pictures_count": slide_pictures,
                "characters_count": slide_chars
            })

        # 열려 있는 전체 PowerPoint 프레젠테이션 목록 조회
        open_prs_list = []
        try:
            from _com_guard import get_all_running_ppt_presentations
            all_running = get_all_running_ppt_presentations()
            for item in all_running:
                open_prs_list.append({
                    "name": item["name"],
                    "path": item["path"],
                    "saved": item.get("saved", True),
                    "slides_count": item.get("slides_count", 0),
                    "active": (item["name"] == prs_name)
                })
        except Exception:
            pass
        if not open_prs_list:
            open_prs_list = [{"name": prs_name, "path": getattr(prs, "FullName", ""), "slides_count": total_slides, "active": True}]

        # 활성 창 뷰 슬라이드 및 선택/커서 위치 정밀 추출
        active_slide_index = 1
        selection_info = {}
        try:
            win = app.ActiveWindow
            if win is not None:
                try:
                    active_slide_index = win.View.Slide.SlideIndex
                except Exception:
                    pass

                sel = win.Selection
                sel_type = getattr(sel, "Type", 0)  # 0=None, 1=Slide, 2=Shape, 3=Text
                sel_type_name = "none"
                selected_shape_name = ""
                selected_text = ""
                text_start = None
                text_length = None

                if sel_type == 1:
                    sel_type_name = "slide"
                    try:
                        active_slide_index = sel.SlideRange(1).SlideIndex
                    except Exception:
                        pass
                elif sel_type == 2:
                    sel_type_name = "shape"
                    try:
                        selected_shape_name = sel.ShapeRange(1).Name
                    except Exception:
                        pass
                elif sel_type == 3:
                    sel_type_name = "text"
                    try:
                        selected_shape_name = sel.ShapeRange(1).Name
                    except Exception:
                        pass
                    try:
                        tr = sel.TextRange
                        selected_text = tr.Text.strip() if tr.Text else ""
                        text_start = tr.Start
                        text_length = tr.Length
                    except Exception:
                        pass

                selection_info = {
                    "active_slide": active_slide_index,
                    "selection_type": sel_type_name,
                    "shape_name": selected_shape_name,
                    "selected_text": selected_text,
                    "cursor_start": text_start,
                    "cursor_length": text_length
                }
        except Exception as e:
            log_debug(f"PPT selection info error: {e}")

        open_prs_names = [p["name"] for p in open_prs_list]
        sel_desc = f"슬라이드 {active_slide_index}번"
        if selection_info.get("selection_type") == "text":
            sel_desc += f" (텍스트 커서: {selection_info.get('shape_name')})"
        elif selection_info.get("selection_type") == "shape":
            sel_desc += f" (도형 선택: {selection_info.get('shape_name')})"

        summary_preview = (
            f"열린 문서: {len(open_prs_list)}개 ({', '.join(open_prs_names)}) | 활성: {prs_name} [{sel_desc}] | "
            f"슬라이드: {total_slides}장 | 차트: {total_charts}개 | 이미지: {total_pictures}개 | 표: {total_tables}개"
        )

        # 활성 슬라이드 복원
        try:
            if original_slide_idx is not None:
                app.ActiveWindow.View.GotoSlide(original_slide_idx)
        except Exception:
            pass

        return format_response(
            status="ok",
            module="ppt_inspect",
            action="inspect_presentation",
            preview=summary_preview,
            agent_directive="VERIFIED: PowerPoint inspection complete.",
            extra={
                "presentation": prs_name,
                "open_presentations": open_prs_list,
                "total_open_presentations": len(open_prs_list),
                "active_slide": active_slide_index,
                "selection": selection_info,
                "total_slides": total_slides,
                "total_characters": total_chars,
                "total_tables": total_tables,
                "total_charts": total_charts,
                "total_pictures": total_pictures,
                "slides_summary": slides_summary
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="ppt_inspect",
            action="inspect",
            preview=str(e),
            agent_directive=f"STOP_RETRY: PowerPoint inspection failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Inspection Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--list-presentations", "--all", dest="list_presentations", action="store_true", help="실행 중인 모든 PowerPoint 프레젠테이션 목록만 고속 조회")
    args = parser.parse_args()

    if args.list_presentations:
        from _com_guard import get_all_running_ppt_presentations
        all_running = get_all_running_ppt_presentations()
        prs_summary = []
        for item in all_running:
            prs_summary.append({
                "name": item["name"],
                "path": item["path"],
                "saved": item.get("saved", True),
                "slides_count": item.get("slides_count", 0),
                "active": item.get("is_active", False)
            })

        names_preview = ", ".join([f"{p['name']}{' (Active)' if p['active'] else ''}" for p in prs_summary])
        res = format_response(
            status="ok",
            module="ppt_inspect",
            action="list_presentations",
            preview=f"총 {len(prs_summary)}개의 열린 PowerPoint 프레젠테이션 감지: [{names_preview}]",
            agent_directive="VERIFIED: Running presentations enumerated across PowerPoint instances.",
            extra={
                "total_count": len(prs_summary),
                "presentations": prs_summary
            }
        )
        emit_response(res)
        return

    run_session_tool("ppt_inspect", "inspect",
                     lambda: ppt_session(target=args.target),
                     lambda app, prs: execute(app, prs, {}))

if __name__ == "__main__":
    main()
