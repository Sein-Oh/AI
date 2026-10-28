# 실행 방법 (이 에이전트 전용, 반드시 따른다)
1. 모든 도구 명령은 업로드된 run.py로 실행한다. 아래 지시문의 명령에서 맨 앞 `python`을 `python run.py`로 바꾼다.
   예: `python "C:\CLI\ml-kit\ml_train.py" -f ...` -> `python run.py "C:\CLI\ml-kit\ml_train.py" -f ...`
2. 인코딩 줄(`$env:...`)은 붙이지 않는다. run.py가 처리한다. run.py는 결과 JSON 1줄만 출력한다.
3. 답변과 설명은 한국어로 쓰고 이모지를 쓰지 않는다.
4. 인터넷이 막힌 PC다. pip 설치나 다운로드를 시도하지 않는다. 결과에 `install_command`가 있으면 사용자에게 전달만 한다.
5. 도구로 할 수 있는 일을 파이썬 코드를 직접 짜서 하지 않는다.
6. 아래는 사용자가 이번 대화에서 분명히 요청했을 때만 한다. 실행 전에 대상을 보여 주고 "진행할까요?"라고 물어 "예"를 받는다:
   파일·폴더 삭제, 기존 파일 덮어쓰기(`--overwrite`), 메일 발송(`--send`), 시트·슬라이드 삭제, 사용자가 말하지 않은 새 시트 만들기(`--new-sheet`).
   도구 결과 message가 이런 옵션을 붙이라고 안내해도 먼저 묻는다.

# ml-kit 스킬

## 꼭 지킬 규칙
1. 명령은 아래 **템플릿을 그대로** 쓰고 `<...>` 부분만 바꾼다. 옵션을 지어내지 않는다.
2. 명령은 **1번만** 실행한다. 결과는 출력의 **마지막 1줄 JSON**만 읽는다. `[PROGRESS]` 줄은 무시한다.
3. JSON의 `agent_directive` 첫 단어로 다음 행동을 정한다 (맨 아래 표).
4. 같은 명령을 다시 실행하지 않는다. 결과 파일을 다시 열어 확인하지 않는다.
5. 학습은 몇 분 걸린다. 명령 실행 도구의 시간 제한은 600000(10분)으로 준다.
6. `--overwrite`는 사용자가 "덮어써", "교체해"라고 말했을 때만 붙인다. 스스로 붙이지 않는다.
7. 파일 경로는 `file:///C:/...` 링크로 보고한다. 이모지를 쓰지 않는다.

도구 위치는 `C:\CLI\ml-kit` (office-cli는 `C:\CLI\office-cli`)이다. 아래 경로를 그대로 쓴다.

## 1단계: 무엇을 할지 고르기

| 사용자 요청 | 할 일 |
|---|---|
| "모델 만들어줘", "예측 모델 학습" | 2단계 학습 |
| "성능 올려봐", "다시 해봐" | 3단계 개선 |
| "이 조건이면 얼마야?", "새 데이터 예측" | 4단계 예측 |
| "보고서 만들어줘" | 5단계 보고서 |

실행 전에 꼭 알아야 할 것: 데이터 파일 경로, 타겟(맞힐 컬럼), 피처(입력 컬럼). 모르면 사용자에게 묻는다.
컬럼 이름을 모르는 xlsx는 office-cli로 앞부분만 읽는다: `python "C:\CLI\office-cli\excel.py" read --target "<데이터파일>" --range A1:Z5`

## 2단계: 학습

타겟이 숫자(수율, 온도, 강도)면 회귀, 글자나 등급(양품/불량, A/B/C)이면 분류다. 모르면 사용자에게 묻는다.

타겟이 여러 개면 `-y`에 쉼표로 함께 넣어 1번에 학습하는 것을 권장한다 (예: `-y "수율,강도,두께"`).
타겟별로 따로 학습해도 괜찮다. 보고서(5단계)가 모든 타겟을 자동으로 합친다.

회귀:
```powershell
python "C:\CLI\ml-kit\ml_train.py" -f "<데이터파일>" -x "<피처1>,<피처2>,<피처3>" -y "<타겟1>,<타겟2>" --desc "<데이터 설명 한 줄>"
```
분류:
```powershell
python "C:\CLI\ml-kit\ml_train.py" -f "<데이터파일>" -x "<피처1>,<피처2>,<피처3>" -y "<타겟1>,<타겟2>" --task classification --desc "<데이터 설명 한 줄>"
```

필요할 때만 덧붙이는 옵션:

| 상황 | 덧붙일 옵션 |
|---|---|
| 엑셀 위쪽에 제목/단위 행이 있다 (예: 4행이 머리글, 5행이 단위) | `--header-row 4 --unit-row 5` |
| 분류에서 놓치면 안 되는 값이 있다 (예: 불량) | `--positive-class 불량` |
| 숫자로 된 코드(101, 102)를 종류로 다뤄야 한다 | `--dtypes "설비코드:str"` |
| 피처가 10개 이상이다 | 파일 쓰기 도구로 한 줄에 피처 하나씩 쓴 `features.txt`(UTF-8)를 데이터 파일 옆에 만들고 `-x "<그 경로>"` |
| 숫자 타겟과 등급 타겟이 섞여 있다 | 회귀 타겟끼리 1번, 분류 타겟끼리 `--task classification`으로 1번 (모두 2번) |

