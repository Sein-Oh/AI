# CHANGELOG – ml-kit

이 문서는 2.0.0부터 관리합니다. 형식: 버전별 `구조 / 기능 / 호환` + 하단 `남은 할 일`.

## [2.1.0] - 2026-10-27

train/predict 완성 단계. CLI 인자와 기존 JSON 키는 모두 유지(추가만).

### 기능
- **범주형 피처**: 문자 컬럼(라인, 설비코드 등)을 자동 감지해 파이프라인 안에서 원-핫 인코딩.
  예측 시 학습 때 없던 범주는 `unseen_category_warning`. 종류가 너무 많은 ID형 컬럼은 `STOP_RETRY`.
- **날짜 피처**: Excel 날짜·`YYYY-MM-DD[ HH:MM]` 문자열을 연/월/일/요일/시 피처로 자동 분해.
  예측 시 학습 기간 밖 날짜는 외삽 경고.
- 피처 유형 판별 결과는 `feature_types`(결과 JSON·원장)와 `feature_schema`(모델 메타)에 기록. `--dtypes`로 강제 지정 가능.
- **선형 모델 자동 튜닝**: RidgeCV, ElasticNetCV, LogisticRegressionCV. 선택된 값은 리더보드 `params`.
- **회귀 예측 범위**: 챔피언 OOF 잔차 분위수 기반 90% 범위. 예측 컬럼 `pred_lo_<타겟>`, `pred_hi_<타겟>`, JSON `intervals`.
- **이진 분류 판정 기준**: `--positive-class <라벨>` 지정 시 양성 F1이 최대가 되는 확률 기준을 OOF로 찾아 저장·적용.
- **예측 입력 결측 경고**: 빈 값/숫자 아닌 값이 대치되면 `missing_input_warning`, `missing_input_counts`.
- **다음 명령 제공**: 결과 JSON `next_commands` (피처 제외 재학습, 교차항 추가, 목표 달성 시 예측·보고서 명령).
  피처가 15개를 넘으면 목록을 `vX/next_features_*.txt`로 저장해 경로로 전달.
- **동시 실행 잠금**: 같은 데이터에 학습이 겹치면 `STOP_RETRY` (OS 파일 잠금, 비정상 종료 시 자동 해제).

### 성능
- CSV: 구분자 자동 감지(`,` `;` 탭 `|`) 후 고속 C 파서 사용.
- 순열 중요도는 최대 5,000행 표본으로 계산. 1만 행 초과 시 RF/ET 트리마다 1만 행 표본, 5만 행 초과 시 KNN 제외.
- 측정 (이 개발 환경 4코어): 2만 행 × 20피처 80초 -> 46초(정확도 동일), 300행 × 150피처 39초 -> 11초.

### 원장 크기
- 피처가 30개를 넘으면 원장의 상관행렬은 중요도 상위 30개 + 타겟만 저장(`correlation_truncated: true`),
  전체 행렬은 `vX/correlation.csv`, 피처-타겟 상관은 `target_correlations`. (150피처 기준 기록 1건 370KB -> 31KB)

### 호환
- 2.1.0 이전 모델(`feature_schema` 없음)은 기존 수치 배열 방식으로 예측. 새 모델도 `ml_predict.py` 단독 실행 유지.

## [2.0.0] - 2026-10-27

### 구조
- `ml_common.py`를 `ml_predict.py`에 병합 (PART C: 공통 런타임). `.py` 파일 3개 구성.
- `ml_predict.py`는 다른 ml-kit 파일 없이 단독 실행됩니다. **배포 = `ml_predict.py` + `vX\` 폴더 복사.**
  `ml_train.py`, `ml_report.py`는 `ml_predict.py`에서 공통 기능을 import합니다.

### 기능
- **분류 학습** `ml_train.py --task classification` (기본값 `regression`, 사용자 지정).
  - 5개 모델: HistGradientBoosting, RandomForest, ExtraTrees, LogisticRegression, KNeighbors
  - Stratified K-Fold, 챔피언 = OOF Macro-F1 최고
  - 지표: Macro-F1, Accuracy, Balanced Accuracy, ROC-AUC, 혼동행렬, 클래스별 Precision/Recall/F1
  - 최소 클래스 비율 20% 미만이면 `class_weight='balanced'` 자동 적용 (`[WARN]`)
  - 라벨은 문자열로 정규화 (`1`, `1.0`, `"1"` -> `"1"`), 클래스별 최소 2개 미만이면 `STOP_RETRY`
- **분류 예측** `ml_predict.py`: 메타데이터의 `task`로 자동 분기.
  - 출력 컬럼 `pred_<타겟>`, `proba_<타겟>_<클래스>`, `conf_<타겟>`
  - JSON `predictions`, `probabilities`, `predicted_class_counts`, `low_confidence_warning`(확신도 0.6 미만)
- 결과 JSON/원장/메타/리더보드에 `task`, `primary_metric`, `mean_val_score`, `delta_score` 추가.
  성능 변화(`delta`)와 `is_best`는 같은 task 기록끼리만 비교.
- `--history`: Task/Score 표시, `best_by_task` 반환.
- `ml_report.py`: 분류 기록은 `STOP_RETRY`로 "다음 버전 지원" 안내 (회귀 보고서는 동일).

### 호환
- 회귀의 기존 키(`mean_val_r2`, `delta_r2`, `val_r2` 등)와 CLI 인자는 그대로 유지.
- `task` 키가 없는 1.x 모델/원장은 회귀로 처리.

### 스킬
- OpenCode Agent Skills 형식 적용: 스킬 이름 `ml-kit`, 폴더 이름도 `CLI/ml-kit/`로 변경 (OpenCode는 폴더명 = 스킬명 필수).
  frontmatter는 `name`, `description`, `license`, `compatibility`, `metadata`만 사용. 설치 방법은 README "OpenCode 스킬 설치".

### 문서
- 이전 이력 문서(ROADMAP 등)를 정리하고 이 CHANGELOG로 일원화. `requirements-dev.txt`, `install_offline.bat` 삭제.

## 남은 할 일
- [ ] 분류 Word 보고서 (혼동행렬, 클래스별 지표, 분류용 소견 5개)
- [ ] 회귀 Word 보고서 점검: 범주형/날짜 피처, 예측 범위, 잘린 상관행렬 반영
- [ ] `-x` 생략 시 피처 자동 선택 (ID/일련번호 배제 규칙)
- [ ] 무거운 import 지연 로딩 (`--history` 응답 속도)
- [x] Windows 실기 테스트 러너 `tools/run_win_tests.py` (M1~M14). 집 PC(Windows 11, Python 3.13.13, scikit-learn 1.9.0, Office 2007) 14개 모두 통과:
  Excel이 만든 보고서형 xlsx(제목/단위 행, 날짜 셀, 범주, 한글+공백 경로), Excel 저장 CP949 CSV, 입력 xlsx가 Excel에 열린 상태,
  결과 CSV를 Excel로 열 때 한글, 결과 CSV/보고서가 열려 잠긴 상태(새 이름 저장), 보고서를 Word로 열기,
  `next_commands`를 cmd.exe/PowerShell에 그대로 실행, 단독 배포 폴더, 2만 행(학습 10.6초, 예측 3.6초),
  동시 학습 잠금, 학습 강제 종료 뒤 복구, 오류/출력 계약.
- [ ] 회사 PC(WinPython, Office 16)에서 `tools/run_win_tests.py` 실행
- [ ] 260자 넘는 긴 경로
- [ ] 잠금 때문에 새 이름으로 저장할 때 이름에 시각이 두 번 붙음 (`_pred_<시각>_<시각>.csv`)
