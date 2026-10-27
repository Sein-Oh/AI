# ml-kit PC 실기 테스트 체크리스트 (Windows 11 + WinPython)

샘플은 `make_samples.py`로 다시 만들 수 있습니다 (`python make_samples.py`).
"예상 결과"는 개발 환경(Linux, 같은 라이브러리 버전)에서 실제로 실행한 값입니다. 점수는 소수점 이하가 조금 달라도 정상입니다.

| 파일 | 내용 |
|---|---|
| `sample_A_process.xlsx` | 공정 데이터 400행. 제목 3행 + 헤더 4행 + 단위 5행, Excel 날짜, 범주(생산라인), 천단위 콤마(소비전력), `-`/`미측정`, 학습에 쓰지 않는 `비고` 컬럼. 타겟 2개(생산효율, 인장강도) |
| `sample_A_process_new.xlsx` | 예측용 30행. 반응온도 범위 밖 2건, 미학습 범주 `D라인`, 결측 2건, 학습 기간 이후 날짜 |
| `sample_B_quality.csv` | 품질검사 500행, **CP949** CSV. 문자열 날짜, 숫자형 설비코드(범주로 강제), 품질등급(A/B/C), 불량여부(불량 10%) |
| `sample_B_quality_new.csv` | 예측용 20행. 미학습 설비코드 106, 경도 범위 밖, 두께 결측 |
| `sample_B_single_input.json` | 단건 입력. **UTF-16**(PowerShell 5 `Out-File` 기본값), 키에 단위 생략 |
| `sample_slots.json` | 보고서 소견 직접 입력 예시 |

## 0. 준비

```bat
python -c "import sys; print(sys.executable)"
cd <AI_WORK 경로>\CLI\ml-kit\samples
python -m pytest -q ..
```
- [ ] 첫 줄이 WinPython 폴더의 `python.exe`를 가리킨다
- [ ] 테스트가 `passed`로 끝난다 (`skipped` 1건은 정상)

## 1. 회귀 학습 (Excel 레이아웃 + 범주 + 날짜 + 다중 타겟)

```bat
python ..\ml_train.py -f sample_A_process.xlsx --header-row 4 --unit-row 5 -x "측정일시,생산라인,반응온도,소비전력,압축압력,촉매비율,수분함량,유입유속" -y "생산효율,인장강도" --desc "반응기 생산효율/인장강도 예측" --tag "베이스라인"
```
- [ ] 마지막 줄 JSON `"status": "ok"`, `"version": "v1"`, `mean_val_score` 약 0.93
- [ ] `feature_types`: categorical = `생산라인`, datetime = `측정일시` (month, day, dayofweek, hour)
- [ ] `column_aliases`에 단위 생략 이름 8개 매칭
- [ ] `next_commands` 2개: 예측 명령, 보고서 명령 (목표 0.90 달성)
- [ ] 콘솔에 한글이 깨지지 않는다 (cmd, PowerShell 각각)

## 2. 회귀 예측

```bat
python ..\ml_predict.py -m sample_A_process_ml_data\v1 -f sample_A_process_new.xlsx --header-row 4 --unit-row 5
python ..\ml_predict.py -m sample_A_process_ml_data\v1 -i "측정일시=2025-06-20 22:00,생산라인=B라인,반응온도=250,소비전력=2000,압축압력=3,촉매비율=1.0,수분함량=18,유입유속=6"
```
- [ ] 배치: `drift_warning: true`, `unseen_category_warning: true` (D라인), `missing_input_counts` = 촉매비율 1, 수분함량 1
- [ ] 배치: `output_file`의 CSV를 **더블클릭**해 Excel에서 한글이 정상 표시되고 `pred_lo_` / `pred_hi_` 컬럼이 있다
- [ ] 단건: 생산효율 약 61.0 (범위 약 58.0~63.7), 인장강도 약 217.9, 날짜 학습 기간 밖 경고 1건

## 3. 분류 학습·예측

