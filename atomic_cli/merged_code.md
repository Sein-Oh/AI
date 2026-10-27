# atomic_cli 소스 코드 (루트 폴더만, 하위 폴더 제외)

생성일: 2026-10-27
총 파일 수: 34

---

=== FILE: _cache.py ===

```python
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
            delete_snapshot_files(old_json)
            log_debug(f"오래된 스냅샷 자동 회전 삭제 (최근 {max_keep}개 유지 정책): {os.path.basename(old_json)}")
        except Exception as e:
            log_debug(f"오래된 스냅샷 삭제 실패: {e}")

def delete_snapshot_files(meta_json_path: str) -> None:
    """스냅샷 메타 JSON과 같은 이름의 데이터 파일(확장자 무관)을 모두 삭제합니다."""
    base_no_ext = os.path.splitext(meta_json_path)[0]
    for data_file in glob.glob(glob.escape(base_no_ext) + ".*"):
        if data_file != meta_json_path and os.path.exists(data_file):
            os.remove(data_file)
    if os.path.exists(meta_json_path):
        os.remove(meta_json_path)

_DEFAULT_SNAPSHOT_EXT = {"excel": ".xlsx", "word": ".docx", "ppt": ".pptx"}

def save_document_snapshot(app_name: str, doc_obj: Any, max_keep: int = 2) -> Optional[str]:
    """오피스 문서의 현재 상태를 캐시 디렉터리에 스냅샷으로 저장합니다 (최근 2개 유지).

    원본 문서는 저장하거나 경로를 바꾸지 않습니다.
    - Excel/PowerPoint: SaveCopyAs (원본 형식 그대로 사본 저장, 원본 확장자 유지)
    - Word: 저장 이후 변경이 없으면 디스크 파일 복사, 미저장 변경이 있거나 새 문서이면
      WordOpenXML(Flat OPC .xml)로 현재 메모리 상태를 그대로 기록합니다.
    """
    if doc_obj is None:
        return None

    try:
        cache_dir = get_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        app_lower = app_name.lower()

        # 1. 문서 식별자(이름/경로) 추출
        doc_name = {"excel": "Workbook", "word": "Document"}.get(app_lower, "Presentation")
        doc_path = ""
        try:
            doc_name = doc_obj.Name
            full_name = str(doc_obj.FullName)
            doc_path = full_name if os.path.isabs(full_name) else ""
        except Exception:
            pass

        # SaveCopyAs는 원본 형식으로 저장하므로 확장자도 원본을 따름 (.xlsm/.xls 등 불일치 방지)
        ext = (os.path.splitext(doc_path)[1].lower() if doc_path else "") or _DEFAULT_SNAPSHOT_EXT.get(app_lower, ".bin")

        # doc_key는 이름과 경로를 기반으로 한 8자리 안정적 고유 해시
        raw_key = (doc_path or doc_name).lower()
        doc_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        base_name = f"snapshot_{app_lower}_{doc_key}_{timestamp}"
        snapshot_meta_path = os.path.join(cache_dir, f"{base_name}.json").replace("\\", "/")

        # 2. 애플리케이션별 스냅샷 생성
        snapshot_data_path = ""
        snapshot_format = "native"
        if app_lower in ("excel", "ppt"):
            snapshot_data_path = os.path.join(cache_dir, f"{base_name}{ext}").replace("\\", "/")
            try:
                doc_obj.SaveCopyAs(os.path.normpath(snapshot_data_path))
            except Exception as e:
                log_debug(f"{app_lower} SaveCopyAs 실패: {e}")
        elif app_lower == "word":
            is_saved = bool(getattr(doc_obj, "Saved", False))
            if doc_path and os.path.exists(doc_path) and is_saved:
                import shutil
                snapshot_data_path = os.path.join(cache_dir, f"{base_name}{ext}").replace("\\", "/")
                try:
                    shutil.copy2(doc_path, snapshot_data_path)
                except Exception as e:
                    log_debug(f"Word 스냅샷 파일 복사 실패: {e}")
            else:
                snapshot_data_path = os.path.join(cache_dir, f"{base_name}.xml").replace("\\", "/")
                snapshot_format = "flat_xml"
                try:
                    xml_text = doc_obj.WordOpenXML
                    with open(snapshot_data_path, "w", encoding="utf-8") as f:
                        f.write(xml_text)
                except Exception as e:
                    log_debug(f"Word WordOpenXML 스냅샷 실패: {e}")

        if not snapshot_data_path or not os.path.exists(snapshot_data_path):
            return None

        # 3. 메타데이터 JSON 저장
        meta_payload = {
            "app": app_lower,
            "name": doc_name,
            "original_path": doc_path,
            "snapshot_file": snapshot_data_path,
            "snapshot_format": snapshot_format,
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
                data["meta_file"] = mf
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
```

=== END FILE: _cache.py ===

---

=== FILE: _com_guard.py ===

```python
import os
import sys
from contextlib import contextmanager
from typing import Generator, Optional, Tuple, Any, List, Dict

# 최우선: 샌드박스 가상 데스크톱(exebox-*) 환경에서 실제 사용자 GUI 데스크톱(Default)으로 최우선 바인딩
def attach_user_desktop():
    """샌드박스 가상 데스크톱(exebox-*) 환경인 경우 사용자의 실제 GUI 데스크톱(Default)으로 스레드 데스크톱을 전환합니다."""
    try:
        import ctypes
        import win32service
        import win32con
        hdesk = win32service.OpenDesktop("Default", 0, False, win32con.MAXIMUM_ALLOWED)
        if hdesk:
            ctypes.windll.user32.SetThreadDesktop(int(hdesk))
    except Exception:
        pass

attach_user_desktop()

# 최우선: 상위 디렉터리 경로 등록 및 COM 환경 초기화
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
for p in [CURRENT_DIR, PARENT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import pythoncom
    import win32com.client
    import win32gui
except ImportError:
    pythoncom = None
    win32com = None
    win32gui = None

from _office_utils import log_debug

def init_com():
    """COM 스레드 아파트먼트 초기화 (pythoncom) 및 실제 사용자 GUI 데스크톱 바인딩"""
    attach_user_desktop()
    if pythoncom is not None:
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass

def jit_repair_office_environment(app_name: str = "excel") -> Dict[str, Any]:
    """COM 이상/충돌/RPC 중단 발생 시 호출되는 실시간(JIT) 자가복구 루틴.
    사용자의 작업 창이나 실행 중인 프로세스는 절대 종료하지 않습니다.
    살아있는 COM 참조가 있는 상태에서 CoUninitialize를 호출하면 프로세스가 비정상 종료될 수 있으므로,
    아파트먼트는 재초기화하지 않고 Office가 응답 가능한 상태로 돌아올 때까지 잠시 대기한 뒤 재바인딩하도록 합니다.
    """
    log_debug(f"[JIT 자가복구] {app_name.upper()} 응답 대기 후 재바인딩 시도")
    init_com()
    import time
    time.sleep(0.5)
    return {"status": "recovered", "killed": []}

class COMError(Exception):
    """Office COM 작업 중 발생하는 예외"""
    pass

def _get_active_or_first_wb(app):
    """Excel Application에서 활성 문서 또는 1번 문서를 안전하게 획득합니다 (임의로 신규 문서를 생성하지 않음)."""
    try:
        if app.ActiveWorkbook:
            return app.ActiveWorkbook
    except Exception:
        pass
    try:
        if hasattr(app, "Workbooks") and app.Workbooks.Count > 0:
            return app.Workbooks(1)
    except Exception:
        pass
    return None

def _get_active_or_first_doc(app):
    """Word Application에서 활성 문서 또는 1번 문서를 안전하게 획득합니다 (임의로 신규 문서를 생성하지 않음)."""
    try:
        if app.ActiveDocument:
            return app.ActiveDocument
    except Exception:
        pass
    try:
        if hasattr(app, "Documents") and app.Documents.Count > 0:
            return app.Documents(1)
    except Exception:
        pass
    return None

def _get_active_or_first_prs(app):
    """PowerPoint Application에서 활성 문서 또는 1번 문서를 안전하게 획득합니다 (임의로 신규 문서를 생성하지 않음)."""
    try:
        if app.ActivePresentation:
            return app.ActivePresentation
    except Exception:
        pass
    try:
        if hasattr(app, "Presentations") and app.Presentations.Count > 0:
            return app.Presentations(1)
    except Exception:
        pass
    return None

def _extract_dispatch_from_hwnd(hwnd: int) -> Optional[Any]:
    """HWND로부터 oleacc AccessibleObjectFromWindow를 통해 IDispatch COM 객체를 추출합니다."""
    try:
        import ctypes
        oleacc = ctypes.windll.oleacc
        p_acc = ctypes.c_void_p()
        riid = ctypes.create_string_buffer(bytes(pythoncom.IID_IDispatch))
        res = oleacc.AccessibleObjectFromWindow(hwnd, 0xFFFFFFF0, riid, ctypes.byref(p_acc))
        if res == 0 and p_acc.value:
            py_obj = pythoncom.ObjectFromAddress(p_acc.value, pythoncom.IID_IDispatch)
            return win32com.client.Dispatch(py_obj)
    except Exception:
        pass
    return None

def _list_child_windows(parent_hwnd: int, class_name: str) -> List[int]:
    """부모 창 아래에서 지정 클래스명을 가진 자식 창 핸들을 모두 수집합니다.
    EnumChildWindows 콜백이 False를 반환하면 pywin32가 예외를 던질 수 있으므로 항상 True를 반환합니다.
    """
    found: List[int] = []

    def _cb(hwnd, _):
        try:
            if win32gui.GetClassName(hwnd) == class_name:
                found.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumChildWindows(parent_hwnd, _cb, None)
    except Exception:
        pass
    return found

def _list_top_windows(match_fn) -> List[int]:
    """최상위 창 중 match_fn(class_name)이 True인 창 핸들을 모두 수집합니다."""
    found: List[int] = []

    def _cb(hwnd, _):
        try:
            if match_fn(win32gui.GetClassName(hwnd)):
                found.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    return found

def _get_window_pid(hwnd: int) -> Optional[int]:
    try:
        import win32process
        return win32process.GetWindowThreadProcessId(hwnd)[1]
    except Exception:
        return None

def _app_from_frame(frame_hwnd: int, doc_class: str) -> Optional[Any]:
    """최상위 프레임 창에서 문서 창(EXCEL7/_WwG/paneClassDC)을 찾아 Application COM 객체를 추출합니다."""
    for child in _list_child_windows(frame_hwnd, doc_class):
        disp = _extract_dispatch_from_hwnd(child)
        if disp:
            try:
                app = getattr(disp, "Application", None)
                if app:
                    return app
            except Exception:
                continue
    return None

# 앱 종류별 (ProgID, 최상위 프레임 클래스 판정, 문서 창 클래스)
_APP_WINDOW_SPECS = {
    "excel": ("Excel.Application", lambda c: c == "XLMAIN", "EXCEL7"),
    "word": ("Word.Application", lambda c: c == "OpusApp", "_WwG"),
    "ppt": ("PowerPoint.Application", lambda c: c == "PPTFrameClass" or ("PP" in c and "Frame" in c), "paneClassDC"),
}

def _find_all_native_apps(app_kind: str) -> List[Any]:
    """실행 중인 모든 Office Application 인스턴스를 프로세스 단위로 중복 없이 수집합니다 (Native oleacc 우선)."""
    init_com()
    prog_id, frame_match, doc_class = _APP_WINDOW_SPECS[app_kind]
    apps: List[Any] = []

    if win32gui is not None:
        seen_pids = set()
        for frame in _list_top_windows(frame_match):
            pid = _get_window_pid(frame)
            if pid is not None and pid in seen_pids:
                continue
            app = _app_from_frame(frame, doc_class)
            if app:
                apps.append(app)
                if pid is not None:
                    seen_pids.add(pid)

    if not apps:
        try:
            active_app = win32com.client.GetActiveObject(prog_id)
            if active_app:
                apps.append(active_app)
        except Exception:
            pass

    return apps

def find_all_native_excel_apps() -> List[Any]:
    """실행 중인 모든 Excel.Application 인스턴스 탐색 (다중 프로세스 지원)"""
    return _find_all_native_apps("excel")

def find_all_native_word_apps() -> List[Any]:
    """실행 중인 모든 Word.Application 인스턴스 탐색"""
    return _find_all_native_apps("word")

def find_all_native_ppt_apps() -> List[Any]:
    """실행 중인 모든 PowerPoint.Application 인스턴스 탐색"""
    return _find_all_native_apps("ppt")

def _find_sheet(wb, sheet_name: str) -> Optional[Any]:
    """시트명을 대소문자 구분 없이 찾습니다 (Excel 자체 규칙과 동일)."""
    target = str(sheet_name).strip().lower()
    try:
        for s in wb.Worksheets:
            if str(s.Name).strip().lower() == target:
                return s
    except Exception:
        pass
    return None

def _resolve_sheet(wb, sheet_name: str, readonly: bool) -> Any:
    """시트를 찾고, 쓰기 모드에서만 없는 시트를 새로 생성합니다."""
    ws = _find_sheet(wb, sheet_name)
    if ws is not None:
        return ws
    if readonly:
        try:
            names = [s.Name for s in wb.Worksheets]
        except Exception:
            names = []
        raise COMError(f"시트 '{sheet_name}'을(를) 찾을 수 없습니다. 존재하는 시트: {names}")
    log_debug(f"시트 '{sheet_name}' 신규 생성")
    ws = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
    ws.Name = sheet_name
    return ws

# 확장자별 저장 형식 (신규 파일 생성 시 확장자와 실제 형식 불일치 방지)
XL_FILE_FORMATS = {".xlsx": 51, ".xlsm": 52, ".xlsb": 50, ".xls": 56}
WD_FILE_FORMATS = {".docx": 16, ".docm": 13, ".doc": 0, ".rtf": 6, ".txt": 2}
PP_FILE_FORMATS = {".pptx": 24, ".pptm": 25, ".ppt": 1}

def _file_format_for(path: str, mapping: Dict[str, int]) -> Optional[int]:
    return mapping.get(os.path.splitext(path)[1].lower())

def get_all_running_excel_workbooks() -> List[Dict[str, Any]]:
    """실행 중인 모든 Excel 프로세스(다중 창/다중 프로세스)에서 열려 있는 모든 통합 문서를 수집합니다."""
    init_com()
    workbooks_info = []
    seen_wb_keys = set()

    try:
        apps = find_all_native_excel_apps()
        for app in apps:
            try:
                active_wb_name = ""
                try:
                    if app.ActiveWorkbook:
                        active_wb_name = app.ActiveWorkbook.Name
                except Exception:
                    pass
                for wb in app.Workbooks:
                    try:
                        wb_name = wb.Name
                        wb_path = getattr(wb, "FullName", "")
                        wb_key = (wb_name, wb_path)
                        if wb_key in seen_wb_keys:
                            continue
                        seen_wb_keys.add(wb_key)

                        sheets = [s.Name for s in wb.Worksheets]
                        workbooks_info.append({
                            "app": app,
                            "wb": wb,
                            "name": wb_name,
                            "path": wb_path,
                            "saved": getattr(wb, "Saved", True),
                            "sheets": sheets,
                            "is_active": (wb_name == active_wb_name)
                        })
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception as e:
        log_debug(f"get_all_running_excel_workbooks 예외: {e}")

    # 폴백: GetActiveObject 및 Dispatch
    if not workbooks_info:
        for method in [win32com.client.GetActiveObject]:  # 목록 조회가 새 Office 프로세스를 띄우지 않도록 Dispatch 배제
            try:
                app = method("Excel.Application")
                if app and hasattr(app, "Workbooks") and app.Workbooks.Count > 0:
                    for wb in app.Workbooks:
                        workbooks_info.append({
                            "app": app,
                            "wb": wb,
                            "name": wb.Name,
                            "path": getattr(wb, "FullName", ""),
                            "saved": getattr(wb, "Saved", True),
                            "sheets": [s.Name for s in wb.Worksheets],
                            "is_active": True
                        })
                    if workbooks_info:
                        break
            except Exception:
                pass

    return workbooks_info

def get_active_excel_app_and_wb(enable_jit: bool = True):
    """화면에 실제 떠 있는 사용자의 Excel 창과 통합 문서를 100% 신뢰도로 바인딩합니다."""
    log_debug("get_active_excel_app_and_wb 진입")
    init_com()

    # 1. 포커스된 최상단 창 우선 검사
    try:
        if win32gui is not None:
            fg_hwnd = win32gui.GetForegroundWindow()
            if fg_hwnd and win32gui.GetClassName(fg_hwnd) == "XLMAIN":
                app_found = _app_from_frame(fg_hwnd, "EXCEL7")
                if app_found and getattr(app_found, "ActiveWorkbook", None):
                    log_debug("Foreground Excel 창 바인딩 성공")
                    return app_found, app_found.ActiveWorkbook
    except Exception as e:
        log_debug(f"Foreground Excel 검사 예외: {e}")

    # 2. find_all_native_excel_apps 순회
    try:
        apps = find_all_native_excel_apps()
        for app in apps:
            try:
                if app.ActiveWorkbook:
                    log_debug(f"Native Excel 인스턴스 및 통합 문서 바인딩 성공: {app.ActiveWorkbook.Name}")
                    return app, app.ActiveWorkbook
            except Exception:
                continue
    except Exception as e:
        log_debug(f"find_all_native_excel_apps 예외: {e}")

    # 3. GetActiveObject 폴백 (이미 실행 중인 인스턴스만 바인딩, 새 창을 띄우는 Dispatch는 배제)
    try:
        app = win32com.client.GetActiveObject("Excel.Application")
        if app:
            wb = _get_active_or_first_wb(app)
            if wb:
                log_debug("Excel 활성 통합 문서 바인딩 성공")
                return app, wb
    except Exception:
        pass

    if enable_jit:
        log_debug("[JIT 자가복구] 활성 Excel 탐색 실패 -> JIT 복구 가동 후 재시도")
        jit_repair_office_environment("excel")
        return get_active_excel_app_and_wb(enable_jit=False)
    raise COMError("화면에 열려 있는 활성 Excel 창이나 통합 문서를 찾을 수 없습니다.")

def _match_running_item(items: List[Dict[str, Any]], target: str) -> Optional[Dict[str, Any]]:
    """실행 중인 문서 목록에서 이름/파일명/절대경로가 target과 일치하는 항목을 찾습니다."""
    target_clean = target.strip().lower()
    target_abs_lower = os.path.abspath(target).lower()
    for item in items:
        name_lower = str(item["name"]).lower()
        path_lower = str(item["path"]).lower() if item["path"] else ""
        if (target_clean == name_lower or
                target_clean == os.path.basename(path_lower) or
                target_abs_lower == path_lower):
            return item
    return None

def _release_com():
    import gc
    gc.collect()
    if pythoncom is not None:
        try:
            pythoncom.CoFreeUnusedLibraries()
        except Exception:
            pass

@contextmanager
def excel_session(
    target: str = "active",
    sheet_name: Optional[str] = None,
    snapshot: bool = False,
    readonly: Optional[bool] = None
) -> Generator[Tuple[Any, Any, Any], None, None]:
    """Excel COM 생명주기를 완벽하게 격리하고 관리하는 Context Manager.

    Args:
        target: "active", 실행 중인 통합 문서 이름, 또는 디스크 파일 경로
        sheet_name: 대상 시트명 (대소문자 무시)
        snapshot: 쓰기 작업 전 자동 스냅샷 생성 여부
        readonly: 읽기 전용 세션 여부. 생략 시 snapshot=False이면 읽기 전용으로 간주합니다.
            읽기 전용 세션은 시트/파일을 새로 만들지 않고, 디스크 파일을 저장하지 않으며, 사용자 화면(활성 시트/스크롤)을 바꾸지 않습니다.

    Yields:
        (app, wb, ws): Excel Application, Workbook, Worksheet COM 객체
    """
    if win32com is None:
        raise COMError("pywin32가 설치되어 있지 않습니다. (pip install pywin32 필요)")

    if readonly is None:
        readonly = not snapshot

    app = None
    wb = None
    ws = None
    owns_app = False   # 이 세션이 직접 띄운 백그라운드 Excel 인스턴스인지 여부
    owns_wb = False    # 이 세션이 직접 연 통합 문서인지 여부 (사용자가 열어둔 문서는 닫지 않음)
    is_active_target = (target.strip().lower() == "active")

    try:
        matched_running_wb = None
        if not is_active_target:
            matched_running_wb = _match_running_item(get_all_running_excel_workbooks(), target)
            if matched_running_wb:
                log_debug(f"실행 중인 Excel 인스턴스에서 대상 문서 발견: {matched_running_wb['name']}")

        if is_active_target or matched_running_wb:
            if matched_running_wb:
                app = matched_running_wb["app"]
                wb = matched_running_wb["wb"]
            else:
                app, wb = get_active_excel_app_and_wb()
                if wb is None:
                    raise COMError("활성 Excel 창에 열린 통합 문서(Workbook)가 없습니다.")

            app = win32com.client.Dispatch(app)
            wb = win32com.client.Dispatch(wb)

            if not readonly:
                try:
                    app.Visible = True
                    app.ScreenUpdating = True
                except Exception:
                    pass

            if sheet_name:
                ws = _resolve_sheet(wb, sheet_name, readonly)
                if not readonly:
                    try:
                        ws.Activate()
                    except Exception:
                        pass
            else:
                try:
                    ws = wb.ActiveSheet
                except Exception:
                    ws = wb.Worksheets(1)
        else:
            abs_path = os.path.abspath(target)
            file_exists = os.path.exists(abs_path)
            if not file_exists and readonly:
                raise COMError(f"대상 Excel 파일이 존재하지 않습니다: {abs_path}")

            # 사용자가 띄워 둔 Excel 인스턴스에 붙어 창을 숨기는 일이 없도록 전용 인스턴스를 생성
            try:
                app = win32com.client.DispatchEx("Excel.Application")
            except Exception as e:
                log_debug(f"[JIT 자가복구] Excel.Application 생성 실패 ({e}) -> JIT 복구 후 재시도")
                jit_repair_office_environment("excel")
                app = win32com.client.DispatchEx("Excel.Application")
            owns_app = True
            app.Visible = False
            app.DisplayAlerts = False
            try:
                app.AskToUpdateLinks = False
            except Exception:
                pass

            if file_exists:
                log_debug(f"Excel 파일 백그라운드 오픈 (readonly={readonly}): {abs_path}")
                try:
                    wb = app.Workbooks.Open(abs_path, UpdateLinks=0, ReadOnly=readonly, AddToMru=False)
                except Exception as e:
                    log_debug(f"[JIT 자가복구] Workbooks.Open 실패 ({e}) -> JIT 복구 후 1회 재시도")
                    jit_repair_office_environment("excel")
                    wb = app.Workbooks.Open(abs_path, UpdateLinks=0, ReadOnly=readonly, AddToMru=False)
            else:
                log_debug(f"Excel 신규 파일 백그라운드 생성: {abs_path}")
                wb = app.Workbooks.Add()
                fmt = _file_format_for(abs_path, XL_FILE_FORMATS)
                if fmt is not None:
                    wb.SaveAs(abs_path, FileFormat=fmt)
                else:
                    wb.SaveAs(abs_path)
            owns_wb = True

            if sheet_name:
                ws = _resolve_sheet(wb, sheet_name, readonly)
            else:
                ws = wb.Worksheets(1)

        # 쓰기 작업 전 자동 캐시 스냅샷 (최근 2개 유지)
        if snapshot and wb is not None:
            try:
                from _cache import save_document_snapshot
                save_document_snapshot("excel", wb)
            except Exception as e:
                log_debug(f"Excel 자동 스냅샷 예외: {e}")

        yield app, wb, ws

        # 화면 시선 동기화 (Visual Focus Sync): 쓰기 작업 후 사용자 창의 활성 시트만 갱신
        if not owns_wb and not readonly and ws is not None:
            try:
                ws.Activate()
            except Exception:
                pass

        # 정상 종료 시 처리 (이 세션이 연 파일만 저장 및 닫기)
        if owns_wb and wb is not None:
            try:
                if not readonly and not getattr(wb, "Saved", True):
                    log_debug("작업 완료: 변경사항 저장")
                    wb.Save()
                else:
                    log_debug("작업 완료: 저장 생략 (읽기 전용 또는 변경사항 없음)")
            finally:
                try:
                    wb.Close(SaveChanges=False)
                except Exception:
                    pass
                wb = None

    except Exception:
        if owns_wb and wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
            wb = None
        raise

    finally:
        # 이 세션이 띄운 전용 인스턴스는 항상 종료 (유령 EXCEL.EXE 방지)
        if owns_app and app is not None:
            try:
                for i in range(app.Workbooks.Count, 0, -1):
                    try:
                        app.Workbooks(i).Close(SaveChanges=False)
                    except Exception:
                        pass
                app.Quit()
            except Exception:
                pass
        ws = None
        wb = None
        app = None
        _release_com()
        log_debug("Excel COM 세션 정상 종료 및 메모리 정리 완료")

def get_all_running_word_documents() -> List[Dict[str, Any]]:
    """실행 중인 모든 Word 프로세스/창에서 열려 있는 모든 문서를 수집합니다."""
    init_com()
    docs_info = []
    apps = find_all_native_word_apps()
    if not apps:
        for method in [win32com.client.GetActiveObject]:  # 목록 조회가 새 Office 프로세스를 띄우지 않도록 Dispatch 배제
            try:
                app_inst = method("Word.Application")
                if app_inst and hasattr(app_inst, "Documents") and app_inst.Documents.Count > 0:
                    apps.append(app_inst)
                    break
            except Exception:
                pass

    seen_doc_names = set()
    for app in apps:
        try:
            active_doc_name = ""
            try:
                if app.ActiveDocument:
                    active_doc_name = app.ActiveDocument.Name
            except Exception:
                pass
            for doc in app.Documents:
                try:
                    name = doc.Name
                    full_name = getattr(doc, "FullName", "") or name
                    # 이름이 같고 폴더가 다른 문서가 누락되지 않도록 전체 경로 기준으로 중복 제거
                    if full_name.lower() in seen_doc_names:
                        continue
                    seen_doc_names.add(full_name.lower())
                    docs_info.append({
                        "app": app,
                        "doc": doc,
                        "name": name,
                        "path": getattr(doc, "FullName", ""),
                        "saved": getattr(doc, "Saved", True),
                        "is_active": (name == active_doc_name)
                    })
                except Exception:
                    continue
        except Exception:
            continue

    return docs_info

def get_active_word_app_and_doc(enable_jit: bool = True):
    """화면에 실제 떠 있는 사용자의 Word 창과 문서를 100% 신뢰도로 바인딩합니다."""
    init_com()

    # 1. Native GUI 창 우선 바인딩
    try:
        apps = find_all_native_word_apps()
        for app in apps:
            doc = _get_active_or_first_doc(app)
            if doc:
                log_debug(f"Native Word 창 바인딩 성공: {doc.Name}")
                return app, doc
    except Exception as e:
        log_debug(f"find_all_native_word_apps 예외: {e}")

    # 2. GetActiveObject 폴백 (이미 실행 중인 인스턴스만 바인딩, 새 창을 띄우는 Dispatch는 배제)
    try:
        app = win32com.client.GetActiveObject("Word.Application")
        if app:
            doc = _get_active_or_first_doc(app)
            if doc:
                log_debug("Word 활성 문서 바인딩 성공!")
                return app, doc
    except Exception:
        pass

    if enable_jit:
        log_debug("[JIT 자가복구] 활성 Word 바인딩 실패 -> JIT 복구 가동 후 재시도")
        jit_repair_office_environment("word")
        return get_active_word_app_and_doc(enable_jit=False)
    raise COMError("화면에 열려 있는 활성 Word 창이나 문서를 찾을 수 없습니다.")

@contextmanager
def word_session(
    target: str = "active",
    snapshot: bool = False,
    readonly: Optional[bool] = None
) -> Generator[Tuple[Any, Any], None, None]:
    """Word COM 생명주기를 완벽하게 격리하고 관리하는 Context Manager.

    readonly 생략 시 snapshot=False이면 읽기 전용으로 간주합니다.
    읽기 전용 세션은 존재하지 않는 파일을 새로 만들지 않고, 디스크 파일을 저장하지 않습니다.
    """
    if win32com is None:
        raise COMError("pywin32가 설치되어 있지 않습니다.")

    if readonly is None:
        readonly = not snapshot

    app = None
    doc = None
    owns_app = False
    owns_doc = False
    is_active_target = (target.strip().lower() == "active")

    try:
        matched_running_doc = None
        if not is_active_target:
            all_running = get_all_running_word_documents()
            log_debug(f"Word 검색: target='{target}', 열린 문서 수={len(all_running)}, 목록={[i['name'] for i in all_running]}")
            matched_running_doc = _match_running_item(all_running, target)
            if matched_running_doc:
                log_debug(f"실행 중인 Word 인스턴스에서 대상 문서 발견: {matched_running_doc['name']}")

        if is_active_target or matched_running_doc:
            if matched_running_doc:
                app = matched_running_doc["app"]
                doc = matched_running_doc["doc"]
            else:
                app, doc = get_active_word_app_and_doc()
                if doc is None:
                    raise COMError("활성 Word 창에 열린 문서(Document)가 없습니다.")

            app = win32com.client.Dispatch(app)
            doc = win32com.client.Dispatch(doc)
            if not readonly:
                try:
                    app.Visible = True
                    app.ScreenUpdating = True
                except Exception:
                    pass
        else:
            abs_path = os.path.abspath(target)
            file_exists = os.path.exists(abs_path)
            if not file_exists and readonly:
                raise COMError(f"대상 Word 파일이 존재하지 않습니다: {abs_path}")

            # 사용자가 띄워 둔 Word 인스턴스에 붙어 창을 숨기는 일이 없도록 전용 인스턴스를 생성
            try:
                app = win32com.client.DispatchEx("Word.Application")
            except Exception as e:
                log_debug(f"[JIT 자가복구] Word.Application 생성 실패 ({e}) -> JIT 복구 후 재시도")
                jit_repair_office_environment("word")
                app = win32com.client.DispatchEx("Word.Application")
            owns_app = True
            app.Visible = False
            app.DisplayAlerts = 0  # wdAlertsNone

            if file_exists:
                log_debug(f"Word 파일 백그라운드 오픈 (readonly={readonly}): {abs_path}")
                doc = app.Documents.Open(abs_path, ConfirmConversions=False, ReadOnly=readonly, AddToRecentFiles=False)
            else:
                log_debug(f"Word 신규 문서 백그라운드 생성: {abs_path}")
                doc = app.Documents.Add()
                fmt = _file_format_for(abs_path, WD_FILE_FORMATS)
                if fmt is not None:
                    doc.SaveAs2(abs_path, FileFormat=fmt)
                else:
                    doc.SaveAs2(abs_path)
            owns_doc = True

        # 쓰기 작업 전 자동 캐시 스냅샷 (최근 2개 유지)
        if snapshot and doc is not None:
            try:
                from _cache import save_document_snapshot
                save_document_snapshot("word", doc)
            except Exception as e:
                log_debug(f"Word 자동 스냅샷 예외: {e}")

        yield app, doc

        # 화면 시선 동기화 (Visual Focus Sync): 쓰기 작업 후 사용자 문서 포커스
        if not owns_doc and not readonly and doc is not None:
            try:
                doc.Activate()
            except Exception:
                pass

        if owns_doc and doc is not None:
            try:
                if not readonly and not getattr(doc, "Saved", True):
                    log_debug("Word 변경사항 저장")
                    doc.Save()
            finally:
                try:
                    doc.Close(SaveChanges=0)  # wdDoNotSaveChanges
                except Exception:
                    pass
                doc = None

    except Exception:
        if owns_doc and doc is not None:
            try:
                doc.Close(SaveChanges=0)
            except Exception:
                pass
            doc = None
        raise

    finally:
        if owns_app and app is not None:
            try:
                app.Quit(SaveChanges=0)
            except Exception:
                pass
        doc = None
        app = None
        _release_com()
        log_debug("Word COM 세션 정상 종료 완료")

def get_all_running_ppt_presentations() -> List[Dict[str, Any]]:
    """실행 중인 모든 PowerPoint 프로세스/창에서 열려 있는 모든 프레젠테이션을 수집합니다."""
    init_com()
    prs_info = []
    apps = find_all_native_ppt_apps()
    if not apps:
        for method in [win32com.client.GetActiveObject]:  # 목록 조회가 새 Office 프로세스를 띄우지 않도록 Dispatch 배제
            try:
                app_inst = method("PowerPoint.Application")
                if app_inst and hasattr(app_inst, "Presentations") and app_inst.Presentations.Count > 0:
                    apps.append(app_inst)
                    break
            except Exception:
                pass

    seen_prs_names = set()
    for app in apps:
        try:
            active_prs_name = ""
            try:
                if app.ActivePresentation:
                    active_prs_name = app.ActivePresentation.Name
            except Exception:
                pass
            for prs in app.Presentations:
                try:
                    name = prs.Name
                    full_name = getattr(prs, "FullName", "") or name
                    if full_name.lower() in seen_prs_names:
                        continue
                    seen_prs_names.add(full_name.lower())
                    prs_info.append({
                        "app": app,
                        "prs": prs,
                        "name": name,
                        "path": getattr(prs, "FullName", ""),
                        "saved": getattr(prs, "Saved", True),
                        "slides_count": prs.Slides.Count,
                        "is_active": (name == active_prs_name)
                    })
                except Exception:
                    continue
        except Exception:
            continue

    return prs_info

def get_active_ppt_app_and_prs(enable_jit: bool = True):
    """화면에 실제 떠 있는 사용자의 PowerPoint 창과 프레젠테이션을 100% 신뢰도로 바인딩합니다."""
    init_com()

    # 1. Native GUI 창 우선 바인딩
    try:
        apps = find_all_native_ppt_apps()
        for app in apps:
            prs = _get_active_or_first_prs(app)
            if prs:
                log_debug(f"Native PowerPoint 창 바인딩 성공: {prs.Name}")
                return app, prs
    except Exception as e:
        log_debug(f"find_all_native_ppt_apps 예외: {e}")

    # 2. GetActiveObject 폴백 (이미 실행 중인 인스턴스만 바인딩, 새 창을 띄우는 Dispatch는 배제)
    try:
        app = win32com.client.GetActiveObject("PowerPoint.Application")
        if app:
            prs = _get_active_or_first_prs(app)
            if prs:
                log_debug("PowerPoint 활성 프레젠테이션 바인딩 성공!")
                return app, prs
    except Exception:
        pass

    if enable_jit:
        log_debug("[JIT 자가복구] 활성 PowerPoint 바인딩 실패 -> JIT 복구 가동 후 재시도")
        jit_repair_office_environment("ppt")
        return get_active_ppt_app_and_prs(enable_jit=False)
    raise COMError("화면에 열려 있는 활성 PowerPoint 창이나 프레젠테이션을 찾을 수 없습니다.")

@contextmanager
def ppt_session(
    target: str = "active",
    snapshot: bool = False,
    readonly: Optional[bool] = None
) -> Generator[Tuple[Any, Any], None, None]:
    """PowerPoint COM 생명주기를 완벽하게 격리하고 관리하는 Context Manager.

    PowerPoint는 단일 인스턴스 앱이라 전용 인스턴스를 만들 수 없으므로,
    사용자가 이미 띄워 둔 PowerPoint의 창 상태(Visible/WindowState)는 절대 바꾸지 않고
    대상 파일만 창 없이(WithWindow=False) 열어 작업합니다.
    readonly 생략 시 snapshot=False이면 읽기 전용으로 간주합니다.
    """
    if win32com is None:
        raise COMError("pywin32가 설치되어 있지 않습니다.")

    if readonly is None:
        readonly = not snapshot

    app = None
    prs = None
    owns_app = False
    owns_prs = False
    orig_alerts = None
    abs_path = ""
    is_active_target = (target.strip().lower() == "active")

    try:
        matched_running_prs = None
        if not is_active_target:
            matched_running_prs = _match_running_item(get_all_running_ppt_presentations(), target)
            if matched_running_prs:
                log_debug(f"실행 중인 PowerPoint 인스턴스에서 대상 문서 발견: {matched_running_prs['name']}")

        if is_active_target or matched_running_prs:
            if matched_running_prs:
                app = matched_running_prs["app"]
                prs = matched_running_prs["prs"]
            else:
                app, prs = get_active_ppt_app_and_prs()
                if prs is None:
                    raise COMError("활성 PowerPoint 창에 열린 프레젠테이션이 없습니다.")

            app = win32com.client.Dispatch(app)
            prs = win32com.client.Dispatch(prs)
        else:
            abs_path = os.path.abspath(target)
            file_exists = os.path.exists(abs_path)
            if not file_exists and readonly:
                raise COMError(f"대상 PowerPoint 파일이 존재하지 않습니다: {abs_path}")

            already_running = False
            try:
                win32com.client.GetActiveObject("PowerPoint.Application")
                already_running = True
            except Exception:
                pass
            try:
                app = win32com.client.Dispatch("PowerPoint.Application")
            except Exception as e:
                log_debug(f"[JIT 자가복구] PowerPoint.Application 생성 실패 ({e}) -> JIT 복구 가동")
                jit_repair_office_environment("ppt")
                app = win32com.client.Dispatch("PowerPoint.Application")
            owns_app = not already_running

            try:
                orig_alerts = app.DisplayAlerts
                app.DisplayAlerts = 1  # ppAlertsNone
            except Exception:
                orig_alerts = None

            if file_exists:
                log_debug(f"PowerPoint 파일 창 없이 오픈 (readonly={readonly}): {abs_path}")
                ms_readonly = -1 if readonly else 0  # msoTrue / msoFalse
                try:
                    prs = app.Presentations.Open(abs_path, ms_readonly, 0, 0)
                except Exception:
                    prs = app.Presentations.Open(abs_path, ms_readonly)
            else:
                log_debug(f"PowerPoint 신규 파일 생성: {abs_path}")
                try:
                    prs = app.Presentations.Add(0)  # WithWindow=msoFalse
                except Exception:
                    prs = app.Presentations.Add()
                fmt = _file_format_for(abs_path, PP_FILE_FORMATS)
                if fmt is not None:
                    prs.SaveAs(abs_path, fmt)
                else:
                    prs.SaveAs(abs_path)
            owns_prs = True

        # 쓰기 작업 전 자동 캐시 스냅샷 (활성/파일 모드 공통, 최근 2개 유지)
        if snapshot and prs is not None:
            try:
                from _cache import save_document_snapshot
                save_document_snapshot("ppt", prs)
            except Exception as e:
                log_debug(f"PPT 자동 스냅샷 예외: {e}")

        yield app, prs

        # 화면 시선 동기화 (Visual Focus Sync): 쓰기 작업 후에만 사용자 화면을 마지막 슬라이드로 이동
        if not owns_prs and not readonly and prs is not None and app is not None:
            try:
                if getattr(app, "ActiveWindow", None):
                    view = getattr(app.ActiveWindow, "View", None)
                    if view and hasattr(view, "GotoSlide") and getattr(prs, "Slides", None) and prs.Slides.Count > 0:
                        view.GotoSlide(prs.Slides.Count)
            except Exception:
                pass

        if owns_prs and prs is not None:
            try:
                if not readonly and not getattr(prs, "Saved", True):
                    log_debug(f"PowerPoint 변경사항 저장: {abs_path}")
                    prs.Save()
            finally:
                try:
                    prs.Close()
                except Exception as e_close:
                    log_debug(f"PowerPoint prs.Close() 예외: {e_close}")
                prs = None

    except Exception:
        if owns_prs and prs is not None:
            try:
                prs.Close()
            except Exception:
                pass
            prs = None
        raise

    finally:
        if app is not None:
            if orig_alerts is not None and not owns_app:
                try:
                    app.DisplayAlerts = orig_alerts
                except Exception:
                    pass
            if owns_app:
                try:
                    if app.Presentations.Count == 0:
                        app.Quit()
                except Exception:
                    pass
        prs = None
        app = None
        _release_com()
        log_debug("PowerPoint COM 세션 정상 종료 완료")
```

=== END FILE: _com_guard.py ===

---

=== FILE: _config.py ===

```python
import os
import sys
import json
import re
from typing import Optional, Dict, Any

try:
    from _office_utils import init_utf8_environment
    init_utf8_environment()
except Exception:
    pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(CURRENT_DIR, "config.json")

DEFAULT_RECIPE_DIR = os.path.join(CURRENT_DIR, "recipes").replace("\\", "/")
DEFAULT_DATA_DIR = os.path.join(CURRENT_DIR, "data").replace("\\", "/")
DEFAULT_CACHE_DIR = os.path.join(CURRENT_DIR, "cache").replace("\\", "/")

def load_config() -> Dict[str, Any]:
    """config.json을 로드하며 파일이 없으면 기본 설정을 생성합니다."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "recipe_dir": DEFAULT_RECIPE_DIR,
        "data_dir": DEFAULT_DATA_DIR,
        "cache_dir": DEFAULT_CACHE_DIR
    }

def save_config(cfg: Dict[str, Any]) -> None:
    """config.json에 설정을 영구 저장합니다."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        sys.stderr.write(f"[WARN] 설정 저장 실패: {e}\n")

def get_recipe_dir() -> str:
    """우선순위: 환경변수(ATOMIC_RECIPE_DIR) > config.json > 기본값"""
    env_dir = os.environ.get("ATOMIC_RECIPE_DIR")
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    cfg = load_config()
    return cfg.get("recipe_dir", DEFAULT_RECIPE_DIR)

def get_data_dir() -> str:
    """우선순위: 환경변수(ATOMIC_DATA_DIR) > config.json > 기본값"""
    env_dir = os.environ.get("ATOMIC_DATA_DIR")
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    cfg = load_config()
    return cfg.get("data_dir", DEFAULT_DATA_DIR)

def get_cache_dir() -> str:
    """우선순위: 환경변수(ATOMIC_CACHE_DIR) > config.json > 기본값"""
    env_dir = os.environ.get("ATOMIC_CACHE_DIR")
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    cfg = load_config()
    return cfg.get("cache_dir", DEFAULT_CACHE_DIR)

def set_recipe_dir(new_path: str) -> str:
    """레시피 기본 저장 폴더를 변경하고 저장합니다."""
    abs_path = os.path.abspath(new_path)
    os.makedirs(abs_path, exist_ok=True)
    cfg = load_config()
    cfg["recipe_dir"] = abs_path.replace("\\", "/")
    save_config(cfg)
    return abs_path

def resolve_recipe_path(recipe_input: str) -> str:
    """파일명만 넘겨도(예: 'sine_recipe') recipe_dir에서 자동으로 찾아 절대경로를 반환합니다."""
    if not recipe_input:
        raise ValueError("레시피 경로가 비어 있습니다.")

    candidates = [recipe_input]
    if not recipe_input.endswith(".json"):
        candidates.append(recipe_input + ".json")

    # 1. 입력된 그대로 존재하는지 확인
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)

    # 2. 설정된 recipe_dir에서 검색
    r_dir = get_recipe_dir()
    for c in candidates:
        target = os.path.join(r_dir, c)
        if os.path.exists(target):
            return os.path.abspath(target)

    # 3. 현재 작업 디렉터리에서 검색
    cwd = os.getcwd()
    for c in candidates:
        target = os.path.join(cwd, c)
        if os.path.exists(target):
            return os.path.abspath(target)

    # 찾지 못한 경우 recipe_dir 기준의 경로로 반환 (에러 메시지용)
    return os.path.abspath(os.path.join(r_dir, candidates[-1]))

def resolve_data_path(file_input: str, recipe_dir_hint: Optional[str] = None) -> str:
    """상대 경로 데이터 파일(CSV, styles.json 등)을 data_dir 또는 레시피 위치 기준으로 자동 탐색합니다."""
    if not file_input:
        return ""
    if os.path.isabs(file_input) and os.path.exists(file_input):
        return file_input

    # 1. 레시피 파일과 같은 폴더에서 검색
    if recipe_dir_hint:
        p1 = os.path.join(recipe_dir_hint, file_input)
        if os.path.exists(p1):
            return os.path.abspath(p1)

    # 2. data_dir에서 검색
    d_dir = get_data_dir()
    p2 = os.path.join(d_dir, file_input)
    if os.path.exists(p2):
        return os.path.abspath(p2)

    # 3. C:\cli_data\data에서 검색
    p_cli = os.path.join(r"C:\cli_data\data", file_input)
    if os.path.exists(p_cli):
        return os.path.abspath(p_cli)

    # 4. 현재 작업 디렉터리에서 검색
    p3 = os.path.join(os.getcwd(), file_input)
    if os.path.exists(p3):
        return os.path.abspath(p3)

    return os.path.abspath(p2)

def get_target_ml_dir(target_name: str) -> str:
    """적용 타겟별 격리 디렉터리 경로를 반환하며 자동 생성합니다 (예: data/ml_sessions/{target}/)."""
    clean_target = re.sub(r"[^\w\-]", "_", str(target_name).strip().lower()) or "default_target"
    t_dir = os.path.join(get_data_dir(), "ml_sessions", clean_target)
    os.makedirs(t_dir, exist_ok=True)
    return t_dir
```

=== END FILE: _config.py ===

---

=== FILE: _office_utils.py ===

```python
import sys
import os
import json
import csv
import ctypes
from typing import Any, Dict, List, Optional, Tuple

def init_utf8_environment() -> None:
    """Windows 11 터미널, 파워쉘, CMD에서 한글 입출력이 깨지지 않도록 OS 콘솔 코드페이지와 파이썬 IO를 UTF-8로 통합 보정합니다."""
    # 1. 윈도우 OS 콘솔 코드페이지를 UTF-8(65001)로 전환
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass

    # 2. Python stdout/stderr/stdin 스트림을 UTF-8로 강제 재구성
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        if sys.stdin and hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 모듈 로드 즉시 전역 UTF-8 환경 활성화
init_utf8_environment()

# 표준 색상 이름 -> BGR 정수 매핑 (Excel COM은 BGR(0xBBGGRR) 형식을 사용함)
COLOR_PALETTE = {
    "black": 0x000000,
    "white": 0xFFFFFF,
    "red": 0x0000FF,
    "green": 0x008000,
    "blue": 0xFF0000,
    "yellow": 0x00FFFF,
    "orange": 0x00A5FF,
    "purple": 0x800080,
    "gray": 0x808080,
    "lightgray": 0xD3D3D3,
    "lightblue": 0xE6D8AD,
    "lightgreen": 0x90EE90,
    "lightyellow": 0xE0FFFF,
    "pink": 0xCBC0FF,
}

def parse_color_to_bgr(color_val: Any) -> Optional[int]:
    """HEX(#RRGGBB) 또는 영문 색상명을 Excel COM용 BGR 정수로 변환합니다."""
    if not color_val:
        return None
    if isinstance(color_val, int):
        return color_val
        
    c = str(color_val).strip().lower()
    if c in COLOR_PALETTE:
        return COLOR_PALETTE[c]
        
    if c.startswith("#"):
        c = c[1:]
    if len(c) == 6:
        try:
            r = int(c[0:2], 16)
            g = int(c[2:4], 16)
            b = int(c[4:6], 16)
            return (b << 16) | (g << 8) | r
        except ValueError:
            return None
    return None

def bgr_to_hex(bgr_val: Any) -> Optional[str]:
    """Excel/Office COM BGR 정수를 표준 HEX 문자열(#RRGGBB)로 변환합니다."""
    if bgr_val is None:
        return None
    try:
        val = int(bgr_val)
        if val < 0:
            return None
        r = val & 0xFF
        g = (val >> 8) & 0xFF
        b = (val >> 16) & 0xFF
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return None

def log_debug(message: str) -> None:
    """터미널 stdout 오염을 방지하기 위해 디버그 메시지는 반드시 stderr로만 출력합니다."""
    sys.stderr.write(f"[DEBUG] {message}\n")
    sys.stderr.flush()

def friendly_error_message(err: Any) -> str:
    """원시 COM 16진수 HRESULT 오류를 모델과 사용자가 이해하기 쉬운 명확한 안내로 변환합니다."""
    msg = str(err)
    if "0x800706BA" in msg or "-2147023174" in msg or "RPC" in msg:
        return "RPC 서버 연결이 중단되었습니다. (Office 창이 닫혔거나 응답하지 않음)"
    if "0x800AC472" in msg or "-2146777998" in msg:
        return "Excel이 사용자의 셀 편집 상태이거나 모달 대화상자가 열려 있습니다. (Esc 키를 누르세요)"
    if "0x800401E3" in msg or "-2147221021" in msg:
        return "실행 중인 활성 Office 창이나 열린 문서를 찾을 수 없습니다."
    if "0x8002000B" in msg or "-2147352565" in msg:
        return "지정한 시트 또는 슬라이드 번호가 범위를 벗어났습니다."
    if "0x800A03EC" in msg or "1004" in msg:
        return "지정한 셀 범위 주소 또는 수식 구문에 오류가 있습니다."
    return msg

def format_response(
    status: str,
    module: str,
    action: str,
    preview: str = "",
    agent_directive: str = "",
    extra: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Gemma 4 26B 가드레일을 위한 표준 딕셔너리를 구성합니다."""
    res = {
        "status": status,
        "module": module,
        "action": action,
        "preview": preview,
        "agent_directive": agent_directive
    }
    if extra:
        # 응답 규약의 핵심 키(status/module/action/preview/agent_directive)는 extra로 덮어쓰지 않음
        for k, v in extra.items():
            if k not in res:
                res[k] = v
    return res

def emit_response(response_dict: Dict[str, Any]) -> None:
    """표준 출력(stdout)에 오직 단 1줄의 순수 JSON 문자열만 출력합니다."""
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    # datetime, timestamp 등 특수 COM 타입 직렬화를 위해 default=str 적용
    json_str = json.dumps(response_dict, ensure_ascii=False, default=str)
    sys.stdout.write(json_str + "\n")
    sys.stdout.flush()

def read_csv_table(file_path: str) -> List[List[Any]]:
    """CSV 파일을 utf-8-sig (또는 fallback cp949/utf-8)로 읽어 2차원 리스트로 반환합니다."""
    encodings = ["utf-8-sig", "utf-8", "cp949"]
    content = None
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                reader = csv.reader(f)
                content = [row for row in reader]
            break
        except UnicodeDecodeError:
            continue
            
    if content is None:
        raise ValueError(f"CSV 파일을 읽을 수 없습니다 (인코딩 지원 실패): {file_path}")
    return content

def range_to_matrix(values: Any) -> List[List[Any]]:
    """Excel Range.Value/Formula 결과를 항상 2차원 리스트로 정규화합니다.
    pywin32는 단일 셀이면 스칼라, 여러 셀이면 (한 행/한 열이어도) 튜플의 튜플을 반환합니다.
    """
    if not isinstance(values, (tuple, list)):
        return [[values]]
    return [list(row) if isinstance(row, (tuple, list)) else [row] for row in values]

def col_idx_to_name(col_idx: int) -> str:
    """1-based 열 인덱스를 엑셀 열 문자열(예: 1 -> 'A', 28 -> 'AB')로 변환합니다."""
    result = ""
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result

def get_target_range_address(start_cell: str, row_count: int, col_count: int) -> str:
    """시작 셀(예: 'A1')과 행/열 개수로 끝 셀 주소(예: 'A1:D10')를 계산합니다."""
    import re
    m = re.match(r"^([A-Za-z]+)(\d+)$", start_cell.strip())
    if not m:
        return start_cell
    
    col_str, row_str = m.groups()
    start_row = int(row_str)
    
    # 열 문자를 1-based 숫자로 변환
    start_col = 0
    for char in col_str.upper():
        start_col = start_col * 26 + (ord(char) - ord('A') + 1)
        
    end_row = start_row + row_count - 1
    end_col = start_col + col_count - 1
    end_col_str = col_idx_to_name(end_col)
    
    return f"{start_cell.upper()}:{end_col_str}{end_row}"

def parse_replace_rules(raw_input: Any, resolve_path_fn=None) -> Dict[str, Any]:
    """경로 문자열, 인메모리 JSON 직렬화 문자열, 또는 사전(dict) 형태의 치환 규칙을 안전하게 파싱합니다."""
    if not raw_input:
        return {}
    if isinstance(raw_input, dict):
        return dict(raw_input)
    if isinstance(raw_input, str):
        s = raw_input.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                return json.loads(s)
            except Exception:
                pass
        # 파일 경로 시도
        target_path = resolve_path_fn(s) if resolve_path_fn else s
        if os.path.exists(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log_debug(f"규칙 파일 읽기 실패 ({target_path}): {e}")
    return {}

def normalize_and_expand_rules(rules: Dict[str, Any]) -> Dict[str, Any]:
    """
    치환 규칙에서 ' | ' 등 가상 구분자로 묶인 복합 항목을 안전하게 분해/확장합니다.
    도구(ppt_read 등)에서 여러 도형 텍스트를 파이프로 연결하여 반환했을 때 발생하는 매칭 실패를 원천 방지합니다.
    """
    if not rules:
        return {}
    expanded = dict(rules)
    for key, rule in list(rules.items()):
        key_str = str(key).strip()
        val_str = ""
        base_style = {}
        if isinstance(rule, str):
            val_str = rule.strip()
        elif isinstance(rule, dict):
            val_str = str(rule.get("text") or rule.get("replace") or "").strip()
            base_style = {k: v for k, v in rule.items() if k not in ("text", "replace")}

        # 1. 파이프(' | ') 구분자 분해
        if " | " in key_str and " | " in val_str:
            k_parts = [p.strip() for p in key_str.split(" | ") if p.strip()]
            v_parts = [p.strip() for p in val_str.split(" | ") if p.strip()]
            if len(k_parts) == len(v_parts):
                for kp, vp in zip(k_parts, v_parts):
                    if kp and kp not in expanded:
                        if isinstance(rule, dict):
                            sub_rule = dict(base_style)
                            sub_rule["text"] = vp
                            expanded[kp] = sub_rule
                        else:
                            expanded[kp] = vp

        # 2. 줄바꿈('\n') 구분자 분해 (다중 단락/문장 매핑 대응)
        if "\n" in key_str and "\n" in val_str and " | " not in key_str:
            k_lines = [p.strip() for p in key_str.splitlines() if p.strip()]
            v_lines = [p.strip() for p in val_str.splitlines() if p.strip()]
            if len(k_lines) == len(v_lines):
                for kl, vl in zip(k_lines, v_lines):
                    if kl and kl not in expanded:
                        if isinstance(rule, dict):
                            sub_rule = dict(base_style)
                            sub_rule["text"] = vl
                            expanded[kl] = sub_rule
                        else:
                            expanded[kl] = vl

    return expanded


def exit_code_for(response_dict: Dict[str, Any]) -> int:
    """응답 status에 따른 프로세스 종료 코드 (ok/no_match=0, 그 외=1)."""
    return 0 if response_dict.get("status") in ("ok", "no_match") else 1

def run_session_tool(module: str, action: str, session_factory, tool_fn) -> None:
    """Office 세션을 열고 도구를 실행한 뒤, 결과를 단 1줄 JSON으로 출력하고 종료 코드를 반환하며 종료합니다.
    세션 연결 실패(대상 문서 없음, 시트 없음 등)를 포함한 모든 예외도 JSON 오류 응답으로 변환합니다.

    Args:
        session_factory: 인자 없이 호출하면 Context Manager를 반환하는 함수 (예: lambda: excel_session(...))
        tool_fn: 세션이 yield한 COM 객체들을 위치 인자로 받아 응답 dict를 반환하는 함수
    """
    try:
        with session_factory() as handles:
            res = tool_fn(*handles)
    except Exception as e:
        log_debug(f"{module} 세션/실행 오류: {e}")
        res = format_response(
            status="error",
            module=module,
            action=action,
            preview=friendly_error_message(e),
            agent_directive="STOP_RETRY: 대상 문서에 연결하지 못했거나 실행 중 오류가 발생했습니다. 사용자에게 보고하세요."
        )
    emit_response(res)
    sys.exit(exit_code_for(res))
```

=== END FILE: _office_utils.py ===

---

=== FILE: _outlook_guard.py ===

```python
"""
_outlook_guard.py - Native Windows Outlook COM Session Guard.
Directly binds to the live Outlook instance on the user's Default desktop.
Zero mock, pure native MAPI COM automation.
"""
import sys
import os
import re
from typing import Optional, Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _com_guard import attach_user_desktop
from _office_utils import log_debug

try:
    import pythoncom
    import win32com.client
    COM_AVAILABLE = True
except ImportError:
    COM_AVAILABLE = False

# Standard Outlook Default Folders (OlDefaultFolders)
OL_FOLDER_MAP = {
    "deleted": 3,
    "outbox": 4,
    "sent": 5,
    "inbox": 6,
    "calendar": 9,
    "contacts": 10,
    "journal": 11,
    "notes": 12,
    "tasks": 13,
    "drafts": 16,
    "junk": 23
}

def get_outlook_app():
    """Binds to live Outlook.Application on the user's Default desktop."""
    if not COM_AVAILABLE:
        raise RuntimeError("pywin32 (win32com) is not installed.")
    
    # Switch to Default desktop to avoid virtual desktop isolation
    attach_user_desktop()
    
    try:
        app = win32com.client.Dispatch("Outlook.Application")
        return app
    except pythoncom.com_error as e:
        raise RuntimeError(f"Failed to connect to Outlook COM: {e}. Ensure MS Outlook is installed.")

def get_mapi_namespace(app=None):
    """Retrieves the MAPI namespace for the active Outlook session."""
    if app is None:
        app = get_outlook_app()
    ns = app.GetNamespace("MAPI")
    try:
        ns.Logon("", "", False, False)
    except pythoncom.com_error:
        pass  # Already logged on
    return ns

def resolve_folder(ns, folder_spec: Optional[str] = None):
    """
    Resolves folder by alias (inbox, sent, drafts) or path ('Account\\SubFolder').
    Defaults to Inbox (6) if omitted.
    """
    spec = (folder_spec or "").strip()
    if not spec or spec.lower() in OL_FOLDER_MAP:
        folder_id = OL_FOLDER_MAP.get(spec.lower(), OL_FOLDER_MAP["inbox"])
        return ns.GetDefaultFolder(folder_id)

    # Path traversal: e.g. "MyAccount\Projects\Work"
    parts = [p for p in re.split(r"[\\/]+", spec) if p]
    try:
        roots = {f.Name: f for f in ns.Folders}
        if parts and parts[0] in roots:
            curr = roots[parts[0]]
            parts = parts[1:]
        else:
            curr = ns.GetDefaultFolder(OL_FOLDER_MAP["inbox"])

        for part in parts:
            found = False
            for sub in curr.Folders:
                if sub.Name.lower() == part.lower():
                    curr = sub
                    found = True
                    break
            if not found:
                raise ValueError(f"Folder part '{part}' not found in path '{spec}'.")
        return curr
    except Exception as e:
        raise RuntimeError(f"Failed to resolve folder '{spec}': {e}")

def get_current_active_item(app=None):
    """
    Captures the mail item the user is currently viewing or selecting in the Outlook UI.
    1. Checks ActiveInspector (mail open in its own window)
    2. Checks ActiveExplorer.Selection (mail highlighted in main list)
    """
    if app is None:
        app = get_outlook_app()

    # 1. Open Inspector window
    try:
        insp = app.ActiveInspector()
        if insp and insp.CurrentItem:
            return insp.CurrentItem, "open_window"
    except Exception:
        pass

    # 2. Selected item in Explorer
    try:
        exp = app.ActiveExplorer()
        if exp and exp.Selection and exp.Selection.Count > 0:
            return exp.Selection.Item(1), "selected_in_list"
    except Exception:
        pass

    return None, "none"
```

=== END FILE: _outlook_guard.py ===

---

=== FILE: clean.py ===

```python
import sys
import os
import glob
import shutil
import argparse
from datetime import datetime
from typing import Dict, Any, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_cache_dir
from _cache import get_latest_snapshot, delete_snapshot_files

def preserve_cache_notice() -> str:
    """캐시 폴더는 중요한 검색 인덱스 자산이므로 일체 삭제하지 않고 영구 보존합니다."""
    return "캐시 인덱스는 중요한 검색 자산이므로 비우지 않고 안전하게 영구 보존됩니다."

def fix_office_environment() -> Dict[str, Any]:
    """사용자의 정상 오피스 작업 창은 100% 온전히 보존하며, 실행 중인 Office 인스턴스가 COM으로 응답하는지 점검합니다.
    프로세스는 종료하지 않습니다.
    """
    responsive = {}
    try:
        from _com_guard import attach_user_desktop, find_all_native_excel_apps, find_all_native_word_apps, find_all_native_ppt_apps
        attach_user_desktop()
        for name, finder in (("excel", find_all_native_excel_apps), ("word", find_all_native_word_apps), ("ppt", find_all_native_ppt_apps)):
            count = 0
            for app in finder():
                try:
                    _ = app.Name
                    count += 1
                except Exception:
                    pass
            responsive[name] = count
    except Exception as e:
        log_debug(f"환경 점검 예외: {e}")

    return {
        "killed_count": 0,
        "killed_processes": [],
        "responsive_instances": responsive
    }

def _backup_path(app_name: str, ext: str) -> str:
    cache_dir = get_cache_dir()
    os.makedirs(cache_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    return os.path.normpath(os.path.join(cache_dir, f"undo_backup_{app_name}_{stamp}{ext}"))

def _find_open_document(app_name: str, orig_path: str) -> Optional[Dict[str, Any]]:
    """원본 경로의 문서가 현재 Office에 열려 있으면 해당 항목을 반환합니다."""
    try:
        from _com_guard import (get_all_running_excel_workbooks, get_all_running_word_documents,
                                get_all_running_ppt_presentations)
        lister = {"excel": get_all_running_excel_workbooks, "word": get_all_running_word_documents,
                  "ppt": get_all_running_ppt_presentations}[app_name]
        target = os.path.normcase(os.path.abspath(orig_path))
        for item in lister():
            path = item.get("path") or ""
            if path and os.path.normcase(os.path.abspath(path)) == target:
                return item
    except Exception as e:
        log_debug(f"열린 문서 탐색 예외: {e}")
    return None

def _word_save_flat_xml_as(app, xml_path: str, dest_path: str):
    """Flat OPC(.xml) 스냅샷을 Word로 열어 원본 확장자 형식으로 저장하고, 저장된 문서 객체를 반환합니다."""
    from _com_guard import WD_FILE_FORMATS, _file_format_for
    doc = app.Documents.Open(os.path.normpath(xml_path), ConfirmConversions=False, AddToRecentFiles=False)
    fmt = _file_format_for(dest_path, WD_FILE_FORMATS)
    if fmt is not None:
        doc.SaveAs2(os.path.normpath(dest_path), FileFormat=fmt)
    else:
        doc.SaveAs2(os.path.normpath(dest_path))
    return doc

def _restore_open_document(app_name: str, item: Dict[str, Any], snap: Dict[str, Any], orig_path: str) -> str:
    """열려 있는 문서를 현재 상태로 백업한 뒤 닫고, 스냅샷으로 교체한 다음 같은 앱에서 다시 엽니다."""
    import win32com.client
    app = win32com.client.Dispatch(item["app"])
    snap_file = snap["snapshot_file"]
    ext = os.path.splitext(orig_path)[1]

    if app_name == "excel":
        wb = item["wb"]
        backup = _backup_path(app_name, ext)
        wb.SaveCopyAs(backup)
        wb.Close(SaveChanges=False)
        shutil.copy2(snap_file, orig_path)
        app.Workbooks.Open(os.path.normpath(orig_path))
    elif app_name == "ppt":
        prs = item["prs"]
        backup = _backup_path(app_name, ext)
        prs.SaveCopyAs(backup)
        prs.Close()
        shutil.copy2(snap_file, orig_path)
        app.Presentations.Open(os.path.normpath(orig_path))
    else:
        doc = item["doc"]
        backup = _backup_path(app_name, ".xml")
        with open(backup, "w", encoding="utf-8") as f:
            f.write(doc.WordOpenXML)
        doc.Close(SaveChanges=0)
        if snap.get("snapshot_format") == "flat_xml":
            _word_save_flat_xml_as(app, snap_file, orig_path)
        else:
            shutil.copy2(snap_file, orig_path)
            app.Documents.Open(os.path.normpath(orig_path))
    return backup

def _restore_closed_document(app_name: str, snap: Dict[str, Any], orig_path: str) -> str:
    """닫혀 있는 원본 파일을 백업한 뒤 스냅샷으로 교체합니다."""
    backup = ""
    if os.path.exists(orig_path):
        backup = _backup_path(app_name, os.path.splitext(orig_path)[1])
        shutil.copy2(orig_path, backup)

    if app_name == "word" and snap.get("snapshot_format") == "flat_xml":
        from _com_guard import init_com
        import win32com.client
        init_com()
        app = win32com.client.DispatchEx("Word.Application")
        try:
            app.Visible = False
            app.DisplayAlerts = 0
            doc = _word_save_flat_xml_as(app, snap["snapshot_file"], orig_path)
            doc.Close(SaveChanges=0)
        finally:
            try:
                app.Quit(SaveChanges=0)
            except Exception:
                pass
    else:
        shutil.copy2(snap["snapshot_file"], orig_path)
    return backup

def _open_snapshot_as_new_document(app_name: str, snap: Dict[str, Any]) -> None:
    """저장된 적 없는 문서의 스냅샷을 사용자 Office에서 '제목 없는 새 문서'로 엽니다 (캐시 파일 자체를 열지 않음)."""
    from _com_guard import get_active_excel_app_and_wb, get_active_word_app_and_doc, get_active_ppt_app_and_prs
    import win32com.client
    snap_file = os.path.normpath(snap["snapshot_file"])
    if app_name == "excel":
        app, _ = get_active_excel_app_and_wb()
        win32com.client.Dispatch(app).Workbooks.Add(snap_file)
    elif app_name == "ppt":
        app, _ = get_active_ppt_app_and_prs()
        win32com.client.Dispatch(app).Presentations.Open(snap_file, 0, -1, -1)  # Untitled=msoTrue, WithWindow=msoTrue
    else:
        app, _ = get_active_word_app_and_doc()
        win32com.client.Dispatch(app).Documents.Add(Template=snap_file)

def undo_latest_backup(app_filter: str = "") -> Dict[str, Any]:
    """가장 최근에 저장된 캐시 스냅샷으로 원본 문서를 복원합니다.

    - 복원 직전의 현재 상태는 cache/undo_backup_* 로 먼저 백업합니다 (복원 자체도 되돌릴 수 있도록).
    - 원본이 Office에 열려 있으면 닫고 교체한 뒤 같은 앱에서 다시 엽니다.
    - 복원에 성공한 스냅샷은 소비(삭제)되어, 다음 undo는 그 이전 스냅샷으로 진행됩니다.
    """
    snap = get_latest_snapshot(app_filter=app_filter)
    if not snap:
        return {"status": "no_match", "preview": "복원 가능한 캐시 스냅샷이 없습니다."}

    app_name = snap.get("app", "excel")
    orig_path = snap.get("original_path", "")
    doc_name = snap.get("name", "")
    snap_file = snap.get("snapshot_file", "")
    restored_as = ""
    backup = ""

    try:
        if not orig_path:
            _open_snapshot_as_new_document(app_name, snap)
            restored_as = "new_untitled_document"
        else:
            if not os.path.isdir(os.path.dirname(orig_path)):
                return {"status": "error", "preview": f"원본 폴더가 존재하지 않습니다: {os.path.dirname(orig_path)}"}
            open_item = _find_open_document(app_name, orig_path)
            if open_item:
                backup = _restore_open_document(app_name, open_item, snap, orig_path)
                restored_as = "reopened_in_office"
            else:
                backup = _restore_closed_document(app_name, snap, orig_path)
                restored_as = "file_replaced"
    except Exception as e:
        log_debug(f"Undo 복원 예외: {e}")
        return {"status": "error", "preview": f"스냅샷 복원 실패 ({doc_name}): {e}"}

    try:
        delete_snapshot_files(snap["meta_file"])
    except Exception as e:
        log_debug(f"사용한 스냅샷 정리 실패: {e}")

    return {
        "status": "ok",
        "app": app_name,
        "doc_name": doc_name,
        "snapshot_id": os.path.basename(snap_file),
        "restored_to": orig_path or "(새 문서)",
        "restored_as": restored_as,
        "pre_undo_backup": backup
    }

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """오피스 COM 응답 점검 또는 직전 작업 되돌리기(Undo)를 수행합니다."""
    action = (params.get("action") or "all").lower()
    app_filter = (params.get("app") or "").lower()

    if action == "undo":
        res = undo_latest_backup(app_filter=app_filter)
        if res.get("status") == "ok":
            extra = {k: v for k, v in res.items() if k != "status"}
            return format_response(
                status="ok",
                module="clean",
                action="undo",
                preview=f"Restored '{res.get('doc_name')}' from snapshot {res.get('snapshot_id')} ({res.get('restored_as')})",
                agent_directive="VERIFIED: 직전 스냅샷 상태로 복원했습니다. 복원 전 상태는 pre_undo_backup에 보관되어 있습니다.",
                extra=extra
            )
        return format_response(
            status=res.get("status", "error"),
            module="clean",
            action="undo",
            preview=res.get("preview", "Undo 실패"),
            agent_directive="STOP_RETRY: 복원 가능한 스냅샷이 없거나 복원 중 오류가 발생했습니다. 사용자에게 보고하세요."
        )

    fix_result = fix_office_environment()
    resp = fix_result.get("responsive_instances", {})
    preview_msg = ("COM 응답 점검 완료 (프로세스 종료 없음): "
                   + ", ".join(f"{k}={v}" for k, v in resp.items()) + " | 캐시 인덱스 보존")

    return format_response(
        status="ok",
        module="clean",
        action="fix_env",
        preview=preview_msg,
        agent_directive="INFO: 실행 중인 Office 인스턴스의 COM 응답 여부만 점검했습니다. 종료된 프로세스는 없습니다.",
        extra={
            "responsive_instances": resp,
            "killed_orphaned_processes": [],
            "cache_status": "preserved"
        }
    )

def main():
    parser = argparse.ArgumentParser(description="Office Environment Recovery & Process Cleaner Micro Block")
    parser.add_argument("--action", choices=["fix-env", "undo", "all"], default="all", help="수행할 작업 (fix-env, undo, all)")
    parser.add_argument("--app", choices=["excel", "word", "ppt"], help="되돌릴 대상 애플리케이션 (생략 시 전역 최신)")
    args = parser.parse_args()

    params = {"action": args.action, "app": args.app}
    try:
        res = execute(params)
    except Exception as e:
        res = format_response("error", "clean", args.action, preview=f"clean 실행 오류: {e}",
                              agent_directive="STOP_RETRY: 사용자에게 오류를 보고하세요.")
    emit_response(res)
    sys.exit(0 if res.get("status") in ("ok", "no_match") else 1)

if __name__ == "__main__":
    main()
```

=== END FILE: clean.py ===

---

=== FILE: eml_read.py ===

```python
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
```

=== END FILE: eml_read.py ===

---

=== FILE: excel_chart.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, parse_color_to_bgr
from _com_guard import excel_session
from office_theme import resolve_theme

# Excel XlChartType 상수 매핑
CHART_TYPES = {
    "column": 51,        # xlColumnClustered
    "bar": 57,           # xlBarClustered
    "line": 4,           # xlLine
    "line_markers": 65,  # xlLineMarkers
    "pie": 5,            # xlPie
    "area": 1,           # xlArea
    "combo": 51          # 복합 차트 (1계열 막대 + 2계열 보조축 꺾은선)
}

LEGEND_POSITIONS = {
    "bottom": -4107,     # xlLegendPositionBottom
    "right": -4152,      # xlLegendPositionRight
    "top": -4160,        # xlLegendPositionTop
    "left": -4131        # xlLegendPositionLeft
}

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체로 차트를 생성하거나 삭제합니다."""
    action = str(params.get("action") or "create").lower()

    # 차트 삭제/초기화 분기
    if action in ["delete", "remove", "clear"]:
        chart_name = params.get("title") or params.get("name") or params.get("chart")
        try:
            chart_objs = ws.ChartObjects()
            total = chart_objs.Count
            if total == 0:
                return format_response(
                    status="ok",
                    module="excel_chart",
                    action="delete_chart",
                    preview="시트에 삭제할 차트가 없습니다 (현재 차트 수: 0개).",
                    agent_directive="VERIFIED: No charts to delete."
                )
            deleted_count = 0
            if chart_name:
                for i in range(total, 0, -1):
                    obj = chart_objs.Item(i)
                    obj_title = ""
                    try:
                        if obj.Chart.HasTitle:
                            obj_title = str(obj.Chart.ChartTitle.Text)
                    except Exception:
                        pass
                    if str(chart_name).lower() in obj.Name.lower() or (obj_title and str(chart_name).lower() in obj_title.lower()):
                        obj.Delete()
                        deleted_count += 1
                if deleted_count == 0:
                    chart_objs.Item(1).Delete()
                    deleted_count = 1
            else:
                deleted_count = total
                chart_objs.Delete()

            return format_response(
                status="ok",
                module="excel_chart",
                action="delete_chart",
                preview=f"시트 '{ws.Name}'에서 차트 {deleted_count}개를 성공적으로 삭제했습니다.",
                agent_directive="VERIFIED: Chart deleted. Do not re-verify.",
                extra={"deleted_count": deleted_count}
            )
        except Exception as e:
            return format_response(
                status="error",
                module="excel_chart",
                action="delete_chart",
                preview=f"차트 삭제 실패: {e}",
                agent_directive=f"STOP_RETRY: Chart deletion failed: {e}"
            )

    source_addr = params.get("source_range") or params.get("range")
    chart_type_name = str(params.get("type", "column")).lower()
    title = params.get("title", "")
    target_cell = params.get("target_cell", "G2")
    width = float(params.get("width", 420))
    height = float(params.get("height", 260))
    data_labels = params.get("data_labels", False)
    theme_arg = params.get("theme")
    legend_pos = params.get("legend", "bottom").lower()

    if not source_addr:
        try:
            used_addr = ws.UsedRange.Address
            if used_addr and (used_addr != "$A$1" or ws.Range("$A$1").Value is not None):
                source_addr = used_addr
                log_debug(f"Source range omitted. Auto-detected UsedRange: {source_addr}")
            else:
                return format_response(
                    status="no_match",
                    module="excel_chart",
                    action="create_chart",
                    preview="source_range is required",
                    agent_directive="STOP_RETRY: Missing source data range for chart."
                )
        except Exception:
            return format_response(
                status="no_match",
                module="excel_chart",
                action="create_chart",
                preview="source_range is required",
                agent_directive="STOP_RETRY: Missing source data range for chart."
            )

    try:
        source_rng = ws.Range(source_addr)
        anchor_cell = ws.Range(target_cell)
        left = anchor_cell.Left
        top = anchor_cell.Top

        chart_code = CHART_TYPES.get(chart_type_name, 51)
        log_debug(f"차트 생성: 유형={chart_type_name}, 데이터={source_addr}, 위치={target_cell}")

        # 차트 오브젝트 생성
        chart_obj = ws.ChartObjects().Add(left, top, width, height)
        chart = chart_obj.Chart
        chart.ChartType = chart_code
        chart.SetSourceData(source_rng)

        # 1. 제목 설정
        if title:
            chart.HasTitle = True
            chart.ChartTitle.Text = title

        # 2. 이중 축 (Combo: 1계열 막대 + 2계열 꺾은선) 구성
        is_combo = chart_type_name in ["combo", "column_line"]
        if is_combo:
            try:
                series_collection = chart.SeriesCollection()
                if series_collection.Count >= 2:
                    # 1계열: 세로 막대 (기본 축)
                    series_collection(1).ChartType = 51  # xlColumnClustered
                    series_collection(1).AxisGroup = 1   # xlPrimary
                    
                    # 2계열: 꺾은선 마커 (보조 축 xlSecondary = 2)
                    series_collection(2).ChartType = 65  # xlLineMarkers
                    series_collection(2).AxisGroup = 2   # xlSecondary
                    log_debug("이중 축(Combo) 차트 구성 완료 (1계열: 막대, 2계열: 보조축 꺾은선)")
            except Exception as ce:
                log_debug(f"이중 축 구성 예외: {ce}")

        # 3. 데이터 레이블(값 표시) 적용
        if data_labels:
            try:
                chart.ApplyDataLabels()
                log_debug("차트 데이터 레이블 적용 완료")
            except Exception as de:
                log_debug(f"데이터 레이블 적용 예외: {de}")

        # 4. 범례 위치 지정
        if legend_pos == "none":
            chart.HasLegend = False
        elif legend_pos in LEGEND_POSITIONS:
            chart.HasLegend = True
            chart.Legend.Position = LEGEND_POSITIONS[legend_pos]

        # 5. 테마 색상 연계
        applied_theme_name = None
        if theme_arg:
            try:
                theme = resolve_theme(theme_arg)
                applied_theme_name = theme.get("name", theme_arg)
                series_collection = chart.SeriesCollection()
                
                # 주색상 / 보조색상 매핑
                p_color = parse_color_to_bgr(theme.get("primary"))
                s_color = parse_color_to_bgr(theme.get("secondary"))
                
                if series_collection.Count >= 1 and p_color is not None:
                    series_collection(1).Format.Fill.ForeColor.RGB = p_color
                if series_collection.Count >= 2 and s_color is not None:
                    if is_combo:
                        series_collection(2).Format.Line.ForeColor.RGB = s_color
                    else:
                        series_collection(2).Format.Fill.ForeColor.RGB = s_color
                log_debug(f"차트 테마({applied_theme_name}) 색상 반영 완료")
            except Exception as te:
                log_debug(f"차트 테마 색상 적용 예외: {te}")

        return format_response(
            status="ok",
            module="excel_chart",
            action="create_chart",
            preview=f"Chart '{title or chart_type_name}' created at {target_cell} using {source_addr} (Combo: {is_combo}, Labels: {data_labels})",
            agent_directive="VERIFIED: Chart generated. Do not re-verify.",
            extra={
                "chart_type": chart_type_name,
                "title": title,
                "anchor": target_cell,
                "is_combo": is_combo,
                "data_labels": data_labels,
                "theme": applied_theme_name
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="excel_chart",
            action="create_chart",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Chart creation failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Advanced Chart Micro Block (Combo & DataLabels Support, Delete Support)")
    parser.add_argument("--action", default="create", choices=["create", "delete", "clear"], help="차트 작업 (create=생성, delete=삭제)")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름")
    parser.add_argument("--range", "--source-range", required=False, help="차트 원본 데이터 범위 (create 시 필수, 예: A1:C6)")
    parser.add_argument("--type", default="column", choices=["column", "bar", "line", "line_markers", "pie", "area", "combo"], help="차트 유형 (combo=이중축 혼합차트)")
    parser.add_argument("--title", type=str, help="차트 제목 (delete 시 특정 차트 매칭)")
    parser.add_argument("--target-cell", default="G2", help="차트 배치 기준 셀 (예: G2)")
    parser.add_argument("--width", type=float, default=420, help="차트 너비(pt)")
    parser.add_argument("--height", type=float, default=260, help="차트 높이(pt)")
    parser.add_argument("--data-labels", action="store_true", help="수치 데이터 레이블 표시")
    parser.add_argument("--legend", choices=["bottom", "right", "top", "none"], default="bottom", help="범례 위치")
    parser.add_argument("--theme", type=str, help="테마 프리셋(navy, slate, teal, emerald) 또는 JSON 경로")
    args = parser.parse_args()

    if args.action == "create" and not args.range:
        parser.error("--range는 차트 생성(action=create) 시 필수입니다.")

    params = {
        "action": args.action,
        "range": args.range,
        "type": args.type,
        "title": args.title,
        "target_cell": args.target_cell,
        "width": args.width,
        "height": args.height,
        "data_labels": args.data_labels,
        "legend": args.legend,
        "theme": args.theme
    }

    with excel_session(target=args.target, sheet_name=args.sheet, snapshot=True) as (app, wb, ws):
        res = execute(wb, ws, params)
        emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: excel_chart.py ===

---

=== FILE: excel_edit.py ===

```python
import sys
import os
import json
import re
import argparse
from typing import Dict, Any, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import (
    format_response, emit_response, log_debug, parse_color_to_bgr,
    parse_replace_rules, normalize_and_expand_rules, range_to_matrix
)
from _com_guard import excel_session
from _config import resolve_data_path, get_data_dir
from office_theme import resolve_theme

ALIGN_MAP = {
    "left": -4131,   # xlHAlignLeft
    "center": -4108, # xlHAlignCenter
    "right": -4152   # xlHAlignRight
}

def apply_edit_to_range(rng, style: Dict[str, Any]) -> None:
    """Excel Range 객체에 안전하게 내용 수정 및 서식을 적용합니다."""
    # 1. 텍스트/값/수식 치환 (formula 또는 text 또는 replace)
    formula_val = style.get("formula")
    text_val = style.get("text") if "text" in style else style.get("replace")

    if formula_val is not None:
        f_str = str(formula_val).strip()
        rng.Formula = f_str if f_str.startswith("=") else f"={f_str}"
    elif text_val is not None:
        val_str = str(text_val).strip()
        if val_str.startswith("="):
            rng.Formula = val_str
        else:
            rng.Value = text_val

    # 2. 배경색 (bg / background)
    bg_val = style.get("bg") or style.get("background")
    if bg_val:
        bgr = parse_color_to_bgr(bg_val)
        if bgr is not None:
            rng.Interior.Color = bgr

    # 3. 글꼴색 (color)
    fg_val = style.get("color")
    if fg_val:
        bgr = parse_color_to_bgr(fg_val)
        if bgr is not None:
            rng.Font.Color = bgr

    # 4. 굵게 (bold)
    if "bold" in style:
        rng.Font.Bold = bool(style["bold"])

    # 5. 기울임 (italic)
    if "italic" in style:
        rng.Font.Italic = bool(style["italic"])

    # 6. 글꼴 크기 (size)
    if "size" in style:
        try:
            rng.Font.Size = float(style["size"])
        except ValueError:
            pass

    # 7. 정렬 (align)
    if "align" in style:
        align_code = ALIGN_MAP.get(str(style["align"]).lower())
        if align_code:
            rng.HorizontalAlignment = align_code

    # 8. 숫자 서식 (number_format)
    if "number_format" in style or "format_num" in style:
        fmt = style.get("number_format") or style.get("format_num")
        try:
            rng.NumberFormat = str(fmt)
        except Exception:
            pass

def apply_theme_to_table(
    ws,
    target_rng,
    theme: Dict[str, Any],
    zebra: Optional[bool] = None,
    format_num: Optional[str] = None
) -> Dict[str, Any]:
    """대상 범위 전체에 기업용 프로페셔널 테마(헤더, 줄무늬, 숫자포맷, 테두리, 요약행)를 일괄 적용합니다."""
    row_count = target_rng.Rows.Count
    col_count = target_rng.Columns.Count
    start_row = target_rng.Row
    start_col = target_rng.Column

    if row_count == 0 or col_count == 0:
        return {"rows": 0, "cols": 0}

    # 1. 헤더 행 서식 (1행)
    header_rng = ws.Range(ws.Cells(start_row, start_col), ws.Cells(start_row, start_col + col_count - 1))
    header_spec = theme.get("header", {})
    if header_spec:
        h_bg = header_spec.get("bg")
        if h_bg:
            bgr = parse_color_to_bgr(h_bg)
            if bgr is not None:
                header_rng.Interior.Color = bgr
        h_fg = header_spec.get("color")
        if h_fg:
            bgr = parse_color_to_bgr(h_fg)
            if bgr is not None:
                header_rng.Font.Color = bgr
        header_rng.Font.Bold = bool(header_spec.get("bold", True))
        header_rng.HorizontalAlignment = -4108  # xlHAlignCenter
        header_rng.VerticalAlignment = -4108    # xlVAlignCenter
        
        try:
            ws.Rows(start_row).RowHeight = float(header_spec.get("row_height", 24))
        except Exception:
            pass

    # 2. 데이터 행 서식 (2행부터)
    use_zebra = zebra if zebra is not None else theme.get("zebra", {}).get("enabled", False)
    odd_bg = parse_color_to_bgr(theme.get("zebra", {}).get("odd", "#FFFFFF"))
    even_bg = parse_color_to_bgr(theme.get("zebra", {}).get("even", "#F4F7FB"))

    num_fmt = format_num or theme.get("number_format")

    # 합계/요약 행 감지
    last_row_is_summary = False
    if row_count >= 3:
        first_cell_val = str(ws.Cells(start_row + row_count - 1, start_col).Value or "")
        if any(k in first_cell_val for k in ["합계", "총계", "Total", "소계", "평균"]):
            last_row_is_summary = True

    data_end_row = (start_row + row_count - 2) if last_row_is_summary else (start_row + row_count - 1)

    for r_idx, r in enumerate(range(start_row + 1, data_end_row + 1)):
        row_rng = ws.Range(ws.Cells(r, start_col), ws.Cells(r, start_col + col_count - 1))
        try:
            row_rng.VerticalAlignment = -4108  # 수직 가운데
            ws.Rows(r).RowHeight = 20          # 넉넉한 20pt 행높이
        except Exception:
            pass

        # Zebra 줄무늬
        if use_zebra:
            bg_color = even_bg if (r_idx % 2 == 1) else odd_bg
            if bg_color is not None:
                row_rng.Interior.Color = bg_color

    # 3. 숫자 열 서식 (#,##0 등) 적용
    if num_fmt:
        for c in range(start_col, start_col + col_count):
            for r in range(start_row + 1, min(start_row + row_count, start_row + 10)):
                val = ws.Cells(r, c).Value
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    col_data_rng = ws.Range(ws.Cells(start_row + 1, c), ws.Cells(start_row + row_count - 1, c))
                    col_data_rng.NumberFormat = num_fmt
                    col_data_rng.HorizontalAlignment = -4152  # xlHAlignRight
                    break

    # 4. 합계 행 스타일 (있을 경우)
    if last_row_is_summary:
        sum_row = start_row + row_count - 1
        sum_rng = ws.Range(ws.Cells(sum_row, start_col), ws.Cells(sum_row, start_col + col_count - 1))
        sum_spec = theme.get("summary", {})
        sum_bg = parse_color_to_bgr(sum_spec.get("bg", "#E8EEF5"))
        if sum_bg is not None:
            sum_rng.Interior.Color = sum_bg
        sum_fg = parse_color_to_bgr(sum_spec.get("color"))
        if sum_fg is not None:
            sum_rng.Font.Color = sum_fg
        sum_rng.Font.Bold = True
        try:
            ws.Rows(sum_row).RowHeight = 22
        except Exception:
            pass

        # 상단 얇은 실선 & 하단 이중선 (xlDouble = -4119)
        try:
            sum_rng.Borders(8).LineStyle = 1      # xlEdgeTop
            sum_rng.Borders(8).Weight = 2         # xlThin
            sum_rng.Borders(9).LineStyle = -4119  # xlEdgeBottom = xlDouble
        except Exception:
            pass

    # 5. 전체 테두리 (내부 얇은 선 + 헤더 하단 선)
    try:
        target_rng.Borders(11).LineStyle = 1      # xlInsideVertical
        target_rng.Borders(11).Weight = 2         # xlThin
        target_rng.Borders(12).LineStyle = 1      # xlInsideHorizontal
        target_rng.Borders(12).Weight = 2         # xlThin
        target_rng.BorderAround(1, 2)             # xlContinuous, xlThin
        
        # 헤더 하단 굵은 선 (xlMedium = -4138)
        header_rng.Borders(9).LineStyle = 1
        header_rng.Borders(9).Weight = -4138
    except Exception:
        pass

    return {
        "rows": row_count,
        "cols": col_count,
        "zebra": use_zebra,
        "number_format": num_fmt,
        "summary_row": last_row_is_summary
    }

def is_cell_address_or_range(key: str) -> bool:
    """'A1', 'A1:D10', 'B:B', 'B1, D1, A2:E3' 등의 단일/다중(유니온) 셀 주소 패턴인지 판별합니다."""
    k = key.strip().upper()
    parts = [p.strip() for p in k.split(",") if p.strip()]
    if not parts:
        return False
    single_pattern = re.compile(r"^([A-Z]+[0-9]+(:[A-Z]+[0-9]+)?|[A-Z]+:[A-Z]+|[0-9]+:[0-9]+)$")
    return all(bool(single_pattern.match(p)) for p in parts)

def apply_rule_to_range(target_rng, rule_str: str) -> int:
    """Range 내의 셀들에 조건부 서식 규칙(예: '>=100:lightgreen', '<80:pink', '=완료:lightgreen')을 적용합니다."""
    parts = rule_str.strip().split(":")
    if len(parts) < 2:
        return 0
    condition = parts[0].strip()
    color_val = parts[1].strip()
    bgr_color = parse_color_to_bgr(color_val)
    if bgr_color is None:
        return 0

    op = None
    threshold = None
    text_target = None

    try:
        if condition.startswith(">="):
            op, threshold = ">=", float(condition[2:])
        elif condition.startswith("<="):
            op, threshold = "<=", float(condition[2:])
        elif condition.startswith(">"):
            op, threshold = ">", float(condition[1:])
        elif condition.startswith("<"):
            op, threshold = "<", float(condition[1:])
        elif condition.startswith("="):
            text_target = condition[1:].strip()
        elif condition.startswith("text="):
            text_target = condition[5:].strip()
        else:
            text_target = condition
    except ValueError:
        text_target = condition

    applied = 0
    for cell in target_rng.Cells:
        val = cell.Value
        matched = False
        if op is not None and isinstance(val, (int, float)):
            if op == ">=" and val >= threshold: matched = True
            elif op == "<=" and val <= threshold: matched = True
            elif op == ">" and val > threshold: matched = True
            elif op == "<" and val < threshold: matched = True
        elif text_target is not None and val is not None:
            if text_target.lower() in str(val).strip().lower():
                matched = True

        if matched:
            cell.Interior.Color = bgr_color
            applied += 1

    return applied

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체로 내용 수정, 서식 적용 또는 테마를 일괄 적용합니다."""
    theme_arg = params.get("theme")
    range_str = params.get("range")
    zebra_opt = params.get("zebra")
    format_num_opt = params.get("format_num") or params.get("number_format")

    # A. 테마 일괄 적용 모드
    if theme_arg:
        theme = resolve_theme(theme_arg)
        target_rng = ws.Range(range_str) if range_str else ws.UsedRange
        theme_stat = apply_theme_to_table(ws, target_rng, theme, zebra=zebra_opt, format_num=format_num_opt)
        
        theme_name = theme.get("name", theme_arg)
        return format_response(
            status="ok",
            module="excel_edit",
            action="apply_theme",
            preview=f"Applied '{theme_name}' theme to {target_rng.Address} (Zebra: {theme_stat['zebra']}, NumFmt: {theme_stat['number_format']})",
            agent_directive="VERIFIED: Excel theme and professional styling applied.",
            extra={
                "theme_name": theme_name,
                "range": target_rng.Address,
                "details": theme_stat
            }
        )

    # B. 조건부 서식/규칙 하이라이트 모드 (--rule)
    rule_str = params.get("rule")
    if rule_str:
        target_rng = ws.Range(range_str) if range_str else ws.UsedRange
        applied_count = apply_rule_to_range(target_rng, rule_str)
        return format_response(
            status="ok",
            module="excel_edit",
            action="apply_rule",
            preview=f"Rule '{rule_str}' applied to {target_rng.Address} ({applied_count} cells matched)",
            agent_directive="VERIFIED: Conditional rule applied.",
            extra={"rule": rule_str, "range": target_rng.Address, "applied_count": applied_count}
        )

    # C. 개별 치환 / 서식 룰 적용 모드
    mapping_file = params.get("mapping_file") or params.get("replace_map")
    styles_map = params.get("styles") or params.get("rules")
    
    find_text = params.get("find")
    replace_text = params.get("replace")
    formula_text = params.get("formula")
    single_style = dict(params.get("style", {}))
    for k in ["bg", "color", "bold", "italic", "underline", "size", "align"]:
        if params.get(k) is not None and k not in single_style:
            single_style[k] = params.get(k)
    if formula_text is not None:
        single_style["formula"] = formula_text
    elif replace_text is not None:
        single_style["text"] = replace_text
    if format_num_opt is not None:
        single_style["number_format"] = format_num_opt

    rules = {}
    if mapping_file:
        rules = parse_replace_rules(mapping_file, resolve_path_fn=resolve_data_path)
    elif styles_map and isinstance(styles_map, dict):
        rules = styles_map
    elif find_text:
        rules = {str(find_text): single_style}
    elif range_str and single_style:
        rules = {range_str: single_style}

    # ' | ' 등 가상 결합 구분자로 묶인 항목 자동 분해 및 확장
    rules = normalize_and_expand_rules(rules)

    if not rules:
        return format_response(
            status="no_match",
            module="excel_edit",
            action="apply_edits",
            preview="No edit or style rules provided",
            agent_directive="STOP_RETRY: Empty edit rules."
        )

    applied_count = 0
    used_range = ws.UsedRange

    for key, style in rules.items():
        key_str = str(key).strip()
        
        # A. 셀 좌표/범위 직접 지정인 경우 (예: 'A1:G1', 'C3')
        if is_cell_address_or_range(key_str):
            try:
                target_rng = ws.Range(key_str)
                apply_edit_to_range(target_rng, style)
                applied_count += 1
                log_debug(f"범위 직접 내용/서식 적용: {key_str}")
            except Exception as e:
                log_debug(f"범위 지정 내용/서식 적용 실패 ({key_str}): {e}")
            continue

        # B. 텍스트/숫자 검색 기반 내용 수정 및 서식 적용
        try:
            row_count = used_range.Rows.Count
            col_count = used_range.Columns.Count

            values = range_to_matrix(used_range.Value)
            # 수식 셀은 계산 결과값으로 매칭되더라도 수식을 상수 텍스트로 덮어쓰지 않도록 수식 문자열을 함께 일괄 조회
            formulas = range_to_matrix(used_range.Formula)

            start_row = used_range.Row
            start_col = used_range.Column

            for r_idx in range(row_count):
                row_vals = values[r_idx]
                for c_idx in range(col_count):
                    raw_val = row_vals[c_idx]
                    if raw_val is None:
                        continue
                    
                    val_str = ""
                    if isinstance(raw_val, float) and raw_val.is_integer():
                        val_str = str(int(raw_val))
                    else:
                        val_str = str(raw_val).strip()

                    if key_str == val_str or (len(key_str) > 1 and key_str in val_str):
                        cell_obj = ws.Cells(start_row + r_idx, start_col + c_idx)
                        target_style = dict(style)
                        text_val = target_style.get("text") if "text" in target_style else target_style.get("replace")
                        formula_str = formulas[r_idx][c_idx]
                        has_formula = isinstance(formula_str, str) and formula_str.startswith("=")
                        if has_formula:
                            # 수식 셀은 서식만 적용하고 내용(수식)은 보존
                            target_style.pop("text", None)
                            target_style.pop("replace", None)
                            log_debug(f"수식 셀 내용 치환 생략 (서식만 적용): 셀({start_row + r_idx}, {start_col + c_idx}) {formula_str}")
                        elif text_val is not None and not str(text_val).strip().startswith("="):
                            # 부분 문자열 치환 지원 (Word/PPT와 동작 일치: 기존 셀 내용 내 매칭 키워드만 치환)
                            target_style["text"] = val_str.replace(key_str, str(text_val))
                        apply_edit_to_range(cell_obj, target_style)
                        applied_count += 1
                        log_debug(f"매칭 수정 완료: 셀({start_row + r_idx}, {start_col + c_idx}) = '{val_str}'")

        except Exception as e:
            log_debug(f"검색 수정 적용 중 예외 발생 (key='{key_str}'): {e}")

    if applied_count == 0:
        return format_response(
            status="no_match",
            module="excel_edit",
            action="apply_edits",
            preview="0 cells matched for given edit rules",
            agent_directive="STOP_RETRY: Target text/number not found in sheet. Proceed."
        )

    return format_response(
        status="ok",
        module="excel_edit",
        action="apply_edits",
        preview=f"{applied_count} cell modifications/styles successfully applied",
        agent_directive="VERIFIED: Edits applied. Do not re-verify.",
        extra={"applied_count": applied_count}
    )

def main():
    parser = argparse.ArgumentParser(description="Excel Edit & Professional Theme Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름")
    parser.add_argument("--theme", type=str, help="테마 프리셋(navy, slate, teal, emerald) 또는 테마 JSON 경로")
    parser.add_argument("--range", type=str, help="적용 범위 (예: 'A1:H20', 생략 시 UsedRange)")
    parser.add_argument("--zebra", action="store_true", help="Zebra 줄무늬 교차 배경 적용")
    parser.add_argument("--format-num", type=str, help="숫자 표시 서식 (예: '#,##0', '0.0%%', '₩#,##0')")
    parser.add_argument("--replace-map", type=str, help="styles.json 또는 edit_rules.json 경로")
    parser.add_argument("--rule", type=str, help="조건부 서식 규칙 (예: '>=100:lightgreen', '<80:pink', 'text=완료:green')")
    parser.add_argument("--find", type=str, help="검색할 텍스트 또는 셀 주소")
    parser.add_argument("--replace", type=str, help="치환할 새 텍스트")
    parser.add_argument("--formula", type=str, help="셀에 설정할 수식 (예: '=SUM(B2:B4)')")
    parser.add_argument("--bg", type=str, help="배경색 (yellow, #RRGGBB 등)")
    parser.add_argument("--color", type=str, help="글자색")
    parser.add_argument("--bold", action="store_true", help="굵게")
    parser.add_argument("--size", type=float, help="글꼴 크기")
    parser.add_argument("--align", choices=["left", "center", "right"], help="정렬")
    args = parser.parse_args()

    single_style = {}
    if args.bg: single_style["bg"] = args.bg
    if args.color: single_style["color"] = args.color
    if args.bold: single_style["bold"] = True
    if args.size: single_style["size"] = args.size
    if args.align: single_style["align"] = args.align
    if args.format_num: single_style["number_format"] = args.format_num

    params = {
        "theme": args.theme,
        "range": args.range,
        "zebra": args.zebra if args.zebra else None,
        "format_num": args.format_num,
        "rule": args.rule,
        "mapping_file": args.replace_map,
        "find": args.find,
        "replace": args.replace,
        "formula": args.formula,
        "style": single_style
    }

    with excel_session(target=args.target, sheet_name=args.sheet, snapshot=True) as (app, wb, ws):
        res = execute(wb, ws, params)
        emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: excel_edit.py ===

---

=== FILE: excel_export.py ===

```python
import sys
import os
import csv
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, run_session_tool
from _config import get_data_dir
from _com_guard import excel_session

def resolve_output_path(file_path: str, default_ext: str = ".csv") -> str:
    """출력 경로를 해석하며, 파일명만 지정된 경우 data_dir 하위로 자동 매핑합니다."""
    if not file_path:
        raise ValueError("출력 파일명(output_file)이 지정되지 않았습니다.")
        
    if not os.path.splitext(file_path)[1]:
        file_path += default_ext

    if os.path.isabs(file_path):
        out_path = file_path
    else:
        out_path = os.path.join(get_data_dir(), file_path)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    return os.path.abspath(out_path)

def extract_columns_from_sheet(ws, col_letters: List[str], start_row: Optional[int] = None, end_row: Optional[int] = None) -> List[List[Any]]:
    """지정된 열들(예: ['A', 'C', 'E'])의 데이터를 UsedRange 행 범위에 맞춰 행별로 결합합니다."""
    used = ws.UsedRange
    if start_row is None:
        start_row = used.Row
    if end_row is None:
        end_row = used.Row + used.Rows.Count - 1

    col_data = []
    for col in col_letters:
        col = col.strip().upper()
        # 단일 열 범위 조회 (예: 'A1:A101')
        rng = ws.Range(f"{col}{start_row}:{col}{end_row}")
        val = rng.Value
        
        row_count = end_row - start_row + 1
        if row_count == 1:
            col_data.append([val if val is not None else ""])
        elif isinstance(val, (list, tuple)):
            col_data.append([r[0] if r is not None else "" for r in val])
        else:
            col_data.append([val if val is not None else ""])

    # 행 단위로 결합
    num_rows = len(col_data[0]) if col_data else 0
    matrix = []
    for r_idx in range(num_rows):
        row_vals = [col_data[c_idx][r_idx] for c_idx in range(len(col_letters))]
        matrix.append(row_vals)
    return matrix

def extract_matrix_from_range(rng) -> List[List[Any]]:
    """Range 객체의 값을 직사각형 2D 파이썬 리스트로 변환합니다."""
    val = rng.Value
    row_count = rng.Rows.Count
    col_count = rng.Columns.Count

    if row_count == 1 and col_count == 1:
        return [[val if val is not None else ""]]
    elif row_count == 1:
        return [[c if c is not None else "" for c in val]]
    elif col_count == 1:
        return [[r[0] if r[0] is not None else ""] for r in val]
    else:
        return [[c if c is not None else "" for c in row] for row in val]

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 호출되는 엑셀 내보내기 엔진."""
    target_sheet_name = params.get("sheet")
    rng_address = (params.get("range") or "").strip()
    cols_param = params.get("columns", "")
    out_arg = params.get("output_file") or params.get("output")
    fmt = (params.get("format") or "").lower()

    if not out_arg:
        return format_response(
            status="error",
            module="excel_export",
            action="export",
            preview="output_file parameter is required",
            agent_directive="STOP_RETRY: Missing output file path."
        )

    try:
        # 1. 대상 워크시트 결정
        target_ws = ws
        if target_sheet_name:
            try:
                target_ws = wb.Worksheets(target_sheet_name)
            except Exception as e:
                return format_response(
                    status="no_match",
                    module="excel_export",
                    action="export",
                    preview=f"Sheet '{target_sheet_name}' not found",
                    agent_directive="STOP_RETRY: Target sheet does not exist."
                )

        # 2. 비연속 열(A, C, E 등) 지정 여부 분석
        target_cols = []
        if cols_param:
            target_cols = [c.strip().upper() for c in cols_param.split(",") if c.strip()]
        elif rng_address and ("," in rng_address or ":" in rng_address):
            parts = [p.strip().upper() for p in rng_address.split(",") if p.strip()]
            # 모든 파트가 'A' 또는 'A:A' 형태인 경우 순수 열 목록으로 해석
            if all(len(p) <= 2 or (":" in p and p.split(":")[0] == p.split(":")[1]) for p in parts):
                target_cols = [p.split(":")[0] for p in parts]

        is_col_mode = len(target_cols) > 0

        # 3. 출력 포맷 결정 (확장자 또는 format 인자)
        out_ext = os.path.splitext(out_arg)[1].lower()
        if fmt:
            out_format = fmt
        elif out_ext in [".csv", ".xlsx"]:
            out_format = out_ext[1:]
        else:
            out_format = "csv"

        final_out_path = resolve_output_path(out_arg, default_ext=f".{out_format}")
        
        # 4. 데이터 매트릭스 추출
        if is_col_mode:
            matrix = extract_columns_from_sheet(target_ws, target_cols)
            row_count = len(matrix)
            col_count = len(target_cols)
            source_desc = f"{target_ws.Name} (열: {', '.join(target_cols)})"
        else:
            target_rng = target_ws.Range(rng_address) if rng_address else target_ws.UsedRange
            matrix = extract_matrix_from_range(target_rng)
            row_count = len(matrix)
            col_count = len(matrix[0]) if row_count > 0 else 0
            source_desc = f"{target_ws.Name}!{target_rng.Address}"

        log_debug(f"Export 대상: {source_desc}, 포맷='{out_format}', 경로='{final_out_path}'")

        # A. CSV 내보내기 (한국어 엑셀 2007~365 완벽 호환 인코딩 지원)
        if out_format == "csv":
            csv_encoding = params.get("encoding") or "cp949"
            try:
                with open(final_out_path, "w", encoding=csv_encoding, newline="") as f:
                    writer = csv.writer(f)
                    for row in matrix:
                        writer.writerow([str(v) if v is not None else "" for v in row])
            except UnicodeEncodeError:
                # 특수문자 등으로 cp949 인코딩 실패 시 utf-8-sig로 자동 폴백
                csv_encoding = "utf-8-sig"
                with open(final_out_path, "w", encoding=csv_encoding, newline="") as f:
                    writer = csv.writer(f)
                    for row in matrix:
                        writer.writerow([str(v) if v is not None else "" for v in row])

            preview_msg = f"Exported {row_count} rows x {col_count} cols ({source_desc}) to CSV ({csv_encoding}): {os.path.basename(final_out_path)}"
            return format_response(
                status="ok",
                module="excel_export",
                action="export_csv",
                preview=preview_msg,
                agent_directive="VERIFIED: CSV exported successfully. Active window preserved.",
                extra={
                    "file_path": final_out_path,
                    "rows": row_count,
                    "cols": col_count,
                    "format": "csv"
                }
            )

        # B. XLSX 내보내기 (기존 활성 창 손상 없이 새 독립 워크북으로 저장)
        elif out_format == "xlsx":
            app = wb.Application
            prev_alerts = app.DisplayAlerts
            new_wb = None
            try:
                app.DisplayAlerts = False
                # 새 워크북 생성 (사용자 화면에 새 창이 뜨지 않도록 즉시 숨김)
                new_wb = app.Workbooks.Add()
                try:
                    new_wb.Windows(1).Visible = False
                except Exception:
                    pass
                new_ws = new_wb.Worksheets(1)
                new_ws.Name = target_ws.Name

                if is_col_mode:
                    from _office_utils import get_target_range_address
                    target_range_addr = get_target_range_address("A1", row_count, col_count)
                    new_ws.Range(target_range_addr).Value = tuple(tuple(r) for r in matrix)
                else:
                    target_rng = target_ws.Range(rng_address) if rng_address else target_ws.UsedRange
                    target_rng.Copy(Destination=new_ws.Range("A1"))

                new_ws.Columns.AutoFit()

                # 숨긴 창 상태가 파일에 저장되어 다음에 열 때 안 보이는 문제 방지
                try:
                    new_wb.Windows(1).Visible = True
                except Exception:
                    pass
                new_wb.SaveAs(final_out_path, FileFormat=51)  # xlOpenXMLWorkbook
            finally:
                # 실패하더라도 임시 워크북이 사용자 Excel에 남지 않도록 항상 닫고 경고 설정 복원
                if new_wb is not None:
                    try:
                        new_wb.Close(SaveChanges=False)
                    except Exception:
                        pass
                try:
                    app.DisplayAlerts = prev_alerts
                except Exception:
                    pass

            preview_msg = f"Exported {source_desc} to new XLSX workbook: {os.path.basename(final_out_path)}"
            return format_response(
                status="ok",
                module="excel_export",
                action="export_xlsx",
                preview=preview_msg,
                agent_directive="VERIFIED: XLSX exported successfully. Active window preserved.",
                extra={
                    "file_path": final_out_path,
                    "sheet": target_ws.Name,
                    "format": "xlsx"
                }
            )

        else:
            raise ValueError(f"지원하지 않는 내보내기 형식입니다: {out_format} (csv 또는 xlsx 지원)")

    except Exception as e:
        return format_response(
            status="error",
            module="excel_export",
            action="export",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Export failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Export Micro Block (CSV & XLSX)")
    parser.add_argument("--target", default="active", help="active 또는 엑셀 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름 (생략 시 활성 시트)")
    parser.add_argument("--range", type=str, help="내보낼 셀 범위 (예: A1:C10, 생략 시 UsedRange)")
    parser.add_argument("--columns", "-c", type=str, help="선택적으로 내보낼 열 목록 (예: A,C,E)")
    parser.add_argument("--output", "-o", required=True, help="저장할 파일명 또는 경로 (.csv 또는 .xlsx)")
    parser.add_argument("--format", choices=["csv", "xlsx"], help="출력 포맷 강제 지정")
    parser.add_argument("--encoding", default="cp949", choices=["cp949", "utf-8-sig", "utf-8"], help="CSV 인코딩 (기본값 cp949: 한국어 엑셀 2007~365 완벽 호환)")
    args = parser.parse_args()

    params = {
        "sheet": args.sheet,
        "range": args.range,
        "columns": args.columns,
        "output_file": args.output,
        "format": args.format,
        "encoding": args.encoding
    }

    is_active = (args.target.lower() == "active")
    file_path = args.target if not is_active else None

    # 원본이 디스크의 CSV 파일인 경우: 엑셀에서 열려 있어도 잠금 충돌 없이 파이썬 엔진으로 0.005초 직접 처리
    if not is_active and file_path and file_path.lower().endswith(".csv") and os.path.exists(file_path):
        from _office_utils import read_csv_table
        matrix = read_csv_table(file_path)
        
        # 범위 슬라이싱 (예: A1:C20)
        rng_str = (args.range or "").strip().upper()
        import re
        m = re.match(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$", rng_str)
        if m:
            start_col, start_row, end_col, end_row = m.groups()
            s_row, e_row = int(start_row) - 1, int(end_row)
            
            def col_to_idx(c_str):
                idx = 0
                for ch in c_str:
                    idx = idx * 26 + (ord(ch) - ord('A') + 1)
                return idx - 1
                
            s_col, e_col = col_to_idx(start_col), col_to_idx(end_col) + 1
            sliced_matrix = [row[s_col:e_col] for row in matrix[s_row:e_row]]
        else:
            sliced_matrix = matrix

        out_path = resolve_output_path(args.output, default_ext=".csv")
        csv_encoding = args.encoding or "cp949"
        
        try:
            with open(out_path, "w", encoding=csv_encoding, newline="") as f:
                writer = csv.writer(f)
                for r in sliced_matrix:
                    writer.writerow([str(v) if v is not None else "" for v in r])
        except UnicodeEncodeError:
            csv_encoding = "utf-8-sig"
            with open(out_path, "w", encoding=csv_encoding, newline="") as f:
                writer = csv.writer(f)
                for r in sliced_matrix:
                    writer.writerow([str(v) if v is not None else "" for v in r])

        row_c = len(sliced_matrix)
        col_c = len(sliced_matrix[0]) if row_c > 0 else 0
        emit_response(format_response(
            status="ok",
            module="excel_export",
            action="export_csv_direct",
            preview=f"Exported {row_c} rows x {col_c} cols ({rng_str or 'All'}) from CSV: {os.path.basename(out_path)}",
            agent_directive="VERIFIED: CSV exported successfully without file lock.",
            extra={
                "file_path": out_path,
                "rows": row_c,
                "cols": col_c,
                "format": "csv"
            }
        ))
        return

    run_session_tool("excel_export", "export",
                     lambda: excel_session(target=args.target, sheet_name=args.sheet),
                     lambda app, wb, ws: execute(wb, ws, params))

if __name__ == "__main__":
    main()
```

=== END FILE: excel_export.py ===

---

=== FILE: excel_fill.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, read_csv_table, get_target_range_address, parse_color_to_bgr
from _com_guard import excel_session
from _config import resolve_data_path, get_data_dir

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체로 엑셀 데이터 주입, 수식 계산 및 덧붙이기(Append)를 수행합니다."""
    start_cell = params.get("range", "A1").strip()
    data_file = params.get("data_file")
    value = params.get("value")
    formula = params.get("formula")
    values = params.get("values")
    clear = params.get("clear", False)
    mode = (params.get("mode") or "overwrite").lower()
    autofit = params.get("autofit", True)

    try:
        # 기존 내용 초기화 옵션
        if clear:
            log_debug("시트 기존 내용 초기화 (ClearContents)")
            ws.Cells.ClearContents()

        # 1. 단일 수식(Formula) 주입
        if formula is not None:
            cell = ws.Range(start_cell)
            formula_str = str(formula).strip()
            if not formula_str.startswith("="):
                formula_str = "=" + formula_str
            cell.Formula = formula_str
            if autofit:
                cell.Columns.AutoFit()
            return format_response(
                status="ok",
                module="excel_fill",
                action="formula_fill",
                preview=f"Cell {start_cell} formula set to '{formula_str}'",
                agent_directive="VERIFIED: Excel formula applied and evaluated.",
                extra={"cell": start_cell, "formula": formula_str}
            )

        # 2. 단일 셀 값 쓰기
        if value is not None and not data_file and values is None:
            cell = ws.Range(start_cell)
            val_str = str(value)
            if val_str.startswith("="):
                cell.Formula = val_str
            else:
                cell.Value = value
            if autofit:
                cell.Columns.AutoFit()
            return format_response(
                status="ok",
                module="excel_fill",
                action="single_value",
                preview=f"Cell {start_cell} set to '{value}'",
                agent_directive="VERIFIED: Single cell updated."
            )

        # 3. 표 데이터 수집 (CSV 파일 또는 리스트)
        table_data: List[List[Any]] = []
        if data_file:
            abs_csv = resolve_data_path(data_file)
            if not os.path.exists(abs_csv):
                return format_response(
                    status="no_match",
                    module="excel_fill",
                    action="csv_fill",
                    preview=f"Data file not found: {abs_csv}",
                    agent_directive="STOP_RETRY: Data file missing."
                )
            table_data = read_csv_table(abs_csv)
        elif values:
            table_data = values
        else:
            return format_response(
                status="no_match",
                module="excel_fill",
                action="fill",
                preview="No data provided (data_file, formula, value, or values required)",
                agent_directive="STOP_RETRY: Empty input."
            )

        row_count = len(table_data)
        if row_count == 0:
            return format_response(
                status="no_match",
                module="excel_fill",
                action="fill",
                preview="Empty table data (0 rows)",
                agent_directive="STOP_RETRY: Data contains 0 rows."
            )

        # 4. Append 모드 처리 (기존 표의 마지막 행 다음에 자동 덧붙이기)
        actual_start_cell = start_cell
        if mode == "append":
            used_rng = ws.UsedRange
            # 시트에 내용이 이미 있는 경우 다음 행 탐색
            if used_rng and (used_rng.Rows.Count > 1 or ws.Cells(used_rng.Row, used_rng.Column).Value is not None):
                last_used_row = used_rng.Row + used_rng.Rows.Count - 1
                
                # 시작 셀의 열 문자 추출 (예: 'B5' -> 'B')
                col_letters = "".join([ch for ch in start_cell if ch.isalpha()]) or "A"
                actual_start_cell = f"{col_letters}{last_used_row + 1}"
                log_debug(f"Append 모드: 마지막 행({last_used_row}) 다음인 '{actual_start_cell}'부터 주입 시작")

                # 기존 헤더와 주입 데이터 첫 행이 동일한지 검사하여 중복 헤더 건너뛰기
                if row_count > 1 and ws.Cells(used_rng.Row, used_rng.Column).Value is not None:
                    first_header = [str(c).strip() for c in table_data[0]]
                    existing_header = [str(ws.Cells(used_rng.Row, used_rng.Column + i).Value or "").strip() for i in range(len(first_header))]
                    if first_header == existing_header:
                        log_debug("Append 모드: 중복 헤더 감지 -> 헤더 1행 건너뛰고 데이터만 추가")
                        table_data = table_data[1:]
                        row_count = len(table_data)

        # 행별 최대 열 수 계산 및 직사각형 2D 정규화
        max_col_count = max(len(row) for row in table_data)
        normalized_data = []
        formula_cells = []  # 수식 셀 위치 추적

        for r_idx, r in enumerate(table_data):
            padded_row = []
            for c_idx, item in enumerate(r):
                item_str = str(item).strip() if item is not None else ""
                if item_str.startswith("="):
                    formula_cells.append((r_idx, c_idx, item_str))
                    padded_row.append("")  # 임시 빈값 주입 후 Formula로 설정
                else:
                    padded_row.append(item)
            padded_row.extend([""] * (max_col_count - len(padded_row)))
            normalized_data.append(tuple(padded_row))

        # 대상 범위 계산 (예: 'A1:E20')
        target_range = get_target_range_address(actual_start_cell, row_count, max_col_count)
        log_debug(f"범위 '{target_range}'에 {row_count}행 x {max_col_count}열 2D 배열 고속 대입 (mode={mode})")

        # 1차 대입: 2차원 SafeArray 일괄 고속 주입
        fill_rng = ws.Range(target_range)
        fill_rng.Value = tuple(normalized_data)

        # 2차 대입: 수식이 포함된 셀 정확한 Formula 설정
        if formula_cells:
            start_row = fill_rng.Row
            start_col = fill_rng.Column
            for r_offset, c_offset, f_str in formula_cells:
                try:
                    ws.Cells(start_row + r_offset, start_col + c_offset).Formula = f_str
                except Exception as fe:
                    log_debug(f"수식 설정 예외 ({f_str}): {fe}")

        # 3차 처리: 테마 일괄 서식 (--theme 지원으로 Gemma 4 원스톱 스타일링)
        theme_arg = params.get("theme")
        if theme_arg:
            try:
                from office_theme import resolve_theme
                theme_dict = resolve_theme(theme_arg)
                start_row = fill_rng.Row
                start_col = fill_rng.Column

                # 1) 헤더 스타일 (1행)
                header_cfg = theme_dict.get("header", {})
                h_bg = parse_color_to_bgr(header_cfg.get("bg", theme_dict.get("primary", "#1B365D")))
                h_fg = parse_color_to_bgr(header_cfg.get("color", "#FFFFFF"))
                header_rng = ws.Range(ws.Cells(start_row, start_col), ws.Cells(start_row, start_col + max_col_count - 1))
                if h_bg is not None:
                    header_rng.Interior.Color = h_bg
                if h_fg is not None:
                    header_rng.Font.Color = h_fg
                header_rng.Font.Bold = True
                header_rng.HorizontalAlignment = -4108  # xlCenter

                # 2) 지브라 패턴 & 합계 행 서식
                zebra_cfg = theme_dict.get("zebra", {})
                even_bg = parse_color_to_bgr(zebra_cfg.get("even", "#F4F7FB")) if zebra_cfg.get("enabled", True) else None
                summary_cfg = theme_dict.get("summary", {})
                sum_bg = parse_color_to_bgr(summary_cfg.get("bg", "#E8EEF5"))

                for r_idx in range(1, row_count):
                    curr_cells = ws.Range(ws.Cells(start_row + r_idx, start_col), ws.Cells(start_row + r_idx, start_col + max_col_count - 1))
                    first_val = str(ws.Cells(start_row + r_idx, start_col).Value or "").strip().lower()
                    is_sum = (r_idx == row_count - 1 and any(f[0] == r_idx for f in formula_cells)) or any(k in first_val for k in ["합계", "총계", "total", "sum"])
                    if is_sum:
                        if sum_bg is not None:
                            curr_cells.Interior.Color = sum_bg
                        curr_cells.Font.Bold = True
                    elif even_bg and (r_idx % 2 == 1):
                        curr_cells.Interior.Color = even_bg

                # 3) 실선 얇은 테두리
                try:
                    fill_rng.Borders.LineStyle = 1
                except Exception:
                    pass
                log_debug(f"Excel 표 테마({theme_dict.get('name', theme_arg)}) 일괄 적용 완료")
            except Exception as te:
                log_debug(f"테마 적용 중 예외: {te}")

        # 4차 처리: AutoFit 자동 연계 (열 너비가 좁아 ### 표시 방지)
        if autofit:
            try:
                fill_rng.Columns.AutoFit()
            except Exception:
                pass

        return format_response(
            status="ok",
            module="excel_fill",
            action="bulk_fill",
            preview=f"Range {target_range} filled ({row_count} rows, {max_col_count} cols, mode={mode}, formulas={len(formula_cells)})",
            agent_directive="VERIFIED: Bulk data filled successfully. Do not re-verify.",
            extra={
                "range": target_range,
                "rows": row_count,
                "cols": max_col_count,
                "mode": mode,
                "formula_count": len(formula_cells),
                "theme": theme_arg
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="excel_fill",
            action="fill",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Fill failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Fill Micro Block with Formula & Append Support")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름")
    parser.add_argument("--range", default="A1", help="시작 셀 (예: A1)")
    parser.add_argument("--data-file", type=str, help="주입할 CSV 파일 경로")
    parser.add_argument("--value", type=str, help="단일 셀에 쓸 값")
    parser.add_argument("--formula", type=str, help="단일 셀에 적용할 엑셀 수식 (예: '=SUM(C2:C10)')")
    parser.add_argument("--mode", choices=["overwrite", "append"], default="overwrite", help="덮어쓰기 또는 덧붙이기")
    parser.add_argument("--theme", type=str, help="표 테마 프리셋(navy, slate, teal, emerald) 또는 JSON 파일")
    parser.add_argument("--no-autofit", action="store_true", help="열 너비 자동 맞춤 비활성화")
    parser.add_argument("--clear", action="store_true", help="주입 전 시트 초기화")
    args = parser.parse_args()

    params = {
        "range": args.range,
        "data_file": args.data_file,
        "value": args.value,
        "formula": args.formula,
        "mode": args.mode,
        "theme": args.theme,
        "autofit": not args.no_autofit,
        "clear": args.clear
    }

    with excel_session(target=args.target, sheet_name=args.sheet, snapshot=True) as (app, wb, ws):
        res = execute(wb, ws, params)
        emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: excel_fill.py ===

---

=== FILE: excel_inspect.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, run_session_tool
from _com_guard import excel_session

def inspect_single_worksheet(ws) -> Dict[str, Any]:
    """단일 시트의 사용 범위, 글자 수, 차트 수, 이미지 수를 초고속(인메모리) 계산합니다."""
    sheet_name = ws.Name
    used_range = ws.UsedRange
    rng_address = used_range.Address if used_range is not None else "A1"
    
    # 1. 셀 데이터 한 번에 덤프 (COM 호출 1회로 고속 처리)
    raw_values = used_range.Value if used_range is not None else None
    
    total_chars = 0
    filled_cells = 0
    row_count = used_range.Rows.Count if used_range is not None else 0
    col_count = used_range.Columns.Count if used_range is not None else 0

    preview_rows = []

    if raw_values is not None:
        # 단일 셀 예외 처리
        if row_count == 1 and col_count == 1:
            matrix = [[raw_values]]
        elif row_count == 1:
            matrix = [list(raw_values)]
        elif col_count == 1:
            matrix = [[r[0]] for r in raw_values]
        else:
            matrix = [list(r) for r in raw_values]

        for r_idx, row in enumerate(matrix):
            # 상위 3행 미리보기 수집
            if r_idx < 3:
                preview_rows.append([str(v) if v is not None else "" for v in row[:5]])
                
            for cell_val in row:
                if cell_val is not None and str(cell_val).strip() != "":
                    filled_cells += 1
                    total_chars += len(str(cell_val))

    # 2. 차트 수 및 정보
    charts_info = []
    try:
        chart_count = ws.ChartObjects().Count
        for i in range(1, chart_count + 1):
            ch_obj = ws.ChartObjects(i)
            title_text = ""
            try:
                if ch_obj.Chart.HasTitle:
                    title_text = ch_obj.Chart.ChartTitle.Text
            except Exception:
                pass
            charts_info.append({
                "name": ch_obj.Name,
                "title": title_text
            })
    except Exception:
        chart_count = 0

    # 3. 이미지 및 기타 도형 수
    image_count = 0
    shape_count = 0
    try:
        shape_count = ws.Shapes.Count
        # 순수 그림(Pictures) 수 조회
        try:
            image_count = ws.Pictures().Count
        except Exception:
            # Pictures() 접근 불가 시 Shapes에서 차트 제외한 개수로 추산
            image_count = max(0, shape_count - chart_count)
    except Exception:
        pass

    return {
        "sheet_name": sheet_name,
        "used_range": rng_address,
        "rows": row_count,
        "cols": col_count,
        "filled_cells": filled_cells,
        "character_count": total_chars,
        "chart_count": chart_count,
        "charts": charts_info,
        "image_count": image_count,
        "shape_count": shape_count,
        "preview_sample": preview_rows
    }

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 호출되는 엑셀 상태 검사 엔진."""
    target_sheet = params.get("sheet")
    
    try:
        wb_name = wb.Name
        all_sheet_names = [s.Name for s in wb.Worksheets]

        # 1. 특정 시트만 지정된 경우 (--sheet)
        if target_sheet:
            if target_sheet not in all_sheet_names:
                return format_response(
                    status="no_match",
                    module="excel_inspect",
                    action="inspect_sheet",
                    preview=f"Sheet '{target_sheet}' not found in workbook '{wb_name}'",
                    agent_directive="STOP_RETRY: Target sheet does not exist."
                )
                
            sheet_obj = wb.Worksheets(target_sheet)
            sheet_info = inspect_single_worksheet(sheet_obj)
            
            preview_msg = (
                f"[{target_sheet}] {sheet_info['rows']}행x{sheet_info['cols']}열 "
                f"({sheet_info['used_range']}), 글자: {sheet_info['character_count']}, "
                f"차트: {sheet_info['chart_count']}, 이미지: {sheet_info['image_count']}"
            )
            
            return format_response(
                status="ok",
                module="excel_inspect",
                action="inspect_sheet",
                preview=preview_msg,
                agent_directive="VERIFIED: Single sheet inspected.",
                extra={
                    "workbook": wb_name,
                    "sheet_details": sheet_info
                }
            )

        # 2. 전체 통합 문서 검사 (기본 모드)
        total_chars = 0
        total_filled_cells = 0
        total_charts = 0
        total_images = 0
        sheet_summaries = []

        for s in wb.Worksheets:
            s_info = inspect_single_worksheet(s)
            total_chars += s_info["character_count"]
            total_filled_cells += s_info["filled_cells"]
            total_charts += s_info["chart_count"]
            total_images += s_info["image_count"]
            sheet_summaries.append(s_info)

        active_sheet_name = ""
        try:
            active_sheet_name = wb.ActiveSheet.Name
        except Exception:
            pass

        # 현재 활성 셀 및 선택 범위(Selection) 정보 추출
        selection_info = {}
        try:
            excel_app = getattr(wb, "Application", None)
            if excel_app is not None:
                sel = excel_app.Selection
                act_cell = excel_app.ActiveCell
                sel_addr = str(sel.Address).replace("$", "") if sel is not None else ""
                act_addr = str(act_cell.Address).replace("$", "") if act_cell is not None else ""
                act_val = act_cell.Value if act_cell is not None else None
                act_formula = str(act_cell.Formula) if (act_cell is not None and str(act_cell.Formula).startswith("=")) else ""
                selection_info = {
                    "active_sheet": active_sheet_name,
                    "selected_range": sel_addr,
                    "active_cell": act_addr,
                    "active_cell_value": act_val if act_val is not None else "",
                    "active_cell_formula": act_formula
                }
        except Exception as e:
            log_debug(f"Excel selection info error: {e}")

        # 열려 있는 전체 통합 문서 목록 조회 (모든 Excel 프로세스 전수 조사)
        open_workbooks = []
        try:
            from _com_guard import get_all_running_excel_workbooks
            all_running = get_all_running_excel_workbooks()
            for item in all_running:
                open_workbooks.append({
                    "name": item["name"],
                    "path": item["path"],
                    "saved": item.get("saved", True),
                    "sheets": item.get("sheets", []),
                    "active": (item["name"] == wb_name)
                })
        except Exception as e:
            log_debug(f"전체 열린 문서 조회 실패: {e}")

        if not open_workbooks:
            open_workbooks = [{"name": wb_name, "path": getattr(wb, "FullName", ""), "active": True}]

        open_wb_names = [w["name"] for w in open_workbooks]
        sel_desc = f"선택: {selection_info.get('selected_range') or selection_info.get('active_cell') or '없음'}"
        summary_preview = (
            f"열린 문서: {len(open_workbooks)}개 ({', '.join(open_wb_names)}) | 활성: {wb_name} [{active_sheet_name}] ({sel_desc}) | "
            f"시트 {len(all_sheet_names)}개 ({', '.join(all_sheet_names)}) | "
            f"총 글자 수: {total_chars}자 | 차트: {total_charts}개 | 이미지: {total_images}개"
        )

        return format_response(
            status="ok",
            module="excel_inspect",
            action="inspect_workbook",
            preview=summary_preview,
            agent_directive="VERIFIED: Inspection complete. State verified.",
            extra={
                "workbook": wb_name,
                "open_workbooks": open_workbooks,
                "total_open_workbooks": len(open_workbooks),
                "active_sheet": active_sheet_name,
                "selection": selection_info,
                "sheets": all_sheet_names,
                "total_sheets": len(all_sheet_names),
                "total_character_count": total_chars,
                "total_filled_cells": total_filled_cells,
                "total_charts_count": total_charts,
                "total_images_count": total_images,
                "sheet_summaries": sheet_summaries
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="excel_inspect",
            action="inspect",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Inspection failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Inspection Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 엑셀 파일 경로")
    parser.add_argument("--sheet", type=str, help="검사할 특정 시트 이름 (생략 시 전체 문서 검사)")
    parser.add_argument("--list-workbooks", "--all", dest="list_workbooks", action="store_true", help="실행 중인 모든 Excel 프로세스의 통합 문서 목록만 고속 조회")
    args = parser.parse_args()

    if args.list_workbooks:
        from _com_guard import get_all_running_excel_workbooks
        all_running = get_all_running_excel_workbooks()
        workbooks_summary = []
        for item in all_running:
            workbooks_summary.append({
                "name": item["name"],
                "path": item["path"],
                "saved": item.get("saved", True),
                "sheets": item.get("sheets", []),
                "active": item.get("is_active", False)
            })

        names_preview = ", ".join([f"{w['name']}{' (Active)' if w['active'] else ''}" for w in workbooks_summary])
        res = format_response(
            status="ok",
            module="excel_inspect",
            action="list_workbooks",
            preview=f"총 {len(workbooks_summary)}개의 열린 엑셀 문서 감지: [{names_preview}]",
            agent_directive="VERIFIED: Running workbooks enumerated across all Excel processes.",
            extra={
                "total_count": len(workbooks_summary),
                "workbooks": workbooks_summary
            }
        )
        emit_response(res)
        return

    params = {"sheet": args.sheet}

    run_session_tool("excel_inspect", "inspect",
                     lambda: excel_session(target=args.target, sheet_name=args.sheet),
                     lambda app, wb, ws: execute(wb, ws, params))

if __name__ == "__main__":
    main()
```

=== END FILE: excel_inspect.py ===

---

=== FILE: excel_range.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import excel_session

# Excel Borders 상수 매핑
BORDER_WEIGHTS = {
    "hairline": 1,
    "thin": 2,
    "medium": -4138,
    "thick": 4
}

def apply_borders(rng, weight: str = "thin", box_only: bool = False) -> None:
    """Range 객체에 테두리를 적용합니다."""
    w = BORDER_WEIGHTS.get(weight.lower(), 2)
    if box_only:
        # 외곽 테두리 (BorderAround)
        rng.BorderAround(Weight=w)
    else:
        # 전체 그리드 테두리 (상하좌우 및 내부 가로/세로선)
        for border_id in [7, 8, 9, 10, 11, 12]:  # xlEdgeLeft, Top, Bottom, Right, InsideVertical, InsideHorizontal
            try:
                rng.Borders(border_id).Weight = w
                rng.Borders(border_id).LineStyle = 1  # xlContinuous
            except Exception:
                pass

def resolve_sheet_range(wb, ws, address: str):
    """'A1:C10', 'Sheet1!A1', "'My Sheet'!A1" 형태의 주소를 Range 객체로 해석합니다."""
    if "!" in address:
        sheet_part, cell_part = address.rsplit("!", 1)
        sheet_part = sheet_part.strip()
        if len(sheet_part) >= 2 and sheet_part[0] == "'" and sheet_part[-1] == "'":
            sheet_part = sheet_part[1:-1].replace("''", "'")
        return wb.Worksheets(sheet_part).Range(cell_part)
    return ws.Range(address)

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체로 셀 범위 조작(AutoFit, 테두리, 너비/높이, 병합, 틀고정, 숨김)을 수행합니다."""
    action = (params.get("action") or "autofit").lower()
    rng_address = (params.get("range") or "").strip()
    dest_address = (params.get("dest") or "").strip()

    try:
        # 대상 범위 지정 (생략 시 UsedRange, 시트명 포함 시 'Sheet1!A1:C10' 자동 해석)
        target_rng = resolve_sheet_range(wb, ws, rng_address) if rng_address else ws.UsedRange

        if action == "autofit":
            target_rng.Columns.AutoFit()
            if params.get("rows"):
                target_rng.Rows.AutoFit()
            return format_response(
                status="ok",
                module="excel_range",
                action="autofit",
                preview=f"AutoFit applied to {rng_address or 'UsedRange'}",
                agent_directive="VERIFIED: Column width adjusted."
            )

        elif action == "borders":
            weight = params.get("weight", "thin")
            box_only = params.get("box", False)
            apply_borders(target_rng, weight=weight, box_only=box_only)
            return format_response(
                status="ok",
                module="excel_range",
                action="borders",
                preview=f"Borders ({weight}) applied to {rng_address or 'UsedRange'}",
                agent_directive="VERIFIED: Borders drawn."
            )

        elif action == "width":
            col_width = params.get("width")
            if col_width is None:
                raise ValueError("'width' 파라미터가 필요합니다.")
            target_rng.ColumnWidth = float(col_width)
            return format_response(
                status="ok",
                module="excel_range",
                action="width",
                preview=f"Column width of {rng_address} set to {col_width}",
                agent_directive="VERIFIED: Width set."
            )

        elif action == "height":
            row_height = params.get("height")
            if row_height is None:
                raise ValueError("'height' 파라미터가 필요합니다.")
            target_rng.RowHeight = float(row_height)
            return format_response(
                status="ok",
                module="excel_range",
                action="height",
                preview=f"Row height of {rng_address} set to {row_height}",
                agent_directive="VERIFIED: Height set."
            )

        elif action == "merge":
            # 범위 생략 시 UsedRange 전체가 병합되는 사고 방지
            if not rng_address:
                raise ValueError("'merge' 작업에는 병합할 범위(range)를 반드시 지정해야 합니다.")
            # 여러 셀에 값이 있으면 '왼쪽 위 값만 유지' 확인 대화상자가 COM 호출을 멈추게 하므로 일시적으로 끔
            xl_app = ws.Application
            prev_alerts = xl_app.DisplayAlerts
            xl_app.DisplayAlerts = False
            try:
                target_rng.Merge()
            finally:
                xl_app.DisplayAlerts = prev_alerts
            return format_response(
                status="ok",
                module="excel_range",
                action="merge",
                preview=f"Range {rng_address} merged",
                agent_directive="VERIFIED: Cells merged."
            )

        elif action == "unmerge":
            target_rng.UnMerge()
            return format_response(
                status="ok",
                module="excel_range",
                action="unmerge",
                preview=f"Range {rng_address} unmerged",
                agent_directive="VERIFIED: Cells unmerged."
            )

        elif action in ["freeze", "freeze_panes"]:
            # 틀 고정: 대상 셀 기준으로 헤더/열 고정
            ws.Activate()
            split_cell = target_rng.Cells(1, 1)
            split_cell.Select()
            win = ws.Application.ActiveWindow
            win.FreezePanes = False
            win.FreezePanes = True
            return format_response(
                status="ok",
                module="excel_range",
                action="freeze",
                preview=f"Freeze panes activated at {split_cell.Address}",
                agent_directive="VERIFIED: Freeze panes applied."
            )

        elif action in ["unfreeze", "unfreeze_panes"]:
            win = ws.Application.ActiveWindow
            win.FreezePanes = False
            return format_response(
                status="ok",
                module="excel_range",
                action="unfreeze",
                preview="Freeze panes removed",
                agent_directive="VERIFIED: Freeze panes removed."
            )

        elif action == "hide":
            axis = (params.get("axis") or ("rows" if params.get("rows") else "columns")).lower()
            if "row" in axis:
                target_rng.EntireRow.Hidden = True
            else:
                target_rng.EntireColumn.Hidden = True
            return format_response(
                status="ok",
                module="excel_range",
                action="hide",
                preview=f"Hidden {axis} in {rng_address}",
                agent_directive="VERIFIED: Hidden."
            )

        elif action == "unhide":
            axis = (params.get("axis") or ("rows" if params.get("rows") else "columns")).lower()
            if "row" in axis:
                target_rng.EntireRow.Hidden = False
            else:
                target_rng.EntireColumn.Hidden = False
            return format_response(
                status="ok",
                module="excel_range",
                action="unhide",
                preview=f"Unhidden {axis} in {rng_address}",
                agent_directive="VERIFIED: Unhidden."
            )

        elif action == "clear":
            clear_type = (params.get("type") or "all").lower()
            if clear_type == "contents":
                target_rng.ClearContents()
            elif clear_type == "formats":
                target_rng.ClearFormats()
            else:
                target_rng.Clear()

            charts_deleted = 0
            if params.get("charts"):
                try:
                    ch_objs = ws.ChartObjects()
                    charts_deleted = ch_objs.Count
                    ch_objs.Delete()
                except Exception:
                    pass

            preview_msg = f"Range {rng_address or 'UsedRange'} cleared ({clear_type})"
            if charts_deleted > 0:
                preview_msg += f", and {charts_deleted} charts deleted"

            return format_response(
                status="ok",
                module="excel_range",
                action="clear",
                preview=preview_msg,
                agent_directive="VERIFIED: Range cleared."
            )

        elif action in ["copy", "move"]:
            if not dest_address:
                raise ValueError(f"'{action}' 작업에는 'dest' 대상 셀 주소가 필요합니다.")
            
            dest_rng = resolve_sheet_range(wb, ws, dest_address)

            if action == "copy":
                target_rng.Copy(Destination=dest_rng)
            else:
                # move: Excel 네이티브 잘라내기 이동 (원본/대상 범위가 겹쳐도 데이터가 사라지지 않고 수식 참조도 갱신됨)
                target_rng.Cut(Destination=dest_rng)

            return format_response(
                status="ok",
                module="excel_range",
                action=action,
                preview=f"Range {rng_address} {action}d to {dest_address}",
                agent_directive=f"VERIFIED: Range {action}d successfully."
            )

        else:
            raise ValueError(f"알 수 없는 action: {action}")

    except Exception as e:
        return format_response(
            status="error",
            module="excel_range",
            action=action,
            preview=str(e),
            agent_directive=f"STOP_RETRY: Range action failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Range Operations Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름")
    parser.add_argument("--action", required=True, choices=["autofit", "borders", "width", "height", "merge", "unmerge", "freeze", "unfreeze", "hide", "unhide", "clear", "copy", "move"], help="수행할 작업")
    parser.add_argument("--range", help="대상 셀 범위 (예: A1:D10, A:B, 생략 시 UsedRange)")
    parser.add_argument("--dest", help="복사/이동 대상 셀 (예: Sheet2!A1)")
    parser.add_argument("--width", type=float, help="열 너비 값")
    parser.add_argument("--height", type=float, help="행 높이 값")
    parser.add_argument("--weight", choices=["hairline", "thin", "medium", "thick"], default="thin", help="테두리 두께")
    parser.add_argument("--box", action="store_true", help="외곽 테두리만 적용")
    parser.add_argument("--axis", choices=["rows", "columns"], default="columns", help="hide/unhide 대상 축")
    parser.add_argument("--type", choices=["all", "contents", "formats"], default="all", help="지우기(clear) 유형")
    parser.add_argument("--charts", action="store_true", help="지우기(clear) 시 시트 내 차트도 함께 삭제")
    args = parser.parse_args()

    params = {
        "action": args.action,
        "range": args.range,
        "dest": args.dest,
        "width": args.width,
        "height": args.height,
        "weight": args.weight,
        "box": args.box,
        "axis": args.axis,
        "type": args.type,
        "charts": args.charts
    }

    with excel_session(target=args.target, sheet_name=args.sheet, snapshot=True) as (app, wb, ws):
        res = execute(wb, ws, params)
        emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: excel_range.py ===

---

=== FILE: excel_read.py ===

```python
import sys
import os
import hashlib
import json
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, run_session_tool
from _com_guard import excel_session
from _cache import get_file_cache, save_file_cache

def read_cells_to_matrix(rng) -> List[List[Any]]:
    """Range 객체의 값을 직사각형 2D 파이썬 리스트로 변환합니다."""
    val = rng.Value
    row_count = rng.Rows.Count
    col_count = rng.Columns.Count

    if row_count == 1 and col_count == 1:
        return [[val if val is not None else ""]]
    elif row_count == 1:
        return [[c if c is not None else "" for c in val]]
    elif col_count == 1:
        return [[r[0] if r[0] is not None else ""] for r in val]
    else:
        return [[c if c is not None else "" for c in row] for row in val]

def execute(wb=None, ws=None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체 또는 캐시를 통해 엑셀 데이터를 고속 조회합니다."""
    if params is None and isinstance(wb, dict):
        params = wb
        wb = None
        ws = None
    if params is None:
        params = {}

    rng_address = (params.get("range") or "").strip()
    search_keyword = (params.get("search") or "").strip()
    search_color = (params.get("color") or "").strip().lower()
    output_format = (params.get("format") or "table").lower()
    
    file_path = params.get("file_path") or (params.get("target") if params.get("target", "active").lower() != "active" else None)
    is_active = (params.get("target", "active").lower() == "active") and (not file_path)

    # 1. 파일 대상이고 캐시 유효 시 (Active OFF vs File ON)
    if not is_active and file_path and os.path.exists(file_path):
        cached_payload = get_file_cache(file_path, sub_key=f"{rng_address}_{output_format}")
        if cached_payload:
            return format_response(
                status="ok",
                module="excel_read",
                action="read_cached",
                preview=f"Read from cache ({len(cached_payload.get('data', []))} rows)",
                agent_directive="VERIFIED: Data retrieved from disk cache.",
                extra=cached_payload
            )

    # 2. 순수 CSV 파일인 경우: COM 없이 초고속 읽기
    if not is_active and file_path and file_path.lower().endswith(".csv") and os.path.exists(file_path):
        from _office_utils import read_csv_table
        matrix = read_csv_table(file_path)
        row_count = len(matrix)
        col_count = len(matrix[0]) if row_count > 0 else 0
        items = []
        for r_idx, row in enumerate(matrix):
            row_str = " | ".join(str(c) for c in row if c is not None and str(c).strip() != "")
            if row_str.strip():
                items.append({"loc": f"Row {r_idx + 1}", "row": r_idx + 1, "text": row_str})
        result_payload = {
            "range": f"A1:{row_count}x{col_count}",
            "rows": row_count,
            "cols": col_count,
            "items": items,
            "data": matrix if output_format == "table" else []
        }
        save_file_cache(file_path, result_payload, sub_key=f"{rng_address}_{output_format}", max_keep=2)
        return format_response(
            status="ok",
            module="excel_read",
            action="read_csv_direct",
            preview=f"Read {row_count} rows x {col_count} cols from CSV: {os.path.basename(file_path)}",
            agent_directive="VERIFIED: CSV read successfully without Excel COM overhead.",
            extra=result_payload
        )

    # 3. COM 객체가 주어지지 않은 경우 excel_session으로 열기
    if ws is None:
        target_name = file_path if (file_path and os.path.exists(file_path)) else "active"
        with excel_session(target=target_name, sheet_name=params.get("sheet")) as (s_app, s_wb, s_ws):
            return execute(s_wb, s_ws, params)

    # 4. 실시간 COM 조회 (활성창이거나 캐시 미스)
    try:
        target_rng = ws.Range(rng_address) if rng_address else ws.UsedRange
        matrix = read_cells_to_matrix(target_rng)
        row_count = len(matrix)
        col_count = len(matrix[0]) if row_count > 0 else 0

        # 검색 키워드가 있는 경우 필터링
        matched_cells = []
        if search_keyword:
            kw = search_keyword.lower()
            for r_idx, row in enumerate(matrix):
                for c_idx, val in enumerate(row):
                    if kw in str(val).lower():
                        matched_cells.append({"row": r_idx + 1, "col": c_idx + 1, "value": val})

        # 배경색 필터링 (search_color)
        color_matches = []
        if search_color:
            try:
                cell_count = target_rng.CountLarge if hasattr(target_rng, "CountLarge") else target_rng.Count
                scan_rng = target_rng if cell_count <= 2500 else ws.Range("A1:Z50")
                for cell in scan_rng.Cells:
                    try:
                        int_color = int(cell.Interior.Color)
                        has_fill = (cell.Interior.ColorIndex != -4142) and (cell.Interior.Pattern != -4142)
                        if has_fill:
                            r = int_color & 0xFF
                            g = (int_color >> 8) & 0xFF
                            b = (int_color >> 16) & 0xFF
                            hex_color = f"#{r:02X}{g:02X}{b:02X}"
                            addr = str(cell.Address).replace("$", "")
                            is_red = (r > 180 and g < 70 and b < 70)
                            match = False
                            if search_color in ("red", "빨강", "빨간색", "#ff0000") and is_red:
                                match = True
                            elif search_color in hex_color.lower():
                                match = True
                            elif search_color in ("any", "all", "*"):
                                match = True

                            if match:
                                color_matches.append({
                                    "address": addr,
                                    "color": hex_color,
                                    "rgb": [r, g, b],
                                    "value": cell.Value
                                })
                    except Exception:
                        pass
            except Exception as e:
                log_debug(f"Color scan error: {e}")

        items = []
        for r_idx, row in enumerate(matrix):
            row_str = " | ".join(str(c) for c in row if c is not None and str(c).strip() != "")
            if row_str.strip():
                items.append({"loc": f"Row {r_idx + 1}", "row": r_idx + 1, "text": row_str})

        result_payload = {
            "range": rng_address or ws.UsedRange.Address,
            "rows": row_count,
            "cols": col_count,
            "items": items,
            "data": matrix if output_format == "table" else []
        }

        if row_count == 1 and col_count == 1:
            try:
                formula_val = target_rng.Formula
                if formula_val and str(formula_val).startswith("="):
                    result_payload["formula"] = str(formula_val)
            except Exception:
                pass

        if search_keyword:
            result_payload["matched"] = matched_cells
            if len(matched_cells) == 0:
                return format_response(
                    status="no_match",
                    module="excel_read",
                    action="search",
                    preview=f"Found 0 cells matching '{search_keyword}'",
                    agent_directive=f"STOP_RETRY: Keyword '{search_keyword}' not found.",
                    extra=result_payload
                )
            preview_msg = f"Found {len(matched_cells)} cells matching '{search_keyword}'"
        elif search_color:
            result_payload["colored_cells"] = color_matches
            if len(color_matches) == 0:
                return format_response(
                    status="no_match",
                    module="excel_read",
                    action="search_color",
                    preview=f"Found 0 cells with color '{search_color}'",
                    agent_directive=f"STOP_RETRY: No cells found with color '{search_color}'.",
                    extra=result_payload
                )
            matched_addrs = ", ".join(c["address"] for c in color_matches[:12])
            preview_msg = f"Found {len(color_matches)} cells matching color '{search_color}': {matched_addrs}"
        else:
            preview_msg = f"Read {row_count} rows x {col_count} cols ({result_payload['range']})"

        # 파일 대상인 경우 캐시 파일 생성 (최근 2개 유지 정책 적용)
        if not is_active and file_path and os.path.exists(file_path):
            save_file_cache(file_path, result_payload, sub_key=f"{rng_address}_{output_format}", max_keep=2)

        return format_response(
            status="ok",
            module="excel_read",
            action="read",
            preview=preview_msg,
            agent_directive="VERIFIED: Data read successfully.",
            extra=result_payload
        )

    except Exception as e:
        return format_response(
            status="error",
            module="excel_read",
            action="read",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Read failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Read Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--sheet", type=str, help="대상 시트 이름")
    parser.add_argument("--range", type=str, help="조회할 범위 (생략 시 UsedRange)")
    parser.add_argument("--search", type=str, help="검색할 키워드")
    parser.add_argument("--color", type=str, help="검색할 셀 배경색 (예: red, #FF0000, any)")
    parser.add_argument("--format", default="table", choices=["table", "summary"])
    args = parser.parse_args()

    is_active = (args.target.lower() == "active")
    file_path = args.target if not is_active else None

    # 1. 초고속 캐시 선조회 (캐시 히트 시 프로세스 실행 일체 없이 0.005초 반환)
    sub_key = f"{(args.range or '').strip()}_{args.format}"
    if not is_active and file_path and os.path.exists(file_path):
        cached_payload = get_file_cache(file_path, sub_key=sub_key)
        if cached_payload:
            emit_response(format_response(
                status="ok",
                module="excel_read",
                action="read_cached",
                preview=f"Read from cache ({len(cached_payload.get('data', []))} rows)",
                agent_directive="VERIFIED: Data retrieved from disk cache.",
                extra=cached_payload
            ))
            return

    # 2. 순수 CSV 파일인 경우: 엑셀 COM을 띄우지 않고 파이썬 엔진으로 0.001초 무결성 고속 읽기
    if not is_active and file_path and file_path.lower().endswith(".csv") and os.path.exists(file_path):
        from _office_utils import read_csv_table
        matrix = read_csv_table(file_path)
        row_count = len(matrix)
        col_count = len(matrix[0]) if row_count > 0 else 0
        
        result_payload = {
            "range": f"A1:{row_count}x{col_count}",
            "rows": row_count,
            "cols": col_count,
            "data": matrix if args.format == "table" else []
        }
        
        # 캐시 저장 (최근 2개 유지)
        save_file_cache(file_path, result_payload, sub_key=sub_key, max_keep=2)
        
        emit_response(format_response(
            status="ok",
            module="excel_read",
            action="read_csv_direct",
            preview=f"Read {row_count} rows x {col_count} cols from CSV: {os.path.basename(file_path)}",
            agent_directive="VERIFIED: CSV read successfully without Excel COM overhead.",
            extra=result_payload
        ))
        return

    params = {
        "range": args.range,
        "search": args.search,
        "color": args.color,
        "format": args.format,
        "target": args.target,
        "file_path": file_path
    }

    run_session_tool("excel_read", "read",
                     lambda: excel_session(target=args.target, sheet_name=args.sheet),
                     lambda app, wb, ws: execute(wb, ws, params))

if __name__ == "__main__":
    main()
```

=== END FILE: excel_read.py ===

---

=== FILE: excel_sheet.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import excel_session

def execute(wb, ws, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py에서 주입받은 COM 객체로 시트 관리 작업을 수행합니다."""
    action = params.get("action", "select").lower()
    name = params.get("name") or params.get("sheet")
    new_name = params.get("new_name") or params.get("new_sheet")
    
    try:
        sheet_names = [s.Name for s in wb.Worksheets]
        
        if action == "list":
            return format_response(
                status="ok",
                module="excel_sheet",
                action="list",
                preview=f"Sheets: {', '.join(sheet_names)}",
                agent_directive="VERIFIED: Sheet list retrieved.",
                extra={"sheets": sheet_names}
            )
            
        elif action == "ensure":
            # 이미 있으면 활성화, 없으면 새로 생성
            if not name:
                raise ValueError("'name' 파라미터가 필요합니다.")
            if name.lower() in ["active", "current", "현재"]:
                # 모델이 target처럼 'active'를 전달했을 때 빈 시트를 새로 만들지 않고 활성 시트를 유지
                active_ws = wb.ActiveSheet
                return format_response(
                    status="ok",
                    module="excel_sheet",
                    action="ensure",
                    preview=f"Active sheet '{active_ws.Name}' kept as active",
                    agent_directive="VERIFIED: Active sheet ready.",
                    extra={"sheet": active_ws.Name}
                )
            if name in sheet_names:
                target_sheet = wb.Worksheets(name)
                target_sheet.Activate()
                return format_response(
                    status="ok",
                    module="excel_sheet",
                    action="ensure",
                    preview=f"Sheet '{name}' already exists and activated",
                    agent_directive="VERIFIED: Sheet ready."
                )
            else:
                new_sheet = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
                new_sheet.Name = name
                new_sheet.Activate()
                return format_response(
                    status="ok",
                    module="excel_sheet",
                    action="ensure",
                    preview=f"Sheet '{name}' created and activated",
                    agent_directive="VERIFIED: Sheet created."
                )

        elif action == "add":
            new_sheet = wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
            if name:
                new_sheet.Name = name
            new_sheet.Activate()
            return format_response(
                status="ok",
                module="excel_sheet",
                action="add",
                preview=f"Sheet '{new_sheet.Name}' added",
                agent_directive="VERIFIED: Sheet added."
            )

        elif action == "rename":
            if not name or not new_name:
                raise ValueError("'name'과 'new_name' 파라미터가 필요합니다.")
            if name not in sheet_names:
                return format_response(
                    status="no_match",
                    module="excel_sheet",
                    action="rename",
                    preview=f"Sheet '{name}' not found",
                    agent_directive="STOP_RETRY: Sheet does not exist."
                )
            wb.Worksheets(name).Name = new_name
            return format_response(
                status="ok",
                module="excel_sheet",
                action="rename",
                preview=f"Sheet '{name}' renamed to '{new_name}'",
                agent_directive="VERIFIED: Sheet renamed."
            )

        elif action == "copy":
            if not name or not new_name:
                raise ValueError("'name'과 'new_name' 파라미터가 필요합니다.")
            src_sheet = wb.Worksheets(name)
            src_sheet.Copy(After=wb.Worksheets(wb.Worksheets.Count))
            copied_sheet = wb.Worksheets(wb.Worksheets.Count)
            copied_sheet.Name = new_name
            return format_response(
                status="ok",
                module="excel_sheet",
                action="copy",
                preview=f"Sheet '{name}' copied to '{new_name}'",
                agent_directive="VERIFIED: Sheet copied."
            )

        elif action == "delete":
            if not name:
                raise ValueError("'name' 파라미터가 필요합니다.")
            if name not in sheet_names:
                return format_response(
                    status="no_match",
                    module="excel_sheet",
                    action="delete",
                    preview=f"Sheet '{name}' not found",
                    agent_directive="STOP_RETRY: Sheet does not exist."
                )
            if wb.Worksheets.Count <= 1:
                raise ValueError("통합 문서에 시트가 1개만 있어 삭제할 수 없습니다.")
            wb.Application.DisplayAlerts = False
            wb.Worksheets(name).Delete()
            wb.Application.DisplayAlerts = True
            return format_response(
                status="ok",
                module="excel_sheet",
                action="delete",
                preview=f"Sheet '{name}' deleted",
                agent_directive="VERIFIED: Sheet deleted."
            )

        elif action == "select":
            if not name:
                raise ValueError("'name' 파라미터가 필요합니다.")
            if name not in sheet_names:
                return format_response(
                    status="no_match",
                    module="excel_sheet",
                    action="select",
                    preview=f"Sheet '{name}' not found",
                    agent_directive="STOP_RETRY: Sheet does not exist."
                )
            wb.Worksheets(name).Activate()
            return format_response(
                status="ok",
                module="excel_sheet",
                action="select",
                preview=f"Sheet '{name}' activated",
                agent_directive="VERIFIED: Sheet activated."
            )

        else:
            raise ValueError(f"알 수 없는 시트 액션입니다: {action}")

    except Exception as e:
        return format_response(
            status="error",
            module="excel_sheet",
            action=action,
            preview=str(e),
            agent_directive=f"STOP_RETRY: Sheet action '{action}' failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Excel Sheet Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 파일 경로")
    parser.add_argument("--action", default="list", choices=["list", "ensure", "add", "rename", "copy", "delete", "select"])
    parser.add_argument("--name", "--sheet", dest="name", type=str, help="대상 시트 이름")
    parser.add_argument("--new-name", "--new-sheet", dest="new_name", type=str, help="새 시트 이름")
    args = parser.parse_args()

    params = {"action": args.action, "name": args.name, "new_name": args.new_name}
    
    with excel_session(target=args.target, snapshot=True) as (app, wb, ws):
        res = execute(wb, ws, params)
        emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: excel_sheet.py ===

---

=== FILE: hwp_read.py ===

```python
import sys
import os
import zlib
import zipfile
import argparse
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_data_dir
from _cache import get_file_cache, save_file_cache

def is_heading_candidate(p_text: str) -> bool:
    """단락이 제목/소제목(Heading)인지 패턴으로 판별합니다."""
    if not p_text or len(p_text) > 80:
        return False
    text_clean = p_text.strip()
    import re
    heading_patterns = [
        r"^\[.+\]$",                   # [소제목]
        r"^【.+】$",                  # 【서식】
        r"^[0-9]+[.\s]+.+",            # 1. 개요, 2. 추진 배경
        r"^[0-9]+-[0-9]+[.\s]+.+",     # 1-1. 세부 사항
        r"^[0-9]+\.[0-9]+[.\s]+.+",    # 1.1 개요
        r"^[IVXLCDM]+[.\s]+.+",        # I. 추진 배경
        r"^[가-힣][.\s)]+.+",          # 가. 추진 일정, 1) 세부 항목
        r"^제\s*[0-9]+\s*장.+",        # 제1장 총칙
    ]
    for pat in heading_patterns:
        if re.match(pat, text_clean):
            return True
    return False

def resolve_target_file(target: str) -> str:
    """대상 HWP/HWPX 파일 경로를 해석하며, 상대 경로 시 data_dir 또는 CWD에서 탐색합니다."""
    if not target:
        raise ValueError("대상 파일 경로(target)가 필요합니다.")
    if os.path.isabs(target):
        if os.path.exists(target):
            return target
    # 1. C:\cli_data\data 탐색
    cli_candidate = os.path.join(r"C:\cli_data\data", target)
    if os.path.exists(cli_candidate):
        return os.path.abspath(cli_candidate)
    # 2. data_dir 탐색
    data_candidate = os.path.join(get_data_dir(), target)
    if os.path.exists(data_candidate):
        return os.path.abspath(data_candidate)
    # 2. CWD 탐색
    cwd_candidate = os.path.abspath(target)
    if os.path.exists(cwd_candidate):
        return cwd_candidate
    raise FileNotFoundError(f"HWP 파일을 찾을 수 없습니다: {target}")

def extract_hwp_binary_ole(abs_path: str) -> Dict[str, Any]:
    """바이너리 HWP 5.0 (OLE 포맷) 파일에서 순수 텍스트를 고속 추출합니다."""
    import olefile

    if not olefile.isOleFile(abs_path):
        raise ValueError("표준 HWP 5.0 OLE 포맷이 아닙니다.")

    ole = olefile.OleFileIO(abs_path)
    dirs = ole.listdir()
    sections = [d for d in dirs if len(d) >= 2 and d[0] == 'BodyText' and d[1].startswith('Section')]
    sections.sort()

    paragraphs = []
    
    # 확장 컨트롤 코드 목록 (16바이트 추가 정보 포함 태그)
    EXTENDED_CONTROLS = {4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31}

    for sec in sections:
        stream = ole.openstream(sec)
        data = stream.read()
        try:
            decompressed = zlib.decompress(data, -15)
        except Exception:
            try:
                decompressed = zlib.decompress(data)
            except Exception:
                decompressed = data

        idx = 0
        while idx < len(decompressed):
            if idx + 4 > len(decompressed):
                break
            header = int.from_bytes(decompressed[idx:idx+4], 'little')
            tag_id = header & 0x3FF
            size = (header >> 20) & 0xFFF
            idx += 4
            if size == 0xFFF:
                size = int.from_bytes(decompressed[idx:idx+4], 'little')
                idx += 4

            rec = decompressed[idx:idx+size]
            idx += size

            if tag_id == 67:  # HWPTAG_PARA_TEXT
                chars = []
                c_idx = 0
                while c_idx < len(rec):
                    code = int.from_bytes(rec[c_idx:c_idx+2], 'little')
                    c_idx += 2
                    if code in (10, 13):
                        chars.append('\n')
                    elif code in (1, 2, 3):
                        continue
                    elif code in EXTENDED_CONTROLS:
                        c_idx += 16  # 16바이트 제어 속성 스킵
                    elif code >= 32:
                        chars.append(chr(code))
                
                line = ''.join(chars).strip()
                if line:
                    paragraphs.append(line)

    ole.close()
    return {
        "format_type": "HWP 5.0 (OLE)",
        "paragraphs": paragraphs,
        "full_text": "\n".join(paragraphs)
    }

def extract_hwpx_zip(abs_path: str) -> Dict[str, Any]:
    """신규 HWPX (XML Zip 포맷) 파일에서 텍스트를 추출합니다."""
    paragraphs = []
    with zipfile.ZipFile(abs_path, 'r') as z:
        section_files = [f for f in z.namelist() if f.startswith("Contents/section") and f.endswith(".xml")]
        section_files.sort()
        for sf in section_files:
            xml_data = z.read(sf)
            root = ET.fromstring(xml_data)
            # 모든 <hp:t> 태그 텍스트 수집
            for elem in root.iter():
                if elem.tag.endswith("}t") or elem.tag == "t":
                    if elem.text:
                        txt = elem.text.strip()
                        if txt:
                            paragraphs.append(txt)

    return {
        "format_type": "HWPX (XML Zip)",
        "paragraphs": paragraphs,
        "full_text": "\n".join(paragraphs)
    }

def extract_hwp_data(abs_path: str) -> Dict[str, Any]:
    """HWP 또는 HWPX 파일 형식을 자동 감지하여 텍스트를 추출합니다."""
    # 1. HWPX (Zip 파일) 검사
    if zipfile.is_zipfile(abs_path):
        try:
            return extract_hwpx_zip(abs_path)
        except Exception as e_zip:
            log_debug(f"HWPX 파싱 실패, OLE 시도: {e_zip}")

    # 2. HWP 5.0 OLE 검사
    try:
        return extract_hwp_binary_ole(abs_path)
    except Exception as e_ole:
        raise RuntimeError(f"HWP 파일 파싱 실패: {e_ole}")

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 주입받은 인자로 HWP 텍스트 및 정보를 고속 조회(캐시 지원)합니다."""
    target = params.get("target") or params.get("file")
    search_kw = (params.get("search") or "").strip()
    fmt = (params.get("format") or "text").lower()

    if not target:
        return format_response(
            status="error",
            module="hwp_read",
            action="read",
            preview="target parameter is required",
            agent_directive="STOP_RETRY: Missing target file path."
        )

    try:
        abs_path = resolve_target_file(target)
        file_name = os.path.basename(abs_path)
        sub_key = f"{search_kw}_{fmt}"

        # 1. mtime 기반 디스크 캐시 검사 (0.001s)
        cached_data = get_file_cache(abs_path, sub_key=sub_key)
        if cached_data:
            return format_response(
                status="ok",
                module="hwp_read",
                action="read_cached",
                preview=cached_data.get("preview", f"Read HWP from cache: {file_name}"),
                agent_directive="VERIFIED: HWP data retrieved from disk cache.",
                extra=cached_data
            )

        # 2. 캐시 미스 시 파싱 수행
        extracted = extract_hwp_data(abs_path)
        paragraphs = extracted["paragraphs"]
        full_text = extracted["full_text"]
        total_paras = len(paragraphs)
        total_chars = len(full_text)

        # 검색 키워드가 있는 경우
        search_matches = []
        if search_kw:
            for p_num, p_text in enumerate(paragraphs, start=1):
                if search_kw in p_text:
                    start_idx = max(0, p_text.find(search_kw) - 40)
                    end_idx = min(len(p_text), p_text.find(search_kw) + len(search_kw) + 60)
                    snippet = p_text[start_idx:end_idx].replace("\n", " ").strip()
                    search_matches.append({
                        "paragraph": p_num,
                        "snippet": f"...{snippet}..."
                    })

            if not search_matches:
                return format_response(
                    status="no_match",
                    module="hwp_read",
                    action="search",
                    preview=f"Keyword '{search_kw}' not found in {file_name}",
                    agent_directive="STOP_RETRY: Keyword not found in HWP."
                )

        # 출력 포맷 결정
        if fmt == "summary":
            preview_msg = f"HWP: {file_name} | 단락 {total_paras}개 | 총 글자: {total_chars}자 ({extracted['format_type']})"
            payload_data = {
                "format_type": extracted["format_type"],
                "total_paragraphs": total_paras,
                "total_characters": total_chars
            }
        elif fmt == "paragraphs":
            preview_msg = f"HWP: {file_name} ({total_paras} paras, {total_chars} chars)"
            payload_data = [{"paragraph": i, "characters": len(p), "text": p} for i, p in enumerate(paragraphs, start=1)]
        else:
            preview_msg = f"HWP: {file_name} ({total_paras} paras, {total_chars} chars)"
            payload_data = full_text

        items = []
        current_page = 1
        cumulative_chars = 0
        current_heading = ""
        toc = []
        CHARS_PER_PAGE_EST = 1200

        for i, p in enumerate(paragraphs, start=1):
            p_len = len(p)
            cumulative_chars += p_len
            if cumulative_chars >= CHARS_PER_PAGE_EST:
                current_page += 1
                cumulative_chars = p_len

            is_h = is_heading_candidate(p)
            if is_h:
                current_heading = p
                toc.append({"title": p, "page": current_page, "para": i})
                loc_label = f"Page {current_page} > [Heading: {p}]"
            else:
                if current_heading:
                    loc_label = f"Page {current_page} > [{current_heading}] (Para {i})"
                else:
                    loc_label = f"Page {current_page} (Para {i})"

            items.append({
                "loc": loc_label,
                "page": current_page,
                "para": i,
                "heading": current_heading,
                "is_heading": is_h,
                "text": p
            })

        result_payload = {
            "file": file_name,
            "path": abs_path,
            "file_type": "hwp",
            "format_type": extracted["format_type"],
            "total_pages": current_page,
            "total_paragraphs": total_paras,
            "total_characters": total_chars,
            "toc": toc,
            "preview": preview_msg,
            "items": items,
            "data": payload_data,
            "search_matches": search_matches if search_kw else None
        }

        # 3. 캐시 저장 (최근 2개 유지)
        save_file_cache(abs_path, result_payload, sub_key=sub_key)

        return format_response(
            status="ok",
            module="hwp_read",
            action="read_hwp",
            preview=preview_msg,
            agent_directive="VERIFIED: HWP read successfully.",
            extra=result_payload
        )

    except Exception as e:
        return format_response(
            status="error",
            module="hwp_read",
            action="read",
            preview=str(e),
            agent_directive=f"STOP_RETRY: HWP read failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="HWP/HWPX Read Micro Block (High Performance & Cache)")
    parser.add_argument("--target", "--file", required=True, help="HWP 또는 HWPX 파일 경로")
    parser.add_argument("--search", type=str, help="특정 단어 검색")
    parser.add_argument("--format", choices=["text", "paragraphs", "summary"], default="text", help="출력 형식")
    args = parser.parse_args()

    params = {
        "target": args.target,
        "search": args.search,
        "format": args.format
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: hwp_read.py ===

---

=== FILE: office_bridge.py ===

```python
import os
import sys
import argparse
import traceback
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import excel_session, word_session, ppt_session, COMError
from _config import get_data_dir

def copy_excel_to_word(from_target: str, sheet_name: Optional[str], range_str: Optional[str],
                        chart_idx: Optional[int], to_target: str, copy_as: str = "table",
                        bookmark: Optional[str] = None) -> Dict[str, Any]:
    """Excel 범위 또는 차트를 Word 문서로 복사하여 붙여넣습니다."""
    # 대상 Word 세션을 먼저 초기화하여 클립보드 소실 방지
    with word_session(target=to_target, snapshot=True) as (w_app, doc):
        with excel_session(target=from_target, sheet_name=sheet_name) as (xl_app, wb, ws):
            # 1. 엑셀 소스 복사 (Direct File/Image 파이프라인 우선 시도)
            item_desc = ""
            exported_img_path = None
            if chart_idx is not None:
                if ws.ChartObjects().Count < chart_idx:
                    raise ValueError(f"시트에 차트 #{chart_idx}가 존재하지 않습니다. (총 {ws.ChartObjects().Count}개)")
                chart_obj = ws.ChartObjects(chart_idx)
                if copy_as == "picture":
                    try:
                        temp_dir = get_data_dir()
                        # Windows COM 호환 경로 사용
                        exported_img_path = os.path.normpath(os.path.join(temp_dir, f"chart_{chart_idx}_{os.getpid()}.png"))
                        os.makedirs(temp_dir, exist_ok=True)
                        chart_obj.Chart.Export(exported_img_path, "PNG")
                        item_desc = f"Chart #{chart_idx} (Direct Image)"
                    except Exception as ex:
                        log_debug(f"차트 직접 이미지 내보내기 실패 ({ex}) -> 클립보드 fallback")
                        exported_img_path = None
                        try:
                            chart_obj.CopyPicture(1, 2)  # xlScreen=1, xlBitmap=2
                        except Exception:
                            chart_obj.CopyPicture()
                        item_desc = f"Chart #{chart_idx} (as Picture)"
                else:
                    try:
                        chart_obj.Copy()
                    except Exception:
                        chart_obj.CopyPicture(1, 2)
                    item_desc = f"Chart #{chart_idx}"
            elif range_str:
                rng = ws.Range(range_str)
                if copy_as == "picture":
                    rng.CopyPicture(1, 2)  # xlScreen=1, xlBitmap=2
                    item_desc = f"Range {range_str} (as Picture)"
                else:
                    rng.Copy()
                    item_desc = f"Range {range_str} (as Table)"
            else:
                raise ValueError("복사할 --range 또는 --chart 인자가 필요합니다.")

            # 2. 워드 문서로 즉시 배치
            if bookmark and bookmark in [b.Name for b in doc.Bookmarks]:
                target_range = doc.Bookmarks(bookmark).Range
            else:
                target_range = doc.Content
                target_range.Collapse(0)  # wdCollapseEnd = 0
                target_range.InsertParagraphAfter()
                target_range.Collapse(0)

            if exported_img_path and os.path.exists(exported_img_path):
                # 클립보드 100% 배제 Direct File 주입
                doc.InlineShapes.AddPicture(FileName=exported_img_path, Range=target_range)
                try:
                    os.remove(exported_img_path)
                except Exception:
                    pass
            elif copy_as == "picture":
                try:
                    target_range.PasteSpecial(DataType=3)  # wdPasteMetafilePicture = 3
                except Exception:
                    try:
                        target_range.PasteSpecial(DataType=4)  # wdPasteBitmap = 4
                    except Exception:
                        target_range.Paste()
            else:
                try:
                    target_range.PasteExcelTable(False, False, False)
                except Exception:
                    target_range.Paste()

            # 클립보드 정리
            try:
                xl_app.CutCopyMode = False
            except Exception:
                pass

            try:
                del target_range
            except Exception:
                pass

    return format_response(
        status="ok",
        module="office_bridge",
        action="excel_to_word",
        preview=f"Transferred {item_desc} from Excel to Word document",
        agent_directive="VERIFIED: Content bridged from Excel to Word successfully.",
        extra={"source_item": item_desc, "from_target": from_target, "to_target": to_target}
    )

def copy_word_to_ppt(from_target: str, chart_idx: Optional[int], shape_idx: Optional[int],
                      to_target: str, slide_idx: int = 1, copy_as: str = "picture",
                      left: Optional[float] = None, top: Optional[float] = None,
                      width: Optional[float] = None, height: Optional[float] = None) -> Dict[str, Any]:
    """Word 문서의 차트, 그림 또는 표를 PowerPoint 슬라이드로 복사하여 배치합니다."""
    item_desc = ""
    with word_session(target=from_target) as (w_app, doc):
        target_idx = chart_idx or shape_idx or 1
        
        # 1. InlineShapes 우선 검사 (차트, 인라인 그림)
        if doc.InlineShapes.Count >= target_idx:
            target_shape = doc.InlineShapes(target_idx)
            try:
                target_shape.Range.CopyAsPicture()
            except Exception:
                target_shape.Range.Copy()
            item_desc = f"Word InlineShape #{target_idx}"
        # 2. 부유 도형(Shapes) 검사
        elif doc.Shapes.Count >= target_idx:
            target_shape = doc.Shapes(target_idx)
            try:
                target_shape.Select()
                w_app.Selection.CopyAsPicture()
            except Exception:
                target_shape.Select()
                w_app.Selection.Copy()
            item_desc = f"Word Shape #{target_idx}"
        # 3. 표(Tables) 검사
        elif doc.Tables.Count >= target_idx:
            tbl = doc.Tables(target_idx)
            tbl.Range.Copy()
            item_desc = f"Word Table #{target_idx}"
        else:
            raise ValueError(f"Word 문서에 복사할 대상 차트/도형/표 #{target_idx}가 없습니다. (총 InlineShapes: {doc.InlineShapes.Count})")

    # 2. PowerPoint로 안전하게 붙여넣기
    with ppt_session(target=to_target, snapshot=True) as (ppt_app, prs):
        if prs.Slides.Count < slide_idx:
            slide = prs.Slides.Add(prs.Slides.Count + 1, 12)  # ppLayoutBlank = 12
        else:
            slide = prs.Slides(slide_idx)

        try:
            pasted_shapes = slide.Shapes.PasteSpecial(2)  # ppPasteBitmap = 2
        except Exception:
            pasted_shapes = slide.Shapes.Paste()

        slide_w = prs.PageSetup.SlideWidth
        slide_h = prs.PageSetup.SlideHeight

        try:
            if left is not None:
                pasted_shapes.Left = float(left)
            else:
                pasted_shapes.Left = max(40.0, (slide_w - pasted_shapes.Width) / 2)

            if top is not None:
                pasted_shapes.Top = float(top)
            else:
                pasted_shapes.Top = max(100.0, (slide_h - pasted_shapes.Height) / 2)

            if width is not None:
                pasted_shapes.Width = float(width)
            if height is not None:
                pasted_shapes.Height = float(height)
        except Exception as e:
            log_debug(f"PPT 도형 크기/위치 조정 중 경고: {e}")

    return format_response(
        status="ok",
        module="office_bridge",
        action="word_to_ppt",
        preview=f"Transferred {item_desc} as image from Word to PPT slide #{slide_idx}",
        agent_directive="VERIFIED: Content bridged from Word to PowerPoint as image successfully.",
        extra={"source_item": item_desc, "from_target": from_target, "to_target": to_target, "slide": slide_idx}
    )

def copy_excel_to_ppt(from_target: str, sheet_name: Optional[str], range_str: Optional[str],
                       chart_idx: Optional[int], to_target: str, slide_idx: int = 1,
                       copy_as: str = "picture", left: Optional[float] = None,
                       top: Optional[float] = None, width: Optional[float] = None,
                       height: Optional[float] = None) -> Dict[str, Any]:
    """Excel 범위 또는 차트를 PowerPoint 슬라이드로 복사하여 붙여넣습니다."""
    item_desc = ""
    exported_img_path = None
    # 1. Excel 소스 복사 (Direct Image 내보내기 우선 시도)
    # Excel COM 세션에서 차트를 PNG로 직접 내보내 클립보드 의존 제거
    with excel_session(target=from_target, sheet_name=sheet_name) as (xl_app, wb, ws):
        if chart_idx is not None:
            if ws.ChartObjects().Count < chart_idx:
                raise ValueError(f"시트에 차트 #{chart_idx}가 존재하지 않습니다. (총 {ws.ChartObjects().Count}개)")
            chart_obj = ws.ChartObjects(chart_idx)
            try:
                temp_dir = get_data_dir()
                # Windows COM은 백슬래시 경로를 요구하므로 replace 제거하고 normpath 사용
                exported_img_path = os.path.normpath(os.path.join(temp_dir, f"chart_{chart_idx}_{os.getpid()}.png"))
                os.makedirs(temp_dir, exist_ok=True)
                chart_obj.Chart.Export(exported_img_path, "PNG")
                item_desc = f"Chart #{chart_idx} (Direct Image)"
            except Exception as ex:
                log_debug(f"차트 직접 이미지 내보내기 실패 ({ex}) -> 클립보드 fallback")
                exported_img_path = None
                try:
                    chart_obj.Copy()
                except Exception:
                    chart_obj.CopyPicture(1, 2)
                item_desc = f"Chart #{chart_idx}"
        elif range_str:
            rng = ws.Range(range_str)
            if copy_as == "table":
                rng.Copy()
                item_desc = f"Range {range_str} (as Table)"
            else:
                rng.CopyPicture(1, 2)  # xlScreen=1, xlBitmap=2
                item_desc = f"Range {range_str} (as Picture)"
        else:
            raise ValueError("복사할 --range 또는 --chart 인자가 필요합니다.")

    # 2. PowerPoint 슬라이드로 배치
    with ppt_session(target=to_target, snapshot=True) as (ppt_app, prs):
        if slide_idx < 1 or slide_idx > prs.Slides.Count:
            slide = prs.Slides.Add(prs.Slides.Count + 1, 12)
            slide_idx = prs.Slides.Count
        else:
            slide = prs.Slides(slide_idx)

        slide_w = prs.PageSetup.SlideWidth
        slide_h = prs.PageSetup.SlideHeight

        if exported_img_path and os.path.exists(exported_img_path):
            # 클립보드 100% 배제 Direct File 주입
            # PNG 파일을 PowerPoint 슬라이드에 직접 삽입하여 안정성 확보
            final_w = float(width) if width is not None else 500.0
            final_h = float(height) if height is not None else 300.0
            final_left = float(left) if left is not None else max(40.0, (slide_w - final_w) / 2)
            final_top = float(top) if top is not None else max(100.0, (slide_h - final_h) / 2)

            pasted_shapes = slide.Shapes.AddPicture(
                FileName=exported_img_path,
                LinkToFile=False,
                SaveWithDocument=True,
                Left=final_left,
                Top=final_top,
                Width=final_w,
                Height=final_h
            )
            try:
                os.remove(exported_img_path)
            except Exception:
                pass
        else:
            # PowerPoint 슬라이드로 클립보드 붙여넣기 fallback
            try:
                pasted_shapes = slide.Shapes.Paste()
            except Exception:
                pasted_shapes = slide.Shapes.PasteSpecial(0)
            
            # 위치 및 크기 조정
            try:
                if left is not None:
                    pasted_shapes.Left = float(left)
                else:
                    pasted_shapes.Left = max(40.0, (slide_w - pasted_shapes.Width) / 2)

                if top is not None:
                    pasted_shapes.Top = float(top)
                else:
                    pasted_shapes.Top = max(100.0, (slide_h - pasted_shapes.Height) / 2)

                if width is not None:
                    pasted_shapes.Width = float(width)
                if height is not None:
                    pasted_shapes.Height = float(height)
            except Exception as e:
                log_debug(f"PPT 도형 크기/위치 조정 중 경고: {e}")

        # PowerPoint가 살아있는 동안 로컬 COM 레퍼런스를 선제 해제하여 RPC 행 방지
        pasted_shapes = None
        slide = None
        prs = None
        ppt_app = None

    return format_response(
        status="ok",
        module="office_bridge",
        action="excel_to_ppt",
        preview=f"Transferred {item_desc} from Excel to PPT slide #{slide_idx}",
        agent_directive="VERIFIED: Content bridged from Excel to PowerPoint successfully.",
        extra={"source_item": item_desc, "from_target": from_target, "to_target": to_target, "slide": slide_idx}
    )

def copy_excel_to_excel(from_target: str, sheet_name: Optional[str], range_str: Optional[str],
                        chart_idx: Optional[int], to_target: str, dest_range: Optional[str] = None) -> Dict[str, Any]:
    """Excel 범위 또는 차트를 이미지로 복사하여 엑셀 시트의 특정 위치에 붙여넣습니다."""
    # 같은 시트에 붙여넣는 쓰기 작업이므로 쓰기 세션(스냅샷 포함)으로 엶
    with excel_session(target=from_target, sheet_name=sheet_name, snapshot=True) as (xl_app, wb, ws):
        item_desc = ""
        if chart_idx is not None:
            if ws.ChartObjects().Count < chart_idx:
                raise ValueError(f"시트에 차트 #{chart_idx}가 존재하지 않습니다. (총 {ws.ChartObjects().Count}개)")
            chart_obj = ws.ChartObjects(chart_idx)
            try:
                chart_obj.CopyPicture(1, 2)
            except Exception:
                chart_obj.Copy()
            item_desc = f"Chart #{chart_idx}"
        elif range_str:
            rng = ws.Range(range_str)
            try:
                rng.CopyPicture(1, 2)
            except Exception:
                rng.Copy()
            item_desc = f"Range {range_str}"
        else:
            raise ValueError("복사할 --range 또는 --chart 인자가 필요합니다.")

        dest = dest_range or "K2"
        try:
            target_cell = ws.Range(dest)
            ws.Paste(Destination=target_cell)
        except Exception:
            ws.Paste()

        return format_response(
            status="ok",
            module="office_bridge",
            action="excel_to_excel",
            preview=f"Transferred {item_desc} as image into Excel at {dest}",
            agent_directive="VERIFIED: Content bridged into Excel as image successfully.",
            extra={"source_item": item_desc, "from_target": from_target, "to_target": to_target}
        )

def copy_word_to_excel(from_target: str, table_idx: int = 1, to_target: str = "active",
                        sheet_name: Optional[str] = None, dest_cell: str = "A1") -> Dict[str, Any]:
    """Word 문서의 표(Table) 데이터를 추출하여 Excel 시트에 SafeArray로 일괄 기입합니다."""
    extracted_rows: List[List[str]] = []
    with word_session(target=from_target, snapshot=False) as (w_app, doc):
        if doc.Tables.Count < table_idx:
            raise ValueError(f"Word 문서에 표 #{table_idx}가 존재하지 않습니다. (총 {doc.Tables.Count}개)")
        table = doc.Tables(table_idx)
        for r_idx in range(1, table.Rows.Count + 1):
            row_data = []
            for c_idx in range(1, table.Columns.Count + 1):
                try:
                    cell_text = table.Cell(r_idx, c_idx).Range.Text.rstrip("\r\x07\n")
                    row_data.append(cell_text)
                except Exception:
                    row_data.append("")
            extracted_rows.append(row_data)

    if not extracted_rows:
        raise ValueError("추출된 표 데이터가 비어 있습니다.")

    with excel_session(target=to_target, sheet_name=sheet_name, snapshot=True) as (xl_app, wb, ws):
        start_rng = ws.Range(dest_cell)
        num_rows = len(extracted_rows)
        num_cols = max(len(r) for r in extracted_rows) if extracted_rows else 1
        end_rng = ws.Cells(start_rng.Row + num_rows - 1, start_rng.Column + num_cols - 1)
        target_rng = ws.Range(start_rng, end_rng)

        safe_matrix = [tuple(r + [""] * (num_cols - len(r))) for r in extracted_rows]
        target_rng.Value = tuple(safe_matrix)

    return format_response(
        status="ok",
        module="office_bridge",
        action="word_to_excel",
        preview=f"Transferred Table #{table_idx} ({num_rows}x{num_cols}) from Word to Excel cell {dest_cell}",
        agent_directive="VERIFIED: Word table transferred to Excel successfully.",
        extra={"from_target": from_target, "to_target": to_target, "rows": num_rows, "cols": num_cols}
    )

def copy_ppt_to_word(from_target: str, slide_idx: int = 1, to_target: str = "active",
                      shape_idx: Optional[int] = None, copy_as: str = "picture",
                      bookmark: Optional[str] = None) -> Dict[str, Any]:
    """PowerPoint 슬라이드 또는 특정 요소를 Word 문서로 복사합니다."""
    item_desc = ""
    is_table_shape = False
    with ppt_session(target=from_target, snapshot=False) as (ppt_app, prs):
        if slide_idx < 1 or slide_idx > prs.Slides.Count:
            raise ValueError(f"PPT 슬라이드 #{slide_idx}가 유효하지 않습니다. (총 {prs.Slides.Count}장)")
        slide = prs.Slides(slide_idx)
        if shape_idx is not None and 1 <= shape_idx <= slide.Shapes.Count:
            shape = slide.Shapes(shape_idx)
            # 표 모양 여부 확인
            try:
                is_table_shape = bool(shape.HasTable)
            except Exception:
                is_table_shape = False
            shape.Copy()
            item_desc = f"Slide #{slide_idx} Shape #{shape_idx}"
            if is_table_shape:
                item_desc += " (Table)"
        else:
            slide.Copy()
            item_desc = f"Slide #{slide_idx}"

    with word_session(target=to_target, snapshot=True) as (w_app, doc):
        target_range = doc.Bookmarks(bookmark).Range if (bookmark and doc.Bookmarks.Exists(bookmark)) else doc.Range(doc.Content.End - 1, doc.Content.End - 1)
        target_range.InsertParagraphAfter()
        paste_rng = doc.Range(doc.Content.End - 1, doc.Content.End - 1)

        # 표 모양은 그림이 아닌 표 구조로 붙여넣기
        if is_table_shape or copy_as == "table":
            try:
                paste_rng.Paste()
            except Exception:
                doc.Content.Paste()
        else:
            try:
                paste_rng.PasteSpecial(DataType=3)  # wdPasteMetafilePicture
            except Exception:
                try:
                    paste_rng.Paste()
                except Exception:
                    doc.Content.Paste()

    return format_response(
        status="ok",
        module="office_bridge",
        action="ppt_to_word",
        preview=f"Transferred {item_desc} from PPT to Word",
        agent_directive="VERIFIED: PowerPoint content bridged to Word successfully.",
        extra={"from_target": from_target, "to_target": to_target, "slide": slide_idx}
    )

def copy_ppt_to_excel(from_target: str, slide_idx: int = 1, shape_idx: Optional[int] = None,
                       to_target: str = "active", sheet_name: Optional[str] = None,
                       dest_cell: str = "A1") -> Dict[str, Any]:
    """PowerPoint 슬라이드의 표(Table Shape)를 추출하여 Excel 시트에 SafeArray로 기입합니다."""
    extracted_rows: List[List[str]] = []
    with ppt_session(target=from_target, snapshot=False) as (ppt_app, prs):
        if slide_idx < 1 or slide_idx > prs.Slides.Count:
            raise ValueError(f"PPT 슬라이드 #{slide_idx}가 유효하지 않습니다. (총 {prs.Slides.Count}장)")
        slide = prs.Slides(slide_idx)
        
        target_table = None
        if shape_idx is not None and 1 <= shape_idx <= slide.Shapes.Count:
            sh = slide.Shapes(shape_idx)
            if sh.HasTable:
                target_table = sh.Table
        else:
            for sh in slide.Shapes:
                if sh.HasTable:
                    target_table = sh.Table
                    break

        if not target_table:
            raise ValueError(f"슬라이드 #{slide_idx}에서 표(Table)를 찾을 수 없습니다.")

        for r_idx in range(1, target_table.Rows.Count + 1):
            row_data = []
            for c_idx in range(1, target_table.Columns.Count + 1):
                try:
                    cell_text = target_table.Cell(r_idx, c_idx).Shape.TextFrame.TextRange.Text.strip()
                    row_data.append(cell_text)
                except Exception:
                    row_data.append("")
            extracted_rows.append(row_data)

    with excel_session(target=to_target, sheet_name=sheet_name, snapshot=True) as (xl_app, wb, ws):
        start_rng = ws.Range(dest_cell)
        num_rows = len(extracted_rows)
        num_cols = max(len(r) for r in extracted_rows) if extracted_rows else 1
        end_rng = ws.Cells(start_rng.Row + num_rows - 1, start_rng.Column + num_cols - 1)
        target_rng = ws.Range(start_rng, end_rng)

        safe_matrix = [tuple(r + [""] * (num_cols - len(r))) for r in extracted_rows]
        target_rng.Value = tuple(safe_matrix)

    return format_response(
        status="ok",
        module="office_bridge",
        action="ppt_to_excel",
        preview=f"Transferred Table ({num_rows}x{num_cols}) from PPT slide #{slide_idx} to Excel cell {dest_cell}",
        agent_directive="VERIFIED: PPT table transferred to Excel successfully.",
        extra={"from_target": from_target, "to_target": to_target, "slide": slide_idx, "rows": num_rows, "cols": num_cols}
    )

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """통합 Cross-Office Bridge 실행 함수."""
    from_app = (params.get("from_app") or "excel").lower()
    to_app = (params.get("to_app") or "word").lower()
    from_target = params.get("from_target") or params.get("from") or "active"
    to_target = params.get("to_target") or params.get("to") or "active"
    sheet_name = params.get("sheet")
    range_str = params.get("range")
    chart_val = params.get("chart")
    chart_idx = int(chart_val) if chart_val is not None else None
    copy_as_default = "picture" if (to_app in ["ppt", "powerpoint"] or chart_idx is not None) else "table"
    copy_as = (params.get("copy_as") or copy_as_default).lower()
    bookmark = params.get("bookmark")
    slide_idx = int(params.get("slide") or 1)
    left = params.get("left")
    top = params.get("top")
    width = params.get("width")
    height = params.get("height")

    try:
        if from_app == "excel" and to_app == "excel":
            return copy_excel_to_excel(
                from_target=from_target,
                sheet_name=sheet_name,
                range_str=range_str,
                chart_idx=chart_idx,
                to_target=to_target,
                dest_range=params.get("range") or params.get("dest")
            )
        elif from_app == "excel" and to_app == "word":
            return copy_excel_to_word(
                from_target=from_target,
                sheet_name=sheet_name,
                range_str=range_str,
                chart_idx=chart_idx,
                to_target=to_target,
                copy_as=copy_as,
                bookmark=bookmark
            )
        elif from_app == "excel" and to_app in ["ppt", "powerpoint"]:
            return copy_excel_to_ppt(
                from_target=from_target,
                sheet_name=sheet_name,
                range_str=range_str,
                chart_idx=chart_idx,
                to_target=to_target,
                slide_idx=slide_idx,
                copy_as=copy_as,
                left=left,
                top=top,
                width=width,
                height=height
            )
        elif from_app == "word" and to_app in ["ppt", "powerpoint"]:
            return copy_word_to_ppt(
                from_target=from_target,
                chart_idx=chart_idx,
                shape_idx=params.get("shape") or params.get("item"),
                to_target=to_target,
                slide_idx=slide_idx,
                copy_as=copy_as,
                left=left,
                top=top,
                width=width,
                height=height
            )
        elif from_app == "word" and to_app == "excel":
            return copy_word_to_excel(
                from_target=from_target,
                table_idx=int(params.get("table") or params.get("item") or 1),
                to_target=to_target,
                sheet_name=sheet_name,
                dest_cell=params.get("range") or params.get("dest") or "A1"
            )
        elif from_app in ["ppt", "powerpoint"] and to_app == "word":
            return copy_ppt_to_word(
                from_target=from_target,
                slide_idx=slide_idx,
                to_target=to_target,
                shape_idx=params.get("shape") or params.get("item"),
                copy_as=copy_as,
                bookmark=bookmark
            )
        elif from_app in ["ppt", "powerpoint"] and to_app == "excel":
            return copy_ppt_to_excel(
                from_target=from_target,
                slide_idx=slide_idx,
                shape_idx=params.get("shape") or params.get("item"),
                to_target=to_target,
                sheet_name=sheet_name,
                dest_cell=params.get("range") or params.get("dest") or "A1"
            )
        else:
            raise NotImplementedError(f"지원하지 않는 브릿지 경로입니다: {from_app} -> {to_app}")

    except Exception as e:
        log_debug(f"office_bridge 실행 오류: {traceback.format_exc()}")
        return format_response(
            status="error",
            module="office_bridge",
            action=f"{from_app}_to_{to_app}",
            preview=f"Bridge failed: {e}",
            agent_directive=f"STOP_RETRY: Cross-Office transfer failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Cross-Office Content Bridge Micro Block")
    parser.add_argument("--from-app", default="excel", choices=["excel", "word", "ppt", "powerpoint"], help="원본 오피스 앱 (excel, word, ppt)")
    parser.add_argument("--from", "--from-target", dest="from_target", default="active", help="원본 파일 경로 또는 'active'")
    parser.add_argument("--sheet", help="엑셀 시트명")
    parser.add_argument("--range", help="엑셀 범위 또는 대상 시작 셀 (예: 'A1:E10', 'A1')")
    parser.add_argument("--chart", type=int, help="복사할 엑셀 차트 번호 (1부터 시작)")
    parser.add_argument("--table", type=int, help="복사할 표 번호 (1부터 시작)")
    parser.add_argument("--shape", type=int, help="복사할 도형 번호 (1부터 시작)")
    parser.add_argument("--copy-as", default="table", choices=["table", "picture"], help="복사 형식 (기본: table)")
    
    parser.add_argument("--to-app", default="word", choices=["word", "ppt", "powerpoint", "excel"], help="대상 오피스 앱 (word, ppt, excel)")
    parser.add_argument("--to", "--to-target", dest="to_target", default="active", help="대상 파일 경로 또는 'active'")
    parser.add_argument("--slide", type=int, default=1, help="PPT 대상 슬라이드 번호 (1부터 시작)")
    parser.add_argument("--bookmark", help="Word 대상 북마크 이름")
    parser.add_argument("--left", type=float, help="PPT 도형 좌측 좌표 (pt)")
    parser.add_argument("--top", type=float, help="PPT 도형 상단 좌표 (pt)")
    parser.add_argument("--width", type=float, help="PPT 도형 너비 (pt)")
    parser.add_argument("--height", type=float, help="PPT 도형 높이 (pt)")

    args = parser.parse_args()
    params = vars(args)
    res = execute(params)
    emit_response(res)
    sys.stdout.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
```

=== END FILE: office_bridge.py ===

---

=== FILE: office_theme.py ===

```python
import sys
import os
import json
import argparse
from typing import Dict, Any, List, Optional
from collections import Counter

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, parse_color_to_bgr, bgr_to_hex
from _config import get_data_dir
from _com_guard import (
    excel_session, word_session, ppt_session,
    get_all_running_excel_workbooks, get_all_running_word_documents, get_all_running_ppt_presentations,
    COMError
)

# --- 비즈니스 표준 컬러 테마 프리셋 모음 ---
THEME_PRESETS = {
    "navy": {
        "name": "Corporate Navy",
        "description": "신뢰감 있는 클래식 비즈니스 네이비 테마",
        "primary": "#1B365D",
        "secondary": "#4A777A",
        "accent": "#D9381E",
        "header": {
            "bg": "#1B365D",
            "color": "#FFFFFF",
            "bold": True,
            "align": "center",
            "font_size": 11
        },
        "zebra": {
            "enabled": True,
            "odd": "#FFFFFF",
            "even": "#F4F7FB"
        },
        "summary": {
            "bg": "#E8EEF5",
            "color": "#1B365D",
            "bold": True,
            "border_bottom": "double"
        },
        "borders": {
            "inner_color": "#D0D7DE",
            "outer_color": "#1B365D"
        },
        "number_format": "#,##0"
    },
    "slate": {
        "name": "Modern Slate",
        "description": "미니멀하고 세련된 차콜/슬레이트 테마",
        "primary": "#2B2D42",
        "secondary": "#8D99AE",
        "accent": "#EF233C",
        "header": {
            "bg": "#2B2D42",
            "color": "#FFFFFF",
            "bold": True,
            "align": "center",
            "font_size": 11
        },
        "zebra": {
            "enabled": True,
            "odd": "#FFFFFF",
            "even": "#F8F9FA"
        },
        "summary": {
            "bg": "#EDF2F4",
            "color": "#2B2D42",
            "bold": True,
            "border_bottom": "double"
        },
        "borders": {
            "inner_color": "#E5E7EB",
            "outer_color": "#2B2D42"
        },
        "number_format": "#,##0"
    },
    "teal": {
        "name": "Clean Teal",
        "description": "전략/재무 보고서에 최적화된 다크 틸 & 민트 테마",
        "primary": "#004D40",
        "secondary": "#00897B",
        "accent": "#FF6F00",
        "header": {
            "bg": "#004D40",
            "color": "#FFFFFF",
            "bold": True,
            "align": "center",
            "font_size": 11
        },
        "zebra": {
            "enabled": True,
            "odd": "#FFFFFF",
            "even": "#F0FDF4"
        },
        "summary": {
            "bg": "#E0F2F1",
            "color": "#004D40",
            "bold": True,
            "border_bottom": "double"
        },
        "borders": {
            "inner_color": "#CCFBF1",
            "outer_color": "#004D40"
        },
        "number_format": "#,##0"
    },
    "emerald": {
        "name": "Forest Emerald",
        "description": "안정적이고 차분한 에메랄드 그린 테마",
        "primary": "#1E4620",
        "secondary": "#3E7B43",
        "accent": "#E65100",
        "header": {
            "bg": "#1E4620",
            "color": "#FFFFFF",
            "bold": True,
            "align": "center",
            "font_size": 11
        },
        "zebra": {
            "enabled": True,
            "odd": "#FFFFFF",
            "even": "#F2F8F2"
        },
        "summary": {
            "bg": "#E5EFE5",
            "color": "#1E4620",
            "bold": True,
            "border_bottom": "double"
        },
        "borders": {
            "inner_color": "#D1E7DD",
            "outer_color": "#1E4620"
        },
        "number_format": "#,##0"
    }
}

def resolve_theme(theme_arg: Optional[str] = None) -> Dict[str, Any]:
    r"""프리셋 이름 또는 테마 JSON 파일 경로를 받아 완성된 테마 딕셔너리를 반환합니다.
    생략되거나 'auto'인 경우 C:\cli_data\data\current_theme.json을 자동 상속받습니다.
    """
    if not theme_arg or theme_arg.strip().lower() in ["auto", "default", "none"]:
        current_theme_file = os.path.join(get_data_dir(), "current_theme.json")
        if os.path.exists(current_theme_file):
            try:
                with open(current_theme_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return THEME_PRESETS["navy"]

    t_clean = theme_arg.strip().lower()
    if t_clean in THEME_PRESETS:
        return THEME_PRESETS[t_clean]

    # 로컬 파일 경로 탐색
    cand_paths = [
        theme_arg,
        os.path.join(get_data_dir(), theme_arg),
        os.path.join(get_data_dir(), f"{theme_arg}.json")
    ]
    for p in cand_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)

    return THEME_PRESETS.get(t_clean, THEME_PRESETS["navy"])

# --- Excel 정밀 스타일 분석기 ---
def extract_excel_style_dna(ws) -> Dict[str, Any]:
    """Excel Worksheet의 UsedRange를 스캔하여 스타일 DNA를 정밀 추출합니다."""
    used_range = ws.UsedRange
    row_count = used_range.Rows.Count
    col_count = used_range.Columns.Count
    start_row = used_range.Row
    start_col = used_range.Column

    dna: Dict[str, Any] = {
        "app": "excel",
        "sheet_name": ws.Name,
        "grid_lines": getattr(ws.Parent.Windows(1), "DisplayGridlines", True),
        "header": {},
        "zebra": {"enabled": False},
        "summary": {},
        "number_format": "#,##0",
        "font_family": "맑은 고딕",
        "palette": []
    }

    if row_count == 0 or col_count == 0:
        return dna

    # 1. 헤더 행 분석 (1행 샘플링)
    header_cell = ws.Cells(start_row, start_col)
    try:
        dna["font_family"] = str(header_cell.Font.Name)
        h_bg_int = header_cell.Interior.Color
        h_color_int = header_cell.Font.Color
        
        # 기본 흰색/투명 제외 유의미한 배경색 추출
        h_bg_hex = bgr_to_hex(h_bg_int)
        h_color_hex = bgr_to_hex(h_color_int)

        dna["header"] = {
            "bg": h_bg_hex if h_bg_hex not in ["#FFFFFF", None] else "#1B365D",
            "color": h_color_hex if h_color_hex is not None else "#FFFFFF",
            "bold": bool(header_cell.Font.Bold),
            "font_size": float(header_cell.Font.Size),
            "align": "center" if header_cell.HorizontalAlignment == -4108 else "left",
            "row_height": float(ws.Rows(start_row).RowHeight)
        }
    except Exception as e:
        log_debug(f"헤더 분석 예외: {e}")

    # 2. 데이터 행 및 Zebra 패턴 분석
    bg_colors = []
    num_formats = []
    
    # 상위 10행 샘플링
    sample_rows = min(row_count - 1, 10)
    for r in range(1, sample_rows + 1):
        curr_row = start_row + r
        try:
            cell = ws.Cells(curr_row, start_col)
            bg = bgr_to_hex(cell.Interior.Color)
            if bg:
                bg_colors.append(bg)
        except Exception:
            pass

    # 숫자 열 포맷 샘플링
    for c in range(col_count):
        curr_col = start_col + c
        try:
            for r in range(1, min(row_count, 5)):
                val = ws.Cells(start_row + r, curr_col).Value
                fmt = ws.Cells(start_row + r, curr_col).NumberFormat
                if isinstance(val, (int, float)) and fmt and fmt != "General":
                    num_formats.append(str(fmt))
                    break
        except Exception:
            pass

    if num_formats:
        most_common_fmt = Counter(num_formats).most_common(1)[0][0]
        dna["number_format"] = most_common_fmt

    # Zebra 교차 배경색 탐지
    if len(bg_colors) >= 2:
        distinct_bgs = list(dict.fromkeys(bg_colors))
        if len(distinct_bgs) >= 2 and distinct_bgs[0] != distinct_bgs[1]:
            dna["zebra"] = {
                "enabled": True,
                "odd": distinct_bgs[0],
                "even": distinct_bgs[1]
            }

    # 3. 합계/요약 행 분석 (마지막 행)
    if row_count >= 3:
        last_row = start_row + row_count - 1
        last_cell = ws.Cells(last_row, start_col)
        last_val = str(last_cell.Value or "")
        
        is_summary = any(k in last_val for k in ["합계", "총계", "Total", "소계", "평균"])
        try:
            # 이중 밑줄 확인 (xlDouble = -4119, xlEdgeBottom = 9)
            has_double_border = (last_cell.Borders(9).LineStyle == -4119)
        except Exception:
            has_double_border = False

        if is_summary or has_double_border or bool(last_cell.Font.Bold):
            dna["summary"] = {
                "detected": True,
                "row_index": last_row,
                "bold": bool(last_cell.Font.Bold),
                "bg": bgr_to_hex(last_cell.Interior.Color),
                "border_bottom": "double" if has_double_border else "single"
            }

    # 4. 전체 팔레트 추출 (상위 사용 색상)
    color_counter = Counter([dna["header"].get("bg"), dna["zebra"].get("even"), dna["summary"].get("bg")])
    dna["palette"] = [c for c, _ in color_counter.most_common() if c and c != "#FFFFFF"]

    return dna

# --- PowerPoint 정밀 스타일 분석기 ---
def extract_ppt_style_dna(prs) -> Dict[str, Any]:
    """PowerPoint 프레젠테이션을 스캔하여 타이포그래피 및 지배적 컬러 팔레트를 추출합니다."""
    dna: Dict[str, Any] = {
        "app": "ppt",
        "title_font": "맑은 고딕",
        "title_size": 28,
        "title_color": "#1B365D",
        "body_font": "맑은 고딕",
        "body_size": 14,
        "body_color": "#333333",
        "palette": [],
        "card_styles": []
    }

    fill_colors = []
    font_colors = []
    fonts = []

    for slide in prs.Slides:
        for shape in slide.Shapes:
            # 도형/카드 채우기 색상
            try:
                if shape.Fill.Visible and shape.Fill.ForeColor.RGB:
                    hex_color = bgr_to_hex(shape.Fill.ForeColor.RGB)
                    if hex_color and hex_color not in ["#FFFFFF", "#000000"]:
                        fill_colors.append(hex_color)
            except Exception:
                pass

            # 텍스트 속성
            try:
                if shape.HasTextFrame and shape.TextFrame.HasText:
                    tr = shape.TextFrame.TextRange
                    if tr.Font.Name:
                        fonts.append(str(tr.Font.Name))
                    if tr.Font.Color.RGB:
                        fc = bgr_to_hex(tr.Font.Color.RGB)
                        if fc:
                            font_colors.append(fc)

                    # 제목 텍스트 상자 추정 (20pt 이상)
                    if tr.Font.Size >= 20:
                        dna["title_font"] = str(tr.Font.Name)
                        dna["title_size"] = float(tr.Font.Size)
                        if fc:
                            dna["title_color"] = fc
                    elif tr.Font.Size <= 16:
                        dna["body_font"] = str(tr.Font.Name)
                        dna["body_size"] = float(tr.Font.Size)
                        if fc:
                            dna["body_color"] = fc
            except Exception:
                pass

    # 주요 팔레트 계산
    all_colors = fill_colors + font_colors
    if all_colors:
        top_colors = [c for c, _ in Counter(all_colors).most_common(5)]
        dna["palette"] = top_colors

    return dna

# --- Word 정밀 스타일 분석기 ---
def extract_word_style_dna(doc) -> Dict[str, Any]:
    """Word 문서를 스캔하여 표준 본문/제목 글꼴 및 표 서식을 추출합니다."""
    dna: Dict[str, Any] = {
        "app": "word",
        "font_family": "맑은 고딕",
        "body_size": 10.5,
        "body_color": "#000000",
        "heading_font": "맑은 고딕",
        "heading_size": 14,
        "heading_color": "#1B365D",
        "table_header_bg": "#1B365D",
        "palette": []
    }

    try:
        # 본문(Normal) 기본 글꼴 추출
        norm_style = doc.Styles("Normal")
        dna["font_family"] = str(norm_style.Font.Name)
        dna["body_size"] = float(norm_style.Font.Size)
    except Exception:
        pass

    try:
        # Heading 1 글꼴 추출
        h1_style = doc.Styles("Heading 1")
        dna["heading_font"] = str(h1_style.Font.Name)
        dna["heading_size"] = float(h1_style.Font.Size)
        h_color = bgr_to_hex(h1_style.Font.Color)
        if h_color:
            dna["heading_color"] = h_color
    except Exception:
        pass

    # 표 헤더 색상 검사
    try:
        if doc.Tables.Count > 0:
            first_tbl = doc.Tables(1)
            cell = first_tbl.Cell(1, 1)
            bg = bgr_to_hex(cell.Range.Shading.BackgroundPatternColor)
            if bg and bg != "#FFFFFF":
                dna["table_header_bg"] = bg
                dna["palette"].append(bg)
    except Exception:
        pass

    return dna

# --- 통합 실행 인터페이스 ---
def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 스타일 테마 추출/목록 조회를 실행합니다."""
    action = (params.get("action") or "extract").lower()
    target = params.get("target") or "active"
    app_hint = (params.get("app") or "").lower()
    export_path = params.get("export") or params.get("export_theme")

    # 1. 내장 프리셋 목록 조회
    if action in ["list", "list-presets", "presets"]:
        presets_summary = {k: {"name": v["name"], "description": v["description"], "primary": v["primary"]} for k, v in THEME_PRESETS.items()}
        return format_response(
            status="ok",
            module="office_theme",
            action="list_presets",
            preview=f"총 {len(THEME_PRESETS)}개 내장 비즈니스 테마 프리셋 제공: [{', '.join(THEME_PRESETS.keys())}]",
            agent_directive="VERIFIED: Theme presets listed.",
            extra={"presets": presets_summary}
        )

    # 1-B. 활성 글로벌 테마 설정 (Set/Apply)
    if action in ["set", "apply", "activate"]:
        theme_name = params.get("theme") or params.get("name") or "navy"
        resolved = resolve_theme(theme_name)
        curr_theme_path = os.path.join(get_data_dir(), "current_theme.json")
        with open(curr_theme_path, "w", encoding="utf-8") as f:
            json.dump(resolved, f, ensure_ascii=False, indent=2)
        return format_response(
            status="ok",
            module="office_theme",
            action="set_theme",
            preview=f"글로벌 활성 테마 설정 완료: '{theme_name}' (이후 모든 Office 도구에 자동 상속)",
            agent_directive="VERIFIED: Global theme activated.",
            extra={"theme": theme_name, "path": curr_theme_path}
        )

    # 2. 스타일 DNA 추출 실행
    # 앱 종류 판별
    if not app_hint:
        t_lower = target.lower()
        if t_lower.endswith((".xlsx", ".xls", ".xlsm")):
            app_hint = "excel"
        elif t_lower.endswith((".docx", ".doc")):
            app_hint = "word"
        elif t_lower.endswith((".pptx", ".ppt")):
            app_hint = "ppt"
        else:
            # 활성 창 기반 자동 감지
            excel_wbs = get_all_running_excel_workbooks()
            if excel_wbs:
                app_hint = "excel"
            elif get_all_running_word_documents():
                app_hint = "word"
            elif get_all_running_ppt_presentations():
                app_hint = "ppt"
            else:
                app_hint = "excel"

    dna_result = {}
    if app_hint == "excel":
        with excel_session(target=target, snapshot=False) as (app, wb, ws):
            dna_result = extract_excel_style_dna(ws)
    elif app_hint == "word":
        with word_session(target=target, snapshot=False) as (app, doc):
            dna_result = extract_word_style_dna(doc)
    elif app_hint == "ppt":
        with ppt_session(target=target, snapshot=False) as (app, prs):
            dna_result = extract_ppt_style_dna(prs)
    else:
        raise ValueError(f"지원하지 않는 애플리케이션: {app_hint}")

    # 글로벌 활성 테마 버스 자동 동기화 (이후 생성 도구에 자동 상속)
    try:
        curr_theme_path = os.path.join(get_data_dir(), "current_theme.json")
        with open(curr_theme_path, "w", encoding="utf-8") as f:
            json.dump(dna_result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # 테마 JSON 저장 처리
    saved_file = None
    if export_path:
        if not os.path.isabs(export_path):
            export_path = os.path.join(get_data_dir(), export_path)
        if not export_path.endswith(".json"):
            export_path += ".json"
        
        os.makedirs(os.path.dirname(export_path), exist_ok=True)
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(dna_result, f, ensure_ascii=False, indent=2)
        saved_file = export_path
        log_debug(f"스타일 DNA 프로필 저장 완료: {export_path}")

    preview_msg = (
        f"[{app_hint.upper()}] 스타일 DNA 추출 완료 | "
        f"폰트: {dna_result.get('font_family') or dna_result.get('title_font', '기본')} | "
        f"주요색상: {dna_result.get('palette', ['없음'])}"
    )
    if saved_file:
        preview_msg += f" | 파일 저장: {os.path.basename(saved_file)}"

    return format_response(
        status="ok",
        module="office_theme",
        action="extract_theme",
        preview=preview_msg,
        agent_directive="VERIFIED: Style theme extracted.",
        extra={
            "app": app_hint,
            "theme_path": saved_file,
            "theme": dna_result
        }
    )

def main():
    parser = argparse.ArgumentParser(description="Office Style & Theme DNA Extraction Micro Block")
    parser.add_argument("--action", "-a", default="extract", choices=["extract", "list-presets", "list", "set", "apply"], help="수행할 작업")
    parser.add_argument("--target", "-t", default="active", help="대상 (active 또는 파일 경로)")
    parser.add_argument("--theme", help="설정할 테마 이름 또는 JSON 경로 (set/apply 시)")
    parser.add_argument("--app", choices=["excel", "word", "ppt"], help="애플리케이션 명시")
    parser.add_argument("--export", "--export-theme", "-o", type=str, help="추출된 테마 JSON 저장 파일명/경로")
    args = parser.parse_args()

    params = {
        "action": args.action,
        "target": args.target,
        "theme": args.theme,
        "app": args.app,
        "export": args.export
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: office_theme.py ===

---

=== FILE: office_window.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any, List

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import (
    get_all_running_excel_workbooks,
    get_all_running_word_documents,
    get_all_running_ppt_presentations
)

def list_all_active_office_windows() -> List[Dict[str, Any]]:
    """Excel, Word, PowerPoint에서 열려 있는 모든 창과 문서를 통합 수집합니다."""
    windows = []

    # 1. Excel
    for w in get_all_running_excel_workbooks():
        windows.append({
            "app": "Excel",
            "name": w["name"],
            "path": w["path"],
            "active": w.get("is_active", False),
            "detail": f"Sheets: {len(w.get('sheets', []))}"
        })

    # 2. Word
    for d in get_all_running_word_documents():
        windows.append({
            "app": "Word",
            "name": d["name"],
            "path": d["path"],
            "active": d.get("is_active", False),
            "detail": "Document"
        })

    # 3. PPT
    for p in get_all_running_ppt_presentations():
        windows.append({
            "app": "PowerPoint",
            "name": p["name"],
            "path": p["path"],
            "active": p.get("is_active", False),
            "detail": f"Slides: {p.get('slides_count', 0)}"
        })

    return windows

def focus_office_app(app_name: str) -> bool:
    """지정한 Office 앱을 화면 최상단(포커스)으로 전환합니다."""
    app_lower = app_name.lower()
    try:
        import win32gui
        target_class = "XLMAIN" if "excel" in app_lower else ("OpusApp" if "word" in app_lower else "PPTFrameClass")
        hwnd = win32gui.FindWindow(target_class, None)
        if hwnd:
            win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
            win32gui.SetForegroundWindow(hwnd)
            return True
    except Exception as e:
        log_debug(f"윈도우 포커스 전환 실패: {e}")
    return False

def open_office_document(file_path: str) -> Dict[str, Any]:
    """지정한 Office 문서를 화면 전면에 보이도록(Visible=True) 열고 활성화합니다."""
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {abs_path}")

    ext = os.path.splitext(abs_path)[1].lower()
    import win32com.client
    app_type = ""

    if ext in [".xlsx", ".xls", ".csv"]:
        app = win32com.client.Dispatch("Excel.Application")
        app.Visible = True
        try:
            app.UserControl = True
            app.ScreenUpdating = True
        except Exception:
            pass
        app.Workbooks.Open(abs_path)
        focus_office_app("excel")
        app_type = "Excel"
    elif ext in [".docx", ".doc"]:
        app = win32com.client.Dispatch("Word.Application")
        app.Visible = True
        try:
            app.ScreenUpdating = True
        except Exception:
            pass
        app.Documents.Open(abs_path)
        focus_office_app("word")
        app_type = "Word"
    elif ext in [".pptx", ".ppt"]:
        app = win32com.client.Dispatch("PowerPoint.Application")
        app.Visible = True
        app.Presentations.Open(abs_path)
        focus_office_app("ppt")
        app_type = "PowerPoint"
    else:
        raise ValueError(f"지원하지 않는 Office 파일 형식입니다: {ext}")

    return {
        "opened": True,
        "app": app_type,
        "file": abs_path,
        "name": os.path.basename(abs_path)
    }

def create_new_office_document(app_name: str) -> Dict[str, Any]:
    """지정한 Office 애플리케이션의 새 문서를 화면 전면에 보이도록(Visible=True) 생성하고 활성화합니다."""
    app_lower = app_name.lower().strip()
    import win32com.client
    app_type = ""
    doc_name = ""

    if "excel" in app_lower or "xlsx" in app_lower:
        app = win32com.client.Dispatch("Excel.Application")
        app.Visible = True
        try:
            app.UserControl = True
            app.ScreenUpdating = True
        except Exception:
            pass
        wb = app.Workbooks.Add()
        focus_office_app("excel")
        app_type = "Excel"
        doc_name = wb.Name
    elif "word" in app_lower or "docx" in app_lower:
        app = win32com.client.Dispatch("Word.Application")
        app.Visible = True
        try:
            app.ScreenUpdating = True
        except Exception:
            pass
        doc = app.Documents.Add()
        focus_office_app("word")
        app_type = "Word"
        doc_name = doc.Name
    elif "ppt" in app_lower or "powerpoint" in app_lower or "pptx" in app_lower:
        app = win32com.client.Dispatch("PowerPoint.Application")
        app.Visible = True
        prs = app.Presentations.Add()
        try:
            prs.Slides.Add(1, 12)  # ppLayoutBlank
        except Exception:
            pass
        focus_office_app("ppt")
        app_type = "PowerPoint"
        doc_name = prs.Name
    else:
        raise ValueError(f"지원하지 않는 Office 프로그램입니다: {app_name}")

    return {
        "created": True,
        "app": app_type,
        "name": doc_name
    }

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """열린 오피스 창 목록 조회, 포커스 전환, 파일 화면 열기 또는 신규 문서 생성을 수행합니다."""
    action = (params.get("action") or "list").lower()
    focus_target = params.get("focus") or params.get("to")
    open_file = params.get("open")
    new_app = params.get("new") or (params.get("app") if action == "new" else None)

    if action == "new" or new_app:
        target_app = new_app or params.get("app") or "excel"
        try:
            res = create_new_office_document(target_app)
            return format_response(
                status="ok",
                module="office_window",
                action="new",
                preview=f"Created new {res['app']} document on screen: {res['name']}",
                agent_directive="VERIFIED: New document created and visible on screen.",
                extra=res
            )
        except Exception as e:
            return format_response(
                status="error",
                module="office_window",
                action="new",
                preview=str(e),
                agent_directive=f"STOP_RETRY: Failed to create new document: {e}"
            )

    if open_file:
        try:
            res = open_office_document(open_file)
            return format_response(
                status="ok",
                module="office_window",
                action="open",
                preview=f"Opened {res['app']} window: {res['name']}",
                agent_directive="VERIFIED: Document opened and visible on screen.",
                extra=res
            )
        except Exception as e:
            return format_response(
                status="error",
                module="office_window",
                action="open",
                preview=str(e),
                agent_directive=f"STOP_RETRY: Failed to open document: {e}"
            )

    if focus_target:
        success = focus_office_app(focus_target)
        status_str = "Focused" if success else "Focus failed"
        return format_response(
            status="ok" if success else "no_match",
            module="office_window",
            action="focus",
            preview=f"{status_str} window: {focus_target.upper()}",
            agent_directive="VERIFIED: Window focused." if success else "STOP_RETRY: Window not found.",
            extra={"target": focus_target, "success": success}
        )

    all_windows = list_all_active_office_windows()
    preview_parts = [f"{w['app']}:{w['name']}{'(*)' if w['active'] else ''}" for w in all_windows]
    preview_msg = f"총 {len(all_windows)}개 활성 오피스 창: [{', '.join(preview_parts) or '없음'}]"

    return format_response(
        status="ok",
        module="office_window",
        action="list_windows",
        preview=preview_msg,
        agent_directive="VERIFIED: Active Office windows enumerated.",
        extra={
            "total_count": len(all_windows),
            "windows": all_windows
        }
    )

def main():
    parser = argparse.ArgumentParser(description="Unified Office Window Inspection & Focus Micro Block")
    parser.add_argument("--action", choices=["list", "focus", "open", "new"], help="수행할 작업")
    parser.add_argument("--list", "--list-active", dest="list_active", action="store_true", help="열린 모든 Office 창 목록 조회")
    parser.add_argument("--focus", action="store_true", help="대상 앱 창을 화면 최상단으로 전환")
    parser.add_argument("--to", choices=["excel", "word", "ppt"], help="포커스 대상 애플리케이션")
    parser.add_argument("--app", choices=["excel", "word", "ppt"], help="대상 애플리케이션 (new 시)")
    parser.add_argument("--new", choices=["excel", "word", "ppt"], help="새 Office 문서 생성 및 화면 표시")
    parser.add_argument("--open", type=str, help="Office 파일을 화면 전면에 열기 (Visible=True)")
    args = parser.parse_args()

    action = args.action
    if not action:
        if args.new:
            action = "new"
        elif args.open:
            action = "open"
        elif args.focus:
            action = "focus"
        else:
            action = "list"

    params = {
        "action": action,
        "to": args.to,
        "app": args.app or args.new,
        "new": args.new,
        "open": args.open
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: office_window.py ===

---

=== FILE: outlook_read.py ===

```python
"""
outlook_read.py - Native Outlook COM Mail Reader & High-Speed Search Engine.
Operates 100% in the background without disturbing user screen.
Supports current active mail capture, built-in Outlook search, folder tree,
and automatic attachment downloading to atomic_cli/data/.
"""
import sys
import os
import argparse
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response
from _outlook_guard import get_outlook_app, get_mapi_namespace, resolve_folder, get_current_active_item
from _config import get_data_dir

def _item_to_summary(item) -> Dict[str, Any]:
    """Extracts clean serializable metadata from an Outlook MailItem."""
    entry_id = getattr(item, "EntryID", "")
    subject = getattr(item, "Subject", "(No Subject)")
    sender = getattr(item, "SenderName", "")
    sender_email = getattr(item, "SenderEmailAddress", "")
    try:
        received = str(item.ReceivedTime)
    except Exception:
        received = ""
    unread = bool(getattr(item, "UnRead", False))
    has_attach = bool(getattr(item, "Attachments", None) and item.Attachments.Count > 0)
    attach_count = item.Attachments.Count if has_attach else 0

    return {
        "id": entry_id,
        "subject": subject,
        "sender": f"{sender} <{sender_email}>" if sender_email else sender,
        "received": received,
        "unread": unread,
        "attachments_count": attach_count
    }

def action_current(app, ns, summarize: bool=False) -> Dict[str, Any]:
    """Captures the mail currently open or selected by the user."""
    item, source = get_current_active_item(app)
    if not item:
        return format_response(
            status="no_match",
            module="outlook_read",
            action="current",
            preview="No mail is currently open in a window or selected in the Outlook list.",
            agent_directive="STOP_RETRY: User has not selected any email in Outlook."
        )

    summary = _item_to_summary(item)
    summary["source"] = source
    body_full = getattr(item, "Body", "")
    body_snippet = body_full[:500]
    summary["body_preview"] = body_snippet.replace("\r\n", " ").strip()

    if summarize:
        # 간단 요약: 제목 + 발신자 + 수신자 + 첫 300자
        to_addr = getattr(item, "To", "")
        cc_addr = getattr(item, "CC", "")
        summary["summary"] = {
            "subject": summary["subject"],
            "from": summary["sender"],
            "to": to_addr,
            "cc": cc_addr,
            "received": summary["received"],
            "body_head": body_full[:300].replace("\r\n", " ").strip()
        }
        preview_msg = f"Captured {source} mail and summarized: '{summary['subject']}' from {summary['sender']}"
    else:
        preview_msg = f"Captured {source} mail: '{summary['subject']}' from {summary['sender']}"

    return format_response(
        status="ok",
        module="outlook_read",
        action="current",
        preview=preview_msg,
        agent_directive="VERIFIED: Active mail captured. Ready for reply or inspection.",
        extra={"mail": summary}
    )

def action_list(ns, folder_name: str, unread_only: bool, limit: int) -> Dict[str, Any]:
    """Lists recent emails from specified folder in background."""
    folder = resolve_folder(ns, folder_name)
    items = folder.Items
    items.Sort("[ReceivedTime]", True)  # Descending order (newest first)

    if unread_only:
        items = items.Restrict("[UnRead] = True")

    results = []
    count = 0
    for item in items:
        if count >= limit:
            break
        # Only process mail items (MessageClass = IPM.Note)
        if getattr(item, "Class", 0) == 43:  # olMail
            results.append(_item_to_summary(item))
            count += 1

    return format_response(
        status="ok",
        module="outlook_read",
        action="list",
        preview=f"Fetched {len(results)} mails from folder '{folder.Name}' (Unread only: {unread_only})",
        agent_directive="VERIFIED: Mail list retrieved successfully.",
        extra={"folder": folder.Name, "count": len(results), "mails": results}
    )

def action_search(ns, folder_name: str, query: str, sender_filter: str, limit: int) -> Dict[str, Any]:
    """Searches emails directly using Outlook's native Restrict engine (DASL/Jet)."""
    folder = resolve_folder(ns, folder_name)
    items = folder.Items
    items.Sort("[ReceivedTime]", True)

    filter_clauses = []
    if query:
        q_clean = query.replace("'", "''")
        filter_clauses.append(f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{q_clean}%' OR \"urn:schemas:httpmail:textdescription\" LIKE '%{q_clean}%'")
    if sender_filter:
        s_clean = sender_filter.replace("'", "''")
        filter_clauses.append(f"@SQL=\"urn:schemas:httpmail:fromname\" LIKE '%{s_clean}%' OR \"urn:schemas:httpmail:fromemail\" LIKE '%{s_clean}%'")

    if filter_clauses:
        dasl_filter = " AND ".join(filter_clauses)
        try:
            items = items.Restrict(dasl_filter)
        except Exception:
            # Fallback to Jet query if complex DASL fails
            if query:
                items = items.Restrict(f"[Subject] = '{query}'")

    results = []
    count = 0
    for item in items:
        if count >= limit:
            break
        if getattr(item, "Class", 0) == 43:
            results.append(_item_to_summary(item))
            count += 1

    return format_response(
        status="ok" if results else "no_match",
        module="outlook_read",
        action="search",
        preview=f"Found {len(results)} mails matching '{query or sender_filter}' in '{folder.Name}'",
        agent_directive="VERIFIED: Outlook native search complete." if results else "STOP_RETRY: No matching emails found.",
        extra={"query": query, "folder": folder.Name, "count": len(results), "mails": results}
    )

def action_read(ns, entry_id: str, save_attach: bool) -> Dict[str, Any]:
    """Reads full content of a specific email by EntryID and saves attachments if requested."""
    try:
        item = ns.GetItemFromID(entry_id)
    except Exception as e:
        return format_response(
            status="error",
            module="outlook_read",
            action="read",
            preview=f"Mail with EntryID '{entry_id}' not found: {e}",
            agent_directive="STOP_RETRY: Invalid EntryID."
        )

    summary = _item_to_summary(item)
    summary["body"] = getattr(item, "Body", "")
    summary["to"] = getattr(item, "To", "")
    summary["cc"] = getattr(item, "CC", "")

    saved_files = []
    if save_attach and item.Attachments.Count > 0:
        data_dir = get_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        for i in range(1, item.Attachments.Count + 1):
            att = item.Attachments.Item(i)
            safe_filename = att.FileName
            dest_path = os.path.join(data_dir, safe_filename)
            att.SaveAsFile(dest_path)
            saved_files.append(safe_filename)

    summary["saved_attachments"] = saved_files

    return format_response(
        status="ok",
        module="outlook_read",
        action="read",
        preview=f"Read mail '{summary['subject']}' from {summary['sender']}. Attachments saved: {len(saved_files)}",
        agent_directive="VERIFIED: Mail content and attachments extracted.",
        extra={"mail": summary}
    )

def action_folders(ns) -> Dict[str, Any]:
    """Lists folder hierarchy and unread mail counts."""
    tree = []
    for store in ns.Folders:
        store_info = {
            "account": store.Name,
            "folders": []
        }
        for f in store.Folders:
            try:
                unread = f.UnReadItemCount
                total = f.Items.Count
            except Exception:
                unread, total = 0, 0
            store_info["folders"].append({
                "name": f.Name,
                "unread": unread,
                "total": total
            })
        tree.append(store_info)

    return format_response(
        status="ok",
        module="outlook_read",
        action="folders",
        preview=f"Discovered {len(tree)} Outlook accounts/stores with folder statistics.",
        agent_directive="VERIFIED: Folder hierarchy retrieved.",
        extra={"accounts": tree}
    )

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py recipe dispatcher compatible executor."""
    action = params.get("action", "list")
    app = app or get_outlook_app()
    ns = get_mapi_namespace(app)

    if action == "current":
        return action_current(app, ns, bool(params.get("summarize", False)))
    elif action == "list":
        return action_list(ns, params.get("folder", "inbox"), bool(params.get("unread", False)), int(params.get("limit", 10)))
    elif action == "search":
        return action_search(ns, params.get("folder", "inbox"), params.get("query", ""), params.get("from", ""), int(params.get("limit", 10)))
    elif action == "read":
        entry_id = params.get("id")
        if not entry_id:
            return format_response(status="error", module="outlook_read", action="read", preview="Missing 'id' param")
        return action_read(ns, entry_id, bool(params.get("save_attach", False)))
    elif action == "folders":
        return action_folders(ns)
    else:
        return format_response(status="error", module="outlook_read", action=action, preview=f"Unknown action: {action}")

def main():
    parser = argparse.ArgumentParser(description="Outlook Background Mail Reader & Native Search Engine")
    parser.add_argument("--action", choices=["current", "list", "search", "read", "folders"], required=True,
                        help="Action to perform: current, list, search, read, folders")
    parser.add_argument("--id", type=str, help="EntryID of the email to read")
    parser.add_argument("--folder", type=str, default="inbox", help="Folder name or alias (default: inbox)")
    parser.add_argument("--unread", action="store_true", help="Filter for unread emails only")
    parser.add_argument("--query", type=str, help="Search query string for subject/body")
    parser.add_argument("--from", dest="from_sender", type=str, help="Filter by sender name or email")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of emails to return (default: 10)")
    parser.add_argument("--save-attach", action="store_true", help="Automatically save all attachments to data_dir")
    parser.add_argument("--summarize", action="store_true", help="Summarize current selected mail")

    args = parser.parse_args()

    try:
        app = get_outlook_app()
        ns = get_mapi_namespace(app)

        if args.action == "current":
            res = action_current(app, ns, args.summarize)
        elif args.action == "list":
            res = action_list(ns, args.folder, args.unread, args.limit)
        elif args.action == "search":
            res = action_search(ns, args.folder, args.query, args.from_sender, args.limit)
        elif args.action == "read":
            if not args.id:
                emit_response(format_response(
                    status="error",
                    module="outlook_read",
                    action="read",
                    preview="--id <entry_id> is required for read action.",
                    agent_directive="STOP_RETRY: Missing --id."
                ))
                sys.exit(1)
            res = action_read(ns, args.id, args.save_attach)
        elif args.action == "folders":
            res = action_folders(ns)
        else:
            res = format_response(status="error", module="outlook_read", action=args.action, preview=f"Unknown action: {args.action}")

        emit_response(res)

    except Exception as e:
        emit_response(format_response(
            status="error",
            module="outlook_read",
            action=args.action,
            preview=f"Outlook COM Error: {str(e)}",
            agent_directive="STOP_RETRY: Verify Outlook is installed and running on Default desktop."
        ))
        sys.exit(1)

if __name__ == "__main__":
    main()
```

=== END FILE: outlook_read.py ===

---

=== FILE: outlook_write.py ===

```python
"""
outlook_write.py - Native Outlook COM Mail Composer, Reply & Forward Engine.
Preserves 100% original conversation history via Outlook's native Reply/Forward methods.
Safely displays draft window on screen by default (Human-in-the-Loop); only sends if --send is explicitly given.
"""
import sys
import os
import argparse
import re
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response
from _outlook_guard import get_outlook_app, get_mapi_namespace, get_current_active_item
from _config import resolve_data_path, get_data_dir

def _attach_files_to_item(mail_item, attach_arg: Optional[str]) -> List[str]:
    """Resolves and attaches files using data_dir path resolver."""
    attached = []
    if not attach_arg:
        return attached

    # Split comma-separated files
    files = [f.strip() for f in attach_arg.split(",") if f.strip()]
    for f in files:
        resolved = resolve_data_path(f)
        if os.path.exists(resolved):
            mail_item.Attachments.Add(resolved)
            attached.append(os.path.basename(resolved))
        else:
            raise FileNotFoundError(f"Attachment file not found: {resolved}")
    return attached

def _format_html_body_prefix(plain_text: str) -> str:
    """Wraps user text in clean styled HTML div to prepend above original history."""
    if not plain_text:
        return ""
    html_lines = plain_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    return (
        f"<div style='font-family: \"Malgun Gothic\", \"Segoe UI\", sans-serif; font-size: 10pt; color: #111;'>"
        f"{html_lines}"
        f"</div><br>"
    )

def _prepend_to_html_body(html: str, prefix_html: str) -> str:
    """HTML 본문의 <body> 태그 바로 뒤에 새 내용을 삽입합니다 (<html> 앞에 붙여 문서 구조가 깨지는 문제 방지)."""
    if not prefix_html:
        return html
    m = re.search(r"<body[^>]*>", html or "", re.IGNORECASE)
    if m:
        return html[:m.end()] + prefix_html + html[m.end():]
    return prefix_html + (html or "")

def _parse_send_flag(value: Any) -> bool:
    """명시적인 참 값(True, "true", "1", "yes")만 발송 요청으로 인정합니다. ("false" 문자열 등이 참으로 처리되는 사고 방지)"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y")
    return False

def _load_default_signature(mail_item) -> None:
    """Inspector를 미리 생성하면 Outlook이 사용자 기본 서명을 본문에 채워 넣습니다 (창은 표시되지 않음)."""
    try:
        _ = mail_item.GetInspector
    except Exception:
        pass

def _finalize(mail_item, send: bool, kind: str, to_desc: str, attached: List[str]) -> Dict[str, Any]:
    """기본은 화면 표시(사용자가 직접 [보내기] 클릭). send=True(명시적 요청)일 때만 수신자 확인 후 발송합니다."""
    subject = mail_item.Subject
    extra = {"to": to_desc, "subject": subject, "attached": attached, "sent": False}

    if send:
        unresolved = []
        try:
            recipients = mail_item.Recipients
            if recipients.Count == 0:
                unresolved.append("(수신자 없음)")
            elif not recipients.ResolveAll():
                for i in range(1, recipients.Count + 1):
                    if not recipients.Item(i).Resolved:
                        unresolved.append(recipients.Item(i).Name)
        except Exception as e:
            unresolved.append(f"(수신자 확인 실패: {e})")

        if unresolved:
            # 주소가 확인되지 않은 메일은 자동 발송하지 않고 사용자 확인 창으로 전환
            mail_item.Display()
            extra["unresolved_recipients"] = unresolved
            return format_response(
                status="partial",
                module="outlook_write",
                action=kind,
                preview=f"Recipient check failed ({', '.join(unresolved)}). Draft displayed on screen instead of sending.",
                agent_directive="STOP_RETRY: 수신자 주소를 확인할 수 없어 발송하지 않고 작성 창만 띄웠습니다. 사용자에게 수신자 확인을 요청하세요.",
                extra=extra
            )

        mail_item.Send()
        extra["sent"] = True
        return format_response(
            status="ok",
            module="outlook_write",
            action=kind,
            preview=f"Sent {kind} mail to '{to_desc}' with subject '{subject}'. Attachments: {len(attached)}",
            agent_directive="VERIFIED: 사용자의 명시적 발송 요청에 따라 메일을 발송했습니다.",
            extra=extra
        )

    mail_item.Display()
    return format_response(
        status="ok",
        module="outlook_write",
        action=kind,
        preview=f"Displayed {kind} mail draft to '{to_desc}' with subject '{subject}' on screen.",
        agent_directive="VERIFIED: 메일 작성 창을 화면에 띄웠습니다. 발송은 사용자가 직접 [보내기]를 눌러야 합니다. 대신 발송하지 마세요.",
        extra=extra
    )

def action_new(app, to: str, cc: str, subject: str, body: str, attach: str, send: bool) -> Dict[str, Any]:
    """Creates a brand new email. Displays window on screen by default."""
    mail = app.CreateItem(0)  # 0 = olMailItem
    _load_default_signature(mail)
    if to:
        mail.To = to
    if cc:
        mail.CC = cc
    if subject:
        mail.Subject = subject
    if body:
        # Body 대입은 사용자 서명을 지우므로 HTML 본문(서명 포함) 앞에 삽입
        mail.HTMLBody = _prepend_to_html_body(mail.HTMLBody, _format_html_body_prefix(body))

    attached = _attach_files_to_item(mail, attach)
    return _finalize(mail, send, "new", to, attached)

def _get_target_item(app, ns, entry_id: Optional[str]):
    if entry_id:
        return ns.GetItemFromID(entry_id)
    target_item, _source = get_current_active_item(app)
    return target_item

def action_reply(app, ns, entry_id: Optional[str], reply_all: bool, body: str, attach: str, send: bool) -> Dict[str, Any]:
    """
    Replies to the active or specified email.
    Uses Outlook's native Reply() / ReplyAll() to preserve 100% of original history, headers and formatting.
    """
    target_item = _get_target_item(app, ns, entry_id)
    if not target_item:
        return format_response(
            status="no_match",
            module="outlook_write",
            action="reply",
            preview="No active email is currently open or selected to reply to. Specify --id <entry_id>.",
            agent_directive="STOP_RETRY: No active email found. User must select an email or provide --id."
        )

    # Use native Reply / ReplyAll to retain native headers & thread lineage
    reply_mail = target_item.ReplyAll() if reply_all else target_item.Reply()
    _load_default_signature(reply_mail)

    # Prepend new message above original history
    if body:
        reply_mail.HTMLBody = _prepend_to_html_body(reply_mail.HTMLBody, _format_html_body_prefix(body))

    attached = _attach_files_to_item(reply_mail, attach)
    return _finalize(reply_mail, send, "reply", reply_mail.To, attached)

def action_forward(app, ns, entry_id: Optional[str], to: str, body: str, attach: str, send: bool) -> Dict[str, Any]:
    """
    Forwards the active or specified email.
    Uses Outlook's native Forward() to preserve complete original email thread.
    """
    target_item = _get_target_item(app, ns, entry_id)
    if not target_item:
        return format_response(
            status="no_match",
            module="outlook_write",
            action="forward",
            preview="No active email found to forward. Specify --id <entry_id>.",
            agent_directive="STOP_RETRY: No active email found."
        )

    fwd_mail = target_item.Forward()
    _load_default_signature(fwd_mail)
    if to:
        fwd_mail.To = to

    if body:
        fwd_mail.HTMLBody = _prepend_to_html_body(fwd_mail.HTMLBody, _format_html_body_prefix(body))

    attached = _attach_files_to_item(fwd_mail, attach)
    return _finalize(fwd_mail, send, "forward", to, attached)

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """에이전트/레시피 호출용 실행기.

    params["send"]는 사용자가 '보내줘', '바로 발송' 등 발송을 명시적으로 요청한 경우에만 true로 지정합니다.
    생략하면 작성 창만 화면에 띄우고 사용자가 직접 [보내기]를 누릅니다.
    """
    action = params.get("action", "new")
    try:
        app = app or get_outlook_app()
        ns = get_mapi_namespace(app)

        send_flag = _parse_send_flag(params.get("send", False))
        attach_files = params.get("attach", "") or ""
        body_text = params.get("body", "") or ""

        if action == "new":
            return action_new(app, params.get("to", "") or "", params.get("cc", "") or "", params.get("subject", "") or "", body_text, attach_files, send_flag)
        elif action == "reply":
            return action_reply(app, ns, params.get("id"), _parse_send_flag(params.get("reply_all", False)), body_text, attach_files, send_flag)
        elif action == "forward":
            return action_forward(app, ns, params.get("id"), params.get("to", "") or "", body_text, attach_files, send_flag)
        return format_response(status="error", module="outlook_write", action=action, preview=f"Unknown action: {action}",
                               agent_directive="STOP_RETRY: action은 new, reply, forward 중 하나여야 합니다.")
    except Exception as e:
        return format_response(
            status="error",
            module="outlook_write",
            action=action,
            preview=f"Outlook Compose Error: {e}",
            agent_directive="STOP_RETRY: Check Outlook status or attachment existence."
        )

def main():
    parser = argparse.ArgumentParser(description="Outlook Safe Mail Composer, Reply & Forward Engine")
    parser.add_argument("--action", choices=["new", "reply", "forward"], required=True,
                        help="Action to perform: new, reply, forward")
    parser.add_argument("--id", type=str, help="EntryID of the email to reply or forward (defaults to currently active mail)")
    parser.add_argument("--to", type=str, help="Recipient email address(es)")
    parser.add_argument("--cc", type=str, help="CC recipient email address(es)")
    parser.add_argument("--subject", type=str, help="Email subject")
    parser.add_argument("--body", type=str, help="Email body text to prepend")
    parser.add_argument("--attach", type=str, help="Comma-separated filenames/paths to attach from data_dir")
    parser.add_argument("--reply-all", action="store_true", help="Reply to all recipients on reply action")
    parser.add_argument("--send", action="store_true",
                        help="사용자가 명시적으로 요청한 경우에만 사용: 화면 표시 대신 수신자 확인 후 즉시 발송 (기본: 작성 창만 표시)")

    args = parser.parse_args()

    params = {
        "action": args.action,
        "id": args.id,
        "to": args.to,
        "cc": args.cc,
        "subject": args.subject,
        "body": args.body,
        "attach": args.attach,
        "reply_all": args.reply_all,
        "send": args.send,
    }
    res = execute(None, None, params)
    emit_response(res)
    sys.exit(0 if res.get("status") == "ok" else 1)

if __name__ == "__main__":
    main()
```

=== END FILE: outlook_write.py ===

---

=== FILE: pdf_read.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_data_dir
from _cache import get_file_cache, save_file_cache

def resolve_target_file(target: str) -> str:
    """대상 파일 경로를 해석하며, 상대 경로 시 data_dir 또는 CWD에서 탐색합니다."""
    if not target:
        raise ValueError("대상 파일 경로(target)가 필요합니다.")
    if os.path.isabs(target):
        if os.path.exists(target):
            return target
    # 1. data_dir 탐색
    data_candidate = os.path.join(get_data_dir(), target)
    if os.path.exists(data_candidate):
        return os.path.abspath(data_candidate)
    # 2. CWD 탐색
    cwd_candidate = os.path.abspath(target)
    if os.path.exists(cwd_candidate):
        return cwd_candidate
    raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {target}")

def extract_via_word_com(abs_path: str) -> Dict[str, Any]:
    """사내 DRM(문서보안) 암호화 PDF를 인증 앱인 MS Word COM을 통해 실시간 복호화하여 추출합니다."""
    log_debug(f"사내 DRM 감지: MS Word COM 백그라운드 복호화 추출 시도: {abs_path}")
    try:
        import win32com.client
        import pythoncom
    except ImportError:
        raise RuntimeError("pywin32가 설치되어 있지 않아 Word DRM 복호화를 실행할 수 없습니다.")

    word = None
    doc = None
    try:
        # 백그라운드 독립 Word 인스턴스 기동
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0

        # Word의 내장 PDF 리플로우 변환기를 통한 DRM 자동 인증 복호화 열기
        doc = word.Documents.Open(
            FileName=abs_path,
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False
        )

        raw_text = doc.Content.Text
        # 제어문자 정리
        cleaned_text = raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n\n")
        cleaned_text = "".join(ch for ch in cleaned_text if ch >= " " or ch in "\n\t").strip()

        # 페이지 단위 구분선 기준 또는 2000자 블록으로 분할
        pages = [p.strip() for p in cleaned_text.split("\n\n") if p.strip()]
        if not pages:
            pages = [cleaned_text]

        metadata = {
            "title": os.path.basename(abs_path),
            "backend": "word_com_drm_decryptor"
        }
        return {"pages": pages, "metadata": metadata}

    except Exception as e:
        raise RuntimeError(f"Word COM DRM 복호화 추출 실패: {e}")
    finally:
        if doc:
            try:
                doc.Close(False)
            except Exception:
                pass
        if word:
            try:
                word.Quit()
            except Exception:
                pass

def extract_pdf_data(abs_path: str) -> Dict[str, Any]:
    """PDF 파일에서 메타데이터와 페이지별 텍스트를 초고속 추출합니다 (pymupdf 우선, pypdf, Word DRM 폴백)."""
    pages_text: List[str] = []
    metadata: Dict[str, Any] = {}

    # 1. pymupdf 시도 (초고속 C기반 엔진)
    try:
        import pymupdf  # or fitz
        doc = pymupdf.open(abs_path)
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", "")
        }
        for page in doc:
            pages_text.append(page.get_text())
        doc.close()
        # 내용이 정상 평문인지 점검 (DRM 파일이면 추출 텍스트가 비어있거나 깨짐)
        if pages_text and any(len(p.strip()) > 0 for p in pages_text):
            return {"pages": pages_text, "metadata": metadata}
    except Exception as e_mupdf:
        log_debug(f"pymupdf 추출 실패 또는 미설치, pypdf 시도: {e_mupdf}")

    # 2. pypdf 폴백
    try:
        import pypdf
        reader = pypdf.PdfReader(abs_path)
        if reader.metadata:
            metadata = {
                "title": getattr(reader.metadata, "title", "") or "",
                "author": getattr(reader.metadata, "author", "") or ""
            }
        for page in reader.pages:
            pages_text.append(page.extract_text() or "")
        if pages_text and any(len(p.strip()) > 0 for p in pages_text):
            return {"pages": pages_text, "metadata": metadata}
    except Exception as e_pypdf:
        log_debug(f"pypdf 추출 실패 또는 DRM 감지: {e_pypdf}")

    # 3. 사내 DRM 복호화 Word COM 폴백
    return extract_via_word_com(abs_path)

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 주입받은 인자로 PDF 텍스트 및 정보를 고속 조회(캐시 지원)합니다."""
    target = params.get("target") or params.get("file")
    page_arg = params.get("page")
    search_kw = (params.get("search") or "").strip()
    fmt = (params.get("format") or "text").lower()

    if not target:
        return format_response(
            status="error",
            module="pdf_read",
            action="read",
            preview="target parameter is required",
            agent_directive="STOP_RETRY: Missing target file path."
        )

    try:
        abs_path = resolve_target_file(target)
        file_name = os.path.basename(abs_path)
        sub_key = f"{page_arg}_{search_kw}_{fmt}"

        # 1. mtime 기반 디스크 캐시 검사 (0.001s)
        cached_data = get_file_cache(abs_path, sub_key=sub_key)
        if cached_data:
            return format_response(
                status="ok",
                module="pdf_read",
                action="read_cached",
                preview=cached_data.get("preview", f"Read PDF from cache: {file_name}"),
                agent_directive="VERIFIED: PDF data retrieved from disk cache.",
                extra=cached_data
            )

        # 2. 캐시 미스 시 파싱 수행
        extracted = extract_pdf_data(abs_path)
        all_pages = extracted["pages"]
        total_pages = len(all_pages)

        # 특정 페이지만 요청된 경우
        target_page_idx = None
        if page_arg is not None:
            target_page_idx = int(page_arg)
            if target_page_idx < 1 or target_page_idx > total_pages:
                return format_response(
                    status="no_match",
                    module="pdf_read",
                    action="read_page",
                    preview=f"Requested page {target_page_idx} out of range (Total: {total_pages})",
                    agent_directive="STOP_RETRY: Page index out of range."
                )

        # 검색 키워드가 있는 경우
        search_matches = []
        if search_kw:
            for p_num, p_text in enumerate(all_pages, start=1):
                if search_kw in p_text:
                    # 매칭된 위치 전후 스니펫 수집
                    start_idx = max(0, p_text.find(search_kw) - 40)
                    end_idx = min(len(p_text), p_text.find(search_kw) + len(search_kw) + 60)
                    snippet = p_text[start_idx:end_idx].replace("\n", " ").strip()
                    search_matches.append({
                        "page": p_num,
                        "snippet": f"...{snippet}..."
                    })

            if not search_matches:
                return format_response(
                    status="no_match",
                    module="pdf_read",
                    action="search",
                    preview=f"Keyword '{search_kw}' not found in {file_name}",
                    agent_directive="STOP_RETRY: Keyword not found in PDF."
                )

        # 출력 포맷 결정
        total_chars = sum(len(p) for p in all_pages)
        if target_page_idx is not None:
            result_text = all_pages[target_page_idx - 1]
            preview_msg = f"PDF: {file_name} (Page {target_page_idx}/{total_pages}, {len(result_text)} chars)"
            payload_data = result_text
        elif fmt == "summary":
            preview_msg = f"PDF: {file_name} | {total_pages}페이지 | 총 글자: {total_chars}자"
            payload_data = {
                "total_pages": total_pages,
                "total_characters": total_chars,
                "metadata": extracted.get("metadata", {})
            }
        elif fmt == "pages":
            preview_msg = f"PDF: {file_name} ({total_pages} pages, {total_chars} chars)"
            payload_data = [{"page": i, "characters": len(p), "text": p} for i, p in enumerate(all_pages, start=1)]
        else:
            # 전체 텍스트 병합
            full_text = "\n\n--- [Page Separator] ---\n\n".join(all_pages)
            preview_msg = f"PDF: {file_name} ({total_pages} pages, {total_chars} chars)"
            payload_data = full_text

        items = [{"loc": f"Page {i}", "page": i, "text": p} for i, p in enumerate(all_pages, start=1)]

        result_payload = {
            "file": file_name,
            "path": abs_path,
            "file_type": "pdf",
            "total_pages": total_pages,
            "total_characters": total_chars,
            "preview": preview_msg,
            "items": items,
            "data": payload_data,
            "search_matches": search_matches if search_kw else None
        }

        # 3. 캐시 저장 (최근 2개 유지)
        save_file_cache(abs_path, result_payload, sub_key=sub_key)

        return format_response(
            status="ok",
            module="pdf_read",
            action="read_pdf",
            preview=preview_msg,
            agent_directive="VERIFIED: PDF read successfully.",
            extra=result_payload
        )

    except Exception as e:
        return format_response(
            status="error",
            module="pdf_read",
            action="read",
            preview=str(e),
            agent_directive=f"STOP_RETRY: PDF read failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PDF Read Micro Block (High Performance & Cache)")
    parser.add_argument("--target", "--file", required=True, help="PDF 파일 경로 또는 data_dir 내 파일명")
    parser.add_argument("--page", type=int, help="특정 페이지만 읽기 (1-based)")
    parser.add_argument("--search", type=str, help="특정 단어 검색")
    parser.add_argument("--format", choices=["text", "pages", "summary"], default="text", help="출력 형식")
    args = parser.parse_args()

    params = {
        "target": args.target,
        "page": args.page,
        "search": args.search,
        "format": args.format
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: pdf_read.py ===

---

=== FILE: ppt_edit.py ===

```python
import sys
import os
import json
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import (
    format_response, emit_response, log_debug, parse_color_to_bgr,
    parse_replace_rules, normalize_and_expand_rules
)
from _com_guard import ppt_session
from _config import resolve_data_path

def apply_style_to_textrange(tr, rule: Dict[str, Any]) -> None:
    """PowerPoint TextRange 객체에 폰트 서식을 적용합니다."""
    if "bold" in rule:
        tr.Font.Bold = bool(rule["bold"])
    if "italic" in rule:
        tr.Font.Italic = bool(rule["italic"])
    if "size" in rule:
        tr.Font.Size = float(rule["size"])
    if "color" in rule:
        bgr = parse_color_to_bgr(rule["color"])
        if bgr is not None:
            tr.Font.Color.RGB = bgr

def replace_in_textframe(tf, find_str: str, rule: Any) -> int:
    """단일 TextFrame 내부에서 특정 문자열을 찾아 치환 및 서식을 적용합니다."""
    matched = 0
    replace_str = find_str
    if isinstance(rule, dict):
        replace_str = str(rule.get("text") or rule.get("replace") or find_str)
    elif isinstance(rule, str):
        replace_str = rule

    tr = tf.TextRange
    # 텍스트 내에 없거나 검색어가 비어있으면 COM Find 호출 없이 즉시 스킵 (초고속 방어)
    if not tr or not tr.Text or not find_str or find_str not in tr.Text:
        return 0

    max_loops = 500
    loop_count = 0
    found_tr = tr.Find(FindWhat=find_str)
    while found_tr is not None and loop_count < max_loops:
        loop_count += 1
        matched += 1
        try:
            found_tr.Text = replace_str
            if isinstance(rule, dict):
                apply_style_to_textrange(found_tr, rule)
        except Exception as e:
            log_debug(f"서식 적용 예외: {e}")
            break

        prev_start = found_tr.Start
        # PowerPoint COM: After=N은 N번째 문자 바로 다음(N+1)부터 검색함을 의미
        after_pos = max(0, prev_start + len(replace_str) - 1)
        if after_pos >= tr.Length:
            break

        try:
            found_tr = tr.Find(FindWhat=find_str, After=after_pos)
            if found_tr is not None and found_tr.Start <= prev_start:
                # PowerPoint COM Find의 순환 검색(Wrap-around) 방어
                break
        except Exception:
            break

    return matched

def process_shape_for_replace(shape, rules: Dict[str, Any]) -> int:
    """도형(일반, 표, 그룹화 도형) 내부 텍스트를 재귀적으로 찾아 치환합니다."""
    applied = 0
    # 1. 그룹화된 도형 (msoGroup = 6) 재귀 탐색
    try:
        if getattr(shape, "Type", None) == 6 or hasattr(shape, "GroupItems"):
            for sub_shape in shape.GroupItems:
                applied += process_shape_for_replace(sub_shape, rules)
            return applied
    except Exception:
        pass

    # 2. 일반 텍스트 상자 / 도형
    try:
        if shape.HasTextFrame and shape.TextFrame.HasText:
            tf = shape.TextFrame
            for target_word, rule in rules.items():
                cnt = replace_in_textframe(tf, str(target_word), rule)
                applied += cnt
    except Exception:
        pass

    # 3. 표(Table) 내부 셀
    try:
        if shape.HasTable:
            tbl = shape.Table
            for row_idx in range(1, tbl.Rows.Count + 1):
                for col_idx in range(1, tbl.Columns.Count + 1):
                    cell_tf = tbl.Cell(row_idx, col_idx).Shape.TextFrame
                    if cell_tf.HasText:
                        for target_word, rule in rules.items():
                            cnt = replace_in_textframe(cell_tf, str(target_word), rule)
                            applied += cnt
    except Exception:
        pass

    return applied

def execute(app, prs, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 PowerPoint 다중 치환 및 서식을 적용합니다."""
    mapping_file = params.get("mapping_file") or params.get("replace_map")
    target_slide_idx = params.get("slide") or params.get("pages")
    find_kw = params.get("find")
    replace_to = params.get("replace")
    style_spec = params.get("style", {})

    rules = {}
    if mapping_file:
        rules = parse_replace_rules(mapping_file, resolve_path_fn=resolve_data_path)
    elif find_kw:
        single_rule = dict(style_spec)
        if replace_to:
            single_rule["text"] = replace_to
        rules = {find_kw: single_rule}

    # ' | ' 등 가상 결합 구분자로 묶인 항목 자동 분해 및 확장
    rules = normalize_and_expand_rules(rules)

    if not rules:
        return format_response(
            status="no_match",
            module="ppt_edit",
            action="apply_edit",
            preview="No edit or replacement rules provided",
            agent_directive="STOP_RETRY: Empty edit map."
        )

    # 검사 대상 슬라이드 결정
    if target_slide_idx:
        slides_to_check = [prs.Slides(int(target_slide_idx))]
    else:
        slides_to_check = [s for s in prs.Slides]

    total_applied = 0

    for slide in slides_to_check:
        for shape in slide.Shapes:
            applied_cnt = process_shape_for_replace(shape, rules)
            total_applied += applied_cnt

    if total_applied == 0:
        return format_response(
            status="no_match",
            module="ppt_edit",
            action="apply_edit",
            preview="0 matches found for edit rules in PowerPoint",
            agent_directive="STOP_RETRY: Target text not found in presentation. Proceed."
        )

    return format_response(
        status="ok",
        module="ppt_edit",
        action="apply_edit",
        preview=f"{total_applied} replacements/styles successfully applied in PowerPoint",
        agent_directive="VERIFIED: PowerPoint edits applied. Do not re-verify.",
        extra={"applied_count": total_applied}
    )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Edit & Style Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--slide", type=int, help="대상 슬라이드 번호 (생략 시 전체 슬라이드)")
    parser.add_argument("--replace-map", type=str, help="styles.json 또는 edit_rules.json 경로")
    parser.add_argument("--find", type=str, help="검색 단어")
    parser.add_argument("--replace", type=str, help="치환할 단어")
    parser.add_argument("--bold", action="store_true", help="굵게")
    parser.add_argument("--color", type=str, help="글자색")
    parser.add_argument("--size", type=float, help="폰트 크기")
    args = parser.parse_args()

    style = {}
    if args.bold: style["bold"] = True
    if args.color: style["color"] = args.color
    if args.size: style["size"] = args.size

    params = {
        "slide": args.slide,
        "mapping_file": args.replace_map,
        "find": args.find,
        "replace": args.replace,
        "style": style
    }

    with ppt_session(target=args.target, snapshot=True) as (app, prs):
        res = execute(app, prs, params)
        emit_response(res)
    sys.stdout.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
```

=== END FILE: ppt_edit.py ===

---

=== FILE: ppt_export.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_data_dir
from _com_guard import ppt_session

# PowerPoint 상수
PP_FIXED_FORMAT_TYPE_PDF = 2
PP_SAVE_AS_PDF = 32

def resolve_output_path(file_path: str, default_ext: str = ".pdf") -> str:
    """출력 경로를 해석하며 파일명만 기입된 경우 data_dir 하위로 매핑합니다."""
    if not file_path:
        raise ValueError("출력 파일명(output_file)이 필요합니다.")
    if not os.path.splitext(file_path)[1]:
        file_path += default_ext
    if os.path.isabs(file_path):
        out_path = file_path
    else:
        out_path = os.path.join(get_data_dir(), file_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    return os.path.abspath(out_path)

def execute(app, prs, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 PowerPoint 프레젠테이션을 PDF 또는 복제본 PPTX로 안전하게 내보냅니다."""
    out_arg = params.get("output_file") or params.get("output")
    fmt = (params.get("format") or "").lower()

    if not out_arg:
        return format_response(
            status="error",
            module="ppt_export",
            action="export",
            preview="output_file parameter is required",
            agent_directive="STOP_RETRY: Missing output file path."
        )

    try:
        out_ext = os.path.splitext(out_arg)[1].lower()
        if fmt:
            out_format = fmt
        elif out_ext in [".pdf", ".pptx", ".ppt"]:
            out_format = "pdf" if out_ext == ".pdf" else "pptx"
        else:
            out_format = "pdf"

        # 형식과 확장자 불일치 방지 (예: --format pdf -o deck.pptx -> deck.pdf)
        # SaveCopyAs는 원본 형식으로 저장하므로 pptx 사본의 확장자는 원본 확장자(.pptx/.pptm/.ppt)를 따름
        if out_format == "pdf":
            wanted_ext = ".pdf"
        else:
            src_ext = os.path.splitext(str(getattr(prs, "FullName", "")))[1].lower()
            wanted_ext = src_ext if src_ext in (".pptx", ".pptm", ".ppt") else ".pptx"
        if out_ext and out_ext != wanted_ext:
            out_arg = os.path.splitext(out_arg)[0] + wanted_ext
        final_out_path = resolve_output_path(out_arg, default_ext=wanted_ext)
        log_debug(f"PowerPoint Export 대상: '{prs.Name}', 포맷='{out_format}', 경로='{final_out_path}'")

        if out_format == "pdf":
            # ExportAsFixedFormat 우선 시도 (2 = ppFixedFormatTypePDF)
            saved_pdf = False
            pdf_missing_feature = False
            try:
                prs.ExportAsFixedFormat(final_out_path, PP_FIXED_FORMAT_TYPE_PDF)
                saved_pdf = True
            except Exception as e_fixed:
                log_debug(f"ExportAsFixedFormat 실패, SaveAs 시도: {e_fixed}")
                raw_fixed = repr(e_fixed) + " " + str(e_fixed)
                # -2147467259(E_FAIL)는 파일 잠금 등 일반 실패에도 쓰이므로 판별 근거로 사용하지 않음
                if "기능이 설치되어 있지 않아" in raw_fixed or "can not be converted" in raw_fixed:
                    pdf_missing_feature = True

            if not saved_pdf:
                try:
                    prs.SaveAs(final_out_path, PP_SAVE_AS_PDF)
                    saved_pdf = True
                except Exception as e_saveas:
                    raw_saveas = repr(e_saveas) + " " + str(e_saveas)
                    if pdf_missing_feature or "기능이 설치되어 있지 않아" in raw_saveas:
                        raise RuntimeError("PowerPoint PDF 내보내기 기능(Office 2007 추가 기능)이 설치되어 있지 않습니다. --format pptx 형식을 사용하세요.")
                    raise e_saveas
            preview_msg = f"Exported PowerPoint presentation to PDF: {os.path.basename(final_out_path)}"
        elif out_format in ["pptx", "ppt"]:
            # 원본 보존 복제본 저장
            prs.SaveCopyAs(final_out_path)
            preview_msg = f"Exported PowerPoint copy to PPTX: {os.path.basename(final_out_path)}"
        else:
            raise ValueError(f"지원하지 않는 PowerPoint 내보내기 형식입니다: {out_format} (pdf 또는 pptx 지원)")

        return format_response(
            status="ok",
            module="ppt_export",
            action=f"export_{out_format}",
            preview=preview_msg,
            agent_directive="VERIFIED: Presentation exported successfully. Active window preserved.",
            extra={
                "file_path": final_out_path,
                "format": out_format
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="ppt_export",
            action="export",
            preview=str(e),
            agent_directive=f"STOP_RETRY: PowerPoint export failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Export Micro Block (PDF & PPTX)")
    parser.add_argument("--target", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--output", "-o", required=True, help="저장할 파일명 (.pdf 또는 .pptx)")
    parser.add_argument("--format", choices=["pdf", "pptx"], help="출력 포맷 강제 지정")
    args = parser.parse_args()

    params = {
        "output_file": args.output,
        "format": args.format
    }

    try:
        with ppt_session(target=args.target) as (app, prs):
            res = execute(app, prs, params)
    except Exception as e:
        res = format_response("error", "ppt_export", "export", preview=f"PowerPoint 세션 오류: {e}",
                              agent_directive="STOP_RETRY: PowerPoint 프레젠테이션에 연결하지 못했습니다. 사용자에게 보고하세요.")
    emit_response(res)
    sys.exit(0 if res.get("status") == "ok" else 1)

if __name__ == "__main__":
    main()
```

=== END FILE: ppt_export.py ===

---

=== FILE: ppt_inspect.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any, List

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, run_session_tool
from _com_guard import ppt_session

def inspect_shape_recursive(shape):
    """도형(그룹 포함)의 문자수, 표수, 차트수, 그림수를 재귀적으로 계산합니다."""
    chars = 0
    tables = 0
    charts = 0
    pics = 0
    title = ""

    # 1. 그룹화된 도형 (msoGroup = 6)
    try:
        if getattr(shape, "Type", None) == 6 or hasattr(shape, "GroupItems"):
            for sub in shape.GroupItems:
                c, t, ch, p, ttl = inspect_shape_recursive(sub)
                chars += c
                tables += t
                charts += ch
                pics += p
                if not title and ttl:
                    title = ttl
            return chars, tables, charts, pics, title
    except Exception:
        pass

    # 2. 일반 텍스트
    try:
        if shape.HasTextFrame and shape.TextFrame.HasText:
            txt = shape.TextFrame.TextRange.Text.strip()
            chars += len(txt)
            if not title and len(txt) > 0:
                title = txt[:40]
    except Exception:
        pass

    # 3. 표
    try:
        if shape.HasTable:
            tables += 1
            tbl = shape.Table
            for r in range(1, tbl.Rows.Count + 1):
                for c in range(1, tbl.Columns.Count + 1):
                    cell_tf = tbl.Cell(r, c).Shape.TextFrame
                    if cell_tf.HasText:
                        chars += len(cell_tf.TextRange.Text.strip())
    except Exception:
        pass

    # 4. 차트 및 그림
    try:
        if getattr(shape, "Type", None) == 3 or getattr(shape, "HasChart", False):
            charts += 1
        elif getattr(shape, "Type", None) in [11, 13]:
            pics += 1
    except Exception:
        pass

    return chars, tables, charts, pics, title

def execute(app, prs, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 PowerPoint 프레젠테이션 상태를 초고속 진단합니다."""
    try:
        # 활성 슬라이드 인덱스 저장
        original_slide_idx = None
        try:
            original_slide_idx = app.ActiveWindow.View.Slide.SlideIndex
        except Exception:
            pass

        prs_name = prs.Name
        total_slides = prs.Slides.Count
        slides_summary = []
        total_chars = 0
        total_tables = 0
        total_charts = 0
        total_pictures = 0

        for i in range(1, total_slides + 1):
            slide = prs.Slides(i)
            shape_count = slide.Shapes.Count
            slide_chars = 0
            slide_tables = 0
            slide_charts = 0
            slide_pictures = 0
            title_text = ""

            for shape in slide.Shapes:
                c, t, ch, p, ttl = inspect_shape_recursive(shape)
                slide_chars += c
                slide_tables += t
                slide_charts += ch
                slide_pictures += p
                if not title_text and ttl:
                    title_text = ttl

            total_chars += slide_chars
            total_tables += slide_tables
            total_charts += slide_charts
            total_pictures += slide_pictures

            slides_summary.append({
                "slide_index": i,
                "title": title_text or "(제목 없음)",
                "shapes_count": shape_count,
                "tables_count": slide_tables,
                "charts_count": slide_charts,
                "pictures_count": slide_pictures,
                "characters_count": slide_chars
            })

        # 열려 있는 전체 PowerPoint 프레젠테이션 목록 조회
        open_prs_list = []
        try:
            from _com_guard import get_all_running_ppt_presentations
            all_running = get_all_running_ppt_presentations()
            for item in all_running:
                open_prs_list.append({
                    "name": item["name"],
                    "path": item["path"],
                    "saved": item.get("saved", True),
                    "slides_count": item.get("slides_count", 0),
                    "active": (item["name"] == prs_name)
                })
        except Exception:
            pass
        if not open_prs_list:
            open_prs_list = [{"name": prs_name, "path": getattr(prs, "FullName", ""), "slides_count": total_slides, "active": True}]

        # 활성 창 뷰 슬라이드 및 선택/커서 위치 정밀 추출
        active_slide_index = 1
        selection_info = {}
        try:
            win = app.ActiveWindow
            if win is not None:
                try:
                    active_slide_index = win.View.Slide.SlideIndex
                except Exception:
                    pass

                sel = win.Selection
                sel_type = getattr(sel, "Type", 0)  # 0=None, 1=Slide, 2=Shape, 3=Text
                sel_type_name = "none"
                selected_shape_name = ""
                selected_text = ""
                text_start = None
                text_length = None

                if sel_type == 1:
                    sel_type_name = "slide"
                    try:
                        active_slide_index = sel.SlideRange(1).SlideIndex
                    except Exception:
                        pass
                elif sel_type == 2:
                    sel_type_name = "shape"
                    try:
                        selected_shape_name = sel.ShapeRange(1).Name
                    except Exception:
                        pass
                elif sel_type == 3:
                    sel_type_name = "text"
                    try:
                        selected_shape_name = sel.ShapeRange(1).Name
                    except Exception:
                        pass
                    try:
                        tr = sel.TextRange
                        selected_text = tr.Text.strip() if tr.Text else ""
                        text_start = tr.Start
                        text_length = tr.Length
                    except Exception:
                        pass

                selection_info = {
                    "active_slide": active_slide_index,
                    "selection_type": sel_type_name,
                    "shape_name": selected_shape_name,
                    "selected_text": selected_text,
                    "cursor_start": text_start,
                    "cursor_length": text_length
                }
        except Exception as e:
            log_debug(f"PPT selection info error: {e}")

        open_prs_names = [p["name"] for p in open_prs_list]
        sel_desc = f"슬라이드 {active_slide_index}번"
        if selection_info.get("selection_type") == "text":
            sel_desc += f" (텍스트 커서: {selection_info.get('shape_name')})"
        elif selection_info.get("selection_type") == "shape":
            sel_desc += f" (도형 선택: {selection_info.get('shape_name')})"

        summary_preview = (
            f"열린 문서: {len(open_prs_list)}개 ({', '.join(open_prs_names)}) | 활성: {prs_name} [{sel_desc}] | "
            f"슬라이드: {total_slides}장 | 차트: {total_charts}개 | 이미지: {total_pictures}개 | 표: {total_tables}개"
        )

        # 활성 슬라이드 복원
        try:
            if original_slide_idx is not None:
                app.ActiveWindow.View.GotoSlide(original_slide_idx)
        except Exception:
            pass

        return format_response(
            status="ok",
            module="ppt_inspect",
            action="inspect_presentation",
            preview=summary_preview,
            agent_directive="VERIFIED: PowerPoint inspection complete.",
            extra={
                "presentation": prs_name,
                "open_presentations": open_prs_list,
                "total_open_presentations": len(open_prs_list),
                "active_slide": active_slide_index,
                "selection": selection_info,
                "total_slides": total_slides,
                "total_characters": total_chars,
                "total_tables": total_tables,
                "total_charts": total_charts,
                "total_pictures": total_pictures,
                "slides_summary": slides_summary
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="ppt_inspect",
            action="inspect",
            preview=str(e),
            agent_directive=f"STOP_RETRY: PowerPoint inspection failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Inspection Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--list-presentations", "--all", dest="list_presentations", action="store_true", help="실행 중인 모든 PowerPoint 프레젠테이션 목록만 고속 조회")
    args = parser.parse_args()

    if args.list_presentations:
        from _com_guard import get_all_running_ppt_presentations
        all_running = get_all_running_ppt_presentations()
        prs_summary = []
        for item in all_running:
            prs_summary.append({
                "name": item["name"],
                "path": item["path"],
                "saved": item.get("saved", True),
                "slides_count": item.get("slides_count", 0),
                "active": item.get("is_active", False)
            })

        names_preview = ", ".join([f"{p['name']}{' (Active)' if p['active'] else ''}" for p in prs_summary])
        res = format_response(
            status="ok",
            module="ppt_inspect",
            action="list_presentations",
            preview=f"총 {len(prs_summary)}개의 열린 PowerPoint 프레젠테이션 감지: [{names_preview}]",
            agent_directive="VERIFIED: Running presentations enumerated across PowerPoint instances.",
            extra={
                "total_count": len(prs_summary),
                "presentations": prs_summary
            }
        )
        emit_response(res)
        return

    run_session_tool("ppt_inspect", "inspect",
                     lambda: ppt_session(target=args.target),
                     lambda app, prs: execute(app, prs, {}))

if __name__ == "__main__":
    main()
```

=== END FILE: ppt_inspect.py ===

---

=== FILE: ppt_read.py ===

```python
import sys
import os
import zipfile
import argparse
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_data_dir
from _cache import get_file_cache, save_file_cache
from _com_guard import ppt_session

def resolve_target_file(target: str) -> str:
    if not target or target.strip().lower() == "active":
        return "active"
    if os.path.isabs(target) and os.path.exists(target):
        return target
    data_candidate = os.path.join(get_data_dir(), target)
    if os.path.exists(data_candidate):
        return os.path.abspath(data_candidate)
    cwd_candidate = os.path.abspath(target)
    if os.path.exists(cwd_candidate):
        return cwd_candidate
    return target

def extract_texts_from_shape(shape) -> List[str]:
    """도형(일반, 표, 그룹화 도형) 내부의 모든 텍스트를 재귀적으로 추출합니다."""
    texts = []
    # 1. 그룹화된 도형 (msoGroup = 6) 재귀 탐색
    try:
        if getattr(shape, "Type", None) == 6 or hasattr(shape, "GroupItems"):
            for sub_shape in shape.GroupItems:
                texts.extend(extract_texts_from_shape(sub_shape))
            return texts
    except Exception:
        pass

    # 2. 일반 텍스트 상자
    try:
        if shape.HasTextFrame and shape.TextFrame.HasText:
            txt = shape.TextFrame.TextRange.Text.strip()
            if txt:
                texts.append(txt)
    except Exception:
        pass

    # 3. 표(Table) 내부 셀 (표 행 단위로 파이프 연결하여 깔끔한 표 구조 제공)
    try:
        if shape.HasTable:
            tbl = shape.Table
            for r in range(1, tbl.Rows.Count + 1):
                row_cells = []
                for c in range(1, tbl.Columns.Count + 1):
                    cell_tf = tbl.Cell(r, c).Shape.TextFrame
                    if cell_tf.HasText:
                        txt = cell_tf.TextRange.Text.strip()
                        if txt:
                            row_cells.append(txt)
                if row_cells:
                    texts.append(" | ".join(row_cells))
            return texts
    except Exception:
        pass

    return texts

def extract_pptx_xml(abs_path: str) -> Dict[str, Any]:
    """PowerPoint PPTX 파일의 XML(ppt/slides/slide*.xml)을 직접 파싱하여 0.005초 만에 슬라이드별 텍스트를 추출합니다."""
    items = []
    
    with zipfile.ZipFile(abs_path, 'r') as z:
        # 슬라이드 파일 식별 및 정렬 (slide1.xml, slide2.xml, ...)
        slide_files = [f for f in z.namelist() if f.startswith("ppt/slides/slide") and f.endswith(".xml")]
        # 번호순 정렬
        def get_slide_num(f_name):
            base = os.path.basename(f_name)
            num_part = "".join(ch for ch in base if ch.isdigit())
            return int(num_part) if num_part else 0
        slide_files.sort(key=get_slide_num)

        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}

        for s_idx, sf in enumerate(slide_files, start=1):
            xml_content = z.read(sf)
            root = ET.fromstring(xml_content)
            
            # 슬라이드 내 모든 텍스트 노드(<a:t>) 수집
            slide_texts = []
            for t_node in root.findall(".//a:t", ns):
                if t_node.text and t_node.text.strip():
                    slide_texts.append(t_node.text.strip())

            s_text = "\n\n".join(slide_texts)
            if s_text:
                items.append({
                    "loc": f"Slide {s_idx}",
                    "slide": s_idx,
                    "text": s_text,
                    "tokens_count": len(slide_texts)
                })

    full_text = "\n\n".join(f"[{it['loc']}] {it['text']}" for it in items)
    return {
        "items": items,
        "total_slides": len(items),
        "full_text": full_text
    }

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """PowerPoint 프레젠테이션의 슬라이드별 텍스트와 위치 메타데이터를 고속 조회(캐시 지원)합니다."""
    target = params.get("target") or params.get("file") or "active"
    slide_arg = params.get("slide")
    search_kw = (params.get("search") or "").strip()
    fmt = (params.get("format") or "text").lower()

    resolved_target = resolve_target_file(target)
    is_active = (resolved_target == "active")

    try:
        # A. 파일 대상이고 캐시가 존재하는 경우
        if not is_active and os.path.exists(resolved_target):
            abs_path = os.path.abspath(resolved_target)
            file_name = os.path.basename(abs_path)
            sub_key = f"{slide_arg}_{search_kw}_{fmt}"

            cached_data = get_file_cache(abs_path, sub_key=sub_key)
            if cached_data:
                return format_response(
                    status="ok",
                    module="ppt_read",
                    action="read_cached",
                    preview=cached_data.get("preview", f"Read PPT from cache: {file_name}"),
                    agent_directive="VERIFIED: PowerPoint data retrieved from disk cache.",
                    extra=cached_data
                )

            # 초고속 XML 추출
            extracted = extract_pptx_xml(abs_path)
            items = extracted["items"]
            total_slides = extracted["total_slides"]
            total_chars = len(extracted["full_text"])

            # 특정 슬라이드만 요청된 경우
            if slide_arg is not None:
                s_num = int(slide_arg)
                filtered_items = [it for it in items if it.get("slide") == s_num]
                if not filtered_items:
                    return format_response(
                        status="no_match",
                        module="ppt_read",
                        action="read_slide",
                        preview=f"Slide {s_num} not found (Total slides: {total_slides})",
                        agent_directive="STOP_RETRY: Slide not found."
                    )
                items = filtered_items

            # 키워드 검색
            search_matches = []
            if search_kw:
                for it in items:
                    if search_kw in it["text"]:
                        search_matches.append({
                            "loc": it["loc"],
                            "text": it["text"]
                        })

                if not search_matches:
                    return format_response(
                        status="no_match",
                        module="ppt_read",
                        action="search",
                        preview=f"Keyword '{search_kw}' not found in {file_name}",
                        agent_directive="STOP_RETRY: Keyword not found in presentation."
                    )

            if fmt == "summary":
                preview_msg = f"PPT: {file_name} | 슬라이드 {total_slides}장 | 총 글자: {total_chars}자"
                payload_data = {"total_slides": total_slides, "total_characters": total_chars}
            elif fmt == "items":
                preview_msg = f"PPT: {file_name} ({len(items)} slides, {total_chars} chars)"
                payload_data = items
            else:
                preview_msg = f"PPT: {file_name} ({len(items)} slides, {total_chars} chars)"
                payload_data = extracted["full_text"]

            result_payload = {
                "file": file_name,
                "path": abs_path,
                "file_type": "ppt",
                "total_slides": total_slides,
                "total_characters": total_chars,
                "preview": preview_msg,
                "items": items,
                "data": payload_data,
                "search_matches": search_matches if search_kw else None
            }

            save_file_cache(abs_path, result_payload, sub_key=sub_key)

            return format_response(
                status="ok",
                module="ppt_read",
                action="read_ppt",
                preview=preview_msg,
                agent_directive="VERIFIED: PowerPoint presentation read successfully.",
                extra=result_payload
            )

        # B. 활성 PowerPoint 창 조회 (COM 경유)
        items = []
        notes_list = []
        with ppt_session(target=resolved_target) as (app, prs):
            prs_name = prs.Name
            # 현재 활성 슬라이드 인덱스 저장하여 조회 후 복원
            try:
                original_slide_idx = app.ActiveWindow.View.Slide.SlideIndex
            except Exception:
                original_slide_idx = None
            slide_count = prs.Slides.Count
            for i in range(1, slide_count + 1):
                slide = prs.Slides(i)
                texts = []
                for shape in slide.Shapes:
                    texts.extend(extract_texts_from_shape(shape))

                s_text = "\n\n".join(t for t in texts if t)
                if s_text:
                    items.append({
                        "loc": f"Slide {i}",
                        "slide": i,
                        "text": s_text
                    })

                # 발표자 노트(Speaker Notes) 추출
                if params.get("notes"):
                    try:
                        notes_shape = slide.NotesPage.Shapes.Placeholders.Item(2)
                        if notes_shape.HasTextFrame and notes_shape.TextFrame.HasText:
                            note_text = notes_shape.TextFrame.TextRange.Text.strip()
                            if note_text:
                                notes_list.append({
                                    "slide": i,
                                    "loc": f"Slide {i} (Notes)",
                                    "notes": note_text
                                })
                    except Exception:
                        pass

            full_text = "\n\n".join(f"[{it['loc']}] {it['text']}" for it in items)
            preview_msg = f"PPT (Active): {prs_name} ({len(items)} slides, {len(full_text)} chars)"
            if notes_list:
                preview_msg += f" | Notes: {len(notes_list)} slides"

            # 조회 후 원래 활성 슬라이드로 복원
            try:
                if original_slide_idx is not None:
                    app.ActiveWindow.View.GotoSlide(original_slide_idx)
            except Exception:
                pass

            return format_response(
                status="ok",
                module="ppt_read",
                action="read_ppt_active",
                preview=preview_msg,
                agent_directive="VERIFIED: Active PowerPoint presentation read successfully.",
                extra={
                    "presentation": prs_name,
                    "file_type": "ppt",
                    "total_slides": len(items),
                    "notes": notes_list,
                    "items": items,
                    "data": full_text
                }
            )

    except Exception as e:
        return format_response(
            status="error",
            module="ppt_read",
            action="read",
            preview=str(e),
            agent_directive=f"STOP_RETRY: PowerPoint read failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Read Micro Block (XML/COM Fast Parse & Cache)")
    parser.add_argument("--target", "--file", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--slide", type=int, help="특정 슬라이드 번호 (1-based)")
    parser.add_argument("--search", type=str, help="특정 단어 검색")
    parser.add_argument("--format", choices=["text", "items", "summary"], default="text", help="출력 형식")
    parser.add_argument("--notes", action="store_true", help="슬라이드별 발표자 노트(Speaker Notes) 추출")
    args = parser.parse_args()

    params = {
        "target": args.target,
        "slide": args.slide,
        "search": args.search,
        "format": args.format,
        "notes": args.notes
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: ppt_read.py ===

---

=== FILE: ppt_slide.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _com_guard import ppt_session

# PPT PpSlideLayout 상수 (기본 빈 슬라이드: ppLayoutBlank = 12, 제목+내용: 2)
PPT_LAYOUT_BLANK = 12
PPT_LAYOUT_TITLE_AND_CONTENT = 2

def execute(app, prs, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 PowerPoint 슬라이드 추가/복제/삭제/이동을 수행합니다."""
    action = params.get("action", "add").lower()
    slide_index = params.get("slide") or params.get("index")
    dest_index = params.get("dest")

    try:
        total_slides = prs.Slides.Count

        if action == "add":
            # 새 슬라이드 추가 (기본 맨 뒤에 추가)
            insert_pos = int(slide_index) if slide_index else (total_slides + 1)
            # 빈 슬라이드 레이아웃 사용 (ppLayoutBlank = 12)
            try:
                layout = prs.SlideMaster.CustomLayouts(7)  # 기본 빈 레이아웃
                new_slide = prs.Slides.AddSlide(insert_pos, layout)
            except Exception:
                new_slide = prs.Slides.Add(insert_pos, PPT_LAYOUT_BLANK)

            return format_response(
                status="ok",
                module="ppt_slide",
                action="add",
                preview=f"Added new blank slide at position {new_slide.SlideIndex} (Total: {prs.Slides.Count})",
                agent_directive="VERIFIED: Slide added successfully.",
                extra={"slide_index": new_slide.SlideIndex, "total_slides": prs.Slides.Count}
            )

        elif action == "duplicate":
            if not slide_index:
                raise ValueError("복제할 대상 슬라이드 번호(slide)가 필요합니다.")
            src_idx = int(slide_index)
            if src_idx < 1 or src_idx > total_slides:
                raise IndexError(f"슬라이드 번호 범위를 벗어났습니다: {src_idx} (총 {total_slides}장)")
            
            dup_range = prs.Slides(src_idx).Duplicate()
            try:
                dup_idx = dup_range.Item(1).SlideIndex
            except Exception:
                try:
                    dup_idx = dup_range.SlideIndex
                except Exception:
                    dup_idx = src_idx + 1

            return format_response(
                status="ok",
                module="ppt_slide",
                action="duplicate",
                preview=f"Duplicated slide {src_idx} to position {dup_idx} (Total: {prs.Slides.Count})",
                agent_directive="VERIFIED: Slide duplicated successfully.",
                extra={"slide_index": dup_idx, "total_slides": prs.Slides.Count}
            )

        elif action == "delete":
            if not slide_index:
                raise ValueError("삭제할 대상 슬라이드 번호(slide)가 필요합니다.")
            del_idx = int(slide_index)
            if del_idx < 1 or del_idx > total_slides:
                raise IndexError(f"슬라이드 번호 범위를 벗어났습니다: {del_idx}")
            if total_slides <= 1:
                raise ValueError("프레젠테이션에 슬라이드가 1개뿐이어서 삭제할 수 없습니다.")
            
            prs.Slides(del_idx).Delete()
            return format_response(
                status="ok",
                module="ppt_slide",
                action="delete",
                preview=f"Deleted slide {del_idx} (Remaining: {prs.Slides.Count})",
                agent_directive="VERIFIED: Slide deleted.",
                extra={"remaining_slides": prs.Slides.Count}
            )

        elif action == "move":
            if not slide_index or not dest_index:
                raise ValueError("'slide'(출발 번호)와 'dest'(목적 번호) 파라미터가 필요합니다.")
            prs.Slides(int(slide_index)).MoveTo(int(dest_index))
            return format_response(
                status="ok",
                module="ppt_slide",
                action="move",
                preview=f"Moved slide {slide_index} to position {dest_index}",
                agent_directive="VERIFIED: Slide moved."
            )

        elif action in ["count", "list"]:
            return format_response(
                status="ok",
                module="ppt_slide",
                action="count",
                preview=f"Total slides: {total_slides}",
                agent_directive="VERIFIED: Slide count retrieved.",
                extra={"total_slides": total_slides}
            )

        elif action in ["clear", "clean"]:
            cleared_shapes = 0
            if slide_index:
                s_idx = int(slide_index)
                target_slide = prs.Slides(s_idx)
                for i in range(target_slide.Shapes.Count, 0, -1):
                    target_slide.Shapes.Item(i).Delete()
                    cleared_shapes += 1
                msg = f"슬라이드 {s_idx}의 모든 요소({cleared_shapes}개)를 삭제했습니다."
            elif params.get("all_slides") is True:
                for s in range(1, prs.Slides.Count + 1):
                    target_slide = prs.Slides(s)
                    for i in range(target_slide.Shapes.Count, 0, -1):
                        target_slide.Shapes.Item(i).Delete()
                        cleared_shapes += 1
                msg = f"모든 슬라이드의 요소({cleared_shapes}개)를 전체 삭제했습니다."
            else:
                # 슬라이드 번호 없이 호출하면 전체 슬라이드가 지워지는 사고를 막기 위해 명시적 --all-slides 요구
                return format_response(
                    status="error",
                    module="ppt_slide",
                    action="clear",
                    preview="clear 작업에는 --slide 번호가 필요합니다. 전체 슬라이드를 비우려면 --all-slides를 명시하세요.",
                    agent_directive="STOP_RETRY: 지울 슬라이드 번호를 사용자에게 확인하세요. 전체 삭제는 사용자가 명시적으로 요청한 경우에만 all_slides=true로 호출합니다."
                )

            return format_response(
                status="ok",
                module="ppt_slide",
                action="clear",
                preview=msg,
                agent_directive="VERIFIED: Slide content cleared. Do not re-verify.",
                extra={"cleared_shapes": cleared_shapes}
            )

        else:
            raise ValueError(f"알 수 없는 슬라이드 액션입니다: {action}")

    except Exception as e:
        return format_response(
            status="error",
            module="ppt_slide",
            action=action,
            preview=str(e),
            agent_directive=f"STOP_RETRY: Slide action failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Slide Management Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--action", default="add", choices=["add", "duplicate", "delete", "move", "count", "list", "clear"])
    parser.add_argument("--slide", type=int, help="대상 슬라이드 번호 (1-based)")
    parser.add_argument("--dest", type=int, help="이동할 목적 위치 번호 (1-based)")
    parser.add_argument("--all-slides", action="store_true", help="clear 시 모든 슬라이드의 요소를 삭제 (명시적 지정 필요)")
    args = parser.parse_args()

    params = {
        "action": args.action,
        "slide": args.slide,
        "dest": args.dest,
        "all_slides": args.all_slides
    }

    try:
        with ppt_session(target=args.target, snapshot=True) as (app, prs):
            res = execute(app, prs, params)
    except Exception as e:
        res = format_response("error", "ppt_slide", args.action, preview=f"PowerPoint 세션 오류: {e}",
                              agent_directive="STOP_RETRY: PowerPoint 프레젠테이션에 연결하지 못했습니다. 사용자에게 보고하세요.")
    emit_response(res)
    sys.exit(0 if res.get("status") == "ok" else 1)

if __name__ == "__main__":
    main()
```

=== END FILE: ppt_slide.py ===

---

=== FILE: ppt_write.py ===

```python
import sys
import os
import re
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, read_csv_table, parse_color_to_bgr
from _com_guard import ppt_session
from office_theme import resolve_theme

MSO_SHAPE_RECTANGLE = 1
MSO_SHAPE_ROUNDED_RECTANGLE = 5

def parse_markdown_table(md_text: str) -> List[List[str]]:
    """마크다운 형식의 표 텍스트를 2차원 리스트로 파싱합니다."""
    lines = [line.strip() for line in md_text.strip().split("\n") if line.strip()]
    table = []
    for line in lines:
        if re.match(r"^\|?[\s\-:|]+\|?$", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        table.append(cells)
    return table

def parse_cards_data(raw_cards: str) -> List[Dict[str, str]]:
    """'제목1:설명1|제목2:설명2|제목3:설명3' 형태의 문자열을 카드 리스트로 파싱합니다."""
    cards = []
    items = raw_cards.strip().split("|")
    for item in items:
        if ":" in item:
            title, desc = item.split(":", 1)
            cards.append({"title": title.strip(), "desc": desc.strip()})
        else:
            cards.append({"title": item.strip(), "desc": ""})
    return cards

def execute(app, prs, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 PowerPoint 슬라이드에 텍스트, 표, 이미지 및 비주얼 카드를 주입합니다."""
    slide_idx = int(params.get("slide") or prs.Slides.Count)
    title_text = params.get("title", "")
    body_text = params.get("text") or params.get("body", "")
    table_data = params.get("table_data")
    data_file = params.get("data_file")
    image_path = params.get("image")
    component = (params.get("component") or "").lower()
    cards_input = params.get("cards")
    theme_arg = params.get("theme")

    left = float(params.get("left") if params.get("left") is not None else 50)
    width = float(params.get("width") if params.get("width") is not None else 620)

    user_top = params.get("top")
    user_height = params.get("height")

    if user_height is not None:
        height = float(user_height)
    else:
        height = 160.0 if component == "cards" else (180.0 if component == "table" else 250.0)

    try:
        if prs.Slides.Count == 0:
            prs.Slides.Add(1, 12)  # 빈 슬라이드 추가

        if slide_idx < 1 or slide_idx > prs.Slides.Count:
            slide_idx = prs.Slides.Count

        slide = prs.Slides(slide_idx)

        # Smart Stacking: top이 지정되지 않은 경우 슬라이드 내 기존 요소 아래 20pt로 자동 누적
        if user_top is not None:
            top = float(user_top)
        else:
            max_bottom = 90.0
            try:
                for sh in slide.Shapes:
                    try:
                        s_bottom = sh.Top + sh.Height
                        if s_bottom > max_bottom and s_bottom < 500:
                            max_bottom = s_bottom
                    except Exception:
                        pass
            except Exception:
                pass
            top = max_bottom + 20.0
            log_debug(f"[Smart Stacking] 좌표 자동 산출 완료: Top={top}pt, Height={height}pt")

        created_elements = []

        # 테마 파싱
        theme = resolve_theme(theme_arg) if theme_arg else resolve_theme("navy")
        primary_color_bgr = parse_color_to_bgr(theme.get("primary", "#1B365D"))
        secondary_color_bgr = parse_color_to_bgr(theme.get("secondary", "#4A777A"))

        # 1. 제목 텍스트 상자 추가
        if title_text:
            title_shape = slide.Shapes.AddTextbox(1, 50, 30, 620, 50)
            tf = title_shape.TextFrame
            tf.TextRange.Text = title_text
            tf.TextRange.Font.Size = 24
            tf.TextRange.Font.Bold = True
            if primary_color_bgr is not None:
                tf.TextRange.Font.Color.RGB = primary_color_bgr
            created_elements.append(f"Title('{title_text[:20]}')")

        # 2. 이미지 삽입 (--image)
        if image_path:
            abs_img = os.path.abspath(image_path)
            if not os.path.exists(abs_img):
                return format_response(
                    status="no_match",
                    module="ppt_write",
                    action="insert_image",
                    preview=f"Image file not found: {abs_img}",
                    agent_directive="STOP_RETRY: Image path does not exist."
                )
            # 가로/세로 -1 지정 시 원본 비율 유지
            img_w = width if width != 620 else -1
            img_h = height if height != 320 else -1
            img_shape = slide.Shapes.AddPicture(
                FileName=abs_img,
                LinkToFile=False,
                SaveWithDocument=True,
                Left=left,
                Top=top,
                Width=img_w,
                Height=img_h
            )
            created_elements.append(f"Image('{os.path.basename(abs_img)}')")

        # 3. 비주얼 카드 레이아웃 생성 (--component cards)
        if component in ["cards", "card", "kpi"] and (cards_input or body_text):
            raw_c = cards_input or body_text
            cards = parse_cards_data(raw_c)
            card_count = len(cards)
            if card_count > 0:
                spacing = 15
                total_w = width
                card_w = (total_w - (spacing * (card_count - 1))) / card_count
                card_h = height if height != 320 else 200

                for idx, c_info in enumerate(cards):
                    c_left = left + (idx * (card_w + spacing))
                    card_shape = slide.Shapes.AddShape(MSO_SHAPE_ROUNDED_RECTANGLE, c_left, top, card_w, card_h)
                    
                    # 카드 배경색 (은은한 회색/하늘색)
                    card_shape.Fill.Visible = True
                    card_shape.Fill.ForeColor.RGB = 0xFAFAF8  # #F8FAFA
                    card_shape.Line.Visible = True
                    card_shape.Line.ForeColor.RGB = primary_color_bgr if primary_color_bgr else 0xD0D7DE
                    card_shape.Line.Weight = 1.5

                    # 텍스트 삽입 (제목 16pt Bold + 설명 12pt)
                    tf = card_shape.TextFrame
                    tf.MarginLeft = 12
                    tf.MarginRight = 12
                    tf.MarginTop = 15
                    tf.MarginBottom = 15
                    
                    full_text = f"{c_info['title']}\n\n{c_info['desc']}" if c_info['desc'] else c_info['title']
                    tf.TextRange.Text = full_text
                    
                    # 1행(제목) 볼드 및 테마 색상 부여
                    if len(tf.TextRange.Paragraphs()) >= 1:
                        p1 = tf.TextRange.Paragraphs(1)
                        p1.Font.Bold = True
                        p1.Font.Size = 16
                        if primary_color_bgr is not None:
                            p1.Font.Color.RGB = primary_color_bgr

                created_elements.append(f"Cards({card_count} boxes)")

        # 4. 표 데이터 주입 (CSV 또는 마크다운)
        matrix = None
        if data_file and os.path.exists(data_file):
            matrix = read_csv_table(data_file)
        elif table_data:
            if isinstance(table_data, str):
                matrix = parse_markdown_table(table_data)
            elif isinstance(table_data, list):
                matrix = table_data
        elif "|" in body_text and "\n" in body_text and component not in ["cards", "card"]:
            matrix = parse_markdown_table(body_text)

        if matrix:
            if len(matrix) > 75:
                log_debug(f"PowerPoint 표 행 제한: {len(matrix)}행 -> 75행으로 자름")
                matrix = matrix[:75]
            num_rows = len(matrix)
            num_cols = max(len(r) for r in matrix) if num_rows > 0 else 0
            
            table_shape = slide.Shapes.AddTable(num_rows, num_cols, left, top, width, height)
            tbl = table_shape.Table

            for r_idx, row in enumerate(matrix):
                for c_idx, val in enumerate(row):
                    try:
                        cell = tbl.Cell(r_idx + 1, c_idx + 1)
                        cell.Shape.TextFrame.TextRange.Text = str(val)
                        if r_idx == 0:
                            cell.Shape.TextFrame.TextRange.Font.Bold = True
                            cell.Shape.TextFrame.TextRange.Font.Size = 13
                            if primary_color_bgr is not None:
                                cell.Shape.Fill.ForeColor.RGB = primary_color_bgr
                                cell.Shape.TextFrame.TextRange.Font.Color.RGB = 0xFFFFFF
                        else:
                            cell.Shape.TextFrame.TextRange.Font.Size = 11
                    except Exception:
                        pass
            created_elements.append(f"Table({num_rows}x{num_cols})")

        # 5. 일반 본문 텍스트 상자 (위 요소들이 없을 경우)
        if body_text and not matrix and component not in ["cards", "card"]:
            body_shape = slide.Shapes.AddTextbox(1, left, top, width, height)
            tf = body_shape.TextFrame
            tf.WordWrap = True
            tf.TextRange.Text = body_text
            tf.TextRange.Font.Size = 14
            created_elements.append(f"Text({len(body_text)} chars)")

        if not created_elements:
            return format_response(
                status="no_match",
                module="ppt_write",
                action="write",
                preview="No content provided (title, body, table, image, or cards required)",
                agent_directive="STOP_RETRY: Missing content parameters."
            )

        preview_str = f"Slide {slide_idx}: Added " + ", ".join(created_elements)
        return format_response(
            status="ok",
            module="ppt_write",
            action="write",
            preview=preview_str,
            agent_directive="VERIFIED: Content written to PowerPoint slide. Do not re-verify.",
            extra={"slide": slide_idx, "elements": created_elements}
        )

    except Exception as e:
        return format_response(
            status="error",
            module="ppt_write",
            action="write",
            preview=str(e),
            agent_directive=f"STOP_RETRY: PowerPoint write failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="PowerPoint Advanced Write Micro Block (Cards & Image Support)")
    parser.add_argument("--target", default="active", help="active 또는 pptx 파일 경로")
    parser.add_argument("--slide", type=int, help="대상 슬라이드 번호 (생략 시 마지막 슬라이드)")
    parser.add_argument("--title", type=str, help="슬라이드 제목")
    parser.add_argument("--text", "--body", type=str, help="본문 일반 텍스트 또는 마크다운 표")
    parser.add_argument("--data-file", type=str, help="표로 변환할 CSV 파일 경로")
    parser.add_argument("--image", type=str, help="삽입할 이미지 파일 경로 (PNG, JPG)")
    parser.add_argument("--component", choices=["cards", "table", "text", "title"], help="컴포넌트 유형")
    parser.add_argument("--cards", type=str, help="카드 데이터 ('제목1:설명1|제목2:설명2')")
    parser.add_argument("--theme", type=str, help="테마 프리셋(navy, slate, teal, emerald)")
    parser.add_argument("--left", type=float, default=None, help="왼쪽 여백(pt)")
    parser.add_argument("--top", type=float, default=None, help="위쪽 여백(pt, 생략 시 Smart Stacking 자동 계산)")
    parser.add_argument("--width", type=float, default=None, help="너비(pt)")
    parser.add_argument("--height", type=float, default=None, help="높이(pt, 생략 시 컴포넌트별 자동 최적화)")
    args = parser.parse_args()

    params = {
        "slide": args.slide,
        "title": args.title,
        "text": args.text,
        "data_file": args.data_file,
        "image": args.image,
        "component": args.component,
        "cards": args.cards,
        "theme": args.theme,
        "left": args.left,
        "top": args.top,
        "width": args.width,
        "height": args.height
    }

    with ppt_session(target=args.target, snapshot=True) as (app, prs):
        res = execute(app, prs, params)
        emit_response(res)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)

if __name__ == "__main__":
    main()
```

=== END FILE: ppt_write.py ===

---

=== FILE: search.py ===

```python
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
```

=== END FILE: search.py ===

---

=== FILE: word_edit.py ===

```python
import sys
import os
import json
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import (
    format_response, emit_response, log_debug, parse_color_to_bgr,
    parse_replace_rules, normalize_and_expand_rules
)
from _com_guard import word_session
from _config import resolve_data_path

# Word WdColorIndex 형광펜(Highlight) 매핑
WORD_HIGHLIGHT_MAP = {
    "yellow": 7,     # wdYellow
    "green": 4,      # wdBrightGreen
    "blue": 9,       # wdBlue
    "red": 6,        # wdRed
    "pink": 5,       # wdPink
    "gray": 16,      # wdGray25
    "none": 0        # wdNoHighlight
}

def apply_word_find_and_replace(doc, find_text: str, style_or_replace: Any) -> int:
    """Word 문서 전체에서 특정 텍스트를 검색하여 치환 및 서식을 적용합니다."""
    if not find_text:
        return 0

    replace_text = find_text
    bold = None
    italic = None
    color_bgr = None
    highlight_code = None

    if isinstance(style_or_replace, dict):
        if "text" in style_or_replace:
            replace_text = str(style_or_replace["text"])
        elif "replace" in style_or_replace:
            replace_text = str(style_or_replace["replace"])
        if "bold" in style_or_replace:
            bold = bool(style_or_replace["bold"])
        if "italic" in style_or_replace:
            italic = bool(style_or_replace["italic"])
        if "color" in style_or_replace:
            color_bgr = parse_color_to_bgr(style_or_replace["color"])
        if "bg" in style_or_replace or "highlight" in style_or_replace:
            hl = str(style_or_replace.get("bg") or style_or_replace.get("highlight")).lower()
            highlight_code = WORD_HIGHLIGHT_MAP.get(hl, 7)
    elif isinstance(style_or_replace, str):
        replace_text = style_or_replace

    matched_count = 0
    rng = doc.Content
    find_obj = rng.Find
    find_obj.ClearFormatting()
    find_obj.Forward = True
    find_obj.Wrap = 0  # wdFindStop (0): 문서 끝 도달 시 순환 검색 원천 차단

    max_loops = 5000
    loop_count = 0
    last_end = -1

    # 반복 검색하며 개별 매칭 범위에 치환 및 서식 적용
    while find_obj.Execute(FindText=find_text):
        loop_count += 1
        if loop_count > max_loops:
            log_debug(f"Word 검색 치환 최대 루프 한도({max_loops}) 초과로 안전 중단: '{find_text}'")
            break

        # 순환 검색(wrap-around) 또는 이전 위치 역행 방어
        if rng.Start < last_end:
            break

        matched_count += 1
        if replace_text != find_text:
            rng.Text = replace_text
        if bold is not None:
            rng.Bold = bold
        if italic is not None:
            rng.Italic = italic
        if color_bgr is not None:
            rng.Font.Color = color_bgr
        if highlight_code is not None:
            rng.HighlightColorIndex = highlight_code
        
        last_end = rng.End
        # 다음 검색을 위해 포인터를 치환 완료된 텍스트 뒤로 이동
        rng.Collapse(0)  # wdCollapseEnd

    return matched_count

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 Word 다중 치환, 서식 적용 및 내용 초기화(clear)를 수행합니다."""
    action = str(params.get("action") or "replace").lower()
    if action in ["clear", "delete_all"]:
        try:
            doc.Content.Delete()
            return format_response(
                status="ok",
                module="word_edit",
                action="clear",
                preview="Word 문서 내용이 전체 초기화(삭제)되었습니다.",
                agent_directive="VERIFIED: Word document cleared. Do not re-verify."
            )
        except Exception as e:
            return format_response(
                status="error",
                module="word_edit",
                action="clear",
                preview=f"Word 문서 내용 지우기 실패: {e}",
                agent_directive=f"STOP_RETRY: Failed to clear Word content: {e}"
            )

    mapping_file = params.get("mapping_file") or params.get("replace_map")
    find_kw = params.get("find")
    replace_to = params.get("replace")
    style_spec = params.get("style", {})

    rules = {}
    if mapping_file:
        rules = parse_replace_rules(mapping_file, resolve_path_fn=resolve_data_path)
    elif find_kw:
        single_rule = dict(style_spec)
        if replace_to:
            single_rule["text"] = replace_to
        rules = {find_kw: single_rule}

    # ' | ' 등 가상 결합 구분자로 묶인 항목 자동 분해 및 확장
    rules = normalize_and_expand_rules(rules)

    if not rules:
        return format_response(
            status="no_match",
            module="word_edit",
            action="apply_edit",
            preview="No replacement or edit rules provided",
            agent_directive="STOP_RETRY: Empty edit rules."
        )

    total_applied = 0
    for target_word, rule in rules.items():
        cnt = apply_word_find_and_replace(doc, str(target_word), rule)
        total_applied += cnt
        log_debug(f"Word 단어 치환/서식 적용: '{target_word}' -> {cnt}건")

    if total_applied == 0:
        return format_response(
            status="no_match",
            module="word_edit",
            action="apply_edit",
            preview="0 matches found for edit rules",
            agent_directive="STOP_RETRY: Target words not found in document. Proceed."
        )

    return format_response(
        status="ok",
        module="word_edit",
        action="apply_edit",
        preview=f"{total_applied} replacements/styles successfully applied",
        agent_directive="VERIFIED: Word edits applied. Do not re-verify.",
        extra={"applied_count": total_applied}
    )

def main():
    parser = argparse.ArgumentParser(description="Word Edit & Style Micro Block")
    parser.add_argument("--action", default="replace", choices=["replace", "clear"], help="수행할 작업 (replace=치환/서식, clear=문서 전체 비우기)")
    parser.add_argument("--target", default="active", help="active 또는 docx 파일 경로")
    parser.add_argument("--replace-map", type=str, help="styles.json 또는 edit_rules.json 경로")
    parser.add_argument("--find", type=str, help="검색 단어")
    parser.add_argument("--replace", type=str, help="치환할 단어")
    parser.add_argument("--bold", action="store_true", help="굵게")
    parser.add_argument("--color", type=str, help="글자색")
    parser.add_argument("--highlight", type=str, help="형광펜 색상 (yellow, green, pink 등)")
    args = parser.parse_args()

    style = {}
    if args.bold: style["bold"] = True
    if args.color: style["color"] = args.color
    if args.highlight: style["highlight"] = args.highlight

    params = {
        "action": args.action,
        "mapping_file": args.replace_map,
        "find": args.find,
        "replace": args.replace,
        "style": style
    }

    with word_session(target=args.target, snapshot=True) as (app, doc):
        res = execute(app, doc, params)
        emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: word_edit.py ===

---

=== FILE: word_export.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_data_dir
from _com_guard import word_session

# Word WdSaveFormat 상수
WD_FORMAT_PDF = 17
WD_FORMAT_DOCX = 16

def resolve_output_path(file_path: str, default_ext: str = ".pdf") -> str:
    """출력 경로를 해석하며 파일명만 기입된 경우 data_dir 하위로 매핑합니다."""
    if not file_path:
        raise ValueError("출력 파일명(output_file)이 필요합니다.")
    if not os.path.splitext(file_path)[1]:
        file_path += default_ext
    if os.path.isabs(file_path):
        out_path = file_path
    else:
        out_path = os.path.join(get_data_dir(), file_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    return os.path.abspath(out_path)

def _is_pdf_feature_missing(err: Exception) -> bool:
    """PDF 내보내기 추가 기능 미설치 오류인지 판별합니다.
    -2147467259(E_FAIL)는 대상 파일 잠금 등 일반 실패에도 쓰이므로 판별 근거로 사용하지 않습니다.
    """
    raw = repr(err) + " " + str(err)
    return "기능이 설치되어 있지 않아" in raw or "25726" in raw

def _open_working_copy(app, doc):
    """원본 문서를 건드리지 않도록 현재 메모리 상태(미저장 변경 포함)를 창 없는 사본 문서로 엽니다."""
    import tempfile
    fd, tmp_xml = tempfile.mkstemp(prefix="atomic_word_copy_", suffix=".xml")
    os.close(fd)
    with open(tmp_xml, "w", encoding="utf-8") as f:
        f.write(doc.WordOpenXML)
    work = app.Documents.Open(tmp_xml, ConfirmConversions=False, AddToRecentFiles=False, Visible=False)
    return work, tmp_xml

def _export_pdf(target_doc, out_path: str) -> None:
    try:
        target_doc.ExportAsFixedFormat(
            OutputFileName=out_path,
            ExportFormat=17,   # wdExportFormatPDF
            OpenAfterExport=False,
            OptimizeFor=0,     # wdExportOptimizeForPrint
            Range=0            # wdExportAllDocument
        )
        log_debug("ExportAsFixedFormat으로 PDF 저장 성공")
    except Exception as e_fixed:
        log_debug(f"ExportAsFixedFormat 실패: {e_fixed}")
        if _is_pdf_feature_missing(e_fixed):
            raise RuntimeError("Word PDF 내보내기 기능이 설치되어 있지 않습니다. --format docx 형식을 사용하세요.")
        raise

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """Word 문서를 PDF 또는 복제본 DOCX로 내보냅니다. 원본 문서(경로, 내용, 저장 상태)는 변경하지 않습니다."""
    out_arg = params.get("output_file") or params.get("output")
    fmt = (params.get("format") or "").lower()
    page_number = bool(params.get("page_number", False))

    if not out_arg:
        return format_response(
            status="error",
            module="word_export",
            action="export",
            preview="output_file parameter is required",
            agent_directive="STOP_RETRY: Missing output file path."
        )

    work_doc = None
    tmp_xml = None
    page_number_applied = False
    try:
        out_ext = os.path.splitext(out_arg)[1].lower()
        if fmt:
            out_format = fmt
        elif out_ext in [".pdf", ".docx"]:
            out_format = out_ext[1:]
        else:
            out_format = "pdf"
        if out_format not in ("pdf", "docx"):
            raise ValueError(f"지원하지 않는 Word 내보내기 형식입니다: {out_format} (pdf 또는 docx 지원)")

        # 형식과 확장자 불일치 방지 (예: --format pdf -o report.docx -> report.pdf)
        if out_ext and out_ext != f".{out_format}":
            out_arg = os.path.splitext(out_arg)[0] + f".{out_format}"
        final_out_path = resolve_output_path(out_arg, default_ext=f".{out_format}")
        log_debug(f"Word Export 대상: '{doc.Name}', 포맷='{out_format}', 경로='{final_out_path}'")

        # 페이지 번호 삽입이나 DOCX 사본 저장은 원본이 아닌 창 없는 사본에서 수행
        if page_number or out_format == "docx":
            work_doc, tmp_xml = _open_working_copy(app, doc)
            target_doc = work_doc
        else:
            target_doc = doc

        if page_number:
            for section in target_doc.Sections:
                footer = section.Footers(1)  # wdHeaderFooterPrimary = 1
                footer.PageNumbers.Add(PageNumberAlignment=1)  # wdAlignPageNumberCenter = 1
            page_number_applied = True
            log_debug("사본 문서에 페이지 번호(하단 중앙) 주입 완료")

        if out_format == "pdf":
            _export_pdf(target_doc, final_out_path)
            preview_msg = f"Exported Word document to PDF: {os.path.basename(final_out_path)}"
        else:
            target_doc.SaveAs2(final_out_path, FileFormat=WD_FORMAT_DOCX)
            preview_msg = f"Exported Word copy to DOCX: {os.path.basename(final_out_path)}"

        return format_response(
            status="ok",
            module="word_export",
            action=f"export_{out_format}",
            preview=preview_msg,
            agent_directive="VERIFIED: Document exported successfully. Original document left unchanged.",
            extra={
                "file_path": final_out_path,
                "format": out_format,
                "page_number": page_number_applied
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="word_export",
            action="export",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Word export failed: {e}"
        )
    finally:
        if work_doc is not None:
            try:
                work_doc.Close(SaveChanges=0)
            except Exception:
                pass
        if tmp_xml and os.path.exists(tmp_xml):
            try:
                os.remove(tmp_xml)
            except Exception:
                pass

def main():
    parser = argparse.ArgumentParser(description="Word Export Micro Block with Page Numbering")
    parser.add_argument("--target", default="active", help="active 또는 docx 파일 경로")
    parser.add_argument("--output", "-o", required=True, help="저장할 파일명 (.pdf 또는 .docx)")
    parser.add_argument("--format", choices=["pdf", "docx"], help="출력 포맷 강제 지정")
    parser.add_argument("--page-number", action="store_true", help="하단 중앙 페이지 번호(- 1 -) 추가")
    args = parser.parse_args()

    params = {
        "output": args.output,
        "format": args.format,
        "page_number": args.page_number
    }

    try:
        with word_session(target=args.target, snapshot=False) as (app, doc):
            res = execute(app, doc, params)
    except Exception as e:
        res = format_response("error", "word_export", "export", preview=f"Word 세션 오류: {e}",
                              agent_directive="STOP_RETRY: Word 문서에 연결하지 못했습니다. 사용자에게 보고하세요.")
    emit_response(res)
    sys.exit(0 if res.get("status") == "ok" else 1)

if __name__ == "__main__":
    main()
```

=== END FILE: word_export.py ===

---

=== FILE: word_inspect.py ===

```python
import sys
import os
import argparse
from typing import Dict, Any, List

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, run_session_tool
from _com_guard import word_session

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 Word 문서 상태를 초고속 진단합니다."""
    try:
        doc_name = doc.Name
        para_count = doc.Paragraphs.Count
        char_count = doc.Characters.Count
        words_count = doc.Words.Count
        table_count = doc.Tables.Count
        
        # 이미지 및 도형 수
        image_count = 0
        try:
            image_count = doc.InlineShapes.Count + doc.Shapes.Count
        except Exception:
            pass

        # 표별 요약 정보
        tables_summary = []
        for i in range(1, min(table_count + 1, 10)):  # 최대 상위 10개 표 요약
            try:
                t = doc.Tables(i)
                tables_summary.append({
                    "table_index": i,
                    "rows": t.Rows.Count,
                    "cols": t.Columns.Count
                })
            except Exception:
                pass

        # 상위 3개 단락 미리보기
        preview_paras = []
        for i in range(1, min(para_count + 1, 4)):
            try:
                p_text = doc.Paragraphs(i).Range.Text.strip()
                if p_text:
                    preview_paras.append(p_text[:60])
            except Exception:
                pass

        # 열려 있는 전체 Word 문서 목록 조회
        open_docs = []
        try:
            from _com_guard import get_all_running_word_documents
            all_running = get_all_running_word_documents()
            for item in all_running:
                open_docs.append({
                    "name": item["name"],
                    "path": item["path"],
                    "saved": item.get("saved", True),
                    "active": (item["name"] == doc_name)
                })
        except Exception:
            pass
        if not open_docs:
            open_docs = [{"name": doc_name, "path": getattr(doc, "FullName", ""), "active": True}]

        # 현재 커서 위치(일반 텍스트 문맥 또는 표 내부 위치) 및 선택 정보 추출
        cursor_info = {}
        try:
            sel = app.Selection
            if sel is not None:
                page_num = sel.Information(3) # wdActiveEndPageNumber
                line_num = sel.Information(10) # wdFirstCharacterLineNumber
                is_in_table = bool(sel.Information(12)) # wdWithInTable
                sel_text = sel.Text.strip() if sel.Text else ""

                curr_para_text = ""
                try:
                    curr_para_text = sel.Paragraphs(1).Range.Text.strip()[:100]
                except Exception:
                    pass

                table_loc = None
                if is_in_table:
                    try:
                        row_idx = sel.Information(13) # wdStartOfRangeRowNumber
                        col_idx = sel.Information(14) # wdStartOfRangeColumnNumber
                        cell_text = ""
                        try:
                            cell_text = sel.Cells(1).Range.Text.strip().replace("\r\x07", "").replace("\x07", "")
                        except Exception:
                            pass
                        table_loc = {
                            "row": row_idx,
                            "col": col_idx,
                            "cell_text": cell_text
                        }
                    except Exception:
                        pass

                cursor_info = {
                    "page": page_num,
                    "line": line_num,
                    "in_table": is_in_table,
                    "table_location": table_loc,
                    "selected_text": sel_text,
                    "context_paragraph": curr_para_text
                }
        except Exception as e:
            log_debug(f"Word cursor info error: {e}")

        open_doc_names = [d["name"] for d in open_docs]
        cursor_desc = f"표 {cursor_info['table_location']['row']}행{cursor_info['table_location']['col']}열" if (cursor_info.get("in_table") and cursor_info.get("table_location")) else f"본문 p.{cursor_info.get('page', 1)} L.{cursor_info.get('line', 1)}"
        summary_preview = (
            f"열린 문서: {len(open_docs)}개 ({', '.join(open_doc_names)}) | 활성: {doc_name} (커서: {cursor_desc}) | "
            f"단락: {para_count}개 | 글자: {char_count}자 | 표: {table_count}개 | 이미지: {image_count}개"
        )

        return format_response(
            status="ok",
            module="word_inspect",
            action="inspect_document",
            preview=summary_preview,
            agent_directive="VERIFIED: Word document inspection complete.",
            extra={
                "document": doc_name,
                "open_documents": open_docs,
                "total_open_documents": len(open_docs),
                "cursor": cursor_info,
                "paragraphs_count": para_count,
                "characters_count": char_count,
                "words_count": words_count,
                "tables_count": table_count,
                "images_count": image_count,
                "tables_summary": tables_summary,
                "preview_paragraphs": preview_paras
            }
        )

    except Exception as e:
        return format_response(
            status="error",
            module="word_inspect",
            action="inspect",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Word inspection failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Word Inspection Micro Block")
    parser.add_argument("--target", default="active", help="active 또는 docx 파일 경로")
    parser.add_argument("--list-docs", "--all", dest="list_docs", action="store_true", help="실행 중인 모든 Word 문서 목록만 고속 조회")
    args = parser.parse_args()

    if args.list_docs:
        from _com_guard import get_all_running_word_documents
        all_running = get_all_running_word_documents()
        docs_summary = []
        for item in all_running:
            docs_summary.append({
                "name": item["name"],
                "path": item["path"],
                "saved": item.get("saved", True),
                "active": item.get("is_active", False)
            })

        names_preview = ", ".join([f"{d['name']}{' (Active)' if d['active'] else ''}" for d in docs_summary])
        res = format_response(
            status="ok",
            module="word_inspect",
            action="list_documents",
            preview=f"총 {len(docs_summary)}개의 열린 Word 문서 감지: [{names_preview}]",
            agent_directive="VERIFIED: Running documents enumerated across Word instances.",
            extra={
                "total_count": len(docs_summary),
                "documents": docs_summary
            }
        )
        emit_response(res)
        return

    run_session_tool("word_inspect", "inspect",
                     lambda: word_session(target=args.target),
                     lambda app, doc: execute(app, doc, {}))

if __name__ == "__main__":
    main()
```

=== END FILE: word_inspect.py ===

---

=== FILE: word_read.py ===

```python
import sys
import os
import re
import zipfile
import argparse
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug
from _config import get_data_dir
from _cache import get_file_cache, save_file_cache
from _com_guard import word_session

def resolve_target_file(target: str) -> str:
    if not target or target.strip().lower() == "active":
        return "active"
    if os.path.isabs(target) and os.path.exists(target):
        return target
    data_candidate = os.path.join(get_data_dir(), target)
    if os.path.exists(data_candidate):
        return os.path.abspath(data_candidate)
    cwd_candidate = os.path.abspath(target)
    if os.path.exists(cwd_candidate):
        return cwd_candidate
    return target

def is_heading_candidate(p_text: str, p_style: str = "") -> bool:
    """단락이 제목/소제목(Heading)인지 스타일 및 문맥 패턴으로 판별합니다."""
    if not p_text or len(p_text) > 80:
        return False

    style_lower = (p_style or "").lower()
    if any(h in style_lower for h in ["heading", "title", "제목", "헤딩", "개요"]):
        return True

    text_clean = p_text.strip()
    heading_patterns = [
        r"^\[.+\]$",                   # [소제목]
        r"^【.+】$",                  # 【서식】
        r"^[0-9]+[.\s]+.+",            # 1. 개요, 2. 추진 배경
        r"^[0-9]+-[0-9]+[.\s]+.+",     # 1-1. 세부 사항
        r"^[0-9]+\.[0-9]+[.\s]+.+",    # 1.1 개요
        r"^[IVXLCDM]+[.\s]+.+",        # I. 추진 배경
        r"^[가-힣][.\s)]+.+",          # 가. 추진 일정, 1) 세부 항목
        r"^제\s*[0-9]+\s*장.+",        # 제1장 총칙
    ]
    for pat in heading_patterns:
        if re.match(pat, text_clean):
            return True
    return False

def extract_docx_xml(abs_path: str) -> Dict[str, Any]:
    """Word DOCX 파일의 XML을 파싱하여 페이지 추정, 소제목(Heading) 계층, 표 헤더를 결합한 고도화된 색인 데이터를 생성합니다."""
    items = []
    paragraphs = []
    toc = []
    
    with zipfile.ZipFile(abs_path, 'r') as z:
        xml_content = z.read("word/document.xml")
        root = ET.fromstring(xml_content)
        
        # XML Namespace mapping
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        
        p_idx = 1
        t_idx = 1
        current_page = 1
        cumulative_chars = 0
        current_heading = ""
        CHARS_PER_PAGE_EST = 1200  # 표준 A4 1페이지 평균 조판 글자 수

        for body in root.findall(".//w:body", ns):
            for child in body:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

                # 1. 단락 (Paragraph)
                if tag == "p":
                    has_hard_page_break = False
                    if child.findall(".//w:br[@w:type='page']", ns) or child.findall(".//w:lastRenderedPageBreak", ns):
                        has_hard_page_break = True

                    p_style = ""
                    p_style_elem = child.find(".//w:pPr/w:pStyle", ns)
                    if p_style_elem is not None:
                        p_style = p_style_elem.get(f"{{{ns['w']}}}val") or p_style_elem.get("val") or ""

                    p_text = "".join(node.text or "" for node in child.findall(".//w:t", ns)).strip()
                    if not p_text:
                        if has_hard_page_break:
                            current_page += 1
                            cumulative_chars = 0
                        continue

                    if has_hard_page_break:
                        current_page += 1
                        cumulative_chars = 0
                    else:
                        cumulative_chars += len(p_text)
                        if cumulative_chars >= CHARS_PER_PAGE_EST:
                            current_page += 1
                            cumulative_chars = len(p_text)

                    is_h = is_heading_candidate(p_text, p_style)
                    if is_h:
                        current_heading = p_text
                        toc.append({"title": p_text, "page": current_page, "para": p_idx})
                        loc_label = f"Page {current_page} > [Heading: {p_text}]"
                    else:
                        if current_heading:
                            loc_label = f"Page {current_page} > [{current_heading}] (Para {p_idx})"
                        else:
                            loc_label = f"Page {current_page} (Para {p_idx})"

                    paragraphs.append(p_text)
                    items.append({
                        "loc": loc_label,
                        "page": current_page,
                        "para": p_idx,
                        "heading": current_heading,
                        "is_heading": is_h,
                        "type": "paragraph",
                        "text": p_text
                    })
                    p_idx += 1

                # 2. 표 (Table)
                elif tag == "tbl":
                    rows = child.findall(".//w:tr", ns)
                    headers = []

                    for r_num, row in enumerate(rows, start=1):
                        cells = row.findall(".//w:tc", ns)
                        row_cell_texts = []
                        for c_num, cell in enumerate(cells, start=1):
                            cell_text = "".join(node.text or "" for node in cell.findall(".//w:t", ns)).strip()
                            row_cell_texts.append(cell_text)

                        # 첫 행은 표의 헤더 컬럼명으로 활용
                        if r_num == 1:
                            headers = row_cell_texts
                            for c_num, cell_text in enumerate(row_cell_texts, start=1):
                                if cell_text:
                                    loc_label = f"Page {current_page} > [Table {t_idx} 헤더: {cell_text}]"
                                    items.append({
                                        "loc": loc_label,
                                        "page": current_page,
                                        "table": t_idx,
                                        "row": 1,
                                        "col": c_num,
                                        "heading": current_heading,
                                        "column_name": cell_text,
                                        "type": "table_header",
                                        "text": cell_text
                                    })
                        else:
                            for c_num, cell_text in enumerate(row_cell_texts, start=1):
                                if cell_text:
                                    col_name = headers[c_num - 1] if c_num - 1 < len(headers) and headers[c_num - 1] else f"Col {c_num}"
                                    loc_label = f"Page {current_page} > [Table {t_idx}: {col_name}]"
                                    items.append({
                                        "loc": loc_label,
                                        "page": current_page,
                                        "table": t_idx,
                                        "row": r_num,
                                        "col": c_num,
                                        "heading": current_heading,
                                        "column_name": col_name,
                                        "type": "table_cell",
                                        "text": cell_text
                                    })
                    t_idx += 1

    full_text = "\n".join(p["text"] for p in items)
    return {
        "items": items,
        "paragraphs": paragraphs,
        "toc": toc,
        "total_pages": current_page,
        "total_paragraphs": len(paragraphs),
        "total_items": len(items),
        "full_text": full_text
    }

def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """Word 문서의 텍스트와 강화된 페이지/소제목 위치 메타데이터를 고속 조회(캐시 지원)합니다."""
    target = params.get("target") or params.get("file") or "active"
    search_kw = (params.get("search") or "").strip()
    fmt = (params.get("format") or "text").lower()

    resolved_target = resolve_target_file(target)
    is_active = (resolved_target == "active")

    try:
        # A. 파일 대상이고 캐시가 존재하는 경우
        if not is_active and os.path.exists(resolved_target):
            abs_path = os.path.abspath(resolved_target)
            file_name = os.path.basename(abs_path)
            sub_key = f"{search_kw}_{fmt}"

            cached_data = get_file_cache(abs_path, sub_key=sub_key)
            if cached_data:
                return format_response(
                    status="ok",
                    module="word_read",
                    action="read_cached",
                    preview=cached_data.get("preview", f"Read Word from cache: {file_name}"),
                    agent_directive="VERIFIED: Word data retrieved from disk cache.",
                    extra=cached_data
                )

            # 초고속 XML 추출 및 페이지/소제목 인덱싱
            extracted = extract_docx_xml(abs_path)
            items = extracted["items"]
            total_chars = len(extracted["full_text"])

            search_matches = []
            if search_kw:
                for item in items:
                    if search_kw in item["text"]:
                        search_matches.append({
                            "loc": item["loc"],
                            "page": item.get("page"),
                            "heading": item.get("heading"),
                            "text": item["text"]
                        })

                if not search_matches:
                    return format_response(
                        status="no_match",
                        module="word_read",
                        action="search",
                        preview=f"Keyword '{search_kw}' not found in {file_name}",
                        agent_directive="STOP_RETRY: Keyword not found in Word document."
                    )

            if fmt == "summary":
                preview_msg = f"Word: {file_name} | {extracted['total_pages']}페이지 | 소제목 {len(extracted['toc'])}개 | 총 {total_chars}자"
                payload_data = {
                    "total_pages": extracted["total_pages"],
                    "total_items": len(items),
                    "toc": extracted["toc"],
                    "total_characters": total_chars
                }
            elif fmt == "items":
                preview_msg = f"Word: {file_name} ({extracted['total_pages']} pages, {len(items)} items, {total_chars} chars)"
                payload_data = items
            else:
                preview_msg = f"Word: {file_name} ({extracted['total_pages']} pages, {len(items)} items, {total_chars} chars)"
                payload_data = extracted["full_text"]

            result_payload = {
                "file": file_name,
                "path": abs_path,
                "file_type": "word",
                "total_pages": extracted["total_pages"],
                "total_items": len(items),
                "total_characters": total_chars,
                "toc": extracted["toc"],
                "preview": preview_msg,
                "items": items,
                "data": payload_data,
                "search_matches": search_matches if search_kw else None
            }

            save_file_cache(abs_path, result_payload, sub_key=sub_key)

            return format_response(
                status="ok",
                module="word_read",
                action="read_word",
                preview=preview_msg,
                agent_directive="VERIFIED: Word document read successfully.",
                extra=result_payload
            )

        # B. 활성 Word 창 조회 (COM 경유 - 실제 조판 페이지 wdActiveEndPageNumber 추출)
        items = []
        toc = []
        comments_list = []
        revisions_list = []
        with word_session(target=resolved_target) as (app, doc):
            doc_name = doc.Name
            para_count = doc.Paragraphs.Count
            current_heading = ""
            max_page = 1

            for i in range(1, para_count + 1):
                p_range = doc.Paragraphs(i).Range
                p_text = p_range.Text.strip()
                if not p_text:
                    continue

                try:
                    # Word COM 실제 물리 렌더링 페이지 번호 추출 (wdActiveEndPageNumber = 3)
                    page_num = p_range.Information(3)
                    if page_num > max_page:
                        max_page = page_num
                except Exception:
                    page_num = 1

                p_style = ""
                try:
                    p_style = str(p_range.Style.NameLocal)
                except Exception:
                    pass

                is_h = is_heading_candidate(p_text, p_style)
                if is_h:
                    current_heading = p_text
                    toc.append({"title": p_text, "page": page_num, "para": i})
                    loc_label = f"Page {page_num} > [Heading: {p_text}]"
                else:
                    if current_heading:
                        loc_label = f"Page {page_num} > [{current_heading}] (Para {i})"
                    else:
                        loc_label = f"Page {page_num} (Para {i})"

                items.append({
                    "loc": loc_label,
                    "page": page_num,
                    "para": i,
                    "heading": current_heading,
                    "is_heading": is_h,
                    "type": "paragraph",
                    "text": p_text
                })

            # 검토 메모(Comments) 추출 옵션
            if params.get("comments") and hasattr(doc, "Comments"):
                try:
                    for c_idx in range(1, doc.Comments.Count + 1):
                        c = doc.Comments(c_idx)
                        comments_list.append({
                            "author": getattr(c, "Author", "Unknown"),
                            "date": str(getattr(c, "Date", "")),
                            "scope": getattr(c.Scope, "Text", "").strip(),
                            "text": getattr(c.Range, "Text", "").strip()
                        })
                except Exception as e_c:
                    log_debug(f"Comments extraction error: {e_c}")

            # 변경 내용 추적(Revisions) 추출 옵션
            if params.get("revisions") and hasattr(doc, "Revisions"):
                try:
                    for r_idx in range(1, doc.Revisions.Count + 1):
                        r = doc.Revisions(r_idx)
                        r_type = "insert" if r.Type == 1 else ("delete" if r.Type == 2 else "other")
                        revisions_list.append({
                            "type": r_type,
                            "author": getattr(r, "Author", "Unknown"),
                            "date": str(getattr(r, "Date", "")),
                            "text": getattr(r.Range, "Text", "").strip()
                        })
                except Exception as e_r:
                    log_debug(f"Revisions extraction error: {e_r}")

            full_text = "\n".join(it["text"] for it in items)
            preview_msg = f"Word (Active): {doc_name} ({max_page} pages, {len(items)} paras, {len(full_text)} chars)"
            if comments_list:
                preview_msg += f" | Comments: {len(comments_list)}"
            if revisions_list:
                preview_msg += f" | Revisions: {len(revisions_list)}"

            return format_response(
                status="ok",
                module="word_read",
                action="read_word_active",
                preview=preview_msg,
                agent_directive="VERIFIED: Active Word document read successfully.",
                extra={
                    "document": doc_name,
                    "file_type": "word",
                    "total_pages": max_page,
                    "total_items": len(items),
                    "toc": toc,
                    "comments": comments_list,
                    "revisions": revisions_list,
                    "items": items,
                    "data": full_text
                }
            )

    except Exception as e:
        return format_response(
            status="error",
            module="word_read",
            action="read",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Word read failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Enhanced Word Read Micro Block (Page & Heading Indexing)")
    parser.add_argument("--target", "--file", default="active", help="active 또는 docx 파일 경로")
    parser.add_argument("--search", type=str, help="특정 단어 검색")
    parser.add_argument("--format", choices=["text", "items", "summary"], default="text", help="출력 형식")
    parser.add_argument("--comments", action="store_true", help="Word 문서 내 검토 메모(Comments) 추출")
    parser.add_argument("--revisions", action="store_true", help="Word 문서 내 변경 내용 추적(Track Changes) 내역 추출")
    args = parser.parse_args()

    params = {
        "target": args.target,
        "search": args.search,
        "format": args.format,
        "comments": args.comments,
        "revisions": args.revisions
    }

    res = execute(params)
    emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: word_read.py ===

---

=== FILE: word_write.py ===

```python
import sys
import os
import re
import argparse
from typing import Dict, Any, List, Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from _office_utils import format_response, emit_response, log_debug, read_csv_table, parse_color_to_bgr
from _com_guard import word_session
from office_theme import resolve_theme

def parse_markdown_table(md_text: str) -> List[List[str]]:
    """마크다운 형식의 표 텍스트를 2차원 리스트로 파싱합니다."""
    lines = [line.strip() for line in md_text.strip().split("\n") if line.strip()]
    table = []
    for line in lines:
        if re.match(r"^\|?[\s\-:|]+\|?$", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        table.append(cells)
    return table

def insert_table_into_word(doc, target_range, matrix: List[List[str]], theme_spec: Optional[Dict[str, Any]] = None) -> Any:
    """Word Range 위치에 네이티브 Word 표(Table)를 생성하고 테마 서식(헤더 음영 및 지브라 패턴)을 적용합니다."""
    num_rows = len(matrix)
    num_cols = max(len(r) for r in matrix) if num_rows > 0 else 0
    if num_rows == 0 or num_cols == 0:
        return None

    table = doc.Tables.Add(target_range, num_rows, num_cols)
    table.Borders.Enable = True

    try:
        table.AutoFitBehavior(2)  # wdAutoFitWindow = 2 (문서 여백에 자동 맞춤)
    except Exception:
        pass

    header_bg_bgr = None
    zebra_even_bgr = None
    if theme_spec:
        h_bg = theme_spec.get("header", {}).get("bg") or theme_spec.get("primary", "#1B365D")
        header_bg_bgr = parse_color_to_bgr(h_bg)
        z_bg = theme_spec.get("zebra", {}).get("even", "#F4F7FB")
        zebra_even_bgr = parse_color_to_bgr(z_bg)

    for r_idx, row in enumerate(matrix):
        for c_idx, val in enumerate(row):
            try:
                cell = table.Cell(r_idx + 1, c_idx + 1)
                cell.Range.Text = str(val)
                if r_idx == 0:
                    cell.Range.Bold = True
                    if header_bg_bgr is not None:
                        cell.Range.Shading.BackgroundPatternColor = header_bg_bgr
                        cell.Range.Font.Color = 0xFFFFFF
                    else:
                        cell.Range.Shading.BackgroundPatternColor = 0xF0F0F0
                elif zebra_even_bgr is not None and (r_idx % 2 == 1):
                    cell.Range.Shading.BackgroundPatternColor = zebra_even_bgr
            except Exception:
                pass
    return table

def insert_callout_box(doc, target_range, title: str, text: str, theme_spec: Optional[Dict[str, Any]] = None) -> Any:
    """Word 문서에 좌측 강조선이 들어간 요약 박스(Callout Box)를 1x1 표로 생성합니다."""
    tbl = doc.Tables.Add(target_range, 1, 1)
    cell = tbl.Cell(1, 1)
    
    # 테마 색상 (좌측 강조 라인)
    primary_bgr = parse_color_to_bgr(theme_spec.get("primary", "#1B365D")) if theme_spec else 0x5D361B
    
    # 텍스트 삽입
    full_content = f"■ {title}\n{text}" if title else text
    cell.Range.Text = full_content
    
    # 셀 배경색 (연한 회색/하늘색)
    cell.Range.Shading.BackgroundPatternColor = 0xF8FAF8  # #F8FAF8
    
    # 좌측 테두리만 굵게 (WdBorderType: wdBorderLeft = -2, wdLineWidth300pt = 24)
    tbl.Borders.Enable = False
    try:
        tbl.Borders(-2).LineStyle = 1      # wdLineStyleSingle
        tbl.Borders(-2).LineWidth = 24     # 3.0 pt
        tbl.Borders(-2).Color = primary_bgr
    except Exception:
        pass

    return tbl

def insert_markdown_document(doc, md_text: str, theme_spec: Optional[Dict[str, Any]] = None) -> List[str]:
    """마크다운 서식(제목 #, ##, 불릿 -, *, 본문, 테마 표 |)을 완벽하게 분해하여 Word 서식 요소로 순차 삽입합니다."""
    blocks = []
    curr_type = None
    curr_lines = []

    for line in md_text.strip().splitlines():
        l_strip = line.strip()
        if not l_strip:
            if curr_type and curr_lines:
                blocks.append((curr_type, curr_lines))
                curr_type, curr_lines = None, []
            continue
        
        if l_strip.startswith('#'):
            if curr_type and curr_lines:
                blocks.append((curr_type, curr_lines))
                curr_type, curr_lines = None, []
            blocks.append(('heading', [l_strip]))
        elif l_strip.startswith('|') and '|' in l_strip[1:]:
            if curr_type != 'table':
                if curr_type and curr_lines:
                    blocks.append((curr_type, curr_lines))
                curr_type = 'table'
                curr_lines = [l_strip]
            else:
                curr_lines.append(l_strip)
        elif l_strip.startswith(('- ', '* ')):
            if curr_type != 'bullet':
                if curr_type and curr_lines:
                    blocks.append((curr_type, curr_lines))
                curr_type = 'bullet'
                curr_lines = [l_strip]
            else:
                curr_lines.append(l_strip)
        else:
            if curr_type != 'text':
                if curr_type and curr_lines:
                    blocks.append((curr_type, curr_lines))
                curr_type = 'text'
                curr_lines = [l_strip]
            else:
                curr_lines.append(l_strip)

    if curr_type and curr_lines:
        blocks.append((curr_type, curr_lines))

    primary_bgr = parse_color_to_bgr(theme_spec.get("primary", "#1B365D")) if theme_spec else 0x5D361B
    created = []

    for b_type, b_lines in blocks:
        rng = doc.Range(doc.Content.End - 1, doc.Content.End - 1)
        if b_type == 'heading':
            line = b_lines[0]
            level = len(line) - len(line.lstrip('#'))
            title_text = line.lstrip('#').strip()
            rng.Text = title_text + "\n"
            try:
                rng.Font.Bold = True
                if level == 1:
                    rng.Font.Size = 18
                    rng.Font.Color = primary_bgr
                elif level == 2:
                    rng.Font.Size = 14
                    rng.Font.Color = 0x333333
                else:
                    rng.Font.Size = 12
            except Exception:
                pass
            created.append(f"Heading{level}('{title_text[:15]}')")
        elif b_type == 'table':
            matrix = parse_markdown_table("\n".join(b_lines))
            if matrix:
                insert_table_into_word(doc, rng, matrix, theme_spec)
                rng_after = doc.Range(doc.Content.End - 1, doc.Content.End - 1)
                rng_after.InsertParagraphAfter()
                created.append(f"Table({len(matrix)} rows)")
        elif b_type == 'bullet':
            for b_line in b_lines:
                clean_b = re.sub(r"^[\-\*\+]\s+", "", b_line)
                b_rng = doc.Range(doc.Content.End - 1, doc.Content.End - 1)
                b_rng.Text = clean_b + "\n"
                try:
                    b_rng.Font.Bold = False
                    b_rng.Font.Size = 11
                    b_rng.ListFormat.ApplyBulletDefault()
                except Exception:
                    pass
            created.append(f"Bullets({len(b_lines)} items)")
        elif b_type == 'text':
            rng.Text = "\n".join(b_lines) + "\n"
            try:
                rng.Font.Bold = False
                rng.Font.Size = 11
                rng.Font.Color = 0x000000
            except Exception:
                pass
            created.append(f"Text({len(b_lines)} lines)")

    return created

def execute(app, doc, params: Dict[str, Any]) -> Dict[str, Any]:
    """run.py 또는 CLI에서 Word 본문 쓰기, 앵커 삽입, 이미지 및 Callout 상자를 추가합니다."""
    text_content = params.get("text") or params.get("data") or ""
    anchor = (params.get("anchor") or "").strip()
    pos = (params.get("pos") or "after").lower()
    table_data = params.get("table_data")
    data_file = params.get("data_file")
    image_path = params.get("image")
    component = (params.get("component") or "").lower()
    title = params.get("title", "")
    bullet = params.get("bullet", False)
    theme_arg = params.get("theme")

    theme_spec = resolve_theme(theme_arg) if theme_arg else None

    try:
        is_pure_table = False
        matrix = None  # 표 분기에서만 할당되므로, 일반 텍스트/제목/글머리 경로의 UnboundLocalError 방지
        if data_file and os.path.exists(data_file):
            matrix = read_csv_table(data_file)
            is_pure_table = True
        elif table_data:
            if isinstance(table_data, str):
                matrix = parse_markdown_table(table_data)
            elif isinstance(table_data, list):
                matrix = table_data
            is_pure_table = True
        elif "|" in text_content and "\n" in text_content and component == "table":
            matrix = parse_markdown_table(text_content)
            is_pure_table = True
        elif "|" in text_content and "\n" in text_content and component != "callout":
            non_empty = [l.strip() for l in text_content.strip().splitlines() if l.strip()]
            if all(l.startswith("|") for l in non_empty):
                matrix = parse_markdown_table(text_content)
                is_pure_table = True

        # 삽입 위치 결정 (앵커 또는 문서 끝)
        if anchor:
            find_obj = doc.Content.Find
            find_obj.ClearFormatting()
            find_obj.Forward = True
            find_obj.Wrap = 0  # wdFindStop
            found = find_obj.Execute(FindText=anchor)
            if not found:
                log_debug(f"Anchor '{anchor}' not found. Falling back to document end.")
                target_range = doc.Range(doc.Content.End - 1, doc.Content.End - 1)
                target_range.InsertParagraphAfter()
                target_range = doc.Range(doc.Content.End - 1, doc.Content.End - 1)
            else:
                found_range = find_obj.Parent
                if pos == "replace":
                    target_range = found_range
                elif pos == "before":
                    target_range = doc.Range(found_range.Start, found_range.Start)
                else:
                    target_range = doc.Range(found_range.End, found_range.End)
                    target_range.InsertParagraphAfter()
                    target_range = doc.Range(target_range.End, target_range.End)
        else:
            end_pos = doc.Content.End - 1
            target_range = doc.Range(end_pos, end_pos)

        created_elements = []

        is_markdown_doc = (
            component == "markdown" or
            (component in ["text", ""] and not is_pure_table and not image_path and
             "\n" in text_content and ("#" in text_content or ("|" in text_content and any(l.strip().startswith("#") or l.strip().startswith("-") for l in text_content.strip().splitlines()))))
        )

        # 1. 이미지 삽입 (--image)
        if image_path:
            abs_img = os.path.abspath(image_path)
            if not os.path.exists(abs_img):
                return format_response(
                    status="no_match",
                    module="word_write",
                    action="insert_image",
                    preview=f"Image file not found: {abs_img}",
                    agent_directive="STOP_RETRY: Image path does not exist."
                )
            doc.InlineShapes.AddPicture(
                FileName=abs_img,
                LinkToFile=False,
                SaveWithDocument=True,
                Range=target_range
            )
            created_elements.append(f"Image('{os.path.basename(abs_img)}')")

        # 2. Callout 요약 상자 생성 (--component callout)
        elif component == "callout":
            insert_callout_box(doc, target_range, title, text_content, theme_spec)
            created_elements.append(f"CalloutBox('{title or text_content[:20]}')")

        # 3. 목차(TOC) 생성 (--component toc)
        elif component == "toc":
            try:
                doc.TablesOfContents.Add(
                    Range=target_range,
                    UseHeadingStyles=True,
                    UpperHeadingLevel=1,
                    LowerHeadingLevel=3
                )
                created_elements.append("TableOfContents(1-3 levels)")
            except Exception as te:
                log_debug(f"Word 목차(TOC) 생성 예외: {te}")
                # 일반 텍스트 목차 필드 폴백 삽입
                try:
                    doc.Fields.Add(Range=target_range, Type=13, Text="TOC \\o \"1-3\" \\h \\z \\u") # wdFieldTOC = 13
                    created_elements.append("TableOfContents(Field)")
                except Exception:
                    pass

        # 4. 복합 마크다운 문서 자동 렌더링
        elif is_markdown_doc:
            created_elements = insert_markdown_document(doc, text_content, theme_spec)

        # 5. 표 생성
        elif matrix:
            insert_table_into_word(doc, target_range, matrix, theme_spec)
            created_elements.append(f"Table({len(matrix)} rows)")

        # 5. 제목(Heading/Title) 서식 삽입
        elif component in ["heading", "title"]:
            target_range.Text = text_content + "\n"
            try:
                target_range.Font.Bold = True
                target_range.Font.Size = 14
            except Exception:
                pass
            created_elements.append(f"Heading({len(text_content)} chars)")

        # 6. 일반 텍스트 및 불릿 리스트
        elif text_content:
            target_range.Text = text_content + "\n"
            if bullet:
                try:
                    target_range.ListFormat.ApplyBulletDefault()
                except Exception:
                    pass
            created_elements.append(f"Text({len(text_content)} chars)")

        if not created_elements:
            return format_response(
                status="no_match",
                module="word_write",
                action="write",
                preview="No content provided (text, table, image, or callout required)",
                agent_directive="STOP_RETRY: Missing content."
            )

        preview_str = "Word content added: " + ", ".join(created_elements)
        if anchor:
            preview_str += f" at anchor '{anchor}' ({pos})"

        return format_response(
            status="ok",
            module="word_write",
            action="write",
            preview=preview_str,
            agent_directive="VERIFIED: Content written to Word document. Do not re-verify.",
            extra={"elements": created_elements, "anchor": anchor, "pos": pos}
        )

    except Exception as e:
        return format_response(
            status="error",
            module="word_write",
            action="write",
            preview=str(e),
            agent_directive=f"STOP_RETRY: Word write failed: {e}"
        )

def main():
    parser = argparse.ArgumentParser(description="Word Advanced Write Micro Block (Image & Callout Support)")
    parser.add_argument("--target", default="active", help="active 또는 docx 파일 경로")
    parser.add_argument("--text", "--data", type=str, help="추가할 일반 본문 텍스트 또는 마크다운 표")
    parser.add_argument("--anchor", type=str, help="삽입 기준이 될 기존 단락/키워드")
    parser.add_argument("--pos", choices=["before", "after", "replace", "end"], default="after", help="앵커 기준 삽입 위치")
    parser.add_argument("--data-file", type=str, help="표로 변환할 CSV 파일 경로")
    parser.add_argument("--image", type=str, help="삽입할 이미지 파일 경로 (PNG, JPG)")
    parser.add_argument("--component", choices=["callout", "table", "text", "heading", "title", "toc", "markdown"], default="text", help="컴포넌트 유형 (callout, table, text, heading, title, toc, markdown)")
    parser.add_argument("--title", type=str, help="Callout 상자 제목")
    parser.add_argument("--bullet", action="store_true", help="불릿(글머리 기호) 목록 적용")
    parser.add_argument("--theme", type=str, help="테마 프리셋(navy, slate, teal, emerald)")
    args = parser.parse_args()

    params = {
        "text": args.text,
        "anchor": args.anchor,
        "pos": args.pos,
        "data_file": args.data_file,
        "image": args.image,
        "component": args.component,
        "title": args.title,
        "bullet": args.bullet,
        "theme": args.theme
    }

    with word_session(target=args.target, snapshot=True) as (app, doc):
        res = execute(app, doc, params)
        emit_response(res)

if __name__ == "__main__":
    main()
```

=== END FILE: word_write.py ===

---

