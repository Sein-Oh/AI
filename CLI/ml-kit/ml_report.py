# -*- coding: utf-8 -*-
"""
ml_report.py - ML 결과 보고서 (Word .docx) generator for one trained version folder.

One integrated document covers every target of the version (regression or classification):
cover, contents, summary, data, method, per-target results with charts, version history,
operation guide and appendix. All numbers and texts are generated deterministically from the
training artifacts; an LLM may optionally override narrative paragraphs with --slots.

Inputs (all written by ml_train.py 2.2.0+):
  <data_root>/history.jsonl, <version_dir>/leaderboard.json, model_<t>.json, oof_<t>.csv, correlation.csv

Select the version with -m <version_dir>, or with -d <data_root> [-v vN] (without -v: the best
version of the latest experiment, i.e. same task and target set as the latest training run).
Requires python-docx and matplotlib (both in the standard environment).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ml_predict import (  # noqa: E402  shared runtime lives in ml_predict.py
    setup_console, run_cli, JsonArgumentParser, InputError,
    sanitize_filename, load_json_file, save_with_lock_fallback, warn_long_path, avoid_overwrite,
    normalize_version, strip_unit, note_recovered, VERSION,
)

setup_console()

import io
import json
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd

# Optional at import time so a missing package is reported as protocol JSON
try:
    import docx
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.section import WD_ORIENT
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    _DOCX_IMPORT_ERROR = None
except ImportError as _e:
    _DOCX_IMPORT_ERROR = _e

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    _MPL_IMPORT_ERROR = None
except ImportError as _e:
    _MPL_IMPORT_ERROR = _e


REPORT_TITLE = "ML 결과 보고서"
REPORT_VERSION = VERSION

# ==============================================================================
# 1. Design tokens (grayscale-safe slate palette + one navy accent)
# ==============================================================================

FONT_KO = "맑은 고딕"
C_INK = "1F2937"      # body text
C_MUTED = "6B7280"    # captions, secondary text
C_LINE = "CBD5E1"     # table grid
C_HEAD = "F1F5F9"     # table header / box background
C_ACCENT = "1E3A8A"   # navy: titles, champion, primary series
C_ACCENT_BG = "E0E7FF"

VERDICT_STYLE = {      # label -> (text color, background)
    "적합": ("1E3A8A", "DBEAFE"),
    "조건부": ("92400E", "FEF3C7"),
    "부적합": ("991B1B", "FEE2E2"),
}
PASS_SCORE = 0.90
CONDITIONAL_SCORE = 0.70
OVERFIT_LIMIT = 0.15

MPL_NAVY = "#1E3A8A"
MPL_GRAY = "#9CA3AF"
MPL_LIGHT = "#E5E7EB"
MPL_ORANGE = "#D97706"
MPL_INK = "#1F2937"
FIG_WIDTH_CM = 16.0


def _setup_matplotlib() -> None:
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "AppleGothic"):
        if name in available:
            plt.rcParams["font.family"] = name
            break
    plt.rcParams.update({
        "axes.unicode_minus": False,
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "axes.edgecolor": "#9CA3AF",
        "axes.labelcolor": MPL_INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": "#4B5563",
        "ytick.color": "#4B5563",
        "axes.grid": True,
        "grid.color": "#E5E7EB",
        "grid.linewidth": 0.6,
        "figure.dpi": 200,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
    })


def verdict_of(score: Optional[float], overfit_gap: Optional[float]) -> Tuple[str, str]:
    """Rule-based verdict shared by summary, cover and JSON output."""
    if score is None:
        return "부적합", "성능 지표 없음"
    if score >= PASS_SCORE:
        if overfit_gap is not None and overfit_gap > OVERFIT_LIMIT:
            return "조건부", f"검증 점수는 기준을 충족하나 과적합 간극 {overfit_gap:.3f} > {OVERFIT_LIMIT}"
        return "적합", f"검증 점수 {score:.3f} >= {PASS_SCORE}"
    if score >= CONDITIONAL_SCORE:
        return "조건부", f"검증 점수 {score:.3f} (기준 {PASS_SCORE} 미달, {CONDITIONAL_SCORE} 이상)"
    return "부적합", f"검증 점수 {score:.3f} < {CONDITIONAL_SCORE}"


def worst_verdict(verdicts: List[str]) -> str:
    order = ["부적합", "조건부", "적합"]
    return min(verdicts, key=order.index) if verdicts else "부적합"


def fmt(v: Any, digits: int = 4) -> str:
    if v is None:
        return "-"
    if isinstance(v, (bool, np.bool_)):
        return "예" if v else "아니오"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    if isinstance(v, (float, np.floating)):
        if not np.isfinite(v):
            return "-"
        return f"{float(v):,.{digits}f}"
    return str(v)


# ==============================================================================
# 2. Word building blocks
# ==============================================================================

def _rgb(hex_color: str) -> "RGBColor":
    return RGBColor.from_string(hex_color)


def _set_run_font(run, size: Optional[float] = None, bold: Optional[bool] = None,
                  color: Optional[str] = None, font: str = FONT_KO) -> None:
    run.font.name = font
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), font)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = _rgb(color)


def _style_font(style, size: float, bold: bool = False, color: str = C_INK) -> None:
    style.font.name = FONT_KO
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = _rgb(color)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), FONT_KO)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if rfonts.get(qn(attr)) is not None:
            del rfonts.attrib[qn(attr)]


def _shade(cell, hex_color: str) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcpr.append(shd)


def _cell_margins(cell, top=60, bottom=60, left=90, right=90) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    for k, v in (("top", top), ("bottom", bottom), ("start", left), ("end", right)):
        el = OxmlElement(f"w:{k}")
        el.set(qn("w:w"), str(v))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tcpr.append(mar)


def _table_borders(table, color: str = C_LINE, inside: bool = True) -> None:
    tblpr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    edges = ["top", "bottom", "left", "right"] + (["insideH", "insideV"] if inside else [])
    for edge in edges:
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    tblpr.append(borders)


def _cell_left_bar(cell, color: str, size: int = 18) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    borders = OxmlElement("w:tcBorders")
    for edge in ("top", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), str(size))
    left.set(qn("w:color"), color)
    borders.append(left)
    tcpr.append(borders)


def _fix_widths(table, widths_cm: List[float]) -> None:
    """Fixed table layout with explicit grid column widths (cell widths alone are ignored by some renderers)."""
    tblpr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblpr.append(layout)
    for col, w in zip(table.columns, widths_cm):
        col.width = Cm(w)
    for row in table.rows:
        for cell, w in zip(row.cells, widths_cm):
            cell.width = Cm(w)


def _repeat_header(row) -> None:
    trpr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trpr.append(el)


def _no_split(row) -> None:
    trpr = row._tr.get_or_add_trPr()
    trpr.append(OxmlElement("w:cantSplit"))


def _add_field(paragraph, instr: str, size: float = 8, color: str = C_MUTED) -> None:
    for kind, text in (("begin", None), ("instr", instr), ("separate", None), ("text", "1"), ("end", None)):
        run = paragraph.add_run()
        _set_run_font(run, size=size, color=color)
        if kind == "instr":
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = f" {text} "
            run._r.append(it)
        elif kind == "text":
            t = OxmlElement("w:t")
            t.text = text
            run._r.append(t)
        else:
            fc = OxmlElement("w:fldChar")
            fc.set(qn("w:fldCharType"), kind)
            run._r.append(fc)


def _para_border_bottom(paragraph, color: str = C_LINE, size: int = 6) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), str(size))
    b.set(qn("w:space"), "1")
    b.set(qn("w:color"), color)
    pbdr.append(b)
    ppr.append(pbdr)


# ------------------------------------------------------------------------------
# Document template (DRM-safe)
# ------------------------------------------------------------------------------
# docx.Document() opens python-docx's templates/default.docx. Corporate DRM may encrypt or replace
# files with Office extensions, leaving a substitute document without the standard styles
# ('Caption' etc.) and with placeholder text. python-docx ships the same template unpacked as plain
# XML files (templates/default-docx-template/), which DRM does not touch, so that folder is used first.

# Paragraph styles the report uses: name -> (outline level for headings or None, bold, size pt)
REPORT_STYLES = {
    "Normal": (None, False, 10),
    "Heading 1": (0, True, 15),
    "Heading 2": (1, True, 12.5),
    "Heading 3": (2, True, 11),
    "Caption": (None, False, 8.5),
    "List Bullet": (None, False, 10),
}


def docx_template_dir() -> str:
    return os.path.join(os.path.dirname(docx.__file__), "templates", "default-docx-template")


def _clear_body(doc) -> int:
    """Removes body content (keeps the final section properties); returns the number of removed blocks."""
    body = doc.element.body
    removed = 0
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)
            removed += 1
    return removed


def _ensure_styles(doc) -> List[str]:
    """Creates every report style missing from a damaged template (based on Normal); returns created names."""
    st = doc.styles
    have = {s.name for s in st}
    created = []
    for name, (outline, bold, size) in REPORT_STYLES.items():
        if name in have:
            continue
        style = st.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        if name != "Normal":
            style.base_style = st["Normal"]
            style.next_paragraph_style = st["Normal"]
        style.font.bold = bold
        style.font.size = Pt(size)
        if outline is not None:
            style.paragraph_format.keep_with_next = True
            ppr = style.element.get_or_add_pPr()
            lvl = OxmlElement("w:outlineLvl")
            lvl.set(qn("w:val"), str(outline))
            ppr.append(lvl)
        created.append(name)
    return created


def docx_from_template_dir(tdir: str):
    """Opens python-docx's unpacked template folder as a document, tolerating missing optional parts.
    On the company PC a security product removed docProps/thumbnail.jpeg from the folder, and python-docx
    fails on any part a relationship points to but that is missing. The folder is packed into an in-memory
    .docx without those relationships. Returns (document, list of dropped part names)."""
    import io
    import zipfile
    import posixpath
    import xml.etree.ElementTree as ET
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    files: Dict[str, bytes] = {}
    for root, _dirs, names in os.walk(tdir):
        for n in names:
            full = os.path.join(root, n)
            with open(full, "rb") as f:
                files[os.path.relpath(full, tdir).replace(os.sep, "/")] = f.read()
    dropped: List[str] = []
    for rels_name in [k for k in files if k.endswith(".rels")]:
        # "_rels/.rels" -> source folder "", "word/_rels/document.xml.rels" -> "word"
        base = posixpath.dirname(posixpath.dirname(rels_name))
        ET.register_namespace("", rel_ns)
        tree = ET.fromstring(files[rels_name])
        changed = False
        for rel in list(tree):
            if rel.get("TargetMode") == "External":
                continue
            target = rel.get("Target", "")
            part = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base, target))
            if part not in files:
                tree.remove(rel)
                dropped.append(part)
                changed = True
        if changed:
            files[rels_name] = ET.tostring(tree, xml_declaration=True, encoding="UTF-8")
    if dropped and "[Content_Types].xml" in files:
        ET.register_namespace("", ct_ns)
        ct = ET.fromstring(files["[Content_Types].xml"])
        for ov in list(ct):
            if (ov.get("PartName") or "").lstrip("/") in dropped:
                ct.remove(ov)
        files["[Content_Types].xml"] = ET.tostring(ct, xml_declaration=True, encoding="UTF-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files, key=lambda k: (k != "[Content_Types].xml", k)):
            z.writestr(name, files[name])
    buf.seek(0)
    return docx.Document(buf), dropped


def new_report_document():
    """Opens a blank document that always has the report styles (JIT recovery for damaged templates)."""
    problems: List[str] = []
    doc = None
    tdir = docx_template_dir()
    if os.path.isdir(tdir):
        try:
            doc, dropped = docx_from_template_dir(tdir)
            if dropped:
                note_recovered(f"Word 내장 템플릿 폴더에 빠진 파일({', '.join(dropped)}) -> 제외하고 사용")
        except Exception as e:
            problems.append(f"내장 템플릿 폴더 열기 실패({type(e).__name__}: {e})")
    else:
        problems.append("내장 템플릿 폴더 없음")
    if doc is None:
        try:
            doc = docx.Document()
        except Exception as e:
            raise InputError(
                f"python-docx 기본 템플릿을 열 수 없습니다 ({'; '.join(problems)}; default.docx: {type(e).__name__}: {e}). "
                f"보안 프로그램(DRM)이 python-docx 설치 폴더의 templates 파일을 바꿨을 수 있습니다. "
                f"관리자에게 python-docx 재설치를 요청하십시오: python -m pip install --force-reinstall python-docx"
            ) from e
        note_recovered(f"Word 내장 템플릿 폴더 사용 불가({'; '.join(problems)}) -> default.docx 사용")
        # A substitute template may carry its own header/footer content: start from fresh ones
        for sec in doc.sections:
            for hf in (sec.header, sec.footer, sec.first_page_header, sec.first_page_footer):
                try:
                    hf.is_linked_to_previous = True
                except Exception:
                    pass
    doc.element.body.get_or_add_sectPr()
    removed = _clear_body(doc)
    if removed:
        note_recovered(f"Word 템플릿에 본문 {removed}개 있음(보안 프로그램 대체 문서 추정) -> 제거 후 작성")
    created = _ensure_styles(doc)
    if created:
        note_recovered(f"Word 템플릿에 스타일 없음({', '.join(created)}) -> Normal 기반으로 생성")
    return doc


class ReportDoc:
    """Thin layer over python-docx enforcing one consistent visual system."""

    def __init__(self, header_text: str):
        self.doc = new_report_document()
        self.table_no = 0
        self.figure_no = 0
        self._setup_page(header_text)
        self._setup_styles()

    # -- page / styles -------------------------------------------------------
    def _setup_page(self, header_text: str) -> None:
        sec = self.doc.sections[0]
        sec.orientation = WD_ORIENT.PORTRAIT
        sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
        sec.left_margin = sec.right_margin = Cm(2.0)
        sec.top_margin, sec.bottom_margin = Cm(2.2), Cm(2.0)
        sec.header_distance, sec.footer_distance = Cm(1.0), Cm(1.0)
        sec.different_first_page_header_footer = True  # clean cover page

        hp = sec.header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_run_font(hp.add_run(header_text), size=8, color=C_MUTED)
        _para_border_bottom(hp)

        fp = sec.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _add_field(fp, "PAGE")
        _set_run_font(fp.add_run(" / "), size=8, color=C_MUTED)
        _add_field(fp, "NUMPAGES")

    def _setup_styles(self) -> None:
        st = self.doc.styles
        normal = st["Normal"]
        _style_font(normal, 10)
        normal.paragraph_format.space_after = Pt(4)
        normal.paragraph_format.line_spacing = 1.2
        for name, size, before, after in (("Heading 1", 15, 0, 10), ("Heading 2", 12.5, 14, 6), ("Heading 3", 11, 10, 4)):
            h = st[name]
            _style_font(h, size, bold=True, color=C_ACCENT if name == "Heading 1" else C_INK)
            h.paragraph_format.space_before = Pt(before)
            h.paragraph_format.space_after = Pt(after)
            h.paragraph_format.keep_with_next = True
        cap = st["Caption"]
        _style_font(cap, 8.5, color=C_MUTED)
        cap.font.italic = False
        cap.paragraph_format.space_before = Pt(3)
        cap.paragraph_format.space_after = Pt(10)

    # -- text ----------------------------------------------------------------
    def h1(self, text: str, page_break: bool = True) -> None:
        if page_break:
            self.page_break()
        p = self.doc.add_heading(text, level=1)
        _para_border_bottom(p, color=C_ACCENT, size=8)

    def h2(self, text: str) -> None:
        self.doc.add_heading(text, level=2)

    def h3(self, text: str) -> None:
        self.doc.add_heading(text, level=3)

    def para(self, text: str, size: float = 10, color: str = C_INK, bold: bool = False,
             align=None, space_after: Optional[float] = None) -> Any:
        p = self.doc.add_paragraph()
        if align is not None:
            p.alignment = align
        if space_after is not None:
            p.paragraph_format.space_after = Pt(space_after)
        _set_run_font(p.add_run(text), size=size, color=color, bold=bold)
        return p

    def bullets(self, items: List[str]) -> None:
        for it in items:
            p = self.doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(2)
            _set_run_font(p.add_run(it), size=10, color=C_INK)

    def page_break(self) -> None:
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def caption(self, kind: str, text: str) -> None:
        if kind == "표":
            self.table_no += 1
            label = f"표 {self.table_no}. "
        else:
            self.figure_no += 1
            label = f"그림 {self.figure_no}. "
        p = self.doc.add_paragraph(style="Caption")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER if kind == "그림" else WD_ALIGN_PARAGRAPH.LEFT
        _set_run_font(p.add_run(label), size=8.5, color=C_INK, bold=True)
        _set_run_font(p.add_run(text), size=8.5, color=C_MUTED)

    # -- tables --------------------------------------------------------------
    def table(self, header: List[str], rows: List[List[Any]], caption: Optional[str] = None,
              widths: Optional[List[float]] = None, align: Optional[List[str]] = None,
              highlight_rows: Optional[List[int]] = None, verdict_col: Optional[int] = None,
              font_size: float = 8.5) -> None:
        """Data table: shaded header, numbers right-aligned, optional highlighted rows (0-based body index)."""
        if caption:
            # Caption above tables (engineering convention), below figures
            self.caption("표", caption)
        n_cols = len(header)
        t = self.doc.add_table(rows=1 + len(rows), cols=n_cols)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        _table_borders(t)
        _fix_widths(t, widths or [17.0 / n_cols] * n_cols)
        highlight_rows = set(highlight_rows or [])
        if align is None:
            align = ["left"] + ["right"] * (n_cols - 1)
        amap = {"left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT, "center": WD_ALIGN_PARAGRAPH.CENTER}

        for r_i in range(len(rows) + 1):
            row = t.rows[r_i]
            _no_split(row)
            if r_i == 0:
                _repeat_header(row)
            for c_i in range(n_cols):
                cell = row.cells[c_i]
                _cell_margins(cell)
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                p = cell.paragraphs[0]
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1.0
                if r_i == 0:
                    _shade(cell, C_HEAD)
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    _set_run_font(p.add_run(str(header[c_i])), size=font_size, bold=True, color=C_INK)
                    continue
                value = rows[r_i - 1][c_i]
                text = value if isinstance(value, str) else fmt(value)
                p.alignment = amap[align[c_i]]
                bold = (r_i - 1) in highlight_rows
                color = C_ACCENT if bold else C_INK
                if verdict_col is not None and c_i == verdict_col and text in VERDICT_STYLE:
                    fg, bg = VERDICT_STYLE[text]
                    _shade(cell, bg)
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    color, bold = fg, True
                elif bold:
                    _shade(cell, "F8FAFC")
                _set_run_font(p.add_run(text), size=font_size, bold=bold, color=color)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def kv_table(self, pairs: List[Tuple[str, Any]], caption: Optional[str] = None,
                 widths: Tuple[float, float] = (4.2, 12.8)) -> None:
        if caption:
            self.caption("표", caption)
        t = self.doc.add_table(rows=len(pairs), cols=2)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        _table_borders(t)
        _fix_widths(t, list(widths))
        for i, (k, v) in enumerate(pairs):
            kc, vc = t.rows[i].cells
            for c in (kc, vc):
                _cell_margins(c)
                c.paragraphs[0].paragraph_format.space_after = Pt(0)
            _shade(kc, C_HEAD)
            _set_run_font(kc.paragraphs[0].add_run(str(k)), size=9, bold=True, color=C_INK)
            text = v if isinstance(v, str) else fmt(v)
            _set_run_font(vc.paragraphs[0].add_run(text), size=9, color=C_INK)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def metric_cards(self, cards: List[Tuple[str, str, str]]) -> None:
        """Row of KPI cards: (label, value, sub-text)."""
        t = self.doc.add_table(rows=1, cols=len(cards))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        _fix_widths(t, [17.0 / len(cards)] * len(cards))
        for i, (label, value, sub) in enumerate(cards):
            c = t.rows[0].cells[i]
            _shade(c, C_HEAD)
            _cell_margins(c, top=120, bottom=120, left=140, right=140)
            _cell_left_bar(c, C_ACCENT, size=16)
            p1 = c.paragraphs[0]
            p1.paragraph_format.space_after = Pt(2)
            _set_run_font(p1.add_run(label), size=8, color=C_MUTED)
            p2 = c.add_paragraph()
            p2.paragraph_format.space_after = Pt(1)
            _set_run_font(p2.add_run(value), size=15 if len(value) <= 10 else (11 if len(value) <= 16 else 9.5), bold=True, color=C_ACCENT)
            p3 = c.add_paragraph()
            p3.paragraph_format.space_after = Pt(0)
            _set_run_font(p3.add_run(sub), size=7.5, color=C_MUTED)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(4)

    def note(self, title: str, text: str) -> None:
        """Finding box: light background, navy left bar."""
        t = self.doc.add_table(rows=1, cols=1)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        _fix_widths(t, [17.0])
        _no_split(t.rows[0])  # keep the finding box on one page
        c = t.rows[0].cells[0]
        _shade(c, "F8FAFC")
        _cell_margins(c, top=100, bottom=100, left=160, right=160)
        _cell_left_bar(c, C_ACCENT)
        p = c.paragraphs[0]
        p.paragraph_format.space_after = Pt(3)
        _set_run_font(p.add_run(title), size=9, bold=True, color=C_ACCENT)
        for line in [s for s in text.split("\n") if s.strip()]:
            q = c.add_paragraph()
            q.paragraph_format.space_after = Pt(1)
            q.paragraph_format.line_spacing = 1.25
            _set_run_font(q.add_run(line), size=9.5, color=C_INK)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # -- figures -------------------------------------------------------------
    def figure(self, fig, caption: str, width_cm: Optional[float] = None) -> None:
        if width_cm is None:
            width_cm = min(fig.get_size_inches()[0] * 2.54, FIG_WIDTH_CM)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_after = Pt(0)
        p.add_run().add_picture(buf, width=Cm(width_cm))
        self.caption("그림", caption)

    def save(self, path: str) -> str:
        return save_with_lock_fallback(path, self.doc.save, what="Word 보고서")


# ==============================================================================
# 3. Charts (matplotlib -> PNG)
# ==============================================================================

def _fig(h_cm: float = 6.5, w_cm: float = FIG_WIDTH_CM, ncols: int = 1):
    return plt.subplots(1, ncols, figsize=(w_cm / 2.54, h_cm / 2.54))


def chart_model_comparison(board: List[Dict[str, Any]], metric: str, label: str):
    names = [e["model_name"] for e in board][::-1]
    vals = [e.get(metric) or 0.0 for e in board][::-1]
    colors = [MPL_NAVY if e.get("is_champion") else MPL_GRAY for e in board][::-1]
    fig, ax = _fig(h_cm=1.2 + 0.9 * len(names))
    bars = ax.barh(names, vals, color=colors, height=0.6)
    lo = min(0.0, min(vals))
    ax.set_xlim(lo, max(1.0, max(vals) * 1.05))
    for b, v in zip(bars, vals):
        ax.text(b.get_width() + 0.01, b.get_y() + b.get_height() / 2, f"{v:.4f}", va="center", fontsize=8, color=MPL_INK)
    ax.set_xlabel(label)
    ax.grid(axis="y", visible=False)
    return fig


def chart_actual_vs_pred(oof: pd.DataFrame, target: str, r2: float):
    fig, ax = _fig(h_cm=7.5, w_cm=9.0)
    a, p = oof["actual"].values, oof["predicted"].values
    lo, hi = float(min(a.min(), p.min())), float(max(a.max(), p.max()))
    pad = (hi - lo) * 0.04
    ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], color=MPL_ORANGE, lw=1, ls="--", label="실측 = 예측")
    ax.scatter(a, p, s=9, color=MPL_NAVY, alpha=0.55, edgecolors="none")
    ax.set_xlim(lo - pad, hi + pad)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlabel(f"실측 {target}")
    ax.set_ylabel(f"예측 {target}")
    ax.text(0.03, 0.95, f"R² = {r2:.4f}\nn = {len(a):,}", transform=ax.transAxes, va="top", fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=MPL_LIGHT))
    ax.legend(loc="lower right", fontsize=7, frameon=False)
    return fig


def chart_residuals(oof: pd.DataFrame, interval: Optional[Dict[str, Any]]):
    fig, (ax1, ax2) = _fig(h_cm=6.0, ncols=2)
    res, pred = oof["residual"].values, oof["predicted"].values
    ax1.hist(res, bins=30, color=MPL_NAVY, alpha=0.85, edgecolor="white", linewidth=0.4)
    ax1.axvline(0, color=MPL_ORANGE, lw=1, ls="--")
    if interval:
        for v in (interval["residual_lower"], interval["residual_upper"]):
            ax1.axvline(v, color=MPL_GRAY, lw=1, ls=":")
    ax1.set_xlabel("잔차 (실측 - 예측)")
    ax1.set_ylabel("빈도")
    ax1.set_title("잔차 분포", loc="left")
    ax2.scatter(pred, res, s=8, color=MPL_NAVY, alpha=0.5, edgecolors="none")
    ax2.axhline(0, color=MPL_ORANGE, lw=1, ls="--")
    if interval:
        ax2.axhspan(interval["residual_lower"], interval["residual_upper"], color=MPL_LIGHT, alpha=0.6, zorder=0,
                    label=f"{int(interval['level'] * 100)}% 예측 범위")
        ax2.legend(loc="upper right", fontsize=7, frameon=False)
    ax2.set_xlabel("예측값")
    ax2.set_ylabel("잔차")
    ax2.set_title("예측값 대비 잔차", loc="left")
    fig.tight_layout(w_pad=2.0)
    return fig


def chart_importance(ranks: List[Dict[str, Any]], top_n: int = 12):
    top = ranks[:top_n][::-1]
    fig, ax = _fig(h_cm=1.2 + 0.62 * len(top))
    vals = [r["pct"] for r in top]
    bars = ax.barh([r["feature"] for r in top], vals,
                   color=[MPL_NAVY if i >= len(top) - 3 else MPL_GRAY for i in range(len(top))], height=0.6)
    for b, v in zip(bars, vals):
        ax.text(b.get_width() + 0.5, b.get_y() + b.get_height() / 2, f"{v:.1f}%", va="center", fontsize=8)
    ax.set_xlim(0, max(vals + [1]) * 1.15)
    ax.set_xlabel("기여도 (%) - 순열 중요도")
    ax.grid(axis="y", visible=False)
    return fig


def chart_confusion(cm: Dict[str, Any]):
    labels, mat = cm["labels"], np.array(cm["matrix"], dtype=float)
    row_sum = mat.sum(axis=1, keepdims=True)
    pct = np.divide(mat, row_sum, out=np.zeros_like(mat), where=row_sum > 0)
    size = 3.0 + 1.6 * len(labels)
    fig, ax = _fig(h_cm=min(size, 12), w_cm=min(size + 2.0, 14.0))
    ax.imshow(pct, cmap="Blues", vmin=0, vmax=1)
    ax.grid(False)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, f"{int(mat[i, j]):,}\n{pct[i, j]:.0%}", ha="center", va="center", fontsize=8,
                    color="white" if pct[i, j] > 0.6 else MPL_INK)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("예측 클래스")
    ax.set_ylabel("실제 클래스")
    for s in ax.spines.values():
        s.set_visible(False)
    return fig


def chart_per_class(per_class: Dict[str, Dict[str, float]]):
    classes = list(per_class)
    x = np.arange(len(classes))
    w = 0.26
    fig, ax = _fig(h_cm=6.0)
    for k, (key, label, color) in enumerate((("precision", "정밀도", MPL_GRAY), ("recall", "재현율", MPL_NAVY),
                                              ("f1", "F1", MPL_ORANGE))):
        ax.bar(x + (k - 1) * w, [per_class[c][key] for c in classes], width=w, color=color, label=label)
    ax.set_xticks(x, classes)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("점수")
    ax.legend(ncol=3, fontsize=7, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.12))
    ax.grid(axis="x", visible=False)
    return fig


def _roc_points(y_pos: np.ndarray, score: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    order = np.argsort(-score)
    y = y_pos[order]
    tps = np.cumsum(y)
    fps = np.cumsum(~y)
    P, N = max(tps[-1], 1), max(fps[-1], 1)
    return np.concatenate([[0], fps / N]), np.concatenate([[0], tps / P])


def chart_binary_curves(oof: pd.DataFrame, classes: List[str], positive: str, threshold: Optional[float], auc: Optional[float]):
    fig, (ax1, ax2) = _fig(h_cm=6.2, ncols=2)
    y_pos = (oof["actual"].astype(str).values == positive)
    score = oof[f"proba_{positive}"].values
    fpr, tpr = _roc_points(y_pos, score)
    ax1.plot([0, 1], [0, 1], color=MPL_GRAY, lw=1, ls="--")
    ax1.plot(fpr, tpr, color=MPL_NAVY, lw=1.6)
    ax1.set_xlabel("거짓 양성 비율 (FPR)")
    ax1.set_ylabel("참 양성 비율 (TPR)")
    ax1.set_title(f"ROC 곡선 (AUC {auc:.3f})" if auc is not None else "ROC 곡선", loc="left")
    ts = np.round(np.arange(0.05, 0.951, 0.01), 2)
    f1s = []
    for t in ts:
        pred = score >= t
        tp = (pred & y_pos).sum()
        prec = tp / max(pred.sum(), 1)
        rec = tp / max(y_pos.sum(), 1)
        f1s.append(0 if prec + rec == 0 else 2 * prec * rec / (prec + rec))
    ax2.plot(ts, f1s, color=MPL_NAVY, lw=1.6)
    if threshold is not None:
        ax2.axvline(threshold, color=MPL_ORANGE, lw=1, ls="--", label=f"적용 기준 {threshold:.2f}")
        ax2.legend(fontsize=7, frameon=False, loc="lower center")
    ax2.set_xlabel(f"'{positive}' 판정 기준 확률")
    ax2.set_ylabel(f"'{positive}' F1")
    ax2.set_ylim(0, 1.02)
    ax2.set_title("판정 기준별 F1", loc="left")
    fig.tight_layout(w_pad=2.0)
    return fig


def chart_target_distributions(targets: List[Dict[str, Any]]):
    n = len(targets)
    ncols = min(n, 3)
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(FIG_WIDTH_CM / 2.54, (5.2 * nrows) / 2.54), squeeze=False)
    for ax, t in zip(axes.ravel(), targets):
        if t["task"] == "regression":
            ax.hist(t["oof"]["actual"].values, bins=25, color=MPL_NAVY, alpha=0.85, edgecolor="white", linewidth=0.4)
            ax.set_ylabel("빈도")
        else:
            counts = t["oof"]["actual"].astype(str).value_counts().reindex(t["classes"]).fillna(0)
            ax.bar(counts.index, counts.values, color=MPL_NAVY, width=0.6)
            for i, v in enumerate(counts.values):
                ax.text(i, v, f"{int(v):,}", ha="center", va="bottom", fontsize=7)
            ax.set_ylabel("건수")
            ax.grid(axis="x", visible=False)
        ax.set_title(t["name"], loc="left")
    for ax in axes.ravel()[n:]:
        ax.set_visible(False)
    fig.tight_layout(w_pad=1.5, h_pad=1.5)
    return fig


def chart_lineage(rows: List[Dict[str, Any]], current: str, label: str):
    fig, ax = _fig(h_cm=6.0)
    xs = [r["version"] for r in rows]
    ys = [r["score"] for r in rows]
    ax.plot(xs, ys, color=MPL_NAVY, lw=1.6, marker="o", ms=4)
    for x, y, r in zip(xs, ys, rows):
        if x == current:
            ax.scatter([x], [y], s=70, facecolor="white", edgecolor=MPL_ORANGE, lw=1.8, zorder=5)
        ax.annotate(f"{y:.3f}", (x, y), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=7)
    ax.axhline(PASS_SCORE, color=MPL_GRAY, lw=1, ls=":", label=f"적합 기준 {PASS_SCORE}")
    ax.set_ylabel(label)
    ax.set_ylim(min(min(ys), CONDITIONAL_SCORE) - 0.05, 1.02)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    ax.grid(axis="x", visible=False)
    return fig


def chart_correlation(corr: pd.DataFrame):
    n = corr.shape[0]
    size = min(16.0, 3.5 + 0.75 * n)
    fig, ax = _fig(h_cm=size - 1.5, w_cm=size)
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.grid(False)
    ax.set_xticks(range(n), corr.columns, rotation=60, ha="right", fontsize=7)
    ax.set_yticks(range(n), corr.index, fontsize=7)
    if n <= 16:
        for i in range(n):
            for j in range(n):
                v = corr.values[i, j]
                if np.isfinite(v):
                    ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=6,
                            color="white" if abs(v) > 0.6 else MPL_INK)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    return fig


# ==============================================================================
# 4. Artifact loading
# ==============================================================================

def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    sys.stderr.write("[WARN] history.jsonl 손상 라인 1건을 건너뜀\n")
    return out


def load_version(version_dir: str, target_filter: Optional[List[str]] = None) -> Dict[str, Any]:
    vdir = os.path.abspath(version_dir)
    if not os.path.isdir(vdir):
        raise FileNotFoundError(f"버전 폴더를 찾을 수 없습니다: {vdir} (학습 결과 JSON의 version_dir 값을 지정하십시오)")
    lb_path = os.path.join(vdir, "leaderboard.json")
    if not os.path.isfile(lb_path):
        raise InputError(f"leaderboard.json이 없습니다. ml_train.py가 만든 버전 폴더(vX)를 지정하십시오: {vdir}")
    data_root = os.path.dirname(vdir)
    ledger = os.path.join(data_root, "history.jsonl")
    if not os.path.isfile(ledger):
        raise InputError(f"실험 원장(history.jsonl)이 없습니다: {ledger}")
    version = os.path.basename(vdir)
    records = _read_jsonl(ledger)
    rec = [r for r in records if r.get("version") == version]
    if not rec:
        raise InputError(f"원장에 버전 '{version}' 기록이 없습니다. [사용 가능한 버전]: {[r.get('version') for r in records]}")
    record = rec[-1]
    leaderboard = load_json_file(lb_path)

    names = list(record["targets"])
    if target_filter:
        wanted, unknown = [], []
        for f in target_filter:
            hit = [t for t in names if t == f or strip_unit(t) == strip_unit(f)]
            (wanted.extend(hit) if hit else unknown.append(f))
        if unknown:
            raise InputError(f"버전 '{version}'에 타겟 {unknown}이(가) 없습니다. [추천] {names}")
        names = list(dict.fromkeys(wanted))

    targets = []
    for t in names:
        safe = sanitize_filename(t)
        meta = load_json_file(os.path.join(vdir, f"model_{safe}.json"))
        oof_path = os.path.join(vdir, f"oof_{safe}.csv")
        if not os.path.isfile(oof_path):
            raise InputError(f"교차검증 예측 파일이 없습니다: {oof_path}. ml-kit 2.2.0 이상으로 다시 학습한 버전만 보고서를 만들 수 있습니다.")
        bench = leaderboard["targets"][t]
        targets.append({
            "name": t, "safe": safe, "task": record["task"], "meta": meta,
            "bench": bench, "champ": bench["champion"], "board": bench["leaderboard"],
            "oof": pd.read_csv(oof_path, encoding="utf-8-sig"),
            "classes": bench["champion"].get("classes"),
        })

    corr = None
    corr_path = os.path.join(vdir, "correlation.csv")
    if os.path.isfile(corr_path):
        corr = pd.read_csv(corr_path, index_col=0, encoding="utf-8-sig")

    lineage = [r for r in records if r.get("task") == record["task"]
               and sorted(r.get("targets", [])) == sorted(record["targets"])]
    seen, uniq = set(), []
    for r in reversed(lineage):  # last record wins for re-trained versions
        if r["version"] not in seen:
            seen.add(r["version"])
            uniq.append(r)
    lineage = sorted(uniq, key=lambda r: r.get("timestamp", ""))

    return {"version_dir": vdir, "data_root": data_root, "version": version, "record": record,
            "leaderboard": leaderboard, "targets": targets, "corr": corr, "lineage": lineage}


# ==============================================================================
# 5. Narrative (deterministic; --slots may override)
# ==============================================================================

def _metric_info(task: str) -> Tuple[str, str]:
    return ("val_r2", "R²") if task == "regression" else ("val_f1_macro", "Macro-F1")


def text_performance(t: Dict[str, Any]) -> str:
    c = t["champ"]
    if t["task"] == "regression":
        std = float(t["oof"]["actual"].std()) or 1.0
        lines = [
            f"챔피언 {c['champion_model']}의 교차검증 R²는 {c['val_r2']:.4f}, MAE는 {c['mae']:.4f}로 "
            f"타겟 표준편차({std:.4f})의 {c['mae'] / std:.0%} 수준입니다.",
        ]
        gap = c.get("overfit_gap", 0.0)
        lines.append(f"학습-검증 간극은 {gap:.4f}로 " + ("과적합 위험이 낮습니다." if gap <= 0.10 else
                     "과적합 경향이 있어 피처 축소나 데이터 추가가 권장됩니다."))
        skew = c.get("residual_skew", 0.0)
        lines.append(f"잔차 왜도는 {skew:.3f}로 " + ("대칭에 가까워 특정 구간의 체계적 편향은 작습니다." if abs(skew) <= 0.5 else
                     "한쪽으로 치우쳐 있어 높은/낮은 구간에서 편향된 예측이 나타날 수 있습니다."))
        iv = c.get("prediction_interval")
        if iv:
            lines.append(f"{int(iv['level'] * 100)}% 예측 범위는 예측값 기준 {iv['residual_lower']:+.3f} ~ {iv['residual_upper']:+.3f}입니다.")
        return "\n".join(lines)
    pc = c["per_class"]
    worst = min(pc, key=lambda k: pc[k]["recall"])
    lines = [
        f"챔피언 {c['champion_model']}의 교차검증 Macro-F1은 {c['val_f1_macro']:.4f}, 정확도 {c['accuracy']:.4f}, "
        f"균형 정확도 {c['balanced_accuracy']:.4f}입니다" + (f" (ROC-AUC {c['roc_auc']:.4f})." if c.get("roc_auc") is not None else "."),
        f"재현율이 가장 낮은 클래스는 '{worst}'({pc[worst]['recall']:.3f})이며, 이 클래스를 놓치는 오분류에 유의해야 합니다.",
    ]
    if c.get("class_weight"):
        lines.append("클래스 불균형으로 class_weight='balanced'가 적용되었습니다.")
    th = c.get("decision_threshold")
    if th:
        m = th["oof_positive_metrics"]
        lines.append(f"양성 클래스 '{th['positive_class']}' 판정 기준 확률은 {th['threshold']:.2f}이며, "
                     f"이때 양성 정밀도 {m['precision']:.3f}, 재현율 {m['recall']:.3f}, F1 {m['f1']:.3f}입니다.")
    return "\n".join(lines)


def text_features(t: Dict[str, Any]) -> str:
    c = t["champ"]
    top = c.get("top_features", [])
    schema = t["meta"]["feature_schema"]
    lines = []
    if top:
        lines.append("예측 기여도 상위 피처는 " + ", ".join(f"'{r['feature']}'({r['pct']:.1f}%)" for r in top) + "입니다.")
    if schema.get("categorical"):
        cats = [f for f in schema["categorical"] if any(r["feature"] == f for r in c["feature_importances"][:5])]
        if cats:
            lines.append(f"범주형 피처 {cats}이(가) 상위 기여 피처에 포함되어, 범주별 운전 조건 차이가 결과에 영향을 줍니다.")
    if schema.get("datetime"):
        lines.append(f"날짜 피처 {list(schema['datetime'])}은(는) {', '.join(sum(schema['datetime'].values(), []))} 단위로 분해해 반영했습니다.")
    weak = c.get("weak_features", [])
    if weak:
        lines.append(f"기여도 1% 이하 피처 {weak[:5]}은(는) 제외해도 성능 저하가 작을 가능성이 높습니다.")
    return "\n".join(lines) or "피처 중요도 정보가 없습니다."


# ==============================================================================
# 6. Document sections
# ==============================================================================

def build_report(ctx: Dict[str, Any], slots: Dict[str, Any], out_path: Optional[str],
                 overwrite: bool = False) -> Dict[str, Any]:
    _setup_matplotlib()
    rec, targets, version = ctx["record"], ctx["targets"], ctx["version"]
    task = rec["task"]
    metric_key, metric_label = _metric_info(task)
    prof = rec.get("data_profile", {})
    data_name = prof.get("source_file", "")
    task_ko = "회귀 (수치 예측)" if task == "regression" else "분류 (범주 예측)"
    slot_targets = slots.get("targets", {}) if isinstance(slots.get("targets"), dict) else {}
    slots_used: List[str] = []

    def slot(key: str, default: str, target: Optional[str] = None) -> str:
        if target is not None and isinstance(slot_targets.get(target), dict) and slot_targets[target].get(key):
            slots_used.append(f"targets.{target}.{key}")
            return str(slot_targets[target][key])
        if slots.get(key):  # document-level text (applies to every target when no target-specific one)
            if key not in slots_used:
                slots_used.append(key)
            return str(slots[key])
        return default

    verdicts = {}
    for t in targets:
        verdicts[t["name"]] = verdict_of(t["champ"].get("val_score"), t["champ"].get("overfit_gap"))
    overall = worst_verdict([v[0] for v in verdicts.values()])
    better = max((r for r in ctx["lineage"] if (r.get("mean_val_score") or -1) > rec["mean_val_score"] + 1e-9),
                 key=lambda r: r["mean_val_score"], default=None)

    R = ReportDoc(f"{REPORT_TITLE}  |  {data_name}  |  {version}")
    d = R.doc

    # -- Cover ---------------------------------------------------------------
    # Title is the first paragraph of the document (top margin via spacing, not empty paragraphs)
    title_p = R.para(REPORT_TITLE, size=28, bold=True, color=C_ACCENT, space_after=6)
    title_p.paragraph_format.space_before = Pt(110)
    R.para(rec.get("description") or "머신러닝 모델 학습 결과", size=13, color=C_INK, space_after=2)
    p = R.para(f"{data_name}  ·  {', '.join(t['name'] for t in targets)}", size=10, color=C_MUTED, space_after=28)
    _para_border_bottom(p, color=C_ACCENT, size=12)
    fg, bg = VERDICT_STYLE[overall]
    vt = d.add_table(rows=1, cols=2)
    vt.autofit = False
    _fix_widths(vt, [4.0, 4.0])
    lc, vc = vt.rows[0].cells
    _shade(lc, C_HEAD)
    _shade(vc, bg)
    for c in (lc, vc):
        _cell_margins(c, top=120, bottom=120, left=160, right=160)
    _set_run_font(lc.paragraphs[0].add_run("종합 판정"), size=10, bold=True, color=C_INK)
    vc.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_run_font(vc.paragraphs[0].add_run(overall), size=14, bold=True, color=fg)
    for _ in range(9):
        d.add_paragraph()
    R.kv_table([
        ("문서", f"{REPORT_TITLE} (ml-kit {REPORT_VERSION})"),
        ("학습 버전", f"{version}  ({rec.get('timestamp', '')[:19].replace('T', ' ')})"),
        ("작업 유형", task_ko),
        ("실험 메모", rec.get("tag") or "-"),
        ("작성일", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("작성 도구", "ml-kit ml_report.py (자동 생성)"),
    ])

    # -- Contents ------------------------------------------------------------
    R.page_break()
    R.para("목차", size=15, bold=True, color=C_ACCENT, space_after=12)
    toc = ["1. 요약", "2. 데이터", "3. 분석 방법", "4. 타겟별 결과"]
    toc += [f"    4.{i}. {t['name']}" for i, t in enumerate(targets, 1)]
    toc += ["5. 버전 이력", "6. 운영 가이드", "부록 A. 상관관계", "부록 B. 산출물 및 실행 환경"]
    for item in toc:
        q = R.para(item, size=10.5 if not item.startswith(" ") else 10,
                   color=C_INK if not item.startswith(" ") else C_MUTED, space_after=5)
        q.paragraph_format.left_indent = Cm(0.8 if item.startswith(" ") else 0)

    # -- 1. Summary ----------------------------------------------------------
    R.h1("1. 요약")
    best = max(targets, key=lambda t: t["champ"].get("val_score") or -1)
    R.metric_cards([
        ("종합 판정", overall, f"기준 {metric_label} {PASS_SCORE} 이상"),
        (f"평균 {metric_label}", f"{rec['mean_val_score']:.4f}", f"타겟 {len(targets)}개 평균"),
        ("학습 데이터", f"{prof.get('rows_loaded', 0):,}행", f"피처 {len(rec.get('features_used', []))}개"),
        ("최고 성능 모델", best["champ"]["champion_model"], best["name"]),
    ])
    rows = []
    for t in targets:
        c = t["champ"]
        err = (f"MAE {c['mae']:.4f}" if task == "regression" else f"정확도 {c['accuracy']:.4f}")
        rows.append([t["name"], c["champion_model"], c.get("val_score"), err, verdicts[t["name"]][0], verdicts[t["name"]][1]])
    R.table(["타겟", "챔피언 모델", metric_label, "보조 지표", "판정", "근거"], rows, caption="타겟별 결과 요약",
            widths=[3.0, 3.9, 1.8, 2.4, 1.5, 4.4], align=["left", "left", "right", "right", "center", "left"], verdict_col=4)
    recs = rec.get("recommendations") or []
    summary_default = "\n".join(
        [f"{t['name']}: {verdicts[t['name']][0]} - {t['champ']['champion_model']}, {metric_label} {t['champ']['val_score']:.4f}"
         for t in targets] + [f"권고: {r}" for r in recs[:3]]
        + ([f"참고: 같은 조건에서 더 높은 점수의 버전 {better['version']}({better['mean_val_score']:.4f})이 있습니다."] if better else []))
    R.note("요약 소견", slot("summary", summary_default))
    R.para(f"판정 기준: {metric_label} >= {PASS_SCORE} 적합, {CONDITIONAL_SCORE} 이상 조건부, 그 미만 부적합. "
           f"적합이라도 학습-검증 간극이 {OVERFIT_LIMIT}를 넘으면 조건부.", size=8.5, color=C_MUTED)

    # -- 2. Data -------------------------------------------------------------
    R.h1("2. 데이터")
    layout = prof.get("layout", {})
    layout_txt = ", ".join(f"{k.replace('_row', '')} {v}행" for k, v in layout.items() if v) or "자동 감지"
    R.kv_table([
        ("원본 파일", data_name),
        ("불러온 데이터", f"{prof.get('rows_loaded', 0):,}행 x {prof.get('columns_loaded', 0)}열 (표 구조: {layout_txt})"),
        ("학습에 사용", ", ".join(f"{t}: {n:,}행" for t, n in prof.get("rows_used", {}).items())),
        ("타겟 결측으로 제외", ", ".join(f"{t}: {n:,}행" for t, n in prof.get("target_missing_rows", {}).items())),
        ("결측 대치", f"피처 값 {prof.get('missing_imputed_cells', 0):,}칸 (수치=중앙값, 범주='__missing__')"),
        ("파생변수", "; ".join(rec.get("derived_evals") or []) or "없음"),
    ], caption="데이터 개요")
    schema = targets[0]["meta"]["feature_schema"]
    stats = targets[0]["meta"].get("feature_stats", {})
    dstats = targets[0]["meta"].get("datetime_stats", {})
    miss = prof.get("feature_missing", {})
    frows = []
    for f in schema["numeric"]:
        s = stats.get(f, {})
        frows.append([f, "수치", f"{fmt(s.get('min'), 3)} ~ {fmt(s.get('max'), 3)}", miss.get(f, 0)])
    for f, parts in schema.get("datetime", {}).items():
        s = dstats.get(f, {})
        frows.append([f, "날짜", f"{s.get('min', '')[:10]} ~ {s.get('max', '')[:10]} ({', '.join(parts)})", miss.get(f, 0)])
    for f, cats in schema.get("categorical", {}).items():
        shown = ", ".join(cats[:6]) + (f" 외 {len(cats) - 6}개" if len(cats) > 6 else "")
        frows.append([f, "범주", f"{len(cats)}개: {shown}", miss.get(f, 0)])
    R.table(["피처", "유형", "학습 범위 / 범주", "결측(칸)"], frows, caption="입력 피처 구성",
            widths=[4.2, 1.6, 9.0, 2.2], align=["left", "center", "left", "right"])
    R.figure(chart_target_distributions(targets), "타겟 분포 (학습에 사용된 행)")
    top_miss = sorted([(k, v) for k, v in miss.items() if v], key=lambda x: -x[1])[:3]
    data_default = (f"전체 {prof.get('rows_loaded', 0):,}행 중 타겟 값이 있는 행만 학습에 사용했습니다. "
                    + (f"결측이 많은 피처는 {', '.join(f'{k}({v}칸)' for k, v in top_miss)}이며 학습 데이터 기준값으로 대치했습니다."
                       if top_miss else "피처 결측은 없습니다."))
    R.note("데이터 소견", slot("data", data_default))

    # -- 3. Method -----------------------------------------------------------
    R.h1("3. 분석 방법")
    if task == "regression":
        models = "HistGradientBoosting, RandomForest, ExtraTrees, Ridge(alpha 자동 선택), ElasticNet(alpha, l1_ratio 자동 선택)"
        cv = "K-Fold 교차검증 (최대 5-fold, shuffle, seed 고정)"
        select = "교차검증 예측(OOF) 기준 R² 최고 모델"
    else:
        models = "HistGradientBoosting, RandomForest, ExtraTrees, LogisticRegression(C 자동 선택), KNeighbors"
        cv = "Stratified K-Fold 교차검증 (클래스 비율 유지, 최대 5-fold)"
        select = "교차검증 예측(OOF) 기준 Macro-F1 최고 모델 (클래스 불균형에 공정)"
    R.kv_table([
        ("작업 유형", task_ko),
        ("전처리", "수치: 중앙값 대치 + 표준화 / 범주: 원-핫 인코딩(처음 보는 값 무시) / 날짜: 연·월·일·요일·시 분해"),
        ("후보 모델", models),
        ("검증 방식", cv),
        ("챔피언 선정", select),
        ("최종 모델", "챔피언을 전체 데이터로 다시 학습하여 저장 (전처리 + 모델 일체형)"),
        ("피처 중요도", "순열 중요도 (최대 5,000행 표본, 5회 반복)"),
        ("누수 방지", "전처리는 각 fold의 학습 데이터로만 적합, 타겟은 피처와 파생 수식에 사용 불가"),
    ], caption="분석 방법", widths=(3.4, 13.6))

    # -- 4. Per-target results -------------------------------------------------
    R.h1("4. 타겟별 결과")
    for i, t in enumerate(targets, 1):
        c, board = t["champ"], t["board"]
        if i > 1:
            R.page_break()
        R.h2(f"4.{i}. {t['name']}")
        v, why = verdicts[t["name"]]
        R.para(f"판정: {v}  ({why})", size=9.5, bold=True, color=VERDICT_STYLE[v][0])

        R.h3(f"4.{i}.1. 모델 비교")
        if task == "regression":
            hdr = ["순위", "모델", "검증 R²", "학습 R²", "간극", "MAE", "RMSE", "선택된 설정"]
            body = [[e["rank"], e["model_name"], e["val_r2"], e["train_r2"], e["overfit_gap"], e["mae"], e["rmse"],
                     ", ".join(f"{k}={v:g}" for k, v in (e.get("params") or {}).items()) or "-"] for e in board]
            widths = [1.1, 4.1, 1.7, 1.7, 1.5, 1.8, 1.8, 3.3]
        else:
            hdr = ["순위", "모델", "Macro-F1", "학습 F1", "간극", "정확도", "균형 정확도", "ROC-AUC"]
            body = [[e["rank"], e["model_name"], e["val_f1_macro"], e["train_f1_macro"], e["overfit_gap"], e["accuracy"],
                     e["balanced_accuracy"], e.get("roc_auc")] for e in board]
            widths = [1.1, 4.1, 1.9, 1.9, 1.6, 1.8, 2.3, 2.3]
        R.table(hdr, body, caption=f"{t['name']} 후보 모델 교차검증 결과", widths=widths,
                align=["center", "left"] + ["right"] * (len(hdr) - 2), highlight_rows=[0])
        R.figure(chart_model_comparison(board, metric_key, f"교차검증 {metric_label}"), f"{t['name']} 모델별 {metric_label}")

        R.h3(f"4.{i}.2. 성능 검증")
        if task == "regression":
            R.metric_cards([
                ("검증 R²", f"{c['val_r2']:.4f}", "교차검증 예측 기준"),
                ("MAE", f"{c['mae']:.4f}", "평균 절대 오차"),
                ("RMSE", f"{c['rmse']:.4f}", "평균 제곱근 오차"),
                ("90% 예측 범위", f"±{(c['prediction_interval']['residual_upper'] - c['prediction_interval']['residual_lower']) / 2:.3f}",
                 "잔차 분위수 기반 근사"),
            ])
            R.figure(chart_actual_vs_pred(t["oof"], t["name"], c["val_r2"]), f"{t['name']} 실측 대비 예측 (교차검증)")
            R.figure(chart_residuals(t["oof"], c.get("prediction_interval")), f"{t['name']} 잔차 진단")
        else:
            R.metric_cards([
                ("Macro-F1", f"{c['val_f1_macro']:.4f}", "교차검증 예측 기준"),
                ("정확도", f"{c['accuracy']:.4f}", "전체 정답 비율"),
                ("균형 정확도", f"{c['balanced_accuracy']:.4f}", "클래스별 재현율 평균"),
                ("ROC-AUC", fmt(c.get("roc_auc")), "확률 순위 성능"),
            ])
            pc = c["per_class"]
            R.table(["클래스", "정밀도", "재현율", "F1", "실제 건수"],
                    [[k, m["precision"], m["recall"], m["f1"], m["support"]] for k, m in pc.items()],
                    caption=f"{t['name']} 클래스별 성능", widths=[4.0, 3.0, 3.0, 3.0, 3.0])
            R.figure(chart_confusion(c["confusion_matrix"]), f"{t['name']} 혼동행렬 (건수, 실제 클래스 대비 비율)")
            R.figure(chart_per_class(pc), f"{t['name']} 클래스별 정밀도·재현율·F1")
            if len(t["classes"]) == 2:
                th = c.get("decision_threshold") or {}
                positive = th.get("positive_class") or t["classes"][1]
                R.figure(chart_binary_curves(t["oof"], t["classes"], positive, th.get("threshold"), c.get("roc_auc")),
                         f"{t['name']} ROC 곡선 및 '{positive}' 판정 기준별 F1")
        R.note("성능 소견", slot("performance", text_performance(t), target=t["name"]))

        R.h3(f"4.{i}.3. 피처 영향")
        R.figure(chart_importance(c["feature_importances"]), f"{t['name']} 피처 기여도 (상위 12개)")
        R.note("피처 소견", slot("features", text_features(t), target=t["name"]))

    # -- 5. Lineage ------------------------------------------------------------
    R.h1("5. 버전 이력")
    lin = ctx["lineage"]
    R.para(f"같은 작업 유형과 타겟 조합({', '.join(rec['targets'])})으로 학습한 {len(lin)}개 버전의 이력입니다.", size=9.5)
    if better:
        R.para(f"참고: 이 보고서 버전({version}, {rec['mean_val_score']:.4f})보다 점수가 높은 버전 "
               f"{better['version']}({better['mean_val_score']:.4f})이 있습니다.", size=9.5, bold=True, color=VERDICT_STYLE['조건부'][0])
    if len(lin) >= 2:
        R.figure(chart_lineage([{"version": r["version"], "score": r.get("mean_val_score") or 0.0} for r in lin],
                               version, f"평균 {metric_label}"), f"버전별 평균 {metric_label} 추이 (원: 이 보고서 버전)")
    lrows, prev_feats = [], None
    for r in lin:
        feats = set(r.get("features_used", []))
        if prev_feats is None:
            change = "기준 버전"
        else:
            added, removed = sorted(feats - prev_feats), sorted(prev_feats - feats)
            change = "; ".join(x for x in ([f"추가 {added}" if added else ""] + [f"제외 {removed}" if removed else ""]) if x) or "피처 동일"
        prev_feats = feats
        delta = r.get("delta_score")
        lrows.append([r["version"], (r.get("timestamp") or "")[:10], r.get("tag") or "-", r.get("mean_val_score"),
                      "기준" if delta == "base" else (f"{delta:+.4f}" if isinstance(delta, (int, float)) else "-"), change])
    cur_idx = [k for k, r in enumerate(lin) if r["version"] == version]
    lineage_note = slot("lineage", "")
    R.table(["버전", "날짜", "메모", f"평균 {metric_label}", "변화", "피처 변경"], lrows, caption="버전별 변경 내용",
            widths=[1.4, 2.2, 3.2, 2.2, 1.6, 6.4], align=["center", "center", "left", "right", "right", "left"],
            highlight_rows=cur_idx)
    if lineage_note:
        R.note("버전 이력 소견", lineage_note)

    # -- 6. Operation ----------------------------------------------------------
    R.h1("6. 운영 가이드")
    here = os.path.dirname(os.path.abspath(__file__))
    R.kv_table([
        ("예측 명령 (파일)", f'python "{os.path.join(here, "ml_predict.py")}" -m "{ctx["version_dir"]}" -f "<새데이터.xlsx>"'),
        ("예측 명령 (단건)", f'python "{os.path.join(here, "ml_predict.py")}" -m "{ctx["version_dir"]}" -i "피처=값,피처=값"'),
        ("단독 배포", f"ml_predict.py 와 {version} 폴더 2가지만 복사 (numpy, pandas, scikit-learn, joblib 필요)"),
        ("필수 입력", ", ".join(targets[0]["meta"]["features_required"])),
    ], caption="예측 실행 방법", widths=(3.4, 13.6))
    R.table(["경고 (예측 결과 JSON)", "의미", "조치"], [
        ["drift_warning (extrapolation_warnings)", "입력값이 학습 범위(표 3) 또는 학습 기간을 벗어남", "결과를 참고값으로만 사용, 반복되면 재학습"],
        ["unseen_category_warning", "학습 때 없던 범주 값 (예: 신규 라인)", "해당 범주 데이터를 추가해 재학습"],
        ["missing_input_warning", "빈 값 또는 숫자가 아닌 값을 학습 기준값으로 대치", "입력 데이터 확인"],
        ["low_confidence_warning", "분류 확률이 0.6 미만인 예측", "해당 건은 사람이 최종 판정"],
    ], caption="예측 경고 해석", widths=[4.4, 6.6, 6.0], align=["left", "left", "left"])
    retrain = []
    if task == "regression":
        for t in targets:
            retrain.append(f"{t['name']}: 운영 중 실측 대비 MAE가 {t['champ']['mae'] * 1.5:.3f}(교차검증 MAE의 1.5배)를 넘으면 재학습")
    else:
        for t in targets:
            retrain.append(f"{t['name']}: 운영 중 Macro-F1이 {max(t['champ']['val_f1_macro'] - 0.10, 0):.3f} 아래로 떨어지면 재학습")
    retrain += ["외삽 또는 미학습 범주 경고가 전체 예측의 10% 이상이면 재학습", "공정 조건, 설비, 원료가 바뀌면 재학습"]
    R.note("운영 소견 및 재학습 기준", slot("operation", "\n".join(retrain)))

    # -- Appendix ----------------------------------------------------------------
    R.h1("부록 A. 상관관계")
    corr = ctx["corr"]
    if corr is not None and corr.shape[0] >= 2:
        order = [r["feature"] for r in targets[0]["champ"]["feature_importances"]]
        numeric_targets = [t["name"] for t in targets if t["task"] == "regression" and t["name"] in corr.columns]
        cols = [cc for cc in corr.columns if cc not in numeric_targets]
        owner_rank = {f: k for k, f in enumerate(order)}
        cols = sorted(cols, key=lambda cc: min([owner_rank.get(f, 999) for f in order if cc == f or cc.startswith(f + "_")] or [999]))
        keep = cols[:15] + numeric_targets
        R.figure(chart_correlation(corr.loc[keep, keep]), "수치 입력 및 타겟 간 피어슨 상관계수 (중요도 상위 15개)")
        pairs = []
        for a_i, a in enumerate(cols):
            for b in cols[a_i + 1:]:
                v = corr.loc[a, b]
                if np.isfinite(v) and abs(v) >= 0.85:
                    pairs.append((a, b, v))
        corr_default = ("다중공선성 주의(|r| >= 0.85) 피처 쌍: " + (", ".join(f"{a}-{b}({v:+.2f})" for a, b, v in pairs[:5])
                        if pairs else "없음"))
        R.note("상관관계 소견", slot("correlation", corr_default))
        R.para(f"전체 상관행렬: {os.path.join(ctx['version_dir'], 'correlation.csv')}", size=8.5, color=C_MUTED)
    else:
        R.para("수치 입력이 2개 미만이라 상관관계를 표시하지 않습니다.", size=9.5)

    R.h1("부록 B. 산출물 및 실행 환경")
    files = sorted(os.listdir(ctx["version_dir"]))
    R.table(["파일", "용도"], [[f, _file_purpose(f)] for f in files], caption=f"{version} 폴더 산출물",
            widths=[6.5, 10.5], align=["left", "left"])
    meta0 = targets[0]["meta"]
    R.kv_table([
        ("Python", meta0.get("python_version", "-")),
        ("scikit-learn", meta0.get("sklearn_version", "-")),
        ("데이터 폴더", ctx["data_root"]),
        ("버전 폴더", ctx["version_dir"]),
        ("학습 소요 시간", f"{rec.get('duration_sec', 0):.1f}초"),
    ], caption="실행 환경")

    # -- Save --------------------------------------------------------------------
    if not out_path:
        out_path = os.path.join(ctx["data_root"], f"ML결과보고서_{os.path.splitext(data_name)[0]}_{version}.docx")
    out_abs = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    warn_long_path(out_abs)
    out_abs = avoid_overwrite(out_abs, overwrite, what="보고서")
    saved = R.save(out_abs)

    return {
        "status": "ok",
        "report_file": saved,
        "best_version": version,
        "version": version,
        "task": task,
        "targets": [t["name"] for t in targets],
        "overall_verdict": overall,
        "verdicts": {k: v[0] for k, v in verdicts.items()},
        "figure_count": R.figure_no,
        "table_count": R.table_no,
        "slots_used": slots_used,
        "preview": f"[보고서 완료] {version} / 타겟 {len(targets)}개 / 종합 판정 {overall} / 저장: {os.path.basename(saved)}",
        "agent_directive": (f"VERIFIED: ML result report for {version} ({len(targets)} target(s)) saved to "
                            f"'{os.path.basename(saved)}'. Overall verdict={overall}. Next step: report the file path to the user."),
    }


def _file_purpose(name: str) -> str:
    if name.startswith("model_") and name.endswith(".joblib"):
        return "예측 모델 (전처리 + 챔피언 모델)"
    if name.startswith("model_") and name.endswith(".json"):
        return "모델 메타데이터 (피처 구성, 학습 범위, 지표)"
    if name.startswith("oof_"):
        return "교차검증 예측값 (보고서 그림 원본)"
    if name.startswith("next_features_"):
        return "다음 학습 명령용 피처 목록"
    return {
        "leaderboard.json": "후보 모델 비교 결과",
        "correlation.csv": "전체 상관행렬",
        "model_dataset.csv": "학습 데이터 스냅샷 (정제 후)",
    }.get(name, "-")


# ==============================================================================
# 7. CLI
# ==============================================================================

LEGACY_SLOTS = {  # names accepted by ml_report.py 2.1 and earlier
    "slot1_residual": "performance", "residual": "performance",
    "slot2_feature": "features", "feature": "features",
    "slot3_lineage": "lineage",
    "slot4_correlation": "correlation",
    "slot5_serving": "operation", "serving": "operation",
}


def parse_slots(raw: Optional[str]) -> Dict[str, Any]:
    data = _read_slots(raw)
    for old, new in LEGACY_SLOTS.items():
        if data.get(old) and not data.get(new):
            data[new] = data[old]
    return data


def _read_slots(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    s_raw = raw.strip()
    try:
        if os.path.isfile(s_raw):
            data = load_json_file(s_raw)
        elif s_raw.startswith("{"):
            data = json.loads(s_raw)
        else:
            raise InputError("--slots는 JSON 파일 경로 또는 '{'로 시작하는 JSON 문자열이어야 합니다.")
        if not isinstance(data, dict):
            raise InputError("슬롯 JSON은 객체({...})여야 합니다.")
        return data
    except (InputError, ValueError) as e:
        sys.stderr.write(f"[WARN] 슬롯 JSON 파싱 실패 ({e}) -> 자동 작성 소견 사용\n")
        return {}


def resolve_version_dir(args: argparse.Namespace) -> str:
    """-m <version_dir> wins; otherwise -d <data_root> with -v, or the best version of the latest experiment."""
    if args.model:
        return args.model
    if not args.data_dir:
        raise InputError("보고서를 만들 버전 폴더(-m <version_dir>) 또는 데이터 폴더(-d <data_root>)를 지정하십시오.")
    root = os.path.abspath(args.data_dir)
    if os.path.isfile(root):  # history.json(l) path given (2.1 style)
        root = os.path.dirname(root)
    if args.version:
        return os.path.join(root, normalize_version(args.version))
    ledger = os.path.join(root, "history.jsonl")
    if not os.path.isfile(ledger):
        raise InputError(f"실험 원장(history.jsonl)이 없습니다: {ledger}")
    records = _read_jsonl(ledger)
    if not records:
        raise InputError(f"실험 원장이 비어 있습니다: {ledger}")
    latest = records[-1]
    same = [r for r in records if r.get("task", "regression") == latest.get("task", "regression")
            and sorted(r.get("targets", [])) == sorted(latest.get("targets", []))
            and isinstance(r.get("mean_val_score"), (int, float))]
    best = max(same, key=lambda r: r["mean_val_score"]) if same else latest
    sys.stderr.write(f"[INFO] 보고서 버전 자동 선택: {best['version']} (최근 학습과 같은 타겟 조합 중 최고 점수)\n")
    return os.path.join(root, best["version"])


def execute_report(args: argparse.Namespace) -> Dict[str, Any]:
    for err, pkg in ((_DOCX_IMPORT_ERROR, "python-docx"), (_MPL_IMPORT_ERROR, "matplotlib")):
        if err is not None:
            raise InputError(f"보고서 생성에 필요한 {pkg} 패키지가 설치되어 있지 않습니다 ({err}). docs/ENVIRONMENT.md를 참고하십시오.")
    target_filter = None
    if args.target and args.target.strip().lower() != "all":
        target_filter = [t.strip() for t in args.target.split(",") if t.strip()]
    ctx = load_version(resolve_version_dir(args), target_filter)
    return build_report(ctx, parse_slots(args.slots), args.out, overwrite=args.overwrite)


def main():
    parser = JsonArgumentParser(description="ML 결과 보고서 (Word) generator for one trained version")
    parser.add_argument("--model", "-m",
                        help="보고서를 만들 학습 버전 폴더 (학습 결과 JSON의 version_dir, 예: data_ml_data\\v3)")
    parser.add_argument("--data-dir", "-d", "--history", "-H", dest="data_dir",
                        help="데이터 폴더 (<파일명>_ml_data). -v 생략 시 최근 학습과 같은 타겟 조합 중 최고 버전")
    parser.add_argument("--version", "-v", help="-d와 함께 쓸 버전 (예: v2 또는 2)")
    parser.add_argument("--target", "-t", help="문서에 넣을 타겟만 지정 (쉼표 구분, 생략 또는 all = 전체)")
    parser.add_argument("--out", "-o", help="저장할 .docx 경로 (생략 시 데이터 폴더에 ML결과보고서_<데이터>_<버전>.docx)")
    parser.add_argument("--overwrite", action="store_true",
                        help="같은 이름의 보고서가 있으면 덮어쓰기 (생략 시 시각을 붙인 새 이름으로 저장)")
    parser.add_argument("--slots", help="소견 덮어쓰기 JSON 파일 또는 문자열: summary, data, performance, features, lineage, "
                                        "correlation, operation, targets.{타겟}.{performance|features}")
    args = parser.parse_args()
    if not args.model and not args.data_dir:
        parser.error("-m <version_dir> 또는 -d <data_root> 중 하나를 지정해야 합니다.")
    run_cli(lambda: execute_report(args), hint="Check the version folder path (version_dir from the training result).")


if __name__ == "__main__":
    main()
