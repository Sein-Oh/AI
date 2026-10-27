# AI_WORK

AI 에이전트가 CLI 도구로 호출하는 **Agent-Computer Interface(ACI)** 툴킷 저장소입니다.

| 디렉토리 | 내용 |
|---|---|
| [`ml_kit/`](ml_kit/) | 자율 회귀 ML 툴킷 (학습 / 추론 / Word 감사 보고서). 상세: [`ml_kit/README.md`](ml_kit/README.md) |
| [`tests/`](tests/) | CLI 계약(contract) 스모크 테스트 + 합성 샘플 데이터 생성기 |
| [`docs/`](docs/) | 개선 로드맵, 변경 이력 |

## 트리

```text
AI_WORK/
├── README.md              # 저장소 안내 (본 문서)
├── CLAUDE.md              # 이 저장소를 수정하는 AI 코딩 에이전트용 작업 규칙
├── requirements.txt       # 런타임 + 개발 의존성
├── .gitignore             # *_ml_data/, 예측 CSV, 보고서 등 런타임 산출물 제외
├── ml_kit/                # 에이전트가 호출하는 CLI 도구 (배포 단위)
│   ├── README.md          # 툴 사용 설명서 / 에이전트 스킬 명세 (ACI 문서)
│   ├── ml_train.py        # 1단계: 학습 엔진
│   ├── ml_predict.py      # 2단계: 추론 엔진
│   └── ml_report.py       # 3단계: Word 감사 보고서
├── tests/
│   ├── make_sample.py     # 결정적 합성 데이터셋 생성
│   └── test_cli_smoke.py  # train -> predict -> report 종단 테스트 (1줄 JSON 계약 검증)
└── docs/
    ├── ROADMAP.md         # 발견된 문제 / 개선 후보 백로그
    └── CHANGELOG.md       # 버전별 변경 이력
```

## 빠른 시작

```bash
pip install -r requirements.txt
python -m pytest -q tests        # 기준선 검증 (약 10초)
```

## 관리 방법

자세한 규칙은 [`CLAUDE.md`](CLAUDE.md) 참고. 요약:

1. **코드는 7z가 아니라 평문 파일로 커밋** – diff/리뷰/blame이 가능해야 개선 작업을 추적할 수 있습니다.
2. **CLI 인터페이스(인자 + stdout 1줄 JSON)는 공개 API** – 에이전트 프롬프트/스킬이 의존하므로 변경 시 `ml_kit/README.md`, `CHANGELOG.md`를 같이 갱신합니다.
3. **작업 1건 = 브랜치 1개 = PR 1개** – 리팩터링(동작 불변)과 기능 변경을 같은 PR에 섞지 않습니다.
4. **모든 PR은 `pytest tests` 통과가 조건** – 최적화 전후 동작이 같은지 테스트로 증명합니다.
