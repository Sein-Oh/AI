"""word.py - 워드 작업

명령:
    read     내용 읽기 (제목 구조 포함, --save로 md 저장)
    info     문서 요약 (페이지/단어/글자 수, 표, 그림, 제목 목록). --all: 열린 문서 전체 목록
    write    텍스트/마크다운/표/그림/요약상자/목차 넣기 (기본: 문서 끝, --anchor로 위치 지정)
    replace  찾아 바꾸기 (+서식). 머리글/바닥글/글상자 포함
    export   PDF / DOCX 사본 저장 (원본은 그대로, --page-number는 사본에만)

--target: active(기본, 지금 보고 있는 문서) | 열린 문서 이름 | 파일 경로
닫힌 .docx 읽기는 Word를 띄우지 않고 python-docx로 읽습니다.

예:
    python word.py write --file "검색결과.md"
    python word.py write --text "## 결론\n- 수율 98% 달성" --anchor "추진 배경" --pos after
    python word.py write --image "chart.png" --width 400
    python word.py replace --find "초안" --replace "최종본" --bold
    python word.py export --save report.pdf --page-number
"""
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _office as off  # noqa: E402
import _runtime as rt  # noqa: E402

TOOL = "word"

# WdBuiltinStyle (언어와 무관한 기본 스타일 번호)
WD_STYLE_NORMAL = -1
WD_STYLE_TITLE = -63
WD_STYLE_LIST_BULLET = -49
WD_STYLE_LIST_NUMBER = -50
WD_HIGHLIGHT = {"yellow": 7, "green": 4, "turquoise": 3, "pink": 5, "blue": 2, "red": 6, "gray": 16, "grey": 16,
                "노랑": 7, "초록": 4, "분홍": 5, "파랑": 2, "빨강": 6, "회색": 16, "none": 0}
FIND_MAX = 255   # Word Find 검색어 길이 한도


def heading_style(level: int) -> int:
    return -(min(max(level, 1), 9) + 1)       # wdStyleHeading1 = -2 ... Heading9 = -10


# ==============================================================================
# 1. read / info
# ==============================================================================

def _closed_docx(target: str) -> Optional[str]:
    if not target or target.strip().lower() == "active":
        return None
    raw = os.path.abspath(os.path.expandvars(target.strip().strip('"')))
    if not os.path.isfile(raw):
        cand = os.path.join(rt.get_data_dir(), target.strip().strip('"'))
        if not os.path.isfile(cand):
            return None
        raw = cand
    if os.path.splitext(raw)[1].lower() not in (".docx", ".docm"):
        return None
    import zipfile
    if not zipfile.is_zipfile(raw):
        return None
    try:
        if off.win32com is not None and off.match_open("word", raw) is not None:
            return None
    except Exception:
        pass
    return raw


def _com_units(doc: Any) -> List[Dict[str, str]]:
    """열린 문서의 단락을 제목 구조와 함께 읽습니다 (단락 단위 COM 호출 2회, 페이지 계산 없음)."""
    units: List[Dict[str, str]] = []
    heading = ""
    n = 0
    for para in doc.Paragraphs:
        text = str(para.Range.Text).rstrip("\r\x07").replace("\x07", " ").replace("\x0b", "\n").strip()
        if not text:
            continue
        n += 1
        try:
            level = int(para.OutlineLevel)
        except Exception:
            level = 10
        if 1 <= level <= 9:
            heading = text
        units.append({"loc": f"단락 {n}", "heading": heading, "text": text, "level": level if level <= 9 else 0})
    return units


