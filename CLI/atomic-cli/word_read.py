import sys
import os
import re
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
from _com_guard import word_session

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

def is_heading_candidate(p_text: str, p_style: str = "") -> bool:
    """단락이 제목/소제목(Heading)인지 스타일 및 문맥 패턴으로 판별합니다."""
    if not p_text or len(p_text) > 80:
        return False

    style_lower = (p_style or "").lower()
    if any(h in style_lower for h in ["heading", "title", "제목", "헤딩", "개요"]):
        return True

    text_clean = p_text.strip()
    heading_patterns = [
        r"^\[.+\]$",                   # [소제목]
        r"^【.+】$",                  # 【서식】
        r"^[0-9]+[.\s]+.+",            # 1. 개요, 2. 추진 배경
        r"^[0-9]+-[0-9]+[.\s]+.+",     # 1-1. 세부 사항
        r"^[0-9]+\.[0-9]+[.\s]+.+",    # 1.1 개요
        r"^[IVXLCDM]+[.\s]+.+",        # I. 추진 배경
        r"^[가-힣][.\s)]+.+",          # 가. 추진 일정, 1) 세부 항목
        r"^제\s*[0-9]+\s*장.+",        # 제1장 총칙
    ]
    for pat in heading_patterns:
        if re.match(pat, text_clean):
            return True
    return False

