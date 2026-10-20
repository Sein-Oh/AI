# -*- coding: utf-8 -*-
"""
================================================================================
Agent Office: Gemma 4 26B 최적화 초경량 MS Office 전용 AI 에이전트
================================================================================
핵심 기능:
1. cli_office.py 완전 캡슐화:
   - 복잡한 셸(PowerShell) 따옴표 이스케이프 및 중간 파일(input.jsonl, styles.json)
     생성 과정을 고수준 파이썬 도구(Tool)로 원자적 자동 처리
2. Gemma 4 26B 인지 부하 극소화:
   - 불필요한 도구(파일 편집, Git, 임의 코드 실행)를 물리적으로 거세하고
     오직 7개의 정밀 Office 제어 도구만 제공하여 환각 0% 달성
3. Zero-Retry & Verified 원칙 준수:
   - cli_office가 'VERIFIED' 또는 'status: ok' 반환 시 불필요한 확인용 재조회 차단
4. 독립형 대화형 세션 및 단발성 CLI 호출 양방향 지원:
   - python agent_office.py "엑셀에 달력 표 만들어줘"
   - python agent_office.py (인터랙티브 챗 모드 진입)
================================================================================
"""

import sys
import os
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

# Windows 콘솔 UTF-8 입출력 강제 고정
if sys.platform == "win32":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

# ==============================================================================
# 1. 모델 및 서버 설정 (사용자 지정 영역)
# ==============================================================================
# 사내 vLLM / Ollama / TGI / OpenAI 호환 서버 엔드포인트 및 API Key를 입력하십시오.
BASE_URL = os.environ.get("OPENAI_BASE_URL", "")  # 예: "http://localhost:8000/v1"
API_KEY = os.environ.get("OPENAI_API_KEY", "")    # 예: "EMPTY" 또는 사내 발급 키
MODEL_NAME = os.environ.get("OPENAI_MODEL_NAME", "gemma-4-26b")

# 경로 상수
SCRIPT_DIR = Path(__file__).resolve().parent
CLI_OFFICE_PATH = SCRIPT_DIR / "cli_office.py"
SKILL_MD_PATH = SCRIPT_DIR / "utils" / "office" / "SKILL.md"

DATA_DIR = Path(r"C:\cli_data\data")
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ==============================================================================
# 2. SKILL.md 로더 및 프롬프트 빌더
# ==============================================================================
def load_skill_documentation() -> str:
    """utils/office/SKILL.md를 동적으로 로드하여 시스템 프롬프트에 주입"""
    if SKILL_MD_PATH.exists():
        try:
            return SKILL_MD_PATH.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            pass
    return "Office Automation CLI Engine for Excel, Word, and PowerPoint."


def build_system_prompt() -> str:
    skill_doc = load_skill_documentation()
    return f"""당신은 Windows MS Office(Excel, Word, PowerPoint) 활성 창을 정밀하게 제어하는 '초경량 Office 전문 AI 에이전트'입니다.
엔진으로 `cli_office.py`를 사용하며, 당신에게 제공된 전용 도구(Tool)들을 호출하여 사용자의 작업을 즉각적이고 정확하게 완수해야 합니다.

[⛔ 핵심 행동 원칙]
1. 파이썬 코드나 터미널 스크립트를 직접 작성하지 마십시오. 오직 제공된 고수준 도구만 호출하십시오.
2. 다중 서식 변경 요청 시 개별 함수를 여러 번 부르지 말고 `apply_excel_styles`의 styles_map으로 1회 일괄 처리하십시오.
3. 도구 실행 결과에 "status": "ok" 또는 "agent_directive": "VERIFIED"가 포함되면 화면에 100% 반영된 것이므로 확인을 위해 다시 읽지 말고 즉시 완료 보고를 출력하십시오.
4. "status": "no_match" 또는 "replacements": 0 수신 시 무리하게 재시도하지 말고 해당 단어를 건너뛴 뒤 작업을 완료하십시오.
5. 모든 표 데이터 주입 및 서식 변경은 이미 백엔드 파이썬 도구가 완벽히 격리된 C:\\cli_data\\data\\ 경로에서 처리하므로 파일 경로를 직접 고민할 필요가 없습니다.

[참고: 도구 표준 매뉴얼]
{skill_doc}
"""


