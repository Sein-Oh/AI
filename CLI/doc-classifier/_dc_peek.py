"""peek: 분류별 표본만 앞부분을 읽어 분류가 맞는지 확인합니다.

- 읽기는 별도 작업 프로세스(`python _dc_peek.py --worker`)가 합니다. 파일마다 시간 상한을 넘기면 그 프로세스를 끝내고
  새로 띄워 다음 파일로 넘어갑니다 (깨진 파일, 거대한 PDF, 응답 없는 파일이 전체를 멈추지 못하게).
- 앞부분만 읽습니다: PDF 1~2쪽, DOCX 앞 단락 20개, PPTX 앞 슬라이드 10장, XLSX 시트 이름 + 첫 10행, HWP/HWPX 미리보기 텍스트,
  TXT/CSV 등 앞 8KB, EML 헤더와 본문 앞부분, 옛 Office(doc/xls/ppt/msg)는 본문 스트림의 글자만 대략.
- 파일은 읽기 전용으로, 다른 프로세스의 읽기·쓰기를 막지 않는 방식(Python open, zipfile, pymupdf)으로만 엽니다. 원본은 바꾸지 않습니다.
- 클라우드 자리표시자/오프라인/링크(no_read)는 절대 열지 않습니다. 열기 직전에도 속성을 다시 확인합니다.
"""
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
import zipfile
from typing import Any, Dict, List, Optional, Tuple

MAX_CHARS = 20000          # 판정에 쓰는 글자 수 상한
EXCERPT_CHARS = 200        # DB에 남기는 발췌 길이
TEXT_BYTES = 8192          # 텍스트 파일은 앞 8KB만
DOCX_PARAS, PPTX_SLIDES, XLSX_SHEETS, XLSX_ROWS, PDF_PAGES = 20, 10, 5, 10, 2

# 확장자 -> 읽는 방법
READERS = {
    ".pdf": "pdf", ".docx": "docx", ".docm": "docx", ".dotx": "docx",
    ".pptx": "pptx", ".pptm": "pptx", ".ppsx": "pptx", ".potx": "pptx",
    ".xlsx": "xlsx", ".xlsm": "xlsx", ".xltx": "xlsx",
    ".hwp": "hwp", ".hwpx": "hwpx",
    ".txt": "text", ".md": "text", ".csv": "text", ".tsv": "text", ".log": "text", ".json": "text", ".xml": "text",
    ".html": "html", ".htm": "html",
    ".eml": "eml",
    ".doc": "ole", ".xls": "ole", ".ppt": "ole", ".msg": "ole",
}
ZIP_READERS = {"docx", "pptx", "xlsx", "hwpx"}
OLE_READERS = {"hwp", "ole"}

