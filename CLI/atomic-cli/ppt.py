"""ppt.py - 파워포인트 작업

명령:
    read     슬라이드 내용 읽기 (제목, 본문, 표, 노트). 사용자 화면은 움직이지 않음
    info     프레젠테이션 요약 (슬라이드별 제목, 도형/표/그림 수). --all: 열린 프레젠테이션 전체 목록
    write    제목/본문/표/그림/카드 넣기. --file의 마크다운은 제목(#, ##)마다 새 슬라이드
    replace  찾아 바꾸기 (+서식). 표, 그룹 도형 포함
    export   PDF / PPTX 사본 저장 (원본은 그대로)
    slide    슬라이드 추가/복제/이동/삭제/비우기/목록

--target: active(기본, 지금 보고 있는 프레젠테이션) | 열린 프레젠테이션 이름 | 파일 경로
--slide: 슬라이드 번호 (1부터). write에서 new는 맨 뒤에 새 슬라이드
닫힌 .pptx 읽기는 PowerPoint를 띄우지 않고 python-pptx로 읽습니다.

예:
    python ppt.py write --slide new --title "추진 전략" --text "- 안정성\n- 확장성"
    python ppt.py write --file "검색결과.md"
    python ppt.py write --slide 3 --image chart.png
    python ppt.py write --slide new --title "핵심 가치" --cards "안정성:무중단|확장성:모듈 구조|보안:폐쇄망"
    python ppt.py slide --action move --slide 1 --to 3
"""
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _office as off  # noqa: E402
import _runtime as rt  # noqa: E402

TOOL = "ppt"

PP_LAYOUT = {"title": 1, "text": 2, "title_only": 11, "blank": 12}
PH_TITLE = (1, 3)          # ppPlaceholderTitle, ppPlaceholderCenterTitle
PH_BODY = (2, 7)           # ppPlaceholderBody, ppPlaceholderObject
MSO_GROUP = 6
MSO_PLACEHOLDER = 14
MSO_ROUNDED_RECT = 5
MARGIN = 36.0
GAP = 14.0
TABLE_ROWS_PER_SLIDE = 15
MAX_NEW_SLIDES = 30


# ==============================================================================
# 1. 도형 텍스트 도우미
# ==============================================================================

def _has(shape: Any, attr: str) -> bool:
    try:
        return bool(getattr(shape, attr))
    except Exception:
        return False


def iter_text_ranges(shape: Any):
    """도형 안의 모든 TextRange (그룹은 재귀, 표는 셀마다)."""
    try:
        if shape.Type == MSO_GROUP:
            items = shape.GroupItems
            for i in range(1, items.Count + 1):
                yield from iter_text_ranges(items.Item(i))
            return
    except Exception:
        pass
    if _has(shape, "HasTable"):
        tbl = shape.Table
        for r in range(1, tbl.Rows.Count + 1):
            for c in range(1, tbl.Columns.Count + 1):
                try:
                    yield tbl.Cell(r, c).Shape.TextFrame.TextRange
                except Exception:
                    continue
        return
    if _has(shape, "HasTextFrame") and _has(shape.TextFrame, "HasText"):
        yield shape.TextFrame.TextRange


def _shape_lines(shape: Any) -> List[str]:
    if _has(shape, "HasTable"):
        tbl = shape.Table
        rows = []
        for r in range(1, tbl.Rows.Count + 1):
            cells = []
            for c in range(1, tbl.Columns.Count + 1):
                try:
                    cells.append(str(tbl.Cell(r, c).Shape.TextFrame.TextRange.Text).replace("\r", " ").strip())
                except Exception:
                    cells.append("")
            rows.append(" | ".join(cells))
        return rows
    out: List[str] = []
    for tr in iter_text_ranges(shape):
        out += [ln.strip() for ln in str(tr.Text).replace("\x0b", "\r").split("\r") if ln.strip()]
    return out


def _title_shape(slide: Any) -> Optional[Any]:
    try:
        if slide.Shapes.HasTitle:
            return slide.Shapes.Title
    except Exception:
        pass
    return None


def slide_units(slide: Any, idx: int) -> Dict[str, Any]:
    title_shape = _title_shape(slide)
    title = ""
    if title_shape is not None:
        try:
            title = str(title_shape.TextFrame.TextRange.Text).strip()
        except Exception:
            pass
    lines: List[str] = []
    for i in range(1, slide.Shapes.Count + 1):
        sh = slide.Shapes(i)
        if title_shape is not None and sh.Name == title_shape.Name:
            continue
        lines += _shape_lines(sh)
    notes = ""
    try:
        notes = str(slide.NotesPage.Shapes.Placeholders(2).TextFrame.TextRange.Text).strip()
    except Exception:
        pass
    return {"no": idx, "title": title or (lines[0] if lines else ""), "text": "\n".join(lines), "notes": notes}


