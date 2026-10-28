import json
import os
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
# 루트 pytest.ini가 --import-mode=importlib를 쓰므로 도구 폴더를 직접 경로에 등록.
# 내부 모듈은 _dc_ 접두어라 같은 세션의 office-cli(_runtime 등)와 이름이 겹치지 않음
for p in (ROOT, TESTS_DIR):           # TESTS_DIR: 도우미 dc_tree.py
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """작업 DB 폴더를 테스트별 임시 폴더로 격리합니다."""
    d = tmp_path / "jobs"
    d.mkdir()
    monkeypatch.setenv("DOCCLS_DATA_DIR", str(d))
    return d


@pytest.fixture
def run(capsys):
    """doc_classifier.main을 실행하고 (종료 코드, JSON)을 돌려줍니다. stdout은 정확히 1줄이어야 합니다."""
    import doc_classifier

    def _run(*argv):
        with pytest.raises(SystemExit) as ei:
            doc_classifier.main(list(argv))
        out = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert len(out) == 1, out
        return ei.value.code, json.loads(out[0])
    return _run
