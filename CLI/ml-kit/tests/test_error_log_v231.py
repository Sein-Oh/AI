# -*- coding: utf-8 -*-
"""
2.3.1 regression tests: error log <data>/logs/errors.txt (AGENTS.md "오류 로그 저장", CLI/README.md R6)
and VERSION == SKILL.md metadata.version.
"""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, KIT)
from test_cli_smoke import run_raw  # noqa: E402
import ml_predict as mc  # noqa: E402


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setenv("ML_KIT_DATA_DIR", str(d))
    monkeypatch.setattr(mc, "_RECOVERED", [])
    monkeypatch.setattr(mc, "_RECOVERY_ATTEMPTS", [])
    return d


def _log(d):
    p = d / "logs" / "errors.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _run_inproc(capsys, body):
    """Runs mc.run_cli in-process; returns (exit code or None, the single stdout JSON)."""
    code = None
    try:
        mc.run_cli(body)
    except SystemExit as e:
        code = e.code
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1, lines
    return code, json.loads(lines[0])


def test_version_matches_skill_metadata():
    text = open(os.path.join(KIT, "SKILL.md"), encoding="utf-8").read()
    m = re.search(r'^\s*version:\s*"?([0-9.]+)"?\s*$', text, re.M)
    assert m and m.group(1) == mc.VERSION
    import ml_report
    assert ml_report.REPORT_VERSION == mc.VERSION


def test_default_data_dir_is_tool_folder(monkeypatch):
    monkeypatch.delenv("ML_KIT_DATA_DIR", raising=False)
    assert mc.get_data_dir() == os.path.join(KIT, "data")
    assert mc.error_log_path() == os.path.join(KIT, "data", "logs", "errors.txt")


def test_input_error_exit1_logged_without_traceback(data_dir, tmp_path):
    proc, payload = run_raw("ml_predict.py", "-m", str(tmp_path / "없는폴더"), "-i", "a=1")
    assert proc.returncode == 1 and payload["agent_directive"].startswith("STOP_RETRY")
    log = _log(data_dir)
    head = log.splitlines()[0]
    assert head.startswith("===== ") and f"| ml-kit {mc.VERSION} | Python " in head
    assert "명령: ml_predict.py -m " in log and "없는폴더" in log
    assert "결과: input | " in log
    assert "traceback:" not in log and "복구 시도:" not in log
    assert log.endswith("\n\n")
    assert "errors.txt" not in json.dumps(payload, ensure_ascii=False)  # log path is never in stdout JSON


def test_argument_error_exit2_logged(data_dir):
    proc, payload = run_raw("ml_predict.py", "-i", "a=1")  # --model missing
    assert proc.returncode == 2 and payload["status"] == "error"
    log = _log(data_dir)
    assert "명령: ml_predict.py -i \"a=1\"" in log and "결과: input | CLI 인자 오류" in log


def test_internal_error_logged_with_traceback(data_dir, capsys):
    def body():
        raise RuntimeError("내부 버그")
    code, payload = _run_inproc(capsys, body)
    assert code == 1 and payload["error_type"] == "internal" and payload["agent_directive"].startswith("ERROR:")
    log = _log(data_dir)
    assert "결과: internal | RuntimeError: 내부 버그" in log
    assert "traceback:\nTraceback (most recent call last):" in log and "RuntimeError: 내부 버그" in log


def test_success_and_interrupt_not_logged(data_dir, capsys):
    code, payload = _run_inproc(capsys, lambda: {"status": "ok", "agent_directive": "VERIFIED: ok"})
    assert code is None and payload["status"] == "ok"

    def interrupted():
        raise KeyboardInterrupt()
    code, payload = _run_inproc(capsys, interrupted)
    assert code == 130 and payload["error_type"] == "interrupted"
    assert not (data_dir / "logs" / "errors.txt").exists()


def test_recovery_attempt_line(data_dir, capsys):
    def body():
        def locked():
            raise PermissionError("locked")
        mc.retry_fs(locked, attempts=2, delay=0)
    code, payload = _run_inproc(capsys, body)
    assert code == 1
    assert "복구 시도: 파일 작업 2회 재시도 실패" in _log(data_dir)


def test_rotation_at_size_limit(data_dir, monkeypatch):
    logs = data_dir / "logs"
    logs.mkdir(parents=True)
    (logs / "errors.txt").write_text("OLD ENTRY\n" * 10, encoding="utf-8")
    monkeypatch.setattr(mc, "ERROR_LOG_MAX", 50)
    mc.write_error_log({"error_type": "input", "message": "새 항목"}, argv=["ml_train.py", "-f", "a.csv"])
    assert "OLD ENTRY" in (logs / "errors.old.txt").read_text(encoding="utf-8")
    new = (logs / "errors.txt").read_text(encoding="utf-8")
    assert "OLD ENTRY" not in new and "결과: input | 새 항목" in new and "명령: ml_train.py -f a.csv" in new


def test_rotation_failure_keeps_entry(data_dir, monkeypatch):
    logs = data_dir / "logs"
    logs.mkdir(parents=True)
    (logs / "errors.txt").write_text("OLD ENTRY\n" * 10, encoding="utf-8")
    monkeypatch.setattr(mc, "ERROR_LOG_MAX", 50)

    def deny(*_a, **_k):
        raise PermissionError("rotation locked")
    monkeypatch.setattr(mc.os, "replace", deny)
    mc.write_error_log({"error_type": "input", "message": "회전 실패에도 기록"}, argv=["ml_report.py"])
    assert "회전 실패에도 기록" in (logs / "errors.txt").read_text(encoding="utf-8")


def test_logging_failure_keeps_json_contract(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")  # data dir is a file -> makedirs fails inside write_error_log
    monkeypatch.setenv("ML_KIT_DATA_DIR", str(blocker))

    def body():
        raise mc.InputError("입력 오류")
    code, payload = _run_inproc(capsys, body)
    assert code == 1 and payload["status"] == "error" and payload["message"] == "입력 오류"
