import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_data_dir
from _com_guard import word_session

# Word WdSaveFormat 상수
WD_FORMAT_PDF = 17
WD_FORMAT_DOCX = 16

def resolve_output_path(file_path: str, default_ext: str = ".pdf") -> str:
    """출력 경로를 해석하며 파일명만 기입된 경우 data_dir 하위로 매핑합니다."""
    if not file_path:
        raise ValueError("출력 파일명(output_file)이 필요합니다.")
    if not os.path.splitext(file_path)[1]:
        file_path += default_ext
    if os.path.isabs(file_path):
        out_path = file_path
    else:
        out_path = os.path.join(get_data_dir(), file_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    return os.path.abspath(out_path)

def _is_pdf_feature_missing(err: Exception) -> bool:
    """PDF 내보내기 추가 기능 미설치 오류인지 판별합니다.
    -2147467259(E_FAIL)는 대상 파일 잠금 등 일반 실패에도 쓰이므로 판별 근거로 사용하지 않습니다.
    """
    raw = repr(err) + " " + str(err)
    return "기능이 설치되어 있지 않아" in raw or "25726" in raw

def _open_working_copy(app, doc):
    """원본 문서를 건드리지 않도록 현재 메모리 상태(미저장 변경 포함)를 창 없는 사본 문서로 엽니다."""
    import tempfile
    fd, tmp_xml = tempfile.mkstemp(prefix="atomic_word_copy_", suffix=".xml")
    os.close(fd)
    with open(tmp_xml, "w", encoding="utf-8") as f:
        f.write(doc.WordOpenXML)
    work = app.Documents.Open(tmp_xml, ConfirmConversions=False, AddToRecentFiles=False, Visible=False)
    return work, tmp_xml

def _export_pdf(target_doc, out_path: str) -> None:
    try:
        target_doc.ExportAsFixedFormat(
            OutputFileName=out_path,
            ExportFormat=17,   # wdExportFormatPDF
            OpenAfterExport=False,
            OptimizeFor=0,     # wdExportOptimizeForPrint
            Range=0            # wdExportAllDocument
        )
        log_debug("ExportAsFixedFormat으로 PDF 저장 성공")
    except Exception as e_fixed:
        log_debug(f"ExportAsFixedFormat 실패: {e_fixed}")
        if _is_pdf_feature_missing(e_fixed):
            raise RuntimeError("Word PDF 내보내기 기능이 설치되어 있지 않습니다. --format docx 형식을 사용하세요.")
        raise

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """Word 문서를 PDF 또는 복제본 DOCX로 내보냅니다. 원본 문서(경로, 내용, 저장 상태)는 변경하지 않습니다."""
    out_arg = params.get("output_file") or params.get("output")
    fmt = (params.get("format") or "").lower()
    page_number = bool(params.get("page_number", False))

    if not out_arg:
        return format_response(
            status="error",
            module="word_export",
            action="export",
            preview="output_file parameter is required",
            agent_directive="STOP_RETRY: Missing output file path."
        )

    work_doc = None
    tmp_xml = None
    page_number_applied = False
    try:
        out_ext = os.path.splitext(out_arg)[1].lower()
        if fmt:
            out_format = fmt
        elif out_ext in [".pdf", ".docx"]:
            out_format = out_ext[1:]
        else:
            out_format = "pdf"
        if out_format not in ("pdf", "docx"):
            raise ValueError(f"지원하지 않는 Word 내보내기 형식입니다: {out_format} (pdf 또는 docx 지원)")

        # 형식과 확장자 불일치 방지 (예: --format pdf -o report.docx -> report.pdf)
        if out_ext and out_ext != f".{out_format}":
            out_arg = os.path.splitext(out_arg)[0] + f".{out_format}"
        final_out_path = resolve_output_path(out_arg, default_ext=f".{out_format}")
        log_debug(f"Word Export 대상: '{doc.Name}', 포맷='{out_format}', 경로='{final_out_path}'")

        # 페이지 번호 삽입이나 DOCX 사본 저장은 원본이 아닌 창 없는 사본에서 수행
        if page_number or out_format == "docx":
            work_doc, tmp_xml = _open_working_copy(app, doc)
            target_doc = work_doc
        else:
            target_doc = doc

        if page_number:
            for section in target_doc.Sections:
                footer = section.Footers(1)  # wdHeaderFooterPrimary = 1
                footer.PageNumbers.Add(PageNumberAlignment=1)  # wdAlignPageNumberCenter = 1
            page_number_applied = True
            log_debug("사본 문서에 페이지 번호(하단 중앙) 주입 완료")

        if out_format == "pdf":
            _export_pdf(target_doc, final_out_path)
            preview_msg = f"Exported Word document to PDF: {os.path.basename(final_out_path)}"
        else:
            target_doc.SaveAs2(final_out_path, FileFormat=WD_FORMAT_DOCX)
            preview_msg = f"Exported Word copy to DOCX: {os.path.basename(final_out_path)}"

        return format_response(
            status="ok",
            module="word_export",
            action=f"export_{out_format}",
            preview=preview_msg,
            agent_directive="VERIFIED: Document exported successfully. Original document left unchanged.",
            extra={
                "file_path": final_out_path,
                "format": out_format,
                "page_number": page_number_applied
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="word_export",
            action="export",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Word export failed: {e}"
        )
    finally:
        if work_doc is not None:
            try:
                work_doc.Close(SaveChanges=0)
            except Exception:
                pass
        if tmp_xml and os.path.exists(tmp_xml):
            try:
                os.remove(tmp_xml)
            except Exception:
                pass

def main():
    parser = argparse.ArgumentParser(description="Word Export Micro Block with Page Numbering")
    parser.add_argument("--target", default="active", help="active 또는 docx 파일 경로")
    parser.add_argument("--output", "-o", required=True, help="저장할 파일명 (.pdf 또는 .docx)")
    parser.add_argument("--format", choices=["pdf", "docx"], help="출력 포맷 강제 지정")
    parser.add_argument("--page-number", action="store_true", help="하단 중앙 페이지 번호(- 1 -) 추가")
    args = parser.parse_args()

    params = {
        "output": args.output,
        "format": args.format,
        "page_number": args.page_number
    }

    try:
        with word_session(target=args.target, snapshot=False) as (app, doc):
            res = execute(app, doc, params)
    except Exception as e:
        res = format_response("error", "word_export", "export", preview=f"Word 세션 오류: {e}",
                              agent_directive="STOP_RETRY: Word 문서에 연결하지 못했습니다. 사용자에게 보고하세요.")
    emit_response(res)
    sys.exit(0 if res.get("status") == "ok" else 1)

if __name__ == "__main__":
    main()