ZIP_SIG = b"PK\x03\x04"
OLE_SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# 확장자만으로 분류하는 카테고리(예: 도면, 이미지)의 형식 확인용 파일 서명
MAGIC = {
    ".dwg": [b"AC10", b"AC1."], ".dxf": [b"  0", b"0\r\n", b"0\n", b"999", b"AutoCAD Binary DXF"],
    ".jpg": [b"\xff\xd8\xff"], ".jpeg": [b"\xff\xd8\xff"], ".png": [b"\x89PNG\r\n\x1a\n"], ".gif": [b"GIF87a", b"GIF89a"],
    ".bmp": [b"BM"], ".tif": [b"II*\x00", b"MM\x00*"], ".tiff": [b"II*\x00", b"MM\x00*"], ".webp": [b"RIFF"],
    ".zip": [ZIP_SIG, b"PK\x05\x06"], ".7z": [b"7z\xbc\xaf\x27\x1c"], ".rar": [b"Rar!\x1a\x07"], ".egg": [b"EGGA"],
    ".alz": [b"ALZ\x01"], ".gz": [b"\x1f\x8b"], ".tgz": [b"\x1f\x8b"], ".pdf": [b"%PDF"],
    ".docx": [ZIP_SIG], ".xlsx": [ZIP_SIG], ".pptx": [ZIP_SIG], ".hwpx": [ZIP_SIG],
    ".doc": [OLE_SIG], ".xls": [OLE_SIG], ".ppt": [OLE_SIG], ".hwp": [OLE_SIG], ".msg": [OLE_SIG],
    ".mp3": [b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"], ".mp4": [], ".exe": [b"MZ"], ".dll": [b"MZ"],
}

FA_OFFLINE, FA_RECALL_ON_OPEN, FA_RECALL_ON_DATA_ACCESS = 0x1000, 0x40000, 0x400000
CLOUD_ATTRS = FA_OFFLINE | FA_RECALL_ON_OPEN | FA_RECALL_ON_DATA_ACCESS


class PeekError(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"[ \t\r\f\v\x00]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def excerpt(text: str, n: int = EXCERPT_CHARS) -> str:
    return re.sub(r"\s+", " ", text).strip()[:n]


# ==============================================================================
# 1. 형식별 "앞부분만" 읽기 (작업 프로세스 안에서 실행)
# ==============================================================================

def _decode(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="ignore")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="ignore")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        if e.start >= len(raw) - 3:                       # 앞 8KB로 자르다 글자 중간에서 끊긴 경우
            return raw[:e.start].decode("utf-8", errors="ignore")
    try:
        return raw.decode("cp949")
    except UnicodeDecodeError:
        return raw.decode("cp949", errors="ignore")


def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        return _decode(f.read(TEXT_BYTES))


def _read_html(path: str) -> str:
    from html import unescape
    html = _read_text(path)
    html = re.sub(r"(?is)<(script|style).*?(</\1>|$)", " ", html)
    return unescape(re.sub(r"<[^>]+>", " ", html))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_texts(stream: Any, para_tag: str, text_tag: str, limit_paras: int, out: List[str]) -> None:
    """XML을 처음부터 흘려 읽으며 문단(para_tag)별 글자(text_tag)를 모읍니다. 상한에 닿으면 나머지는 읽지 않습니다."""
    import xml.etree.ElementTree as ET
    buf: List[str] = []
    paras = 0
    for event, elem in ET.iterparse(stream, events=("end",)):
        tag = _local(elem.tag)
        if tag == text_tag and elem.text:
            buf.append(elem.text)
        elif tag == para_tag:
            line = "".join(buf).strip()
            buf = []
            if line:
                out.append(line)
                paras += 1
                if paras >= limit_paras or sum(len(x) for x in out) >= MAX_CHARS:
                    return
            elem.clear()


def _read_docx(path: str) -> str:
    out: List[str] = []
    with zipfile.ZipFile(path) as z:
        with z.open("word/document.xml") as f:
            _xml_texts(f, "p", "t", DOCX_PARAS, out)
    return "\n".join(out)


def _read_pptx(path: str) -> str:
    out: List[str] = []
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.sub(r"\D", "", n)))
        for name in slides[:PPTX_SLIDES]:
            with z.open(name) as f:
                _xml_texts(f, "p", "t", 200, out)
            if sum(len(x) for x in out) >= MAX_CHARS:
                break
    return "\n".join(out)


def _read_xlsx(path: str) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out: List[str] = []
    try:
        for ws in wb.worksheets[:XLSX_SHEETS]:
            out.append(f"[시트] {ws.title}")
            n = 0
            for row in ws.iter_rows(values_only=True):
                cells = [str(v) for v in row if v is not None and str(v).strip()]
                if cells:
                    out.append(" ".join(cells))
                    n += 1
                    if n >= XLSX_ROWS:
                        break
    finally:
        wb.close()
    return "\n".join(out)


def _read_pdf(path: str) -> str:
    import pymupdf
    try:
        pymupdf.TOOLS.mupdf_display_errors(False)
    except Exception:
        pass
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        raise PeekError("encrypted_or_drm", f"PDF를 열 수 없음 (DRM/손상 가능): {type(e).__name__}")
    try:
        if doc.needs_pass:
            raise PeekError("encrypted_or_drm", "암호가 걸린 PDF")
        return "\n".join(doc[i].get_text("text") for i in range(min(PDF_PAGES, doc.page_count)))
    finally:
        doc.close()


