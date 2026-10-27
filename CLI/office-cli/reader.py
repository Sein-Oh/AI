"""reader.py - 문서 파일 읽기와 검색 (Office 프로그램 불필요)

명령:
    read    파일 하나를 읽습니다. PDF, HWP, HWPX, EML, DOCX, PPTX, XLSX, CSV, TXT, MD
    search  읽은 적 있는 문서 전체(또는 지정한 파일/폴더)에서 검색합니다.
    list    읽은 적 있는 문서(색인) 목록을 봅니다.

읽은 문서는 캐시(cache/docs)와 색인(cache/index.json)에 자동 등록되어, 이후 search 대상이 됩니다.
결과를 다른 문서에 넣으려면 --save로 파일을 만든 뒤 word.py/ppt.py write --file 또는 excel.py write --file로 넘깁니다.

예:
    python reader.py read --file "C:\\docs\\보고서.pdf" --pages 1-3
    python reader.py search --query "마일스톤 AND 일정" --save
    python reader.py search --query "단가" --file "C:\\docs\\견적" --save 결과.csv
    python reader.py list
"""
import email
import hashlib
import json
import os
import re
import sys
import zipfile
import zlib
from email import policy
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _runtime as rt  # noqa: E402

TOOL = "reader"
SUPPORTED = {
    ".pdf": "pdf", ".hwp": "hwp", ".hwpx": "hwpx", ".eml": "eml",
    ".docx": "docx", ".docm": "docx", ".pptx": "pptx", ".pptm": "pptx",
    ".xlsx": "xlsx", ".xlsm": "xlsx", ".csv": "csv", ".txt": "txt", ".md": "txt",
}
UNIT_NAMES = {"pdf": "페이지", "pptx": "슬라이드", "xlsx": "행", "csv": "행"}
PARSER_VERSION = 1          # 파서가 바뀌면 올려서 기존 캐시를 무효화
MAX_SHEET_ROWS = 20000      # xlsx 시트당 최대 행 수
MAX_FOLDER_FILES = 300      # 폴더 검색 시 최대 파일 수
MAX_FOLDER_DEPTH = 3


# ==============================================================================
# 1. 형식별 파서: 결과는 units = [{"loc", "heading", "text"}]
# ==============================================================================

def _unit(loc: str, text: str, heading: str = "") -> Dict[str, str]:
    return {"loc": loc, "heading": heading, "text": text}


def _encrypted_hint(path: str) -> rt.InputError:
    return rt.InputError(
        f"파일을 열 수 없습니다. 문서 보안(DRM)으로 암호화되었거나 손상된 파일일 수 있습니다: {os.path.basename(path)}. "
        "Office 문서라면 excel.py / word.py / ppt.py read --target \"<경로>\"로 Office에서 직접 읽어 보세요."
    )


def parse_pdf(path: str) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    try:
        import pymupdf
    except ImportError:
        raise rt.InputError("PDF를 읽으려면 pymupdf가 필요합니다 (python -m pip install pymupdf).")
    try:
        doc = pymupdf.open(path)
    except Exception:
        raise _encrypted_hint(path)
    try:
        if doc.needs_pass:
            raise rt.InputError(f"암호가 걸린 PDF입니다: {os.path.basename(path)}")
        units = [_unit(f"p.{i}", page.get_text("text").strip()) for i, page in enumerate(doc, 1)]
        meta = {"pages": doc.page_count, "title": (doc.metadata or {}).get("title") or ""}
    finally:
        doc.close()
    if not any(u["text"] for u in units):
        meta["ocr_needed"] = True
        rt.log("WARN", "텍스트가 없는 PDF입니다 (스캔 이미지일 가능성). OCR이 필요합니다.")
    return units, meta


# HWP 5.0 제어 문자: 1 WCHAR 짜리 문자 컨트롤. 나머지 1~31은 인라인/확장 컨트롤로 8 WCHAR(16바이트)를 차지합니다.
_HWP_CHAR_CONTROLS = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}
_HWP_CHAR_MAP = {10: "\n", 24: "-", 30: " ", 31: " "}
_HWPTAG_PARA_TEXT = 67


