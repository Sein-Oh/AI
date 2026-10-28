"""classify 규칙: 규칙 JSON 읽기·검증, 키워드 정규화, 점수 계산, 형식(kind) 표, 파일명 속 정보.

규칙 파일 (사용자 결정: JSON, 적은 순서 = 동점일 때 우선순위)
    {"계약서": ["계약", "협약"], "도면": [".dwg", ".dxf"]}
    {"계약서": {"keywords": ["계약"], "exclude": ["계약직"]}}     <- 확장 형식 (exclude: 맞으면 그 카테고리 제외)

점수: 확장자 3점, 파일명 2점, 바로 위 폴더 1점, 더 위 폴더 0.5점 (대상 폴더 자신과 그 위는 보지 않음).
키워드 하나는 가장 높은 위치 한 번만 세고, 같은 카테고리 안의 여러 키워드는 합산합니다.
디스크를 읽지 않으며 표준 라이브러리만 씁니다.
"""
import json
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple

import _dc_runtime as rt

UNCLASSIFIED = "미분류"
SCORE_EXT, SCORE_NAME, SCORE_PARENT, SCORE_UPPER = 3.0, 2.0, 1.0, 0.5
WHERE_LABEL = {"e": "확장자", "n": "파일명", "d1": "바로 위 폴더", "d2": "더 위 폴더"}

_IGNORED = re.compile(r"[\s_\-]+")


def norm(text: str) -> str:
    """비교용 정규화: 한글 NFC(맥 자모 분리 대비), 대소문자 무시, 공백·_·- 무시."""
    return _IGNORED.sub("", unicodedata.normalize("NFC", str(text)).casefold())


def lower(text: str) -> str:
    """단어 경계를 보는 비교용: NFC + 대소문자 무시 (공백·구분자는 그대로)."""
    return unicodedata.normalize("NFC", str(text)).casefold()


SHORT_WORD = 4      # 이 길이 이하의 영문·숫자 키워드는 단어로만 비교 ('PO'가 'report'에 맞지 않게)


def word_matcher(keyword: str) -> Optional["re.Pattern[str]"]:
    """짧은 영문 키워드면 앞뒤가 영문자가 아닐 때만 맞는 정규식 (숫자, 한글, 구분자는 경계로 인정)."""
    k = lower(keyword.strip())
    if re.fullmatch(r"[a-z0-9]+(?:[ _\-][a-z0-9]+)*", k) and len(norm(k)) <= SHORT_WORD:
        body = r"[\s_\-]*".join(re.escape(ch) for ch in norm(k))
        return re.compile(rf"(?<![a-z]){body}(?![a-z])")
    return None


def keyword_in(w: str, rx: Optional["re.Pattern[str]"], normed: str, low: str) -> bool:
    return bool(rx.search(low)) if rx is not None else w in normed


# ==============================================================================
# 1. 규칙 파일
# ==============================================================================

class Category:
    __slots__ = ("name", "order", "exts", "words", "excludes", "raw")

    def __init__(self, name: str, order: int, raw: List[str], excludes: List[str]):
        self.name, self.order, self.raw = name, order, raw
        self.exts = {k.strip().lower() for k in raw if k.strip().startswith(".")}
        self.words = [(norm(k), k.strip(), word_matcher(k)) for k in raw if not k.strip().startswith(".")]
        self.excludes = [norm(k) for k in excludes]


