import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(TESTS_DIR))), "CLI", "office-cli")  # 실행 파일
# 저장소 루트 pytest.ini는 --import-mode=importlib를 쓰므로 테스트 폴더(fake_com)와 도구 폴더를 직접 경로에 등록
for p in (ROOT, TESTS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """캐시/데이터 폴더를 테스트별 임시 폴더로 격리합니다."""
    cache = tmp_path / "cache"
    data = tmp_path / "data"
    cache.mkdir()
    data.mkdir()
    monkeypatch.setenv("OFFICE_CLI_CACHE_DIR", str(cache))
    monkeypatch.setenv("OFFICE_CLI_DATA_DIR", str(data))
    return {"cache": cache, "data": data}
