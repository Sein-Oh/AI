import sys
import os
import zipfile
import argparse
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_data_dir
from _cache import get_file_cache, save_file_cache
from _com_guard import ppt_session

def resolve_target_file(target: str) -> str:
    if not target or target.strip().lower() == "active":
        return "active"
    if os.path.isabs(target) and os.path.exists(target):
        return target
    data_candidate = os.path.join(get_data_dir(), target)
    if os.path.exists(data_candidate):
        return os.path.abspath(data_candidate)
    cwd_candidate = os.path.abspath(target)
    if os.path.exists(cwd_candidate):
        return cwd_candidate
    return target

def extract_texts_from_shape(shape) -> List[str]:
    """도형(일반, 표, 그룹화 도형) 내부의 모든 텍스트를 재귀적으로 추출합니다."""
    texts = []
    # 1. 그룹화된 도형 (msoGroup = 6) 재귀 탐색
    try:
        if getattr(shape, "Type", None) == 6 or hasattr(shape, "GroupItems"):
            for sub_shape in shape.GroupItems:
                texts.extend(extract_texts_from_shape(sub_shape))
            return texts
    except Exception:
        pass

    # 2. 일반 텍스트 상자
    try:
        if shape.HasTextFrame and shape.TextFrame.HasText:
            txt = shape.TextFrame.TextRange.Text.strip()
            if txt:
                texts.append(txt)
    except Exception:
        pass

    # 3. 표(Table) 내부 셀 (표 행 단위로 파이프 연결하여 깔끔한 표 구조 제공)
    try:
        if shape.HasTable:
            tbl = shape.Table
            for r in range(1, tbl.Rows.Count + 1):
                row_cells = []
                for c in range(1, tbl.Columns.Count + 1):
                    cell_tf = tbl.Cell(r, c).Shape.TextFrame
                    if cell_tf.HasText:
                        txt = cell_tf.TextRange.Text.strip()
                        if txt:
                            row_cells.append(txt)
                if row_cells:
                    texts.append(" | ".join(row_cells))
            return texts
    except Exception:
        pass

    return texts

