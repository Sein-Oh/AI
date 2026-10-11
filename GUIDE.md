# [Office Visual Agent] 폐쇄망 환경 구축 및 구현 완벽 가이드
> **문서 버전:** 1.0  
> **대상 LLM / 개발자:** 사내 구축형 온프레미스 LLM (Gemma 4 26B 등) 및 폐쇄망 시스템 엔지니어  
> **목적:** 최소한의 반입 자원(Python Wheel, LibreOffice Portable)만으로 고속 인메모리 오피스 조작 및 초경량 실시간 시각 뷰포트 시스템을 100% 무결점으로 재구축

---

## 1. 프로젝트 핵심 철학 및 이전 실패의 교훈 (반드시 준수할 원칙)

이 프로젝트는 기존 MS Office 자동화의 치명적 결함을 극복하기 위해 설계되었습니다. 구현 시 아래 원칙을 반드시 지켜야 합니다.

1. **Win32 COM 사용 금지 (Zero Win32 COM)**:
   - Windows COM 바인딩의 프로세스 지연, 셀 편집 중 블로킹(Busy), 대화상자 프리징을 원천 배제합니다.
2. **두꺼운 헬퍼 클래스 금지 (No Thick Helpers)**:
   - 헬퍼를 두껍게 만들수록 LLM은 좁은 API 감옥에 갇혀 자율성을 잃습니다. LLM이 세계적으로 검증된 파이썬 표준 라이브러리(`openpyxl`, `python-docx`, `python-pptx`, `pandas`, `matplotlib`)를 직접 다루게 합니다.
3. **도구 과다 세분화 금지 (No Fine-grained MCP Explosion)**:
   - 수십 개의 잘게 쪼갠 도구(예: 셀 수정, 폰트 변경, 표 삽입 등)를 만들지 않습니다. **단 1개의 통합 Code Runner** 또는 파이썬 스크립트 실행 체계로 처리합니다.
4. **리브레오피스는 렌더러로만 사용 (Renderer Only)**:
   - 불안정하고 무거운 LibreOffice UNO 편집 API는 일체 쓰지 않습니다.
   - 오직 `soffice --headless --convert-to pdf` 단일 백그라운드 명령어만 사용하여 100% 인쇄 품질의 고해상도 벡터 PDF를 추출하는 렌더러로만 씁니다.
5. **초경량 뷰포트 (OpenCV Blit)**:
   - 무거운 오피스 GUI나 브라우저 대신, OpenCV(`cv2.imshow`)의 네이티브 메모리 버퍼 표출을 사용하여 **10ms 만에 실시간 시각 피드백**을 제공합니다.
6. **100% 결정론적 정량 비전 진단 (Deterministic Visual Diagnostics)**:
   - 비전 모델(Vision LLM) 토큰을 소모하지 않고, `PyMuPDF`로 벡터 텍스트/좌표를 파싱하여 **셀 너비 부족 마스킹(`###`)과 여백 넘침을 1ms 만에 수학적으로 검출**하고 코드를 자율 교정합니다.

---

## 2. 폐쇄망 최소 반입 자원 목록 (Whitelist Assets)

폐쇄망 내부로 반입해야 하는 자원은 오직 2가지(Python 패키지 Wheel 파일들과 LibreOffice Portable 압축 파일)입니다.

### 2.1 Python 패키지 Wheel (인터넷 망에서 사전 다운로드)
인터넷 PC에서 아래 명령으로 `.whl` 파일들을 수집하여 반입합니다:
```bash
pip download openpyxl python-docx python-pptx pandas opencv-python pymupdf matplotlib -d ./wheels/
```

| 패키지명 | 역할 |
| :--- | :--- |
| `openpyxl` | 엑셀(.xlsx) 인메모리 생성, 셀 서식, 네이티브 차트 생성 |
| `python-docx` | 워드(.docx) 보고서 본문, 테이블, 스타일 서식 생성 |
| `python-pptx` | 파워포인트(.pptx) 프레젠테이션 슬라이드 조작 |
| `pandas` | 초고속 오피스 간 데이터 추출 및 가공 허브 |
| `opencv-python` | 실시간 멀티 탭 GUI 뷰포트 팝업 (`cv2.imshow`) |
| `pymupdf` | PDF 페이지를 초고속(10~30ms)으로 OpenCV BGR 이미지로 래스터화 |
| `matplotlib` | 고해상도 비즈니스 그래프 인메모리 렌더링 (`io.BytesIO`) |

