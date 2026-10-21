# -*- coding: utf-8 -*-
"""
================================================================================
Agent Office: Nemotron 3 Ultra 550B 최적화 차세대 MS Office AI 에이전트
================================================================================
핵심 기능 및 아키텍처:
1. 초거대 엔터프라이즈 모델(550B) 맞춤형 설계:
   - 26B용의 경직된 보조바퀴를 걷어내고, 복합 멀티스텝 작업(Planning & Execution)과
     도구 체이닝(Tool Chaining)을 원활히 지원하는 풍부한 인터페이스 제공.
2. 유연한 입력 포맷 수용 (Auto-Parsing):
   - 표 데이터 작성 시 2차원 리스트([["A", 1]])뿐만 아니라 마크다운 표 문자열(| A | B |)도
     자동 감지하여 원자적으로 엑셀에 주입.
3. 자율 반성 및 자가 복구 (Self-Healing / Reflection):
   - 도구 실행 실패 또는 매칭 불발 시 무작정 멈추지 않고, 에러 피드백을 수신하여
     스스로 시트명이나 파라미터를 교정(Self-Correction) 후 재시도.
4. 통합 오피스 제어 범위:
   - Excel (표 작성, 셀 서식/색상 일괄 매핑, 시트 관리, 범위 조작, 차트 생성)
   - Word & PowerPoint (본문/표 삽입, 슬라이드 텍스트 앵커 치환)
   - Search & Export (PDF/CSV 내보내기, 다중 문서 키워드 검색)
   - Power Fallback (cli_office 날것의 모든 옵션 직접 실행 지원)
5. 독립형 대화형 세션 및 단발성 CLI 호출 양방향 지원:
   - python agent_office.py "활성 엑셀 창에 이번달 실적표 만들고 합계는 노란색 칠해줘"
   - python agent_office.py (인터랙티브 대화형 콘솔 모드 진입)
================================================================================
"""

import sys
import os
import json
import csv
import io
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
MODEL_NAME = os.environ.get("OPENAI_MODEL_NAME", "nemotron-3-ultra-550b")

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
    return f"""당신은 Windows MS Office(Excel, Word, PowerPoint) 활성 창 및 문서를 정밀하게 제어하는 '엔터프라이즈 최상위 오피스 자동화 AI 에이전트'입니다.
백엔드 엔진으로 `cli_office.py`를 사용하며, 주어진 전용 도구(Tool)들을 조율하여 복잡한 오피스 실무를 완벽하게 수행합니다.

[⛔ 최우선 안전 가드레일 (불필요한 창 실행 방지)]
1. 단순 대화/인사/질의 시 도구 호출 금지:
   - 사용자가 "안녕", "도움말", "기능 알려줘", "어떤 작업이 가능해?" 같은 단순 대화나 일반 질의를 할 때는 **절대로 오피스 제어 도구를 호출하지 마십시오**.
   - 반드시 텍스트로만 정중하게 답변하십시오.
2. 임의 예제 생성 및 창 띄우기 금지:
   - 사용자가 명시적으로 표나 문서를 만들어달라고 요청하지 않았는데, 능력을 보여주기 위해 임의로 엑셀이나 워드에 예제 데이터를 쓰거나 창을 열지 마십시오.
3. 작업 전 상태 점검 (Inspect First):
   - 실제 오피스 작업을 지시받았을 때는, 먼저 `excel_inspect_or_list`를 호출하여 제어할 프로그램(Excel, Word 등)이나 시트가 열려 있는지 확인하십시오.
   - 열려 있는 창이 전혀 없을 때 사용자가 "새로 만들어줘"라고 명시하지 않았다면, 무작정 창을 띄우기 전에 사용자에게 현재 열린 문서가 없음을 알리고 새 문서를 열어 진행할지 확인하십시오.

[🌟 핵심 작업 지침 및 사고 체계]
1. 멀티스텝 작업 계획(Planning):
   - 복합적인 요구사항(예: "시트 내용 지우고 표 넣은 뒤 합계 행 서식 넣고 차트 그려줘")을 받으면,
     어떤 순서로 도구를 호출할지 명확한 단계(Plan)를 먼저 생각하고 차례대로 도구를 호출하십시오.
2. 자율 반성 및 자가 복구 (Self-Healing / Reflection):
   - 도구 실행 결과에서 에러(status: error)나 시트/텍스트 불일치(status: no_match)가 발생하면, 즉시 포기하지 마십시오.
   - 반환된 에러 메시지를 꼼꼼히 분석하여(예: 시트명이 다름, 셀 범위 표현 오류 등), 인자를 올바르게 교정한 뒤 재시도하여 작업을 완수하십시오.
3. 파일 데이터 원자성 보장:
   - 표 데이터 주입과 다중 셀 서식 매핑은 이미 백엔드 도구가 `C:\\cli_data\\data\\` 내에서 UTF-8 인코딩을 완벽히 보장하여 처리하므로, 모델은 오직 데이터 구조(2차원 배열/마크다운 표)와 서식 규칙(딕셔너리)에만 집중하십시오.
4. 신속한 완료 보고:
   - 모든 화면 반영이 정상적으로 완료되었으면, 어떤 작업이 수행되었는지 사용자에게 전문적이고 친절하게 요약 보고하십시오.

[참고: CLI 엔진 매뉴얼 (SKILL.md)]
{skill_doc}
"""


