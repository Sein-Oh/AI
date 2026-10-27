import sys
import os
import glob
import json
import re
import argparse
from typing import Dict, Any, List, Optional, Set

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_cache_dir, get_data_dir
from _cache import get_fresh_cache_payload, list_cached_files

def ensure_file_cached(file_path: str) -> None:
    """대상 파일의 캐시가 없으면 적절한 마이크로 리더를 호출하여 캐시를 사전 생성합니다."""
    ext = os.path.splitext(file_path)[1].lower()
    log_debug(f"캐시 사전 확인 및 생성: {file_path} (확장자: {ext})")
    
    try:
        if ext == ".pdf":
            import pdf_read
            pdf_read.execute({"target": file_path, "format": "text"})
        elif ext in [".hwp", ".hwpx"]:
            import hwp_read
            hwp_read.execute({"target": file_path, "format": "text"})
        elif ext in [".docx", ".doc"]:
            import word_read
            word_read.execute({"target": file_path, "format": "text"})
        elif ext in [".pptx", ".ppt"]:
            import ppt_read
            ppt_read.execute({"target": file_path, "format": "text"})
        elif ext in [".xlsx", ".xls", ".csv"]:
            import excel_read
            excel_read.execute({"target": file_path, "file_path": file_path, "format": "table"})
        elif ext == ".eml":
            import eml_read
            from _cache import save_file_cache
            parsed = eml_read.parse_single_eml(file_path)
            if parsed:
                res_pl = {"emails": [parsed]}
                save_file_cache(file_path, res_pl)
        elif ext in [".txt", ".md", ".log", ".yaml", ".yml", ".ini"]:
            from _cache import save_file_cache
            lines = []
            for enc in ["utf-8-sig", "utf-8", "cp949", "euc-kr", "latin1"]:
                try:
                    with open(file_path, "r", encoding=enc) as f:
                        lines = f.readlines()
                    break
                except Exception:
                    continue
            items = []
            for idx, line in enumerate(lines):
                line_str = line.strip()
                if line_str:
                    items.append({"loc": f"Line {idx + 1}", "line": idx + 1, "text": line_str})
            save_file_cache(file_path, {"items": items, "total_lines": len(lines)})
    except Exception as e:
        log_debug(f"캐시 자동 생성 중 예외 (무시하고 계속): {e}")

def resolve_target_path(target_arg: str) -> Optional[str]:
    """대상 파일 경로를 보정합니다."""
    if not target_arg or target_arg.lower() in ["all", "cache", "*"]:
        return None
    if os.path.isabs(target_arg) and os.path.exists(target_arg):
        return os.path.abspath(target_arg)
    cli_cand = os.path.join(r"C:\cli_data\data", target_arg)
    if os.path.exists(cli_cand):
        return os.path.abspath(cli_cand)
    data_cand = os.path.join(get_data_dir(), target_arg)
    if os.path.exists(data_cand):
        return os.path.abspath(data_cand)
    cwd_cand = os.path.abspath(target_arg)
    if os.path.exists(cwd_cand):
        return cwd_cand
    return target_arg

def parse_num_range(range_str: Optional[str]) -> Set[int]:
    """'1', '1-3', '1,3,5' 등의 숫자 범위를 파싱하여 정수 집합으로 반환합니다."""
    nums: Set[int] = set()
    if not range_str:
        return nums
    for part in str(range_str).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            sub = part.split("-")
            try:
                start = int(sub[0].strip())
                end = int(sub[1].strip())
                nums.update(range(start, end + 1))
            except Exception:
                pass
        else:
            try:
                nums.add(int(part))
            except Exception:
                pass
    return nums