# ==============================================================================
# 2. read / info
# ==============================================================================

def _closed_pptx(target: str) -> Optional[str]:
    if not target or target.strip().lower() == "active":
        return None
    raw = os.path.abspath(os.path.expandvars(target.strip().strip('"')))
    if not os.path.isfile(raw):
        cand = os.path.join(rt.get_data_dir(), target.strip().strip('"'))
        if not os.path.isfile(cand):
            return None
        raw = cand
    if os.path.splitext(raw)[1].lower() not in (".pptx", ".pptm"):
        return None
    import zipfile
    if not zipfile.is_zipfile(raw):
        return None
    try:
        if off.win32com is not None and off.match_open("ppt", raw) is not None:
            return None
    except Exception:
        pass
    return raw


def cmd_read(args) -> Dict[str, Any]:
    import reader
    closed = _closed_pptx(args.target)
    if closed:
        units, _ = reader.parse_pptx(closed)
        slides = [{"no": i, "title": u["heading"], "text": u["text"]} for i, u in enumerate(units, 1)]
        source = {"app": "PowerPoint", "name": os.path.basename(closed), "path": closed, "source": "file(python-pptx)"}
    else:
        with off.open_target("ppt", args.target, readonly=True) as t:       # 읽기: 화면 이동 없음
            prs = t.doc
            numbers = reader.parse_pages(args.slides, prs.Slides.Count) if prs.Slides.Count else []
            slides = [slide_units(prs.Slides(n), n) for n in numbers]
            source = t.resolved()
            total = int(prs.Slides.Count)
    if closed:
        total = len(slides)
        numbers = reader.parse_pages(args.slides, total) if total else []
        slides = [slides[n - 1] for n in numbers]
    result: Dict[str, Any] = {"target_resolved": source, "slides_total": total}
    if args.save:
        units = [{"loc": f"슬라이드 {s['no']}", "heading": s["title"], "text": s["text"]} for s in slides]
        out = rt.resolve_output_path(None if args.save is True else args.save, os.path.splitext(source["name"])[0], ".md")
        out = rt.write_text(out, reader.units_to_markdown(source["name"], units))
        result.update(output_file=out, next_commands=[
            rt.next_command("word.py", ["write", "--file", out], "저장한 내용을 열린 워드 문서에 넣기"),
            rt.next_command("office.py", ["transfer", "--from", "ppt", "--what", "text", "--to", "excel"],
                            "슬라이드 내용을 엑셀 표로 옮기기")])
        return rt.ok(TOOL, "read", f"{source['name']}: 슬라이드 {len(slides)}장을 저장했습니다 ({out})", **result)
    shown: List[Dict[str, Any]] = []
    used = 0
    for s in slides:
        size = len(s["text"]) + len(s["title"]) + 20
        if shown and used + size > rt.DEFAULT_MAX_CHARS:
            break
        shown.append(s)
        used += size
    truncated = len(shown) < len(slides)
    result.update(slides=shown, truncated=truncated)
    if truncated:
        nxt = shown[-1]["no"] + 1
        last = slides[-1]["no"]
        result["next_commands"] = [rt.next_command("ppt.py", ["read", "--target", args.target, "--slides", f"{nxt}-{last}"],
                                                   "나머지 슬라이드 이어서 읽기")]
    return rt.ok(TOOL, "read", f"{source['name']}: 슬라이드 {len(shown)}장 표시 (전체 {total}장)",
                 "VERIFIED: 읽기 완료. 일부만 표시되었으면 next_commands로 이어서 읽으세요." if truncated else "", **result)