def cmd_read(args) -> Dict[str, Any]:
    closed = _closed_docx(args.target)
    if closed:
        import reader
        units, _ = reader.parse_docx(closed)
        source = {"app": "Word", "name": os.path.basename(closed), "path": closed, "source": "file(python-docx)"}
    else:
        with off.open_target("word", args.target, readonly=True) as t:
            units = _com_units(t.doc)
            source = t.resolved()
    name = source["name"]
    result: Dict[str, Any] = {"target_resolved": source, "units_total": len(units)}
    if args.save:
        import reader
        out = rt.resolve_output_path(None if args.save is True else args.save, os.path.splitext(name)[0], ".md")
        out = rt.write_text(out, reader.units_to_markdown(name, units))
        result.update(output_file=out, next_commands=[
            rt.next_command("ppt.py", ["write", "--file", out], "저장한 내용을 열린 PPT에 넣기"),
            rt.next_command("office.py", ["transfer", "--from", "word", "--what", "text", "--to", "excel"],
                            "이 문서의 단락을 엑셀 표로 옮기기")])
        return rt.ok(TOOL, "read", f"{name}: 단락 {len(units)}개를 저장했습니다 ({out})", **result)
    shown: List[Dict[str, Any]] = []
    used = 0
    start = max(1, args.start)
    for i, u in enumerate(units[start - 1:], start):
        size = len(u["text"]) + 12
        if shown and used + size > rt.DEFAULT_MAX_CHARS:
            break
        shown.append({"no": i, "heading": u["heading"], "text": rt.clamp_text(u["text"], rt.DEFAULT_MAX_CHARS)[0]})
        used += size
    truncated = start - 1 + len(shown) < len(units)
    result.update(paragraphs=shown, truncated=truncated)
    if truncated:
        nxt = start + len(shown)
        result["next_commands"] = [
            rt.next_command("word.py", ["read", "--target", args.target, "--start", str(nxt)], f"{nxt}번째 단락부터 이어서 읽기"),
            rt.next_command("word.py", ["read", "--target", args.target, "--save"], "전체를 md 파일로 저장")]
    preview = f"{name}: 단락 {len(shown)}개 표시 (전체 {len(units)}개)"
    return rt.ok(TOOL, "read", preview, "VERIFIED: 읽기 완료. 일부만 표시되었으면 next_commands로 이어서 읽으세요."
                 if truncated else "", **result)


def cmd_info(args) -> Dict[str, Any]:
    if args.all:
        docs = [{"name": d["name"], "path": d["path"], "saved": d["saved"], "active": d["active"]}
                for d in off.list_open("word")]
        return rt.ok(TOOL, "info", f"열린 문서 {len(docs)}개", documents=docs)
    with off.open_target("word", args.target, readonly=True) as t:
        doc = t.doc
        stats = {}
        for key, code in (("pages", 2), ("words", 0), ("characters", 3), ("paragraphs", 4)):
            try:
                stats[key] = int(doc.ComputeStatistics(code))
            except Exception:
                pass
        tables = []
        for i in range(1, doc.Tables.Count + 1):
            try:
                tb = doc.Tables(i)
                tables.append({"no": i, "rows": int(tb.Rows.Count), "cols": int(tb.Columns.Count)})
            except Exception:
                tables.append({"no": i})
        headings = [u["text"] for u in _com_units(doc) if u.get("level")][:30]
        result = {"target_resolved": t.resolved(), "stats": stats, "tables": tables,
                  "pictures": int(doc.InlineShapes.Count), "floating_shapes": int(doc.Shapes.Count),
                  "headings": headings, "saved": off.is_saved(doc)}
    preview = (f"{result['target_resolved']['name']}: {stats.get('pages', '?')}쪽, 글자 {stats.get('characters', '?')}, "
               f"표 {len(tables)}개, 그림 {result['pictures']}개, 제목 {len(headings)}개")
    return rt.ok(TOOL, "info", preview, **result)


# ==============================================================================
# 2. write
# ==============================================================================

