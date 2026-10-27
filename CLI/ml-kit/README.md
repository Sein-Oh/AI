# ml-kit 1.0.0

표(Excel/CSV) 데이터로 **회귀(수치 예측)·분류(범주 예측)** 모델을 학습하고, 새 데이터를 예측하고, **ML 결과 보고서(Word)** 를 만드는 CLI 도구입니다.
Windows 11 폐쇄망에서 OpenCode + 26B~30B 경량 LLM이 스킬로 호출하도록 설계했습니다. 에이전트용 요약은 [`SKILL.md`](SKILL.md)에 있습니다.

**설계 원칙**
- **LLM 개입 최소화**: 데이터 정제, 피처 유형 판별, 모델 선택, 다음 명령 구성까지 도구가 판단합니다. 에이전트는 명령 1회 실행 후 JSON 1줄을 읽습니다.
- **정직한 평가**: 모든 성능 수치는 교차검증 예측(OOF) 기준이며, 전처리는 fold마다 학습 데이터로만 적합합니다.
- **재현과 추적**: 학습할 때마다 버전 폴더(`v1`, `v2`, ...)와 실험 원장(`history.jsonl`)에 기록합니다.
- **단독 배포**: `ml_predict.py` 1개 + 버전 폴더만으로 예측이 가능합니다.

---

## 1. 구성

```text
ml-kit/
├── SKILL.md            OpenCode 스킬 (에이전트용 사용법)
├── README.md           본 문서
├── CHANGELOG.md        변경 이력 + 남은 할 일
├── requirements.txt    의존 패키지
├── ml_train.py         학습
├── ml_predict.py       예측 + 공통 런타임 (PART C: 데이터 로딩, 수치 변환, 수식, 피처 스키마, JSON 규약, Windows 파일 처리)
├── ml_report.py        ML 결과 보고서 (Word)
├── samples/            실기 테스트 샘플 + PC_TEST.md (스킬 설치 시 복사 불필요)
└── tests/              자동 테스트 (python -m pytest)
```

`ml_train.py`와 `ml_report.py`는 `ml_predict.py`의 공통 런타임을 import합니다. 학습과 예측이 같은 코드로 데이터를 처리하므로 둘 사이에 처리 방식이 어긋나지 않습니다.

## 2. 설치

- 표준 환경: Windows 11, WinPython (Python 3.13), pandas, scikit-learn, openpyxl, python-docx, matplotlib ([`docs/ENVIRONMENT.md`](../../docs/ENVIRONMENT.md)). 표준 환경이면 추가 설치가 필요 없습니다.
- 폐쇄망에 패키지를 반입하는 방법: [`docs/WINDOWS_OFFLINE.md`](../../docs/WINDOWS_OFFLINE.md)

**OpenCode 스킬 설치**: OpenCode는 `skills/<name>/SKILL.md`를 찾고, 폴더 이름이 스킬 이름(`ml-kit`)과 같아야 합니다.