def cmd_info(args) -> Dict[str, Any]:
    if args.all:
        items = [{"name": d["name"], "path": d["path"], "saved": d["saved"], "active": d["active"]}
                 for d in off.list_open("ppt")]
        return rt.ok(TOOL, "info", f"열린 프레젠테이션 {len(items)}개", presentations=items)
    with off.open_target("ppt", args.target, readonly=True) as t:
        prs = t.doc
        slides = []
        for i in range(1, prs.Slides.Count + 1):
            s = prs.Slides(i)
            tables = pictures = 0
            for k in range(1, s.Shapes.Count + 1):
                sh = s.Shapes(k)
                if _has(sh, "HasTable"):
                    tables += 1
                try:
                    if sh.Type in (13, 11) or (sh.Type == MSO_PLACEHOLDER and sh.PlaceholderFormat.ContainedType == 13):
                        pictures += 1
                except Exception:
                    pass
            u = slide_units(s, i)
            slides.append({"no": i, "title": u["title"][:60], "shapes": int(s.Shapes.Count), "tables": tables,
                           "pictures": pictures, "chars": len(u["text"]) + len(u["title"])})
        size = {"width": float(prs.PageSetup.SlideWidth), "height": float(prs.PageSetup.SlideHeight)}
        result = {"target_resolved": t.resolved(), "slides_total": len(slides), "slides": slides,
                  "slide_size": size, "saved": off.is_saved(prs)}
    return rt.ok(TOOL, "info", f"{result['target_resolved']['name']}: 슬라이드 {len(slides)}장", **result)


# ==============================================================================
# 3. write
# ==============================================================================

class SlideWriter:
    """슬라이드 하나에 요소를 위에서 아래로 쌓습니다 (슬라이드 경계 안에서)."""

    def __init__(self, prs: Any, slide: Any, theme: Dict[str, Any]):
        self.prs = prs
        self.slide = slide
        self.theme = theme
        self.W = float(prs.PageSetup.SlideWidth)
        self.H = float(prs.PageSetup.SlideHeight)
        self.created: List[str] = []

    def _empty_placeholder(self, sh: Any) -> bool:
        try:
            return sh.Type == MSO_PLACEHOLDER and _has(sh, "HasTextFrame") and not _has(sh.TextFrame, "HasText")
        except Exception:
            return False

    def next_top(self) -> float:
        bottom = MARGIN
        for i in range(1, self.slide.Shapes.Count + 1):
            sh = self.slide.Shapes(i)
            if self._empty_placeholder(sh):
                continue
            try:
                bottom = max(bottom, float(sh.Top) + float(sh.Height))
            except Exception:
                pass
        return bottom + GAP

    def space_left(self) -> float:
        return self.H - MARGIN - self.next_top()

    def title(self, text: str) -> None:
        ts = _title_shape(self.slide)
        if ts is not None:
            ts.TextFrame.TextRange.Text = text
        else:
            box = self.slide.Shapes.AddTextbox(1, MARGIN, MARGIN * 0.6, self.W - 2 * MARGIN, 50)
            tr = box.TextFrame.TextRange
            tr.Text = text
            tr.Font.Size = 28
            tr.Font.Bold = True
            tr.Font.Color.RGB = off.parse_color(self.theme["primary"])
        self.created.append("제목")

    def _body_placeholder(self) -> Optional[Any]:
        for i in range(1, self.slide.Shapes.Count + 1):
            sh = self.slide.Shapes(i)
            try:
                if sh.Type == MSO_PLACEHOLDER and sh.PlaceholderFormat.Type in PH_BODY and not _has(sh.TextFrame, "HasText"):
                    return sh
            except Exception:
                continue
        return None

    def body(self, lines: List[Tuple[str, bool]]) -> None:
        """lines: [(텍스트, 글머리 여부)]"""
        text = "\r".join(t for t, _ in lines)
        ph = self._body_placeholder()
        if ph is not None:
            shape = ph
            shape.TextFrame.TextRange.Text = text
        else:
            top = self.next_top()
            height = max(40.0, min(self.H - MARGIN - top, 28.0 * len(lines) + 10))
            shape = self.slide.Shapes.AddTextbox(1, MARGIN, top, self.W - 2 * MARGIN, height)
            shape.TextFrame.WordWrap = -1
            tr = shape.TextFrame.TextRange
            tr.Text = text
            tr.Font.Size = 18 if len(lines) <= 6 else 14
        tr = shape.TextFrame.TextRange
        for i, (_, bullet) in enumerate(lines, 1):
            try:
                tr.Paragraphs(i).ParagraphFormat.Bullet.Visible = -1 if bullet else 0
            except Exception:
                pass
        self.created.append(f"본문 {len(lines)}줄")

    def table(self, rows: List[List[Any]]) -> None:
        nrows, ncols = len(rows), max(len(r) for r in rows)
        top = self.next_top()
        height = min(self.H - MARGIN - top, 26.0 * nrows)
        shape = self.slide.Shapes.AddTable(nrows, ncols, MARGIN, top, self.W - 2 * MARGIN, max(height, 26.0))
        tbl = shape.Table
        size = 14 if nrows <= 8 else 11
        header_bg = off.parse_color(self.theme["header_bg"])
        header_fg = off.parse_color(self.theme["header_fg"])
        for r, row in enumerate(rows, 1):
            for c in range(1, ncols + 1):
                value = row[c - 1] if c - 1 < len(row) else ""
                cell = tbl.Cell(r, c).Shape
                tr = cell.TextFrame.TextRange
                tr.Text = "" if value is None else str(value)
                tr.Font.Size = size
                if r == 1:
                    tr.Font.Bold = True
                    tr.Font.Color.RGB = header_fg
                    cell.Fill.ForeColor.RGB = header_bg
        self.created.append(f"표 {nrows}x{ncols}")

    def image(self, path: str, width: Optional[float]) -> None:
        top = self.next_top()
        pic = self.slide.Shapes.AddPicture(FileName=path, LinkToFile=0, SaveWithDocument=-1, Left=MARGIN, Top=top)
        max_w = width or (self.W - 2 * MARGIN)
        max_h = max(60.0, self.H - MARGIN - top)
        w0, h0 = float(pic.Width), float(pic.Height)
        ratio = min(max_w / w0, max_h / h0)            # 남은 공간 안에 들어가는 최대 배율
        if not width:
            ratio = min(ratio, 1.0)                    # 너비를 지정하지 않았으면 원본보다 키우지 않음
        pic.LockAspectRatio = -1
        pic.Width = w0 * ratio
        pic.Height = h0 * ratio
        pic.Left = (self.W - float(pic.Width)) / 2
        self.created.append(f"그림 {os.path.basename(path)}")

    def cards(self, cards: List[Tuple[str, str]]) -> None:
        n = len(cards)
        top = self.next_top()
        height = max(80.0, min(self.H - MARGIN - top, 220.0))
        total = self.W - 2 * MARGIN
        w = (total - GAP * (n - 1)) / n
        primary = off.parse_color(self.theme["primary"])
        light = off.parse_color(self.theme["light"])
        for i, (head, desc) in enumerate(cards):
            box = self.slide.Shapes.AddShape(MSO_ROUNDED_RECT, MARGIN + i * (w + GAP), top, w, height)
            box.Fill.ForeColor.RGB = light
            box.Line.ForeColor.RGB = primary
            box.Line.Weight = 1.5
            tr = box.TextFrame.TextRange
            tr.Text = head + ("\r" + desc if desc else "")
            tr.Font.Color.RGB = 0x333333
            tr.Font.Size = 14
            first = tr.Paragraphs(1)
            first.Font.Bold = True
            first.Font.Size = 18
            first.Font.Color.RGB = primary
        self.created.append(f"카드 {n}개")


