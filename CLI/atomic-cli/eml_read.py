import sys
import os
import re
import glob
import json
import hashlib
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Dict, Any, List, Optional, Set, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_data_dir, get_cache_dir, resolve_data_path

class HTMLStripper(HTMLParser):
    """HTML 본문에서 태그를 완전히 제거하고 순수 텍스트만 추출하는 경량 파서"""
    def __init__(self):
        super().__init__()
        self.reset()
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self) -> str:
        raw = "".join(self.fed)
        # 다중 공백 및 불필요한 줄바꿈 정리
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        return "\n".join(lines)

def strip_html(html_str: str) -> str:
    """HTML 문자열을 순수 텍스트로 변환합니다."""
    if not html_str:
        return ""
    try:
        s = HTMLStripper()
        s.feed(html_str)
        return s.get_data()
    except Exception:
        # 정규식 fallback
        clean = re.sub(r"<[^>]+>", " ", html_str)
        return re.sub(r"\s+", " ", clean).strip()

def format_size(num_bytes: int) -> str:
    """바이트 수를 읽기 쉬운 KB/MB 단위 문자열로 변환합니다."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    else:
        return f"{num_bytes / (1024 * 1024):.1f} MB"

def normalize_subject(subj: str) -> str:
    """Re:, Fwd:, [회신] 등의 접두사를 모두 제거한 원본 대화 제목을 반환합니다."""
    if not subj:
        return "(제목 없음)"
    cleaned = subj
    # Re, Fwd, 회신, 답장, 전달 등 반복 제거
    pattern = re.compile(r"^\s*(\[?(?:re|fwd|fw|회신|답장|전달)\]?[:\s\-]*)", re.IGNORECASE)
    while True:
        m = pattern.match(cleaned)
        if not m:
            break
        cleaned = cleaned[m.end():].strip()
    return cleaned if cleaned else subj.strip()

def parse_single_eml(file_path: str) -> Optional[Dict[str, Any]]:
    """단일 .eml 파일을 파싱하여 메타데이터와 순수 텍스트가 정규화된 딕셔너리를 반환합니다."""
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return None

    try:
        with open(abs_path, "rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)
    except Exception as e:
        log_debug(f"EML 파싱 실패 ({os.path.basename(abs_path)}): {e}")
        return None

    # 1. 헤더 추출
    subject = str(msg.get("subject", "") or "").strip()
    from_addr = str(msg.get("from", "") or "").strip()
    to_addr = str(msg.get("to", "") or "").strip()
    cc_addr = str(msg.get("cc", "") or "").strip()
    msg_id = str(msg.get("message-id", "") or "").strip()
    in_reply_to = str(msg.get("in-reply-to", "") or "").strip()
    refs_header = str(msg.get("references", "") or "").strip()
    references = [r.strip() for r in refs_header.split() if r.strip()]

    # 2. 일시(Date) 및 연도(Year) 파싱
    date_header = msg.get("date")
    parsed_date_str = ""
    year = 0
    if date_header:
        try:
            dt = parsedate_to_datetime(str(date_header))
            parsed_date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            year = dt.year
        except Exception:
            parsed_date_str = str(date_header)

    if not year:
        # 파일 수정 시간 fallback
        mtime = os.path.getmtime(abs_path)
        dt = datetime.fromtimestamp(mtime)
        parsed_date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        year = dt.year

    # 3. 고유 ID 생성 (Message-ID 우선, 없으면 내용 해시)
    if not msg_id:
        seed = f"{from_addr}_{parsed_date_str}_{subject}_{os.path.getsize(abs_path)}"
        msg_id = f"gen_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"

    # 4. 첨부파일명 및 용량 목록 추출 (바이너리 본문은 완전 제외)
    attachments: List[str] = []
    body_text_parts: List[str] = []
    html_body_parts: List[str] = []

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = str(part.get_content_disposition() or "")

        # 첨부파일 감지
        filename = part.get_filename()
        if filename or disposition in ["attachment", "inline"] and content_type not in ["text/plain", "text/html"]:
            fn = filename or "이름_없는_첨부"
            payload = part.get_payload(decode=True)
            size_str = format_size(len(payload)) if payload else "0 B"
            attachments.append(f"{fn} ({size_str})")
            continue

        # 본문 감지
        if content_type == "text/plain" and disposition != "attachment":
            try:
                text_content = part.get_content()
                if isinstance(text_content, str):
                    body_text_parts.append(text_content.strip())
            except Exception:
                raw_payload = part.get_payload(decode=True)
                if raw_payload:
                    for enc in ["utf-8", "cp949", "euc-kr", "latin1"]:
                        try:
                            body_text_parts.append(raw_payload.decode(enc).strip())
                            break
                        except Exception:
                            pass
        elif content_type == "text/html" and disposition != "attachment":
            try:
                html_content = part.get_content()
                if isinstance(html_content, str):
                    html_body_parts.append(strip_html(html_content))
            except Exception:
                raw_payload = part.get_payload(decode=True)
                if raw_payload:
                    for enc in ["utf-8", "cp949", "euc-kr", "latin1"]:
                        try:
                            html_body_parts.append(strip_html(raw_payload.decode(enc)))
                            break
                        except Exception:
                            pass

    # 본문 결합: Plain 우선, 없으면 HTML 변환 텍스트
    if body_text_parts:
        final_body = "\n\n".join(body_text_parts)
    elif html_body_parts:
        final_body = "\n\n".join(html_body_parts)
    else:
        final_body = ""

    # 답장 여부 판별
    is_reply = bool(in_reply_to or re.match(r"^\s*(\[?(?:re|회신|답장)\]?[:\s\-])", subject, re.IGNORECASE))
    clean_sub = normalize_subject(subject)

    return {
        "id": msg_id,
        "file_name": os.path.basename(abs_path),
        "file_path": abs_path,
        "date": parsed_date_str,
        "year": year,
        "from": from_addr,
        "to": to_addr,
        "cc": cc_addr,
        "subject": subject,
        "clean_subject": clean_sub,
        "is_reply": is_reply,
        "in_reply_to": in_reply_to,
        "references": references,
        "attachments": attachments,
        "body_text": final_body
    }

def link_and_sort_threads(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """이메일 목록의 In-Reply-To 및 제목을 대조하여 thread_id, thread_seq, thread_count를 부여하고 시간순 정렬합니다."""
    if not emails:
        return []

    # 1. 일시 기준 오름차순 정렬 (가장 오래된 원본이 1번)
    emails.sort(key=lambda x: str(x.get("date", "")))

    # 2. 메시지 ID 매핑 및 제목 매핑
    msg_id_map: Dict[str, Dict[str, Any]] = {e["id"]: e for e in emails if e.get("id")}
    subject_thread_map: Dict[str, str] = {}

    for idx, e in enumerate(emails):
        parent_id = e.get("in_reply_to")
        clean_sub = e.get("clean_subject") or normalize_subject(e.get("subject", ""))

        thread_id = None
        # A. In-Reply-To 부모가 존재하는 경우
        if parent_id and parent_id in msg_id_map:
            thread_id = msg_id_map[parent_id].get("thread_id")
        
        # B. 부모가 없거나 못 찾은 경우 정규화된 제목으로 그룹화
        if not thread_id:
            sub_key = clean_sub.lower().strip()
            if sub_key in subject_thread_map:
                thread_id = subject_thread_map[sub_key]
            else:
                # 새로운 스레드 시작
                th_seed = f"{sub_key}_{idx}"
                thread_id = f"thread_{hashlib.sha256(th_seed.encode('utf-8')).hexdigest()[:12]}"
                subject_thread_map[sub_key] = thread_id

        e["thread_id"] = thread_id

    # 3. 스레드별 카운트 및 순번 부여
    thread_groups: Dict[str, List[Dict[str, Any]]] = {}
    for e in emails:
        tid = e["thread_id"]
        thread_groups.setdefault(tid, []).append(e)

    for tid, group in thread_groups.items():
        # 시간순 정렬
        group.sort(key=lambda x: str(x.get("date", "")))
        tot = len(group)
        for seq, item in enumerate(group, start=1):
            item["thread_seq"] = seq
            item["thread_count"] = tot

    # 최신 날짜 역순(또는 시간순)으로 반환
    emails.sort(key=lambda x: str(x.get("date", "")), reverse=True)
    return emails

def build_master_json(source_dir_or_files: List[str], recursive: bool = True) -> Dict[str, Any]:
    """지정된 폴더 또는 파일들로부터 모든 .eml을 수집하여 단 1개의 Master JSON 페이로드를 생성합니다."""
    eml_files: List[str] = []
    
    for src in source_dir_or_files:
        if os.path.isfile(src) and src.lower().endswith(".eml"):
            eml_files.append(os.path.abspath(src))
        elif os.path.isdir(src):
            pattern = "**/*.eml" if recursive else "*.eml"
            found = glob.glob(os.path.join(src, pattern), recursive=recursive)
            eml_files.extend([os.path.abspath(f) for f in found])

    eml_files = sorted(list(set(eml_files)))
    log_debug(f"수집된 EML 파일 수: {len(eml_files)}건")

    parsed_list: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    for f_path in eml_files:
        parsed = parse_single_eml(f_path)
        if parsed:
            m_id = parsed["id"]
            if m_id not in seen_ids:
                seen_ids.add(m_id)
                parsed_list.append(parsed)

    linked_emails = link_and_sort_threads(parsed_list)

    return {
        "generated_at": datetime.now().isoformat(),
        "total_emails": len(linked_emails),
        "source_count": len(eml_files),
        "emails": linked_emails
    }

def resolve_json_path(path_arg: str) -> str:
    """JSON 경로를 현재 작업 디렉터리, cache_dir, data_dir 순으로 보정합니다."""
    if not path_arg:
        return os.path.join(get_cache_dir(), "eml_master.json")
    if os.path.isabs(path_arg) and os.path.exists(path_arg):
        return path_arg
    if os.path.exists(path_arg):
        return os.path.abspath(path_arg)
    c_cand = os.path.join(get_cache_dir(), path_arg)
    if os.path.exists(c_cand):
        return os.path.abspath(c_cand)
    d_cand = os.path.join(get_data_dir(), path_arg)
    if os.path.exists(d_cand):
        return os.path.abspath(d_cand)
    return path_arg

def extract_from_json(
    master_path: str,
    year: Optional[int] = None,
    keyword: Optional[str] = None,
    from_addr: Optional[str] = None
) -> Dict[str, Any]:
    """Master JSON에서 연도/키워드/발신자 조건을 필터링하여 새로운 1개의 JSON 페이로드를 추출합니다."""
    resolved_path = resolve_json_path(master_path)
    if not os.path.exists(resolved_path):
        raise FileNotFoundError(f"Master JSON 파일을 찾을 수 없습니다: {master_path}")

    with open(resolved_path, "r", encoding="utf-8") as f:
        master_data = json.load(f)

    emails: List[Dict[str, Any]] = master_data.get("emails", [])
    filtered: List[Dict[str, Any]] = []

    kw_lower = keyword.lower().strip() if keyword else None
    from_lower = from_addr.lower().strip() if from_addr else None

    for e in emails:
        # 연도 조건
        if year is not None:
            if e.get("year") != year:
                continue

        # 발신자 조건
        if from_lower:
            if from_lower not in str(e.get("from", "")).lower():
                continue

        # 키워드 조건 (제목, 본문, 발신자, 첨부파일명 전방위 검사)
        if kw_lower:
            haystack = (
                f"{e.get('subject', '')} {e.get('body_text', '')} "
                f"{e.get('from', '')} {e.get('to', '')} "
                f"{' '.join(e.get('attachments', []))}"
            ).lower()
            if kw_lower not in haystack:
                continue

        filtered.append(e)

    return {
        "generated_at": datetime.now().isoformat(),
        "extracted_from": os.path.basename(master_path),
        "filter_criteria": {
            "year": year,
            "keyword": keyword,
            "from": from_addr
        },
        "total_emails": len(filtered),
        "emails": filtered
    }

def merge_json_files(json_paths: List[str]) -> Dict[str, Any]:
    """여러 JSON 파일들의 이메일 목록을 읽어 중복을 제거하고 스레드를 재구성하여 1개의 통합 JSON 페이로드로 결합합니다."""
    merged_list: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    for jp in json_paths:
        if not os.path.exists(jp):
            continue
        try:
            with open(jp, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("emails", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for e in items:
                m_id = e.get("id")
                if not m_id:
                    seed = f"{e.get('from')}_{e.get('date')}_{e.get('subject')}"
                    m_id = f"gen_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"
                    e["id"] = m_id
                if m_id not in seen_ids:
                    seen_ids.add(m_id)
                    merged_list.append(e)
        except Exception as e_m:
            log_debug(f"JSON 결합 읽기 실패 ({jp}): {e_m}")

    linked = link_and_sort_threads(merged_list)
    return {
        "generated_at": datetime.now().isoformat(),
        "total_emails": len(linked),
        "merged_source_files": [os.path.basename(p) for p in json_paths],
        "emails": linked
    }

def print_thread_tree(master_path: str, query: str) -> None:
    """Master JSON에서 쿼리와 매칭되는 스레드의 전체 Re: 대화 흐름을 트리 형태로 출력합니다."""
    resolved_path = resolve_json_path(master_path)
    if not os.path.exists(resolved_path):
        print(f"[ERROR] JSON 파일이 없습니다: {master_path}")
        return

    with open(resolved_path, "r", encoding="utf-8") as f:
        master_data = json.load(f)

    emails: List[Dict[str, Any]] = master_data.get("emails", [])
    q_lower = query.lower().strip()

    # 1. 쿼리와 일치하는 이메일 찾기
    matched_threads: Set[str] = set()
    for e in emails:
        haystack = f"{e.get('subject', '')} {e.get('clean_subject', '')} {e.get('body_text', '')}".lower()
        if q_lower in haystack:
            matched_threads.add(e.get("thread_id"))

    if not matched_threads:
        print(f"[알림] '{query}'와 일치하는 대화 스레드를 찾을 수 없습니다.")
        return

    for tid in matched_threads:
        group = [e for e in emails if e.get("thread_id") == tid]
        group.sort(key=lambda x: str(x.get("date", "")))

        clean_title = group[0].get("clean_subject") or group[0].get("subject")
        print("\n" + "=" * 80)
        print(f" 대화 스레드: [ {clean_title} ] (총 {len(group)}건의 대화)")
        print("=" * 80)

        for idx, item in enumerate(group, start=1):
            is_reply_mark = "(답장 Re:)" if item.get("is_reply") else "(원문 최초 발신)"
            indent = "  " * (idx - 1)
            branch = "└── " if idx > 1 else ""
            print(f"{indent}{branch}[{idx}/{len(group)}] {item.get('date')} | {item.get('from')} -> {item.get('to')} {is_reply_mark}")
            print(f"{indent}    제목: {item.get('subject')}")
            print(f"{indent}    원본 파일: {item.get('file_name')}")
            print(f"{indent}    원본 경로: {item.get('file_path')}")
            if item.get("attachments"):
                print(f"{indent}    첨부: {', '.join(item['attachments'])}")
            
            body_preview = item.get("body_text", "").replace("\n", " ").strip()[:90]
            if body_preview:
                print(f"{indent}    본문: {body_preview}...")
            print(f"{indent}  │")
        print("=" * 80)

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 및 CLI 연동을 위한 메인 실행 핸들러"""
    action = (params.get("action") or "build").lower()
    target = params.get("target") or params.get("dir")
    to_file = params.get("to") or params.get("output")
    from_file = params.get("from")

    # 캐시 목록 조회 액션
    if action == "list":
        cache_dir = get_cache_dir()
        pattern = os.path.join(cache_dir, "eml_master_*.json")
        files = glob.glob(pattern)
        file_infos = []
        for fp in sorted(files):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                total = data.get("total_emails", 0)
                generated = data.get("generated_at", "")
                # 제목 목록 추출 (최대 5개)
                subjects = [e.get("subject", "") for e in data.get("emails", [])[:5]]
                file_infos.append({
                    "file": os.path.basename(fp),
                    "total_emails": total,
                    "generated_at": generated,
                    "subjects_sample": subjects
                })
            except Exception:
                continue
        return format_response(
            status="ok",
            module="eml_read",
            action="list",
            preview=f"Found {len(file_infos)} EML master caches",
            agent_directive="VERIFIED: EML cache list retrieved.",
            extra={"caches": file_infos}
        )

    # 1. Thread 조회 액션
    if action == "thread":
        src = from_file or target or os.path.join(get_cache_dir(), "eml_master.json")
        q = params.get("query") or params.get("q") or ""
        print_thread_tree(src, q)
        return format_response(
            status="ok",
            module="eml_read",
            action="thread",
            preview=f"Thread trace executed for query: '{q}'",
            agent_directive="VERIFIED: Thread history displayed."
        )

    # 2. Extract (연도별/과제별 추출) 액션
    if action == "extract":
        src = from_file or target or os.path.join(get_cache_dir(), "eml_master.json")
        year_val = int(params["year"]) if params.get("year") else None
        keyword_val = params.get("keyword") or params.get("project")
        from_val = params.get("from_addr")

        res_payload = extract_from_json(src, year=year_val, keyword=keyword_val, from_addr=from_val)
        
        out_dest = to_file
        if not out_dest:
            cond_label = f"_{year_val}" if year_val else ""
            if keyword_val:
                cond_label += f"_{re.sub(r'[^a-zA-Z0-9가-힣]', '_', keyword_val)}"
            out_dest = os.path.join(get_cache_dir(), f"eml_extracted{cond_label}.json")

        os.makedirs(os.path.dirname(os.path.abspath(out_dest)), exist_ok=True)
        with open(out_dest, "w", encoding="utf-8") as f:
            json.dump(res_payload, f, ensure_ascii=False, indent=2)

        return format_response(
            status="ok",
            module="eml_read",
            action="extract",
            preview=f"Extracted {res_payload['total_emails']} emails to 1 JSON: {os.path.basename(out_dest)}",
            agent_directive="VERIFIED: Filtered emails extracted to single JSON.",
            extra={"output_file": out_dest, "total_emails": res_payload["total_emails"]}
        )

    # 3. Merge 액션
    if action == "merge":
        src_list = []
        if from_file:
            src_list = [p.strip() for p in from_file.split(",") if p.strip()]
        elif target and os.path.isdir(target):
            src_list = glob.glob(os.path.join(target, "*.json"))
        
        if not src_list:
            return format_response(
                status="no_match",
                module="eml_read",
                action="merge",
                preview="No JSON files found to merge",
                agent_directive="STOP_RETRY: Missing source JSONs for merge."
            )

        res_payload = merge_json_files(src_list)
        out_dest = to_file or os.path.join(get_cache_dir(), "eml_master.json")
        os.makedirs(os.path.dirname(os.path.abspath(out_dest)), exist_ok=True)
        with open(out_dest, "w", encoding="utf-8") as f:
            json.dump(res_payload, f, ensure_ascii=False, indent=2)

        return format_response(
            status="ok",
            module="eml_read",
            action="merge",
            preview=f"Merged {len(src_list)} JSON files into {res_payload['total_emails']} emails in {os.path.basename(out_dest)}",
            agent_directive="VERIFIED: Multiple JSONs merged into single Master JSON.",
            extra={"output_file": out_dest, "total_emails": res_payload["total_emails"]}
        )

    # 4. Build / Import (기본 액션): EML 읽어 1개의 Master JSON 생성
    target_dir = target or get_cache_dir()
    targets = [target_dir] if isinstance(target_dir, str) else target_dir

    # 단일 EML 파일인 경우
    if len(targets) == 1 and os.path.isfile(targets[0]) and targets[0].lower().endswith(".eml"):
        parsed = parse_single_eml(targets[0])
        if not parsed:
            return format_response(
                status="error",
                module="eml_read",
                action="parse_eml",
                preview=f"Failed to parse EML: {targets[0]}",
                agent_directive="STOP_RETRY: Corrupted or unreadable EML file."
            )
        res_payload = {
            "generated_at": datetime.now().isoformat(),
            "total_emails": 1,
            "emails": [parsed]
        }
        # 파일명 기반 네이밍
        base_name = os.path.splitext(os.path.basename(targets[0]))[0]
    else:
        res_payload = build_master_json(targets, recursive=params.get("recursive", True))
        # 폴더명 기반 네이밍: 첫 번째 target 경로의 마지막 폴더명 사용
        first_target = targets[0] if targets else get_cache_dir()
        if os.path.isdir(first_target):
            base_name = os.path.basename(os.path.normpath(first_target))
        else:
            base_name = "eml_master"

    # 파일명 중복 방지 네이밍 규칙: eml_master_<폴더명or파일명>.json
    safe_name = re.sub(r"[^\w\-]", "_", base_name)
    default_file_name = f"eml_master_{safe_name}.json"
    out_dest = to_file or os.path.join(get_cache_dir(), default_file_name)
    os.makedirs(os.path.dirname(os.path.abspath(out_dest)), exist_ok=True)
    with open(out_dest, "w", encoding="utf-8") as f:
        json.dump(res_payload, f, ensure_ascii=False, indent=2)

    return format_response(
        status="ok",
        module="eml_read",
        action="build_master",
        preview=f"Processed {res_payload['total_emails']} emails -> 1 Master JSON: {os.path.basename(out_dest)}",
        agent_directive="VERIFIED: EML parsing completed and serialized to single JSON.",
        extra={
            "output_file": out_dest,
            "total_emails": res_payload["total_emails"]
        }
    )

