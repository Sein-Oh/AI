# CHANGELOG – ml-kit

이 문서는 2.0.0부터 관리합니다. 형식: 버전별 `구조 / 기능 / 호환` + 하단 `남은 할 일`.

## [2.3.0] - 2026-10-28

저장소 지침(AGENTS.md "JIT 자가복구" 3번: 덮어쓰기·삭제는 사용자 확인 필요) 반영 1차. 근거: `docs/COMPLIANCE_REVIEW_2026-10-28.md` 2절.
구현은 `CLI/README.md` "공통 런타임 구현 규칙" R1(사후 확인), R3(`recovered`), R4(덮어쓰기 방지).

### 수정 (사용자 확인 없이 지우거나 덮어쓰던 동작)
- 학습 시작 시 `leaderboard.json`/`model_dataset.csv`가 없는 `vN` 폴더를 **통째로 지우던** 동작을 없앴습니다.
  이제 지우지 않고 `[WARN]`과 결과 JSON `incomplete_versions`로 알리며, 자동 버전 번호는 그 번호를 건너뜁니다.
  도구가 만든 임시 폴더 `.tmp_*`만 계속 자동 청소합니다.
- `--version`에 이미 있는 버전을 주면 **아무 말 없이 교체하던** 동작을 막았습니다.
  `STOP_RETRY` + `[추천] --version v<다음>`을 내고, 교체는 새 인자 `--overwrite`가 있을 때만 합니다.
  교체 중에는 기존 폴더를 `.bak_vX`로 보관했다가 새 버전이 원장에 기록된 뒤에 지우며, 실패·중단 시 되돌립니다
  (프로세스가 죽어 남은 `.bak_vX`는 다음 학습 때 `vX`가 없으면 복원).
- 원장(`history.jsonl`) 기록을 버전 폴더 커밋 **뒤로** 옮겼습니다. 커밋이 실패하면 원장에 없는 버전이 남지 않고,
  원장 기록이 실패하면 방금 만든 버전 폴더를 롤백합니다.
  `history.jsonl`에 한 줄이 기록되는 즉시 그 버전을 확정하므로, 이후 `history.json` 동기화 중에 중단돼도 폴더를 지우거나 되돌리지 않습니다
  (원장과 폴더가 항상 일치).
- `--overwrite` 교체 시 이전 덮어쓰기의 백업 `.bak_vX`가 남아 있으면 지우지 않고 `STOP_RETRY`로 멈춥니다 (유일한 정상본일 수 있음).
- `ml_predict.py --out`의 파일이 이미 있으면 덮어쓰던 동작, `ml_report.py`가 같은 이름(`ML결과보고서_<데이터>_<버전>.docx`)의
  기존 보고서를 덮어쓰던 동작을 막았습니다. 시각을 붙인 새 이름으로 저장하고 `recovered`에 적습니다. 덮어쓰기는 새 인자 `--overwrite`.
- 실기 러너 `tools/run_win_tests.py`가 `--dir` 폴더를 확인 없이 `rmtree` 하던 동작을 막았습니다.
  러너가 만든 폴더(표식 파일 `.created_by_ml-kit-tests`)나 빈 폴더만 비우고, 다른 폴더면 지우지 않고 준비 단계 오류로 멈춥니다.
- 잠금 때문에 새 이름으로 저장할 때 이름에 시각이 두 번 붙던 문제 (`_pred_<시각>_<시각>.csv`): 기존 시각을 바꿔 붙입니다.
  같은 초에 같은 이름이 있으면 `_2`를 붙여 기존 파일을 덮지 않습니다.

### 기능 (추가만)
- 학습 결과 JSON `verified`: 커밋 후 버전 폴더를 다시 읽어 확인(leaderboard, 데이터 스냅샷, 모델 다시 load, 메타, 원장 마지막 기록).
  확인 실패 시 `verified: false`, `unverified` 사유 목록, `agent_directive`는 `UNVERIFIED:`.
- 모든 도구 결과 JSON `recovered` (있을 때만): 결과가 달라진 자동 복구 문구 목록. 공통 런타임 `note_recovered()`가 stderr `[WARN]`과 함께 모읍니다.
  이번 버전에서 기록하는 것: 기존 파일 덮어쓰기 회피, 잠긴 파일 새 이름 저장.
