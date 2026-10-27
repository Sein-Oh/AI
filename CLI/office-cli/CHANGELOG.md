# CHANGELOG – office-cli

형식: 버전별 `구조 / 기능 / 수정` + 하단 `남은 할 일`. 1.0.0부터 관리합니다.

## [1.1.0] - 2026-10-27

### 구조 (이름 변경, 동작 불변)
- 도구 이름을 `atomic-cli`에서 `office-cli`로 바꿨습니다. 진입점 6개로 합치면서 "작은 도구 여러 개"라는 뜻이 더 이상 맞지 않기 때문입니다.
  - 폴더 `CLI/atomic-cli` -> `CLI/office-cli`, 스킬 이름(SKILL.md `name`) `office-cli`. OpenCode 스킬 폴더도 `office-cli`로 바꿔 배치하세요.
  - 환경변수 `ATOMIC_DATA_DIR` / `ATOMIC_CACHE_DIR` / `ATOMIC_VERBOSE` -> `OFFICE_CLI_DATA_DIR` / `OFFICE_CLI_CACHE_DIR` / `OFFICE_CLI_VERBOSE`. 예전 이름은 읽지 않습니다.
  - 실기 테스트 기본 폴더 `C:\atomic_test` -> `C:\office_test`.
- 내부 함수 `_runtime.atomic_write_text`(중단돼도 기존 파일이 깨지지 않는 저장)를 `safe_write_text`로 바꿨습니다. 코드에 `atomic` 이름이 남지 않습니다.
- 명령, 인자, JSON 키, `config.json`, `cache`/`data` 폴더 구조는 그대로입니다.

### 테스트 러너 (`tools/run_win_tests.py`)
- 분석용 오류 로그 `errors_<시각>.txt`를 `report_*.txt`와 함께 항상 만듭니다. 환경(Windows, Python, 라이브러리, Office 버전과 PDF 가능 여부, `config.json`, 러너 옵션)과, 실패/오류 항목마다 실행한 도구 명령 전체, 종료 코드, 걸린 시간, stdout JSON 전체, stderr 전체, traceback, 그 항목의 진행 로그를 담습니다. 기존 보고서는 JSON 400자, stderr 600자에서 잘려 원인을 알기 어려웠습니다.
- 준비 단계 실패(테스트 파일 만들기, 창 열기), 러너 자체 오류, Ctrl+C 중단에도 그 시점까지의 오류 로그를 남깁니다.
- `--agent`: 에이전트(OpenCode 스킬)용 실행. `--auto`와 같고, 진행 로그는 stderr로, stdout에는 결과 JSON 1줄(`summary`, `failed`, `report_file`, `error_log`, `agent_directive`)만 씁니다. 준비 실패는 exit 1, 중단은 130.
- 실기 테스트 스킬 `tools/office-cli-test/SKILL.md` 추가. 경량 모델이 사용자 확인 후 러너를 1회 실행하고 결과와 오류 로그 경로를 보고합니다.

## [1.0.1] - 2026-10-27

Windows 실기 테스트(집 PC: Windows 11 Pro 26200, Python 3.13.13, Office 2007 32비트) 결과 반영. 최종 65개 중 PASS 63, ENV-SKIP 2(PDF 추가 기능 없음).

### 기능 (추가만, 기존 인자·키 유지)
- `excel.py / word.py / ppt.py info --detail`: 결과가 제대로 보이는지 도구로 확인. PPT는 도형별 위치·크기·글자 크기·목록 종류와 경고(슬라이드 밖, 글자 넘침, 겹침, `--slides`로 범위 지정), 엑셀은 차트 종류·계열 수·위치와 데이터를 가리는 차트 경고, 워드는 그림 크기(쪽 너비 대비)와 제목 수준. 경고 수는 `layout_warnings`.
- `office.py windows`가 실행 중인 Office 버전과 PDF 내보내기 가능 여부(`office`)를 알려 줍니다. PDF 기능이 없는 Office(추가 기능 없는 2007 등)에서는 `export --save *.pdf`가 시도하지 않고 바로 STOP_RETRY로 안내합니다.
- 되돌리기 스냅샷에 문서 식별값(파일 속 만든 시각 `docProps/core.xml`)을 저장합니다. 같은 경로에 다른 문서를 새로 만들면 이전 문서의 스냅샷은 undo 목록에서 빠지고 정리됩니다(Office 저장으로는 바뀌지 않음).

