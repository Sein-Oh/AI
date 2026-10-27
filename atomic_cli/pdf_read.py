import sys
import os
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_data_dir
from _cache import get_file_cache, save_file_cache

def resolve_target_file(target: str) -> str:
    """대상 파일 경로를 해석하며, 상대 경로 시 data_dir 또는 CWD에서 탐색합니다."""
    if not target:
        raise ValueError("대상 파일 경로(target)가 필요합니다.")
    if os.path.isabs(target):
        if os.path.exists(target):
            return target
    # 1. data_dir 탐색
    data_candidate = os.path.join(get_data_dir(), target)
    if os.path.exists(data_candidate):
        return os.path.abspath(data_candidate)
    # 2. CWD 탐색
    cwd_candidate = os.path.abspath(target)
    if os.path.exists(cwd_candidate):
        return cwd_candidate
    raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {target}")

def extract_via_word_com(abs_path: str) -> Dict[str, Any]:
    """사내 DRM(문서보안) 암호화 PDF를 인증 앱인 MS Word COM을 통해 실시간 복호화하여 추출합니다."""
    log_debug(f"사내 DRM 감지: MS Word COM 백그라운드 복호화 추출 시도: {abs_path}")
    try:
        import win32com.client
        import pythoncom
    except ImportError:
        raise RuntimeError("pywin32가 설치되어 있지 않아 Word DRM 복호화를 실행할 수 없습니다.")

    word = None
    doc = None
    try:
        # 백그라운드 독립 Word 인스턴스 기동
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0

        # Word의 내장 PDF 리플로우 변환기를 통한 DRM 자동 인증 복호화 열기
        doc = word.Documents.Open(
            FileName=abs_path,
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False
        )

        raw_text = doc.Content.Text
        # 제어문자 정리
        cleaned_text = raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n\n")
        cleaned_text = "".join(ch for ch in cleaned_text if ch >= " " or ch in "\n\t").strip()

        # 페이지 단위 구분선 기준 또는 2000자 블록으로 분할
        pages = [p.strip() for p in cleaned_text.split("\n\n") if p.strip()]
        if not pages:
            pages = [cleaned_text]

        metadata = {
            "title": os.path.basename(abs_path),
            "backend": "word_com_drm_decryptor"
        }
        return {"pages": pages, "metadata": metadata}

    except Exception as e:
        raise RuntimeError(f"Word COM DRM 복호화 추출 실패: {e}")
    finally:
        if doc:
            try:
                doc.Close(False)
            except Exception:
                pass
        if word:
            try:
                word.Quit()
            except Exception:
                pass