class Writer:
    """문서의 한 위치(pos)부터 블록을 차례로 넣는 도우미. 넣은 뒤 pos는 다음 삽입 위치로 이동합니다."""

    def __init__(self, doc: Any, pos: int, theme: Optional[Dict[str, Any]]):
        self.doc = doc
        self.pos = pos
        self.theme = theme or off.THEMES["navy"] | {"name": "navy"}
        self.created: List[str] = []

    def _para(self, text: str, style: Optional[int] = None, bold_spans: Sequence[Tuple[int, int]] = ()) -> Any:
        r = self.doc.Range(self.pos, self.pos)
        r.InsertAfter(text + "\r")
        para = self.doc.Range(r.Start, r.Start + len(text))
        try:
            para.Style = self.doc.Styles(style if style is not None else WD_STYLE_NORMAL)
        except Exception:
            pass
        para.Font.Bold = False
        for a, b in bold_spans:
            self.doc.Range(r.Start + a, r.Start + b).Font.Bold = True
        self.pos = r.End
        return para

    def text(self, text: str, style: Optional[int] = None) -> None:
        plain, spans = rt.split_bold(text)
        self._para(plain, style, spans)

    def heading(self, level: int, text: str) -> None:
        self.text(text, heading_style(level))
        self.created.append(f"제목{level}")

    def items(self, items: List[str], numbered: bool) -> None:
        for it in items:
            self.text(it, WD_STYLE_LIST_NUMBER if numbered else WD_STYLE_LIST_BULLET)
        self.created.append(f"{'번호' if numbered else '글머리'} 목록 {len(items)}개")

    def table(self, rows: List[List[Any]]) -> Any:
        width = max(len(r) for r in rows)
        lines = ["\t".join(str("" if v is None else v).replace("\t", " ").replace("\r", " ").replace("\n", " ")
                           for v in (list(r) + [""] * (width - len(r)))) for r in rows]
        r = self.doc.Range(self.pos, self.pos)
        r.InsertAfter("\r".join(lines) + "\r")
        body = self.doc.Range(r.Start, r.End - 1)
        body.Style = self.doc.Styles(WD_STYLE_NORMAL)
        tbl = body.ConvertToTable(Separator=1, NumRows=len(rows), NumColumns=width)   # 탭 구분 -> 표 (셀 단위 COM 호출 없음)
        tbl.Borders.Enable = True
        try:
            tbl.AutoFitBehavior(2)            # 창 너비에 맞춤
        except Exception:
            pass
        head = tbl.Rows(1)
        head.Range.Font.Bold = True
        head.Shading.BackgroundPatternColor = off.parse_color(self.theme["header_bg"])
        head.Range.Font.Color = off.parse_color(self.theme["header_fg"])
        try:
            head.HeadingFormat = True          # 페이지가 넘어가면 머리글 행 반복
        except Exception:
            pass
        self.pos = tbl.Range.End
        if self.pos >= self.doc.Content.End - 1:     # 문서 끝 표 뒤에는 빈 단락이 하나 있음
            self.pos = self.doc.Content.End - 1
        self.created.append(f"표 {len(rows)}x{width}")
        return tbl

    def callout(self, text: str) -> None:
        r = self.doc.Range(self.pos, self.pos)
        r.InsertAfter(text.replace("\n", "\v") + "\r")
        body = self.doc.Range(r.Start, r.End - 1)
        tbl = body.ConvertToTable(Separator=1, NumRows=1, NumColumns=1)
        cell = tbl.Cell(1, 1)
        cell.Shading.BackgroundPatternColor = off.parse_color(self.theme["light"])
        tbl.Borders.Enable = False
        left = tbl.Borders(-2)                     # wdBorderLeft
        left.LineStyle = 1
        left.LineWidth = 24                        # 3pt
        left.Color = off.parse_color(self.theme["primary"])
        self.pos = tbl.Range.End
        if self.pos >= self.doc.Content.End - 1:
            self.pos = self.doc.Content.End - 1
        self.created.append("요약 상자")

    def image(self, path: str, width: Optional[float]) -> None:
        r = self.doc.Range(self.pos, self.pos)
        r.InsertAfter("\r")
        anchor = self.doc.Range(r.Start, r.Start)
        pic = self.doc.InlineShapes.AddPicture(FileName=path, LinkToFile=False, SaveWithDocument=True, Range=anchor)
        setup = self.doc.PageSetup
        usable = float(setup.PageWidth - setup.LeftMargin - setup.RightMargin)
        target_w = min(width or usable, usable)
        w0, h0 = float(pic.Width), float(pic.Height)
        if w0 > 0 and (w0 > target_w or width):
            ratio = target_w / w0                     # 가로세로 비율 유지
            pic.Width = target_w
            pic.Height = h0 * ratio
        try:
            pic.Range.ParagraphFormat.Alignment = 1   # 가운데
        except Exception:
            pass
        self.pos = pic.Range.End + 1
        self.created.append(f"그림 {os.path.basename(path)}")

    def toc(self) -> None:
        r = self.doc.Range(self.pos, self.pos)
        r.InsertAfter("\r")
        anchor = self.doc.Range(r.Start, r.Start)
        toc = self.doc.TablesOfContents.Add(Range=anchor, UseHeadingStyles=True, UpperHeadingLevel=1, LowerHeadingLevel=3)
        toc.Update()
        self.pos = toc.Range.End + 1
        self.created.append("목차")

    def page_break(self) -> None:
        r = self.doc.Range(self.pos, self.pos)
        r.InsertBreak(7)                              # wdPageBreak
        self.pos = r.End
        self.created.append("페이지 나누기")

    def markdown(self, text: str) -> None:
        for kind, payload in rt.parse_markdown_blocks(text):
            if kind == "heading":
                self.heading(*payload)
            elif kind == "paragraph":
                self.text(payload)
                if not self.created or not self.created[-1].startswith("본문"):
                    self.created.append("본문")
            elif kind in ("bullets", "numbered"):
                self.items(payload, kind == "numbered")
            elif kind == "table":
                self.table(payload)
            elif kind == "break":
                self.page_break()