### 수정
- `excel.py chart`를 `--at` 없이 만들면 데이터 범위 바로 오른쪽에 놓여 시트의 다른 데이터를 가리던 문제. 사용 범위 오른쪽에 놓습니다 (실기 J2에서 발견).
- `ppt.py export --save *.pdf`가 항상 내부 오류(`TypeError: The Python instance can not be converted to a COM object`)를 내던 문제. `ExportAsFixedFormat`의 개체 인자 `PrintRange`를 생략하면 pywin32가 인자 변환에서 실패하므로 `PrintRange=None`을 명시합니다.
- PowerPoint 2007(12.x)에 PDF 추가 기능이 없을 때 E_FAIL이 내부 오류로 나가던 문제. `.pptx`로 저장하라는 STOP_RETRY 입력 오류로 안내합니다. 다른 버전의 E_FAIL은 그대로 Office 오류로 보고합니다.
- Word 2007에 없는 `SaveAs2` 호출(새 파일 만들기, `word.py export --save *.docx`, undo의 Flat XML 복원)이 AttributeError로 실패하던 문제. 공통 `_office.word_save_as()`가 `SaveAs`로 대체합니다.
- `ppt.py write`의 `-` 글머리 목록이 "1. 2." 번호 목록으로 나오던 문제. 글머리 표시만 켜고 종류를 정하지 않아 PowerPoint 2007 글상자가 번호 목록으로 만들었습니다. 종류(글머리표/번호)를 명시하고, 마크다운과 `--text`의 `1.` 번호 목록도 구분합니다.
- `excel.py chart`의 분산형 종류가 틀리던 문제. `--type scatter`가 표식만이 아니라 선+표식(74)으로, `scatter_lines`(숫자 x축 `line` 자동 전환 포함)가 표식 없는 선(75) 대신 선+표식으로 그려졌습니다. `scatter` 상수를 -4169로 고치고, 종류를 데이터 지정 앞뒤로 모두 정합니다(앞: 첫 열을 x값으로, 뒤: Excel 2007이 바꾼 세부 종류 복원).
- 열린 워드 문서를 읽을 때 본문 그림 자리가 글자 `/`(Word 2007, 새 버전은 `\x01`)로 나오던 문제. `word.py read`와 `office.py transfer --from word`에서 그림 위치의 글자만 `[그림]`으로 바꿉니다(본문의 진짜 `/`는 유지).