_HWP_CHAR_CONTROLS = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}


def _hwp_para_text(rec: bytes) -> str:
    out: List[str] = []
    i, n = 0, len(rec)
    while i + 1 < n:
        code = rec[i] | (rec[i + 1] << 8)
        if code >= 32:
            out.append(chr(code))
            i += 2
        elif code in _HWP_CHAR_CONTROLS:
            out.append("\n" if code == 10 else (" " if code in (30, 31) else ""))
            i += 2
        else:
            if code == 9:
                out.append("\t")
            i += 16
    return "".join(out)


def _read_hwp(path: str) -> str:
    """HWP 5.0: 미리보기 텍스트(PrvText, 본문 앞부분 약 1천 자)를 먼저, 없으면 첫 구역 본문 앞부분."""
    import olefile
    import zlib
    ole = olefile.OleFileIO(path)
    try:
        header = ole.openstream("FileHeader").read() if ole.exists("FileHeader") else b""
        if not header.startswith(b"HWP Document File"):
            raise PeekError("encrypted_or_drm", "HWP 파일 머리가 없음 (DRM/다른 형식 가능)")
        props = int.from_bytes(header[36:40], "little") if len(header) >= 40 else 0
        if ole.exists("PrvText"):
            text = ole.openstream("PrvText").read().decode("utf-16-le", errors="ignore")
            if text.strip():
                return text
        if props & 0x2:
            raise PeekError("encrypted_or_drm", "암호가 걸린 HWP")
        if props & 0x4:
            raise PeekError("encrypted_or_drm", "배포용 HWP (본문 암호화)")
        if not ole.exists("BodyText/Section0"):
            return ""
        data = ole.openstream("BodyText/Section0").read()
        if props & 0x1:
            d = zlib.decompressobj(-15)
            data = d.decompress(data, 4 * 1024 * 1024)
        out: List[str] = []
        pos = 0
        while pos + 4 <= len(data) and sum(len(x) for x in out) < MAX_CHARS:
            h = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
            tag, size = h & 0x3FF, (h >> 20) & 0xFFF
            if size == 0xFFF:
                size = int.from_bytes(data[pos:pos + 4], "little")
                pos += 4
            if tag == 67:
                t = _hwp_para_text(data[pos:pos + size]).strip()
                if t:
                    out.append(t)
            pos += size
        return "\n".join(out)
    finally:
        ole.close()