def _new_slide(prs: Any, index: int, with_title: bool) -> Any:
    return prs.Slides.Add(index, PP_LAYOUT["title_only"] if with_title else PP_LAYOUT["blank"])


def _md_sections(text: str) -> List[Dict[str, Any]]:
    """마크다운을 슬라이드 단위로 나눕니다: '#'/'##' 제목마다 새 슬라이드, 그 밖의 블록은 본문/표."""
    sections: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for kind, payload in rt.parse_markdown_blocks(text):
        if kind == "heading" and payload[0] <= 2:
            cur = {"title": payload[1], "lines": [], "tables": []}
            sections.append(cur)
            continue
        if cur is None:
            cur = {"title": "", "lines": [], "tables": []}
            sections.append(cur)
        if kind == "heading":
            cur["lines"].append((payload[1], False))
        elif kind == "paragraph":
            cur["lines"].append((rt.split_bold(payload)[0], False))
        elif kind in ("bullets", "numbered"):
            cur["lines"] += [(rt.split_bold(x)[0], True) for x in payload]
        elif kind == "table":
            cur["tables"].append(payload)
    return [s for s in sections if s["title"] or s["lines"] or s["tables"]]


def _text_lines(text: str) -> List[Tuple[str, bool]]:
    lines = []
    for ln in text.replace("\\n", "\n").splitlines():
        s = ln.strip()
        if not s:
            continue
        m = re.match(r"^[-*+]\s+(.*)$", s)
        lines.append((rt.split_bold(m.group(1) if m else s)[0], bool(m)))
    return lines


def _parse_cards(raw: str) -> List[Tuple[str, str]]:
    cards = []
    for part in raw.split("|"):
        if not part.strip():
            continue
        head, _, desc = part.partition(":")
        cards.append((head.strip(), desc.strip()))
    if not 1 <= len(cards) <= 5:
        raise rt.InputError("--cards는 1~5개를 '제목:내용|제목:내용' 형식으로 주세요.")
    return cards