def extract_pptx_xml(abs_path: str) -> Dict[str, Any]:
    """PowerPoint PPTX 파일의 XML(ppt/slides/slide*.xml)을 직접 파싱하여 0.005초 만에 슬라이드별 텍스트를 추출합니다."""
    items = []
    
    with zipfile.ZipFile(abs_path, 'r') as z:
        # 슬라이드 파일 식별 및 정렬 (slide1.xml, slide2.xml, ...)
        slide_files = [f for f in z.namelist() if f.startswith("ppt/slides/slide") and f.endswith(".xml")]
        # 번호순 정렬
        def get_slide_num(f_name):
            base = os.path.basename(f_name)
            num_part = "".join(ch for ch in base if ch.isdigit())
            return int(num_part) if num_part else 0
        slide_files.sort(key=get_slide_num)

        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}

        for s_idx, sf in enumerate(slide_files, start=1):
            xml_content = z.read(sf)
            root = ET.fromstring(xml_content)
            
            # 슬라이드 내 모든 텍스트 노드(<a:t>) 수집
            slide_texts = []
            for t_node in root.findall(".//a:t", ns):
                if t_node.text and t_node.text.strip():
                    slide_texts.append(t_node.text.strip())

            s_text = "\n\n".join(slide_texts)
            if s_text:
                items.append({
                    "loc": f"Slide {s_idx}",
                    "slide": s_idx,
                    "text": s_text,
                    "tokens_count": len(slide_texts)
                })

    full_text = "\n\n".join(f"[{it['loc']}] {it['text']}" for it in items)
    return {
        "items": items,
        "total_slides": len(items),
        "full_text": full_text
    }

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """PowerPoint 프레젠테이션의 슬라이드별 텍스트와 위치 메타데이터를 고속 조회(캐시 지원)합니다."""
    target = params.get("target") or params.get("file") or "active"
    slide_arg = params.get("slide")
    search_kw = (params.get("search") or "").strip()
    fmt = (params.get("format") or "text").lower()

    resolved_target = resolve_target_file(target)
    is_active = (resolved_target == "active")

    try:
        # A. 파일 대상이고 캐시가 존재하는 경우
        if not is_active and os.path.exists(resolved_target):
            abs_path = os.path.abspath(resolved_target)
            file_name = os.path.basename(abs_path)
            sub_key = f"{slide_arg}_{search_kw}_{fmt}"

            cached_data = get_file_cache(abs_path, sub_key=sub_key)
            if cached_data:
                return format_response(
                    status="ok",
                    module="ppt_read",
                    action="read_cached",
                    preview=cached_data.get("preview", f"Read PPT from cache: {file_name}"),
                    agent_directive="VERIFIED: PowerPoint data retrieved from disk cache.",
                    extra=cached_data
                )

            # 초고속 XML 추출
            extracted = extract_pptx_xml(abs_path)
            items = extracted["items"]
            total_slides = extracted["total_slides"]
            total_chars = len(extracted["full_text"])

            # 특정 슬라이드만 요청된 경우
            if slide_arg is not None:
                s_num = int(slide_arg)
                filtered_items = [it for it in items if it.get("slide") == s_num]
                if not filtered_items:
                    return format_response(
                        status="no_match",
                        module="ppt_read",
                        action="read_slide",
                        preview=f"Slide {s_num} not found (Total slides: {total_slides})",
                        agent_directive="STOP_RETRY: Slide not found."
                    )
                items = filtered_items

            # 키워드 검색
            search_matches = []
            if search_kw:
                for it in items:
                    if search_kw in it["text"]:
                        search_matches.append({
                            "loc": it["loc"],
                            "text": it["text"]
                        })

                if not search_matches:
                    return format_response(
                        status="no_match",
                        module="ppt_read",
                        action="search",
                        preview=f"Keyword '{search_kw}' not found in {file_name}",
                        agent_directive="STOP_RETRY: Keyword not found in presentation."
                    )

            if fmt == "summary":
                preview_msg = f"PPT: {file_name} | 슬라이드 {total_slides}장 | 총 글자: {total_chars}자"
                payload_data = {"total_slides": total_slides, "total_characters": total_chars}
            elif fmt == "items":
                preview_msg = f"PPT: {file_name} ({len(items)} slides, {total_chars} chars)"
                payload_data = items
            else:
                preview_msg = f"PPT: {file_name} ({len(items)} slides, {total_chars} chars)"
                payload_data = extracted["full_text"]

            result_payload = {
                "file": file_name,
                "path": abs_path,
                "file_type": "ppt",
                "total_slides": total_slides,
                "total_characters": total_chars,
                "preview": preview_msg,
                "items": items,
                "data": payload_data,
                "search_matches": search_matches if search_kw else None
            }

            save_file_cache(abs_path, result_payload, sub_key=sub_key)

            return format_response(
                status="ok",
                module="ppt_read",
                action="read_ppt",
                preview=preview_msg,
                agent_directive="VERIFIED: PowerPoint presentation read successfully.",
                extra=result_payload
            )

        # B. 활성 PowerPoint 창 조회 (COM 경유)
        items = []
        notes_list = []
        with ppt_session(target=resolved_target) as (app, prs):
            prs_name = prs.Name
            # 현재 활성 슬라이드 인덱스 저장하여 조회 후 복원
            try:
                original_slide_idx = app.ActiveWindow.View.Slide.SlideIndex
            except Exception:
                original_slide_idx = None
            slide_count = prs.Slides.Count
            for i in range(1, slide_count + 1):
                slide = prs.Slides(i)
                texts = []
                for shape in slide.Shapes:
                    texts.extend(extract_texts_from_shape(shape))

                s_text = "\n\n".join(t for t in texts if t)
                if s_text:
                    items.append({
                        "loc": f"Slide {i}",
                        "slide": i,
                        "text": s_text
                    })

                # 발표자 노트(Speaker Notes) 추출
                if params.get("notes"):
                    try:
                        notes_shape = slide.NotesPage.Shapes.Placeholders.Item(2)
                        if notes_shape.HasTextFrame and notes_shape.TextFrame.HasText:
                            note_text = notes_shape.TextFrame.TextRange.Text.strip()
                            if note_text:
                                notes_list.append({
                                    "slide": i,
                                    "loc": f"Slide {i} (Notes)",
                                    "notes": note_text
                                })
                    except Exception:
                        pass

            full_text = "\n\n".join(f"[{it['loc']}] {it['text']}" for it in items)
            preview_msg = f"PPT (Active): {prs_name} ({len(items)} slides, {len(full_text)} chars)"
            if notes_list:
                preview_msg += f" | Notes: {len(notes_list)} slides"

            # 조회 후 원래 활성 슬라이드로 복원
            try:
                if original_slide_idx is not None:
                    app.ActiveWindow.View.GotoSlide(original_slide_idx)
            except Exception:
                pass

            return format_response(
                status="ok",
                module="ppt_read",
                action="read_ppt_active",
                preview=preview_msg,
                agent_directive="VERIFIED: Active PowerPoint presentation read successfully.",
                extra={
                    "presentation": prs_name,
                    "file_type": "ppt",
                    "total_slides": len(items),
                    "notes": notes_list,
                    "items": items,
                    "data": full_text
                }
            )

    except Exception as e:
        return format_response(
            status="error",
            module="ppt_read",
            action="read",
            preview=str(e),
            agent_directive=f"STOP_RETRY: PowerPoint read failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Read Micro Block (XML/COM Fast Parse & Cache)")
    parser.add_argument("--target", "--file", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--slide", type=int, help="특정 슬라이드 번호 (1-based)")
    parser.add_argument("--search", type=str, help="특정 단어 검색")
    parser.add_argument("--format", choices=["text", "items", "summary"], default="text", help="출력 형식")
    parser.add_argument("--notes", action="store_true", help="슬라이드별 발표자 노트(Speaker Notes) 추출")
    args = parser.parse_args()

    params = {
        "target": args.target,
        "slide": args.slide,
        "search": args.search,
        "format": args.format,
        "notes": args.notes
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