### 2.2 LibreOffice Portable
- 설치가 필요 없는 포터블 버전(약 200MB zip)을 다운로드하여 프로젝트 폴더 내 `LibreOfficePortable/`로 압축 해제합니다.
- 핵심 실행 파일 경로: `LibreOfficePortable/App/libreoffice/program/soffice.com`

---

## 3. 권장 디렉터리 구조

```text
libreoffice_viewer/
│
├── LibreOfficePortable/          # [반입] 내장 리브레오피스 포터블 폴더
│   └── App/libreoffice/program/soffice.com
│
├── wheels/                       # [반입] 오프라인 설치용 패키지 .whl 모음
│
├── src/                          # 핵심 패키지 소스 코드
│   └── office_visual/
│       ├── __init__.py           # 최상위 고수준 API export
│       ├── config.py             # soffice 바이너리 자동 탐색 및 기본 환경 설정
│       ├── renderer.py           # Headless PDF 변환 & PyMuPDF 래스터화
│       ├── inspector.py          # 1ms 정량 비전 진단기 (### 마스킹, 오버플로우 검출)
│       ├── viewport.py           # MultiDocViewer (OpenCV 다중 탭 및 Live 자동감지 뷰포트)
│       ├── runner.py             # Unified Code Runner (코드 실행 ➔ 검사 ➔ 렌더링)
│       ├── cli.py                # 단일 CLI 진입점 (live, preview, check, render)
│       └── __main__.py           # python -m office_visual 진입점
│
├── samples/                      # 작업 및 출력 디렉터리
│   ├── workspace/                # 실시간 뷰어가 감시하는 동적 작업 폴더
│   ├── docs/                     # 원본 오피스 문서 보관함
│   └── outputs/                  # 최종 저장 및 이미지 결과물
│
├── tests/                        # 자동화 검증 스위트
│   ├── test_pipeline.py
│   └── test_self_healing_loop.py
│
├── pyproject.toml                # 패키지 빌드 매니페스트
├── README.md                     # 프로젝트 안내 가이드
└── GUIDE.md                      # [본 문서] 폐쇄망 구현 지침서
```

---

## 4. 소스 코드 구현 명세 (Source Code Implementation)

Gemma 4 26B 또는 개발자가 그대로 구현할 수 있는 전체 핵심 소스 코드입니다.

### 4.1 `pyproject.toml`
```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "office-visual"
version = "0.2.0"
description = "High-speed In-Memory Office Manipulation with Headless LibreOffice Viewport"
authors = [{ name = "Office Visual Agent Team" }]
requires-python = ">=3.10"
dependencies = [
    "openpyxl",
    "python-docx",
    "python-pptx",
    "pandas",
    "opencv-python",
    "pymupdf",
    "matplotlib",
]

[project.scripts]
office-visual = "office_visual.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

---

### 4.2 `src/office_visual/config.py`
LibreOffice의 `soffice` 실행 바이너리를 시스템 PATH 및 로컬 포터블 디렉터리에서 자동 감지합니다.
```python
import os
import shutil
from pathlib import Path

DEFAULT_DPI = 130
MAX_VIEWPORT_HEIGHT = 900
SUPPORTED_EXTENSIONS = {
    ".xlsx", ".xlsm", ".xls", ".csv",
    ".docx", ".doc", ".odt", ".rtf",
    ".pptx", ".ppt", ".odp",
}