def _resolve_slide(prs: Any, value: Optional[str], default_new: bool) -> Tuple[Optional[int], bool]:
    """(슬라이드 번호, 새로 만들지). value: None | 'new' | 숫자"""
    count = int(prs.Slides.Count)
    if value is None:
        return (None, True) if default_new or count == 0 else (count, False)
    if str(value).strip().lower() == "new":
        return None, True
    try:
        n = int(value)
    except ValueError:
        raise rt.InputError(f"--slide는 번호 또는 new여야 합니다: {value}")
    if not 1 <= n <= count:
        raise rt.InputError(f"슬라이드 {n}번이 없습니다 (전체 {count}장). 새 슬라이드는 --slide new")
    return n, False


def cmd_write(args) -> Dict[str, Any]:
    if not any([args.title, args.text, args.file, args.image, args.cards]):
        raise rt.InputError("넣을 내용이 없습니다. --title, --text, --file, --image, --cards 중 하나 이상을 지정하세요.")
    theme = off.get_theme(args.theme or "navy")
    md_sections: List[Dict[str, Any]] = []
    table_rows: Optional[List[List[str]]] = None
    if args.file:
        path = rt.resolve_input_path(args.file, "입력 파일")
        if os.path.splitext(path)[1].lower() in (".csv", ".tsv"):
            table_rows = rt.read_csv_rows(path)
            if not table_rows:
                raise rt.InputError(f"입력 표 파일이 비어 있습니다: {args.file}")
        else:
            md_sections = _md_sections(rt.read_text_file(path))
            if len(md_sections) > MAX_NEW_SLIDES:
                raise rt.InputError(f"파일 내용이 슬라이드 {len(md_sections)}장 분량입니다 (최대 {MAX_NEW_SLIDES}장). 내용을 줄여 주세요.")
    image = rt.resolve_input_path(args.image, "그림 파일") if args.image else None
    cards = _parse_cards(args.cards) if args.cards else None

    with off.open_target("ppt", args.target, readonly=False, focus=not args.no_focus, create=True,
                         tool=TOOL, command="write") as t:
        prs = t.doc
        created: List[str] = []
        touched: List[int] = []
        slide_no, make_new = _resolve_slide(prs, args.slide, default_new=bool(md_sections or table_rows) and args.slide is None)
        insert_at = int(prs.Slides.Count) + 1 if slide_no is None else slide_no + 1

        def open_slide(with_title: bool) -> Tuple[Any, int]:
            nonlocal slide_no, make_new, insert_at
            if make_new:
                s = _new_slide(prs, insert_at, with_title)
                no = insert_at
                insert_at += 1
            else:
                no = slide_no
                s = prs.Slides(no)
                make_new = True              # 두 번째 섹션부터는 새 슬라이드
            touched.append(no)
            return s, no

        if md_sections:
            for k, sec in enumerate(md_sections):
                s, no = open_slide(bool(sec["title"]))
                w = SlideWriter(prs, s, theme)
                if sec["title"]:
                    w.title(sec["title"])
                if sec["lines"]:
                    w.body(sec["lines"])
                for tb in sec["tables"]:
                    w.table(tb)
                created.append(f"슬라이드 {no}: " + ", ".join(w.created))
        if table_rows:
            header, body_rows = table_rows[0], table_rows[1:] or [[""] * len(table_rows[0])]
            for k in range(0, len(body_rows), TABLE_ROWS_PER_SLIDE):     # 긴 표는 머리글을 반복해 여러 슬라이드로
                s, no = open_slide(bool(args.title))
                w = SlideWriter(prs, s, theme)
                if args.title:
                    w.title(args.title + (f" ({k // TABLE_ROWS_PER_SLIDE + 1})" if len(body_rows) > TABLE_ROWS_PER_SLIDE else ""))
                w.table([header] + body_rows[k:k + TABLE_ROWS_PER_SLIDE])
                created.append(f"슬라이드 {no}: " + ", ".join(w.created))
        if args.text or (args.title and not table_rows and not md_sections) or image or cards:
            # 파일 내용을 이미 넣었으면 그 마지막 슬라이드에 이어서, 아니면 대상 슬라이드에
            s, no = (prs.Slides(touched[-1]), touched[-1]) if touched else open_slide(bool(args.title))
            w = SlideWriter(prs, s, theme)
            if args.title and not table_rows:
                w.title(args.title)
            if args.text:
                w.body(_text_lines(args.text))
            if cards:
                w.cards(cards)
            if image:
                if w.space_left() < 80:              # 공간이 부족하면 다음 새 슬라이드에
                    s, no = open_slide(False)
                    w = SlideWriter(prs, s, theme)
                w.image(image, args.width)
            created.append(f"슬라이드 {no}: " + ", ".join(w.created))
        t.set_focus(slide=touched[-1])
        resolved = t.resolved()
    return rt.ok(TOOL, "write", "; ".join(created), "VERIFIED: 쓰기 완료. 다시 읽어서 확인하지 마세요.",
                 target_resolved=resolved, slides_written=sorted(set(touched)))


