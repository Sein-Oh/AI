import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_data_dir
from _com_guard import ppt_session

# PowerPoint 상수
PP_FIXED_FORMAT_TYPE_PDF = 2
PP_SAVE_AS_PDF = 32

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

def execute(app, prs, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 PowerPoint 프레젠테이션을 PDF 또는 복제본 PPTX로 안전하게 내보냅니다."""
    out_arg = params.get("output_file") or params.get("output")
    fmt = (params.get("format") or "").lower()

    if not out_arg:
        return format_response(
            status="error",
            module="ppt_export",
            action="export",
            preview="output_file parameter is required",
            agent_directive="STOP_RETRY: Missing output file path."
        )

    try:
        out_ext = os.path.splitext(out_arg)[1].lower()
        if fmt:
            out_format = fmt
        elif out_ext in [".pdf", ".pptx", ".ppt"]:
            out_format = "pdf" if out_ext == ".pdf" else "pptx"
        else:
            out_format = "pdf"

        # 형식과 확장자 불일치 방지 (예: --format pdf -o deck.pptx -> deck.pdf)
        # SaveCopyAs는 원본 형식으로 저장하므로 pptx 사본의 확장자는 원본 확장자(.pptx/.pptm/.ppt)를 따름
        if out_format == "pdf":
            wanted_ext = ".pdf"
        else:
            src_ext = os.path.splitext(str(getattr(prs, "FullName", "")))[1].lower()
            wanted_ext = src_ext if src_ext in (".pptx", ".pptm", ".ppt") else ".pptx"
        if out_ext and out_ext != wanted_ext:
            out_arg = os.path.splitext(out_arg)[0] + wanted_ext
        final_out_path = resolve_output_path(out_arg, default_ext=wanted_ext)
        log_debug(f"PowerPoint Export 대상: '{prs.Name}', 포맷='{out_format}', 경로='{final_out_path}'")

        if out_format == "pdf":
            # ExportAsFixedFormat 우선 시도 (2 = ppFixedFormatTypePDF)
            saved_pdf = False
            pdf_missing_feature = False
            try:
                prs.ExportAsFixedFormat(final_out_path, PP_FIXED_FORMAT_TYPE_PDF)
                saved_pdf = True
            except Exception as e_fixed:
                log_debug(f"ExportAsFixedFormat 실패, SaveAs 시도: {e_fixed}")
                raw_fixed = repr(e_fixed) + " " + str(e_fixed)
                # -2147467259(E_FAIL)는 파일 잠금 등 일반 실패에도 쓰이므로 판별 근거로 사용하지 않음
                if "기능이 설치되어 있지 않아" in raw_fixed or "can not be converted" in raw_fixed:
                    pdf_missing_feature = True

            if not saved_pdf:
                try:
                    prs.SaveAs(final_out_path, PP_SAVE_AS_PDF)
                    saved_pdf = True
                except Exception as e_saveas:
                    raw_saveas = repr(e_saveas) + " " + str(e_saveas)
                    if pdf_missing_feature or "기능이 설치되어 있지 않아" in raw_saveas:
                        raise RuntimeError("PowerPoint PDF 내보내기 기능(Office 2007 추가 기능)이 설치되어 있지 않습니다. --format pptx 형식을 사용하세요.")
                    raise e_saveas
            preview_msg = f"Exported PowerPoint presentation to PDF: {os.path.basename(final_out_path)}"
        elif out_format in ["pptx", "ppt"]:
            # 원본 보존 복제본 저장
            prs.SaveCopyAs(final_out_path)
            preview_msg = f"Exported PowerPoint copy to PPTX: {os.path.basename(final_out_path)}"
        else:
            raise ValueError(f"지원하지 않는 PowerPoint 내보내기 형식입니다: {out_format} (pdf 또는 pptx 지원)")

        return format_response(
            status="ok",
            module="ppt_export",
            action=f"export_{out_format}",
            preview=preview_msg,
            agent_directive="VERIFIED: Presentation exported successfully. Active window preserved.",
            extra={
                "file_path": final_out_path,
                "format": out_format
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="ppt_export",
            action="export",
            preview=str(e),
            agent_directive=f"STOP_RETRY: PowerPoint export failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Export Micro Block (PDF & PPTX)")
    parser.add_argument("--target", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--output", "-o", required=True, help="저장할 파일명 (.pdf 또는 .pptx)")
    parser.add_argument("--format", choices=["pdf", "pptx"], help="출력 포맷 강제 지정")
    args = parser.parse_args()

    params = {
        "output_file": args.output,
        "format": args.format
    }

    try:
        with ppt_session(target=args.target) as (app, prs):
            res = execute(app, prs, params)
    except Exception as e:
        res = format_response("error", "ppt_export", "export", preview=f"PowerPoint 세션 오류: {e}",
                              agent_directive="STOP_RETRY: PowerPoint 프레젠테이션에 연결하지 못했습니다. 사용자에게 보고하세요.")
    emit_response(res)
    sys.exit(0 if res.get("status") == "ok" else 1)

if __name__ == "__main__":
    main()
