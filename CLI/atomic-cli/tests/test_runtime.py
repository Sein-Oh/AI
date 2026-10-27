"""_runtime.py 계약 테스트: stdout 1줄 JSON, 종료 코드, agent_directive, 경로/입출력 도우미."""
import datetime
import json
import os
import subprocess
import sys
import textwrap

import pytest

import _runtime as rt

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_script(tmp_path, body, *args):
    """_runtime을 쓰는 임시 진입점을 하위 프로세스로 실행합니다. (종료 코드, JSON, stderr)"""
    script = tmp_path / "tool.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {TOOL_DIR!r})\n"
        "import _runtime as rt\n" + textwrap.dedent(body),
        encoding="utf-8",
    )
    proc = subprocess.run([sys.executable, str(script), *args], capture_output=True, timeout=60,
                          env=dict(os.environ, ATOMIC_DATA_DIR=str(tmp_path / "data"),
                                   ATOMIC_CACHE_DIR=str(tmp_path / "cache")))
    out = proc.stdout.decode("utf-8")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, f"stdout은 정확히 1줄이어야 함: {out!r} / stderr: {proc.stderr.decode('utf-8', 'replace')}"
    return proc.returncode, json.loads(lines[0]), proc.stderr.decode("utf-8", "replace")


TOOL_BODY = """
parser, sub = rt.build_parser("demo", "demo tool")
p = sub.add_parser("go")
p.add_argument("--mode", required=True)
args = parser.parse_args()

def execute():
    if args.mode == "ok":
        rt.log("PROGRESS", "작업 중")
        return rt.ok("demo", "go", "완료했습니다", value="한글")
    if args.mode == "input":
        raise rt.not_found("시트", "Sheet3", ["Sheet1", "Sheet2", "시트3"])
    if args.mode == "busy":
        class com_error(Exception):
            pass
        raise com_error(-2146777998, "예외", (0, "Microsoft Excel", "편집 중", None, 0, -2146777998), None)
    if args.mode == "interrupt":
        raise KeyboardInterrupt()
    raise RuntimeError("버그")

rt.run_cli("demo", "go", execute)
"""


def test_ok_response_is_one_json_line_exit_0(tmp_path):
    code, payload, err = run_script(tmp_path, TOOL_BODY, "go", "--mode", "ok")
    assert code == 0
    assert payload["status"] == "ok" and payload["value"] == "한글"
    assert payload["agent_directive"].startswith("VERIFIED:")
    assert "[PROGRESS] 작업 중" in err


def test_input_error_is_stop_retry_with_suggestion(tmp_path):
    code, payload, _ = run_script(tmp_path, TOOL_BODY, "go", "--mode", "input")
    assert code == 1
    assert payload["status"] == "error" and payload["error_type"] == "input"
    assert payload["agent_directive"].startswith("STOP_RETRY:")
    assert "[추천] 시트3" in payload["message"] or "[추천]" in payload["message"]


def test_com_busy_error_is_explained(tmp_path):
    code, payload, _ = run_script(tmp_path, TOOL_BODY, "go", "--mode", "busy")
    assert code == 1
    assert payload["error_type"] == "office_busy"
    assert payload["hresult"] == "0x800AC472"
    assert "Esc" in payload["message"]


def test_internal_error_is_error_directive(tmp_path):
    code, payload, _ = run_script(tmp_path, TOOL_BODY, "go", "--mode", "boom")
    assert code == 1
    assert payload["error_type"] == "internal"
    assert payload["agent_directive"].startswith("ERROR:")


def test_interrupt_exit_130(tmp_path):
    code, payload, _ = run_script(tmp_path, TOOL_BODY, "go", "--mode", "interrupt")
    assert code == 130 and payload["error_type"] == "interrupted"


def test_argument_error_is_json_exit_2(tmp_path):
    code, payload, _ = run_script(tmp_path, TOOL_BODY, "go")
    assert code == 2
    assert payload["status"] == "error" and payload["tool"] == "demo"
    assert payload["agent_directive"].startswith("STOP_RETRY:")


def test_missing_subcommand_is_json_exit_2(tmp_path):
    code, payload, _ = run_script(tmp_path, TOOL_BODY)
    assert code == 2 and payload["status"] == "error"


# ---------------------------------------------------------------------------
# 도우미 함수
# ---------------------------------------------------------------------------

def test_suggest_and_find_name():
    assert rt.find_name(" sheet1 ", ["Sheet1", "Sheet2"]) == "Sheet1"
    assert rt.suggest("시트 2", ["시트1", "시트2", "요약"])[0] == "시트2"
    assert rt.suggest("매출보고", ["10월 매출보고서", "요약"])[0] == "10월 매출보고서"
    msg = str(rt.not_found("시트", "없는", ["A", "B"]))
    assert "사용 가능한 시트: A, B" in msg


