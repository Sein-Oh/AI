---
name: ml-kit
description: 표(Excel/CSV) 데이터로 수치 예측(회귀) 또는 범주 예측(분류) 모델을 학습하고(ml_train.py), 새 데이터를 예측하고(ml_predict.py), Word로 ML 결과 보고서를 만든다(ml_report.py). 데이터 정제, 5개 모델 경쟁, 버전 관리, 입력 경고를 도구가 자동 처리하므로 명령 1회 실행 후 JSON 결과만 읽으면 된다. 예측 모델 만들기, 성능 개선, 새 조건 예측값 계산, 결과 보고서 요청 시 사용.
license: Proprietary
compatibility: opencode
metadata:
  version: "1.0.0"
  platform: windows
---

# ml-kit 스킬 (Windows)

`<SKILL_DIR>` 는 이 SKILL.md 가 있는 폴더의 절대 경로다 (설치 시 실제 경로로 바뀌어 있을 수 있다).
모든 명령은 **1회 실행**으로 끝난다. stdout 의 **마지막 1줄 JSON** 만 읽는다 (stderr 의 `[PROGRESS]` 로그는 무시).
데이터가 크면 학습에 몇 분 걸릴 수 있다. 명령 실행 도구에 시간 제한 옵션이 있으면 넉넉히(10분) 준다.

## 1. 학습

```bat
python "<SKILL_DIR>\ml_train.py" -f "<데이터.xlsx>" -x "<피처1>,<피처2>,<피처3>" -y "<타겟>" --desc "<데이터 목적 한 줄>" --tag "베이스라인"
python "<SKILL_DIR>\ml_train.py" -f "<데이터.xlsx>" -x "<피처1>,<피처2>" -y "<타겟>" --task classification
```
- 작업 유형은 사용자가 정한다. 수치 예측은 생략(기본 regression), 등급/양불/종류 같은 범주 예측은 `--task classification`.
  사용자가 정하지 않았으면 물어본다.
- 이진 분류에서 놓치면 안 되는 클래스(예: 불량)가 있으면 `--positive-class 불량` 을 추가한다.
- 컬럼명은 단위를 빼고 써도 된다: `반응온도` -> `반응온도(°C)` 자동 매칭.
- 문자 컬럼(라인, 설비코드)과 날짜 컬럼(일시)도 `-x` 에 그대로 넣는다. 숫자 코드(101, 102)를 범주로 쓰려면 `--dtypes "설비코드:str"`.
- 엑셀 위쪽에 제목/단위 행이 있으면 `--header-row 4 --unit-row 5` (1부터 센 행 번호).
- 피처가 10개 이상이면 `features.txt` 에 한 줄에 하나씩 써서 `-x "features.txt"`.
- 2회차부터 `--desc` 는 생략한다 (자동 상속). `--tag` 에는 이번에 바꾼 점을 짧게 쓴다.
- 이력 확인: `python "<SKILL_DIR>\ml_train.py" -f "<데이터.xlsx>" --history`

결과 JSON에서 볼 것: `version_dir`, `task`, `mean_val_score`(회귀=R2, 분류=Macro-F1), `delta_score`, `goal_met`, `recommendations`, `next_commands`.

## 2. 성능 개선 반복

- `goal_met` 가 `false` 이면 `next_commands[0].command` 를 **그대로** 실행한다. 명령을 직접 만들지 않는다.
- `goal_met` 가 `true` 이거나 5회 반복하면 멈추고 결과를 보고한다.

## 3. 예측

```bat
python "<SKILL_DIR>\ml_predict.py" -m "<version_dir>" -i "반응온도=240,소비전력=65,촉매비율=0.8"
python "<SKILL_DIR>\ml_predict.py" -m "<version_dir>" -f "<새데이터.xlsx>"
```
- `<version_dir>` 은 학습 결과 JSON 의 `version_dir` 값을 그대로 쓴다.
- `-i` 는 `키=값,키=값` 형식. 레코드가 여러 개면 JSON 파일을 만들어 `-i "input.json"`.
- 결과 JSON에서 볼 것: `predictions_summary`, `output_file`. 회귀는 `intervals`(90% 예측 범위), 분류는 `predictions`, `probabilities`.
- 아래 값이 `true` 이면 해당 `*_warnings` 내용을 함께 알린다:
  `extrapolation_warning`(학습 범위 밖), `unseen_category_warning`(학습 때 없던 범주), `missing_input_warning`(빈 값 대치), `low_confidence_warning`(분류 확신도 낮음).
- 예측만 다른 PC에 배포할 때: `ml_predict.py` 와 `<version_dir>` 폴더 2가지만 복사한다.

## 4. ML 결과 보고서 (Word)

```bat
python "<SKILL_DIR>\ml_report.py" -m "<version_dir>"
```
- 그 버전의 모든 타겟을 담은 문서 1개를 만든다 (회귀, 분류 모두). 결과 JSON의 `report_file`, `overall_verdict` 를 보고한다.
- 소견은 도구가 자동 작성한다. 사용자가 문장을 지정하면 JSON 파일로 만들어 `--slots "slots.json"`:
  `{"summary": "...", "operation": "...", "targets": {"<타겟>": {"performance": "...", "features": "..."}}}`

## 5. 결과 처리 규칙 (반드시 따른다)

| `agent_directive` 시작 | 할 일 |
|---|---|
| `VERIFIED:` | 완료. `preview` 와 파일 경로를 사용자에게 보고. 같은 명령 재실행/파일 재조회 금지. |
| `STOP_RETRY:` + message 에 `[추천]` 있음 | 추천된 이름으로 **1회만** 다시 실행. 또 실패하면 사용자에게 보고. |
| `STOP_RETRY:` (추천 없음) | 재시도 금지. `message` 를 사용자에게 그대로 보고. |
| `ERROR:` | 재시도 금지. `message` 를 사용자에게 그대로 보고. |

- 파일 경로는 `file:///C:/...` 형식 링크로 보고한다. 이모지 금지.
