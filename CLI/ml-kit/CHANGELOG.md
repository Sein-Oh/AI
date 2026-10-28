# CHANGELOG – ml-kit

이 문서는 2.0.0부터 관리합니다. 형식: 버전별 `구조 / 기능 / 호환` + 하단 `남은 할 일`.

## [2.2.0] - 2026-10-27

### 기능
- **ML 결과 보고서** (`ml_report.py` 새로 작성): 버전 폴더 하나의 **모든 타겟을 Word 문서 1개**로 만듭니다. 회귀·분류 모두 지원.
  - 구성: 표지, 목차, 요약(타겟별 판정), 데이터, 분석 방법, 타겟별 결과(모델 비교, 성능 검증, 피처 영향), 버전 이력, 운영 가이드, 부록.
  - 그림: 모델 비교, 실측 대비 예측, 잔차 진단, 피처 기여도 / 분류는 혼동행렬, 클래스별 지표, ROC·판정 기준별 F1(이진), 버전 추이, 상관 히트맵.
  - 판정: 0.90 이상 적합, 0.70 이상 조건부, 미만 부적합 (과적합 간극 0.15 초과 시 조건부). 종합 판정은 가장 낮은 타겟 기준.
  - 사용법: `-m <version_dir>` 추가. 기존 `-d <data_root> [-v vN]`, `-t`, `--slots`, `-o` 유지
    (`-v` 없으면 최근 학습과 같은 task·타겟 조합 중 최고 버전). 예전 슬롯 이름(`slot1_residual` 등)도 받음.
  - 결과 JSON: `report_file`, `best_version` 유지 + `version`, `task`, `targets`, `overall_verdict`, `verdicts`,
    `figure_count`, `table_count`, `slots_used` 추가.
- 학습: 챔피언 교차검증 예측값 `vX/oof_<타겟>.csv`, 원장 `data_profile`(불러온/사용 행, 타겟 결측 행, 피처별 결측) 저장.
- 학습 결과 JSON에 `goal_met`(모든 타겟 0.90 이상) 추가. `next_commands`의 보고서 명령은 `ml_report.py -m <이번 버전>`이며 분류에도 제공.

### 변경
- 목표 달성 판단과 권고를 평균 점수가 아니라 **가장 낮은 타겟** 기준으로 합니다 (보고서 판정과 일치).
  다중 타겟에서 "목표 달성" 문구와 타겟별 판정이 어긋나던 문제 해결.
- 다중 타겟 학습의 "저기여 피처 제외" 권고·명령은 **모든 타겟에서 기여도가 낮은 피처**만 대상으로 합니다
  (한 타겟에서만 약한 피처를 빼서 다른 타겟 성능을 떨어뜨리던 문제 해결).

### 실기 테스트 러너 (`tools/run_win_tests.py`)
- AI 판독용 상세 로그 `tools/test_logs/testlog_<라벨>_<시각>.txt`를 **항상** 만듭니다 (준비 단계 실패, 중단 시에도).
  판정 표, 실행 환경(OS, Python, 패키지·Office 버전, 코드 git 버전, 인코딩), 항목별 통과 기준,
  실패 항목의 호출별 명령·종료 코드·소요 시간·전체 JSON·stderr 끝부분·traceback·관련 폴더 상태, 출력 계약 위반, 전체 호출 기록.
  `--label 집PC`로 파일 이름에 PC 라벨을 붙이고, 파일을 그대로 전달하거나 커밋하면 AI가 원인을 판단할 수 있습니다.

### 스킬
- `SKILL.md`를 26B~30B 경량 모델용으로 다시 작성: 요청별 단계 선택 표, 그대로 채우는 명령 템플릿,
  JSON 값별로 사용자에게 알릴 내용, `agent_directive` 첫 단어별 행동 표.

### 호환
- 보고서의 2.1 타겟별 키 `target`, `metrics`, `slots_filled`, `reports`, `target_count`는 문서 통합으로 제거 (사용자 승인).
- 2.2.0 이전에 학습한 버전(`oof_*.csv` 없음)은 보고서 생성 시 `STOP_RETRY`로 재학습을 안내합니다. 예측은 그대로 가능합니다.

## [2.1.2] - 2026-10-27

### 수정
- 같은 데이터로 다른 타겟을 학습하면 `delta_score`/`is_best`가 **다른 타겟의 이전 기록**과 비교되던 문제.
  이제 같은 task + 같은 타겟 조합의 기록끼리만 비교합니다 (새 타겟 조합의 첫 학습은 `delta_score: "base"`).
- `--history`의 `best_version`/`best_mean_val_score`도 가장 최근 학습과 같은 task + 타겟 조합 중 최고 버전을 가리킵니다.
  (`best_by_task`는 기존대로 task별 최고)