def _find(rng: Any, text: str, match_case: bool = False, whole_word: bool = False) -> bool:
    """Find 옵션을 모두 명시합니다 (사용자가 마지막에 쓴 와일드카드 등 설정이 남아 오동작하는 것 방지)."""
    f = rng.Find
    f.ClearFormatting()
    return bool(f.Execute(FindText=text, MatchCase=match_case, MatchWholeWord=whole_word, MatchWildcards=False,
                          MatchSoundsLike=False, MatchAllWordForms=False, Forward=True, Wrap=0, Format=False))


def _insert_position(doc: Any, anchor: Optional[str], pos: str) -> Tuple[int, str]:
    """삽입 위치(문자 오프셋)와 설명. 앵커가 있으면 그 단락의 앞/뒤, replace면 앵커 단락을 지우고 그 자리."""
    if not anchor:
        end = doc.Content.End - 1
        last = doc.Range(end, end).Paragraphs(1).Range
        if pos == "start":
            return 0, "문서 처음"
        if str(last.Text).strip():                    # 마지막 단락에 내용이 있으면 새 단락에서 시작
            doc.Range(end, end).InsertAfter("\r")
            end = doc.Content.End - 1
        return end, "문서 끝"
    if len(anchor) > FIND_MAX:
        raise rt.InputError(f"--anchor는 {FIND_MAX}자 이하여야 합니다. 앵커 단락의 앞부분 일부만 쓰세요.")
    rng = doc.Content
    if not _find(rng, anchor):
        raise rt.InputError(f"문서에서 '{anchor}'을(를) 찾을 수 없습니다. word.py read로 정확한 문구를 확인하세요.")
    para = rng.Paragraphs(1).Range
    if pos == "before":
        return int(para.Start), f"'{anchor}' 단락 앞"
    if pos == "replace":
        start = int(para.Start)
        if int(para.End) < int(doc.Content.End):
            para.Delete()                                  # 단락 전체(단락 기호 포함)를 지우고 그 자리에 넣음
        else:
            doc.Range(para.Start, para.End - 1).Delete()  # 마지막 단락은 단락 기호를 남김
        return start, f"'{anchor}' 단락 자리"
    return int(para.End), f"'{anchor}' 단락 뒤"