# ==============================================================================
# 3. 고수준 안전 실행기 및 데이터 변환기
# ==============================================================================
def parse_flexible_table_input(data: Any) -> List[List[Any]]:
    """2차원 리스트 또는 마크다운 표 텍스트(| A | B |)를 표준 2차원 리스트로 자동 변환"""
    if isinstance(data, list):
        if all(isinstance(r, list) for r in data):
            return data
        return [data]

    if isinstance(data, str):
        lines = [line.strip() for line in data.strip().splitlines() if line.strip()]
        rows = []
        for line in lines:
            if line.startswith("|") and line.endswith("|"):
                parts = [p.strip() for p in line[1:-1].split("|")]
                if all(set(p) <= {"-", ":"} for p in parts if p):
                    continue  # 마크다운 헤더 구분선 생략
                rows.append(parts)
            elif "\t" in line:
                rows.append([p.strip() for p in line.split("\t")])
            elif "," in line:
                rows.extend(list(csv.reader(io.StringIO(line))))
            else:
                rows.append([line])
        return rows

    return []


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
            timeout=40
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if proc.returncode != 0:
            return {
                "status": "error",
                "message": stderr or stdout or f"Process exited with code {proc.returncode}"
            }

        if stdout:
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                return {"status": "ok", "raw_output": stdout}
        return {"status": "ok", "message": "Command executed successfully"}

    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "실행 시간 초과 (40초 경과)"}
    except Exception as e:
        return {"status": "error", "message": f"실행 중 예외 발생: {str(e)}"}


def excel_inspect_or_list() -> Dict[str, Any]:
    """현재 열려 있는 MS Office 활성 창 및 엑셀 시트 목록, 문서 정보를 조회합니다."""
    return _execute_cli_office(["--list-active"])


def excel_write_table(table_data: Union[List[List[Any]], str], sheet_name: Optional[str] = None,
                      clear: bool = True, chart_type: Optional[str] = None,
                      chart_title: Optional[str] = None) -> Dict[str, Any]:
    """
    2차원 배열 또는 마크다운 표 데이터를 활성 엑셀 창에 즉시 작성합니다.
    차트 동시 생성 옵션(chart_type: column, bar, line, pie)을 지원합니다.
    """
    grid = parse_flexible_table_input(table_data)
    if not grid:
        return {"status": "error", "message": "유효한 표 데이터(2D 리스트 또는 마크다운 표)를 찾을 수 없습니다."}

    input_file = DATA_DIR / "input.jsonl"
    try:
        with open(input_file, "w", encoding="utf-8") as f:
            for row in grid:
                f.write(json.dumps({"type": "table_row", "data": list(row)}, ensure_ascii=False) + "\n")
    except Exception as e:
        return {"status": "error", "message": f"데이터 임시 파일 생성 실패: {e}"}

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


