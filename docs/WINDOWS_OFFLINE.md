# Windows 11 폐쇄망 설치 가이드

`CLI/` 아래 모든 도구 공통. 폐쇄망 PC에서는 `pip install`이 인터넷에 접근할 수 없으므로
**인터넷 PC에서 wheel 파일을 미리 받아 반입**합니다.

## 1. 인터넷 PC에서 준비

폐쇄망 PC의 Python 버전을 먼저 확인합니다 (`python --version`, 예: 3.11).

```bat
cd CLI\ml_kit
python -m pip download -r requirements.txt -d wheels ^
  --only-binary=:all: --platform win_amd64 --python-version 3.11 --implementation cp
```
- 인터넷 PC가 폐쇄망과 **같은 Windows + 같은 Python 버전**이면 `--platform` 이하 옵션은 생략 가능합니다.
- 테스트까지 돌리려면 `requirements-dev.txt`로 한 번 더 받습니다.
- Python 설치 파일(`python-3.11.x-amd64.exe`)도 함께 반입합니다.

## 2. 반입 후 폐쇄망 PC에서 설치

```bat
CLI\ml_kit\install_offline.bat
```
`wheels\` 폴더만 사용하며(`--no-index`), 마지막 줄에 `[STATUS] ml_kit dependencies OK`가 나오면 완료입니다.

## 3. 버전 일치 (중요)

`.joblib` 모델은 scikit-learn 버전에 민감합니다. **학습 PC와 예측 PC에 같은 wheel 묶음**을 설치하십시오.
버전이 다르면 `ml_predict.py`가 `[WARN] scikit-learn 버전 불일치`를 출력합니다.
설치 후 `python -m pip freeze > wheels\lock.txt`로 고정 버전을 기록해 두면 다음 반입 때 같은 버전을 받을 수 있습니다
(`pip download -r wheels\lock.txt ...`).

## 4. Windows 사용 시 주의

| 상황 | 동작 |
|---|---|
| 결과 CSV/보고서를 Excel·Word로 열어둔 채 재실행 | 잠금 감지 후 `_YYYYMMDD_HHMMSS` 붙은 새 파일로 저장 |
| 백신/탐색기가 버전 폴더를 잡고 있음 | 이름 변경·삭제를 최대 6회 재시도 |
| 경로가 240자 초과 | `[WARN]` 출력. 데이터를 `C:\work\` 같은 짧은 경로로 이동 |
| 메모장/PowerShell로 만든 txt·json (UTF-8 BOM, UTF-16, CP949) | 자동 인식 |
| CSV 출력 | CP949 기본 (Excel 더블클릭 시 한글 정상), 표현 불가 문자 시 utf-8-sig |
| 에이전트가 stdout 읽기 | 항상 UTF-8 1줄 JSON (`PYTHONIOENCODING` 설정 불필요) |