def cmd_write(args) -> Dict[str, Any]:
    if not any([args.text, args.file, args.image, args.toc, args.page_break]):
        raise rt.InputError("넣을 내용이 없습니다. --text, --file, --image, --toc, --page-break 중 하나 이상을 지정하세요.")
    theme = off.get_theme(args.theme)
    text = args.text.replace("\\n", "\n") if args.text else None
    file_rows = None
    file_text = None
    if args.file:
        path = rt.resolve_input_path(args.file, "입력 파일")
        if os.path.splitext(path)[1].lower() in (".csv", ".tsv"):
            file_rows = rt.read_csv_rows(path)
        else:
            file_text = rt.read_text_file(path)
    image = rt.resolve_input_path(args.image, "그림 파일") if args.image else None

    with off.open_target("word", args.target, readonly=False, focus=not args.no_focus, create=True,
                         tool=TOOL, command="write") as t:
        doc = t.doc
        start, where = _insert_position(doc, args.anchor, args.pos)
        w = Writer(doc, start, theme)
        if args.page_break:
            w.page_break()
        if args.toc:
            w.toc()
        for content in (text, file_text):
            if content is None:
                continue
            if args.callout:
                w.callout(content.strip())
            elif args.heading:
                w.heading(args.heading, content.strip())
            elif args.title:
                w.text(content.strip(), WD_STYLE_TITLE)
                w.created.append("문서 제목")
            elif rt.looks_like_markdown(content):
                w.markdown(content)
            else:
                for para in [p for p in re.split(r"\n\s*\n|\n", content) if p.strip()]:
                    w.text(para.strip())
                w.created.append("본문")
        if file_rows:
            w.table(file_rows)
        if image:
            w.image(image, args.width)
        t.set_focus()
        if t.source == "active" and not args.no_focus:
            try:
                doc.Range(w.pos, w.pos).Select()          # 커서를 넣은 내용 끝으로
            except Exception:
                pass
        resolved = t.resolved()
    return rt.ok(TOOL, "write", f"{resolved['name']}의 {where}에 넣었습니다: {', '.join(w.created)}",
                 "VERIFIED: 쓰기 완료. 다시 읽어서 확인하지 마세요.", target_resolved=resolved, inserted=w.created)


# ==============================================================================
# 3. replace
# ==============================================================================

def _stories(doc: Any) -> List[Any]:
    """본문, 머리글/바닥글, 글상자, 각주 등 모든 텍스트 영역."""
    result = []
    try:
        for story in doc.StoryRanges:
            s = story
            while s is not None:
                result.append(s)
                try:
                    s = s.NextStoryRange
                except Exception:
                    s = None
    except Exception:
        result = [doc.Content]
    return result or [doc.Content]


def _load_map(args) -> Dict[str, str]:
    if args.map:
        raw = args.map.strip()
        if not raw.startswith("{"):
            raw = rt.read_text_file(rt.resolve_input_path(raw, "치환 목록 파일"))
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise rt.InputError(f"--map은 JSON 객체여야 합니다 (예: {{\"초안\": \"최종\"}}): {e}")
        if not isinstance(data, dict) or not data:
            raise rt.InputError("--map은 비어 있지 않은 JSON 객체여야 합니다.")
        mapping = {str(k): ("" if v is None else str(v)) for k, v in data.items()}
    elif args.find is not None:
        mapping = {args.find: args.find if args.replace is None else args.replace}   # --replace "" 는 삭제
    else:
        raise rt.InputError("--find 또는 --map을 지정하세요.")
    long_keys = [k for k in mapping if len(k) > FIND_MAX]
    if long_keys:
        raise rt.InputError(f"찾을 문구는 {FIND_MAX}자 이하여야 합니다: '{long_keys[0][:30]}...' 문장을 나눠서 지정하세요.")
    return mapping


