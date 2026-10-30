# -*- coding: utf-8 -*-
"""OpenCode 대화 내보내기(JSON) 채점기 + 메시지 팩 생성기 (사람이 실행하는 개발 도구)

채점:
    python grade_opencode.py --export <대화.json> [<대화2.json> ...] [--label 회사PC] [--judge]
메시지 팩 다시 만들기 (agent_scenarios.yaml을 고친 뒤):
    python grade_opencode.py --make-pack [--dir C:\\ml_beta\\agent]

채점 기준은 agent_scenarios.yaml 한 곳에 있다. 사용자 메시지 앞의 "[ID]" 표시로 시나리오를 찾고,
그 요청부터 다음 표시가 나오기 전까지의 명령·도구 결과·답변을 본다 (하나씩 보낸 대화와 한 번에 보낸 대화 모두).

판정 (도구로 확인, LLM 판단 없음):
  - 필요한 명령을 실행했는가 (commands), 도구 결과 JSON이 ok인가 (tool_ok)
  - 답변에 꼭 들어갈 값이 있는가 (answer_all, answer_any)
  - 공통 금지: 패키지 설치, py/python3, 임의 파이썬 코드, 도구 코드 읽기, .py 쓰기, 같은 명령 반복, 답변의 이모지·file:///·같은 말 반복
--judge: 사내 OpenAI 호환 API(completions)로 시나리오별 1~5점과 이유를 붙인다 (참고용, 통과 여부에는 넣지 않음).
  환경변수 JUDGE_BASE_URL (예: http://서버/v1), JUDGE_API_KEY(없으면 생략), --judge-model (기본 LLM42).

결과: 이 파일 옆에 grade_<라벨>_<시각>.md (요약 + 실패 상세 + 명령 기록)와 .xlsx (시나리오별 표).
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCENARIOS = os.path.join(HERE, "agent_scenarios.yaml")
PACK_DIR = os.path.join(REPO, "docs", "opencode", "자동테스트")
TAG = re.compile(r"\[([A-Z]\d+)\]")
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2460-\u24FF\u2190-\u21FF]")
REPEAT = re.compile(r"(\S{1,10})(?:\s*\1){7,}")
ENC_PREFIX = re.compile(r"^(\s*(\$env:\w+\s*=\s*[^;]+|\[Console\]::\w+\s*=\s*[^;]+);)+\s*")   # PowerShell encoding line from the global rules


def load_scenarios():
    import yaml
    with open(SCENARIOS, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    order = [s for g in spec["groups"] for s in g["scenarios"]]
    return spec, {s["id"]: s for s in order}, [s["id"] for s in order]


# ------------------------------------------------------------------------------------------------
# 대화 읽기
def read_turns(path):
    """Splits one export into turns: a user message with a [ID] tag plus everything after it up to the next tag."""
    with open(path, encoding="utf-8-sig") as f:
        data = json.load(f)
    turns, cur = [], None
    for m in data.get("messages", []):
        info, parts = m.get("info", {}), m.get("parts", [])
        t = info.get("time", {})
        if info.get("role") == "user":
            text = "\n".join(p.get("text", "") for p in parts if p.get("type") == "text")
            tags = list(dict.fromkeys(TAG.findall(text)))
            if tags or cur is None:
                cur = {"tags": tags, "user": [text], "tools": [], "texts": [], "start": t.get("created"), "end": t.get("created"),
                       "file": os.path.basename(path)}
                turns.append(cur)
            else:
                cur["user"].append(text)               # follow-up without a tag (e.g. answering Gemma's question)
            continue
        if cur is None:
            continue
        cur["end"] = t.get("completed") or t.get("created") or cur["end"]
        for p in parts:
            if p.get("type") == "text" and p.get("text", "").strip():
                cur["texts"].append(p["text"])
            elif p.get("type") == "tool":
                st = p.get("state", {})
                inp = st.get("input", {}) or {}
                cur["tools"].append({"tool": p.get("tool"), "status": st.get("status"), "input": inp,
                                     "command": inp.get("command", ""), "path": inp.get("filePath", ""),
                                     "output": st.get("output") or st.get("error") or "",
                                     "exit": (st.get("metadata") or {}).get("exit")})
    return data.get("info", {}), turns


def last_json(output):
    for line in reversed(str(output).splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


# ------------------------------------------------------------------------------------------------
# 채점
def grade_turn(sc, turn, rules):
    """Returns a list of (check name, ok, detail) for one scenario on one turn."""
    cmds = [ENC_PREFIX.sub("", t["command"]) for t in turn["tools"] if t["tool"] == "bash"]
    answer = turn["texts"][-1] if turn["texts"] else ""
    every = "\n".join(turn["texts"])
    out = []
    for rx in sc.get("commands", []):
        hit = any(re.search(rx, c, re.I) for c in cmds)
        out.append((f"명령: {rx}", hit, "" if hit else "맞는 명령 없음"))
    if sc.get("tool_ok"):
        runs = [t for t in turn["tools"] if t["tool"] == "bash" and re.search(sc["tool_ok"], t["command"], re.I)]
        payload = last_json(runs[-1]["output"]) if runs else None
        ok = bool(payload) and payload.get("status") == "ok"
        detail = "실행 없음" if not runs else "JSON 없음" if not payload else str(payload.get("agent_directive", ""))[:200]
        out.append(("도구 결과 ok", ok, "" if ok else detail))
    for rx in sc.get("answer_all", []):
        hit = bool(re.search(rx, every, re.I))
        out.append((f"답변: {rx}", hit, "" if hit else "답변에 없음"))
    if sc.get("answer_any"):
        hit = any(re.search(rx, every, re.I) for rx in sc["answer_any"])
        out.append(("답변: " + " 또는 ".join(sc["answer_any"]), hit, "" if hit else "답변에 없음"))
    for rx in sc.get("forbid", []):
        bad = [c for c in cmds if re.search(rx, c, re.I)]
        out.append((f"금지 명령: {rx}", not bad, "; ".join(bad)[:300]))

    allow = set(sc.get("allow", []))
    for rid, rule in rules.items():
        if rid in allow:
            continue
        bad = []
        if rule.get("command"):
            bad += [c for c in cmds if re.search(rule["command"], c, re.I | re.M)]
        if rule.get("read"):
            bad += [t["path"] for t in turn["tools"] if t["tool"] == "read" and re.search(rule["read"], t["path"], re.I)]
        if rule.get("write"):
            bad += [t["path"] for t in turn["tools"] if t["tool"] == "write" and re.search(rule["write"], t["path"], re.I)]
        if rule.get("max_repeat"):
            bad += [f"{n}회: {c}" for c, n in Counter(re.sub(r"\s+", " ", c).strip() for c in cmds).items() if n > rule["max_repeat"]]
        if rid == "answer_clean":
            bad += [f"이모지 {m}" for m in set(EMOJI.findall(every))]
            bad += ["file:/// 링크"] if "file:///" in every else []
            bad += [f"반복 '{m.group(0)[:40]}'" for m in REPEAT.finditer(every) if re.search(r"[^\W\d_]", m.group(1))][:3]   # words, not table rules
        out.append((rule["title"], not bad, "; ".join(map(str, bad))[:300]))
    if not answer:
        out.append(("최종 답변 있음", False, "답변 문장이 없음"))
    return out


def judge(sc, turn, rubric, model):
    base = os.environ.get("JUDGE_BASE_URL", "").rstrip("/")
    if not base:
        return None, "JUDGE_BASE_URL 환경변수가 없어 건너뜀"
    tools = "\n".join(f"$ {t['command'] or t['tool'] + ' ' + t['path']}\n{str(t['output'])[-1500:]}" for t in turn["tools"])[-6000:]
    prompt = ("너는 업무 도우미 AI의 답변을 채점하는 평가자다.\n"
              f"[채점 기준]\n{rubric}\n\n[사용자 요청]\n{chr(10).join(turn['user'])}\n\n"
              f"[도우미가 실행한 명령과 결과]\n{tools or '(없음)'}\n\n[도우미의 최종 답변]\n{(turn['texts'] or [''])[-1][-3000:]}\n\n"
              "기준에 맞으면 5, 전혀 맞지 않으면 1이다. 아래 형식으로 두 줄만 쓴다.\n점수: <1~5>\n이유: <한 문장>\n")
    body = json.dumps({"model": model, "prompt": prompt, "max_tokens": 200, "temperature": 0}).encode("utf-8")
    req = urllib.request.Request(base + "/completions", data=body, headers={"Content-Type": "application/json"})
    if os.environ.get("JUDGE_API_KEY"):
        req.add_header("Authorization", "Bearer " + os.environ["JUDGE_API_KEY"])
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            text = json.loads(r.read().decode("utf-8"))["choices"][0]["text"]
    except Exception as e:
        return None, f"채점 API 오류: {type(e).__name__}: {e}"[:200]
    m = re.search(r"점수\s*[:：]\s*([1-5])", text)
    why = re.search(r"이유\s*[:：]\s*(.+)", text)
    return (int(m.group(1)) if m else None), (why.group(1).strip() if why else text.strip())[:300]


def grade(paths, label, use_judge, model):
    spec, by_id, order = load_scenarios()
    rules = spec["rules"]
    found, meta = {}, []
    for p in paths:
        info, turns = read_turns(p)
        meta.append(f"{os.path.basename(p)} (모델 {info.get('model', {}).get('id', '?')}, OpenCode {info.get('version', '?')})")
        for t in turns:
            for tag in t["tags"]:
                if tag in by_id:
                    found.setdefault(tag, []).append(t)
    rows, detail = [], []
    for sid in order:
        sc = by_id[sid]
        if sid not in found:
            rows.append({"id": sid, "결과": "없음", "실패": "대화에 이 요청이 없음", "명령수": 0, "초": None, "보낸횟수": 0})
            continue
        turn = found[sid][-1]                            # graded on the last time the request was sent
        shared = [x for x in turn["tags"] if x != sid]
        checks = grade_turn(sc, turn, rules)
        fails = [f"{n} ({d})" if d else n for n, ok, d in checks if not ok]
        row = {"id": sid, "결과": "통과" if not fails else "실패", "실패": " | ".join(fails), "명령수": len(turn["tools"]),
               "초": round((turn["end"] - turn["start"]) / 1000) if turn["start"] and turn["end"] else None,
               "보낸횟수": len(found[sid]), "같이 보낸 요청": ",".join(shared)}
        if use_judge:
            row["점수"], row["채점 이유"] = judge(sc, turn, sc.get("judge") or spec["default_judge"], model)
        rows.append(row)
        detail.append((sid, sc, turn, checks))
    return meta, rows, detail


def write_report(label, meta, rows, detail):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(HERE, f"grade_{label}_{stamp}")
    graded = [r for r in rows if r["결과"] != "없음"]
    npass = sum(r["결과"] == "통과" for r in graded)
    scores = [r["점수"] for r in graded if isinstance(r.get("점수"), int)]
    lines = [f"# OpenCode 종합 테스트 채점 ({label})", "", f"- 채점 시각: {datetime.now():%Y-%m-%d %H:%M}"]
    lines += [f"- 대화 파일: {m}" for m in meta]
    lines += [f"- 결과: 채점 {len(graded)}건 중 통과 {npass}건 ({npass / max(len(graded), 1) * 100:.0f}%), 대화에 없음 {len(rows) - len(graded)}건"]
    if scores:
        lines.append(f"- 채점 LLM 평균 점수: {sum(scores) / len(scores):.2f} / 5 ({len(scores)}건, 참고용)")
    has_judge = any("점수" in r for r in rows)
    lines += ["", "| 요청 | 결과 | 명령 수 | 걸린 초 | 실패 항목 |" + (" 점수 |" if has_judge else ""),
              "|---|---|---|---|---|" + ("---|" if has_judge else "")]
    for r in rows:
        lines.append(f"| {r['id']} | {r['결과']} | {r['명령수']} | {r['초'] if r['초'] is not None else ''} | {r['실패'] or ''} |"
                     + (f" {r.get('점수') if r.get('점수') is not None else ''} |" if has_judge else ""))
    lines += ["", "## 요청별 기록", ""]
    for sid, sc, turn, checks in detail:
        lines += [f"### {sid}", "", "요청: " + " / ".join(u.strip() for u in turn["user"])[:400], ""]
        for n, ok, d in checks:
            lines.append(f"- [{'OK' if ok else 'FAIL'}] {n}" + (f": {d}" if d and not ok else ""))
        lines += ["", "명령:"]
        for t in turn["tools"]:
            what = ENC_PREFIX.sub("", t["command"]) or f"{t['tool']} {t['path']}".strip()
            payload = last_json(t["output"]) if t["tool"] == "bash" else None
            res = f" -> {payload.get('status')} / {str(payload.get('agent_directive', ''))[:60]}" if payload else ""
            lines.append(f"- `{what[:300]}`{res}")
        answer = (turn["texts"] or ["(답변 없음)"])[-1].strip()
        lines += ["", "최종 답변:", "", "> " + answer[:1500].replace("\n", "\n> "), ""]
        row = next(r for r in rows if r["id"] == sid)
        if row.get("채점 이유"):
            lines += [f"채점 LLM: {row.get('점수')}점, {row['채점 이유']}", ""]
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    try:
        import pandas as pd
        pd.DataFrame(rows).to_excel(base + ".xlsx", index=False)
    except Exception as e:
        print(f"[WARN] xlsx 저장 실패: {e}", file=sys.stderr)
    return base + ".md", npass, len(graded)


# ------------------------------------------------------------------------------------------------
# 메시지 팩
def make_pack(test_dir):
    spec, _, _ = load_scenarios()
    d = test_dir or spec["dir"]
    os.makedirs(PACK_DIR, exist_ok=True)
    msg = lambda s: f"[{s['id']}] " + s["message"].replace("{DIR}", d)
    index = ["# OpenCode 종합 테스트 메시지 팩", "",
             "agent_scenarios.yaml에서 만든 파일입니다. 직접 고치지 말고 yaml을 고친 뒤 `python grade_opencode.py --make-pack`으로 다시 만듭니다.", "",
             "## 1. 도구 점검 (정답을 아는 샘플로 도구만 확인, 5~10분)", "",
             "PowerShell에서 직접 실행하거나 Gemma에게 아래 메시지를 붙여넣습니다. 결과는 `C:\\CLI-dev\\beta_check_회사PC_<시각>.md`.", "",
             "```powershell", "python \"C:\\CLI-dev\\run_beta_check.py\" --label 회사PC", "```", "",
             "```text",
             "python \"C:\\CLI-dev\\run_beta_check.py\" --label 회사PC --agent 를 시간 제한 1800000으로 1번만 실행하고, "
             "결과 JSON의 passed, failed, skipped, failed_items, report_file을 그대로 알려줘.",
             "```", "",
             "## 2. Gemma 종합 테스트 (요청 처리 확인)", "",
             f"1. 시험 폴더 `{d}`가 이미 있으면 탐색기에서 지웁니다 (이전 모델이 남아 있으면 버전 번호가 달라집니다).",
             "2. OpenCode에서 새 대화를 열고, 아래 묶음 파일의 메시지를 순서대로 붙여넣습니다.",
             "   - 하나씩: 메시지 1개를 보내고 답을 받은 뒤 다음 메시지를 보냅니다 (권장).",
             "   - 한 번에: 묶음 전체를 메시지 1개로 보냅니다 (긴 작업을 이어서 처리하는지 볼 때).",
             "   - 묶음은 S -> A -> M -> P -> R -> X 순서입니다. P와 R은 A에서 만든 모델을 씁니다.",
             "3. 끝나면 OpenCode에서 대화를 JSON으로 내보냅니다.",
             "4. `C:\\CLI-dev`에서 채점합니다:", "",
             "```powershell", "python grade_opencode.py --export \"<내보낸 대화.json>\" --label 회사PC", "```", "",
             "   여러 대화로 나눠 했으면 `--export a.json b.json`처럼 함께 넣습니다.",
             "   사내 LLM 참고 점수를 붙이려면 `$env:JUDGE_BASE_URL='http://<서버>/v1'` 설정 후 `--judge` (통과 여부에는 넣지 않음).",
             "5. 만들어진 `grade_회사PC_<시각>.md`와 `beta_check_회사PC_<시각>.md`를 전달합니다.", "",
             "Gemma가 질문하면 답해도 됩니다. 표시([ID])가 없는 메시지는 앞 요청에 이어진 대화로 채점합니다.", "",
             "## 묶음", ""]
    for g in spec["groups"]:
        name = f"{g['id']}_{g['title'].split(' (')[0].replace(' ', '_')}.md"
        index.append(f"- [{g['id']} {g['title']}]({name}): " + ", ".join(s["id"] for s in g["scenarios"]))
        body = [f"# {g['id']} {g['title']}", "", "## 하나씩 보내기", ""]
        for s in g["scenarios"]:
            body += [f"{s['id']}:", "", "```text", msg(s), "```", ""]
        body += ["## 한 번에 보내기", "", "```text",
                 "아래 요청을 순서대로 하나씩 처리해줘. 요청마다 결과를 짧게 알리고 다음 요청으로 넘어가. 중간에 막히면 그 요청만 건너뛰고 이유를 알려줘.", ""]
        body += [msg(s) for s in g["scenarios"]] + ["```", ""]
        with open(os.path.join(PACK_DIR, name), "w", encoding="utf-8") as f:
            f.write("\n".join(body))
    with open(os.path.join(PACK_DIR, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(index) + "\n")
    return PACK_DIR


def main():
    ap = argparse.ArgumentParser(description="OpenCode 대화 채점 / 메시지 팩 생성")
    ap.add_argument("--export", nargs="+", help="OpenCode에서 내보낸 대화 JSON (여러 개 가능)")
    ap.add_argument("--label", default="PC")
    ap.add_argument("--judge", action="store_true", help="사내 OpenAI 호환 API로 참고 점수 (JUDGE_BASE_URL)")
    ap.add_argument("--judge-model", default="LLM42")
    ap.add_argument("--make-pack", action="store_true", help="agent_scenarios.yaml로 docs/opencode/자동테스트 다시 만들기")
    ap.add_argument("--dir", help="메시지 팩의 시험 폴더 (기본: yaml의 dir)")
    args = ap.parse_args()
    if args.make_pack:
        print(f"[INFO] 메시지 팩 저장: {make_pack(args.dir)}")
        return 0
    if not args.export:
        ap.error("--export 또는 --make-pack 이 필요합니다")
    meta, rows, detail = grade(args.export, args.label, args.judge, args.judge_model)
    report, npass, n = write_report(args.label, meta, rows, detail)
    print(f"[STATUS] 통과 {npass} / {n} -> {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