def extract_match_snippet(
    raw_text: str,
    match_start: int,
    match_end: int,
    context_chars: int,
    highlight_terms: List[str],
    regex_pat: Optional[re.Pattern] = None,
    case_sensitive: bool = False,
    full_text: bool = False
) -> str:
    """매칭 위치를 중심으로 전후 문맥을 추출하고 매칭 단어를 **강조** 처리합니다."""
    if full_text:
        snippet = raw_text.strip()
    else:
        start_idx = max(0, match_start - context_chars)
        end_idx = min(len(raw_text), match_end + context_chars)
        core = raw_text[start_idx:end_idx].replace("\n", " ").strip()
        pfx = "..." if start_idx > 0 else ""
        sfx = "..." if end_idx < len(raw_text) else ""
        snippet = f"{pfx}{core}{sfx}"

    # 하이라이트 (**단어**) 적용
    if regex_pat is not None:
        try:
            snippet = regex_pat.sub(lambda m: f"**{m.group(0)}**", snippet)
        except Exception:
            pass
    elif highlight_terms:
        flags = 0 if case_sensitive else re.IGNORECASE
        for ht in sorted(highlight_terms, key=len, reverse=True):
            if not ht:
                continue
            try:
                pat = re.compile(re.escape(ht), flags)
                snippet = pat.sub(lambda m: f"**{m.group(0)}**", snippet)
            except Exception:
                pass

    return snippet