### 테스트 러너 (`tools/run_win_tests.py`)
- 테스트 파일 준비가 Word 2007에서 `SaveAs2`로 멈추던 문제.
- 더블클릭으로 연 Excel은 포커스를 잃기 전까지 ROT에 등록되지 않아(`GetActiveObject` 실패, MS KB 238610) "A.xlsx가 열리지 않았습니다"로 중단되던 문제. 도구와 같은 창 핸들 바인딩(`_office.find_apps`)을 씁니다.
- 이전 실행의 스냅샷이 남아 같은 경로로 다시 만든 A 파일에 undo가 이어져 C7이 두 번째 실행부터 실패하던 문제. 도구 캐시/data를 테스트 폴더의 `_cache`(실행마다 비움), `_data`로 분리합니다.
- PDF 기능이 없는 PC의 D1, D4를 FAIL 대신 `ENV-SKIP`으로 기록합니다.
- I그룹 27개 추가 (모두 자동 판정): 엑셀 CSV/`--values`/`--append` 쓰기, `--search`·`--save`, 300행 잘림, 차트 종류·목록·삭제, 조건부 서식·숫자 서식·지우기, 시트 이름변경·복사·삭제, 범위 복사·숨김·틀 고정, 워드 그림·CSV 표·앵커 앞/바꾸기·제목 수준·쪽 나누기·목차·치환(굵게, `--map`, 바닥글), PPT 그림·카드·마크다운·긴 표·슬라이드 관리·표/그룹 치환·`.pptx` 사본, 엑셀 범위 -> 워드/PPT 표, 워드 표 -> 엑셀, redraw 강제, `undo --list/--pick`, 닫힌 파일 undo, 창 전환 시 최대화 유지. 집 PC(Office 2007): 60개 중 PASS 60(ENV-SKIP 2 제외).
- J그룹 3개 추가: `info --detail`로 PPT 전체 슬라이드, 엑셀 차트, 워드 그림의 배치 경고가 없는지 판정.
- 끝나면 A.pptx 모든 슬라이드와 A.xlsx 모든 차트를 `shots\`에 PNG로 저장하고, 테스트 폴더 문서와 실행 중 생긴 제목 없는 문서를 저장하지 않고 닫습니다(`--keep-open`으로 유지). 문서가 남지 않은 앱은 끝내고, `Quit`을 받고도 남는 빈 Excel/PowerPoint(이 실행 뒤에 생긴 것만)는 창 닫기로 정리합니다. 정리는 러너가 COM 참조를 놓은 뒤 별도 프로세스에서 합니다.

## [1.0.0] - 2026-10-27

첫 배포. 기존 마이크로 CLI 34개를 진입점 6개로 다시 설계했습니다. 이전 버전과의 CLI 호환은 없습니다.

### 구조
- 진입점 6개: `excel.py`, `word.py`, `ppt.py`, `outlook.py`, `reader.py`, `office.py`. 공통 모듈 2개: `_runtime.py`(응답 계약, 경로, 입출력), `_office.py`(COM 세션, 스냅샷, 색/테마).
- 저장소 ACI 계약 준수: stdout 1줄 JSON, exit 0/1/2/130, `VERIFIED:` / `STOP_RETRY:` / `ERROR:`, 인자 오류도 JSON.
- 닫힌 파일 읽기는 라이브러리(openpyxl, python-docx, python-pptx, pymupdf, olefile)로, Office를 띄우지 않습니다. 열린 문서와 쓰기는 COM입니다.
- 결과에 `target_resolved`(실제 작업한 문서), `next_commands`(다음 명령), 이름 오타 시 `[추천]`을 넣습니다.

### 기능
- 화면 규칙: 읽기는 사용자 화면(활성 시트, 스크롤, 슬라이드)을 움직이지 않습니다. 쓰기는 고친 시트/슬라이드로만 이동합니다(`--no-focus`로 끔).
- 쓰기 전 자동 스냅샷과 `office.py undo`(`--list`, `--pick`). 원본은 저장하지 않으며 복원 직전 상태를 백업합니다.
- 차트 전달 3방식(`export` / `redraw` / `relay`)을 자동으로 이어서 시도합니다(DRM으로 PNG가 암호화되는 환경 대응). `--probe`로 이 PC에서 되는 방식을 저장합니다.
- 엑셀: 범위 수식(열마다 수식), 머리글, 이어 쓰기, 테마, 실제 조건부 서식, 숫자 x축 꺾은선의 분산형 자동 전환.
- 워드: 마크다운(제목/목록/표/굵게)을 기본 스타일로 변환, 표는 ConvertToTable로 빠르게, 그림 비율 유지, 앵커 단락 앞/뒤/교체.
- PPT: 마크다운 제목마다 새 슬라이드, 긴 표는 머리글을 반복해 나눔, 그림은 남은 공간에 비율 유지, 카드.
- reader: 읽은 문서 자동 색인과 전체 검색(AND/OR/정규식), `--save`로 md/csv.
- outlook: 기본은 작성 창만 표시, `--send`는 명시 요청 시에만 수신자 확인 후 발송.

### 수정 (기존 코드 대비)
- 파일 대상 작업이 사용자 Excel/Word 창을 숨기던 문제 (전용 인스턴스 사용).
- 읽기 작업이 없는 시트/파일을 만들고 저장하던 문제, PPT 읽기만 해도 마지막 슬라이드로 이동하던 문제.
- Word 스냅샷이 원본을 저장하거나 경로를 바꾸던 문제, 활성 PPT는 스냅샷이 없던 문제, undo가 실패해도 성공으로 보고하던 문제.
- 한 행 범위 처리 오류, 범위 이동이 겹치면 데이터가 지워지던 문제, 치환이 수식을 덮어쓰던 문제.
- 워드 일반 텍스트 쓰기가 항상 실패하던 문제, 앵커 뒤 삽입이 단락을 쪼개던 문제, 빈 문자열 치환이 무시되던 문제.
- HWP 제어 문자 해석 오류, PPT 슬라이드 순서와 단어 쪼개짐, EML 한글 헤더와 전달 메일 본문 섞임.
- Outlook 검색 필터 구문 오류, 첨부 덮어쓰기, 서명 사라짐.

## 남은 할 일

### 1.0 제거 기능 (필요하면 다시 추가할 후보)
- 스타일 DNA 추출 (`office_theme --action extract`). 테마 프리셋은 유지.
- 검색 결과를 Office로 바로 넣기 (`search --to`). 현재는 `reader.py search --save` 후 `write --file`.
- 검색어가 파일명과 같으면 파일을 반환하던 처리.
- 샌드박스 가상 데스크톱 전환 (exebox, `SetThreadDesktop`).
- `clean fix-env`, JIT 자가복구의 "유령 프로세스 정리".
- 새 문서 만들기 / 파일 열기 (`office_window --new/--open`).
- EML 마스터 JSON 빌드·병합·스레드 (`eml_read build/merge/thread`). 단일 EML 읽기는 `reader.py read`.
- 워드 그림/도형 -> PPT 전달 (`office_bridge` word->ppt), PPT -> 워드 전달.
- Outlook 날짜 범위 검색 (`--since`).

### 확인 필요
- Windows 실기 검증: 집 PC(Office 2007)에서 A~F, H 자동 판정 통과(1.0.1). 남은 것: 회사 PC(Office 16)에서 전체 실행, 눈 확인 항목(`--auto` 없이), Outlook G 그룹, PDF 내보내기(D1, D4).
- 실제 HWP 5.0 파일과 DRM 문서로 `reader.py` 검증.
- 회사 PC에서 `office.py transfer --probe` 결과 확인. (집 PC Office 2007: export, redraw 성공 / relay는 "워드에 붙여넣기 안 됨"으로 실패)
- 남은 Office 2007 실기 확인: `.xls/.doc/.ppt`(OOXML 아님)는 문서 식별값이 없어 같은 경로 새 파일 판별을 하지 않습니다.