| 범위 | 설치 위치 (Windows) |
|---|---|
| 모든 프로젝트 공용 (권장) | `C:\Users\<사용자>\.config\opencode\skills\ml-kit\` |
| 특정 프로젝트 전용 | `<프로젝트>\.opencode\skills\ml-kit\` |

1. `ml-kit` 폴더를 위 위치에 복사합니다 (`tests\`, `samples\`는 생략 가능).
2. 복사한 `SKILL.md`의 `<SKILL_DIR>`를 실제 절대 경로로 모두 바꿔 저장합니다 (권장: 경량 LLM이 경로를 추론할 필요가 없어짐).
3. 권한을 제한한다면 `opencode.json`에 `"permission": {"skill": {"ml-kit": "allow"}}`를 추가합니다.

## 3. 빠른 시작

```bat
python ml_train.py -f data.xlsx --header-row 4 --unit-row 5 -x "측정일시,생산라인,반응온도,촉매비율" -y "생산효율" --desc "생산효율 예측"
python ml_predict.py -m data_ml_data\v1 -f new.xlsx --header-row 4 --unit-row 5
python ml_report.py -m data_ml_data\v1
```

---

## 4. 학습 (`ml_train.py`)

### 처리 흐름
데이터 로드 → 컬럼명 확인(단위 생략 이름 자동 매칭, 오타 시 `[추천]`) → 파생변수(`--eval`) → 피처 유형 판별 → 5개 모델 교차검증 → 챔피언 선정 → 전체 데이터로 재학습 → 버전 폴더 저장 → 원장 기록

### 옵션

| 옵션 | 설명 |
|---|---|
| `-f`, `--file` | 데이터 파일 (`.xlsx`, `.csv`). CSV는 인코딩(UTF-8/CP949)과 구분자(`,` `;` 탭 `|`)를 자동 감지 |
| `-x`, `--features` | 피처 목록. 쉼표 구분 또는 파일(`.txt` 한 줄에 하나, `.json` 배열) |
| `-y`, `--targets` | 타겟 목록. 여러 개면 타겟마다 따로 모델을 만듦 |
| `--task` | `regression`(기본) / `classification` |
| `--positive-class` | 이진 분류의 양성 클래스. 지정 시 양성 F1이 최대가 되는 판정 기준 확률을 자동으로 찾음 |
| `--desc` | 데이터와 목적 설명 (문자열 또는 `.txt`/`.md` 파일). 다음 버전이 자동 상속 |
| `--tag` | 이번 실험의 변경 메모 |
| `--eval` | 파생변수 수식. `이름 = 수식; 이름2 = 수식2`. 함수: log, log1p, log10, sqrt, exp, abs, square, clip, sin, cos, tan. 타겟 참조 금지 |
| `--header-row`, `--unit-row`, `--data-row` | Excel 양식의 헤더/단위/데이터 시작 행 (1부터). 생략 시 헤더 자동 감지, 단위는 `반응온도(°C)`처럼 결합 |
| `--dtypes` | 피처 유형 강제. 예: `"설비코드:str,측정일:datetime,값:float"` |
| `-v`, `--version` | 버전 이름 지정 (생략 시 자동 증가) |
| `--seed` | 난수 시드 (기본 42) |
| `--encoding` | `model_dataset.csv` 저장 인코딩 (기본 CP949, 불가 시 UTF-8-SIG) |
| `--history` | 실험 이력 조회 (표는 stderr, 요약 JSON은 stdout) |

### 피처 유형 자동 판별

| 유형 | 판별 기준 | 모델 입력 |
|---|---|---|
| 수치 | 값의 90% 이상이 숫자 (`1,234` 허용, `-`/`N/A`/`미측정`은 결측) | 중앙값 대치 + 표준화 |
| 날짜 | Excel 날짜 셀, 또는 90% 이상이 `YYYY-MM-DD[ HH:MM]` | `<컬럼>_year/month/day/dayofweek/hour` (값이 변하는 부분만) |
| 범주 | 그 외 문자 | 결측은 `__missing__`, 원-핫 인코딩 (처음 보는 값은 무시하고 예측 시 경고) |

값 종류가 200개를 넘거나, 50개를 넘으면서 행의 절반 이상이 서로 다른 문자 컬럼은 ID로 보고 거부합니다.

### 모델과 선정 기준

| | 회귀 | 분류 |
|---|---|---|
| 후보 | HistGradientBoosting, RandomForest, ExtraTrees, Ridge(alpha 자동), ElasticNet(alpha·l1_ratio 자동) | HistGradientBoosting, RandomForest, ExtraTrees, LogisticRegression(C 자동), KNeighbors |
| 검증 | K-Fold (최대 5) | Stratified K-Fold (최대 5, 최소 클래스 크기에 맞춤) |
| 챔피언 | OOF R² 최고 | OOF Macro-F1 최고 |
| 추가 | 90% 예측 범위 (OOF 잔차 5%·95% 분위수) | 불균형(최소 클래스 20% 미만) 시 `class_weight='balanced'`, `--positive-class` 판정 기준 |

- 피처 중요도: 순열 중요도 (최대 5,000행 표본, 날짜 부분은 원래 컬럼으로 합산)
- 대용량: 1만 행 초과 시 RF/ET 트리마다 1만 행 표본, 5만 행 초과 시 KNN 제외
- 같은 데이터에 학습이 겹치면 두 번째 실행을 거부합니다 (OS 파일 잠금, 비정상 종료 시 자동 해제)

### 결과 JSON (stdout 마지막 줄)

| 키 | 내용 |
|---|---|
| `version`, `version_dir`, `data_root` | 이번 버전과 경로 (`version_dir`를 예측·보고서에 그대로 사용) |
| `task`, `primary_metric`, `mean_val_score` | 작업 유형, 지표(`val_r2`/`val_f1_macro`), 타겟 평균 점수 |
| `delta_score`, `is_best` | 같은 작업 유형·타겟 조합의 직전 버전 대비 변화, 역대 최고 여부 |
| `goal_met` | 모든 타겟이 0.90 이상이면 `true` |
| `recommendations` | 가장 낮은 타겟 기준 개선 권고 |
| `next_commands` | 바로 실행 가능한 다음 명령 (`purpose`, `command`). 미달 시 피처 제외/교차항 추가 재학습, 달성 시 예측·보고서 |
| `feature_types`, `column_aliases` | 피처 유형 판별 결과, 단위 생략 이름 매칭 내역 |

## 5. 예측 (`ml_predict.py`)

| 옵션 | 설명 |
|---|---|
| `-m`, `--model` | 버전 폴더 (학습 결과의 `version_dir`) 또는 개별 `.joblib` |
| `-f`, `--file` / `-i`, `--input` | 배치 파일 / 단건 입력 (`키=값,키=값`, JSON 문자열, `.json` 파일). 입력 키는 단위 생략 가능 |
| `-y`, `--targets` | 일부 타겟만 예측 |
| `-o`, `--out` | 결과 파일 (`.csv`/`.xlsx`). 생략 시 원본 옆에 `<원본>_pred_<시각>.csv` |
| `--header-row`, `--unit-row`, `--data-row`, `--encoding` | 학습과 동일 |

**출력 컬럼**: 회귀 `pred_<타겟>`, `pred_lo_<타겟>`, `pred_hi_<타겟>` / 분류 `pred_<타겟>`, `proba_<타겟>_<클래스>`, `conf_<타겟>`

**결과 JSON**: `total_rows`, `targets_predicted`, `output_file`, `predictions_summary`(타겟별 요약, 단건이면 `predictions`·`intervals`·`probabilities`)와 경고 4종

| 경고 | 조건 |
|---|---|
| `extrapolation_warning(s)` | 수치 입력이 학습 범위 밖이거나 날짜가 학습 기간 밖 |
| `unseen_category_warning(s)` | 학습 때 없던 범주 값 |
| `missing_input_warning(s)`, `missing_input_counts` | 빈 값 또는 숫자로 읽을 수 없는 값을 학습 기준값으로 대치 |
| `low_confidence_warning(s)` | 분류 확률 최댓값이 0.6 미만 |

**단독 배포**: `ml_predict.py`와 버전 폴더만 복사하면 됩니다. numpy, pandas, scikit-learn, joblib(+ xlsx는 openpyxl)이 필요하며, 학습 PC와 scikit-learn 버전이 다르면 경고합니다.

## 6. ML 결과 보고서 (`ml_report.py`)

```bat
python ml_report.py -m <version_dir> [--slots slots.json] [-o 결과.docx]
```
선택한 버전의 **모든 타겟을 문서 1개**에 담습니다 (회귀·분류). 기본 저장 위치는 데이터 폴더의 `ML결과보고서_<데이터>_<버전>.docx`입니다.

| 구성 | 내용 |
|---|---|
| 표지·목차 | 제목, 목적, 데이터, 종합 판정, 문서 정보 |
| 1. 요약 | 핵심 수치 카드, 타겟별 판정 표, 요약 소견 |
| 2. 데이터 | 데이터 개요, 피처 구성(유형·학습 범위·결측), 타겟 분포 |
| 3. 분석 방법 | 전처리, 후보 모델, 검증, 선정 기준 |
| 4. 타겟별 결과 | 모델 비교(표·그림), 성능 검증(회귀: 실측 대비 예측·잔차 / 분류: 혼동행렬·클래스별 지표·ROC·판정 기준별 F1), 피처 영향 |
| 5. 버전 이력 | 점수 추이, 버전별 변경 내용, 더 좋은 버전이 있으면 안내 |
| 6. 운영 가이드 | 예측 명령, 경고 해석, 재학습 기준 |
| 부록 | 상관관계 히트맵, 산출물 목록, 실행 환경 |

**판정**: 점수 0.90 이상 적합, 0.70 이상 조건부, 그 미만 부적합. 적합이라도 학습-검증 간극이 0.15를 넘으면 조건부. 종합 판정은 가장 낮은 타겟 기준입니다.

**소견**: 모든 문장은 수치로부터 자동 작성합니다. `--slots`로 원하는 항목만 바꿀 수 있습니다.
```json
{"summary": "...", "data": "...", "operation": "...",
 "targets": {"생산효율(%)": {"performance": "...", "features": "..."}}}