def _hwp_para_text(rec: bytes) -> str:
    out: List[str] = []
    i, n = 0, len(rec)
    while i + 1 < n:
        code = rec[i] | (rec[i + 1] << 8)
        if code >= 32:
            out.append(chr(code))
            i += 2
        elif code in _HWP_CHAR_CONTROLS:
            out.append(_HWP_CHAR_MAP.get(code, ""))
            i += 2
        else:
            if code == 9:
                out.append("\t")
            i += 16
    return "".join(out)


def parse_hwp(path: str) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    try:
        import olefile
    except ImportError:
        raise rt.InputError("HWP를 읽으려면 olefile이 필요합니다 (python -m pip install olefile).")
    if not olefile.isOleFile(path):
        raise _encrypted_hint(path)
    ole = olefile.OleFileIO(path)
    try:
        header = ole.openstream("FileHeader").read()
        props = int.from_bytes(header[36:40], "little") if len(header) >= 40 else 0
        compressed = bool(props & 0x1)
        if props & 0x2:
            raise rt.InputError(f"암호가 걸린 HWP 문서입니다: {os.path.basename(path)}")
        if props & 0x4:
            raise rt.InputError(f"배포용 HWP 문서라 본문을 추출할 수 없습니다: {os.path.basename(path)}")

        sections = [d for d in ole.listdir() if len(d) == 2 and d[0] == "BodyText" and d[1].startswith("Section")]
        sections.sort(key=lambda d: int(re.sub(r"\D", "", d[1]) or 0))
        paragraphs: List[str] = []
        for sec in sections:
            data = ole.openstream(sec).read()
            if compressed:
                data = zlib.decompress(data, -15)
            pos, size_total = 0, len(data)
            while pos + 4 <= size_total:
                h = int.from_bytes(data[pos:pos + 4], "little")
                pos += 4
                tag, size = h & 0x3FF, (h >> 20) & 0xFFF
                if size == 0xFFF:
                    size = int.from_bytes(data[pos:pos + 4], "little")
                    pos += 4
                if tag == _HWPTAG_PARA_TEXT:
                    text = _hwp_para_text(data[pos:pos + size]).strip()
                    if text:
                        paragraphs.append(text)
                pos += size
    finally:
        ole.close()
    units = [_unit(f"단락 {i}", t) for i, t in enumerate(paragraphs, 1)]
    return units, {"format": "HWP 5.0", "sections": len(sections)}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_hwpx(path: str) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    if not zipfile.is_zipfile(path):
        raise _encrypted_hint(path)
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)]
        if not names:
            raise rt.InputError(f"HWPX 본문(Contents/section*.xml)이 없습니다: {os.path.basename(path)}")
        names.sort(key=lambda n: int(re.sub(r"\D", "", n)))
        paragraphs: List[str] = []
        for name in names:
            root = ET.fromstring(z.read(name))
            _hwpx_walk(root, None, paragraphs)
    texts = [p.strip() for p in paragraphs if p and p.strip()]
    return [_unit(f"단락 {i}", t) for i, t in enumerate(texts, 1)], {"format": "HWPX", "sections": len(names)}


def _hwpx_walk(elem: ET.Element, buf: Optional[List[str]], out: List[str]) -> None:
    """문단(<p>)마다 자기 텍스트(<t>)만 모읍니다. 표 안의 문단은 별도 문단으로, 문서 순서를 유지합니다."""
    tag = _local(elem.tag)
    if tag == "p":
        slot = len(out)
        out.append("")
        own: List[str] = []
        for child in elem:
            _hwpx_walk(child, own, out)
        out[slot] = "".join(own)
        return
    if tag == "t" and buf is not None:
        if elem.text:
            buf.append(elem.text)
        for child in elem:
            if _local(child.tag) == "tab":
                buf.append("\t")
            if child.tail:
                buf.append(child.tail)
        return
    for child in elem:
        _hwpx_walk(child, buf, out)


def _decode_bytes(raw: bytes, declared: Optional[str]) -> str:
    for enc in [declared, "utf-8", "cp949", "euc-kr"]:
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1")


def _decode_header_value(value: Any) -> str:
    """RFC2047 인코딩과 인코딩 표시 없는 8비트(CP949 등) 헤더를 모두 처리합니다."""
    if value is None:
        return ""
    s = str(value)
    try:
        raw = s.encode("ascii", "surrogateescape")
        if any(b > 127 for b in raw):
            return _decode_bytes(raw, None).strip()
    except UnicodeEncodeError:
        pass
    try:
        return str(make_header(decode_header(s))).strip()
    except Exception:
        return s.strip()


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())