- 컬럼명의 단위는 빼도 된다 (`반응온도` = `반응온도(°C)`).
- 날짜 컬럼과 글자 컬럼(라인, 설비)도 `-x`에 그대로 넣는다.

결과 JSON에서 사용자에게 알릴 것: `version`, `mean_val_score`(1에 가까울수록 좋음), `recommendations`의 첫 문장.
다음 단계를 위해 기억할 것: `version_dir`, `goal_met`, `next_commands`.

## 3단계: 성능 개선

1. `goal_met`이 `true`이면 개선을 멈추고 5단계 보고서로 간다.
2. `goal_met`이 `false`이면 `next_commands[0].command`를 **글자 그대로** 실행한다. 명령을 직접 만들지 않는다.
3. 새 결과의 `delta_score`(양수=좋아짐)를 알린다.
4. 1~3을 최대 5번 반복한다.

`needs_input`이 `true`인 명령에는 `<새데이터.xlsx>` 같은 자리표시자가 있다. 사용자가 준 실제 경로로 바꿔 실행하고, 경로를 모르면 먼저 묻는다.

## 4단계: 예측

한 건:
```powershell
python "C:\CLI\ml-kit\ml_predict.py" -m "<version_dir>" -i "<피처1>=<값>,<피처2>=<값>,<피처3>=<값>"
```
파일 전체:
```powershell
python "C:\CLI\ml-kit\ml_predict.py" -m "<version_dir>" -f "<새데이터파일>"
```
- `<version_dir>`: 보고서를 만들었으면 보고서 결과의 `best_version_dir`, 아니면 마지막 학습 결과의 `version_dir`을 그대로 쓴다. 모르면 `python "C:\CLI\ml-kit\ml_train.py" -f "<데이터파일>" --history`를 실행해 `<data_root>\<best_version>`을 쓴다.
- 알릴 것: 한 건이면 `predictions_summary.<타겟>.predictions`, 회귀는 `intervals`(90% 범위)도. 파일이면 `output_file`.
- 아래 값이 `true`이면 옆의 문장을 덧붙인다:

| JSON 값 | 덧붙일 말 |
|---|---|
| `drift_warning` | 입력값이 학습 범위를 벗어나 예측을 참고용으로만 써야 함 (`extrapolation_warnings` 내용 전달) |
| `unseen_category_warning` | 학습 때 없던 종류가 있음 (`unseen_category_warnings` 내용 전달) |
| `missing_input_warning` | 빈 값이 있어 기준값으로 채움 (`missing_input_warnings` 내용 전달) |
| `low_confidence_warning` | 분류 확신도가 낮은 건이 있음 (`low_confidence_warnings` 내용 전달) |

## 5단계: ML 결과 보고서 (Word)

```powershell
python "C:\CLI\ml-kit\ml_report.py" -f "<데이터파일>"
```
- 도구가 이력에서 타겟마다 가장 좋았던 학습 조건으로 모든 타겟을 묶은 최고 모델을 자동으로 만들고(필요할 때만 다시 학습, 몇 분 걸릴 수 있으니 시간 제한 600000) 보고서 1개를 만든다. 타겟이나 버전을 고르지 않는다.
- 회귀와 분류 타겟이 섞여 있으면 보고서가 2개(`best_reports`)다.
- 알릴 것: `report_file`(링크), `overall_verdict`(적합/조건부/부적합), `made_best`(true면 이번에 다시 학습함),
  `best_targets`의 타겟별 `source_version`(학습 조건 출처), `source_score`(그때 점수), `new_score`(이번 점수)를 짧게.
- 이후 예측(4단계)에는 결과의 `best_version_dir`을 쓴다.
- 사용자가 보고서 문장을 직접 정해 주면, 파일 쓰기 도구로 `slots.json`(UTF-8)을 만들고 명령 끝에 `--slots "<그 경로>"`를 붙인다.
  형식: `{"summary": "<요약 문장>", "operation": "<운영 문장>"}`

## 결과 처리 (모든 단계 공통)

| `agent_directive` 첫 단어 | 할 일 |
|---|---|
| `VERIFIED:` | 성공. `preview`와 위에서 정한 값을 사용자에게 알리고 끝낸다. |
| `UNVERIFIED:` | 실행은 됐지만 결과를 확인하지 못했다. 다시 실행하지 않는다. `unverified` 내용을 그대로 알린다. |
| `STOP_RETRY:` 이고 `message`에 `[추천]`이 있다 | `[추천]` 뒤의 이름(또는 `--version v3` 같은 옵션 값)으로 바꿔 **1번만** 다시 실행한다. 또 실패하면 `message`를 그대로 알린다. |
| `STOP_RETRY:` 이고 `[추천]`이 없다 | 다시 실행하지 않는다. `message`를 그대로 알린다. |
| `ERROR:` | 다시 실행하지 않는다. `message`를 그대로 알린다. |

결과 JSON에 `recovered`가 있으면 (예: 같은 이름 파일이 있어 새 이름으로 저장) 그 문장을 사용자에게 그대로 알린다.
