import sys
import os
import zlib
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

def is_heading_candidate(p_text: str) -> bool:
    """단락이 제목/소제목(Heading)인지 패턴으로 판별합니다."""
    if not p_text or len(p_text) > 80:
        return False
    text_clean = p_text.strip()
    import re
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

def resolve_target_file(target: str) -> str:
    """대상 HWP/HWPX 파일 경로를 해석하며, 상대 경로 시 data_dir 또는 CWD에서 탐색합니다."""
    if not target:
        raise ValueError("대상 파일 경로(target)가 필요합니다.")
    if os.path.isabs(target):
        if os.path.exists(target):
            return target
    # 1. C:\cli_data\data 탐색
    cli_candidate = os.path.join(r"C:\cli_data\data", target)
    if os.path.exists(cli_candidate):
        return os.path.abspath(cli_candidate)
    # 2. data_dir 탐색
    data_candidate = os.path.join(get_data_dir(), target)
    if os.path.exists(data_candidate):
        return os.path.abspath(data_candidate)
    # 2. CWD 탐색
    cwd_candidate = os.path.abspath(target)
    if os.path.exists(cwd_candidate):
        return cwd_candidate
    raise FileNotFoundError(f"HWP 파일을 찾을 수 없습니다: {target}")

def extract_hwp_binary_ole(abs_path: str) -> Dict[str, Any]:
    """바이너리 HWP 5.0 (OLE 포맷) 파일에서 순수 텍스트를 고속 추출합니다."""
    import olefile

    if not olefile.isOleFile(abs_path):
        raise ValueError("표준 HWP 5.0 OLE 포맷이 아닙니다.")

    ole = olefile.OleFileIO(abs_path)
    dirs = ole.listdir()
    sections = [d for d in dirs if len(d) >= 2 and d[0] == 'BodyText' and d[1].startswith('Section')]
    sections.sort()

    paragraphs = []
    
    # 확장 컨트롤 코드 목록 (16바이트 추가 정보 포함 태그)
    EXTENDED_CONTROLS = {4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31}

    for sec in sections:
        stream = ole.openstream(sec)
        data = stream.read()
        try:
            decompressed = zlib.decompress(data, -15)
        except Exception:
            try:
                decompressed = zlib.decompress(data)
            except Exception:
                decompressed = data

        idx = 0
        while idx < len(decompressed):
            if idx + 4 > len(decompressed):
                break
            header = int.from_bytes(decompressed[idx:idx+4], 'little')
            tag_id = header & 0x3FF
            size = (header >> 20) & 0xFFF
            idx += 4
            if size == 0xFFF:
                size = int.from_bytes(decompressed[idx:idx+4], 'little')
                idx += 4

            rec = decompressed[idx:idx+size]
            idx += size

            if tag_id == 67:  # HWPTAG_PARA_TEXT
                chars = []
                c_idx = 0
                while c_idx < len(rec):
                    code = int.from_bytes(rec[c_idx:c_idx+2], 'little')
                    c_idx += 2
                    if code in (10, 13):
                        chars.append('\n')
                    elif code in (1, 2, 3):
                        continue
                    elif code in EXTENDED_CONTROLS:
                        c_idx += 16  # 16바이트 제어 속성 스킵
                    elif code >= 32:
                        chars.append(chr(code))
                
                line = ''.join(chars).strip()
                if line:
                    paragraphs.append(line)

    ole.close()
    return {
        "format_type": "HWP 5.0 (OLE)",
        "paragraphs": paragraphs,
        "full_text": "\n".join(paragraphs)
    }

def extract_hwpx_zip(abs_path: str) -> Dict[str, Any]:
    """신규 HWPX (XML Zip 포맷) 파일에서 텍스트를 추출합니다."""
    paragraphs = []
    with zipfile.ZipFile(abs_path, 'r') as z:
        section_files = [f for f in z.namelist() if f.startswith("Contents/section") and f.endswith(".xml")]
        section_files.sort()
        for sf in section_files:
            xml_data = z.read(sf)
            root = ET.fromstring(xml_data)
            # 모든 <hp:t> 태그 텍스트 수집
            for elem in root.iter():
                if elem.tag.endswith("}t") or elem.tag == "t":
                    if elem.text:
                        txt = elem.text.strip()
                        if txt:
                            paragraphs.append(txt)

    return {
        "format_type": "HWPX (XML Zip)",
        "paragraphs": paragraphs,
        "full_text": "\n".join(paragraphs)
    }

