# -*- coding: utf-8 -*-
"""grade_opencode.py: OpenCode export parsing, scenario checks, and the message pack staying in sync with the yaml."""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("grade_opencode", os.path.join(os.path.dirname(HERE), "grade_opencode.py"))
go = importlib.util.module_from_spec(spec)
spec.loader.exec_module(go)

ENC = "$env:PYTHONIOENCODING='utf-8'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "


def _bash(cmd, out):
    return {"type": "tool", "tool": "bash", "state": {"status": "completed", "input": {"command": ENC + cmd},
                                                      "output": "[PROGRESS] ...\n" + json.dumps(out, ensure_ascii=False), "metadata": {"exit": 0}}}


def _export(tmp_path, turns):
    msgs, t = [], 1000
    for user, parts in turns:
        msgs.append({"info": {"role": "user", "time": {"created": t}}, "parts": [{"type": "text", "text": user}]})
        msgs.append({"info": {"role": "assistant", "time": {"created": t + 1, "completed": t + 5000}}, "parts": parts})
        t += 10000
    path = tmp_path / "chat.json"
    path.write_text(json.dumps({"info": {"model": {"id": "LLM42"}, "version": "1.18"}, "messages": msgs}, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_pass_fail_and_forbidden_actions(tmp_path):
    ok = {"status": "ok", "agent_directive": "VERIFIED: ok"}
    path = _export(tmp_path, [
        ("[M1] 맵.xlsx 에서 A가 12.5일 때", [_bash('python "C:\\CLI\\ml-kit\\ml_map.py" -f "맵.xlsx" -i "A=12.5"', ok),
                                         {"type": "text", "text": "B는 16.25, C는 87.5입니다."}]),
        ("[M2] D가 64가 되는 A", [_bash('python -c "import pandas"', ok), _bash('pip install scipy', ok),
                                {"type": "tool", "tool": "read", "state": {"status": "completed", "input": {"filePath": "C:\\CLI\\ml-kit\\ml_map.py"}, "output": ""}},
                                {"type": "text", "text": "file:///C:/x.xlsx la la la la la la la la la"}]),
        ("아니 다시 해줘", [{"type": "text", "text": "A는 20과 80입니다."}]),       # untagged follow-up joins M2
    ])
    meta, rows, detail = go.grade([path], "t", False, "LLM42")
    by = {r["id"]: r for r in rows}
    assert by["M1"]["결과"] == "통과" and by["M1"]["초"] == 5
    assert by["M2"]["결과"] == "실패" and by["A1"]["결과"] == "없음"
    fails = by["M2"]["실패"]
    for word in ("ml_map", "패키지 설치", "임의 파이썬", "도구 코드", "file:///", "반복"):
        assert word in fails
    assert "20" not in fails and "$env:" not in fails                                           # answer from the follow-up counts
    report, npass, n = go.write_report("t", meta, rows, detail)
    text = open(report, encoding="utf-8").read()
    os.remove(report)
    os.remove(report[:-3] + ".xlsx") if os.path.exists(report[:-3] + ".xlsx") else None
    assert npass == 1 and n == 2 and "$env:" not in text and "`python \"C:\\CLI\\ml-kit\\ml_map.py\"" in text


def test_bulk_message_grades_each_tag(tmp_path):
    ok = {"status": "ok", "agent_directive": "VERIFIED: ok"}
    path = _export(tmp_path, [("순서대로 처리해줘\n[M1] A=12.5\n[M3] A=103", [
        _bash('python "C:\\CLI\\ml-kit\\ml_map.py" -f "맵.xlsx" -i "A=12.5"', ok),
        _bash('python "C:\\CLI\\ml-kit\\ml_map.py" -f "맵.xlsx" -i "A=103"', ok),
        {"type": "text", "text": "B 16.25, C 87.5 / B 1058.5 (범위 밖 외삽값)"}])])
    _, rows, _ = go.grade([path], "t", False, "LLM42")
    by = {r["id"]: r for r in rows}
    assert by["M1"]["결과"] == "통과" and by["M3"]["결과"] == "통과" and by["M1"]["같이 보낸 요청"] == "M3"


def test_message_pack_matches_yaml(tmp_path, monkeypatch):
    committed = {f: open(os.path.join(go.PACK_DIR, f), encoding="utf-8").read() for f in os.listdir(go.PACK_DIR)}
    monkeypatch.setattr(go, "PACK_DIR", str(tmp_path))
    go.make_pack(None)
    fresh = {f: (tmp_path / f).read_text(encoding="utf-8") for f in os.listdir(tmp_path)}
    assert fresh == committed, "agent_scenarios.yaml이 바뀌었으면 python grade_opencode.py --make-pack 으로 메시지 팩을 다시 만드세요"
    spec_, by_id, order = go.load_scenarios()
    assert len(order) == len(set(order)) and all(go.TAG.fullmatch(f"[{s}]") for s in order)


def test_judge_uses_completions_api(tmp_path, monkeypatch):
    import http.server
    import threading
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = json.dumps({"choices": [{"text": "점수: 4\n이유: 값은 맞지만 경고가 빠짐"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("JUDGE_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    path = _export(tmp_path, [("[M1] A=12.5", [{"type": "text", "text": "B 16.25, C 87.5"}])])
    _, rows, _ = go.grade([path], "t", True, "LLM42")
    srv.shutdown()
    m1 = next(r for r in rows if r["id"] == "M1")
    assert (m1["점수"], m1["채점 이유"]) == (4, "값은 맞지만 경고가 빠짐")
    assert seen["path"] == "/v1/completions" and seen["body"]["model"] == "LLM42" and "B 16.25" in seen["body"]["prompt"]


def test_remote_agent_instructions_match_skill_files(tmp_path, monkeypatch):
    """docs/remote-agent/<tool>_지시문.md는 SKILL.md에서 만든 것: SKILL.md를 고치면 build.py를 다시 실행."""
    repo = os.path.dirname(os.path.dirname(HERE))
    spec_ = importlib.util.spec_from_file_location("build", os.path.join(repo, "docs", "remote-agent", "build.py"))
    build = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(build)
    monkeypatch.setattr(build, "OUT", str(tmp_path))
    for tool in ("ml-kit", "office-cli"):
        with open(os.path.join(repo, "docs", "remote-agent", f"{tool}_지시문.md"), encoding="utf-8") as f, \
                open(build.convert(tool), encoding="utf-8") as g:
            assert f.read() == g.read(), f"python docs/remote-agent/build.py 를 실행하세요 ({tool})"