def cmd_replace(args) -> Dict[str, Any]:
    mapping = _load_map(args)
    color = off.parse_color(args.color) if args.color else None
    highlight = None
    if args.highlight:
        highlight = WD_HIGHLIGHT.get(args.highlight.strip().lower())
        if highlight is None:
            raise rt.not_found("형광펜 색", args.highlight, [k for k in WD_HIGHLIGHT if k.isascii()])
    formatting = any(x is not None for x in (color, highlight, args.bold, args.italic, args.size))
    counts: Dict[str, int] = {}
    limit_hit = False
    with off.open_target("word", args.target, readonly=False, focus=not args.no_focus,
                         tool=TOOL, command="replace") as t:
        for story in _stories(t.doc):
            for find, rep in mapping.items():
                n = 0
                rng = story.Duplicate
                while _find(rng, find, args.match_case, args.whole_word):
                    if find != rep:
                        rng.Text = rep
                    if formatting:
                        if color is not None:
                            rng.Font.Color = color
                        if args.bold is not None:
                            rng.Font.Bold = args.bold
                        if args.italic is not None:
                            rng.Font.Italic = args.italic
                        if args.size:
                            rng.Font.Size = args.size
                        if highlight is not None:
                            rng.HighlightColorIndex = highlight
                    n += 1
                    if n >= 5000:
                        limit_hit = True
                        break
                    rng.Collapse(0)            # wdCollapseEnd: 바꾼 글 뒤부터 이어서 찾기 (바꾼 글을 다시 찾지 않음)
                if n:
                    counts[find] = counts.get(find, 0) + n
        if counts:
            t.set_focus()
        resolved = t.resolved()
    total = sum(counts.values())
    result = {"target_resolved": resolved, "replaced": total, "by_text": counts}
    if not total:
        return rt.ok(TOOL, "replace", "일치하는 문구가 없습니다",
                     "VERIFIED: 일치하는 문구가 없습니다. 검색어를 임의로 바꿔 재시도하지 말고 사용자에게 알리세요.", **result)
    if limit_hit:
        result["limit_reached"] = True
        return rt.ok(TOOL, "replace", f"{total}곳 처리 (문구당 5000곳 상한 도달, 일부 남았을 수 있음)",
                     "VERIFIED: 상한까지 처리했습니다. 남은 곳이 있을 수 있으니 사용자에게 알리세요.", **result)
    return rt.ok(TOOL, "replace", f"{total}곳 처리: " + ", ".join(f"'{k}' {v}곳" for k, v in counts.items()), **result)


# ==============================================================================
# 4. export
# ==============================================================================

def _working_copy(app: Any, doc: Any) -> Tuple[Any, str]:
    """현재 메모리 상태(미저장 포함)를 창 없는 사본 문서로 엽니다. 원본은 그대로."""
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="atomic_word_", suffix=".xml")
    os.close(fd)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(doc.WordOpenXML)
    return app.Documents.Open(tmp, ConfirmConversions=False, AddToRecentFiles=False, Visible=False), tmp


def cmd_export(args) -> Dict[str, Any]:
    ext = os.path.splitext(args.save)[1].lower() if args.save else ".pdf"
    if ext not in (".pdf", ".docx"):
        raise rt.InputError(f"--save 확장자는 .pdf 또는 .docx여야 합니다: {args.save}")
    work = tmp = None
    with off.open_target("word", args.target, readonly=True) as t:
        out = rt.resolve_output_path(args.save, os.path.splitext(t.name)[0], ext)
        try:
            target_doc = t.doc
            if args.page_number or ext == ".docx":
                work, tmp = _working_copy(t.app, t.doc)
                target_doc = work
            if args.page_number:
                for section in target_doc.Sections:
                    section.Footers(1).PageNumbers.Add(PageNumberAlignment=1)
            if ext == ".pdf":
                try:
                    target_doc.ExportAsFixedFormat(OutputFileName=os.path.normpath(out), ExportFormat=17,
                                                   OpenAfterExport=False, OptimizeFor=0, Range=0)
                except Exception as e:
                    if "25726" in str(e) or "기능이 설치되어 있지 않아" in str(e):
                        raise rt.InputError("Word PDF 내보내기 기능이 없습니다. --save에 .docx를 쓰세요.")
                    raise
            else:
                target_doc.SaveAs2(os.path.normpath(out), FileFormat=16)
        finally:
            if work is not None:
                try:
                    work.Close(SaveChanges=0)
                except Exception:
                    pass
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        resolved = t.resolved()
    return rt.ok(TOOL, "export", f"{resolved['name']}을(를) {ext[1:].upper()}로 저장: {out}",
                 "VERIFIED: 저장 완료. 원본 문서는 바뀌지 않았습니다.", target_resolved=resolved, output_file=out,
                 page_number=bool(args.page_number))