class Rules:
    def __init__(self, categories: List[Category], path: str, text: str):
        self.categories = categories
        self.path = path
        self.text = text
        self.warnings: List[str] = []
        self.by_name = {c.name: c for c in categories}
        self.ext_map: Dict[str, List[int]] = {}
        self.words: List[Tuple[str, str, int, Any]] = []   # (정규화 키워드, 원래 키워드, 카테고리 번호, 단어 정규식)
        for i, c in enumerate(categories):
            for e in c.exts:
                self.ext_map.setdefault(e, []).append(i)
            for w, original, rx in c.words:
                self.words.append((w, original, i, rx))
        # 파일마다 도는 반복을 가볍게: 글자 포함 키워드와 단어 정규식 키워드를 나눠 둡니다
        self.sub_words = [(w, o, i) for w, o, i, rx in self.words if rx is None]
        self.rx_words = [(rx, o, i) for w, o, i, rx in self.words if rx is not None]

    def text_hits(self, text: str) -> Dict[int, List[str]]:
        """본문(peek)에서 카테고리별로 맞은 글자 키워드 (확장자 키워드 제외)."""
        normed, low = norm(text), lower(text)
        out: Dict[int, List[str]] = {}
        for w, original, ci, rx in self.words:
            if keyword_in(w, rx, normed, low):
                out.setdefault(ci, []).append(original)
        return out

    @property
    def names(self) -> List[str]:
        return [c.name for c in self.categories]

    def as_meta(self) -> Dict[str, Any]:
        return {"path": self.path, "categories": {c.name: c.raw for c in self.categories},
                "excludes": {c.name: [k for k in c.excludes] for c in self.categories if c.excludes}}


def _pairs_no_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise rt.InputError(f"규칙 파일에 카테고리 '{k}'가 두 번 있습니다. 하나로 합치세요.")
        out[k] = v
    return out


def _json_error_hint(text: str, e: json.JSONDecodeError) -> str:
    line = text.splitlines()[e.lineno - 1] if 0 < e.lineno <= len(text.splitlines()) else ""
    hint = ""
    if "Expecting ',' delimiter" in e.msg or "Expecting property name" in e.msg:
        hint = " (쉼표가 빠졌거나 마지막 항목 뒤에 쉼표가 남았는지 확인)"
    elif "Invalid control character" in e.msg or "Unterminated string" in e.msg:
        hint = " (따옴표가 닫혔는지 확인)"
    return f"규칙 파일 JSON 문법 오류: {e.lineno}번째 줄 {e.colno}번째 글자, {e.msg}{hint}. 그 줄: {line.strip()[:80]}"


def parse_rules(text: str, path: str = "") -> Rules:
    try:
        data = json.loads(text, object_pairs_hook=_pairs_no_duplicates)
    except json.JSONDecodeError as e:
        raise rt.InputError(_json_error_hint(text, e))
    if not isinstance(data, dict) or not data:
        raise rt.InputError('규칙 파일은 {"카테고리": ["키워드", ".확장자"]} 형태의 JSON 객체여야 하고 비어 있으면 안 됩니다.')
    cats: List[Category] = []
    warnings: List[str] = []
    for order, (name, value) in enumerate(data.items()):
        where = f"카테고리 '{name}'"
        if not str(name).strip():
            raise rt.InputError("규칙 파일에 이름이 빈 카테고리가 있습니다.")
        if name.strip() == UNCLASSIFIED:
            raise rt.InputError(f"'{UNCLASSIFIED}'는 아무 규칙에도 맞지 않는 파일에 쓰는 이름이라 카테고리로 쓸 수 없습니다.")
        excludes: List[Any] = []
        if isinstance(value, dict):
            unknown = set(value) - {"keywords", "exclude"}
            if unknown:
                raise rt.InputError(f"{where}: 알 수 없는 항목 {sorted(unknown)}. 'keywords'와 'exclude'만 쓸 수 있습니다.")
            excludes = value.get("exclude") or []
            value = value.get("keywords")
            if not isinstance(excludes, list) or not all(isinstance(k, str) and k.strip() for k in excludes):
                raise rt.InputError(f"{where}: exclude는 빈 칸이 아닌 문자열 목록이어야 합니다.")
        if not isinstance(value, list) or not value:
            raise rt.InputError(f"{where}: 키워드 목록이 비었거나 목록([...])이 아닙니다.")
        for i, k in enumerate(value, 1):
            if not isinstance(k, str):
                raise rt.InputError(f"{where}: {i}번째 키워드가 문자열이 아닙니다 ({json.dumps(k, ensure_ascii=False)}). 따옴표로 감싸세요.")
            if not k.strip() or k.strip() == ".":
                raise rt.InputError(f"{where}: {i}번째 키워드가 비어 있습니다.")
            if not k.strip().startswith(".") and len(norm(k)) < 2:
                warnings.append(f"{where}: 키워드 '{k}'는 너무 짧아 엉뚱한 파일에도 맞을 수 있습니다.")
            if not k.strip().startswith(".") and not norm(k):
                raise rt.InputError(f"{where}: {i}번째 키워드 '{k}'는 공백·_·-만 있어 비교할 글자가 없습니다.")
        cats.append(Category(name.strip(), order, [k.strip() for k in value], excludes))
    rules = Rules(cats, path, text)
    rules.warnings = warnings
    return rules