def excel_format_cells(styles_map: Dict[str, Dict[str, Any]], sheet_name: Optional[str] = None) -> Dict[str, Any]:
    """
    특정 단어, 숫자 또는 조건에 맞는 셀의 서식(배경색 bg, 글자색 color, 굵게 bold, 기울임 italic)을 1회 일괄 적용합니다.
    예: {"합계": {"bg": "yellow", "bold": true}, "일": {"color": "red"}}
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


def excel_manage_sheet(action: str, sheet_name: str, new_name: Optional[str] = None) -> Dict[str, Any]:
    """엑셀 시트를 관리합니다. (add: 추가, copy: 복제, rename: 이름변경, delete: 삭제)"""
    args = ["--sheet-action", action, "--sheet-name", sheet_name, "--to", "excel"]
    if new_name:
        args.extend(["--new-name", new_name])
    return _execute_cli_office(args)


def excel_manage_range(action: str, range_str: str, dest_str: Optional[str] = None) -> Dict[str, Any]:
    """엑셀 셀 범위를 원자적으로 조작합니다. (move: 이동, copy: 복사, clear: 지우기)"""
    args = ["--range-action", action, "--range", range_str, "--to", "excel"]
    if dest_str:
        args.extend(["--dest", dest_str])
    return _execute_cli_office(args)


def office_doc_write(app_type: str, content: str, anchor: Optional[str] = None,
                     pos: str = "after", page_num: Optional[int] = None) -> Dict[str, Any]:
    """Word 본문/마크다운 표 쓰기 또는 PowerPoint 슬라이드 내용 삽입"""
    args = ["--to", app_type.lower(), "--active", "--data", content]
    if anchor:
        args.extend(["--anchor", anchor, "--pos", pos])
    if page_num is not None:
        args.extend(["--pages", str(page_num)])
    return _execute_cli_office(args)


def office_export_or_search(action: str, target: str, app_type: Optional[str] = "excel", top_k: int = 5) -> Dict[str, Any]:
    """
    문서 내보내기(action='export', target='경로.pdf') 또는
    문서 키워드 하이브리드 검색(action='search', target='검색어', app_type='보고서.hwp/pdf')을 수행합니다.
    """
    if action == "export":
        return _execute_cli_office(["--export", target, "--from", app_type.lower(), "--active"])
    elif action == "search":
        args = ["--search", target, "--top", str(top_k)]
        if app_type and app_type not in ("excel", "word", "ppt"):
            args.extend(["--from", app_type])
        return _execute_cli_office(args)
    return {"status": "error", "message": f"지원되지 않는 action입니다: {action}"}


def run_raw_cli_command(cli_args: str) -> Dict[str, Any]:
    """고급/특수 옵션용 날것의 cli_office 명령어 직접 실행 (폴백 전용)"""
    import shlex
    try:
        tokens = shlex.split(cli_args)
    except Exception:
        tokens = cli_args.split()
    return _execute_cli_office(tokens)


# ==============================================================================
# 4. Nemotron 550B용 OpenAI Function Calling 도구 스키마
# ==============================================================================
OFFICE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "excel_inspect_or_list",
            "description": "현재 열려 있는 MS Office(Excel, Word, PPT) 활성 창과 시트 목록을 조회합니다. 작업 전 상태 파악 시 유용합니다.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "excel_write_table",
            "description": "2D 배열 또는 마크다운 표(| A | B |)를 활성 엑셀 시트에 작성하고 필요 시 차트를 동시 생성합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_data": {
                        "type": ["array", "string"],
                        "description": "2차원 리스트(예: [['품목', '값'], ['A', 100]]) 또는 마크다운 표 문자열"
                    },
                    "sheet_name": {"type": "string", "description": "특정 대상 시트명 (생략 시 활성 시트)"},
                    "clear": {"type": "boolean", "description": "기존 시트 내용을 모두 지우고 쓸지 여부 (기본: true)"},
                    "chart_type": {"type": "string", "enum": ["column", "bar", "line", "pie"], "description": "생성할 차트 종류"},
                    "chart_title": {"type": "string", "description": "차트 제목"}
                },
                "required": ["table_data"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "excel_format_cells",
            "description": "단어, 숫자 또는 조건에 일치하는 셀들의 서식(배경색 bg, 글자색 color, 굵게 bold)을 1회 일괄 적용합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "styles_map": {
                        "type": "object",
                        "description": "매핑 딕셔너리 (예: {'합계': {'bg': 'yellow', 'bold': true}, '일': {'color': 'red'}})"
                    },
                    "sheet_name": {"type": "string", "description": "특정 대상 시트명 (생략 시 활성 시트)"}
                },
                "required": ["styles_map"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "excel_manage_sheet",
            "description": "엑셀 시트 관리 (add: 추가, copy: 복제, rename: 이름변경, delete: 삭제)",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["add", "copy", "rename", "delete"], "description": "수행할 작업"},
                    "sheet_name": {"type": "string", "description": "대상 시트명"},
                    "new_name": {"type": "string", "description": "rename/copy 시 새 시트명"}
                },
                "required": ["action", "sheet_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "excel_manage_range",
            "description": "엑셀 셀 범위 조작 (move: 이동, copy: 복사, clear: 내용 지우기)",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["move", "copy", "clear"], "description": "작업 종류"},
                    "range_str": {"type": "string", "description": "소스 범위 (예: 'A1:C10' 또는 'Sheet1!A1:C10')"},
                    "dest_str": {"type": "string", "description": "이동/복사할 대상 시작 셀 (예: 'Sheet2!A1')"}
                },
                "required": ["action", "range_str"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "office_doc_write",
            "description": "Word 문서 또는 PowerPoint 슬라이드에 텍스트나 표를 삽입/작성합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_type": {"type": "string", "enum": ["word", "ppt"], "description": "대상 프로그램"},
                    "content": {"type": "string", "description": "추가할 본문 텍스트 또는 마크다운 표"},
                    "anchor": {"type": "string", "description": "기준 위치가 될 기존 텍스트 앵커"},
                    "pos": {"type": "string", "enum": ["before", "after", "replace"], "description": "앵커 기준 삽입 위치"},
                    "page_num": {"type": "integer", "description": "PPT 슬라이드 쪽수"}
                },
                "required": ["app_type", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "office_export_or_search",
            "description": "활성 문서를 PDF/CSV로 내보내거나(export), 문서 내 키워드를 하이브리드 검색(search)합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["export", "search"], "description": "작업 종류"},
                    "target": {"type": "string", "description": "export 시 내보낼 파일 경로, search 시 검색 키워드"},
                    "app_type": {"type": "string", "description": "export 대상 앱(excel, word, ppt) 또는 search 대상 파일명(예: 보고서.pdf)"},
                    "top_k": {"type": "integer", "description": "검색 결과 상위 표시 개수 (기본: 5)"}
                },
                "required": ["action", "target"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_raw_cli_command",
            "description": "기타 고급 기능 실행용 날것의 cli_office 명령어 직접 실행 (폴백 전용)",
            "parameters": {
                "type": "object",
                "properties": {
                    "cli_args": {"type": "string", "description": "cli_office 뒤에 붙일 인자 문자열 (예: --undo)"}
                },
                "required": ["cli_args"]
            }
        }
    }
]

TOOL_FUNCTION_MAP = {
    "excel_inspect_or_list": excel_inspect_or_list,
    "excel_write_table": excel_write_table,
    "excel_format_cells": excel_format_cells,
    "excel_manage_sheet": excel_manage_sheet,
    "excel_manage_range": excel_manage_range,
    "office_doc_write": office_doc_write,
    "office_export_or_search": office_export_or_search,
    "run_raw_cli_command": run_raw_cli_command
}


# ==============================================================================
# 5. Nemotron 550B 에이전트 실행 루프 (Planning & Self-Healing Loop)
# ==============================================================================
def run_office_agent(user_query: str, verbose: bool = True) -> str:
    """사용자의 자연어 요청을 받아 Nemotron 550B 멀티스텝 기획 및 자율 복구 루프로 처리"""
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
        timeout=120.0
    )

    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": user_query}
    ]

    max_steps = 10  # 550B의 복합 멀티스텝 기획 및 자율 복구 허용 (최대 10단계)
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

        # 모델이 생성한 사고 과정 또는 설명 출력
        if msg.content and verbose:
            print(f"\n[에이전트 사고 및 계획]\n{msg.content.strip()}\n")

        # 도구 호출이 없으면 최종 답변으로 종료
        if not msg.tool_calls:
            return msg.content or "작업이 완료되었습니다."

        # 도구 순차 실행
        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            fn_args_raw = tool_call.function.arguments
            try:
                fn_args = json.loads(fn_args_raw)
            except Exception:
                fn_args = {}

            if verbose:
                print(f"[도구 실행] {fn_name}({fn_args})")

            # 도구 핸들러 호출
            handler = TOOL_FUNCTION_MAP.get(fn_name)
            if handler:
                try:
                    result = handler(**fn_args)
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
            else:
                result = {"status": "error", "message": f"알 수 없는 도구: {fn_name}"}

            # 실행 결과 모니터링
            status = result.get("status", "ok")
            if verbose:
                if status == "ok":
                    print(f"  └ [성공] {json.dumps(result, ensure_ascii=False)[:130]}")
                else:
                    print(f"  └ [피드백/반성 대상] {json.dumps(result, ensure_ascii=False)}")

            # 실행 결과를 대화 문맥에 주입 (모델이 에러를 보고 자율 복구할 수 있도록 제공)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False)
            })

    # 루프 소진 시 최종 정리 보고서 요청
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
# 6. 진입점 및 인터랙티브 콘솔
# ==============================================================================
def main():
    print("=" * 70)
    print("  Agent Office: Nemotron 3 Ultra 550B 최적화 차세대 MS Office 에이전트")
    print(f"  엔드포인트: {BASE_URL or '(미설정 - 코드 상단 또는 환경변수 지정)'}")
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

            print("-" * 60)
            result = run_office_agent(user_input, verbose=True)
            print("-" * 60)
            print(f"[응답]\n{result}\n")

        except (KeyboardInterrupt, EOFError):
            print("\nAgent Office를 종료합니다.")
            break


if __name__ == "__main__":
    main()