- 새 인자 `--overwrite`: `ml_train.py`(기존 버전 교체), `ml_predict.py`(`--out` 덮어쓰기), `ml_report.py`(같은 이름 보고서 덮어쓰기).
- SKILL.md: `UNVERIFIED:` 행동, `recovered` 전달, `--overwrite`는 사용자가 허락했을 때만 붙이는 규칙.

### 실기 테스트 러너
- M5/M7은 `--overwrite`를 주고 잠긴 파일을 덮어쓰려 할 때 새 이름 저장 + `recovered`의 '잠김'을 확인합니다
  (덮어쓰기 방지 때문에 잠금 경로가 검사되지 않는 것을 막음).
- 이전 러너가 만든 `C:\ml_test\ml 테스트`에는 표식 파일이 없으므로, 처음 한 번은 그 폴더를 직접 지우거나 다른 `--dir`을 주세요.

### 호환
- 기존 CLI 인자와 JSON 키는 그대로입니다. 다만 위 세 경우(이미 있는 `--version`, 이미 있는 `--out` 파일, 같은 이름 보고서)는
  기존처럼 교체·덮어쓰기하려면 `--overwrite`를 붙여야 합니다 (지침의 "덮어쓰기는 `--overwrite`가 있을 때만", R4).

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

### 저장소 지침 반영 (AGENTS.md 2026-10-28, 우선순위 순)
상세 근거: `docs/COMPLIANCE_REVIEW_2026-10-28.md`. 공통 키·함수는 `CLI/README.md` "공통 런타임 구현 규칙"(R1~R9)대로 구현.
- [ ] 진입점 최상단 import(numpy/pandas/joblib/sklearn) 실패 시 traceback 대신 STOP_RETRY JSON + `python -m pip install ...` 안내, ImportError를 STOP_RETRY로 분류 (회귀 테스트)
- [ ] 예측 결과와 보고서 저장 후 다시 읽어 확인(행 수, docx 열기), 실패하면 `VERIFIED:` 대신 사유
- [ ] `run_cli`/`JsonArgumentParser.error`에서 `data/logs/errors.txt` 기록 (doc-classifier `write_error_log` 복사, 환경변수 `ML_KIT_DATA_DIR`)
- [ ] `recovered` 나머지: cp949 -> utf-8-sig 폴백, .xls -> .xlsx 저장 (잠금 새 이름 저장과 덮어쓰기 회피는 2.3.0), 폴백에도 `[WARN]`
- [ ] `--history` 원장 0건을 `status: ok` + `record_count: 0`으로 (ml_train.py:1582, `no_history`는 별도 키로 유지), 빈 행만 있는 입력의 0행 명시 오류(ml_predict.py:444)
- [ ] 파괴적 작업 미리보기 `--dry-run` (R8): 학습 `--overwrite`, 예측·보고서 `--overwrite` 대상
- [ ] `--overwrite`로 버전을 교체하면 원장에 같은 version 기록이 2개 생김: `ml_report -d` 최고 버전 선택과 `is_best` 비교가 옛 기록을 볼 수 있음 (교체 표시 또는 마지막 기록 우선)
- [ ] `--dtypes` 컬럼명을 resolve_column_names로 매칭 + `[추천]`, int 변환의 fillna(0) 제거 또는 경고(ml_train.py:237-242)
- [ ] 예측 `--targets` 불일치(ml_predict.py:904), 보고서 버전 없음(ml_report.py:772)에 `[추천] <후보>`
- [ ] JSON 목록 상한 + `truncated`: `--history` records, feature_types/features_used, 오류 메시지 컬럼 목록
- [ ] `-h/--help` 출력을 stderr로 (stdout은 JSON 1줄)
- [ ] requirements.txt에 matplotlib 추가, 2행 주석을 `python -m pip install ...`로
- [ ] 로그 태그 정리: `[PROGRESS  5%] [===]` -> `[PROGRESS] 5% ...`(러너 M14 파서 확인), 이력 표 머리 `[STATUS]`, 러너 `[준비]` -> `[INFO]`
- [ ] 인자 alias: ml_report `--targets/-y`, 저장 `--save`(`--out` 유지)
- [ ] 테스트 보강: exit 130 롤백, 성공 경로 `VERIFIED:` 검사 확대, 빈 데이터 (덮어쓰기 차단은 2.3.0)
- [ ] 이 섹션 위의 완료 `[x]` 항목(Windows 러너 M1~M14)을 2.2.0 항목으로 이동