def load_rules(path: str) -> Rules:
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise rt.InputError(f"규칙 파일을 찾을 수 없습니다: {path}. [추천] {os.path.join(rt.TOOL_DIR, 'rules.example.json')}")
    if os.path.isdir(path):
        raise rt.InputError(f"규칙 파일 자리에 폴더를 주었습니다: {path}")
    return parse_rules(rt.read_text_file(path), path)


# ==============================================================================
# 2. 점수
# ==============================================================================

class Classifier:
    """파일 하나의 분류. 폴더 점수는 폴더별로 캐시합니다 (파일은 폴더 단위로 모여 들어옴)."""

    def __init__(self, rules: Rules, root: str):
        self.rules = rules
        self.root = root.rstrip("\\/")
        self._dir_cache: Dict[int, Tuple[Dict[int, Dict[str, Any]], List[Tuple[str, str]]]] = {}

    def folder_names(self, dir_path: str) -> List[str]:
        """대상 폴더 아래 폴더 이름들 (가까운 것부터). 대상 폴더 자신과 그 위는 보지 않습니다."""
        rel = dir_path[len(self.root):] if dir_path.startswith(self.root) else ""
        return [p for p in re.split(r"[\\/]+", rel) if p][::-1]

    def _dir_part(self, dir_id: int, dir_path: str) -> Tuple[Dict[int, Dict[str, Any]], List[Tuple[str, str]]]:
        hit = self._dir_cache.get(dir_id)
        if hit is not None:
            return hit
        if len(self._dir_cache) > 50000:
            self._dir_cache.clear()
        names = [(norm(n), lower(n)) for n in self.folder_names(dir_path)]
        scores: Dict[int, Dict[str, Any]] = {}
        for w, original, ci, rx in self.rules.words:
            for depth, (folder, folder_low) in enumerate(names):
                if keyword_in(w, rx, folder, folder_low):
                    pts, where = (SCORE_PARENT, "d1") if depth == 0 else (SCORE_UPPER, "d2")
                    s = scores.setdefault(ci, {})
                    if s.get(original, (0, ""))[0] < pts:
                        s[original] = (pts, where)
                    break
        self._dir_cache[dir_id] = (scores, names)
        return scores, names

    def classify(self, name: str, ext: str, dir_id: int, dir_path: str
                 ) -> Tuple[str, str, Optional[List[Any]], List[Tuple[int, str]]]:
        """(category, confidence, matches, 맞은 (카테고리 번호, 키워드) 목록)."""
        rules = self.rules
        raw_stem = name[: len(name) - len(ext)] if ext and name.lower().endswith(ext) else name
        stem, stem_low = norm(raw_stem), (lower(raw_stem) if rules.rx_words else "")
        found: Dict[int, Dict[str, Tuple[float, str]]] = {}
        for ci in rules.ext_map.get(ext, ()):
            found.setdefault(ci, {})[ext] = (SCORE_EXT, "e")
        for w, original, ci in rules.sub_words:
            if w in stem:
                found.setdefault(ci, {})[original] = (SCORE_NAME, "n")
        for rx, original, ci in rules.rx_words:
            if rx.search(stem_low):
                found.setdefault(ci, {})[original] = (SCORE_NAME, "n")
        dir_scores, folder_norms = self._dir_part(dir_id, dir_path)
        for ci, kws in dir_scores.items():
            tgt = found.setdefault(ci, {})
            for original, val in kws.items():
                if original not in tgt:
                    tgt[original] = val
        if not found:
            return UNCLASSIFIED, "", None, []
        scored: List[Tuple[float, int, Dict[str, Tuple[float, str]]]] = []
        for ci, kws in found.items():
            cat = rules.categories[ci]
            if cat.excludes and any(x in stem or any(x in f for f, _ in folder_norms) for x in cat.excludes):
                continue
            scored.append((sum(v[0] for v in kws.values()), ci, kws))
        if not scored:
            return UNCLASSIFIED, "", None, []
        scored.sort(key=lambda t: (-t[0], t[1]))          # 점수 높은 순, 동점이면 규칙 파일에 먼저 적은 카테고리
        s1 = scored[0][0]
        s2 = scored[1][0] if len(scored) > 1 else 0.0
        conf = confidence(s1, s2)
        matches = [[rules.categories[ci].name, s, [f"{k}@{w}" for k, (_, w) in kws.items()]] for s, ci, kws in scored[:3]]
        hits = [(scored[0][1], k) for k in scored[0][2]]
        return rules.categories[scored[0][1]].name, conf, matches, hits