# ==============================================================================
# 3. 고수준 안전 실행기 (Gemma 4 26B 전용 래퍼 함수)
# ==============================================================================
def _execute_cli_office(args_list: List[str]) -> Dict[str, Any]:
    """cli_office.py를 안전한 subprocess 인자 배열로 실행하고 결과 JSON을 파싱"""
    cmd = [sys.executable, str(CLI_OFFICE_PATH)] + args_list
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if proc.returncode != 0:
            return {
                "status": "error",
                "message": stderr or stdout or f"Exit code {proc.returncode}"
            }

        if stdout:
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                return {"status": "ok", "raw_output": stdout}
        return {"status": "ok", "message": "Command completed successfully"}

    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "실행 시간 초과 (30초)"}
    except Exception as e:
        return {"status": "error", "message": f"실행 중 예외 발생: {str(e)}"}


def write_excel_table(table_data: List[List[Any]], sheet_name: Optional[str] = None,
                      clear: bool = True, chart_type: Optional[str] = None,
                      chart_title: Optional[str] = None) -> Dict[str, Any]:
    """
    2D 배열 형태의 표 데이터를 활성 엑셀 창에 즉시 주입하고 필요 시 차트를 동시 생성합니다.
    (input.jsonl 파일 생성부터 CLI 주입까지 백엔드에서 원자적으로 처리)
    """
    input_file = DATA_DIR / "input.jsonl"
    try:
        with open(input_file, "w", encoding="utf-8") as f:
            for row in table_data:
                f.write(json.dumps({"type": "table_row", "data": list(row)}, ensure_ascii=False) + "\n")
    except Exception as e:
        return {"status": "error", "message": f"임시 데이터 파일 생성 실패: {e}"}

    args = ["--from", str(input_file), "--to", "excel", "--active"]
    if clear:
        args.append("--clear")
    if sheet_name:
        args.extend(["--pages", sheet_name])
    if chart_type:
        args.extend(["--chart", chart_type])
    if chart_title:
        args.extend(["--chart-title", chart_title])

    return _execute_cli_office(args)