def find_soffice_binary() -> Path:
    current_file = Path(__file__).resolve()
    repo_root = current_file.parents[2]

    candidates = [
        repo_root / "LibreOfficePortable" / "App" / "libreoffice" / "program" / "soffice.com",
        repo_root / "LibreOfficePortable" / "App" / "libreoffice" / "program" / "soffice.exe",
        repo_root / "LibreOfficePortable" / "LibreOfficePortable.exe",
        Path(r"C:\Program Files\LibreOffice\program\soffice.com"),
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.com"),
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    which_path = shutil.which("soffice")
    if which_path:
        return Path(which_path)

    raise FileNotFoundError(
        "LibreOffice executable (soffice) not found. "
        "Ensure 'LibreOfficePortable' exists in the workspace root or LibreOffice is installed."
    )
```

---

### 4.3 `src/office_visual/renderer.py`
어떤 오피스 문서든 헤드리스 PDF로 변환하고, PyMuPDF를 통해 수십 밀리초 만에 OpenCV BGR 이미지로 변환합니다.
```python
import tempfile
import subprocess
from pathlib import Path
from typing import Union, List, Optional
import numpy as np
import cv2
import pymupdf

from .config import find_soffice_binary, DEFAULT_DPI, SUPPORTED_EXTENSIONS

def convert_to_pdf(input_path: Union[str, Path], output_dir: Optional[Union[str, Path]] = None) -> Path:
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    soffice = find_soffice_binary()
    out_dir = Path(output_dir).resolve() if output_dir else input_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(soffice),
        "--headless",
        "--convert-to", "pdf",
        "--outdir", str(out_dir),
        str(input_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {result.stderr or result.stdout}")

    expected_pdf = out_dir / f"{input_path.stem}.pdf"
    if not expected_pdf.exists():
        raise FileNotFoundError(f"Converted PDF not found at {expected_pdf}")

    return expected_pdf

def pdf_to_images(pdf_path: Union[str, Path], dpi: int = DEFAULT_DPI) -> List[np.ndarray]:
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = pymupdf.open(str(pdf_path))
    images: List[np.ndarray] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        
        if pix.n == 4:
            bgr = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:
            bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        else:
            bgr = cv2.cvtColor(img_array, cv2.COLOR_GRAY2BGR)
        images.append(bgr)

    doc.close()
    return images

def render_document(input_path: Union[str, Path], dpi: int = DEFAULT_DPI) -> List[np.ndarray]:
    input_path = Path(input_path).resolve()
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = convert_to_pdf(input_path, output_dir=tmpdir)
        images = pdf_to_images(pdf_path, dpi=dpi)
    return images
```

---

### 4.4 `src/office_visual/inspector.py`
비전 모델 없이 수치와 좌표 계산만으로 엑셀 `###` 마스킹과 여백 침범을 1ms 만에 잡아내는 핵심 모듈입니다.
```python
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Union
import pymupdf

from .renderer import convert_to_pdf

@dataclass
class VisualIssue:
    issue_type: str        # CELL_MASKED, HORIZONTAL_OVERFLOW, VERTICAL_OVERFLOW, PAGE_SPILLOVER
    page_number: int
    message: str
    coordinates: Optional[List[float]] = None
    hint: str = ""

@dataclass
class InspectionReport:
    is_valid: bool
    total_pages: int
    issues: List[VisualIssue] = field(default_factory=list)
    document_path: Optional[Path] = None

    def summary(self) -> str:
        if self.is_valid:
            return f"[PASS] Document layout is clean ({self.total_pages} page(s), 0 issues)."
        lines = [f"[FAIL] Document layout has {len(self.issues)} issue(s):"]
        for idx, issue in enumerate(self.issues, 1):
            lines.append(f"  {idx}. [{issue.issue_type}] Page {issue.page_number}: {issue.message}")
            if issue.hint:
                lines.append(f"     -> Recommendation: {issue.hint}")
        return "\n".join(lines)

def inspect_pdf(pdf_path: Union[str, Path], expected_pages: Optional[int] = None, margin_pts: float = 20.0) -> InspectionReport:
    pdf_path = Path(pdf_path).resolve()
    doc = pymupdf.open(str(pdf_path))
    total_pages = len(doc)
    issues: List[VisualIssue] = []

    if expected_pages is not None and total_pages > expected_pages:
        issues.append(VisualIssue(
            issue_type="PAGE_SPILLOVER",
            page_number=total_pages,
            message=f"Document produced {total_pages} pages, but expected at most {expected_pages} page(s).",
            hint=f"Reduce table margins/row heights or set fit-to-page so it fits in {expected_pages} page(s)."
        ))

    for page_idx in range(total_pages):
        page = doc[page_idx]
        page_num = page_idx + 1
        safe_max_x = page.rect.width - margin_pts
        safe_max_y = page.rect.height - margin_pts

        words = page.get_text("words")  # (x0, y0, x1, y1, word, ...)
        for w in words:
            x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
            cleaned_text = text.strip()

            # 1. Excel Cell Masking (###)
            if len(cleaned_text) >= 2 and all(ch == '#' for ch in cleaned_text):
                issues.append(VisualIssue(
                    issue_type="CELL_MASKED",
                    page_number=page_num,
                    message=f"Masked cell content detected ('{cleaned_text}') at position ({x0:.1f}, {y0:.1f}).",
                    coordinates=[round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                    hint="Column width is too narrow. Increase column width in openpyxl by at least 5-10."
                ))

            # 2. Horizontal Overflow
            if x1 > safe_max_x:
                issues.append(VisualIssue(
                    issue_type="HORIZONTAL_OVERFLOW",
                    page_number=page_num,
                    message=f"Text '{text}' exceeds right printable margin ({x1:.1f} > {safe_max_x:.1f}).",
                    coordinates=[round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                    hint="Reduce table width or change page orientation to Landscape."
                ))

            # 3. Vertical Overflow
            if y1 > safe_max_y:
                issues.append(VisualIssue(
                    issue_type="VERTICAL_OVERFLOW",
                    page_number=page_num,
                    message=f"Text '{text}' clipped beyond bottom page margin ({y1:.1f} > {safe_max_y:.1f}).",
                    coordinates=[round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                    hint="Content spilled off page. Adjust font size, reduce row height, or insert proper page breaks."
                ))

    doc.close()
    return InspectionReport(is_valid=(len(issues) == 0), total_pages=total_pages, issues=issues, document_path=pdf_path)

def inspect_document(input_path: Union[str, Path], expected_pages: Optional[int] = None, margin_pts: float = 20.0) -> InspectionReport:
    input_path = Path(input_path).resolve()
    if input_path.suffix.lower() == ".pdf":
        return inspect_pdf(input_path, expected_pages=expected_pages, margin_pts=margin_pts)

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = convert_to_pdf(input_path, output_dir=tmpdir)
        report = inspect_pdf(pdf_path, expected_pages=expected_pages, margin_pts=margin_pts)
        report.document_path = input_path
        return report
```

---

### 4.5 `src/office_visual/viewport.py`
실시간 폴더 감시(Auto-Reload) 및 마우스 클릭/단축키 지원 OpenCV 멀티 탭 뷰포트입니다.
```python
import time
from pathlib import Path
from typing import Union, List, Dict, Optional, Tuple
import numpy as np
import cv2

from .renderer import render_document
from .config import MAX_VIEWPORT_HEIGHT

class MultiDocViewer:
    def __init__(
        self,
        documents: Optional[Dict[str, Union[List[np.ndarray], np.ndarray, str, Path]]] = None,
        window_title: str = "Office Visual Multi-Viewport",
        max_height: int = MAX_VIEWPORT_HEIGHT,
        dpi: int = 130,
        watch_dir: Optional[Union[str, Path]] = None
    ):
        self.window_title = window_title
        self.max_height = max_height
        self.dpi = dpi
        self.watch_dir = Path(watch_dir).resolve() if watch_dir else None

        self.docs: Dict[str, List[np.ndarray]] = {}
        self.file_sources: Dict[str, Path] = {}
        self.file_mtimes: Dict[str, float] = {}

        if documents:
            for name, item in documents.items():
                if isinstance(item, (str, Path)):
                    p = Path(item).resolve()
                    self.file_sources[name] = p
                    self.file_mtimes[name] = p.stat().st_mtime if p.exists() else 0.0
                    self.docs[name] = render_document(p, dpi=self.dpi)
                elif isinstance(item, np.ndarray):
                    self.docs[name] = [item]
                elif isinstance(item, list):
                    self.docs[name] = item

        if self.watch_dir and self.watch_dir.exists():
            for f in sorted(self.watch_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in [".xlsx", ".docx", ".pptx"] and not f.name.startswith("~"):
                    if f.name not in self.file_sources:
                        self.file_sources[f.name] = f
                        self.file_mtimes[f.name] = f.stat().st_mtime
                        try:
                            self.docs[f.name] = render_document(f, dpi=self.dpi)
                        except Exception:
                            pass

        self.doc_names = list(self.docs.keys())
        self.active_doc_idx = max(0, len(self.doc_names) - 1)
        self.active_page_idx = 0
        self.tab_rects: List[Tuple[int, int, int, int]] = []
        self.header_height = 46

    def _mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and y <= self.header_height:
            for idx, (x1, y1, x2, y2) in enumerate(self.tab_rects):
                if x1 <= x <= x2 and y1 <= y <= y2:
                    if self.active_doc_idx != idx:
                        self.active_doc_idx = idx
                        self.active_page_idx = 0
                    break

    def _render_frame(self) -> np.ndarray:
        if not self.doc_names:
            blank = np.full((350, 700, 3), 240, dtype=np.uint8)
            cv2.putText(blank, "No documents in workspace", (120, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (50, 50, 50), 2)
            return blank

        current_doc_name = self.doc_names[self.active_doc_idx]
        current_pages = self.docs[current_doc_name]
        page_idx = min(self.active_page_idx, len(current_pages) - 1)
        content_img = current_pages[page_idx].copy()

        h, w = content_img.shape[:2]
        available_h = self.max_height - self.header_height
        if h > available_h:
            scale = available_h / h
            target_w = max(int(w * scale), 400)
            content_img = cv2.resize(content_img, (target_w, available_h), interpolation=cv2.INTER_AREA)

        canvas_w = max(content_img.shape[1], 850)
        canvas_h = content_img.shape[0] + self.header_height
        canvas = np.full((canvas_h, canvas_w, 3), 245, dtype=np.uint8)

        x_offset = (canvas_w - content_img.shape[1]) // 2
        canvas[self.header_height : self.header_height + content_img.shape[0], x_offset : x_offset + content_img.shape[1]] = content_img

        # Top Tab Bar
        cv2.rectangle(canvas, (0, 0), (canvas_w, self.header_height), (35, 30, 25), -1)
        self.tab_rects.clear()
        tab_x = 10

        for idx, name in enumerate(self.doc_names):
            label = f"[{idx + 1}] {name}"
            (text_w, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
            tab_w = text_w + 24
            tab_x2 = tab_x + tab_w
            is_active = (idx == self.active_doc_idx)

            if is_active:
                cv2.rectangle(canvas, (tab_x, 6), (tab_x2, self.header_height - 6), (180, 105, 30), -1)
                cv2.putText(canvas, label, (tab_x + 12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2)
            else:
                cv2.rectangle(canvas, (tab_x, 6), (tab_x2, self.header_height - 6), (55, 50, 45), -1)
                cv2.putText(canvas, label, (tab_x + 12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (180, 180, 180), 1)

            self.tab_rects.append((tab_x, 6, tab_x2, self.header_height - 6))
            tab_x = tab_x2 + 8

        page_info = f"Page {self.active_page_idx + 1}/{len(current_pages)}"
        hint = f"{page_info} | Tab/1-9: Select Doc | Arrows: Page | ESC: Exit"
        (hint_w, _), _ = cv2.getTextSize(hint, cv2.FONT_HERSHEY_SIMPLEX, 0.44, 1)
        hint_x = max(tab_x + 10, canvas_w - hint_w - 15)
        cv2.putText(canvas, hint, (hint_x, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (160, 160, 160), 1)

        return canvas

    def show(self, wait_ms: int = 0) -> int:
        cv2.namedWindow(self.window_title, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(self.window_title, self._mouse_callback)
        last_reload_check = time.time()

        while True:
            now = time.time()
            if now - last_reload_check > 0.5:
                last_reload_check = now

                # Dynamic detection of new documents in watch_dir
                if self.watch_dir and self.watch_dir.exists():
                    for f in sorted(self.watch_dir.iterdir()):
                        if f.is_file() and f.suffix.lower() in [".xlsx", ".docx", ".pptx"] and not f.name.startswith("~"):
                            if f.name not in self.file_sources:
                                self.file_sources[f.name] = f
                                self.file_mtimes[f.name] = f.stat().st_mtime
                                try:
                                    self.docs[f.name] = render_document(f, dpi=self.dpi)
                                    self.doc_names.append(f.name)
                                    self.active_doc_idx = len(self.doc_names) - 1
                                    self.active_page_idx = 0
                                except Exception:
                                    pass

                # Check for updates to existing documents
                for name, path in list(self.file_sources.items()):
                    if path.exists():
                        try:
                            mtime = path.stat().st_mtime
                            if mtime > self.file_mtimes.get(name, 0.0):
                                self.file_mtimes[name] = mtime
                                self.docs[name] = render_document(path, dpi=self.dpi)
                                if self.active_page_idx >= len(self.docs[name]):
                                    self.active_page_idx = max(0, len(self.docs[name]) - 1)
                        except Exception:
                            pass

            frame = self._render_frame()
            cv2.imshow(self.window_title, frame)

            key = cv2.waitKey(wait_ms if wait_ms > 0 else 30)
            if wait_ms > 0 or key in [27, ord('q'), ord('Q')]:
                break

            if ord('1') <= key <= ord('9'):
                target_idx = key - ord('1')
                if target_idx < len(self.doc_names):
                    self.active_doc_idx = target_idx
                    self.active_page_idx = 0
            elif key == 9:  # Tab
                if self.doc_names:
                    self.active_doc_idx = (self.active_doc_idx + 1) % len(self.doc_names)
                    self.active_page_idx = 0
            elif key in [81, 2424832, ord('p'), ord('P')]:  # Left Arrow
                if self.doc_names:
                    total = len(self.docs[self.doc_names[self.active_doc_idx]])
                    if total > 1:
                        self.active_page_idx = (self.active_page_idx - 1) % total
            elif key in [83, 2555904, ord('n'), ord('N'), 32]:  # Right Arrow / Space
                if self.doc_names:
                    total = len(self.docs[self.doc_names[self.active_doc_idx]])
                    if total > 1:
                        self.active_page_idx = (self.active_page_idx + 1) % total

        cv2.destroyWindow(self.window_title)
        return key

def show_preview(target: Union[Dict, List, str, Path], window_title: str = "Office Visual Viewport", max_height: int = MAX_VIEWPORT_HEIGHT, wait_ms: int = 0, dpi: int = 130) -> int:
    watch_dir = None
    if isinstance(target, dict):
        docs = target
    elif isinstance(target, (str, Path)) and Path(target).is_dir():
        docs = {}
        watch_dir = Path(target)
    elif isinstance(target, list) and target and isinstance(target[0], (str, Path)):
        docs = {Path(p).name: p for p in target}
        watch_dir = Path(target[0]).parent
    elif isinstance(target, (str, Path)):
        docs = {Path(target).name: target}
        watch_dir = Path(target).parent
    else:
        docs = {"Active Document": target}

    viewer = MultiDocViewer(docs, window_title=window_title, max_height=max_height, dpi=dpi, watch_dir=watch_dir)
    return viewer.show(wait_ms=wait_ms)
```

---

### 4.6 `src/office_visual/runner.py`
에이전트가 작성한 순수 파이썬 코드를 실행하고, 레이아웃 정량 진단 및 렌더링을 원스톱으로 처리하는 러너입니다.
```python
import sys, io, time, traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Union
import numpy as np

from .inspector import inspect_document, InspectionReport
from .renderer import render_document

@dataclass
class ExecutionResult:
    success: bool
    code: str
    stdout: str
    stderr: str
    document_paths: List[Path] = field(default_factory=list)
    images: List[np.ndarray] = field(default_factory=list)
    inspection: Optional[InspectionReport] = None
    execution_time_ms: float = 0.0
    render_time_ms: float = 0.0

    @property
    def has_visual_issues(self) -> bool:
        return self.inspection is not None and not self.inspection.is_valid

    def feedback_message(self) -> str:
        if not self.success:
            return f"[Execution Error]\n{self.stderr}"
        msg = [f"[Execution Success] Generated {len(self.document_paths)} document(s)."]
        if self.inspection:
            msg.append(f"\n{self.inspection.summary()}")
        return "\n".join(msg)

class OfficeCodeRunner:
    def __init__(self, workspace_dir: Optional[Union[str, Path]] = None):
        self.workspace_dir = Path(workspace_dir or Path.cwd()).resolve()

    def run_code(
        self,
        code_string: str,
        expected_output_files: Optional[List[Union[str, Path]]] = None,
        expected_pages: Optional[int] = None,
        auto_inspect: bool = True,
        auto_render: bool = True,
        dpi: int = 120
    ) -> ExecutionResult:
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        exec_globals: Dict[str, Any] = {
            "__name__": "__main__",
            "Path": Path,
            "workspace_dir": self.workspace_dir,
        }
        for mod in ["openpyxl", "docx", "pptx", "pandas", "np", "numpy", "matplotlib", "plt"]:
            try:
                exec_globals[mod] = __import__(mod)
            except ImportError:
                pass

        t0 = time.perf_counter()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        success = True

        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            exec(code_string, exec_globals)
        except Exception:
            success = False
            stderr_capture.write(traceback.format_exc())
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        exec_time = (time.perf_counter() - t0) * 1000
        found_docs: List[Path] = []
        if expected_output_files:
            for p in expected_output_files:
                resolved = Path(p) if Path(p).is_absolute() else (self.workspace_dir / p).resolve()
                if resolved.exists():
                    found_docs.append(resolved)

        inspection_report = None
        images: List[np.ndarray] = []
        render_time = 0.0

        if success and found_docs:
            t_render_start = time.perf_counter()
            primary_doc = found_docs[0]
            if auto_inspect:
                try:
                    inspection_report = inspect_document(primary_doc, expected_pages=expected_pages)
                except Exception as e:
                    stderr_capture.write(f"\n[Inspector Warning] {e}")

            if auto_render:
                try:
                    images = render_document(primary_doc, dpi=dpi)
                except Exception as e:
                    stderr_capture.write(f"\n[Renderer Warning] {e}")

            render_time = (time.perf_counter() - t_render_start) * 1000

        return ExecutionResult(
            success=success,
            code=code_string,
            stdout=stdout_capture.getvalue(),
            stderr=stderr_capture.getvalue(),
            document_paths=found_docs,
            images=images,
            inspection=inspection_report,
            execution_time_ms=exec_time,
            render_time_ms=render_time
        )
```

---

### 4.7 `src/office_visual/cli.py`
```python
import sys, argparse
from pathlib import Path

from .config import find_soffice_binary
from .renderer import render_document
from .viewport import show_preview

def main():
    parser = argparse.ArgumentParser(prog="office-visual", description="Office Visual Agent CLI Viewport")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("check", help="Verify LibreOffice and runtime environment")

    p_live = subparsers.add_parser("live", help="Live Workspace Watcher (Real-time auto-reload & tab additions)")
    p_live.add_argument("directory", nargs="?", default="samples/workspace", help="Directory to watch")
    p_live.add_argument("--dpi", type=int, default=130)

    p_preview = subparsers.add_parser("preview", help="Preview documents")
    p_preview.add_argument("files", nargs="+", help="Files to preview")
    p_preview.add_argument("--dpi", type=int, default=130)
    p_preview.add_argument("--wait", type=int, default=0)

    args = parser.parse_args()

    if args.command == "check":
        soffice = find_soffice_binary()
        print(f"[OK] LibreOffice Binary: {soffice}")
        print("[OK] Environment is ready for Office Visual Agent.")

    elif args.command == "live":
        watch_path = Path(args.directory).resolve()
        watch_path.mkdir(parents=True, exist_ok=True)
        print(f"Starting Live Workspace Viewport watching: {watch_path}")
        show_preview(watch_path, window_title="Office Visual Live Workspace", dpi=args.dpi)

    elif args.command == "preview":
        file_paths = [Path(f) for f in args.files]
        if len(file_paths) == 1:
            show_preview(file_paths[0], wait_ms=args.wait, dpi=args.dpi)
        else:
            doc_dict = {f.name: f for f in file_paths}
            show_preview(doc_dict, wait_ms=args.wait, dpi=args.dpi)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
```

---

## 5. 폐쇄망 설치 및 가동 절차 (Deployment Steps)

폐쇄망 PC에 소스 파일과 반입 자원을 배치한 후 실행하는 절차입니다.

### 1단계: 오프라인 Wheel 패키지 설치
```cmd
cd C:\Users\JooJoo\Desktop\AI\libreoffice_viewer
pip install --no-index --find-links=wheels openpyxl python-docx python-pptx pandas opencv-python pymupdf matplotlib
```

### 2단계: 로컬 패키지 등록 (Editable Install)
```cmd
pip install -e . --no-deps
```

### 3단계: 환경 검증
```cmd
office-visual check
```
출력에 `[OK] LibreOffice Binary: ...\soffice.com`이 표시되면 완벽하게 준비된 것입니다.

### 4단계: 실시간 라이브 뷰어 실행
```cmd
office-visual live
```
뷰어가 `samples\workspace\` 폴더를 감시하기 시작하며 화면에 상주합니다.

---

## 6. 사내 LLM (Gemma 4 26B) 프롬프트 가이드

사내 LLM에게 역할을 부여할 때는 두꺼운 래퍼나 가상 도구를 주지 말고, 아래 시스템 프롬프트를 주어 **직접 파이썬 코드를 작성하게 한 후 `OfficeCodeRunner`로 실행**합니다.

### 6.1 LLM 시스템 프롬프트 (System Prompt)
```text
당신은 'Office Visual Agent'입니다. 
당신은 MS Office Win32 COM을 절대 사용하지 않으며, 100% 인메모리 파이썬 라이브러리(openpyxl, python-docx, python-pptx, pandas, matplotlib)만을 사용하여 오피스 문서를 생성/편집합니다.

[규칙]
1. 작업 결과 파일은 반드시 'samples/workspace/' 폴더에 저장하십시오. (뷰어가 실시간으로 감지합니다.)
2. 엑셀을 생성할 때는 셀 너비 부족으로 '###' 마스킹이 발생하지 않도록 넉넉한 열 너비(column_dimensions['A'].width = 15~25)를 지정하십시오.
3. 엑셀 대시보드는 ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE 및 fitToWidth = 1 설정을 주어 1페이지에 깔끔하게 인쇄되도록 하십시오.
4. 오피스 간 데이터 교환(Excel -> Word/PPT)은 pandas DataFrame과 matplotlib 이미지 버퍼(io.BytesIO)를 활용하십시오.
```

### 6.2 자율 자가 교정(Self-Healing) 프롬프트 템플릿
러너 실행 후 `result.has_visual_issues`가 `True`일 경우 LLM에게 보낼 피드백:
```text
[Visual Inspector Feedback]
당신이 생성한 문서에서 다음과 같은 시각적 서식 결함이 감지되었습니다:
{result.feedback_message()}

위의 Recommendation(권장 사항)을 반영하여 기존 코드를 수정한 파이썬 코드를 다시 작성하십시오.
```

---

## 7. 주요 트러블슈팅

1. **`ModuleNotFoundError: No module named 'cv2'` / `pymupdf`**:
   - 오프라인 wheel 설치 시 C++ 런타임 종속성이 있는 경우, Windows용 `VC_redist.x64.exe`(Visual C++ Redistributable)를 폐쇄망에 반입하여 설치해야 합니다.
2. **`LibreOffice conversion failed`**:
   - `LibreOfficePortable/App/libreoffice/program/soffice.com` 경로가 올바른지 확인하십시오. (`office-visual check`로 자동 진단 가능)
3. **콘솔 한글 인코딩 깨짐 (Windows cmd cp949)**:
   - 파이썬 출력문에서 특수 유니코드 기호(`•` 등) 대신 표준 ASCII 기호(`-`, `*`)를 사용하십시오.
