"""word.py 읽기 범위(--pages/--paragraphs/--section), outline, comment, revisions 테스트 (가짜 Word)."""
import json

import pytest

import _office as off
import word
from fake_office import make_win32com
from fake_word import FakeComment, FakeRange, FakeWordDocument


class _Shapes:
    Count = 0


class _Rng:
    def __init__(self, doc, start, end):
        self.doc = doc
        self.Start = start
        self.End = end
        self.InlineShapes = _Shapes()

    @property
    def Text(self):
        return self.doc.full[self.Start:self.End]

    def Information(self, kind):
        assert kind == word.WD_PAGE_NUMBER
        return self.doc.page_at(self.Start)


class _Para:
    def __init__(self, rng, level):
        self.Range = rng
        self.OutlineLevel = level


class PageDoc:
    """단락(글, 개요 수준)과 쪽 시작 위치로 만든 가짜 문서. 개요 수준 10은 본문."""

    def __init__(self, paras, page_starts=None, name="규격.docx"):
        self.full = ""
        self.Paragraphs = []
        for text, level in paras:
            s = len(self.full)
            self.full += text + "\r"
            self.Paragraphs.append(_Para(_Rng(self, s, len(self.full)), level))
        self.page_starts = page_starts or [0]
        self.Name = name
        self.FullName = "C:\\docs\\" + name
        self.Content = _Rng(self, 0, len(self.full))

    def start_of(self, text):
        return self.full.index(text)

    def page_at(self, pos):
        return max(i + 1 for i, st in enumerate(self.page_starts) if st <= pos)

    def ComputeStatistics(self, kind):
        assert kind == 2
        return len(self.page_starts)

    def GoTo(self, What=None, Which=None, Count=1):
        assert (What, Which) == (1, 1)
        return _Rng(self, self.page_starts[min(Count, len(self.page_starts)) - 1], len(self.full))

    def Range(self, s, e):
        return _Rng(self, s, e)


SPEC = [("1. 개요", 1), ("개요 본문", 10), ("1.1 범위", 2), ("범위 본문", 10), ("1.1.1 세부", 3), ("세부 본문", 10),
        ("1.2 용어", 2), ("용어 본문", 10), ("2. 시험", 1), ("시험 본문", 10)]


@pytest.fixture
def wd(monkeypatch):
    holder = {"doc": PageDoc(SPEC)}
    fake, _ = make_win32com()
    monkeypatch.setattr(off, "win32com", fake)
    monkeypatch.setattr(off, "pythoncom", None)
    monkeypatch.setattr(off, "list_open", lambda kind: [])
    monkeypatch.setattr(off, "get_active", lambda kind: {"name": holder["doc"].Name, "path": holder["doc"].FullName,
                                                          "app": object(), "doc": holder["doc"]})
    monkeypatch.setattr(off, "save_snapshot", lambda *a, **k: None)
    return holder


def run(capsys, *argv):
    with pytest.raises(SystemExit) as ei:
        word.main(list(argv))
    out = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(out) == 1, out
    return ei.value.code, json.loads(out[0])


def texts(out):
    return [p["text"] for p in out["paragraphs"]]


# ------------------------------------------------------------------ read 범위

def test_read_pages_includes_paragraph_continued_from_previous_page(wd, capsys):
    doc = PageDoc([("머리말", 1), ("1쪽 본문", 10), ("다음 쪽까지 이어지는 긴 단락", 10), ("2쪽 본문", 10), ("3쪽 본문", 10)])
    doc.page_starts = [0, doc.start_of("다음 쪽까지") + 4, doc.start_of("3쪽 본문")]
    wd["doc"] = doc
    code, out = run(capsys, "read", "--pages", "2")
    assert code == 0, out
    assert texts(out) == ["다음 쪽까지 이어지는 긴 단락", "2쪽 본문"]
    assert [p["page"] for p in out["paragraphs"]] == [2, 2]
    assert [p["no"] for p in out["paragraphs"]] == [3, 4]          # 번호는 문서 전체 단락 번호 그대로
    assert out["page_total"] == 3 and out["count"] == 2


def test_read_pages_out_of_range_is_input_error(wd, capsys):
    code, out = run(capsys, "read", "--pages", "9")
    assert code == 1 and out["agent_directive"].startswith("STOP_RETRY:")
    assert "전체 1~1" in out["message"]


def test_read_paragraphs_open_ended_range(wd, capsys):
    code, out = run(capsys, "read", "--paragraphs", "8-")
    assert code == 0, out
    assert texts(out) == ["용어 본문", "2. 시험", "시험 본문"]
    assert [p["no"] for p in out["paragraphs"]] == [8, 9, 10]