```bat
python ..\ml_train.py -f sample_B_quality.csv -x "검사일자,설비코드,두께,경도,표면조도,작업장온도" -y 품질등급 --task classification --dtypes "설비코드:str"
python ..\ml_train.py -f sample_B_quality.csv -x "설비코드,두께,경도,표면조도,작업장온도" -y 불량여부 --task classification --positive-class 불량 --dtypes "설비코드:str"
python ..\ml_predict.py -m sample_B_quality_ml_data\v1 -f sample_B_quality_new.csv
python ..\ml_predict.py -m sample_B_quality_ml_data\v1 -i sample_B_single_input.json
```
- [ ] 다중 분류 v1: Macro-F1 약 0.73, `설비코드`가 categorical, `next_commands` 2개
- [ ] 이진 분류 v2: 약 0.80, 콘솔에 `class_weight='balanced'` 경고와 `판정 기준 확률 = 0.69` 정도
- [ ] 배치 예측: 설비코드 106 미학습 경고, 두께 결측 1건, `drift_warning: true`
- [ ] UTF-16 JSON 단건: 예측 `C`, `column_aliases`에 단위 생략 키 4개

## 4. 성능 개선 루프 (next_commands)

```bat
python ..\ml_train.py -f sample_B_quality.csv --history
```
- [ ] v1 결과 JSON의 `next_commands[0].command`를 **그대로 복사해 cmd와 PowerShell에 각각 붙여 넣어** 실행되고 새 버전이 생긴다
- [ ] `--history` 표(stderr)와 JSON(`best_by_task`)이 나온다

## 5. 보고서

```bat
python ..\ml_report.py -d sample_A_process_ml_data --slots sample_slots.json
python ..\ml_report.py -d sample_B_quality_ml_data
```
- [ ] 회귀: 보고서 2개(타겟별) 생성, Word에서 열린다
- [ ] 분류: `STOP_RETRY` (분류 보고서는 다음 버전) 안내

## 6. Windows 고유 동작

- [ ] **파일 잠금**: 2번 배치 결과 CSV를 Excel로 열어둔 채 같은 명령을 다시 실행 -> `_YYYYMMDD_HHMMSS`가 붙은 새 파일로 저장 + `[WARN]`
- [ ] **보고서 잠금**: 생성된 docx를 Word로 열어둔 채 5번 재실행 -> 새 파일명으로 저장
- [ ] **동시 실행 잠금**: cmd 창 2개에서 1번 학습을 거의 동시에 실행 -> 두 번째가 `STOP_RETRY` ("다른 학습이 이미 실행 중")
- [ ] **Ctrl+C**: 1번 학습 중 Ctrl+C -> JSON `"error_type": "interrupted"`, `sample_A_process_ml_data`에 `.tmp_v*` 폴더가 남지 않음
- [ ] **한글 경로**: samples 폴더를 `C:\작업\테스트\`로 복사해 1번 실행 -> 정상

## 7. 단독 배포 (예측만)

```bat
mkdir C:\deploy_test
copy ..\ml_predict.py C:\deploy_test\
xcopy /E /I sample_A_process_ml_data\v1 C:\deploy_test\v1
cd C:\deploy_test
python ml_predict.py -m v1 -i "측정일시=2025-06-20 22:00,생산라인=B라인,반응온도=250,소비전력=2000,압축압력=3,촉매비율=1.0,수분함량=18,유입유속=6"
```
- [ ] 2번 단건과 같은 예측값

## 8. OpenCode 스킬

1. `CLI\ml-kit` 폴더를 `C:\Users\<사용자>\.config\opencode\skills\ml-kit\`로 복사 (`tests`, `samples` 생략 가능)
2. 복사한 `SKILL.md`의 `<SKILL_DIR>`를 위 절대 경로로 바꿔 저장
3. OpenCode에서 요청: "samples 폴더의 sample_A_process.xlsx로 생산효율 예측 모델 만들어줘. 헤더는 4행, 단위는 5행이야."

- [ ] 에이전트가 `skill({ name: "ml-kit" })`로 스킬을 불러온다
- [ ] 명령 1회로 학습하고 JSON 결과를 보고한다 (재실행 반복 없음)
- [ ] 이어서 "성능 더 올려봐" -> `next_commands[0]`을 그대로 실행한다

결과가 다르거나 오류가 나면 해당 명령의 **마지막 줄 JSON**과 stderr의 `[WARN]`/`[ERROR]` 줄을 알려주세요.