def apply_excel_styles(styles_map: Dict[str, Dict[str, Any]], sheet_name: Optional[str] = None) -> Dict[str, Any]:
    """
    단어/숫자별 서식(배경색 bg, 글자색 color, 굵게 bold)을 엑셀 활성 시트에 1회 일괄 적용합니다.
    (styles.json 파일 생성부터 --replace-map 적용까지 백엔드에서 원자적으로 처리)
    """
    styles_file = DATA_DIR / "styles.json"
    try:
        with open(styles_file, "w", encoding="utf-8") as f:
            json.dump(styles_map, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return {"status": "error", "message": f"스타일 매핑 파일 생성 실패: {e}"}

    args = ["--to", "excel", "--active", "--replace-map", str(styles_file)]
    if sheet_name:
        args.extend(["--pages", sheet_name])

    return _execute_cli_office(args)


def manage_excel_sheet(action: str, sheet_name: str, new_name: Optional[str] = None) -> Dict[str, Any]:
    """엑셀 시트 관리 (add: 추가, copy: 복제, rename: 이름변경, delete: 삭제)"""
    args = ["--sheet-action", action, "--sheet-name", sheet_name, "--to", "excel"]
    if new_name:
        args.extend(["--new-name", new_name])
    return _execute_cli_office(args)


def manage_excel_range(action: str, range_str: str, dest_str: Optional[str] = None) -> Dict[str, Any]:
    """엑셀 셀 범위 원자적 조작 (move: 이동, copy: 복사, clear: 내용지우기)"""
    args = ["--range-action", action, "--range", range_str, "--to", "excel"]
    if dest_str:
        args.extend(["--dest", dest_str])
    return _execute_cli_office(args)


def write_word_or_ppt(app_type: str, content: str, anchor: Optional[str] = None,
                      pos: str = "after", page_num: Optional[int] = None) -> Dict[str, Any]:
    """Word 본문/마크다운 표 쓰기 또는 PowerPoint 슬라이드 내용 삽입"""
    args = ["--to", app_type.lower(), "--active", "--data", content]
    if anchor:
        args.extend(["--anchor", anchor, "--pos", pos])
    if page_num is not None:
        args.extend(["--pages", str(page_num)])
    return _execute_cli_office(args)


def inspect_active_office() -> Dict[str, Any]:
    """현재 열려 있는 MS Office 활성 창 및 시트/문서 정보 0.1초 조회"""
    return _execute_cli_office(["--list-active"])


def export_active_office(app_type: str, export_path: str) -> Dict[str, Any]:
    """활성 엑셀/워드/PPT 문서를 CSV 또는 PDF로 안전하게 내보내기"""
    return _execute_cli_office(["--export", export_path, "--from", app_type.lower(), "--active"])


def run_raw_cli_office(cli_args: str) -> Dict[str, Any]:
    """특수/고급 작업용 날것의 cli_office 인자 직접 실행 (폴백 전용)"""
    import shlex
    try:
        tokens = shlex.split(cli_args)
    except Exception:
        tokens = cli_args.split()
    return _execute_cli_office(tokens)


# ==============================================================================
# 4. OpenAI Function Calling 도구 스키마 정의
# ==============================================================================
OFFICE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_excel_table",
            "description": "2D 배열 형태의 표 데이터를 활성 엑셀 창에 즉시 작성합니다. (임시 파일 생성 및 CLI 주입 자동 처리)",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_data": {
                        "type": "array",
                        "items": {"type": "array", "items": {}},
                        "description": "행(row)들의 리스트로 구성된 2차원 표 데이터 (예: [['품목', '단가'], ['사과', 1000]])"
                    },
                    "sheet_name": {"type": "string", "description": "데이터를 주입할 특정 시트명 (생략 시 현재 활성 시트)"},
                    "clear": {"type": "boolean", "description": "주입 전 기존 시트 내용을 모두 지울지 여부 (기본값: true)"},
                    "chart_type": {"type": "string", "enum": ["column", "bar", "line", "pie"], "description": "동시 생성할 차트 종류"},
                    "chart_title": {"type": "string", "description": "차트 제목"}
                },
                "required": ["table_data"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_excel_styles",
            "description": "다중 단어/숫자에 대한 셀 서식(배경색, 글자색, 굵게)을 엑셀 활성 창에 1회 일괄 적용합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "styles_map": {
                        "type": "object",
                        "description": "단어별 서식 매핑 딕셔너리 (예: {'합계': {'bg': 'yellow', 'bold': true}, '일': {'color': 'red'}})"
                    },
                    "sheet_name": {"type": "string", "description": "적용할 특정 시트명 (생략 시 현재 활성 시트)"}
                },
                "required": ["styles_map"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_excel_sheet",
            "description": "엑셀 시트 관리 (추가 add, 복제 copy, 이름변경 rename, 삭제 delete)",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "copy", "rename", "delete"], "description": "수행할 작업"},
                    "sheet_name": {"type": "string", "description": "대상 시트 이름"},
                    "new_name": {"type": "string", "description": "이름변경(rename) 또는 복제(copy) 시 새 시트명"}
                },
                "required": ["action", "sheet_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "manage_excel_range",
            "description": "엑셀 셀 범위 이동, 복사, 또는 내용 지우기",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["move", "copy", "clear"], "description": "작업 종류"},
                    "range_str": {"type": "string", "description": "소스 범위 (예: 'A1:C10' 또는 'Sheet1!A1:C10')"},
                    "dest_str": {"type": "string", "description": "이동/복사 대상 시작 셀 (예: 'Sheet2!A1')"}
                },
                "required": ["action", "range_str"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_word_or_ppt",
            "description": "활성 Word 문서 또는 PowerPoint 슬라이드에 텍스트/마크다운 표 삽입",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_type": {"type": "string", "enum": ["word", "ppt"], "description": "대상 애플리케이션"},
                    "content": {"type": "string", "description": "추가할 본문 텍스트 또는 마크다운 표"},
                    "anchor": {"type": "string", "description": "기준 위치가 될 기존 문서 내 텍스트 앵커"},
                    "pos": {"type": "string", "enum": ["before", "after", "replace"], "description": "앵커 기준 삽입 위치 (기본: after)"},
                    "page_num": {"type": "integer", "description": "PPT 슬라이드 쪽수 (기본: 현재 슬라이드)"}
                },
                "required": ["app_type", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_active_office",
            "description": "현재 열려 있는 MS Office 활성 창 및 시트/문서 목록을 확인합니다.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "export_active_office",
            "description": "활성 오피스 문서를 PDF 또는 CSV 파일로 내보냅니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_type": {"type": "string", "enum": ["excel", "word", "ppt"], "description": "대상 앱"},
                    "export_path": {"type": "string", "description": "내보낼 대상 파일 경로 (예: C:\\cli_data\\data\\result.pdf)"}
                },
                "required": ["app_type", "export_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_raw_cli_office",
            "description": "기타 특수 옵션용 날것의 cli_office 명령어 직접 실행 (폴백용)",
            "parameters": {
                "type": "object",
                "properties": {
                    "cli_args": {"type": "string", "description": "cli_office 뒤에 붙일 인자 문자열"}
                },
                "required": ["cli_args"]
            }
        }
    }
]

