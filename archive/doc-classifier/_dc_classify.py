"""classify: DB의 이름 정보만으로 분류합니다 (디스크의 파일은 읽지 않음).

- 파일을 id 순서로 묶음(BATCH)씩 읽어 분류하고 같은 묶음 단위로 기록합니다. 메모리는 파일 수와 무관합니다.
- 규칙을 바꿔 다시 실행하면 처음부터 다시 분류합니다 (수백만 행도 DB 안에서 처리).
- 규칙이 바뀌면 이전 peek 결과는 판정 기준이 달라졌으므로 지웁니다.
- 함께 기록: 형식(kind), 파일명 속 날짜/버전/사본·임시 표시, 상위 폴더(top_id), 중복 후보(같은 이름+같은 크기) 요약.
"""
import collections
import datetime as dt
import hashlib
import heapq
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import _dc_rules as ru
import _dc_runtime as rt
import _dc_store as st

BATCH = 20000
PROGRESS_SECONDS = 2.0
TOKEN_KINDS_SKIP = {"임시/시스템", "실행파일"}       # 미분류 단어 집계에서 뺄 형식
DUP_EXAMPLES = 200


def rules_hash(rules: ru.Rules) -> str:
    """규칙 내용(카테고리 순서, 키워드, exclude)의 지문. 파일 경로는 넣지 않습니다(같은 내용을 옮겨도 peek 결과 유지)."""
    m = rules.as_meta()
    body = json.dumps([m["categories"], m["excludes"]], ensure_ascii=False)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]


def _fill_top_ids(con: Any) -> None:
    """dirs.top_id: 대상 폴더 바로 아래 폴더의 id (대상 폴더 자신은 자기 id). 깊이 순서로 부모 값을 물려받습니다."""
    con.execute("BEGIN")
    con.execute("UPDATE dirs SET top_id = id WHERE depth <= 1")
    max_depth = con.execute("SELECT COALESCE(MAX(depth), 0) FROM dirs").fetchone()[0]
    for d in range(2, max_depth + 1):
        con.execute("UPDATE dirs SET top_id = (SELECT p.top_id FROM dirs p WHERE p.id = dirs.parent_id) WHERE depth = ?", (d,))
    con.execute("COMMIT")


def _clear_peek(con: Any) -> int:
    n = con.execute("SELECT COUNT(*) FROM files WHERE peek_status IS NOT NULL").fetchone()[0]
    if n:
        con.execute("UPDATE files SET peek_status=NULL, peek_excerpt=NULL, peek_category=NULL, peek_reason=NULL, peek_ms=NULL "
                    "WHERE peek_status IS NOT NULL")
    return n


def _duplicates(con: Any) -> Dict[str, Any]:
    """같은 이름(대소문자 무시) + 같은 크기 묶음. 내용 해시는 비싸므로 하지 않습니다(후보일 뿐)."""
    groups = files = wasted = 0
    top: List[Tuple[int, str, int, int]] = []
    sql = ("SELECT lower(name) AS n, size, COUNT(*) AS c FROM files "
           "WHERE size > 0 AND COALESCE(kind, '') <> '임시/시스템' GROUP BY lower(name), size HAVING c > 1")
    for name, size, c in con.execute(sql):
        groups += 1
        files += c
        w = (c - 1) * size
        wasted += w
        item = (w, name, size, c)
        if len(top) < DUP_EXAMPLES:
            heapq.heappush(top, item)
        elif item > top[0]:
            heapq.heapreplace(top, item)
    top.sort(reverse=True)
    examples: List[Dict[str, Any]] = []
    if top:
        con.execute("CREATE TEMP TABLE IF NOT EXISTS dup_top (n TEXT, size INTEGER, PRIMARY KEY(size, n))")
        con.execute("DELETE FROM dup_top")
        con.executemany("INSERT OR IGNORE INTO dup_top VALUES (?, ?)", [(n, s) for _, n, s, _ in top])
        paths: Dict[Tuple[str, int], List[str]] = collections.defaultdict(list)
        q = ("SELECT lower(f.name), f.size, d.path, f.name FROM files f JOIN dirs d ON d.id = f.dir_id "
             "WHERE f.size IN (SELECT size FROM dup_top) AND EXISTS (SELECT 1 FROM dup_top t WHERE t.size = f.size AND t.n = lower(f.name))")
        for n, size, dpath, fname in con.execute(q):
            lst = paths[(n, size)]
            if len(lst) < 5:
                lst.append(st.full_path(dpath, fname))
        con.execute("DROP TABLE dup_top")
        for w, n, size, c in top:
            ps = paths.get((n, size), [])
            examples.append({"name": ps[0].replace("\\", "/").rsplit("/", 1)[-1] if ps else n, "size": size,
                             "copies": c, "wasted": w, "paths": ps})
    return {"groups": groups, "files": files, "wasted_bytes": wasted, "wasted_size": rt.human_size(wasted),
            "examples": examples}


