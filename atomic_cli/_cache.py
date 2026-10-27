import os
import sys
import glob
import json
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _config import get_cache_dir
from _office_utils import log_debug

def get_file_hash_prefix(file_path: str) -> str:
    """파일의 절대경로를 기반으로 한 고유 식별자 해시(앞 12자리)를 생성합니다."""
    abs_path = os.path.abspath(file_path).lower()
    return hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:12]

def clean_old_caches_for_file(file_path: str, max_keep: int = 2) -> None:
    """해당 원본 파일에 대한 캐시 파일 중 가장 최근 max_keep(기본 2개)만 남기고 삭제합니다."""
    cache_dir = get_cache_dir()
    if not os.path.exists(cache_dir):
        return

    prefix = get_file_hash_prefix(file_path)
    pattern = os.path.join(cache_dir, f"cache_{prefix}_*.json")
    matched_files = glob.glob(pattern)

    if len(matched_files) <= max_keep:
        return

    # 파일 수정 시간(mtime) 역순 정렬 (최신 파일이 앞)
    matched_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    # 최근 2개를 제외한 나머지 삭제
    for old_file in matched_files[max_keep:]:
        try:
            os.remove(old_file)
            log_debug(f"오래된 캐시 파일 자동 삭제 (최근 2개 유지 정책): {os.path.basename(old_file)}")
        except Exception as e:
            log_debug(f"오래된 캐시 삭제 실패: {e}")

def get_file_cache(file_path: str, sub_key: str = "") -> Optional[Dict[str, Any]]:
    """파일의 절대경로와 mtime이 정확히 일치하는 유효한 캐시가 있으면 반환합니다."""
    if not file_path or not os.path.exists(file_path):
        return None

    abs_path = os.path.abspath(file_path)
    current_mtime = os.path.getmtime(abs_path)
    current_size = os.path.getsize(abs_path)

    cache_dir = get_cache_dir()
    if not os.path.exists(cache_dir):
        return None

    prefix = get_file_hash_prefix(abs_path)
    pattern = os.path.join(cache_dir, f"cache_{prefix}_*.json")
    matched_files = glob.glob(pattern)

    # 최신 캐시 파일부터 검사
    matched_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    for c_path in matched_files:
        try:
            with open(c_path, "r", encoding="utf-8") as f:
                cached_obj = json.load(f)
            
            # 절대경로와 mtime, sub_key가 일치하는지 무결성 검증
            if (cached_obj.get("file_path") == abs_path and 
                cached_obj.get("mtime") == current_mtime and 
                cached_obj.get("size") == current_size and
                cached_obj.get("sub_key", "") == sub_key):
                
                log_debug(f"캐시 히트 (0.01s): {os.path.basename(c_path)} (mtime={current_mtime})")
                return cached_obj.get("data")
        except Exception:
            continue

    log_debug(f"캐시 미스 또는 mtime 불일치: {os.path.basename(abs_path)}")
    return None

def get_fresh_cache_payload(file_path: str) -> Optional[Dict[str, Any]]:
    """sub_key에 관계없이 해당 파일의 현재 mtime 및 크기와 일치하는 유효한 최신 캐시 전체 페이로드를 반환합니다."""
    if not file_path or not os.path.exists(file_path):
        return None

    abs_path = os.path.abspath(file_path)
    current_mtime = os.path.getmtime(abs_path)
    current_size = os.path.getsize(abs_path)

    cache_dir = get_cache_dir()
    if not os.path.exists(cache_dir):
        return None

    prefix = get_file_hash_prefix(abs_path)
    pattern = os.path.join(cache_dir, f"cache_{prefix}_*.json")
    matched_files = glob.glob(pattern)
    matched_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    for c_path in matched_files:
        try:
            with open(c_path, "r", encoding="utf-8") as f:
                cached_obj = json.load(f)
            if (cached_obj.get("file_path") == abs_path and 
                cached_obj.get("mtime") == current_mtime and 
                cached_obj.get("size") == current_size):
                log_debug(f"유효한 최신 캐시 발견 (0.001s): {os.path.basename(c_path)}")
                return cached_obj
        except Exception:
            continue

    log_debug(f"유효한 캐시 없음 (mtime 변경 또는 신규 파일): {os.path.basename(abs_path)}")
    return None

