"""classify 규칙 단위 테스트: 규칙 검증, 정규화, 점수와 우선순위, 신뢰도, 형식 표, 파일명 속 정보."""
import json
import unicodedata

import pytest

import _dc_rules as ru
import _dc_runtime as rt

RULES = {
    "계약서": ["계약", "협약", "MOU"],
    "회의록": ["회의록", "회의"],
    "보고서": ["보고", "현황"],
    "견적/발주": ["견적", "PO"],
    "도면": [".dwg", ".dxf"],
    "시험성적서": ["시험 성적서", "test report"],
}


def clf(rules=RULES, root="D:\\자료"):
    return ru.Classifier(ru.parse_rules(json.dumps(rules, ensure_ascii=False)), root)


def cat(name, folder="D:\\자료", ext=None, c=None):
    ext = ext if ext is not None else ("." + name.rsplit(".", 1)[1].lower() if "." in name else "")
    return (c or clf()).classify(name, ext, hash(folder), folder)


def test_extension_filename_and_folder_scores():
    assert cat("A-01.dwg")[:2] == ("도면", "high")                                    # 확장자 3점
    c, conf, matches, _ = cat("2026_공급계약서.hwp")
    assert (c, conf) == ("계약서", "high") and matches[0][1] == 2.0 and matches[0][2] == ["계약@n"]
    c, conf, matches, _ = cat("스캔001.pdf", "D:\\자료\\회의\\3월")                    # 더 위 폴더 0.5점
    assert (c, conf) == ("회의록", "low") and matches[0][1] == 0.5 and "d2" in matches[0][2][0]
    c, conf, _, _ = cat("스캔001.pdf", "D:\\자료\\회의")                                 # 바로 위 폴더 1점
    assert (c, conf) == ("회의록", "medium")
    assert cat("사진.jpg")[:2] == ("미분류", "")


def test_target_folder_itself_is_not_used_as_evidence():
    c = clf(root="D:\\계약")                    # 대상 폴더 이름이 '계약'이어도 모든 파일이 계약서가 되면 안 됨
    assert c.classify("메모.txt", ".txt", 1, "D:\\계약")[0] == "미분류"
    assert c.classify("메모.txt", ".txt", 2, "D:\\계약\\협약")[0] == "계약서"


def test_keywords_in_same_category_add_up_and_tie_goes_to_first_category():
    c, conf, matches, _ = cat("회의록_보고.hwp")                       # 회의록 4점(회의록+회의) vs 보고서 2점
    assert c == "회의록" and conf == "high" and matches[0][1] == 4.0 and matches[1][0] == "보고서"
    rules = {"보고서": ["보고"], "계약서": ["계약"]}
    c, conf, _, _ = cat("계약_보고.hwp", c=clf(rules))                # 동점이면 JSON에 먼저 적은 카테고리
    assert c == "보고서" and conf == "low"
    rules = {"계약서": ["계약"], "보고서": ["보고"]}
    assert cat("계약_보고.hwp", c=clf(rules))[0] == "계약서"


def test_keyword_counts_once_at_best_location():
    c, _, matches, hits = cat("계약서.hwp", "D:\\자료\\계약")
    assert c == "계약서" and matches[0][1] == 2.0 and hits == [(0, "계약")]


def test_normalization_spaces_underscores_case_and_nfd():
    assert cat("시험_성적서_A.pdf")[0] == "시험성적서"
    assert cat("시험-성적서.pdf")[0] == "시험성적서"
    assert cat("Final TEST-Report.docx")[0] == "시험성적서"
    nfd = unicodedata.normalize("NFD", "공급계약서.hwp")            # 맥에서 온 파일명 (자모 분리)
    assert nfd != "공급계약서.hwp" and cat(nfd)[0] == "계약서"


def test_short_english_keywords_match_as_words_only():
    assert cat("annual report.docx")[0] == "미분류"                 # report 속 'po'는 맞지 않음
    assert cat("PO_2026_부품.xlsx")[0] == "견적/발주"
    assert cat("부품PO목록.xlsx")[0] == "견적/발주"                  # 한글과 붙어도 단어로 인정
    assert cat("my po list.xlsx")[0] == "견적/발주"
    assert cat("MOU초안.docx")[0] == "계약서" and cat("HUMOUR.docx")[0] == "미분류"


def test_exclude_keywords_in_extended_form():
    rules = {"계약서": {"keywords": ["계약"], "exclude": ["계약직"]}, "인사": ["계약직"]}
    c = clf(rules)
    assert c.classify("계약직_채용.hwp", ".hwp", 1, "D:\\자료")[0] == "인사"
    assert c.classify("공급계약.hwp", ".hwp", 2, "D:\\자료")[0] == "계약서"


