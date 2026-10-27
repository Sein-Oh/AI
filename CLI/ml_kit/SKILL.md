---
name: autonomous-regression-ml
description: 표(Excel/CSV) 데이터로 회귀(수치) 또는 분류(범주) 예측 모델을 학습(ml_train), 예측(ml_predict), Word 감사 보고서 생성(ml_report, 회귀만)하는 1-Turn CLI 스킬. 데이터 정제, 5개 모델 경쟁, 버전 관리, 외삽 경고까지 도구가 자동 처리하므로 에이전트는 명령 1회 실행 후 JSON 결과만 읽으면 된다.
tools:
  - run_command
  - read_file
  - write_file
---

# ml_kit 스킬 (Windows)

`<SKILL_DIR>` 는 이 SKILL.md 가 있는 폴더의 절대 경로로 바꿔서 실행한다.
모든 명령은 **1회 실행**으로 끝난다. stdout 의 **마지막 1줄 JSON** 만 읽는다 (stderr 의 `[PROGRESS]` 로그는 무시).

## 1. 학습: 모델 만들기 / 성능 개선

```bat
python "<SKILL_DIR>\ml_train.py" -f "<데이터.xlsx>" -x "<피처1>,<피처2>,<피처3>" -y "<타겟>" --desc "<데이터 목적 한 줄>" --tag "베이스라인"
python "<SKILL_DIR>\ml_train.py" -f "<데이터.xlsx>" -x "<피처1>,<피처2>" -y "<타겟>" --task classification
```
- 작업 유형은 사용자가 정한다. 수치 예측은 생략(기본 regression), 등급/양불/종류 같은 범주 예측은 `--task classification`.
  사용자가 정하지 않았으면 물어본다.
- 컬럼명은 단위를 빼고 써도 된다: `반응온도` -> `반응온도(°C)` 자동 매칭 (같은 이름이 하나뿐일 때).
- 엑셀 위쪽에 제목/단위 행이 있으면: `--header-row 3 --unit-row 4` (1부터 센 행 번호).
- 피처가 10개 이상이면 `features.txt` 에 한 줄에 하나씩 써서 `-x "features.txt"`.
- 파생변수: `--eval "에너지비 = 소비전력 / (반응온도 + 1e-6); 로그비 = log1p(에너지비)"`
  (사용 가능 함수: log, log1p, log10, sqrt, exp, abs, square, clip, sin, cos, tan). 타겟은 수식에 쓸 수 없다.
- 2회차부터 `--desc` 는 생략한다 (자동 상속). `--tag` 에는 이번에 바꾼 점을 짧게 쓴다.
- 이력 확인: `python "<SKILL_DIR>\ml_train.py" -f "<데이터.xlsx>" --history`

결과 JSON에서 볼 것: `version`, `task`, `mean_val_score`(회귀=R2, 분류=Macro-F1), `delta_score`, `is_best`, `recommendations`, `version_dir`.

## 2. 예측

```bat
python "<SKILL_DIR>\ml_predict.py" -m "<version_dir>" -i "반응온도=240,소비전력=65,촉매비율=0.8"
python "<SKILL_DIR>\ml_predict.py" -m "<version_dir>" -f "<새데이터.xlsx>"
```
- `<version_dir>` 은 학습 결과 JSON 의 `version_dir` 값을 그대로 쓴다.
- `-i` 는 `키=값,키=값` 형식을 쓴다. 레코드가 여러 개면 JSON 파일을 만들어 `-i "input.json"` 으로 넘긴다.
- 결과 JSON에서 볼 것: `predictions_summary`, `output_file`, `drift_warning`, `extrapolation_warnings`.
- 분류 모델이면 `predictions_summary.<타겟>` 에 `predictions`(라벨), `probabilities`, `predicted_class_counts` 가 있고,
  `low_confidence_warning: true` 이면 확신도가 낮은 예측이 있다고 함께 알린다.
- 예측만 다른 PC에 배포할 때: `ml_predict.py` 와 `<version_dir>` 폴더 2가지만 복사하면 된다.

## 3. Word 보고서 (회귀 모델만 지원)

```bat
python "<SKILL_DIR>\ml_report.py" -d "<data_root>"
python "<SKILL_DIR>\ml_report.py" -d "<data_root>" -v v2 -t "<타겟>"
```
- `<data_root>` 는 학습 결과 JSON 의 `data_root` 값. `-v` 생략 시 최고 성능 버전으로 작성된다.
- 소견을 직접 쓰려면 JSON 파일(`slot1_residual`, `slot2_feature`, `slot3_lineage`, `slot4_correlation`, `slot5_serving`)을 만들어 `--slots "slots.json"`. 생략하면 도구가 자동 작성한다.

## 4. 결과 처리 규칙 (반드시 따른다)

| `agent_directive` 시작 | 할 일 |
|---|---|
| `VERIFIED:` | 완료. `preview` 와 파일 경로를 사용자에게 보고. 같은 명령 재실행/파일 재조회 금지. |
| `STOP_RETRY:` + message 에 `[추천]` 있음 | 추천된 컬럼명으로 **1회만** 다시 실행. 또 실패하면 사용자에게 보고. |
| `STOP_RETRY:` (추천 없음) | 재시도 금지. `message` 를 사용자에게 그대로 보고. |
| `ERROR:` | 재시도 금지. `message` 를 사용자에게 그대로 보고. |

- `drift_warning: true` 이면 "입력값이 학습 범위를 벗어나 예측 신뢰도가 낮음"을 함께 알린다.
- 성능 개선 반복: `recommendations` 를 따라 `--eval` 추가 또는 기여도 낮은 피처 제외 후 재학습. 재학습 때도 같은 `--task` 를 쓴다.
  `mean_val_score >= 0.90` 이면 반복을 멈춘다 (회귀는 보고서 생성). 최대 5회.
- 파일 경로는 `file:///C:/...` 형식 링크로 보고한다. 이모지 금지.