def extract_docx_xml(abs_path: str) -> Dict[str, Any]:
    """Word DOCX 파일의 XML을 파싱하여 페이지 추정, 소제목(Heading) 계층, 표 헤더를 결합한 고도화된 색인 데이터를 생성합니다."""
    items = []
    paragraphs = []
    toc = []
    
    with zipfile.ZipFile(abs_path, 'r') as z:
        xml_content = z.read("word/document.xml")
        root = ET.fromstring(xml_content)
        
        # XML Namespace mapping
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        
        p_idx = 1
        t_idx = 1
        current_page = 1
        cumulative_chars = 0
        current_heading = ""
        CHARS_PER_PAGE_EST = 1200  # 표준 A4 1페이지 평균 조판 글자 수

        for body in root.findall(".//w:body", ns):
            for child in body:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

                # 1. 단락 (Paragraph)
                if tag == "p":
                    has_hard_page_break = False
                    if child.findall(".//w:br[@w:type='page']", ns) or child.findall(".//w:lastRenderedPageBreak", ns):
                        has_hard_page_break = True

                    p_style = ""
                    p_style_elem = child.find(".//w:pPr/w:pStyle", ns)
                    if p_style_elem is not None:
                        p_style = p_style_elem.get(f"{{{ns['w']}}}val") or p_style_elem.get("val") or ""

                    p_text = "".join(node.text or "" for node in child.findall(".//w:t", ns)).strip()
                    if not p_text:
                        if has_hard_page_break:
                            current_page += 1
                            cumulative_chars = 0
                        continue

                    if has_hard_page_break:
                        current_page += 1
                        cumulative_chars = 0
                    else:
                        cumulative_chars += len(p_text)
                        if cumulative_chars >= CHARS_PER_PAGE_EST:
                            current_page += 1
                            cumulative_chars = len(p_text)

                    is_h = is_heading_candidate(p_text, p_style)
                    if is_h:
                        current_heading = p_text
                        toc.append({"title": p_text, "page": current_page, "para": p_idx})
                        loc_label = f"Page {current_page} > [Heading: {p_text}]"
                    else:
                        if current_heading:
                            loc_label = f"Page {current_page} > [{current_heading}] (Para {p_idx})"
                        else:
                            loc_label = f"Page {current_page} (Para {p_idx})"

                    paragraphs.append(p_text)
                    items.append({
                        "loc": loc_label,
                        "page": current_page,
                        "para": p_idx,
                        "heading": current_heading,
                        "is_heading": is_h,
                        "type": "paragraph",
                        "text": p_text
                    })
                    p_idx += 1

                # 2. 표 (Table)
                elif tag == "tbl":
                    rows = child.findall(".//w:tr", ns)
                    headers = []

                    for r_num, row in enumerate(rows, start=1):
                        cells = row.findall(".//w:tc", ns)
                        row_cell_texts = []
                        for c_num, cell in enumerate(cells, start=1):
                            cell_text = "".join(node.text or "" for node in cell.findall(".//w:t", ns)).strip()
                            row_cell_texts.append(cell_text)

                        # 첫 행은 표의 헤더 컬럼명으로 활용
                        if r_num == 1:
                            headers = row_cell_texts
                            for c_num, cell_text in enumerate(row_cell_texts, start=1):
                                if cell_text:
                                    loc_label = f"Page {current_page} > [Table {t_idx} 헤더: {cell_text}]"
                                    items.append({
                                        "loc": loc_label,
                                        "page": current_page,
                                        "table": t_idx,
                                        "row": 1,
                                        "col": c_num,
                                        "heading": current_heading,
                                        "column_name": cell_text,
                                        "type": "table_header",
                                        "text": cell_text
                                    })
                        else:
                            for c_num, cell_text in enumerate(row_cell_texts, start=1):
                                if cell_text:
                                    col_name = headers[c_num - 1] if c_num - 1 < len(headers) and headers[c_num - 1] else f"Col {c_num}"
                                    loc_label = f"Page {current_page} > [Table {t_idx}: {col_name}]"
                                    items.append({
                                        "loc": loc_label,
                                        "page": current_page,
                                        "table": t_idx,
                                        "row": r_num,
                                        "col": c_num,
                                        "heading": current_heading,
                                        "column_name": col_name,
                                        "type": "table_cell",
                                        "text": cell_text
                                    })
                    t_idx += 1

    full_text = "\n".join(p["text"] for p in items)
    return {
        "items": items,
        "paragraphs": paragraphs,
        "toc": toc,
        "total_pages": current_page,
        "total_paragraphs": len(paragraphs),
        "total_items": len(items),
        "full_text": full_text
    }

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """Word 문서의 텍스트와 강화된 페이지/소제목 위치 메타데이터를 고속 조회(캐시 지원)합니다."""
    target = params.get("target") or params.get("file") or "active"
    search_kw = (params.get("search") or "").strip()
    fmt = (params.get("format") or "text").lower()

    resolved_target = resolve_target_file(target)
    is_active = (resolved_target == "active")

    try:
        # A. 파일 대상이고 캐시가 존재하는 경우
        if not is_active and os.path.exists(resolved_target):
            abs_path = os.path.abspath(resolved_target)
            file_name = os.path.basename(abs_path)
            sub_key = f"{search_kw}_{fmt}"

            cached_data = get_file_cache(abs_path, sub_key=sub_key)
            if cached_data:
                return format_response(
                    status="ok",
                    module="word_read",
                    action="read_cached",
                    preview=cached_data.get("preview", f"Read Word from cache: {file_name}"),
                    agent_directive="VERIFIED: Word data retrieved from disk cache.",
                    extra=cached_data
                )

            # 초고속 XML 추출 및 페이지/소제목 인덱싱
            extracted = extract_docx_xml(abs_path)
            items = extracted["items"]
            total_chars = len(extracted["full_text"])

            search_matches = []
            if search_kw:
                for item in items:
                    if search_kw in item["text"]:
                        search_matches.append({
                            "loc": item["loc"],
                            "page": item.get("page"),
                            "heading": item.get("heading"),
                            "text": item["text"]
                        })

                if not search_matches:
                    return format_response(
                        status="no_match",
                        module="word_read",
                        action="search",
                        preview=f"Keyword '{search_kw}' not found in {file_name}",
                        agent_directive="STOP_RETRY: Keyword not found in Word document."
                    )

            if fmt == "summary":
                preview_msg = f"Word: {file_name} | {extracted['total_pages']}페이지 | 소제목 {len(extracted['toc'])}개 | 총 {total_chars}자"
                payload_data = {
                    "total_pages": extracted["total_pages"],
                    "total_items": len(items),
                    "toc": extracted["toc"],
                    "total_characters": total_chars
                }
            elif fmt == "items":
                preview_msg = f"Word: {file_name} ({extracted['total_pages']} pages, {len(items)} items, {total_chars} chars)"
                payload_data = items
            else:
                preview_msg = f"Word: {file_name} ({extracted['total_pages']} pages, {len(items)} items, {total_chars} chars)"
                payload_data = extracted["full_text"]

            result_payload = {
                "file": file_name,
                "path": abs_path,
                "file_type": "word",
                "total_pages": extracted["total_pages"],
                "total_items": len(items),
                "total_characters": total_chars,
                "toc": extracted["toc"],
                "preview": preview_msg,
                "items": items,
                "data": payload_data,
                "search_matches": search_matches if search_kw else None
            }

            save_file_cache(abs_path, result_payload, sub_key=sub_key)

            return format_response(
                status="ok",
                module="word_read",
                action="read_word",
                preview=preview_msg,
                agent_directive="VERIFIED: Word document read successfully.",
                extra=result_payload
            )

        # B. 활성 Word 창 조회 (COM 경유 - 실제 조판 페이지 wdActiveEndPageNumber 추출)
        items = []
        toc = []
        comments_list = []
        revisions_list = []
        with word_session(target=resolved_target) as (app, doc):
            doc_name = doc.Name
            para_count = doc.Paragraphs.Count
            current_heading = ""
            max_page = 1

            for i in range(1, para_count + 1):
                p_range = doc.Paragraphs(i).Range
                p_text = p_range.Text.strip()
                if not p_text:
                    continue

                try:
                    # Word COM 실제 물리 렌더링 페이지 번호 추출 (wdActiveEndPageNumber = 3)
                    page_num = p_range.Information(3)
                    if page_num > max_page:
                        max_page = page_num
                except Exception:
                    page_num = 1

                p_style = ""
                try:
                    p_style = str(p_range.Style.NameLocal)
                except Exception:
                    pass

                is_h = is_heading_candidate(p_text, p_style)
                if is_h:
                    current_heading = p_text
                    toc.append({"title": p_text, "page": page_num, "para": i})
                    loc_label = f"Page {page_num} > [Heading: {p_text}]"
                else:
                    if current_heading:
                        loc_label = f"Page {page_num} > [{current_heading}] (Para {i})"
                    else:
                        loc_label = f"Page {page_num} (Para {i})"

                items.append({
                    "loc": loc_label,
                    "page": page_num,
                    "para": i,
                    "heading": current_heading,
                    "is_heading": is_h,
                    "type": "paragraph",
                    "text": p_text
                })

            # 검토 메모(Comments) 추출 옵션
            if params.get("comments") and hasattr(doc, "Comments"):
                try:
                    for c_idx in range(1, doc.Comments.Count + 1):
                        c = doc.Comments(c_idx)
                        comments_list.append({
                            "author": getattr(c, "Author", "Unknown"),
                            "date": str(getattr(c, "Date", "")),
                            "scope": getattr(c.Scope, "Text", "").strip(),
                            "text": getattr(c.Range, "Text", "").strip()
                        })
                except Exception as e_c:
                    log_debug(f"Comments extraction error: {e_c}")

            # 변경 내용 추적(Revisions) 추출 옵션
            if params.get("revisions") and hasattr(doc, "Revisions"):
                try:
                    for r_idx in range(1, doc.Revisions.Count + 1):
                        r = doc.Revisions(r_idx)
                        r_type = "insert" if r.Type == 1 else ("delete" if r.Type == 2 else "other")
                        revisions_list.append({
                            "type": r_type,
                            "author": getattr(r, "Author", "Unknown"),
                            "date": str(getattr(r, "Date", "")),
                            "text": getattr(r.Range, "Text", "").strip()
                        })
                except Exception as e_r:
                    log_debug(f"Revisions extraction error: {e_r}")

            full_text = "\n".join(it["text"] for it in items)
            preview_msg = f"Word (Active): {doc_name} ({max_page} pages, {len(items)} paras, {len(full_text)} chars)"
            if comments_list:
                preview_msg += f" | Comments: {len(comments_list)}"
            if revisions_list:
                preview_msg += f" | Revisions: {len(revisions_list)}"

            return format_response(
                status="ok",
                module="word_read",
                action="read_word_active",
                preview=preview_msg,
                agent_directive="VERIFIED: Active Word document read successfully.",
                extra={
                    "document": doc_name,
                    "file_type": "word",
                    "total_pages": max_page,
                    "total_items": len(items),
                    "toc": toc,
                    "comments": comments_list,
                    "revisions": revisions_list,
                    "items": items,
                    "data": full_text
                }
            )

    except Exception as e:
        return format_response(
            status="error",
            module="word_read",
            action="read",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Word read failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Enhanced Word Read Micro Block (Page & Heading Indexing)")
    parser.add_argument("--target", "--file", default="active", help="active 또는 docx 파일 경로")
    parser.add_argument("--search", type=str, help="특정 단어 검색")
    parser.add_argument("--format", choices=["text", "items", "summary"], default="text", help="출력 형식")
    parser.add_argument("--comments", action="store_true", help="Word 문서 내 검토 메모(Comments) 추출")
    parser.add_argument("--revisions", action="store_true", help="Word 문서 내 변경 내용 추적(Track Changes) 내역 추출")
    args = parser.parse_args()

    params = {
        "target": args.target,
        "search": args.search,
        "format": args.format,
        "comments": args.comments,
        "revisions": args.revisions
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
