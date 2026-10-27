# AI_WORK

AI 에이전트가 CLI 도구로 호출하는 **Agent-Computer Interface(ACI)** 툴킷 저장소입니다.
대상 환경: **Windows 11 폐쇄망, Python 3.13.13**, 26B~30B 경량 LLM 에이전트(스킬로 제공).
라이브러리 버전은 [`constraints.txt`](constraints.txt) / [`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md).

## 트리

```text
AI_WORK/
├── README.md                  # 저장소 안내 (본 문서)
├── CLAUDE.md                  # 이 저장소를 수정하는 AI 코딩 에이전트용 작업 규칙
├── pytest.ini                 # python -m pytest -> CLI/ 아래 모든 도구 테스트
├── constraints.txt            # 표준 사용자 환경 라이브러리 버전 고정
├── docs/
│   ├── ENVIRONMENT.md         # 표준 사용자 환경 정의 + 도구별 호환 현황
│   └── WINDOWS_OFFLINE.md     # 폐쇄망 wheel 반입/설치 가이드 (모든 도구 공통)
└── CLI/                       # 도구 모음 (도구 1개 = 폴더 1개)
    ├── README.md              # 도구 목록 + 새 도구 추가 규칙 / ACI 공통 계약
    └── ml_kit/                # 회귀 ML 툴킷
        ├── SKILL.md           # 에이전트용 스킬 (짧은 명령 템플릿 + 결과 처리 규칙)
        ├── README.md          # 상세 설명서
        ├── CHANGELOG.md / ROADMAP.md
        ├── requirements.txt / requirements-dev.txt / install_offline.bat
        ├── ml_common.py       # 공통 모듈 (로딩, 수치 변환, 수식 엔진, JSON 규약, Windows 파일 처리)
        ├── ml_train.py        # 1단계: 학습
        ├── ml_predict.py      # 2단계: 예측
        ├── ml_report.py       # 3단계: Word 보고서
        └── tests/             # CLI 계약 + 회귀 테스트
```

## 빠른 시작

```bash
pip install -r CLI/ml_kit/requirements-dev.txt
python -m pytest -q              # 전체 도구 테스트
```
폐쇄망 설치는 [`docs/WINDOWS_OFFLINE.md`](docs/WINDOWS_OFFLINE.md), 에이전트 연동은 각 도구의 `SKILL.md`.

## 관리 방법

1. **코드는 압축 파일 대신 평문 파일로 커밋** – diff/리뷰가 가능해야 합니다.
2. **CLI 인터페이스(인자 + stdout 1줄 JSON)는 공개 API** – 바꾸면 `SKILL.md`, `README.md`, `CHANGELOG.md`를 같이 갱신.
3. **작업 1건 = 브랜치 1개 = PR 1개**, 리팩터링과 동작 변경은 분리.
4. **모든 PR은 `python -m pytest` 통과가 조건.**
5. **배포 = 도구 폴더 복사** – `CLI/<tool>/` 폴더를 폐쇄망 PC의 스킬 폴더로 복사 (+ `wheels/`).