# ==============================================================================
# 4. replace
# ==============================================================================

def _load_map(args) -> Dict[str, str]:
    if args.map:
        raw = args.map.strip()
        if not raw.startswith("{"):
            raw = rt.read_text_file(rt.resolve_input_path(raw, "치환 목록 파일"))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise rt.InputError(f"--map은 JSON 객체여야 합니다 (예: {{\"진행중\": \"완료\"}}): {e}")
        if not isinstance(data, dict) or not data:
            raise rt.InputError("--map은 비어 있지 않은 JSON 객체여야 합니다.")
        return {str(k): ("" if v is None else str(v)) for k, v in data.items()}
    if args.find is None:
        raise rt.InputError("--find 또는 --map을 지정하세요.")
    return {args.find: args.find if args.replace is None else args.replace}


def replace_in_range(tr: Any, find: str, rep: str, match_case: bool, fmt: Dict[str, Any]) -> int:
    """TextRange.Replace를 반복합니다. 바꾼 글 뒤부터 이어서 찾아 무한 반복을 막습니다."""
    text = str(tr.Text)
    if (find not in text) if match_case else (find.lower() not in text.lower()):
        return 0
    count = 0
    after = 0
    while count < 1000:
        found = tr.Replace(FindWhat=find, ReplaceWhat=rep, After=after, MatchCase=-1 if match_case else 0, WholeWords=0)
        if found is None:
            break
        count += 1
        if fmt:
            font = found.Font
            if "bold" in fmt:
                font.Bold = -1 if fmt["bold"] else 0
            if "italic" in fmt:
                font.Italic = -1 if fmt["italic"] else 0
            if "size" in fmt:
                font.Size = fmt["size"]
            if "color" in fmt:
                font.Color.RGB = fmt["color"]
        after = int(found.Start) - 1 + len(rep)
        if after >= len(str(tr.Text)):
            break
    return count


def cmd_replace(args) -> Dict[str, Any]:
    mapping = _load_map(args)
    fmt: Dict[str, Any] = {}
    if args.bold is not None:
        fmt["bold"] = args.bold
    if args.italic is not None:
        fmt["italic"] = args.italic
    if args.size:
        fmt["size"] = args.size
    if args.color:
        fmt["color"] = off.parse_color(args.color)
    counts: Dict[str, int] = {}
    slides_changed: List[int] = []
    with off.open_target("ppt", args.target, readonly=False, focus=not args.no_focus, tool=TOOL, command="replace") as t:
        prs = t.doc
        numbers = [int(args.slide)] if args.slide else list(range(1, prs.Slides.Count + 1))
        for n in numbers:
            if not 1 <= n <= prs.Slides.Count:
                raise rt.InputError(f"슬라이드 {n}번이 없습니다 (전체 {prs.Slides.Count}장).")
            slide = prs.Slides(n)
            changed = False
            for k in range(1, slide.Shapes.Count + 1):
                for tr in iter_text_ranges(slide.Shapes(k)):
                    for find, rep in mapping.items():
                        c = replace_in_range(tr, find, rep, args.match_case, fmt)
                        if c:
                            counts[find] = counts.get(find, 0) + c
                            changed = True
            if changed:
                slides_changed.append(n)
        if slides_changed:
            t.set_focus(slide=slides_changed[0])
        resolved = t.resolved()
    total = sum(counts.values())
    result = {"target_resolved": resolved, "replaced": total, "by_text": counts, "slides": slides_changed}
    if not total:
        return rt.ok(TOOL, "replace", "일치하는 문구가 없습니다",
                     "VERIFIED: 일치하는 문구가 없습니다. 검색어를 임의로 바꿔 재시도하지 말고 사용자에게 알리세요.", **result)
    return rt.ok(TOOL, "replace", f"{total}곳 처리 (슬라이드 {', '.join(map(str, slides_changed))})", **result)