def test_confidence_from_margin():
    assert ru.confidence(3, 0) == "high" and ru.confidence(1, 0) == "medium" and ru.confidence(0.5, 0) == "low"
    assert ru.confidence(4, 2) == "high" and ru.confidence(3, 2) == "medium" and ru.confidence(2, 2) == "low"


@pytest.mark.parametrize("text,needle", [
    ("{", "JSON 문법 오류: 1번째 줄"),
    ('{"계약서": ["계약",]}', "JSON 문법 오류"),
    ("[]", "JSON 객체"),
    ("{}", "비어 있으면"),
    ('{"계약서": []}', "비었거나"),
    ('{"계약서": "계약"}', "목록"),
    ('{"계약서": ["계약", 3]}', "2번째 키워드가 문자열이 아닙니다"),
    ('{"계약서": [" "]}', "비어 있습니다"),
    ('{"계약서": ["계약"], "계약서": ["협약"]}', "두 번"),
    ('{"미분류": ["x"]}', "카테고리로 쓸 수 없습니다"),
    ('{"계약서": {"keywords": ["계약"], "skip": []}}', "알 수 없는 항목"),
    ('{"계약서": ["__"]}', "비교할 글자가 없습니다"),
])
def test_rule_file_errors_point_to_the_problem(text, needle):
    with pytest.raises(rt.InputError) as ei:
        ru.parse_rules(text)
    assert needle in str(ei.value)


def test_one_letter_keyword_warns(tmp_path):
    rules = ru.parse_rules('{"기타": ["A", ".zip"]}')
    assert rules.warnings and "너무 짧아" in rules.warnings[0]


def test_load_rules_reads_cp949_and_bom(tmp_path):
    p = tmp_path / "r.json"
    p.write_bytes('{"계약서": ["계약"]}'.encode("cp949"))
    assert ru.load_rules(str(p)).names == ["계약서"]
    p.write_bytes(b"\xef\xbb\xbf" + '{"보고서": ["보고"]}'.encode("utf-8"))
    assert ru.load_rules(str(p)).names == ["보고서"]
    with pytest.raises(rt.InputError) as ei:
        ru.load_rules(str(tmp_path / "없음.json"))
    assert "[추천]" in str(ei.value) and "rules.example.json" in str(ei.value)


def test_example_rules_file_is_valid():
    rules = ru.load_rules(rt.TOOL_DIR + "/rules.example.json")
    assert len(rules.names) >= 10 and not rules.warnings


def test_kind_table():
    assert ru.kind_of("a.HWP", ".hwp") == "한글" and ru.kind_of("b.xlsx", ".xlsx") == "표"
    assert ru.kind_of("~$보고서.docx", ".docx") == "임시/시스템" and ru.kind_of("Thumbs.db", ".db") == "임시/시스템"
    assert ru.kind_of("x.unknown", ".unknown") == "기타"
    assert len(set(ru.EXT_KIND)) == sum(len(v.split()) for v in ru.KIND_EXTS.values())    # 한 확장자는 한 형식


@pytest.mark.parametrize("name,date,version,flags", [
    ("회의록_20260301.hwp", "2026-03-01", "", ""),
    ("회의록 2026-03-01 최종.hwp", "2026-03-01", "최종", ""),
    ("보고서_2026.03.docx", "2026-03", "", ""),
    ("26년 3월 실적.xlsx", "2026-03", "", ""),
    ("회의록_260301.hwp", "2026-03-01", "", ""),
    ("계약서_v2.hwp", "", "v2", ""),
    ("계약서_rev3 (1).hwp", "", "rev3", "copy"),
    ("계약서 - 복사본.hwp", "", "", "copy"),
    ("보고서_최최종.hwp", "", "최최종", ""),
    ("~$보고서.docx", "", "", "temp"),
    ("dev2_notes.txt", "", "", ""),
    ("제품번호 123456789.pdf", "", "", ""),
    ("2026년 사업계획.hwp", "2026", "", ""),
])
def test_name_info(name, date, version, flags):
    ext = "." + name.rsplit(".", 1)[1]
    assert ru.name_info(name, ext) == (date, version, flags)


def test_name_tokens_for_unclassified_words():
    assert ru.name_tokens("2026_인사발령_v2 (1)") == ["인사발령"]
    assert ru.name_tokens("IMG_0001") == []
    assert ru.name_tokens("교육자료 Training") == ["교육자료", "training"]


def test_matches_text_is_readable():
    m = [["계약서", 4.0, ["계약@n", ".hwp@e"]], ["보고서", 1.0, ["보고@d1"]]]
    assert ru.matches_text(m) == "계약서 4점(계약@파일명, .hwp@확장자) / 보고서 1점(보고@바로 위 폴더)"