def confidence(s1: float, s2: float) -> str:
    """1위 점수와 1·2위 점수 차로 신뢰도를 정합니다."""
    if s2 <= 0:
        return "high" if s1 >= SCORE_NAME else ("medium" if s1 >= SCORE_PARENT else "low")
    margin = s1 - s2
    return "high" if margin >= 2 else ("medium" if margin >= 1 else "low")


# ==============================================================================
# 3. 형식(kind) 표: 확장자로 정하는 파일 형식 (규칙과 무관, 내장)
# ==============================================================================

KIND_EXTS = {
    "문서": ".doc .docx .docm .dot .dotx .odt .rtf .txt .md .wpd",
    "표": ".xls .xlsx .xlsm .xlsb .xlt .xltx .csv .tsv .ods",
    "발표": ".ppt .pptx .pptm .pps .ppsx .pot .potx .odp .key",
    "PDF": ".pdf",
    "한글": ".hwp .hwpx .hwt .hml",
    "메일": ".eml .msg .pst .ost .mbox",
    "이미지": ".jpg .jpeg .png .gif .bmp .tif .tiff .webp .heic .svg .ico .psd .ai .eps .raw .cr2 .nef .emf .wmf",
    "도면": ".dwg .dxf .dgn .dwf .step .stp .igs .iges .stl .sldprt .sldasm .slddrw .catpart .catproduct .prt .asm .ipt .iam .3dm",
    "압축": ".zip .7z .rar .egg .alz .tar .gz .tgz .bz2 .xz .cab .iso .lzh .arj",
    "코드/데이터": ".py .js .ts .java .c .cpp .h .hpp .cs .vb .vbs .go .rs .php .rb .sh .sql .json .xml .yaml .yml .toml "
                  ".html .htm .css .ipynb .r .m .db .sqlite .mdb .accdb .dbf .sav .parquet .log .ini .cfg .conf",
    "미디어": ".mp3 .wav .wma .flac .aac .m4a .ogg .mp4 .avi .mkv .mov .wmv .flv .webm .mpg .mpeg .m4v .3gp",
    "실행파일": ".exe .dll .msi .bat .cmd .ps1 .sys .com .scr .jar .apk .appx .msix .ocx .cpl",
    "임시/시스템": ".tmp .temp .bak .old .lnk .url .dat .crdownload .part .swp .cache .lock .~tmp",
}
EXT_KIND = {e: kind for kind, exts in KIND_EXTS.items() for e in exts.split()}
SYSTEM_NAMES = {"thumbs.db", "desktop.ini", ".ds_store", "ehthumbs.db"}
KIND_ORDER = list(KIND_EXTS) + ["기타"]


def kind_of(name: str, ext: str) -> str:
    low = name.lower()
    if low in SYSTEM_NAMES or low.startswith("~$"):
        return "임시/시스템"
    return EXT_KIND.get(ext, "기타")


# ==============================================================================
# 4. 파일명 속 정보: 날짜, 버전, 사본/임시 표시
# ==============================================================================

