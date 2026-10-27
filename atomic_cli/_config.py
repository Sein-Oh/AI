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
