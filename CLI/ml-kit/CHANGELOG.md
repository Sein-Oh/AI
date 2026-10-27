# CHANGELOG – ml-kit

첫 배포 버전 1.0.0부터 관리합니다. 형식: 버전별 변경 내용 + 하단 `남은 할 일`.

## [1.0.0] - 2026-10-27

첫 배포 버전.

### 학습 (`ml_train.py`)
- 회귀(`--task regression`, 기본)와 분류(`--task classification`). 후보 모델 5개 교차검증 경쟁, 챔피언은 OOF R² / Macro-F1 기준.
- 피처 유형 자동 판별: 수치, 범주(원-핫), 날짜(연·월·일·요일·시). ID형 문자 컬럼 거부, `--dtypes`로 강제 지정.
- 선형 모델 자동 튜닝(RidgeCV, ElasticNetCV, LogisticRegressionCV).
- 회귀 90% 예측 범위, 이진 분류 `--positive-class` 판정 기준 자동 조정, 불균형 시 class_weight 자동 적용.
- 단위 생략 컬럼명 자동 매칭, 오타 시 `[추천]`, 타겟 누수 차단, 안전한 파생변수 수식(`--eval`).
- 결과 JSON: `goal_met`, `recommendations`(가장 낮은 타겟 기준), 바로 실행 가능한 `next_commands`.
- 버전 폴더 원자적 저장, 실험 원장 `history.jsonl`(데이터 프로파일 포함), 교차검증 예측값 `oof_<타겟>.csv`.
- 동시 실행 잠금, 대용량 최적화(고속 CSV 파서, 중요도 표본 계산, 트리 표본 학습).

### 예측 (`ml_predict.py`)
- `ml_predict.py` + 버전 폴더만으로 단독 실행 (공통 런타임 내장).
- 회귀 예측 범위, 분류 확률·확신도, 경고 4종(외삽, 미학습 범주, 결측 대치, 저확신).

### 보고서 (`ml_report.py`)
- ML 결과 보고서(Word): 버전 폴더 하나의 모든 타겟을 문서 1개로. 회귀·분류 지원.
- 표지, 목차, 요약(판정), 데이터, 분석 방법, 타겟별 결과(차트), 버전 이력, 운영 가이드, 부록.
- 소견 자동 작성, `--slots`로 항목별 덮어쓰기.

### 에이전트 연동
- OpenCode 스킬(`SKILL.md`, 스킬 이름 `ml-kit`), stdout 1줄 JSON, `STOP_RETRY`/`ERROR` 지시어, 종료 코드 규약.
- Windows 대응: 파일 잠금 시 새 이름 저장, 재시도, 인코딩 자동 인식, CP949 CSV.

## 남은 할 일
- [ ] PC 실기 테스트 결과 반영 (`samples/PC_TEST.md`)
- [ ] 보고서 디자인 피드백 반영
- [ ] `-x` 생략 시 피처 자동 선택 (ID/일련번호 배제 규칙)
- [ ] 무거운 import 지연 로딩 (`--history` 응답 속도)