```

**디자인**: A4 세로, 맑은 고딕, 슬레이트 회색 + 남색 강조 1색(흑백 인쇄 가능), 고정 너비 표, 표·그림 번호, 머리글(문서명·데이터·버전)과 바닥글(쪽 번호).

**결과 JSON**: `report_file`, `version`, `task`, `targets`, `overall_verdict`, `verdicts`, `figure_count`, `table_count`, `slots_used`

## 7. 산출물 구조

```text
<데이터파일명>_ml_data/
├── history.jsonl              실험 원장 (버전마다 1줄: 설정, 점수, 데이터 프로파일, 권고, 다음 명령)
├── ML결과보고서_<데이터>_vN.docx
└── vN/
    ├── model_<타겟>.joblib     예측 모델 (전처리 + 챔피언)
    ├── model_<타겟>.json       메타데이터 (feature_schema, 학습 범위, 지표, 예측 범위/판정 기준)
    ├── oof_<타겟>.csv          챔피언의 교차검증 예측값 (보고서 그림 원본)
    ├── leaderboard.json       후보 모델 비교 (튜닝된 설정 포함)
    ├── correlation.csv        전체 상관행렬 (원장에는 피처 30개 이하로 축약)
    ├── model_dataset.csv      학습 데이터 스냅샷
    └── next_features_*.txt    다음 명령용 피처 목록 (피처 15개 초과 시)