# ==============================================================================
# 5. export
# ==============================================================================

def _ppt2007_without_pdf(app: Any, e: Exception) -> bool:
    """PowerPoint 2007(12.x)은 PDF 추가 기능이 없으면 E_FAIL만 돌려줍니다. 다른 버전의 E_FAIL은 그대로 둡니다."""
    try:
        version = str(app.Version)
    except Exception:
        return False
    return version.startswith("12.") and "-2147467259" in str(e)


def cmd_export(args) -> Dict[str, Any]:
    ext = os.path.splitext(args.save)[1].lower() if args.save else ".pdf"
    if ext not in (".pdf", ".pptx", ".pptm", ".ppt"):
        raise rt.InputError(f"--save 확장자는 .pdf 또는 .pptx여야 합니다: {args.save}")
    with off.open_target("ppt", args.target, readonly=True) as t:
        prs = t.doc
        if ext == ".pdf":
            out = rt.resolve_output_path(args.save, os.path.splitext(t.name)[0], ".pdf")
            try:
                # PrintRange(개체 인자)를 생략하면 pywin32가 인자 변환에서 TypeError를 냅니다. None을 명시합니다.
                prs.ExportAsFixedFormat(os.path.normpath(out), 2, PrintRange=None)   # ppFixedFormatTypePDF
            except Exception as e:
                if "기능이 설치되어 있지 않아" in str(e) or _ppt2007_without_pdf(t.app, e):
                    raise rt.InputError("PowerPoint PDF 내보내기 기능이 없습니다(Office 2007은 'PDF/XPS로 저장' 추가 기능 필요). "
                                        "--save에 .pptx를 쓰세요.")
                raise
        else:
            src_ext = os.path.splitext(t.path)[1].lower() if t.path else ".pptx"
            out = rt.resolve_output_path(args.save, os.path.splitext(t.name)[0] + "_사본", src_ext or ".pptx")
            prs.SaveCopyAs(os.path.normpath(out))                     # 원본 형식 그대로 사본
        resolved = t.resolved()
    return rt.ok(TOOL, "export", f"{resolved['name']}을(를) 저장: {out}", "VERIFIED: 저장 완료. 원본은 그대로입니다.",
                 target_resolved=resolved, output_file=out)


# ==============================================================================
# 6. slide
# ==============================================================================

def cmd_slide(args) -> Dict[str, Any]:
    a = args.action
    if a == "list":
        with off.open_target("ppt", args.target, readonly=True) as t:
            prs = t.doc
            items = [{"no": i, "title": slide_units(prs.Slides(i), i)["title"][:60]} for i in range(1, prs.Slides.Count + 1)]
            resolved = t.resolved()
        return rt.ok(TOOL, "slide", f"슬라이드 {len(items)}장", target_resolved=resolved, slides=items)
    with off.open_target("ppt", args.target, readonly=False, focus=not args.no_focus, tool=TOOL, command="slide") as t:
        prs = t.doc
        count = int(prs.Slides.Count)

        def need(n: Optional[int], what: str = "--slide") -> int:
            if n is None:
                raise rt.InputError(f"slide {a}에는 {what}가 필요합니다.")
            if not 1 <= n <= count:
                raise rt.InputError(f"슬라이드 {n}번이 없습니다 (전체 {count}장).")
            return n

        if a == "add":
            pos = count + 1 if args.slide is None else min(max(1, args.slide), count + 1)
            prs.Slides.Add(pos, PP_LAYOUT[args.layout])
            focus, msg = pos, f"{pos}번 위치에 새 슬라이드를 추가했습니다"
        elif a == "duplicate":
            n = need(args.slide)
            prs.Slides(n).Duplicate()
            focus, msg = n + 1, f"슬라이드 {n}을(를) 복제해 {n + 1}번에 넣었습니다"
        elif a == "move":
            n = need(args.slide)
            dest = need(args.to, "--to")
            prs.Slides(n).MoveTo(dest)
            focus, msg = dest, f"슬라이드 {n}을(를) {dest}번 위치로 옮겼습니다"
        elif a == "delete":
            n = need(args.slide)
            if count == 1:
                raise rt.InputError("마지막 남은 슬라이드는 삭제할 수 없습니다.")
            prs.Slides(n).Delete()
            focus, msg = min(n, count - 1), f"슬라이드 {n}을(를) 삭제했습니다 (되돌리기: office.py undo)"
        else:   # clear
            if args.slide is None and not args.all_slides:
                raise rt.InputError("clear에는 --slide가 필요합니다. 모든 슬라이드를 비우려면 --all-slides를 명시하세요 (사용자가 요청한 경우에만).")
            numbers = list(range(1, count + 1)) if args.slide is None else [need(args.slide)]
            removed = 0
            for n in numbers:
                shapes = prs.Slides(n).Shapes
                for k in range(shapes.Count, 0, -1):
                    shapes(k).Delete()
                    removed += 1
            focus, msg = numbers[0], f"슬라이드 {', '.join(map(str, numbers))}의 요소 {removed}개를 지웠습니다"
        t.set_focus(slide=focus)
        resolved = t.resolved()
        total = int(prs.Slides.Count)
    return rt.ok(TOOL, "slide", msg, target_resolved=resolved, slides_total=total)


