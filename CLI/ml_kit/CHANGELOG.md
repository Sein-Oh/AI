# CHANGELOG – ml_kit

이 문서는 2.0.0부터 관리합니다. 형식: 버전별 `구조 / 기능 / 호환` + 하단 `남은 할 일`.

## [2.0.0] - 2026-10-27

### 구조
- `ml_common.py`를 `ml_predict.py`에 병합 (PART C: 공통 런타임). `.py` 파일 3개 구성.
- `ml_predict.py`는 다른 ml_kit 파일 없이 단독 실행됩니다. **배포 = `ml_predict.py` + `vX\` 폴더 복사.**
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

### 문서
- 이전 이력 문서(ROADMAP 등)를 정리하고 이 CHANGELOG로 일원화. `requirements-dev.txt`, `install_offline.bat` 삭제.

## 남은 할 일
- [ ] 분류 Word 보고서 (혼동행렬, 클래스별 지표, 분류용 소견 5개)
- [ ] `-x` 생략 시 수치형 피처 자동 선택 (ID/일련번호 배제 규칙)
- [ ] `recommendations`를 바로 실행 가능한 `next_command`로 제공
- [ ] 같은 데이터 동시 실행 시 버전 번호 충돌 잠금
- [ ] 무거운 import 지연 로딩 (`--history` 응답 속도)
- [ ] 대용량 데이터 순열 중요도 샘플링
- [ ] Windows 실기 테스트 (파일 잠금, 긴 경로, cmd/PowerShell 인자 전달)
