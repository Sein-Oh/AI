# AGENTS.md – AI_WORK 저장소에서 작업하는 모든 AI 에이전트용 규칙

OpenCode, Claude Code(CLAUDE.md가 이 파일을 불러옴) 등 이 저장소에서 작업하는 모든 에이전트가 따르는 단일 원본입니다.

## 저장소 성격
- `CLI/<tool>/` 의 스크립트는 **Windows 11 폐쇄망에서 26B~30B 경량 LLM 에이전트가 스킬로 호출하는 CLI 도구**입니다.
- 소비자는 사람이 아닌 경량 LLM입니다. 출력 형식의 작은 변화도 에이전트를 깨뜨립니다.
- 설계 원칙: **LLM 개입 최소화** – 판단은 도구가 하고, LLM은 명령 1회 실행 + JSON 1줄 해석만 한다.

## 사용자 환경 (모든 작업의 전제)
| 항목 | 값 |
|---|---|
| OS | Windows 11, **폐쇄망** (런타임 인터넷 접근 불가) |
| Python | **WinPython**, Python 3.13.13, 시스템 PATH 등록 |
| 실행 명령 | `python`, `python -m pip` 만 사용 (`py`, `python3`, 단독 `pip` 금지) |
| 에이전트 | **OpenCode** + 26B~30B 경량 LLM, 도구는 OpenCode 스킬로 제공 |
| 주요 라이브러리 | pandas 3.0.5, scikit-learn 1.9.0, scipy 1.18.1, numpy/joblib(의존성), openpyxl 3.1.5, python-docx 1.2.0, python-pptx 1.0.2, matplotlib 3.11.1, seaborn 0.13.2, pymupdf 1.28.2, opencv-python 5.0.0.93, PyYAML 6.0.3, python-dateutil 2.9.0.post0, pywin32 312, pytest 9.1.1, pymupdf4llm 1.28.2, fastapi 0.141.1, fastmcp 3.4.7, mcp 1.28.1, langgraph 1.2.11, openai 2.54.0 |
| 버전 기준 | 루트 `constraints.txt` (전체 목록). 상세 설명: `docs/ENVIRONMENT.md` |

- 목록 외 패키지도 대부분 설치되어 있고, Python 3.13 / win_amd64 wheel로 추가 설치 가능.
- 환경이 바뀌면 이 표, `constraints.txt`, `docs/ENVIRONMENT.md` 세 곳을 함께 갱신한다.

## 반드시 지킬 ACI 계약 (상세: CLI/README.md)
1. stdout은 정확히 1줄 JSON. 진행 로그·표·경고는 전부 stderr.
2. exit 0 = ok, 1 = error, 2 = 인자 오류, 130 = 중단. 에러 시 `agent_directive`는 `STOP_RETRY:` 또는 `ERROR:`.
   - ml-kit: 모든 진입점은 `run_cli()` + `JsonArgumentParser` 사용 (공통 런타임은 `ml_predict.py` PART C).
3. 이모지/원문자 금지. 로그 태그는 `[INFO] [PROGRESS] [WARN] [ERROR] [STATUS]`.
4. 기존 CLI 인자·JSON 키는 삭제/의미 변경 금지 (추가는 OK). 바꿔야 하면 alias 유지.
5. 산출물 레이아웃(`<stem>_ml_data/history.jsonl`, `vX/model_<target>.joblib|json`)과 원장 스키마는 하위 호환.
   - 규칙 4, 5는 각 도구의 **1.0.0 첫 배포 이후**부터 적용한다. 첫 배포 전에는 불편한 인터페이스를 자유롭게 정리한다.
6. 학습과 추론이 같아야 하는 로직(데이터 로딩, 수치 변환, `--eval` 수식)은 `ml_predict.py` PART C 한 곳에만 둔다.
   `ml_predict.py`는 다른 ml-kit 파일을 import하지 않는다 (모델 폴더와 함께 단독 배포). `ml_train.py`/`ml_report.py`가 `ml_predict.py`를 import한다.

## 폐쇄망 / Windows 제약
- 런타임 네트워크 접근 금지. 새 의존성은 win_amd64 wheel이 있는 순수 pip 패키지만, `requirements.txt`에 추가.
- 파일 저장은 잠금(Excel/Word) 대비 `save_with_lock_fallback`, 폴더 조작은 `retry_fs`/`remove_tree` 사용.
- 텍스트 입력 파일은 `read_text_file`(UTF-8/BOM/UTF-16/CP949 자동)로 읽는다.
- 대상 환경: Windows 11 + WinPython (Python 3.13.13, PATH 등록) + `constraints.txt`의 라이브러리 버전 (상세: docs/ENVIRONMENT.md).
- 명령 예시·스킬·배치 파일은 `python` 으로 호출한다 (`py`, `python3`, 단독 `pip` 금지 → `python -m pip`).
- 새 기능/도구는 표준 환경 라이브러리를 우선 사용. 없는 패키지는 Python 3.13 wheel이 있는 것만, ENVIRONMENT.md와 constraints.txt에 기록하고 미설치 시 JSON 오류로 안내.
- 테스트는 `constraints.txt` 버전 기준으로 통과해야 한다.

## 작업 절차
1. 변경 전 `python -m pytest -q`로 기준선 확인.
2. 리팩터링(동작 불변)과 기능 변경은 별도 커밋/PR.
3. 버그 수정에는 회귀 테스트 추가. 동작이 바뀌면 `SKILL.md`, `README.md`, `CHANGELOG.md` 갱신.
4. 남은 할 일은 각 도구 `CHANGELOG.md` 하단 "남은 할 일"에서 관리 (처리 시 해당 버전 항목으로 이동).
5. `SKILL.md`는 경량 LLM 컨텍스트에 들어가므로 짧게 유지 (상세는 README.md).
6. 스킬은 OpenCode 형식: 도구 폴더명 = frontmatter `name` (`^[a-z0-9]+(-[a-z0-9]+)*$`), frontmatter는 name/description/license/compatibility/metadata만.
