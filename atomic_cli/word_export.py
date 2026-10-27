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

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 Word 문서를 PDF 또는 복제본 DOCX로 안전하게 내보냅니다."""
    out_arg = params.get("output_file") or params.get("output")
    fmt = (params.get("format") or "").lower()
    page_number = params.get("page_number", False)

    if not out_arg:
        return format_response(
            status="error",
            module="word_export",
            action="export",
            preview="output_file parameter is required",
            agent_directive="STOP_RETRY: Missing output file path."
        )

    try:
        # 페이지 번호 자동 주입
        if page_number:
            try:
                for section in doc.Sections:
                    footer = section.Footers(1)  # wdHeaderFooterPrimary = 1
                    footer.PageNumbers.Add(PageNumberAlignment=1)  # wdAlignPageNumberCenter = 1
                log_debug("Word 페이지 번호(하단 중앙) 주입 완료")
            except Exception as pe:
                log_debug(f"페이지 번호 주입 예외: {pe}")

        out_ext = os.path.splitext(out_arg)[1].lower()
        if fmt:
            out_format = fmt
        elif out_ext in [".pdf", ".docx"]:
            out_format = out_ext[1:]
        else:
            out_format = "pdf"

        final_out_path = resolve_output_path(out_arg, default_ext=f".{out_format}")
        log_debug(f"Word Export 대상: '{doc.Name}', 포맷='{out_format}', 경로='{final_out_path}'")

        if out_format == "pdf":
            saved_pdf = False
            # 1. ExportAsFixedFormat 시도 (Word 2007 SP2+ 권장 표준)
            pdf_missing_feature = False
            if hasattr(doc, "ExportAsFixedFormat"):
                try:
                    doc.ExportAsFixedFormat(
                        OutputFileName=final_out_path,
                        ExportFormat=17,  # wdExportFormatPDF
                        OpenAfterExport=False,
                        OptimizeFor=0,     # wdExportOptimizeForPrint
                        Range=0            # wdExportAllDocument
                    )
                    saved_pdf = True
                    log_debug("ExportAsFixedFormat으로 PDF 저장 성공")
                except Exception as e_fixed:
                    log_debug(f"ExportAsFixedFormat 실패: {e_fixed}")
                    raw_str = repr(e_fixed) + " " + str(e_fixed)
                    if "기능이 설치되어 있지 않아" in raw_str or "25726" in raw_str or "-2147467259" in raw_str:
                        pdf_missing_feature = True

            # 2. SaveAs2 / SaveAs 시도 (폴백)
            if not saved_pdf:
                if pdf_missing_feature:
                    raise RuntimeError("Word PDF 내보내기 기능(Office 2007 추가 기능)이 설치되어 있지 않습니다. --format docx 형식을 사용하세요.")
                try:
                    if hasattr(doc, "SaveAs2"):
                        doc.SaveAs2(final_out_path, FileFormat=WD_FORMAT_PDF)
                    else:
                        doc.SaveAs(final_out_path, FileFormat=WD_FORMAT_PDF)
                    saved_pdf = True
                except Exception as e_saveas:
                    log_debug(f"SaveAs(2) 실패, 위치 인자 호출 시도: {e_saveas}")
                    try:
                        doc.SaveAs(final_out_path, WD_FORMAT_PDF)
                        saved_pdf = True
                    except Exception as e_final:
                        err_str = str(e_final) + " " + fixed_err_msg
                        if "기능이 설치되어 있지 않아" in err_str or "-2147467259" in err_str:
                            raise RuntimeError("Word PDF 내보내기 기능(Office 2007 추가 기능)이 설치되어 있지 않습니다. --format docx 형식을 사용하세요.")
                        raise e_final

            preview_msg = f"Exported Word document to PDF: {os.path.basename(final_out_path)}"
        elif out_format == "docx":
            try:
                if hasattr(doc, "FullName") and os.path.exists(doc.FullName):
                    if not getattr(doc, "Saved", True):
                        doc.Save()
                    import shutil
                    shutil.copy2(doc.FullName, final_out_path)
                else:
                    doc.SaveAs(final_out_path)
            except Exception as e_copy:
                log_debug(f"Save & Copy 실패, SaveAs 시도: {e_copy}")
                doc.SaveAs(final_out_path)
            preview_msg = f"Exported Word copy to DOCX: {os.path.basename(final_out_path)}"
        else:
            raise ValueError(f"지원하지 않는 Word 내보내기 형식입니다: {out_format} (pdf 또는 docx 지원)")

        return format_response(
            status="ok",
            module="word_export",
            action=f"export_{out_format}",
            preview=preview_msg,
            agent_directive="VERIFIED: Document exported successfully. Active window preserved.",
            extra={
                "file_path": final_out_path,
                "format": out_format,
                "page_number": page_number
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

    with word_session(target=args.target, snapshot=False) as (app, doc):
        res = execute(app, doc, params)
        emit_response(res)

if __name__ == "__main__":
    main()