def run(con: Any, job: str, rules: ru.Rules, meta: Dict[str, Any]) -> Dict[str, Any]:
    root = meta.get("root") or ""
    clf = ru.Classifier(rules, root)
    new_hash = rules_hash(rules)
    old_hash = meta.get("rules_hash")
    total = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    con.execute("BEGIN")
    peek_cleared = _clear_peek(con) if old_hash and old_hash != new_hash else 0
    st.set_meta(con, classify_status="running", rules=rules.as_meta(), rules_text=rules.text, rules_hash=new_hash,
                **({"peek_files": 0} if peek_cleared else {}))
    con.execute("COMMIT")
    _fill_top_ids(con)

    kw_hits: "collections.Counter[Tuple[int, str]]" = collections.Counter()
    tokens: "collections.Counter[str]" = collections.Counter()
    start = last = time.time()
    done = 0
    last_id = 0
    sql = ("SELECT f.id, f.name, f.ext, f.dir_id, d.path FROM files f JOIN dirs d ON d.id = f.dir_id "
           "WHERE f.id > ? ORDER BY f.id LIMIT ?")
    try:
        while True:
            rows = con.execute(sql, (last_id, BATCH)).fetchall()
            if not rows:
                break
            updates = []
            for fid, name, ext, dir_id, dpath in rows:
                kind = ru.kind_of(name, ext)
                cat, conf, matches, hits = clf.classify(name, ext, dir_id, dpath)
                ndate, nver, nflags = ru.name_info(name, ext)
                for h in hits:
                    kw_hits[h] += 1
                if cat == ru.UNCLASSIFIED and kind not in TOKEN_KINDS_SKIP:
                    stem = name[: len(name) - len(ext)] if ext else name
                    tokens.update(set(ru.name_tokens(stem)))
                updates.append((kind, cat, conf or None, json.dumps(matches, ensure_ascii=False) if matches else None,
                                ndate or None, nver or None, nflags or None, fid))
            con.execute("BEGIN")
            con.executemany("UPDATE files SET kind=?, category=?, confidence=?, matches=?, name_date=?, name_version=?, "
                            "name_flags=? WHERE id=?", updates)
            con.execute("COMMIT")
            last_id = rows[-1][0]
            done += len(rows)
            if len(tokens) > 300000:
                tokens = collections.Counter(dict(tokens.most_common(50000)))
            now = time.time()
            if now - last >= PROGRESS_SECONDS:
                last = now
                rt.log("PROGRESS", f"분류 {done:,}/{total:,}개 ({done * 100 // max(total, 1)}%), 초당 {done / (now - start):,.0f}개")
    except KeyboardInterrupt:
        con.execute("BEGIN")
        st.set_meta(con, classify_status="partial")
        con.execute("COMMIT")
        raise

    rt.log("INFO", "분류 색인과 중복 후보 집계 중")
    con.execute("CREATE INDEX IF NOT EXISTS files_category ON files(category)")
    dups = _duplicates(con)

    names = rules.names
    keyword_hits: Dict[str, Dict[str, int]] = {}
    for (ci, kw), n in kw_hits.most_common():
        keyword_hits.setdefault(names[ci], {})
        if len(keyword_hits[names[ci]]) < 10:
            keyword_hits[names[ci]][kw] = n
    unclassified_words = [{"word": w, "files": n} for w, n in tokens.most_common(100) if n >= 2]
    seconds = round(time.time() - start, 1)
    con.execute("BEGIN")
    st.set_meta(con, classify_status="complete", classified_at=dt.datetime.now().isoformat(timespec="seconds"),
                classified_files=done, keyword_hits=keyword_hits, unclassified_words=unclassified_words, duplicates=dups,
                updated_at=dt.datetime.now().isoformat(timespec="seconds"))
    con.execute("COMMIT")
    return {"files": done, "seconds": seconds, "files_per_sec": round(done / seconds) if seconds else None,
            "keyword_hits": keyword_hits, "unclassified_words": unclassified_words, "duplicates": dups,
            "peek_cleared": peek_cleared, "rules_changed": bool(old_hash and old_hash != new_hash)}


