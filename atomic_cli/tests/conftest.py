import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """캐시/데이터 폴더를 테스트별 임시 폴더로 격리합니다."""
    cache = tmp_path / "cache"
    data = tmp_path / "data"
    cache.mkdir()
    data.mkdir()
    monkeypatch.setenv("ATOMIC_CACHE_DIR", str(cache))
    monkeypatch.setenv("ATOMIC_DATA_DIR", str(data))
    return {"cache": cache, "data": data}