# ==============================================================================
# 7. 진입점
# ==============================================================================

def build_cli():
    parser, sub = rt.build_parser(TOOL, "파워포인트 작업")

    def common(p, write=False):
        p.add_argument("--target", "-t", default="active", help="active(기본) | 열린 프레젠테이션 이름 | 파일 경로")
        if write:
            p.add_argument("--no-focus", action="store_true", help="작업 후 화면을 고친 슬라이드로 옮기지 않음")

    p = sub.add_parser("read", help="슬라이드 내용 읽기")
    common(p)
    p.add_argument("--slides", help="슬라이드 번호 (예: 3, 1-3, 1,4)")
    p.add_argument("--save", nargs="?", const=True, help="md 파일로 저장")

    p = sub.add_parser("info", help="프레젠테이션 요약")
    common(p)
    p.add_argument("--all", action="store_true", help="열린 프레젠테이션 전체 목록")

    p = sub.add_parser("write", help="내용 넣기")
    common(p, write=True)
    p.add_argument("--slide", help="슬라이드 번호 또는 new (기본: --file이면 new, 아니면 마지막 슬라이드)")
    p.add_argument("--title", help="슬라이드 제목")
    p.add_argument("--text", help="본문 (- 로 시작하는 줄은 글머리 기호, 줄바꿈은 \\n)")
    p.add_argument("--file", "-f", help="입력 파일 (.md: 제목마다 새 슬라이드, .csv: 표)")
    p.add_argument("--image", help="그림 파일 (남은 공간에 비율 유지로 맞춤)")
    p.add_argument("--width", type=float, help="그림 너비(pt)")
    p.add_argument("--cards", help="카드 '제목:내용|제목:내용' (1~5개)")
    p.add_argument("--theme", help=f"색 테마: {', '.join(off.THEMES)} (기본 navy)")

    p = sub.add_parser("replace", help="찾아 바꾸기")
    common(p, write=True)
    p.add_argument("--find", help="찾을 글")
    p.add_argument("--replace", help="바꿀 글 (빈 문자열이면 삭제, 생략하면 서식만)")
    p.add_argument("--map", help='여러 개 한 번에: JSON 객체 또는 JSON 파일')
    p.add_argument("--slide", type=int, help="이 슬라이드만 (생략 시 전체)")
    p.add_argument("--match-case", action="store_true", help="대소문자 구분")
    p.add_argument("--bold", action="store_true", default=None)
    p.add_argument("--italic", action="store_true", default=None)
    p.add_argument("--size", type=float)
    p.add_argument("--color")

    p = sub.add_parser("export", help="PDF/PPTX 사본 저장")
    common(p)
    p.add_argument("--save", help="저장 경로 (.pdf 또는 .pptx, 생략 시 작업 폴더에 PDF)")

    p = sub.add_parser("slide", help="슬라이드 관리")
    common(p, write=True)
    p.add_argument("--action", "-a", required=True, choices=["list", "add", "duplicate", "move", "delete", "clear"])
    p.add_argument("--slide", type=int, help="대상 슬라이드 번호 (add는 넣을 위치)")
    p.add_argument("--to", type=int, help="move 목적 위치")
    p.add_argument("--layout", choices=list(PP_LAYOUT), default="title_only", help="add 레이아웃 (기본 title_only)")
    p.add_argument("--all-slides", action="store_true", help="clear: 모든 슬라이드 (명시 필요)")
    return parser


HANDLERS = {"read": cmd_read, "info": cmd_info, "write": cmd_write, "replace": cmd_replace,
            "export": cmd_export, "slide": cmd_slide}


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_cli().parse_args(argv)
    rt.run_cli(TOOL, args.command, lambda: HANDLERS[args.command](args))


if __name__ == "__main__":
    main()