def test_read_paragraphs_bad_format(wd, capsys):
    code, out = run(capsys, "read", "--paragraphs", "a-3")
    assert code == 1 and "--paragraphs 형식" in out["message"]


def test_read_section_by_number_includes_subsections_only(wd, capsys):
    code, out = run(capsys, "read", "--section", "1.1")         # '1.1.1 세부'와 헷갈리지 않음
    assert code == 0, out
    assert texts(out) == ["1.1 범위", "범위 본문", "1.1.1 세부", "세부 본문"]
    assert "단락 3-6" in out["selection"]


def test_read_section_matches_numbering_with_trailing_dot(wd, capsys):
    wd["doc"] = PageDoc([("1. SCOPE", 1), ("a", 10), ("1.1. Scope", 2), ("b", 10), ("1.1.1. Data", 3), ("c", 10)])
    code, out = run(capsys, "read", "--section", "1.1")
    assert code == 0, out
    assert texts(out) == ["1.1. Scope", "b", "1.1.1. Data", "c"]


def test_read_section_ambiguous_then_occurrence(wd, capsys):
    wd["doc"] = PageDoc([("1. 장비", 1), ("검증 방법", 2), ("장비 검증", 10), ("2. 소프트웨어", 1), ("검증 방법", 2), ("SW 검증", 10)])
    code, out = run(capsys, "read", "--section", "검증 방법")
    assert code == 1 and "[후보]" in out["message"] and "--occurrence" in out["message"]
    code, out = run(capsys, "read", "--section", "검증 방법", "--occurrence", "2")
    assert code == 0 and texts(out) == ["검증 방법", "SW 검증"]


def test_read_section_not_found_and_no_headings(wd, capsys):
    code, out = run(capsys, "read", "--section", "부록")
    assert code == 1 and "제목 '부록'" in out["message"]
    wd["doc"] = PageDoc([("본문만 있음", 10)])
    code, out = run(capsys, "read", "--section", "1")
    assert code == 1 and "제목" in out["message"] and "--pages" in out["message"]


def test_read_only_one_range_option(wd, capsys):
    code, out = run(capsys, "read", "--pages", "1", "--section", "1.1")
    assert code == 1 and "하나만" in out["message"]


def test_read_section_truncated_gives_paragraph_range(wd, capsys, monkeypatch):
    monkeypatch.setattr(word.rt, "DEFAULT_MAX_CHARS", 30)
    code, out = run(capsys, "read", "--section", "1")
    assert code == 0 and out["truncated"] is True
    nxt = out["next_commands"][0]["command"]
    shown = len(out["paragraphs"])
    assert f"--paragraphs {shown + 1}-8" in nxt                      # 1장 끝(단락 8)까지만 이어 읽기
    assert "--section 1 --save" in out["next_commands"][1]["command"]


# ------------------------------------------------------------------ outline

def test_outline_lists_levels_paragraph_numbers_and_pages(wd, capsys):
    doc = PageDoc(SPEC)
    doc.page_starts = [0, doc.start_of("2. 시험")]
    wd["doc"] = doc
    code, out = run(capsys, "outline")
    assert code == 0, out
    heads = out["headings"]
    assert [(h["paragraph"], h["level"], h["text"]) for h in heads][:3] == [(1, 1, "1. 개요"), (3, 2, "1.1 범위"), (5, 3, "1.1.1 세부")]
    assert heads[-1]["page"] == 2 and heads[0]["page"] == 1
    assert out["count"] == 5 and "--section" in out["agent_directive"]


def test_outline_without_headings_is_explicit_zero(wd, capsys):
    wd["doc"] = PageDoc([("본문", 10)])
    code, out = run(capsys, "outline")
    assert code == 0 and out["count"] == 0 and "0건" in out["agent_directive"]


# ------------------------------------------------------------------ comment

@pytest.fixture
def cd(wd):
    wd["doc"] = FakeWordDocument("시험 온도는 25도로 한다.\r습도 조건\r시험 시간과 시험 온도 기록")
    return wd


def test_comment_list_and_zero(cd, capsys):
    code, out = run(capsys, "comment")
    assert code == 0 and out["count"] == 0 and "0건" in out["agent_directive"]
    doc = cd["doc"]
    doc.Comments.items.append(FakeComment(FakeRange(doc, 0, 5), "규격 4.2항 확인\r값 다름", author="김검토"))
    code, out = run(capsys, "comment")
    assert code == 0 and out["count"] == 1
    item = out["items"][0]
    assert item["author"] == "김검토" and item["text"] == "규격 4.2항 확인\n값 다름" and item["target_text"] == "시험 온도"