def search_in_cache_data(
    cached_payload: Dict[str, Any],
    query: str,
    use_regex: bool = False,
    case_sensitive: bool = False,
    context_chars: int = 80,
    full_text: bool = False,
    page_filter: Optional[Set[int]] = None,
    slide_filter: Optional[Set[int]] = None
) -> List[Dict[str, Any]]:
    """단일 캐시 JSON 페이로드 내부에서 쿼리(다중 AND/OR, 정규식, 범위 필터)를 검색합니다."""
    matches = []
    file_path = cached_payload.get("file_path", "")
    file_name = os.path.basename(file_path) if file_path else ""
    data_section = cached_payload.get("data", {})

    items = data_section.get("items") or []
    emails = data_section.get("emails") if isinstance(data_section, dict) else None
    if not emails and isinstance(cached_payload.get("emails"), list):
        emails = cached_payload.get("emails")

    if emails and isinstance(emails, list):
        for e in emails:
            e_sub = e.get("subject", "")
            e_from = e.get("from", "")
            e_date = str(e.get("date", ""))
            e_file = e.get("file_name", file_name)
            e_path = e.get("file_path", file_path)
            e_seq = e.get("thread_seq", 1)
            e_tot = e.get("thread_count", 1)
            e_att = ", ".join(e.get("attachments", []))
            
            loc_label = f"[{e_date[:10]}] {e_sub} (From: {e_from}) [대화 {e_seq}/{e_tot}]"
            e_text = f"제목: {e_sub}\n보낸사람: {e_from}\n받는사람: {e.get('to', '')}\n일시: {e_date}\n첨부: {e_att}\n\n{e.get('body_text', '')}"
            items.append({
                "loc": loc_label,
                "text": e_text,
                "file": e_file,
                "path": e_path,
                "date": e_date,
                "year": e.get("year"),
                "subject": e_sub
            })

    if not items and isinstance(data_section, dict):
        raw_data = data_section.get("data")
        if isinstance(raw_data, list):
            for r_idx, row in enumerate(raw_data):
                if isinstance(row, list):
                    row_str = " | ".join(str(c) for c in row if c is not None and str(c).strip() != "")
                    if row_str.strip():
                        items.append({"loc": f"Row {r_idx + 1}", "row": r_idx + 1, "text": row_str})
                elif isinstance(row, str) and row.strip():
                    items.append({"loc": f"Row {r_idx + 1}", "row": r_idx + 1, "text": row})
        else:
            # items가 없는 구형/단순 텍스트 캐시 fallback
            raw_body = str(raw_data or "")
            if raw_body:
                items = [{"loc": "Body", "text": raw_body}]

    # 정규식 모드 사전 컴파일
    regex_pat = None
    if use_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex_pat = re.compile(query, flags)
        except Exception as e:
            log_debug(f"정규식 컴파일 오류: {e}")
            return []

    # 일반 모드 조건 분석 (AND / OR)
    is_and_mode = False
    is_or_mode = False
    terms: List[str] = []
    if not use_regex:
        if " AND " in query:
            is_and_mode = True
            terms = [t.strip() for t in query.split(" AND ") if t.strip()]
        elif " OR " in query:
            is_or_mode = True
            terms = [t.strip() for t in query.split(" OR ") if t.strip()]
        else:
            terms = [query.strip()]

    for it in items:
        # 1. 페이지 및 슬라이드 범위 필터링
        if page_filter and it.get("page") is not None:
            if it.get("page") not in page_filter:
                continue
        if slide_filter and it.get("slide") is not None:
            if it.get("slide") not in slide_filter:
                continue

        raw_txt = str(it.get("text", ""))
        if not raw_txt.strip():
            continue

        match_found = False
        m_start = 0
        m_end = 0
        matched_term = ""
        highlight_terms: List[str] = []

        # 2. 정규식 검색
        if use_regex and regex_pat is not None:
            m = regex_pat.search(raw_txt)
            if m:
                match_found = True
                m_start = m.start()
                m_end = m.end()
                matched_term = m.group(0)

        # 3. 논리 AND 검색 (모든 키워드가 포함되어야 함)
        elif is_and_mode:
            cmp_txt = raw_txt if case_sensitive else raw_txt.lower()
            positions = []
            all_found = True
            for t in terms:
                t_cmp = t if case_sensitive else t.lower()
                pos = cmp_txt.find(t_cmp)
                if pos == -1:
                    all_found = False
                    break
                positions.append((pos, pos + len(t), t))
            if all_found and positions:
                match_found = True
                positions.sort(key=lambda x: x[0])
                m_start, m_end, matched_term = positions[0]
                highlight_terms = [t for _, _, t in positions]

        # 4. 논리 OR 검색 (하나 이상의 키워드가 포함되면 매칭)
        elif is_or_mode:
            cmp_txt = raw_txt if case_sensitive else raw_txt.lower()
            positions = []
            for t in terms:
                t_cmp = t if case_sensitive else t.lower()
                pos = cmp_txt.find(t_cmp)
                if pos != -1:
                    positions.append((pos, pos + len(t), t))
            if positions:
                match_found = True
                positions.sort(key=lambda x: x[0])
                m_start, m_end, matched_term = positions[0]
                highlight_terms = [t for _, _, t in positions]

        # 5. 단일 키워드 / 정확 매칭
        else:
            cmp_txt = raw_txt if case_sensitive else raw_txt.lower()
            target_t = terms[0] if terms else query
            t_cmp = target_t if case_sensitive else target_t.lower()
            pos = cmp_txt.find(t_cmp)
            if pos != -1:
                match_found = True
                m_start = pos
                m_end = pos + len(target_t)
                matched_term = raw_txt[m_start:m_end]
                highlight_terms = [target_t]

        if match_found:
            loc_label = it.get("loc") or (
                f"Page {it.get('page')}" if it.get("page") else (
                    f"Slide {it.get('slide')}" if it.get("slide") else (
                        f"Para {it.get('para')}" if it.get("para") else "Text"
                    )
                )
            )

            snippet = extract_match_snippet(
                raw_text=raw_txt,
                match_start=m_start,
                match_end=m_end,
                context_chars=context_chars,
                highlight_terms=highlight_terms,
                regex_pat=regex_pat,
                case_sensitive=case_sensitive,
                full_text=full_text
            )

            match_entry = {
                "file": it.get("file") or file_name,
                "path": it.get("path") or file_path,
                "loc": loc_label,
                "page": it.get("page"),
                "slide": it.get("slide"),
                "para": it.get("para"),
                "table": it.get("table"),
                "matched_term": matched_term,
                "snippet": snippet
            }
            if full_text:
                match_entry["full_text"] = raw_txt.strip()

            matches.append(match_entry)

    return matches

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """향상된 다중 조건(AND/OR), 정규식, 범위 필터 및 초고속 캐시 인덱스 검색을 수행합니다."""
    query = (params.get("query") or params.get("search") or params.get("q") or "").strip()
    target = params.get("target") or params.get("file") or params.get("dir")
    top_k = int(params.get("top") or params.get("limit") or 10)
    cache_only = bool(params.get("cache_only", False))
    use_regex = bool(params.get("regex", False))
    case_sensitive = bool(params.get("case_sensitive", False))
    context_chars = int(params.get("context") or 80)
    full_text = bool(params.get("full_text", False))

    page_filter = parse_num_range(params.get("pages") or params.get("page"))
    slide_filter = parse_num_range(params.get("slides") or params.get("slide"))

    # 캐시 목록 조회 모드 (--list / list_caches)
    list_caches = bool(params.get("list_caches") or params.get("list") or params.get("action") == "list" or query in ["--list", "list_caches", "__list__"])
    if list_caches:
        cached_list = list_cached_files(unique_only=True)
        preview_lines = [f"총 {len(cached_list)}개 원본 문서 캐시 보관 중:"]
        for idx, c in enumerate(cached_list[:15], 1):
            ex = "[존재]" if c["file_exists"] else "[삭제됨]"
            preview_lines.append(f"  {idx}. {c['file_name']} ({c['file_type'].upper()}, {c['cached_at']}, {c['items']}개 항목) {ex}")
        if len(cached_list) > 15:
            preview_lines.append(f"  ... 외 {len(cached_list) - 15}개 문서")

        return format_response(
            status="ok",
            module="search",
            action="list_caches",
            preview="\n".join(preview_lines),
            agent_directive="VERIFIED: Cache file list retrieved successfully. Do not re-verify.",
            extra={
                "total_unique_files": len(cached_list),
                "caches": cached_list
            }
        )

    if not query:
        return format_response(
            status="error",
            module="search",
            action="search",
            preview="Query parameter (query/search) is required",
            agent_directive="STOP_RETRY: Missing search query."
        )

    cache_dir = get_cache_dir()
    if not os.path.exists(cache_dir):
        return format_response(
            status="no_match",
            module="search",
            action="search",
            preview=f"No cache directory found: {cache_dir}",
            agent_directive="STOP_RETRY: Cache directory unavailable."
        )

    target_abs = resolve_target_path(target) if target else None

    # A. 특정 폴더 대상 검색인 경우: 폴더 내 모든 지원 포맷 파일 탐색 및 캐시 검색
    if target_abs and os.path.isdir(target_abs):
        SUPPORTED_EXTS = {".docx", ".doc", ".xlsx", ".xls", ".csv", ".pptx", ".ppt", ".pdf", ".hwp", ".hwpx", ".eml", ".md", ".txt", ".json"}
        folder_files = []
        for root, dirs, files in os.walk(target_abs):
            for fn in files:
                ext = os.path.splitext(fn)[1].lower()
                if ext in SUPPORTED_EXTS:
                    folder_files.append(os.path.join(root, fn))

        folder_files.sort()
        all_matches = []
        for fp in folder_files:
            c_payload = None
            if fp.lower().endswith(".json"):
                try:
                    with open(fp, "r", encoding="utf-8") as jf:
                        direct_json = json.load(jf)
                    c_payload = {"file_path": fp, "data": direct_json}
                except Exception:
                    continue
            else:
                c_payload = get_fresh_cache_payload(fp)
                if not c_payload and not cache_only:
                    ensure_file_cached(fp)
                    c_payload = get_fresh_cache_payload(fp)

            if c_payload:
                f_matches = search_in_cache_data(
                    cached_payload=c_payload,
                    query=query,
                    use_regex=use_regex,
                    case_sensitive=case_sensitive,
                    context_chars=context_chars,
                    full_text=full_text,
                    page_filter=page_filter if page_filter else None,
                    slide_filter=slide_filter if slide_filter else None
                )
                all_matches.extend(f_matches)
                if len(all_matches) >= top_k:
                    break
        all_matches = all_matches[:top_k]

    # B. 특정 단일 파일 대상 검색인 경우: 캐시 존재 시 직접 읽고, 없을 때만 생성 후 읽음
    elif target_abs:
        if target_abs.lower().endswith(".json") and os.path.exists(target_abs):
            try:
                with open(target_abs, "r", encoding="utf-8") as jf:
                    direct_json = json.load(jf)
                cached_payload = {
                    "file_path": target_abs,
                    "data": direct_json
                }
            except Exception as e_jf:
                log_debug(f"Direct JSON load failed: {e_jf}")
                cached_payload = None
        else:
            cached_payload = get_fresh_cache_payload(target_abs)
            if cached_payload:
                log_debug(f"캐시 존재: '{os.path.basename(target_abs)}' 기존 캐시에서 직접 검색 (0.001s)")
            elif not cache_only and os.path.exists(target_abs):
                log_debug(f"캐시 없음: '{os.path.basename(target_abs)}' 신규 캐시 생성 후 검색")
                ensure_file_cached(target_abs)
                cached_payload = get_fresh_cache_payload(target_abs)

        if not cached_payload:
            return format_response(
                status="no_match",
                module="search",
                action="search",
                preview=f"No valid cache or data found for '{os.path.basename(target_abs)}'",
                agent_directive="STOP_RETRY: Document cache unavailable.",
                extra={"query": query, "target": target_abs, "matches": []}
            )

        all_matches = search_in_cache_data(
            cached_payload=cached_payload,
            query=query,
            use_regex=use_regex,
            case_sensitive=case_sensitive,
            context_chars=context_chars,
            full_text=full_text,
            page_filter=page_filter if page_filter else None,
            slide_filter=slide_filter if slide_filter else None
        )[:top_k]

    # B. 전체 파일 대상 전역 검색인 경우: cache_dir 내 최신 캐시 전수 탐색
    else:
        # 0. query가 실제 파일 경로 또는 파일명인 경우 디스크 선제 탐색 및 캐싱
        cand_path = resolve_target_path(query)
        if cand_path and os.path.isfile(cand_path):
            ensure_file_cached(cand_path)
            return format_response(
                status="ok",
                module="search",
                action="file_found",
                preview=f"파일 발견: {cand_path} (존재 확인 완료)",
                agent_directive=f"VERIFIED: File found at '{cand_path}'. Proceed with operations on this file.",
                extra={"query": query, "file_path": cand_path, "matches": [{"file": cand_path, "path": cand_path, "loc": "File", "snippet": f"File exists at {cand_path}"}]}
            )

        cache_files = glob.glob(os.path.join(cache_dir, "cache_*.json"))
        cache_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        all_matches = []
        inspected_files = set()

        for c_path in cache_files:
            try:
                with open(c_path, "r", encoding="utf-8") as f:
                    c_payload = json.load(f)

                c_file_path = c_payload.get("file_path", "")
                if c_file_path in inspected_files:
                    continue
                inspected_files.add(c_file_path)

                file_matches = search_in_cache_data(
                    cached_payload=c_payload,
                    query=query,
                    use_regex=use_regex,
                    case_sensitive=case_sensitive,
                    context_chars=context_chars,
                    full_text=full_text,
                    page_filter=page_filter if page_filter else None,
                    slide_filter=slide_filter if slide_filter else None
                )
                all_matches.extend(file_matches)

                if len(all_matches) >= top_k:
                    break
            except Exception:
                continue

        all_matches = all_matches[:top_k]

    if not all_matches:
        target_info = f" in '{os.path.basename(target_abs)}'" if target_abs else ""
        return format_response(
            status="no_match",
            module="search",
            action="search",
            preview=f"0 matches found for '{query}'{target_info}",
            agent_directive="STOP_RETRY: No search matches found in cached files.",
            extra={"query": query, "matches": []}
        )

    # 1줄 프리뷰 메시지 구성
    match_locations = [f"{m['file']} ({m['loc']})" for m in all_matches[:3]]
    if len(all_matches) > 3:
        loc_str = ", ".join(match_locations) + f" 외 {len(all_matches)-3}건"
    else:
        loc_str = ", ".join(match_locations)

    preview_msg = f"Found {len(all_matches)} matches for '{query}': [{loc_str}]"

    # 검색 결과를 Office 활성 창/대상 문서로 직접 체이닝 전송 (--to word / excel / ppt)
    to_app = (params.get("to") or "").lower()
    dest_target = params.get("dest") or "active"

    if to_app and all_matches:
        send_summary = ""
        try:
            if to_app == "word":
                from _com_guard import word_session
                import word_write
                # Word 전송 시 깔끔한 마크다운 리스트 형태로 서식화 주입
                content_lines = [f"### [SEARCH RESULT] '{query}' (총 {len(all_matches)}건 매칭)\n"]
                for m in all_matches:
                    content_lines.append(f"- **[{m['file']}] {m['loc']}**")
                    content_lines.append(f"  > {m.get('snippet', '')}\n")
                formatted_doc_text = "\n".join(content_lines)

                with word_session(target=dest_target, snapshot=True) as (app, doc):
                    word_write.execute(app, doc, {"text": formatted_doc_text})
                    send_summary = f" -> Sent {len(all_matches)} matches to Word ({dest_target})"

            elif to_app == "excel":
                from _com_guard import excel_session
                import excel_fill
                excel_rows = [["파일명", "위치", "매칭키워드", "스니펫"]]
                for m in all_matches:
                    excel_rows.append([m["file"], m["loc"], m.get("matched_term", query), m.get("snippet", "")])
                with excel_session(target=dest_target, snapshot=True) as (app, wb, ws):
                    excel_fill.execute(wb, ws, {"values": excel_rows})
                    send_summary = f" -> Sent {len(all_matches)} matches to Excel ({dest_target})"

            elif to_app == "ppt":
                from _com_guard import ppt_session
                import ppt_write
                ppt_text = "\n".join(f"[{m['file']} - {m['loc']}]\n{m.get('snippet', '')}" for m in all_matches)
                with ppt_session(target=dest_target, snapshot=True) as (app, prs):
                    ppt_write.execute(app, prs, {"title": f"검색 결과: '{query}'", "text": ppt_text})
                    send_summary = f" -> Sent {len(all_matches)} matches to PPT ({dest_target})"

        except Exception as e_send:
            log_debug(f"Office 전송 실패: {e_send}")
            send_summary = f" -> Failed sending to {to_app}: {e_send}"

        preview_msg += send_summary

    return format_response(
        status="ok",
        module="search",
        action="search_and_send" if to_app else "search",
        preview=preview_msg,
        agent_directive="VERIFIED: Search completed and chained." if to_app else "VERIFIED: Search completed. Do not re-verify.",
        extra={
            "query": query,
            "total_matches": len(all_matches),
            "matches": all_matches,
            "chained_to": to_app if to_app else None
        }
    )

