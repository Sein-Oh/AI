# AI_WORK

AI 에이전트가 CLI 도구로 호출하는 **Agent-Computer Interface(ACI)** 툴킷 저장소입니다.
대상 환경: **Windows 11 폐쇄망, WinPython (Python 3.13.13, PATH 등록)**, 26B~30B 경량 LLM 에이전트(스킬로 제공).
라이브러리 버전은 [`constraints.txt`](constraints.txt) / [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md).

## 트리

```text
AI_WORK/
├── README.md                  # 저장소 안내 (본 문서)
├── AGENTS.md                  # 에이전트 공통 규칙 + 사용자 환경 (단일 원본, OpenCode가 자동으로 읽음)
├── CLAUDE.md                  # @AGENTS.md 한 줄 (Claude Code용)
├── opencode.json              # OpenCode가 docs/ENVIRONMENT.md도 함께 읽도록 설정
├── pytest.ini                 # python -m pytest -> CLI/ 아래 모든 도구 테스트
├── constraints.txt            # 표준 사용자 환경 라이브러리 버전 고정
├── docs/
│   ├── ENVIRONMENT.md         # 표준 사용자 환경 정의 + 도구별 호환 현황
│   └── WINDOWS_OFFLINE.md     # 폐쇄망 wheel 반입/설치 가이드 (모든 도구 공통)
└── CLI/                       # 도구 모음 (도구 1개 = 폴더 1개)
    ├── README.md              # 도구 목록 + 새 도구 추가 규칙 / ACI 공통 계약
    └── ml-kit/                # 회귀·분류 ML 툴킷 (2.1.0)
        ├── SKILL.md           # 에이전트용 스킬 (짧은 명령 템플릿 + 결과 처리 규칙)
        ├── README.md          # 상세 설명서
        ├── CHANGELOG.md       # 변경 이력 + 남은 할 일 (2.0.0부터 관리)
        ├── requirements.txt
        ├── ml_train.py        # 1단계: 학습
        ├── ml_predict.py      # 2단계: 예측 (단독 배포 가능) + 공통 런타임
        ├── ml_report.py       # 3단계: Word 보고서
        └── tests/             # CLI 계약 + 회귀 테스트
    └── atomic-cli/            # Office(Excel/Word/PPT/Outlook) COM 자동화 마이크로 CLI 모음 (Phase 1 정비 중)
        ├── README.md          # 상세 설명서 (구버전, 재작성 예정)
        ├── WORK_PLAN.md       # 오류 수정/최적화/고도화 작업계획 + 진행 현황
        ├── TEST_CHECKLIST.md  # Windows 실기 테스트 체크리스트
        ├── *.py               # 도구 진입점(excel_*, word_*, ppt_*, outlook_*, ...) + 공통 모듈(_*.py)
        ├── tools/             # merge_code.py(반출용 merged_code.md 생성/분리), run_win_tests.py(실기 테스트 러너)
        └── tests/             # 가짜 COM 기반 오프라인 테스트
```

## 빠른 시작

```bash
python -m pip install -r CLI/ml-kit/requirements.txt -c constraints.txt
python -m pytest -q              # 전체 도구 테스트
```
폐쇄망 설치는 [`docs/WINDOWS_OFFLINE.md`](docs/WINDOWS_OFFLINE.md), 에이전트 연동은 각 도구의 `SKILL.md`.

## 관리 방법

1. **코드는 압축 파일 대신 평문 파일로 커밋** – diff/리뷰가 가능해야 합니다.
2. **CLI 인터페이스(인자 + stdout 1줄 JSON)는 공개 API** – 바꾸면 `SKILL.md`, `README.md`, `CHANGELOG.md`를 같이 갱신.
3. **작업 1건 = 브랜치 1개 = PR 1개**, 리팩터링과 동작 변경은 분리.
4. **모든 PR은 `python -m pytest` 통과가 조건.**
5. **배포 = 도구 폴더 복사** – `CLI/<tool>/` 폴더를 폐쇄망 PC의 스킬 폴더로 복사.
   ml-kit 예측만 배포할 때는 `ml_predict.py` + 학습된 `vX\` 폴더 2가지만 복사하면 됩니다.