def test_comment_add_on_exact_anchor_text_and_verified(cd, capsys):
    code, out = run(capsys, "comment", "--action", "add", "--anchor", "습도", "--text", "규격에 습도 기준 없음")
    assert code == 0, out
    assert out["verified"] is True and out["agent_directive"].startswith("VERIFIED:")
    c = cd["doc"].Comments(1)
    assert c.Scope.Text == "습도" and c.Range.Text == "규격에 습도 기준 없음"


def test_comment_add_ambiguous_anchor_adds_nothing(cd, capsys):
    code, out = run(capsys, "comment", "--action", "add", "--anchor", "시험 온도", "--text", "확인")
    assert code == 1 and "[후보]" in out["message"]
    assert cd["doc"].Comments.Count == 0
    code, out = run(capsys, "comment", "--action", "add", "--anchor", "시험 온도", "--text", "확인", "--occurrence", "2")
    assert code == 0 and cd["doc"].Comments(1).Scope.Start == cd["doc"].text.index("시험 온도 기록")


def test_comment_add_from_csv_all_or_nothing(cd, capsys, tmp_path):
    bad = tmp_path / "메모.csv"
    bad.write_text("기준 글,메모 내용\n습도,기준 없음\n없는 문구,확인\n", encoding="utf-8")
    code, out = run(capsys, "comment", "--action", "add", "--file", str(bad))
    assert code == 1 and "하나도 달지 않았습니다" in out["message"] and "2번째 줄" in out["message"]
    assert "[추천]" not in out["message"] and "[후보]" not in out["message"]   # 여러 줄 오류에 재시도 표시를 섞지 않음
    assert cd["doc"].Comments.Count == 0
    good = tmp_path / "메모2.csv"
    good.write_text("습도,기준 없음\n시험 온도,4.2항과 다름,2\n", encoding="utf-8")
    code, out = run(capsys, "comment", "--action", "add", "--file", str(good))
    assert code == 0 and out["count"] == 2 and out["verified"] is True
    assert sorted(c.Range.Text for c in cd["doc"].Comments.items) == ["4.2항과 다름", "기준 없음"]


def test_comment_add_unverified_when_reread_differs(cd, capsys, monkeypatch):
    real_add = cd["doc"].Comments.Add
    monkeypatch.setattr(cd["doc"].Comments, "Add", lambda Range=None, Text="": real_add(Range=Range, Text=Text[:2]))
    code, out = run(capsys, "comment", "--action", "add", "--anchor", "습도", "--text", "규격에 습도 기준 없음")
    assert code == 0 and out["verified"] is False and out["agent_directive"].startswith("UNVERIFIED:")


def test_comment_add_requires_anchor_and_text(cd, capsys):
    code, out = run(capsys, "comment", "--action", "add", "--text", "메모")
    assert code == 1 and "--anchor" in out["message"]
    code, out = run(capsys, "comment", "--action", "add", "--anchor", "습도")
    assert code == 1 and "메모 내용" in out["message"]


# ------------------------------------------------------------------ revisions

class _Rev:
    def __init__(self, kind, text):
        self.Type = kind
        self.Author = "홍길동"
        self.Date = "2026-10-27"
        self.Range = type("R", (), {"Text": text, "Information": lambda self, k: 4})()


class _Revs:
    def __init__(self, items):
        self.items = items
        self.Count = len(items)

    def __call__(self, i):
        return self.items[i - 1]


def test_revisions_list_types_and_zero(wd, capsys):
    doc = wd["doc"]
    doc.Revisions = _Revs([])
    doc.TrackRevisions = False
    code, out = run(capsys, "revisions")
    assert code == 0 and out["count"] == 0 and "0건" in out["agent_directive"]
    doc.Revisions = _Revs([_Rev(1, "추가된 문장"), _Rev(2, "지운 문장"), _Rev(99, "?")])
    doc.TrackRevisions = True
    code, out = run(capsys, "revisions")
    assert code == 0 and out["count"] == 3 and out["track_changes"] is True
    assert [i["type"] for i in out["items"]] == ["삽입", "삭제", "기타(99)"]
    assert out["items"][0]["page"] == 4 and out["items"][0]["text"] == "추가된 문장"


def test_read_pages_does_not_pull_previous_paragraph_across_blank_break(wd, capsys):
    # 쪽 나누기만 있는 빈 단락 다음 쪽: 빈 단락 앞의 단락은 앞 쪽에서 끝났으므로 넣지 않음
    doc = PageDoc([("1쪽 마지막 문장", 10), ("\x0c", 10), ("2쪽 첫 문장", 10)])
    doc.page_starts = [0, doc.start_of("2쪽 첫 문장")]
    wd["doc"] = doc
    code, out = run(capsys, "read", "--pages", "2")
    assert code == 0 and texts(out) == ["2쪽 첫 문장"]