def extract_pdf_data(abs_path: str) -> Dict[str, Any]:
    """PDF 파일에서 메타데이터와 페이지별 텍스트를 초고속 추출합니다 (pymupdf 우선, pypdf, Word DRM 폴백)."""
    pages_text: List[str] = []
    metadata: Dict[str, Any] = {}

    # 1. pymupdf 시도 (초고속 C기반 엔진)
    try:
        import pymupdf  # or fitz
        doc = pymupdf.open(abs_path)
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", "")
        }
        for page in doc:
            pages_text.append(page.get_text())
        doc.close()
        # 내용이 정상 평문인지 점검 (DRM 파일이면 추출 텍스트가 비어있거나 깨짐)
        if pages_text and any(len(p.strip()) > 0 for p in pages_text):
            return {"pages": pages_text, "metadata": metadata}
    except Exception as e_mupdf:
        log_debug(f"pymupdf 추출 실패 또는 미설치, pypdf 시도: {e_mupdf}")

    # 2. pypdf 폴백
    try:
        import pypdf
        reader = pypdf.PdfReader(abs_path)
        if reader.metadata:
            metadata = {
                "title": getattr(reader.metadata, "title", "") or "",
                "author": getattr(reader.metadata, "author", "") or ""
            }
        for page in reader.pages:
            pages_text.append(page.extract_text() or "")
        if pages_text and any(len(p.strip()) > 0 for p in pages_text):
            return {"pages": pages_text, "metadata": metadata}
    except Exception as e_pypdf:
        log_debug(f"pypdf 추출 실패 또는 DRM 감지: {e_pypdf}")

    # 3. 사내 DRM 복호화 Word COM 폴백
    return extract_via_word_com(abs_path)

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 주입받은 인자로 PDF 텍스트 및 정보를 고속 조회(캐시 지원)합니다."""
    target = params.get("target") or params.get("file")
    page_arg = params.get("page")
    search_kw = (params.get("search") or "").strip()
    fmt = (params.get("format") or "text").lower()

    if not target:
        return format_response(
            status="error",
            module="pdf_read",
            action="read",
            preview="target parameter is required",
            agent_directive="STOP_RETRY: Missing target file path."
        )

    try:
        abs_path = resolve_target_file(target)
        file_name = os.path.basename(abs_path)
        sub_key = f"{page_arg}_{search_kw}_{fmt}"

        # 1. mtime 기반 디스크 캐시 검사 (0.001s)
        cached_data = get_file_cache(abs_path, sub_key=sub_key)
        if cached_data:
            return format_response(
                status="ok",
                module="pdf_read",
                action="read_cached",
                preview=cached_data.get("preview", f"Read PDF from cache: {file_name}"),
                agent_directive="VERIFIED: PDF data retrieved from disk cache.",
                extra=cached_data
            )

        # 2. 캐시 미스 시 파싱 수행
        extracted = extract_pdf_data(abs_path)
        all_pages = extracted["pages"]
        total_pages = len(all_pages)

        # 특정 페이지만 요청된 경우
        target_page_idx = None
        if page_arg is not None:
            target_page_idx = int(page_arg)
            if target_page_idx < 1 or target_page_idx > total_pages:
                return format_response(
                    status="no_match",
                    module="pdf_read",
                    action="read_page",
                    preview=f"Requested page {target_page_idx} out of range (Total: {total_pages})",
                    agent_directive="STOP_RETRY: Page index out of range."
                )

        # 검색 키워드가 있는 경우
        search_matches = []
        if search_kw:
            for p_num, p_text in enumerate(all_pages, start=1):
                if search_kw in p_text:
                    # 매칭된 위치 전후 스니펫 수집
                    start_idx = max(0, p_text.find(search_kw) - 40)
                    end_idx = min(len(p_text), p_text.find(search_kw) + len(search_kw) + 60)
                    snippet = p_text[start_idx:end_idx].replace("\n", " ").strip()
                    search_matches.append({
                        "page": p_num,
                        "snippet": f"...{snippet}..."
                    })

            if not search_matches:
                return format_response(
                    status="no_match",
                    module="pdf_read",
                    action="search",
                    preview=f"Keyword '{search_kw}' not found in {file_name}",
                    agent_directive="STOP_RETRY: Keyword not found in PDF."
                )

        # 출력 포맷 결정
        total_chars = sum(len(p) for p in all_pages)
        if target_page_idx is not None:
            result_text = all_pages[target_page_idx - 1]
            preview_msg = f"PDF: {file_name} (Page {target_page_idx}/{total_pages}, {len(result_text)} chars)"
            payload_data = result_text
        elif fmt == "summary":
            preview_msg = f"PDF: {file_name} | {total_pages}페이지 | 총 글자: {total_chars}자"
            payload_data = {
                "total_pages": total_pages,
                "total_characters": total_chars,
                "metadata": extracted.get("metadata", {})
            }
        elif fmt == "pages":
            preview_msg = f"PDF: {file_name} ({total_pages} pages, {total_chars} chars)"
            payload_data = [{"page": i, "characters": len(p), "text": p} for i, p in enumerate(all_pages, start=1)]
        else:
            # 전체 텍스트 병합
            full_text = "\n\n--- [Page Separator] ---\n\n".join(all_pages)
            preview_msg = f"PDF: {file_name} ({total_pages} pages, {total_chars} chars)"
            payload_data = full_text

        items = [{"loc": f"Page {i}", "page": i, "text": p} for i, p in enumerate(all_pages, start=1)]

        result_payload = {
            "file": file_name,
            "path": abs_path,
            "file_type": "pdf",
            "total_pages": total_pages,
            "total_characters": total_chars,
            "preview": preview_msg,
            "items": items,
            "data": payload_data,
            "search_matches": search_matches if search_kw else None
        }

        # 3. 캐시 저장 (최근 2개 유지)
        save_file_cache(abs_path, result_payload, sub_key=sub_key)

        return format_response(
            status="ok",
            module="pdf_read",
            action="read_pdf",
            preview=preview_msg,
            agent_directive="VERIFIED: PDF read successfully.",
            extra=result_payload
        )

    except Exception as e:
        return format_response(
            status="error",
            module="pdf_read",
            action="read",
            preview=str(e),
            agent_directive=f"STOP_RETRY: PDF read failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PDF Read Micro Block (High Performance & Cache)")
    parser.add_argument("--target", "--file", required=True, help="PDF 파일 경로 또는 data_dir 내 파일명")
    parser.add_argument("--page", type=int, help="특정 페이지만 읽기 (1-based)")
    parser.add_argument("--search", type=str, help="특정 단어 검색")
    parser.add_argument("--format", choices=["text", "pages", "summary"], default="text", help="출력 형식")
    args = parser.parse_args()

    params = {
        "target": args.target,
        "page": args.page,
        "search": args.search,
        "format": args.format
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
