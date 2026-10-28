"""Windows 실기 러너의 테스트 폴더 준비: 러너가 만든 폴더만 지우고, 사용자 폴더는 거부 (CLI/README.md R4)."""
import importlib.util
import os

import pytest

import _dc_runtime as rt


def _runner():
    spec = importlib.util.spec_from_file_location("dc_run_win_tests", os.path.join(rt.TOOL_DIR, "tools", "run_win_tests.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prepare_test_dir_creates_marker_and_only_clears_own_folder(tmp_path):
    r = _runner()
    d = tmp_path / "dc_test"
    r.prepare_test_dir(str(d))                                  # 없으면 만들고 표식
    assert (d / r.MARKER).exists()
    (d / "jobs").mkdir()
    (d / "jobs" / "old.db").write_text("x")
    r.prepare_test_dir(str(d))                                  # 러너가 만든 폴더면 비우고 다시
    assert sorted(os.listdir(d)) == [r.MARKER]
    empty = tmp_path / "빈폴더"
    empty.mkdir()
    r.prepare_test_dir(str(empty))                              # 비어 있는 폴더는 사용
    assert (empty / r.MARKER).exists()


def test_prepare_test_dir_refuses_user_folder(tmp_path):
    r = _runner()
    user = tmp_path / "내자료"
    user.mkdir()
    (user / "중요.docx").write_text("소중한 자료")
    with pytest.raises(r.RefusedDir) as ei:
        r.prepare_test_dir(str(user))
    assert "지우지 않았습니다" in str(ei.value)
    assert (user / "중요.docx").read_text() == "소중한 자료" and not (user / r.MARKER).exists()
    f = tmp_path / "파일.txt"
    f.write_text("x")
    with pytest.raises(r.RefusedDir):
        r.prepare_test_dir(str(f))