```

학습 중에는 `.tmp_vN/`에 저장하고 모두 끝나야 `vN/`으로 바꿉니다. 실패나 Ctrl+C 시에는 임시 폴더를 지웁니다.

## 8. 에이전트 프로토콜

- stdout에는 **정확히 1줄의 JSON**만 출력합니다. 진행 로그(모델당 1줄)와 경고는 stderr로 보냅니다.
- 종료 코드는 0(성공), 1(오류), 2(인자 오류), 130(중단)입니다.

| `agent_directive` | 의미 | 에이전트 행동 |
|---|---|---|
| `VERIFIED:` | 성공 | 결과 보고, 재실행 금지 |
| `STOP_RETRY:` | 입력·데이터 문제 (`error_type: input`) | message에 `[추천]`이 있으면 1회만 재실행, 없으면 사용자에게 보고 |
| `STOP_RETRY:` | 중단 (`error_type: interrupted`) | 사용자에게 확인 |
| `ERROR:` | 내부 오류 (`error_type: internal`) | 재시도 없이 보고 |

## 9. Windows·폐쇄망 동작

| 상황 | 동작 |
|---|---|
| 결과 CSV/Excel/Word가 열려 있음 | 이름에 `_YYYYMMDD_HHMMSS`를 붙인 새 파일로 저장 |
| 백신·탐색기가 폴더를 잡고 있음 | 이름 변경·삭제를 재시도 |
| 메모장·PowerShell이 만든 txt/json | UTF-8, BOM, UTF-16, CP949 자동 인식 |
| CSV 출력 | CP949 (Excel 더블클릭 시 한글 정상), 불가 시 UTF-8-SIG |
| 경로 240자 초과 | 경고 |
| 실행 중 네트워크 | 사용하지 않음 |

## 10. 제한 사항

- 예측 범위는 잔차 분위수 기반의 폭이 일정한 근사치입니다.
- 텍스트 원문(자유 서술) 컬럼은 피처로 쓸 수 없습니다 (범주 200개 초과 시 거부).
- 시계열 예측(과거 값으로 미래 예측)은 지원하지 않습니다. 날짜는 달력 피처로만 사용합니다.
- 모델 파일(`.joblib`)은 신뢰하는 출처의 것만 사용하십시오 (pickle 형식).