# ==============================================================================
# 5. 진입점
# ==============================================================================

def build_cli():
    parser, sub = rt.build_parser(TOOL, "워드 작업")

    def common(p, write=False):
        p.add_argument("--target", "-t", default="active", help="active(기본) | 열린 문서 이름 | 파일 경로")
        if write:
            p.add_argument("--no-focus", action="store_true", help="작업 후 화면 이동 안 함")

    p = sub.add_parser("read", help="내용 읽기")
    common(p)
    p.add_argument("--start", type=int, default=1, help="이 번호의 단락부터 읽기")
    p.add_argument("--save", nargs="?", const=True, help="md 파일로 저장 (경로 생략 시 작업 폴더)")

    p = sub.add_parser("info", help="문서 요약")
    common(p)
    p.add_argument("--all", action="store_true", help="열린 문서 전체 목록")

    p = sub.add_parser("write", help="내용 넣기")
    common(p, write=True)
    p.add_argument("--text", help="넣을 글. 마크다운(# 제목, - 목록, | 표 |, **굵게**)은 Word 서식으로 변환. 줄바꿈은 \\n")
    p.add_argument("--file", "-f", help="넣을 파일 (.md/.txt는 글, .csv는 표)")
    p.add_argument("--image", help="넣을 그림 파일")
    p.add_argument("--width", type=float, help="그림 너비(pt). 생략 시 본문 폭에 맞춤")
    p.add_argument("--heading", type=int, choices=range(1, 7), help="--text를 이 수준의 제목으로")
    p.add_argument("--title", action="store_true", help="--text를 문서 제목 스타일로")
    p.add_argument("--callout", action="store_true", help="--text를 강조 요약 상자로")
    p.add_argument("--toc", action="store_true", help="목차 넣기")
    p.add_argument("--page-break", action="store_true", help="넣기 전에 페이지 나누기")
    p.add_argument("--anchor", help="이 글이 있는 단락을 기준으로 넣기")
    p.add_argument("--pos", choices=["after", "before", "replace", "end", "start"], default="after",
                   help="앵커 기준 위치 (앵커 없으면 end/start만 의미, 기본: 문서 끝)")
    p.add_argument("--theme", help=f"표/요약 상자 색: {', '.join(off.THEMES)}")

    p = sub.add_parser("replace", help="찾아 바꾸기")
    common(p, write=True)
    p.add_argument("--find", help="찾을 글")
    p.add_argument("--replace", help="바꿀 글 (빈 문자열이면 삭제, 생략하면 서식만 적용)")
    p.add_argument("--map", help='여러 개 한 번에: JSON 객체 또는 JSON 파일 (예: {"초안":"최종"})')
    p.add_argument("--match-case", action="store_true", help="대소문자 구분")
    p.add_argument("--whole-word", action="store_true", help="단어 전체 일치")
    p.add_argument("--bold", action="store_true", default=None, help="굵게")
    p.add_argument("--italic", action="store_true", default=None, help="기울임")
    p.add_argument("--color", help="글자색")
    p.add_argument("--size", type=float, help="글자 크기")
    p.add_argument("--highlight", help="형광펜 (yellow, green, pink, blue, red, gray, none)")

    p = sub.add_parser("export", help="PDF/DOCX 사본 저장")
    common(p)
    p.add_argument("--save", help="저장 경로 (.pdf 또는 .docx, 생략 시 작업 폴더에 PDF)")
    p.add_argument("--page-number", action="store_true", help="사본 아래쪽 가운데에 쪽 번호")
    return parser


HANDLERS = {"read": cmd_read, "info": cmd_info, "write": cmd_write, "replace": cmd_replace, "export": cmd_export}


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_cli().parse_args(argv)
    if args.command == "write" and not args.anchor and args.pos not in ("end", "start"):
        args.pos = "end"
    rt.run_cli(TOOL, args.command, lambda: HANDLERS[args.command](args))


if __name__ == "__main__":
    main()