def parse_eml(path: str) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=policy.compat32)
    # compat32의 msg.get()은 인코딩 표시 없는 8비트 헤더를 깨진 문자로 바꾸므로 원본 헤더 값을 직접 해석
    raw_headers: Dict[str, str] = {}
    for key, value in msg.raw_items():
        raw_headers.setdefault(key.lower(), value)
    subject = _decode_header_value(raw_headers.get("subject"))
    sender = _decode_header_value(raw_headers.get("from"))
    to = _decode_header_value(raw_headers.get("to"))
    cc = _decode_header_value(raw_headers.get("cc"))
    date = ""
    if msg.get("Date"):
        try:
            date = parsedate_to_datetime(str(msg.get("Date"))).strftime("%Y-%m-%d %H:%M")
        except Exception:
            date = str(msg.get("Date"))

    plain: List[str] = []
    html: List[str] = []
    attachments: List[str] = []

    def walk(part) -> None:
        ctype = part.get_content_type()
        if ctype == "message/rfc822":   # 전달된 메일은 본문에 섞지 않고 첨부로만 표시 (multipart 판정보다 먼저)
            attachments.append("(첨부된 메일)")
            return
        if part.is_multipart():
            for sub in part.get_payload():
                walk(sub)
            return
        filename = part.get_filename()
        disposition = (part.get("Content-Disposition") or "").lower()
        if filename or disposition.startswith("attachment"):
            attachments.append(_decode_header_value(filename) if filename else "(이름 없는 첨부)")
            return
        payload = part.get_payload(decode=True)
        if payload is None:
            return
        text = _decode_bytes(payload, part.get_content_charset())
        if ctype == "text/plain":
            plain.append(text.strip())
        elif ctype == "text/html":
            html.append(_strip_html(text))

    walk(msg)
    body = "\n\n".join(p for p in plain if p) or "\n\n".join(h for h in html if h)
    header = "\n".join(f"{k}: {v}" for k, v in (("제목", subject), ("보낸사람", sender), ("받는사람", to),
                                                    ("참조", cc), ("날짜", date)) if v)
    if attachments:
        header += "\n첨부: " + ", ".join(attachments)
    units = [_unit("헤더", header, subject)]
    for i, para in enumerate([p for p in re.split(r"\n\s*\n", body) if p.strip()], 1):
        units.append(_unit(f"본문 {i}", para.strip(), subject))
    return units, {"subject": subject, "from": sender, "to": to, "date": date, "attachments": attachments}


def parse_docx(path: str) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    if not zipfile.is_zipfile(path):
        raise _encrypted_hint(path)
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    document = docx.Document(path)
    units: List[Dict[str, str]] = []
    heading = ""
    para_no = table_no = 0
    for child in document.element.body.iterchildren():
        tag = _local(child.tag)
        if tag == "p":
            para = Paragraph(child, document)
            text = para.text.strip()
            if not text:
                continue
            para_no += 1
            style = (para.style.name if para.style is not None else "") or ""
            if style.lower().startswith(("heading", "title")) or style.startswith(("제목", "부제")):
                heading = text
            units.append(_unit(f"단락 {para_no}", text, heading))
        elif tag == "tbl":
            table_no += 1
            rows: List[str] = []
            for row in Table(child, document).rows:
                cells: List[str] = []
                seen = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:      # 병합 셀 중복 제거
                        continue
                    seen.add(id(cell._tc))
                    cells.append(cell.text.strip().replace("\n", " "))
                rows.append(" | ".join(cells))
            units.append(_unit(f"표 {table_no}", "\n".join(rows), heading))
    core = document.core_properties
    return units, {"title": core.title or "", "paragraphs": para_no, "tables": table_no}