def main():
    import argparse
    parser = argparse.ArgumentParser(description="EML to Single JSON Converter & Thread Analyzer Micro Block")
    parser.add_argument("--action", choices=["build", "extract", "merge", "thread", "list"], default="build", help="수행할 액션 (build, extract, merge, thread, list)")
    parser.add_argument("--dir", dest="dir_path", help="EML 원본 폴더 경로 (미지정 시 config.json의 eml_dir 사용)")
    parser.add_argument("--target", help="단일 EML 파일 또는 대상 폴더")
    parser.add_argument("--to", "--output", dest="to_file", help="저장할 단일 대상 JSON 파일 경로")
    parser.add_argument("--from", dest="from_file", help="추출/병합 대상 소스 JSON 파일 경로 (쉼표 구분 가능)")
    parser.add_argument("--year", type=int, help="추출할 대상 연도 (예: 2026)")
    parser.add_argument("--keyword", "--project", dest="keyword", help="추출 또는 검색할 과제명/키워드")
    parser.add_argument("--query", "-q", help="스레드 조회 검색어")

    args = parser.parse_args()

    params = {
        "action": args.action,
        "dir": args.dir_path,
        "target": args.target,
        "to": args.to_file,
        "from": args.from_file,
        "year": args.year,
        "keyword": args.keyword,
        "query": args.query
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