_D8 = re.compile(r"(?<!\d)((?:19|20)\d{2})[-._ ]?(0[1-9]|1[0-2])[-._ ]?(0[1-9]|[12]\d|3[01])(?!\d)")
_D6 = re.compile(r"(?<!\d)(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")
_DYM = re.compile(r"(?<!\d)((?:19|20)\d{2})[-._ ]?(?:년\s*)?(0?[1-9]|1[0-2])(?:월)?(?!\d)")
_DKR = re.compile(r"(?<!\d)(\d{2}|(?:19|20)\d{2})\s*년\s*(\d{1,2})\s*월")
_DY = re.compile(r"(?<!\d)((?:19|20)\d{2})(?:년|[_\-. ]|$)")
_VERSION = re.compile(r"(?<![a-z])(v|ver|rev|r)\.?\s?(\d+(?:\.\d+)*)(?![\d])|(최+종)|(초안)|(수정본|수정\d*)|(?<![a-z])(final)(?![a-z])"
                      r"|(?<![a-z])(draft)(?![a-z])", re.I)
_COPY = re.compile(r"(복사본|사본|\bcopy\b|\(\d{1,3}\)\s*$|\[\d{1,3}\]\s*$)", re.I)


def _year2(yy: str) -> Optional[int]:
    n = int(yy)
    return 2000 + n if n <= 40 else (1900 + n if n >= 80 else None)


def name_date(stem: str) -> str:
    """파일명 속 날짜 -> 'YYYY-MM-DD', 'YYYY-MM', 'YYYY' (없으면 '')."""
    m = _D8.search(stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DKR.search(stem)
    if m:
        y = int(m.group(1)) if len(m.group(1)) == 4 else _year2(m.group(1))
        if y and 1 <= int(m.group(2)) <= 12:
            return f"{y}-{int(m.group(2)):02d}"
    m = _D6.search(stem)
    if m:
        y = _year2(m.group(1))
        if y:
            return f"{y}-{m.group(2)}-{m.group(3)}"
    m = _DYM.search(stem)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = _DY.search(stem)
    return m.group(1) if m else ""


def name_info(name: str, ext: str) -> Tuple[str, str, str]:
    """(날짜, 버전, 표시[copy,temp]) - 파일명에서 뽑은 정보."""
    stem = name[: len(name) - len(ext)] if ext and name.lower().endswith(ext) else name
    stem = unicodedata.normalize("NFC", stem)
    version = ""
    m = _VERSION.search(stem)
    if m:
        if m.group(1):
            version = f"{m.group(1).lower()}{m.group(2)}"
        else:
            version = next(g for g in m.groups()[2:] if g).lower()
    flags: List[str] = []
    if _COPY.search(stem):
        flags.append("copy")
    if name.startswith("~") or EXT_KIND.get(ext) == "임시/시스템" and ext not in (".lnk", ".url", ".dat"):
        flags.append("temp")
    return name_date(stem), version, ",".join(flags)


# ==============================================================================
# 5. 미분류 파일명의 자주 나오는 단어 (규칙 보완용)
# ==============================================================================

_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
_EDGE_DIGITS = re.compile(r"^\d+|\d+$")
_VERSION_TOKEN = re.compile(r"v\d*|r\d*")
_STOP = {"the", "and", "of", "for", "copy", "img", "dsc", "final", "ver", "rev", "new", "file", "복사본", "사본", "최종",
         "수정", "수정본", "초안"}


def name_tokens(stem: str) -> List[str]:
    out = []
    for t in _TOKEN.findall(unicodedata.normalize("NFC", stem)):
        t = t.lower()
        t = _EDGE_DIGITS.sub("", t)       # 'v2', '2026보고서' -> 숫자 떼기
        if len(t) >= 2 and not t.isdigit() and t not in _STOP and not _VERSION_TOKEN.fullmatch(t):
            out.append(t)
    return out


def matches_text(matches: Optional[Sequence[Any]]) -> str:
    """matches(JSON)를 사람이 읽는 글로: '계약서 4점(계약@파일명, .hwp@확장자)'."""
    if not matches:
        return ""
    parts = []
    for cat, score, hits in matches:
        where = ", ".join(f"{h.rsplit('@', 1)[0]}@{WHERE_LABEL.get(h.rsplit('@', 1)[1], '')}" for h in hits)
        parts.append(f"{cat} {score:g}점({where})")
    return " / ".join(parts)