def category_counts(con: Any, rules_names: List[str]) -> List[Dict[str, Any]]:
    """카테고리별 파일 수, 용량, 신뢰도 분포 (규칙 순서, 미분류는 마지막)."""
    rows: Dict[str, Dict[str, Any]] = {}
    for cat, conf, n, size in con.execute("SELECT category, confidence, COUNT(*), COALESCE(SUM(size), 0) FROM files "
                                          "WHERE category IS NOT NULL GROUP BY category, confidence"):
        r = rows.setdefault(cat, {"category": cat, "files": 0, "bytes": 0, "high": 0, "medium": 0, "low": 0})
        r["files"] += n
        r["bytes"] += size
        if conf in ("high", "medium", "low"):
            r[conf] += n
    total = sum(r["files"] for r in rows.values()) or 1
    order = {n: i for i, n in enumerate(rules_names + [ru.UNCLASSIFIED])}
    out = []
    for r in sorted(rows.values(), key=lambda r: order.get(r["category"], len(order))):
        r["size"] = rt.human_size(r["bytes"])
        r["share"] = round(r["files"] * 100 / total, 1)
        out.append(r)
    for name in rules_names:                   # 하나도 맞지 않은 카테고리도 0으로 보여 규칙 점검을 돕기
        if name not in rows:
            out.append({"category": name, "files": 0, "bytes": 0, "size": "0B", "share": 0.0, "high": 0, "medium": 0, "low": 0})
    out.sort(key=lambda r: order.get(r["category"], len(order)))
    return out


def kind_counts(con: Any) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT kind, COUNT(*), COALESCE(SUM(size), 0) FROM files WHERE kind IS NOT NULL GROUP BY kind").fetchall()
    order = {k: i for i, k in enumerate(ru.KIND_ORDER)}
    return [{"kind": k, "files": n, "size": rt.human_size(b), "bytes": b}
            for k, n, b in sorted(rows, key=lambda r: (order.get(r[0], 99), -r[1]))]


def peek_estimate(con: Any, rules: ru.Rules, per_category: int = 20, max_files: int = 500) -> Dict[str, Any]:
    """peek 기본 설정으로 읽을 표본 수와 대략의 시간 (파일당 약 0.5초로 어림)."""
    n = 0
    for cat in rules.names + [ru.UNCLASSIFIED]:
        c = con.execute("SELECT COUNT(*) FROM (SELECT 1 FROM files WHERE category=? AND no_read=0 LIMIT ?)",
                        (cat, per_category)).fetchone()[0]
        n += c
    n = min(n, max_files)
    return {"files": n, "seconds_estimate": round(n * 0.5)}


def time_text(seconds: Optional[float]) -> str:
    s = int(seconds or 0)
    return f"{s // 60}분 {s % 60}초" if s >= 60 else f"{s}초"