def _read_hwpx(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "Preview/PrvText.txt" in names:
            text = _decode(z.read("Preview/PrvText.txt")[:65536])
            if text.strip():
                return text
        sections = sorted((n for n in names if re.match(r"Contents/section\d+\.xml$", n)),
                          key=lambda n: int(re.sub(r"\D", "", n)))
        if not sections:
            raise PeekError("unreadable", "HWPX 본문이 없음")
        out: List[str] = []
        with z.open(sections[0]) as f:
            _xml_texts(f, "p", "t", DOCX_PARAS, out)
        return "\n".join(out)


def _read_eml(path: str) -> str:
    import email
    from email import policy
    with open(path, "rb") as f:
        raw = f.read(65536)
    msg = email.message_from_bytes(raw, policy=policy.default)
    out = []
    for key in ("subject", "from", "to"):
        try:
            v = msg.get(key)
        except Exception:
            v = None
        if v:
            out.append(str(v))
    try:
        body = msg.get_body(preferencelist=("plain", "html"))
        if body is not None:
            content = body.get_content()
            if body.get_content_type() == "text/html":
                content = re.sub(r"<[^>]+>", " ", content)
            out.append(content[:MAX_CHARS])
    except Exception:
        pass
    return "\n".join(out)


# 옛 Office 바이너리(OLE)에서 본문이 들어 있는 스트림
_OLE_STREAMS = {".doc": ["WordDocument"], ".xls": ["Workbook", "Book"], ".ppt": ["PowerPoint Document"],
                ".msg": ["__substg1.0_0037001F", "__substg1.0_1000001F", "__substg1.0_0E1D001F"]}
_UTF16_RUN = re.compile(rb"(?:[\x20-\x7e\t\r\n]\x00|[\x00-\xff][\xac-\xd7]|[\x00-\xff][\x31\x30]\x00?){3,}")
_ASCII_RUN = re.compile(rb"[A-Za-z][\x20-\x7e]{7,}")


def _read_ole(path: str, ext: str) -> str:
    """doc/xls/ppt/msg: 형식을 해석하지 않고 본문 스트림에서 글자(UTF-16 한글·영문, ASCII 영문)만 대략 뽑습니다."""
    import olefile
    ole = olefile.OleFileIO(path)
    try:
        if ole.exists("EncryptedPackage") or ole.exists("EncryptionInfo"):
            raise PeekError("encrypted_or_drm", "암호가 걸린 Office 문서")
        out: List[str] = []
        for name in _OLE_STREAMS.get(ext, []):
            if not ole.exists(name):
                continue
            data = ole.openstream(name).read(2 * 1024 * 1024)
            if name.endswith("001F"):
                out.append(data.decode("utf-16-le", errors="ignore"))
                continue
            for m in _UTF16_RUN.finditer(data):
                chunk = m.group(0)
                if len(chunk) % 2:
                    chunk = chunk[:-1]
                s = chunk.decode("utf-16-le", errors="ignore")
                if re.search(r"[가-힣]", s) or len(s) >= 6:
                    out.append(s)
            for m in _ASCII_RUN.finditer(data):
                s = m.group(0).decode("ascii")
                if " " in s:
                    out.append(s)
            if sum(len(x) for x in out) >= MAX_CHARS:
                break
        return "\n".join(out)
    finally:
        ole.close()


def check_signature(path: str, ext: str) -> Tuple[Optional[bool], bytes]:
    """파일 앞부분 서명이 확장자와 맞는지 (None이면 알 수 없는 확장자)."""
    with open(path, "rb") as f:
        head = f.read(1024)
    sigs = MAGIC.get(ext)
    if not sigs:
        return None, head
    if ext == ".pdf":
        return b"%PDF" in head, head
    return any(head.startswith(s) for s in sigs), head


def read_head(path: str, ext: str, mode: str) -> Dict[str, Any]:
    """파일 하나를 읽어 {"status": "ok", "text", "method"} 또는 {"status": 오류, "reason"}."""
    try:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return {"status": "missing", "reason": "파일이 없어짐 (목록화 이후 이동/삭제)"}
        attrs = int(getattr(st, "st_file_attributes", 0) or 0)
        if attrs & CLOUD_ATTRS:
            return {"status": "skipped", "reason": "클라우드 자리표시자/오프라인 (열지 않음)"}
        if st.st_size == 0:
            return {"status": "no_text", "reason": "빈 파일", "method": "size"}
        if mode == "signature":
            ok, head = check_signature(path, ext)
            if ok is None:
                return {"status": "not_checked", "reason": "형식 서명을 모르는 확장자", "method": "signature"}
            if ok:
                return {"status": "ok", "text": "", "method": "signature"}
            return {"status": "unreadable", "reason": f"파일 서명이 {ext} 형식과 다름 (DRM/손상/확장자 오류 가능)",
                    "method": "signature"}
        reader = READERS.get(ext)
        if not reader:
            return {"status": "skipped", "reason": "내용을 읽지 않는 형식"}
        if reader in ZIP_READERS or reader in OLE_READERS or reader == "pdf":
            _, head = check_signature(path, ext)
            if reader in ZIP_READERS and not head.startswith(ZIP_SIG):
                if head.startswith(OLE_SIG):
                    return {"status": "encrypted_or_drm", "reason": "암호/보안이 걸린 Office 문서 (OLE로 감싸짐)"}
                return {"status": "encrypted_or_drm", "reason": "ZIP 형식이 아님 (DRM으로 암호화/손상 가능)"}
            if reader in OLE_READERS and not head.startswith(OLE_SIG):
                return {"status": "encrypted_or_drm", "reason": "OLE 형식이 아님 (DRM으로 암호화/손상 가능)"}
            if reader == "pdf" and b"%PDF" not in head:
                return {"status": "encrypted_or_drm", "reason": "PDF 머리가 없음 (DRM으로 암호화/손상 가능)"}
        fn = {"pdf": _read_pdf, "docx": _read_docx, "pptx": _read_pptx, "xlsx": _read_xlsx, "hwp": _read_hwp,
              "hwpx": _read_hwpx, "text": _read_text, "html": _read_html, "eml": _read_eml}.get(reader)
        text = _read_ole(path, ext) if reader == "ole" else fn(path)
        text = _clean(text)[:MAX_CHARS]
        if not text:
            return {"status": "no_text", "reason": "글자가 없음 (스캔 이미지 PDF 등)", "method": reader}
        return {"status": "ok", "text": text, "method": reader}
    except PeekError as e:
        return {"status": e.status, "reason": e.reason}
    except ImportError as e:
        return {"status": "unreadable", "reason": f"라이브러리 없음: {e.name} (python -m pip install {e.name})"}
    except (zipfile.BadZipFile, KeyError) as e:
        return {"status": "unreadable", "reason": f"손상되었거나 형식이 다름: {type(e).__name__}"}
    except PermissionError:
        return {"status": "unreadable", "reason": "권한 없음 또는 다른 프로세스가 독점 중"}
    except MemoryError:
        return {"status": "unreadable", "reason": "메모리 부족"}
    except Exception as e:
        return {"status": "unreadable", "reason": f"{type(e).__name__}: {str(e)[:120]}"}


def worker_main() -> None:
    """작업 프로세스: stdin 한 줄(JSON 요청) -> stdout 한 줄(JSON 결과). stdout은 이 통신에만 씁니다."""
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    try:
        os.dup2(2, 1)                    # 라이브러리가 C 수준에서 stdout에 쓰는 글이 통신을 깨지 않게 stderr로
    except OSError:
        pass
    sys.stdout = sys.stderr
    try:
        import _dc_scan
        _dc_scan.set_background_priority()
    except Exception:
        pass
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        req = json.loads(line.decode("utf-8"))
        res = read_head(req["path"], req["ext"], req.get("mode", "text"))
        proto.write(json.dumps(res, ensure_ascii=True) + "\n")
        proto.flush()


# ==============================================================================
# 2. 작업 프로세스 관리 (본 프로세스)
# ==============================================================================

class WorkerPool:
    """작업 프로세스 1개. 요청마다 시간 상한을 두고, 넘기면 끝내고 다음 요청 때 새로 띄웁니다."""

    def __init__(self, verbose: bool = False):
        self.proc: Optional[subprocess.Popen] = None
        self.lines: "queue.Queue[Optional[bytes]]" = queue.Queue()
        self.verbose = verbose
        self.restarts = 0

    def command(self) -> List[str]:
        return [sys.executable, os.path.abspath(__file__), "--worker"]

    def _start(self) -> None:
        cmd = self.command()
        flags = 0x08000000 if sys.platform == "win32" else 0          # CREATE_NO_WINDOW
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=None if self.verbose else subprocess.DEVNULL,
                                     creationflags=flags, env=env, cwd=os.path.dirname(os.path.abspath(__file__)))
        q: "queue.Queue[Optional[bytes]]" = queue.Queue()
        self.lines = q
        out = self.proc.stdout

        def pump() -> None:
            try:
                for ln in out:
                    q.put(ln)
            except Exception:
                pass
            q.put(None)
        threading.Thread(target=pump, daemon=True).start()

    def _kill(self) -> None:
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=10)
            except Exception:
                pass
            self.proc = None

    def ask(self, path: str, ext: str, mode: str, timeout: float) -> Dict[str, Any]:
        if self.proc is None or self.proc.poll() is not None:
            self._start()
        assert self.proc is not None and self.proc.stdin is not None
        try:
            self.proc.stdin.write((json.dumps({"path": path, "ext": ext, "mode": mode}) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError:
            self._kill()
            return {"status": "unreadable", "reason": "읽는 프로세스와 통신 실패"}
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            self._kill()
            self.restarts += 1
            return {"status": "timeout", "reason": f"{timeout:g}초 안에 읽지 못함 (거대/손상/응답 없는 파일)"}
        if line is None:
            self._kill()
            self.restarts += 1
            return {"status": "unreadable", "reason": "읽는 중 프로세스가 비정상 종료 (손상된 파일 가능)"}
        try:
            return json.loads(line.decode("utf-8"))
        except ValueError:
            return {"status": "unreadable", "reason": "읽는 프로세스 응답 오류"}

    def close(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self._kill()
        self.proc = None


# ==============================================================================
# 3. 표본 고르기, 판정, 실행 (본 프로세스)
# ==============================================================================

JUDGED = ("confirmed", "changed", "no_match")          # 확인율 계산에 넣는 판정
STATUS_TEXT = {"confirmed": "맞음", "changed": "다른 분류 제안", "no_match": "본문에 키워드 없음", "no_text": "글자 없음",
               "encrypted_or_drm": "암호/DRM", "unreadable": "읽기 실패", "timeout": "시간 초과", "missing": "파일 없음",
               "skipped": "열지 않음", "not_checked": "확인 불가"}


def select_samples(con: Any, rules: Any, per_category: int, max_files: int, max_bytes: int) -> List[Dict[str, Any]]:
    """카테고리마다 아직 확인하지 않은 표본을 고릅니다. 신뢰도 low -> medium -> high 순, 여러 폴더에 고르게 퍼지도록
    id를 섞은 순서로. 전체 상한(max_files)은 카테고리를 돌아가며 하나씩 배분합니다."""
    import _dc_rules as ru
    readable = sorted(READERS)
    queues: List[List[Dict[str, Any]]] = []
    for cat in rules.names + [ru.UNCLASSIFIED]:
        done = con.execute("SELECT COUNT(*) FROM files WHERE category=? AND peek_status IS NOT NULL", (cat,)).fetchone()[0]
        need = per_category - done
        if need <= 0:
            continue
        cobj = rules.by_name.get(cat)
        sig_exts = sorted(cobj.exts) if cobj else []
        exts = sorted(set(readable) | set(sig_exts))
        marks = ",".join("?" * len(exts))
        rows = con.execute(
            "SELECT f.id, d.path, f.name, f.ext, f.size, f.confidence FROM files f JOIN dirs d ON d.id = f.dir_id "
            f"WHERE f.category=? AND f.no_read=0 AND f.peek_status IS NULL AND f.ext IN ({marks}) AND f.size <= ? "
            "AND COALESCE(f.kind, '') <> '임시/시스템' "
            "ORDER BY CASE f.confidence WHEN 'low' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, (f.id * 2654435761) % 4294967311 "
            "LIMIT ?", (cat, *exts, max_bytes, need)).fetchall()
        q = [{"id": r[0], "dir": r[1], "name": r[2], "ext": r[3], "size": r[4], "category": cat,
              "mode": "signature" if r[3] in sig_exts else "text"} for r in rows]
        if q:
            queues.append(q)
    picked: List[Dict[str, Any]] = []
    while queues and len(picked) < max_files:
        for q in list(queues):
            if len(picked) >= max_files:
                break
            picked.append(q.pop(0))
            if not q:
                queues.remove(q)
    picked.sort(key=lambda s: (s["dir"], s["name"]))          # 같은 폴더끼리 이어서 읽기 (디스크 이동 줄이기)
    return picked


def judge(res: Dict[str, Any], category: str, mode: str, rules: Any) -> Tuple[str, Optional[str], str]:
    """(판정, 제안 카테고리, 이유)."""
    status = res.get("status")
    if status != "ok":
        return status or "unreadable", None, res.get("reason") or ""
    if mode == "signature":
        return "confirmed", None, "파일 형식 서명이 확장자와 일치"
    hits = rules.text_hits(res.get("text") or "")
    names = rules.names
    ci = names.index(category) if category in names else None
    own = hits.get(ci, []) if ci is not None else []
    others = sorted(((len(v), -k) for k, v in hits.items() if k != ci), reverse=True)
    if own and (not others or len(own) >= others[0][0]):
        return "confirmed", None, "본문 키워드: " + ", ".join(own[:5])
    if others:
        k = -others[0][1]
        return "changed", names[k], f"본문에 '{names[k]}' 키워드가 더 많음: " + ", ".join(hits[k][:5])
    return "no_match", None, "본문 앞부분에 규칙 키워드가 없음"


def run(con: Any, rules: Any, samples: List[Dict[str, Any]], timeout: float, time_limit: Optional[float],
        throttle_ms: int, log: Any, full_path: Any) -> Dict[str, Any]:
    """표본을 읽고 판정해 기록합니다. 몇 개씩 묶어 커밋하므로 중단돼도 읽은 것은 남습니다."""
    pool = WorkerPool(verbose=os.environ.get("DOCCLS_VERBOSE", "") not in ("", "0", "false", "False"))
    start = last_flush = last_log = time.time()
    updates: List[Tuple[Any, ...]] = []
    counts: Dict[str, int] = {}
    stopped: Optional[str] = None

    def flush() -> None:
        nonlocal updates, last_flush
        if updates:
            con.execute("BEGIN")
            con.executemany("UPDATE files SET peek_status=?, peek_excerpt=?, peek_category=?, peek_reason=?, peek_ms=? "
                            "WHERE id=?", updates)
            con.execute("COMMIT")
            updates = []
        last_flush = time.time()

    try:
        for i, s in enumerate(samples, 1):
            if time_limit is not None and time.time() - start >= time_limit:
                stopped = "time_limit"
                break
            path = full_path(s["dir"], s["name"])
            t0 = time.time()
            res = pool.ask(path, s["ext"], s["mode"], timeout)
            ms = int((time.time() - t0) * 1000)
            status, suggested, reason = judge(res, s["category"], s["mode"], rules)
            counts[status] = counts.get(status, 0) + 1
            updates.append((status, excerpt(res.get("text") or "") or None, suggested, reason[:300] or None, ms, s["id"]))
            now = time.time()
            if len(updates) >= 20 or now - last_flush >= 2:
                flush()
            if now - last_log >= 2:
                last_log = now
                log("PROGRESS", f"표본 {i}/{len(samples)}개 확인 ({now - start:.0f}초): "
                                + ", ".join(f"{STATUS_TEXT.get(k, k)} {v}" for k, v in counts.items()))
            if throttle_ms:
                time.sleep(throttle_ms / 1000.0)
    except KeyboardInterrupt:
        stopped = "interrupted"
    finally:
        pool.close()
        flush()
    seconds = round(time.time() - start, 1)
    return {"files": sum(counts.values()), "by_status": counts, "seconds": seconds, "stopped": stopped,
            "worker_restarts": pool.restarts}


def category_stats(con: Any, rules: Any) -> List[Dict[str, Any]]:
    """카테고리별 확인 결과 (지금까지 확인한 표본 전체)."""
    import _dc_rules as ru
    stats: Dict[str, Dict[str, Any]] = {}
    for cat, status, n in con.execute("SELECT category, peek_status, COUNT(*) FROM files WHERE peek_status IS NOT NULL "
                                      "GROUP BY category, peek_status"):
        s = stats.setdefault(cat, {"category": cat, "sampled": 0})
        s["sampled"] += n
        s[status] = s.get(status, 0) + n
    for cat, sugg, n in con.execute("SELECT category, peek_category, COUNT(*) FROM files WHERE peek_status='changed' "
                                    "GROUP BY category, peek_category ORDER BY 3 DESC"):
        stats[cat].setdefault("suggested", {})[sugg] = n
    order = {n: i for i, n in enumerate(rules.names + [ru.UNCLASSIFIED])}
    out = []
    for s in sorted(stats.values(), key=lambda s: order.get(s["category"], 999)):
        judged = sum(s.get(k, 0) for k in JUDGED)
        s["judged"] = judged
        s["confirm_rate"] = round(s.get("confirmed", 0) / judged, 2) if judged else None
        out.append(s)
    return out


if __name__ == "__main__" and "--worker" in sys.argv:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    worker_main()