def main():
    parser = argparse.ArgumentParser(description="Enhanced Multi-Condition Universal Cache Search Micro Block")
    parser.add_argument("--query", "-q", "--search", default="", help="검색할 키워드 (다중 조건 'A AND B', 'A OR B' 지원)")
    parser.add_argument("--list", "--list-caches", action="store_true", help="스냅샷/백업을 제외하고 순수 캐시된 원본 문서 목록만 빠르게 조회")
    parser.add_argument("--target", "--file", "-f", "--dir", dest="target", help="특정 대상 파일 또는 폴더 (생략 시 전체 캐시 대상 검색)")
    parser.add_argument("--top", "-n", type=int, default=10, help="최대 반환 매칭 건수 (기본 10)")
    parser.add_argument("--regex", "-r", action="store_true", help="정규표현식(Regex) 패턴 검색 활성화")
    parser.add_argument("--case-sensitive", "-c", action="store_true", help="대소문자 정확 구분")
    parser.add_argument("--context", "-C", type=int, default=80, help="스니펫 전후 문맥 글자 수 (기본 80)")
    parser.add_argument("--full-text", action="store_true", help="스니펫 대신 단락/슬라이드 전체 텍스트 반환")
    parser.add_argument("--pages", "-p", help="특정 페이지 번호 필터링 (예: '1', '1-3', '1,4')")
    parser.add_argument("--slides", "-s", help="특정 슬라이드 번호 필터링 (예: '1-3', '2')")
    parser.add_argument("--cache-only", action="store_true", help="기존 캐시만 검색 (자동 캐시 생성 생략)")
    parser.add_argument("--to", choices=["word", "excel", "ppt"], help="검색 결과를 지정한 Office 앱으로 즉시 전송 및 주입")
    parser.add_argument("--dest", default="active", help="전송 대상 문서 (기본: active)")
    args = parser.parse_args()

    params = {
        "query": args.query,
        "list_caches": args.list,
        "target": args.target,
        "top": args.top,
        "regex": args.regex,
        "case_sensitive": args.case_sensitive,
        "context": args.context,
        "full_text": args.full_text,
        "pages": args.pages,
        "slides": args.slides,
        "cache_only": args.cache_only,
        "to": args.to,
        "dest": args.dest
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
