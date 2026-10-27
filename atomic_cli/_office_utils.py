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
        res.update(extra)
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

