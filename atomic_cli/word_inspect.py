import sys
import os
import argparse
from typing import Dict, Any, List

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import word_session

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 Word 문서 상태를 초고속 진단합니다."""
    try:
        doc_name = doc.Name
        para_count = doc.Paragraphs.Count
        char_count = doc.Characters.Count
        words_count = doc.Words.Count
        table_count = doc.Tables.Count
        
        # 이미지 및 도형 수
        image_count = 0
        try:
            image_count = doc.InlineShapes.Count + doc.Shapes.Count
        except Exception:
            pass

        # 표별 요약 정보
        tables_summary = []
        for i in range(1, min(table_count + 1, 10)):  # 최대 상위 10개 표 요약
            try:
                t = doc.Tables(i)
                tables_summary.append({
                    "table_index": i,
                    "rows": t.Rows.Count,
                    "cols": t.Columns.Count
                })
            except Exception:
                pass

        # 상위 3개 단락 미리보기
        preview_paras = []
        for i in range(1, min(para_count + 1, 4)):
            try:
                p_text = doc.Paragraphs(i).Range.Text.strip()
                if p_text:
                    preview_paras.append(p_text[:60])
            except Exception:
                pass

        # 열려 있는 전체 Word 문서 목록 조회
        open_docs = []
        try:
            from _com_guard import get_all_running_word_documents
            all_running = get_all_running_word_documents()
            for item in all_running:
                open_docs.append({
                    "name": item["name"],
                    "path": item["path"],
                    "saved": item.get("saved", True),
                    "active": (item["name"] == doc_name)
                })
        except Exception:
            pass
        if not open_docs:
            open_docs = [{"name": doc_name, "path": getattr(doc, "FullName", ""), "active": True}]

        # 현재 커서 위치(일반 텍스트 문맥 또는 표 내부 위치) 및 선택 정보 추출
        cursor_info = {}
        try:
            sel = app.Selection
            if sel is not None:
                page_num = sel.Information(3) # wdActiveEndPageNumber
                line_num = sel.Information(10) # wdFirstCharacterLineNumber
                is_in_table = bool(sel.Information(12)) # wdWithInTable
                sel_text = sel.Text.strip() if sel.Text else ""

                curr_para_text = ""
                try:
                    curr_para_text = sel.Paragraphs(1).Range.Text.strip()[:100]
                except Exception:
                    pass

                table_loc = None
                if is_in_table:
                    try:
                        row_idx = sel.Information(13) # wdStartOfRangeRowNumber
                        col_idx = sel.Information(14) # wdStartOfRangeColumnNumber
                        cell_text = ""
                        try:
                            cell_text = sel.Cells(1).Range.Text.strip().replace("\r\x07", "").replace("\x07", "")
                        except Exception:
                            pass
                        table_loc = {
                            "row": row_idx,
                            "col": col_idx,
                            "cell_text": cell_text
                        }
                    except Exception:
                        pass

                cursor_info = {
                    "page": page_num,
                    "line": line_num,
                    "in_table": is_in_table,
                    "table_location": table_loc,
                    "selected_text": sel_text,
                    "context_paragraph": curr_para_text
                }
        except Exception as e:
            log_debug(f"Word cursor info error: {e}")

        open_doc_names = [d["name"] for d in open_docs]
        cursor_desc = f"표 {cursor_info['table_location']['row']}행{cursor_info['table_location']['col']}열" if (cursor_info.get("in_table") and cursor_info.get("table_location")) else f"본문 p.{cursor_info.get('page', 1)} L.{cursor_info.get('line', 1)}"
        summary_preview = (
            f"열린 문서: {len(open_docs)}개 ({', '.join(open_doc_names)}) | 활성: {doc_name} (커서: {cursor_desc}) | "
            f"단락: {para_count}개 | 글자: {char_count}자 | 표: {table_count}개 | 이미지: {image_count}개"
        )

        return format_response(
            status="ok",
            module="word_inspect",
            action="inspect_document",
            preview=summary_preview,
            agent_directive="VERIFIED: Word document inspection complete.",
            extra={
                "document": doc_name,
                "open_documents": open_docs,
                "total_open_documents": len(open_docs),
                "cursor": cursor_info,
                "paragraphs_count": para_count,
                "characters_count": char_count,
                "words_count": words_count,
                "tables_count": table_count,
                "images_count": image_count,
                "tables_summary": tables_summary,
                "preview_paragraphs": preview_paras
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="word_inspect",
            action="inspect",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Word inspection failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Word Inspection Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 docx 파일 경로")
    parser.add_argument("--list-docs", "--all", dest="list_docs", action="store_true", help="실행 중인 모든 Word 문서 목록만 고속 조회")
    args = parser.parse_args()

    if args.list_docs:
        from _com_guard import get_all_running_word_documents
        all_running = get_all_running_word_documents()
        docs_summary = []
        for item in all_running:
            docs_summary.append({
                "name": item["name"],
                "path": item["path"],
                "saved": item.get("saved", True),
                "active": item.get("is_active", False)
            })

        names_preview = ", ".join([f"{d['name']}{' (Active)' if d['active'] else ''}" for d in docs_summary])
        res = format_response(
            status="ok",
            module="word_inspect",
            action="list_documents",
            preview=f"총 {len(docs_summary)}개의 열린 Word 문서 감지: [{names_preview}]",
            agent_directive="VERIFIED: Running documents enumerated across Word instances.",
            extra={
                "total_count": len(docs_summary),
                "documents": docs_summary
            }
        )
        emit_response(res)
        return

    with word_session(target=args.target) as (app, doc):
        res = execute(app, doc, {})
        emit_response(res)

if __name__ == "__main__":
    main()