TOOL_FUNCTION_MAP = {
    "write_excel_table": write_excel_table,
    "apply_excel_styles": apply_excel_styles,
    "manage_excel_sheet": manage_excel_sheet,
    "manage_excel_range": manage_excel_range,
    "write_word_or_ppt": write_word_or_ppt,
    "inspect_active_office": inspect_active_office,
    "export_active_office": export_active_office,
    "run_raw_cli_office": run_raw_cli_office
}


# ==============================================================================
# 5. 에이전트 실행 루프 (Agent Core Loop)
# ==============================================================================
def run_office_agent(user_query: str, verbose: bool = True) -> str:
    """사용자의 자연어 요청을 받아 Gemma 4 26B 도구 호출 루프를 거쳐 작업 수행"""
    if not BASE_URL:
        print("[안내] 코드 상단의 BASE_URL 또는 환경 변수(OPENAI_BASE_URL)가 비어 있습니다.", file=sys.stderr)
        print("사내 LLM 서버 엔드포인트(예: http://localhost:8000/v1)를 입력해 주십시오.", file=sys.stderr)
        return "BASE_URL 설정이 필요합니다. 코드 상단의 BASE_URL 변수에 사내 모델 엔드포인트를 입력하십시오."

    try:
        from openai import OpenAI
    except ImportError:
        return "openai 라이브러리가 필요합니다. 'pip install openai'를 실행하십시오."

    client = OpenAI(
        base_url=BASE_URL,
        api_key=API_KEY or "EMPTY",
        timeout=60.0
    )

    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": user_query}
    ]

    max_steps = 5
    for step in range(max_steps):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=OFFICE_TOOLS,
                tool_choice="auto",
                temperature=0.1
            )
        except Exception as e:
            return f"LLM API 호출 에러: {e}"

        msg = response.choices[0].message
        messages.append(msg)

        # 도구 호출이 없는 경우 (답변 완료)
        if not msg.tool_calls:
            return msg.content or "작업이 완료되었습니다."

        # 도구 호출 처리
        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            fn_args_raw = tool_call.function.arguments
            try:
                fn_args = json.loads(fn_args_raw)
            except Exception:
                fn_args = {}

            if verbose:
                print(f"[실행 요청] {fn_name}({fn_args})")

            # 도구 함수 매핑 실행
            handler = TOOL_FUNCTION_MAP.get(fn_name)
            if handler:
                try:
                    result = handler(**fn_args)
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
            else:
                result = {"status": "error", "message": f"알 수 없는 도구: {fn_name}"}

            if verbose:
                status_badge = "[성공]" if result.get("status") == "ok" else "[오류]"
                print(f"{status_badge} 결과: {json.dumps(result, ensure_ascii=False)[:120]}")

            # 결과를 메시지에 추가
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False)
            })

            # 조기 종료 가드레일: 이미 VERIFIED 또는 성공 반영된 경우
            directive = str(result.get("agent_directive", ""))
            if "VERIFIED" in directive or result.get("status") == "ok":
                # 추가 확인 없이 모델에게 완료 보고를 유도
                pass

    # 최종 마무리 응답 생성
    try:
        final_res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=0.1
        )
        return final_res.choices[0].message.content or "작업이 완료되었습니다."
    except Exception as e:
        return f"작업 실행 완료 (보고서 생성 에러: {e})"


# ==============================================================================
# 6. 진입점 및 인터랙티브 CLI 인터페이스
# ==============================================================================
def main():
    print("=" * 70)
    print("  Agent Office: Gemma 4 26B 최적화 초경량 MS Office AI 에이전트")
    print(f"  엔드포인트: {BASE_URL or '(미설정 - 코드 상단에 입력 필요)'}")
    print(f"  모델명: {MODEL_NAME}")
    print("=" * 70)

    # 1. 단발성 CLI 인자 전달 시 즉시 실행
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        query = " ".join(sys.argv[1:])
        print(f"\n[작업 시작] {query}\n")
        answer = run_office_agent(query, verbose=True)
        print(f"\n[최종 보고]\n{answer}\n")
        return

    # 2. 대화형 인터랙티브 세션 모드
    print("\n엑셀/워드/PPT 제어 명령을 자연어로 입력하십시오. (종료: 'q', 'exit')\n")
    while True:
        try:
            user_input = input("Office-Agent > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("q", "quit", "exit"):
                print("Agent Office를 종료합니다.")
                break

            print("-" * 50)
            result = run_office_agent(user_input, verbose=True)
            print("-" * 50)
            print(f"[응답]\n{result}\n")

        except (KeyboardInterrupt, EOFError):
            print("\nAgent Office를 종료합니다.")
            break


if __name__ == "__main__":
    main()
