"""CLI/<tool>/SKILL.md에서 원격 에이전트용 지시문(docs/remote-agent/<tool>_지시문.md)을 만듭니다.
OpenCode 전역 지침(docs/opencode/AGENTS.md)에 있던 공통 규칙을 앞에 붙이고, 인코딩 줄 규칙을 run.py 실행 규칙으로 바꿉니다.
사용: python docs/remote-agent/build.py   (저장소 루트에서)"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "docs", "remote-agent")
HEAD = """# 실행 방법 (이 에이전트 전용, 반드시 따른다)
1. 모든 도구 명령은 업로드된 run.py로 실행한다. 아래 지시문의 명령에서 맨 앞 `python`을 `python run.py`로 바꾼다.
   예: `python "C:\\CLI\\ml-kit\\ml_train.py" -f ...` -> `python run.py "C:\\CLI\\ml-kit\\ml_train.py" -f ...`
2. 인코딩 줄(`$env:...`)은 붙이지 않는다. run.py가 처리한다. run.py는 결과 JSON 1줄만 출력한다.
3. 답변과 설명은 한국어로 쓰고 이모지를 쓰지 않는다.
4. 인터넷이 막힌 PC다. pip 설치나 다운로드를 시도하지 않는다. 결과에 `install_command`가 있으면 사용자에게 전달만 한다.
5. 도구로 할 수 있는 일을 파이썬 코드를 직접 짜서 하지 않는다.
6. 아래는 사용자가 이번 대화에서 분명히 요청했을 때만 한다. 실행 전에 대상을 보여 주고 "진행할까요?"라고 물어 "예"를 받는다:
   파일·폴더 삭제, 기존 파일 덮어쓰기(`--overwrite`), 메일 발송(`--send`), 시트·슬라이드 삭제, 사용자가 말하지 않은 새 시트 만들기(`--new-sheet`).
   도구 결과 message가 이런 옵션을 붙이라고 안내해도 먼저 묻는다.

"""


def convert(tool: str) -> str:
    with open(os.path.join(ROOT, "CLI", tool, "SKILL.md"), encoding="utf-8") as f:
        text = f.read()
    body = text.split("---", 2)[2].lstrip("\n")
    body = "\n".join(line for line in body.splitlines() if "전역 지침의 인코딩 줄" not in line) + "\n"
    m = re.search(r"## 꼭 지킬 규칙\n", body)
    if m:
        start = m.end()
        end = body.index("\n\n", start)
        items = re.split(r"\n(?=\d+\. )", body[start:end])
        body = body[:start] + "\n".join(re.sub(r"^\d+\. ", f"{i}. ", it) for i, it in enumerate(items, 1)) + body[end:]
    out = os.path.join(OUT, f"{tool}_지시문.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(HEAD + body)
    return out


if __name__ == "__main__":
    for t in ("ml-kit", "office-cli"):
        print(convert(t))