def test_json_safe():
    data = {"nan": float("nan"), "d": datetime.date(2026, 10, 27), "t": (1, 2), "b": b"x"}
    assert rt.json_safe(data) == {"nan": None, "d": "2026-10-27", "t": [1, 2], "b": "x"}


def test_read_text_file_encodings(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes("한글 테스트".encode("cp949"))
    assert rt.read_text_file(str(p)) == "한글 테스트"
    p.write_bytes("한글 테스트".encode("utf-16"))
    assert rt.read_text_file(str(p)) == "한글 테스트"
    p.write_bytes("﻿한글".encode("utf-8"))
    assert rt.read_text_file(str(p)) == "한글"


def test_read_csv_rows_detects_delimiter(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("이름;값\n가;1\n나;2\n", encoding="utf-8")
    assert rt.read_csv_rows(str(p)) == [["이름", "값"], ["가", "1"], ["나", "2"]]
    p.write_text("이름\t값\n가\t1\n", encoding="utf-8")
    assert rt.read_csv_rows(str(p))[1] == ["가", "1"]


def test_write_csv_roundtrip_utf8_sig(tmp_path):
    path = rt.write_csv_rows(str(tmp_path / "o.csv"), [["x", "sin(x)"], [0, None]])
    assert open(path, "rb").read().startswith(b"\xef\xbb\xbf")
    assert rt.read_csv_rows(path) == [["x", "sin(x)"], ["0", ""]]


def test_save_with_lock_fallback_uses_new_name(tmp_path):
    target = str(tmp_path / "locked.csv")
    calls = []

    def writer(p):
        calls.append(p)
        if p == target:
            raise PermissionError("locked")
        open(p, "w").close()

    saved = rt.save_with_lock_fallback(target, writer)
    assert saved != target and os.path.exists(saved) and calls[0] == target


def test_resolve_output_path_rules():
    auto = rt.resolve_output_path(None, "search", ".md")
    assert os.path.dirname(auto) == rt.get_work_dir() and auto.endswith(".md")
    named = rt.resolve_output_path("report.docx", "x", ".pdf")
    assert named == os.path.join(rt.get_data_dir(), "report.pdf")
    noext = rt.resolve_output_path("result", "x", "csv")
    assert noext.endswith("result.csv")


def test_resolve_input_path_suggests(tmp_path):
    data = rt.get_data_dir()
    open(os.path.join(data, "매출_10월.csv"), "w").close()
    assert rt.resolve_input_path("매출_10월.csv") == os.path.join(data, "매출_10월.csv")
    with pytest.raises(rt.InputError) as ei:
        rt.resolve_input_path("매출_10월.xlsx")
    assert "[추천] 매출_10월.csv" in str(ei.value)


def test_cleanup_work_dir_removes_old_files():
    work = rt.get_work_dir()
    old = os.path.join(work, "old.md")
    new = os.path.join(work, "new.md")
    for p in (old, new):
        open(p, "w").close()
    past = datetime.datetime.now().timestamp() - 30 * 86400
    os.utime(old, (past, past))
    assert rt.cleanup_work_dir() == 1
    assert not os.path.exists(old) and os.path.exists(new)


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(rt, "_config_cache", None)
    assert rt.load_config() == {}
    rt.set_config("transfer_method", {"ppt": "relay"})
    monkeypatch.setattr(rt, "_config_cache", None)
    assert rt.load_config()["transfer_method"] == {"ppt": "relay"}


def test_clamp_rows_and_text():
    rows = [[i, "x" * 10] for i in range(500)]
    clipped, cut = rt.clamp_rows(rows, max_rows=50)
    assert len(clipped) == 50 and cut
    clipped, cut = rt.clamp_rows(rows[:5])
    assert len(clipped) == 5 and not cut
    text, cut = rt.clamp_text("가" * 10, max_chars=4)
    assert text == "가가가가" and cut


def test_next_command_quotes_paths():
    cmd = rt.next_command("office.py", ["transfer", "--chart", "사인 2주기", "--to", "word,ppt"], "차트 전달")
    assert cmd["purpose"] == "차트 전달"
    assert '"사인 2주기"' in cmd["command"] and '"word,ppt"' in cmd["command"]
    assert "office.py" in cmd["command"]


def test_markdown_blocks_and_bold():
    blocks = rt.parse_markdown_blocks("# 제목\n본문 **굵게**\n이어짐\n\n- a\n- b\n1. x\n2) y\n| 공정 | 수율 |\n|---|---|\n| 가열 | 98 |\n---\n## 끝")
    assert blocks == [("heading", (1, "제목")), ("paragraph", "본문 **굵게** 이어짐"), ("bullets", ["a", "b"]),
                      ("numbered", ["x", "y"]), ("table", [["공정", "수율"], ["가열", "98"]]), ("break", None),
                      ("heading", (2, "끝"))]
    assert rt.split_bold("가 **나** 다 __라__") == ("가 나 다 라", [(2, 3), (6, 7)])
    assert rt.looks_like_markdown("- 항목") and not rt.looks_like_markdown("그냥 문장")