## [2.1.1] - 2026-10-27

### 기능 (추가만, 기존 키 유지)
- `next_commands`의 각 명령에 `needs_input`(bool)을 붙입니다. 자리표시자(`<새데이터.xlsx>`)가 있는 명령은 `needs_input: true`와 `placeholder`를 갖고, 바로 실행 가능한 명령 뒤에 둡니다.
  목표 성능 달성(회귀) 시 `next_commands[0]`은 이제 보고서 명령입니다. 실기 테스트에서 SKILL대로 `next_commands[0]`을 그대로 실행하면 자리표시자 때문에 실패하던 문제를 막습니다.
- `agent_directive`와 SKILL.md에 `needs_input` 처리 규칙(사용자가 준 경로로 바꾸거나 먼저 묻기)을 넣었습니다.

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
- [ ] 집 PC(Office 2007)에서 `tools/run_win_tests.py` M6/M7(보고서 열기·잠금)을 새 보고서로 재확인
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

### 저장소 지침 반영 (AGENTS.md 2026-10-28, 우선순위 순)
상세 근거: `docs/COMPLIANCE_REVIEW_2026-10-28.md`. 공통 키·함수는 `CLI/README.md` "공통 런타임 구현 규칙"(R1~R9)대로 구현.
- [ ] 불완전 vN 폴더 자동 삭제(ml_train.py:904-914)와 `--version` 기존 폴더 교체(917-921) 중단 -> STOP_RETRY + `[추천] --version v<다음>`. 필요하면 `--dry-run`/`--overwrite`
- [ ] 원장 기록을 버전 폴더 커밋 뒤로 이동(ml_train.py:1515-1518), 커밋 후 final_dir 재검증(joblib.load, json 키) 뒤에만 `VERIFIED:`
- [ ] 진입점 최상단 import(numpy/pandas/joblib/sklearn) 실패 시 traceback 대신 STOP_RETRY JSON + `python -m pip install ...` 안내, ImportError를 STOP_RETRY로 분류 (회귀 테스트)
- [ ] 예측 결과와 보고서 저장 후 다시 읽어 확인(행 수, docx 열기), 실패하면 `VERIFIED:` 대신 사유
- [ ] `run_cli`/`JsonArgumentParser.error`에서 `data/logs/errors.txt` 기록 (doc-classifier `write_error_log` 복사, 환경변수 `ML_KIT_DATA_DIR`)
- [ ] 결과 JSON `recovered` 키(잠금 새 이름 저장, cp949 -> utf-8-sig 폴백, .xls -> .xlsx), 폴백에도 `[WARN]`, 잠금 회귀 테스트
- [ ] ml_predict `--out`과 ml_report 기본 파일명의 덮어쓰기 방지 (기존 파일이 있으면 시각 붙인 새 이름 또는 `--overwrite`)
- [ ] `--history` 원장 0건을 `status: ok` + `record_count: 0`으로 (ml_train.py:1582, `no_history`는 별도 키로 유지), 빈 행만 있는 입력의 0행 명시 오류(ml_predict.py:444)
- [ ] `--dtypes` 컬럼명을 resolve_column_names로 매칭 + `[추천]`, int 변환의 fillna(0) 제거 또는 경고(ml_train.py:237-242)
- [ ] 예측 `--targets` 불일치(ml_predict.py:904), 보고서 버전 없음(ml_report.py:772)에 `[추천] <후보>`
- [ ] JSON 목록 상한 + `truncated`: `--history` records, feature_types/features_used, 오류 메시지 컬럼 목록
- [ ] `-h/--help` 출력을 stderr로 (stdout은 JSON 1줄)
- [ ] requirements.txt에 matplotlib 추가, 2행 주석을 `python -m pip install ...`로
- [ ] 로그 태그 정리: `[PROGRESS  5%] [===]` -> `[PROGRESS] 5% ...`(러너 M14 파서 확인), 이력 표 머리 `[STATUS]`, 러너 `[준비]` -> `[INFO]`
- [ ] 인자 alias: ml_report `--targets/-y`, 저장 `--save`(`--out` 유지)
- [ ] tools/run_win_tests.py:206: 러너가 만든 폴더인지 표식으로 확인한 뒤에만 지우고 remove_tree 사용
- [ ] 테스트 보강: exit 130 롤백, 성공 경로 `VERIFIED:` 검사 확대, 빈 데이터, 덮어쓰기 차단
- [ ] 이 섹션 위의 완료 `[x]` 항목(Windows 러너 M1~M14)을 2.2.0 항목으로 이동