def extract_hwp_data(abs_path: str) -> Dict[str, Any]:
    """HWP 또는 HWPX 파일 형식을 자동 감지하여 텍스트를 추출합니다."""
    # 1. HWPX (Zip 파일) 검사
    if zipfile.is_zipfile(abs_path):
        try:
            return extract_hwpx_zip(abs_path)
        except Exception as e_zip:
            log_debug(f"HWPX 파싱 실패, OLE 시도: {e_zip}")

    # 2. HWP 5.0 OLE 검사
    try:
        return extract_hwp_binary_ole(abs_path)
    except Exception as e_ole:
        raise RuntimeError(f"HWP 파일 파싱 실패: {e_ole}")

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 주입받은 인자로 HWP 텍스트 및 정보를 고속 조회(캐시 지원)합니다."""
    target = params.get("target") or params.get("file")
    search_kw = (params.get("search") or "").strip()
    fmt = (params.get("format") or "text").lower()

    if not target:
        return format_response(
            status="error",
            module="hwp_read",
            action="read",
            preview="target parameter is required",
            agent_directive="STOP_RETRY: Missing target file path."
        )

    try:
        abs_path = resolve_target_file(target)
        file_name = os.path.basename(abs_path)
        sub_key = f"{search_kw}_{fmt}"

        # 1. mtime 기반 디스크 캐시 검사 (0.001s)
        cached_data = get_file_cache(abs_path, sub_key=sub_key)
        if cached_data:
            return format_response(
                status="ok",
                module="hwp_read",
                action="read_cached",
                preview=cached_data.get("preview", f"Read HWP from cache: {file_name}"),
                agent_directive="VERIFIED: HWP data retrieved from disk cache.",
                extra=cached_data
            )

        # 2. 캐시 미스 시 파싱 수행
        extracted = extract_hwp_data(abs_path)
        paragraphs = extracted["paragraphs"]
        full_text = extracted["full_text"]
        total_paras = len(paragraphs)
        total_chars = len(full_text)

        # 검색 키워드가 있는 경우
        search_matches = []
        if search_kw:
            for p_num, p_text in enumerate(paragraphs, start=1):
                if search_kw in p_text:
                    start_idx = max(0, p_text.find(search_kw) - 40)
                    end_idx = min(len(p_text), p_text.find(search_kw) + len(search_kw) + 60)
                    snippet = p_text[start_idx:end_idx].replace("\n", " ").strip()
                    search_matches.append({
                        "paragraph": p_num,
                        "snippet": f"...{snippet}..."
                    })

            if not search_matches:
                return format_response(
                    status="no_match",
                    module="hwp_read",
                    action="search",
                    preview=f"Keyword '{search_kw}' not found in {file_name}",
                    agent_directive="STOP_RETRY: Keyword not found in HWP."
                )

        # 출력 포맷 결정
        if fmt == "summary":
            preview_msg = f"HWP: {file_name} | 단락 {total_paras}개 | 총 글자: {total_chars}자 ({extracted['format_type']})"
            payload_data = {
                "format_type": extracted["format_type"],
                "total_paragraphs": total_paras,
                "total_characters": total_chars
            }
        elif fmt == "paragraphs":
            preview_msg = f"HWP: {file_name} ({total_paras} paras, {total_chars} chars)"
            payload_data = [{"paragraph": i, "characters": len(p), "text": p} for i, p in enumerate(paragraphs, start=1)]
        else:
            preview_msg = f"HWP: {file_name} ({total_paras} paras, {total_chars} chars)"
            payload_data = full_text

        items = []
        current_page = 1
        cumulative_chars = 0
        current_heading = ""
        toc = []
        CHARS_PER_PAGE_EST = 1200

        for i, p in enumerate(paragraphs, start=1):
            p_len = len(p)
            cumulative_chars += p_len
            if cumulative_chars >= CHARS_PER_PAGE_EST:
                current_page += 1
                cumulative_chars = p_len

            is_h = is_heading_candidate(p)
            if is_h:
                current_heading = p
                toc.append({"title": p, "page": current_page, "para": i})
                loc_label = f"Page {current_page} > [Heading: {p}]"
            else:
                if current_heading:
                    loc_label = f"Page {current_page} > [{current_heading}] (Para {i})"
                else:
                    loc_label = f"Page {current_page} (Para {i})"

            items.append({
                "loc": loc_label,
                "page": current_page,
                "para": i,
                "heading": current_heading,
                "is_heading": is_h,
                "text": p
            })

        result_payload = {
            "file": file_name,
            "path": abs_path,
            "file_type": "hwp",
            "format_type": extracted["format_type"],
            "total_pages": current_page,
            "total_paragraphs": total_paras,
            "total_characters": total_chars,
            "toc": toc,
            "preview": preview_msg,
            "items": items,
            "data": payload_data,
            "search_matches": search_matches if search_kw else None
        }

        # 3. 캐시 저장 (최근 2개 유지)
        save_file_cache(abs_path, result_payload, sub_key=sub_key)

        return format_response(
            status="ok",
            module="hwp_read",
            action="read_hwp",
            preview=preview_msg,
            agent_directive="VERIFIED: HWP read successfully.",
            extra=result_payload
        )

    except Exception as e:
        return format_response(
            status="error",
            module="hwp_read",
            action="read",
            preview=str(e),
            agent_directive=f"STOP_RETRY: HWP read failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="HWP/HWPX Read Micro Block (High Performance & Cache)")
    parser.add_argument("--target", "--file", required=True, help="HWP 또는 HWPX 파일 경로")
    parser.add_argument("--search", type=str, help="특정 단어 검색")
    parser.add_argument("--format", choices=["text", "paragraphs", "summary"], default="text", help="출력 형식")
    args = parser.parse_args()

    params = {
        "target": args.target,
        "search": args.search,
        "format": args.format
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