def save_file_cache(file_path: str, data: Dict[str, Any], sub_key: str = "", max_keep: int = 2) -> str:
    """파일의 절대경로와 현재 mtime을 결합하여 캐시를 저장하고, 최근 2개만 유지합니다."""
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return ""

    current_mtime = os.path.getmtime(abs_path)
    current_size = os.path.getsize(abs_path)
    cache_dir = get_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)

    prefix = get_file_hash_prefix(abs_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    cache_filename = f"cache_{prefix}_{timestamp}.json"
    cache_filepath = os.path.join(cache_dir, cache_filename)

    cache_payload = {
        "file_path": abs_path,
        "mtime": current_mtime,
        "size": current_size,
        "sub_key": sub_key,
        "cached_at": datetime.now().isoformat(),
        "data": data
    }

    try:
        with open(cache_filepath, "w", encoding="utf-8") as f:
            json.dump(cache_payload, f, ensure_ascii=False, indent=2, default=str)
        log_debug(f"캐시 저장 완료: {cache_filename}")
        
        # 최근 2개 유지 정책 적용
        clean_old_caches_for_file(abs_path, max_keep=max_keep)
        return cache_filepath
    except Exception as e:
        log_debug(f"캐시 파일 쓰기 실패: {e}")
        return ""

def clean_old_snapshots_for_doc(app_name: str, doc_key: str, max_keep: int = 2) -> None:
    """해당 오피스 문서에 대한 스냅샷 파일 중 최근 max_keep(기본 2개)만 남기고 오래된 버전을 자동 삭제합니다."""
    cache_dir = get_cache_dir()
    if not os.path.exists(cache_dir):
        return

    prefix = f"snapshot_{app_name}_{doc_key}"
    pattern_json = os.path.join(cache_dir, f"{prefix}_*.json")
    json_files = glob.glob(pattern_json)

    if len(json_files) <= max_keep:
        return

    # 수정 시간(mtime) 역순 정렬 (최신 파일이 앞)
    json_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    # 최근 max_keep개를 제외한 나머지 오래된 스냅샷(JSON 및 원본 복사본 데이터) 삭제
    for old_json in json_files[max_keep:]:
        try:
            base_no_ext = os.path.splitext(old_json)[0]
            for ext in [".xlsx", ".xlsm", ".xls", ".docx", ".doc", ".pptx", ".ppt"]:
                data_file = base_no_ext + ext
                if os.path.exists(data_file):
                    os.remove(data_file)
            os.remove(old_json)
            log_debug(f"오래된 스냅샷 자동 회전 삭제 (최근 {max_keep}개 유지 정책): {os.path.basename(old_json)}")
        except Exception as e:
            log_debug(f"오래된 스냅샷 삭제 실패: {e}")

def save_document_snapshot(app_name: str, doc_obj: Any, max_keep: int = 2) -> Optional[str]:
    """오피스 활성 문서의 현재 상태를 캐시 디렉터리에 스냅샷으로 저장합니다 (최근 2개 유지)."""
    if doc_obj is None:
        return None

    try:
        cache_dir = get_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        app_lower = app_name.lower()
        
        # 1. 문서 식별자(이름/경로) 및 확장자 추출
        doc_name = "unknown"
        doc_path = ""
        ext = ".xlsx" if app_lower == "excel" else (".docx" if app_lower == "word" else ".pptx")

        if app_lower == "excel":
            try:
                doc_name = doc_obj.Name
                doc_path = doc_obj.FullName if os.path.isabs(doc_obj.FullName) else ""
            except Exception:
                doc_name = "Workbook"
        elif app_lower == "word":
            try:
                doc_name = doc_obj.Name
                doc_path = doc_obj.FullName if os.path.isabs(doc_obj.FullName) else ""
            except Exception:
                doc_name = "Document"
        elif app_lower == "ppt":
            try:
                doc_name = doc_obj.Name
                doc_path = doc_obj.FullName if os.path.isabs(doc_obj.FullName) else ""
            except Exception:
                doc_name = "Presentation"

        # doc_key는 이름과 경로를 기반으로 한 8자리 안정적 고유 해시
        raw_key = (doc_path or doc_name).lower()
        doc_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        base_name = f"snapshot_{app_lower}_{doc_key}_{timestamp}"
        snapshot_data_path = os.path.join(cache_dir, f"{base_name}{ext}").replace("\\", "/")
        snapshot_meta_path = os.path.join(cache_dir, f"{base_name}.json").replace("\\", "/")

        # 2. 애플리케이션별 스냅샷 생성
        saved = False
        if app_lower == "excel":
            try:
                doc_obj.SaveCopyAs(snapshot_data_path)
                saved = os.path.exists(snapshot_data_path)
            except Exception as e:
                log_debug(f"Excel SaveCopyAs 실패: {e}")
        elif app_lower == "ppt":
            try:
                doc_obj.SaveCopyAs(snapshot_data_path)
                saved = os.path.exists(snapshot_data_path)
            except Exception as e:
                log_debug(f"PPT SaveCopyAs 실패: {e}")
        elif app_lower == "word":
            try:
                import shutil
                if doc_path and os.path.exists(doc_path):
                    try:
                        doc_obj.Save()
                    except Exception:
                        pass
                    shutil.copy2(doc_path, snapshot_data_path)
                    saved = True
                else:
                    doc_obj.SaveAs(snapshot_data_path)
                    saved = os.path.exists(snapshot_data_path)
            except Exception as e:
                log_debug(f"Word 스냅샷 저장 실패: {e}")

        if not saved:
            return None

        # 3. 메타데이터 JSON 저장
        meta_payload = {
            "app": app_lower,
            "name": doc_name,
            "original_path": doc_path,
            "snapshot_file": snapshot_data_path,
            "timestamp": timestamp,
            "created_at": datetime.now().isoformat()
        }
        with open(snapshot_meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_payload, f, ensure_ascii=False, indent=2)

        # 4. 최근 2개 유지 정책 적용 (오래된 스냅샷 자동 회전 삭제)
        clean_old_snapshots_for_doc(app_lower, doc_key, max_keep=max_keep)
        log_debug(f"문서 자동 스냅샷 완료 (캐시 보관): {os.path.basename(snapshot_data_path)}")
        return snapshot_data_path
    except Exception as e:
        log_debug(f"스냅샷 생성 예외: {e}")
        return None

def get_latest_snapshot(app_filter: str = "") -> Optional[Dict[str, Any]]:
    """캐시 디렉터리에서 가장 최근에 생성된 스냅샷 메타데이터를 반환합니다."""
    cache_dir = get_cache_dir()
    if not os.path.exists(cache_dir):
        return None

    pattern = os.path.join(cache_dir, "snapshot_*.json")
    meta_files = glob.glob(pattern)
    if not meta_files:
        return None

    meta_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    for mf in meta_files:
        try:
            with open(mf, "r", encoding="utf-8") as f:
                data = json.load(f)
            if app_filter and data.get("app") != app_filter.lower():
                continue
            if os.path.exists(data.get("snapshot_file", "")):
                return data
        except Exception:
            continue
    return None

def list_cached_files(unique_only: bool = True) -> List[Dict[str, Any]]:
    """캐시 디렉터리 내의 순수 캐시 파일(cache_*.json)만 모아 원본 파일명 및 메타데이터 목록을 반환합니다."""
    cache_dir = get_cache_dir()
    if not os.path.exists(cache_dir):
        return []

    cache_files = glob.glob(os.path.join(cache_dir, "cache_*.json"))
    cache_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    seen_files = set()
    results = []

    for c_path in cache_files:
        try:
            with open(c_path, "r", encoding="utf-8") as f:
                c_payload = json.load(f)

            file_path = c_payload.get("file_path", "")
            if not file_path:
                continue

            if unique_only:
                if file_path.lower() in seen_files:
                    continue
                seen_files.add(file_path.lower())

            file_name = os.path.basename(file_path)
            cached_at = str(c_payload.get("cached_at", ""))[:19].replace("T", " ")
            file_exists = os.path.exists(file_path)
            cache_file_size = os.path.getsize(c_path)

            data_sec = c_payload.get("data", {})
            if isinstance(data_sec, dict):
                items = data_sec.get("items") or []
                total_items = len(items) if isinstance(items, list) else (data_sec.get("rows") or data_sec.get("total_lines") or 0)
                total_chars = data_sec.get("total_characters") or len(str(data_sec.get("data") or ""))
                doc_type = data_sec.get("file_type") or os.path.splitext(file_name)[1].lstrip(".").lower()
            else:
                total_items = 0
                total_chars = len(str(data_sec))
                doc_type = os.path.splitext(file_name)[1].lstrip(".").lower()

            results.append({
                "file_name": file_name,
                "file_path": file_path,
                "file_type": doc_type,
                "cached_at": cached_at,
                "items": total_items,
                "characters": total_chars,
                "file_exists": file_exists,
                "cache_file": os.path.basename(c_path),
                "cache_size_bytes": cache_file_size
            })
        except Exception:
            continue

    return results