def _pptx_shape_lines(shape, out: List[str]) -> None:
    """도형 하나의 텍스트를 줄 단위로 모읍니다 (그룹은 재귀, 표는 행 단위)."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        for sub in shape.shapes:
            _pptx_shape_lines(sub, out)
    elif getattr(shape, "has_table", False):
        for row in shape.table.rows:
            out.append(" | ".join(c.text.strip().replace("\n", " ") for c in row.cells))
    elif getattr(shape, "has_text_frame", False):
        for para in shape.text_frame.paragraphs:
            text = para.text.replace("\v", " ").strip()
            if text:
                out.append(text)


def parse_pptx(path: str) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    if not zipfile.is_zipfile(path):
        raise _encrypted_hint(path)
    import pptx
    prs = pptx.Presentation(path)
    units: List[Dict[str, str]] = []
    for idx, slide in enumerate(prs.slides, 1):   # presentation.xml의 실제 슬라이드 순서
        title_shape = slide.shapes.title
        title = title_shape.text.strip() if title_shape is not None and title_shape.has_text_frame else ""
        lines: List[str] = []
        for shape in slide.shapes:
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                continue
            _pptx_shape_lines(shape, lines)
        if not title and lines:
            title = lines[0]
        notes = ""
        if slide.has_notes_slide:
            notes = (slide.notes_slide.notes_text_frame.text or "").strip()
        body = "\n".join(([title] if title and (not lines or lines[0] != title) else []) + lines)
        if notes:
            body += f"\n[노트] {notes}"
        units.append(_unit(f"슬라이드 {idx}", body.strip(), title))
    return units, {"slides": len(prs.slides)}


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if hasattr(v, "isoformat"):
        return v.isoformat(sep=" ") if hasattr(v, "hour") else v.isoformat()
    return str(v)


def parse_xlsx(path: str) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    if not zipfile.is_zipfile(path):
        raise _encrypted_hint(path)
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    units: List[Dict[str, str]] = []
    sheets: List[str] = []
    truncated = False
    try:
        for ws in wb.worksheets:
            sheets.append(ws.title)
            count = 0
            for r_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                cells = [_cell_str(v) for v in row]
                while cells and cells[-1] == "":
                    cells.pop()
                if not any(cells):
                    continue
                count += 1
                if count > MAX_SHEET_ROWS:
                    truncated = True
                    break
                units.append(_unit(f"{ws.title}!{r_idx}행", "\t".join(cells), ws.title))
    finally:
        wb.close()
    meta: Dict[str, Any] = {"sheets": sheets}
    if truncated:
        meta["rows_truncated"] = True
        rt.log("WARN", f"시트당 {MAX_SHEET_ROWS}행까지만 읽었습니다.")
    return units, meta


def parse_csv(path: str) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    rows = rt.read_csv_rows(path)
    units = [_unit(f"{i}행", "\t".join(r)) for i, r in enumerate(rows, 1) if any(c.strip() for c in r)]
    return units, {"rows": len(rows)}


def parse_txt(path: str) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    text = rt.read_text_file(path)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: List[Dict[str, str]] = []
    heading = ""
    for i, p in enumerate(paras, 1):
        if p.startswith("#"):
            heading = p.lstrip("#").strip().splitlines()[0]
        units.append(_unit(f"단락 {i}", p, heading))
    return units, {}


PARSERS = {"pdf": parse_pdf, "hwp": parse_hwp, "hwpx": parse_hwpx, "eml": parse_eml, "docx": parse_docx,
           "pptx": parse_pptx, "xlsx": parse_xlsx, "csv": parse_csv, "txt": parse_txt}


def file_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xls" or ext == ".doc" or ext == ".ppt":
        raise rt.InputError(f"구형 Office 형식({ext})은 라이브러리로 읽을 수 없습니다. "
                            f"excel.py / word.py / ppt.py read --target \"{path}\"로 Office에서 읽으세요.")
    if ext not in SUPPORTED:
        raise rt.InputError(f"지원하지 않는 형식입니다: {ext} (지원: {', '.join(sorted(SUPPORTED))})")
    return SUPPORTED[ext]


# ==============================================================================
# 2. 캐시와 색인
# ==============================================================================

def _doc_cache_path(path: str) -> str:
    key = hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()[:16]
    folder = os.path.join(rt.get_cache_dir(), "docs")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{key}.json")


def _index_path() -> str:
    return os.path.join(rt.get_cache_dir(), "index.json")


def load_index() -> Dict[str, Dict[str, Any]]:
    p = _index_path()
    if not os.path.exists(p):
        return {}
    try:
        data = json.loads(rt.read_text_file(p))
        return data if isinstance(data, dict) else {}
    except Exception:
        rt.log("WARN", "색인 파일이 손상되어 새로 만듭니다.")
        return {}


def _save_index(index: Dict[str, Dict[str, Any]]) -> None:
    rt.safe_write_text(_index_path(), json.dumps(index, ensure_ascii=False))


def load_document(path: str, use_cache: bool = True) -> Dict[str, Any]:
    """파일을 파싱하거나(수정 시각/크기가 같으면) 캐시에서 불러오고, 색인에 등록합니다."""
    path = os.path.abspath(path)
    ftype = file_type(path)
    st = os.stat(path)
    cache_file = _doc_cache_path(path)
    if use_cache and os.path.exists(cache_file):
        try:
            cached = json.loads(rt.read_text_file(cache_file))
            if (cached.get("mtime") == st.st_mtime and cached.get("size") == st.st_size
                    and cached.get("parser_version") == PARSER_VERSION):
                rt.debug(f"캐시 사용: {os.path.basename(path)}")
                return cached
        except Exception:
            pass
    rt.log("PROGRESS", f"문서 읽는 중: {os.path.basename(path)}")
    units, meta = PARSERS[ftype](path)
    doc = {"file": path, "type": ftype, "mtime": st.st_mtime, "size": st.st_size,
           "parser_version": PARSER_VERSION, "parsed_at": rt.timestamp(), "meta": meta, "units": units}
    try:
        rt.safe_write_text(cache_file, json.dumps(doc, ensure_ascii=False))
        index = load_index()
        index[path] = {"type": ftype, "units": len(units), "parsed_at": doc["parsed_at"],
                       "chars": sum(len(u["text"]) for u in units), "cache_file": os.path.basename(cache_file)}
        _save_index(index)
    except OSError as e:
        rt.log("WARN", f"캐시 저장 실패 (결과에는 영향 없음): {e}")
    return doc


def load_cached_only(path: str) -> Optional[Dict[str, Any]]:
    cache_file = _doc_cache_path(path)
    if not os.path.exists(cache_file):
        return None
    try:
        return json.loads(rt.read_text_file(cache_file))
    except Exception:
        return None


# ==============================================================================
# 3. 공통 출력 도우미
# ==============================================================================

def parse_pages(spec: Optional[str], total: int) -> List[int]:
    """'3', '1-3', '1,4,6-8' -> 1부터 센 번호 목록."""
    if not spec:
        return list(range(1, total + 1))
    result: List[int] = []
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise rt.InputError(f"--pages 형식이 잘못되었습니다: '{spec}' (예: 3, 1-3, 1,4,6-8)")
        a = int(m.group(1))
        b = int(m.group(2) or a)
        result += [n for n in range(min(a, b), max(a, b) + 1) if 1 <= n <= total]
    if not result:
        raise rt.InputError(f"--pages '{spec}'에 해당하는 항목이 없습니다 (전체 {total}개).")
    return sorted(set(result))


def units_to_markdown(title: str, units: List[Dict[str, str]]) -> str:
    lines = [f"# {title}", ""]
    for u in units:
        head = u["loc"] + (f" - {u['heading']}" if u.get("heading") and u["heading"] != u["text"] else "")
        lines += [f"## {head}", "", u["text"], ""]
    return "\n".join(lines)


def _write_next_commands(output_file: str) -> List[Dict[str, str]]:
    if output_file.lower().endswith(".csv"):
        return [rt.next_command("excel.py", ["write", "--target", "active", "--file", output_file],
                                "저장한 표를 열린 엑셀에 넣기")]
    return [rt.next_command("word.py", ["write", "--target", "active", "--file", output_file],
                            "저장한 내용을 열린 워드 문서 끝에 넣기"),
            rt.next_command("ppt.py", ["write", "--target", "active", "--file", output_file],
                            "저장한 내용을 열린 PPT에 새 슬라이드로 넣기")]


# ==============================================================================
# 4. 명령: read
# ==============================================================================

def cmd_read(args) -> Dict[str, Any]:
    path = rt.resolve_input_path(args.file, "문서 파일")
    doc = load_document(path)
    units = doc["units"]
    total = len(units)
    selected_numbers = parse_pages(args.pages, total) if total else []
    selected = [units[n - 1] for n in selected_numbers]
    name = os.path.basename(path)
    unit_name = UNIT_NAMES.get(doc["type"], "항목")
    result: Dict[str, Any] = {"file": path, "type": doc["type"], "units_total": total,
                              "unit_name": unit_name, "meta": doc.get("meta", {})}

    if args.save:
        if str(args.save).lower().endswith(".csv"):
            out = rt.resolve_output_path(args.save, os.path.splitext(name)[0], ".csv")
            out = rt.write_csv_rows(out, [["위치", "제목", "내용"]] + [[u["loc"], u["heading"], u["text"]] for u in selected])
        else:
            save_arg = None if args.save is True else args.save
            out = rt.resolve_output_path(save_arg, os.path.splitext(name)[0], ".md")
            out = rt.write_text(out, units_to_markdown(name, selected))
        result.update(output_file=out, next_commands=_write_next_commands(out))
        preview = f"{name}: {len(selected)}개 {unit_name}을(를) 파일로 저장했습니다 ({out})"
        return rt.ok(TOOL, "read", preview, "VERIFIED: 저장 완료. 다른 문서에 넣으려면 next_commands를 그대로 실행하세요.", **result)

    if args.format == "summary":
        preview = f"{name}: {doc['type']} 문서, {unit_name} {total}개, 글자 수 {sum(len(u['text']) for u in units)}"
        return rt.ok(TOOL, "read", preview, **result)

    # 본문: 상한까지 담고, 넘으면 다음 구간 명령 제공
    budget = rt.DEFAULT_MAX_CHARS
    shown: List[Dict[str, str]] = []
    used = 0
    for n, u in zip(selected_numbers, selected):
        size = len(u["text"]) + len(u["loc"]) + 8
        if shown and used + size > budget:
            break
        text, _ = rt.clamp_text(u["text"], budget)
        shown.append({"no": n, "loc": u["loc"], "heading": u["heading"], "text": text})
        used += size
    truncated = len(shown) < len(selected)
    result["units"] = shown
    result["truncated"] = truncated
    if truncated:
        nxt = selected_numbers[len(shown)]
        last = selected_numbers[-1]
        result["next_commands"] = [
            rt.next_command("reader.py", ["read", "--file", path, "--pages", f"{nxt}-{last}"], f"나머지 {unit_name} 이어서 읽기"),
            rt.next_command("reader.py", ["read", "--file", path, "--save"], "전체 내용을 파일로 저장 (다른 문서에 넣을 때)"),
        ]
    preview = f"{name}: {unit_name} {len(shown)}개 표시 (전체 {total}개)" + (" - 길이 제한으로 일부만 표시" if truncated else "")
    directive = ("VERIFIED: 읽기 완료. 일부만 표시되었으니 필요하면 next_commands로 이어서 읽으세요."
                 if truncated else "")
    return rt.ok(TOOL, "read", preview, directive, **result)


# ==============================================================================
# 5. 명령: search
# ==============================================================================

def build_matcher(query: str, regex: bool, case_sensitive: bool):
    """검색 조건을 함수로 만듭니다. 'A AND B', 'A OR B' 조합 지원 (AND가 OR보다 먼저 묶임).
    반환: (match_fn(text) -> 강조할 단어 목록 또는 None, 강조용 정규식 목록)"""
    flags = 0 if case_sensitive else re.IGNORECASE
    if regex:
        try:
            pat = re.compile(query, flags)
        except re.error as e:
            raise rt.InputError(f"정규식 오류: {e}")

        def match_regex(text: str):
            m = pat.search(text)
            return [m.group(0)] if m else None
        return match_regex

    groups = [[t.strip() for t in re.split(r"\s+AND\s+", g) if t.strip()] for g in re.split(r"\s+OR\s+", query.strip())]
    groups = [g for g in groups if g]
    if not groups:
        raise rt.InputError("검색어가 비어 있습니다.")

    def norm(s: str) -> str:
        return s if case_sensitive else s.lower()

    def match_terms(text: str):
        t = norm(text)
        for g in groups:
            if all(norm(term) in t for term in g):
                return g
        return None
    return match_terms


def make_snippet(text: str, terms: List[str], context: int, case_sensitive: bool) -> str:
    flags = 0 if case_sensitive else re.IGNORECASE
    first = None
    for term in terms:
        m = re.search(re.escape(term), text, flags)
        if m and (first is None or m.start() < first.start()):
            first = m
    if first is None:
        return text[: context * 2]
    start = max(0, first.start() - context)
    end = min(len(text), first.end() + context)
    snippet = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
    pattern = re.compile("|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)), flags)
    return pattern.sub(lambda m: f"**{m.group(0)}**", snippet).replace("\n", " ")


def _collect_folder(folder: str) -> List[str]:
    files: List[str] = []
    base_depth = folder.rstrip("\\/").count(os.sep)
    for root, dirs, names in os.walk(folder):
        if root.count(os.sep) - base_depth >= MAX_FOLDER_DEPTH:
            dirs[:] = []
        dirs[:] = [d for d in dirs if not d.startswith((".", "~$", "_"))]
        for n in sorted(names):
            if n.startswith(("~$", ".")) or os.path.splitext(n)[1].lower() not in SUPPORTED:
                continue
            files.append(os.path.join(root, n))
            if len(files) >= MAX_FOLDER_FILES:
                rt.log("WARN", f"폴더 검색은 최대 {MAX_FOLDER_FILES}개 파일까지만 합니다.")
                return files
    return files


def _search_targets(file_arg: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """검색 대상 문서를 불러옵니다. (문서 목록, 건너뛴 파일 목록)"""
    docs: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []

    def add(path: str) -> None:
        try:
            docs.append(load_document(path))
        except Exception as e:
            skipped.append({"file": path, "reason": str(e)})

    if file_arg:
        raw = os.path.expandvars(str(file_arg).strip().strip('"'))
        if os.path.isdir(raw):
            for p in _collect_folder(os.path.abspath(raw)):
                add(p)
        else:
            add(rt.resolve_input_path(raw, "검색할 파일"))
        return docs, skipped

    index = load_index()
    if not index:
        raise rt.InputError("아직 읽은 문서가 없어 검색할 대상이 없습니다. reader.py read --file 로 문서를 먼저 읽거나, "
                            "--file에 파일이나 폴더를 지정하세요.")
    for path in sorted(index, key=lambda p: index[p].get("parsed_at", ""), reverse=True):
        if os.path.exists(path):
            add(path)
        else:
            cached = load_cached_only(path)
            if cached:
                cached["file_missing"] = True
                docs.append(cached)
    return docs, skipped


def cmd_search(args) -> Dict[str, Any]:
    matcher = build_matcher(args.query, args.regex, args.case_sensitive)
    docs, skipped = _search_targets(args.file)
    hits: List[Dict[str, Any]] = []
    for doc in docs:
        for u in doc["units"]:
            terms = matcher(u["text"])
            if terms is None:
                continue
            hits.append({"file": doc["file"], "loc": u["loc"], "heading": u.get("heading", ""),
                         "snippet": make_snippet(u["text"], terms, args.context, args.case_sensitive),
                         "text": u["text"], "file_missing": bool(doc.get("file_missing"))})

    total = len(hits)
    shown = hits[: args.top]
    result: Dict[str, Any] = {"query": args.query, "files_searched": len(docs), "total_matches": total,
                              "matched": len(shown)}
    if skipped:
        result["skipped"] = skipped[:20]

    if args.save and hits:
        stem = "search_" + re.sub(r"[^\w가-힣]+", "_", args.query)[:30].strip("_")
        if str(args.save).lower().endswith(".csv"):
            out = rt.resolve_output_path(args.save, stem, ".csv")
            out = rt.write_csv_rows(out, [["파일", "위치", "제목", "내용"]] +
                                    [[os.path.basename(h["file"]), h["loc"], h["heading"], h["text"]] for h in shown])
        else:
            save_arg = None if args.save is True else args.save
            out = rt.resolve_output_path(save_arg, stem, ".md")
            lines = [f"# 검색 결과: {args.query}", ""]
            for h in shown:
                lines += [f"## {os.path.basename(h['file'])} > {h['loc']}" + (f" ({h['heading']})" if h["heading"] else ""),
                          "", h["text"] if args.full else h["snippet"].replace("**", ""), ""]
            out = rt.write_text(out, "\n".join(lines))
        result.update(output_file=out, next_commands=_write_next_commands(out))

    view = []
    for h in shown:
        item = {"file": os.path.basename(h["file"]), "path": h["file"], "loc": h["loc"],
                "heading": h["heading"], "snippet": h["snippet"]}
        if args.full:
            item["text"], _ = rt.clamp_text(h["text"], 2000)
        if h["file_missing"]:
            item["file_missing"] = True
        view.append(item)
    result["matches"] = view

    if total == 0:
        preview = f"'{args.query}': 문서 {len(docs)}개에서 일치 항목 없음"
        return rt.ok(TOOL, "search", preview,
                     "VERIFIED: 일치 항목이 없습니다. 검색어를 임의로 바꿔 재시도하지 말고 사용자에게 결과를 알리세요.", **result)
    preview = f"'{args.query}': 문서 {len(docs)}개에서 {total}건 일치" + (f" (상위 {len(shown)}건 표시)" if total > len(shown) else "")
    if "output_file" in result:
        preview += f", 저장: {result['output_file']}"
        directive = "VERIFIED: 검색과 저장 완료. 다른 문서에 넣으려면 next_commands를 그대로 실행하세요."
    else:
        directive = "VERIFIED: 검색 완료. 결과를 다른 문서에 넣으려면 같은 검색에 --save를 붙여 파일로 저장한 뒤 넘기세요."
    return rt.ok(TOOL, "search", preview, directive, **result)


# ==============================================================================
# 6. 명령: list
# ==============================================================================

def cmd_list(args) -> Dict[str, Any]:
    index = load_index()
    items = []
    for path, info in sorted(index.items(), key=lambda kv: kv[1].get("parsed_at", ""), reverse=True):
        items.append({"file": os.path.basename(path), "path": path, "type": info.get("type"),
                      "units": info.get("units"), "chars": info.get("chars"),
                      "read_at": info.get("parsed_at"), "exists": os.path.exists(path)})
    shown = items[:100]
    preview = f"읽은 문서 {len(items)}개" + (" (최근 100개 표시)" if len(items) > 100 else "")
    return rt.ok(TOOL, "list", preview, documents=shown, total=len(items))


# ==============================================================================
# 7. 진입점
# ==============================================================================

def build_cli():
    parser, sub = rt.build_parser(TOOL, "문서 파일 읽기와 검색 (Office 불필요)")

    p = sub.add_parser("read", help="파일 하나 읽기")
    p.add_argument("--file", "-f", required=True, help="문서 경로 (파일명만 쓰면 data 폴더에서 찾음)")
    p.add_argument("--pages", "-p", help="페이지/슬라이드 번호 (그 외 형식은 항목 번호). 예: 3, 1-3, 1,4")
    p.add_argument("--format", choices=["text", "summary"], default="text", help="text: 본문, summary: 요약 정보만")
    p.add_argument("--save", nargs="?", const=True, help="결과를 파일로 저장 (.md 기본, .csv 가능). 경로 생략 시 작업 폴더")

    s = sub.add_parser("search", help="읽은 문서 전체 또는 지정 파일/폴더에서 검색")
    s.add_argument("--query", "-q", required=True, help="검색어. 'A AND B', 'A OR B' 사용 가능")
    s.add_argument("--file", "-f", help="검색할 파일 또는 폴더 (생략 시 읽은 적 있는 문서 전체)")
    s.add_argument("--regex", "-r", action="store_true", help="정규식으로 검색")
    s.add_argument("--case-sensitive", "-c", action="store_true", help="대소문자 구분")
    s.add_argument("--top", "-n", type=int, default=10, help="표시할 최대 건수 (기본 10)")
    s.add_argument("--context", "-C", type=int, default=80, help="스니펫 앞뒤 글자 수 (기본 80)")
    s.add_argument("--full", action="store_true", help="스니펫 대신 일치한 단락/페이지 전체")
    s.add_argument("--save", nargs="?", const=True, help="결과를 파일로 저장 (.md 기본, .csv 가능)")

    sub.add_parser("list", help="읽은 적 있는 문서 목록")
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    args = build_cli().parse_args(argv)
    handlers = {"read": cmd_read, "search": cmd_search, "list": cmd_list}
    rt.run_cli(TOOL, args.command, lambda: handlers[args.command](args))


if __name__ == "__main__":
    main()
