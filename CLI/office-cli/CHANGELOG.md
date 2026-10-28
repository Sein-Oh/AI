# CHANGELOG – office-cli

형식: 버전별 `구조 / 기능 / 수정` + 하단 `남은 할 일`. 1.0.0부터 관리합니다.

## [1.2.2] - 2026-10-28

사내 경량 LLM(Gemma, OpenCode + PowerShell)으로 `docs/opencode/SCENARIOS.md`를 실행한 시나리오 테스트 결과 반영 (시나리오 10, 12).

### 스킬
- 도구 위치를 `C:\CLI\office-cli`로 고정: SKILL.md와 office-cli-test SKILL.md의 명령 경로를 실제 경로로 적음 (office-cli 옆 배치 조건 없앰).

### 수정
- (시나리오 10) Sheet1만 있는 빈 통합문서에서 "Sheet9에 '테스트'라고 써줘" -> Gemma가 사용자에게 묻지 않고 Sheet9를 만들어 썼습니다.
  원인: 없는 시트 오류(`_office.missing_sheet`)의 message에 "새 시트로 만들려면 같은 명령에 --new-sheet를 붙이세요"가 있었고, 비슷한 시트가 있으면 `[후보]`에 "(새 시트 만들기: --new-sheet)"를 섞어 넣어 LLM이 그것을 골랐습니다.
  - message와 `[후보]`에는 사실만 적습니다: 없는 시트, 있는 시트 목록, 아무 데도 쓰지 않았음, 사용자에게 물어볼 것. `--new-sheet`와 명령문을 넣지 않습니다.
  - 표기만 다른 시트(대소문자·공백·_-.)가 하나면 지금처럼 `[추천]`(error_type `input`). 그 밖에는 새 error_type `needs_user_decision`(첫 단어는 `STOP_RETRY:` 그대로). 비슷한 기존 시트가 있으면 그 이름만 `[후보]`와 `candidates`에 넣습니다.
  - `agent_directive`: `STOP_RETRY: 다시 실행하지 마세요. message를 사용자에게 그대로 보여 주고, 새 시트 '<이름>'을(를) 만들지 물어보세요. 사용자가 만들라고 답한 경우에만 같은 명령에 --new-sheet를 붙여 실행하세요.` (`[후보]`가 있으면 기존 시트를 고르는 경우도 안내)
  - 공통 런타임에 `UserDecisionError`(InputError 하위 클래스, 사용자 결정이 필요한 오류) 추가.
  - SKILL.md 3절 `[후보]` 행에서 `--new-sheet`를 고를 값 목록에서 빼고 "사용자가 새 시트를 원한다고 답한 경우에만"으로 바꿨습니다.
  - `office.py transfer --to excel --sheet X`에서 X가 이미 있을 때의 `[추천] X 2`는 유지합니다. transfer는 원래 항상 새 시트에 받고(`--sheet` 생략 시에도 `Word 내용 2`처럼 비어 있는 이름), 기존 시트를 덮어쓰는 길은 `--overwrite`뿐이라 추천대로 다시 실행해도 기존 데이터가 바뀌지 않습니다.
- (시나리오 12) 저장한 적 없는 새 워드 문서(`문서1`)에 엑셀 차트를 transfer한 뒤 "방금 한 거 되돌려줘" -> `office.py undo`가 빈 워드 창을 새로 열고, 차트가 들어간 문서는 그대로 남았습니다.
  원인: 저장한 적 없는 문서의 스냅샷은 항상 "새 제목 없는 문서"로 열었습니다(1.0 설계).
  - 스냅샷 때의 문서 이름으로 열린 문서 중 저장 안 된 문서를 찾습니다(`_office.open_untitled`, 스냅샷 meta에 `untitled` 추가).
  - 워드: 현재 내용을 `pre_undo_backup`(.xml)에 보관하고, 같은 창에서 내용만 스냅샷으로 바꿉니다(flat XML 스냅샷은 `InsertXML`, 그 밖은 `InsertFile`). `restored_as: "restored_in_place"`.
  - 엑셀/PPT: 현재 상태를 `pre_undo_backup`에 보관하고 스냅샷을 새 제목 없는 문서로 연 뒤, 바뀐 문서를 저장하지 않고 닫습니다(문서 수 그대로). `restored_as: "replaced_untitled_document"`.
  - 바뀐 문서가 닫혔거나 같은 이름의 저장 안 된 문서가 둘 이상이면 고르지 않고 예전처럼 새 문서로만 엽니다(`new_untitled_document`). 이유를 `preview`에 적습니다.
  - `preview`와 `agent_directive`에 무엇을 했는지 적습니다(예: `'문서1'을(를) 같은 창에서 되돌렸습니다`). 결과에 `restored_name`(되돌린 내용이 있는 문서 이름) 추가. 기존 키(`restored`, `app`, `name`, `restored_as`, `pre_undo_backup`) 유지.

### 실기 테스트 러너 (`tools/run_win_tests.py`)
- C3(저장 안 한 새 통합문서 undo): 기대값을 "통합문서 수 +1"에서 "수 그대로, 바뀐 통합문서는 닫힘, 되돌린 통합문서의 A1이 쓰기 전 값"으로 바꿨습니다.
- C8 추가: 새 워드 문서에 쓰고 undo -> 같은 창에서 문장이 사라지고 문서 수 그대로 (시나리오 12).

### 테스트
- 없는 시트: message·`[후보]`에 `--new-sheet`와 명령문이 없음, directive가 사용자에게 묻게 함, `[추천]`(표기만 다름) 유지, `[후보]`는 실제 시트만, 시나리오 10 재현.
- 저장 안 한 문서 undo: 워드 같은 창 복원(새 문서 없음, 백업 기록), 엑셀/PPT 바꿔 열고 바뀐 문서 닫기, 문서가 닫혀 있으면 예전 동작, 같은 이름 둘이면 고르지 않음.

## [1.2.1] - 2026-10-28

회사 PC 실기 테스트(Windows 11, Office 16.0 / Microsoft 365, WinPython 3.13.13, DRM) 결과 반영과 오류 로그(R6).

### 스킬
- SKILL.md를 PowerShell 기준으로 정리: 꼭 지킬 규칙 8개(인코딩 줄, 1회 실행, 표·여러 줄·큰따옴표 값은 파일로, `$`는 작은따옴표), PowerShell에서 따옴표가 사라지는 `--values` JSON 예시를 `--file "표.csv"`로 교체, `UNVERIFIED:` 행 추가, 유니코드 화살표 제거. 도구 동작은 바뀌지 않습니다.

### 기능 (추가만, 기존 인자·키 유지)
- 오류 로그: 실패한 실행(exit 1, 인자 오류 exit 2)을 `<data 폴더>/logs/errors.txt`에 자동으로 덧붙입니다 (`CLI/README.md` R6, 기준 doc-classifier `write_error_log`).
  머리줄 `===== <시각> | office-cli <버전> | Python <버전> | <OS>`, `명령:`, `결과: <error_type> | <message>`, 한도를 넘긴 복구 시도는 `복구 시도:`, 내부 오류(`ERROR:`)만 `traceback:`.
  성공과 사용자 중단(130)은 기록하지 않고, 2MB를 넘으면 `errors.old.txt`로 넘깁니다(1세대). 회전 실패와 기록 실패는 따로 삼켜 stdout 1줄 JSON에 영향이 없습니다. 로그 경로는 JSON에 넣지 않습니다.
- `_runtime.VERSION`("1.2.1"), `record_recovery_attempt()`. `retry_fs`가 한도를 넘기면 `복구 시도:`에 남깁니다. SKILL.md `metadata.version`과 같은지 테스트합니다.

### 실기 테스트 러너 (`tools/run_win_tests.py`)
- A5(두 번째 Excel 정리)가 A.xlsx를 연 사용자 Excel까지 닫던 문제. 이후 B2, B3, C1, C2, D3, E, H1, H3, I1, I2가 `DISP_E_BADINDEX`(Workbooks("A.xlsx") 없음)로 실패했습니다.
  원인: 정리 스크립트가 "실행 시작 뒤 생긴 Excel/PowerPoint의 숨은 창 또는 제목 빈 창"에 WM_CLOSE를 보냈는데, A.xlsx를 연 Excel도 러너가 띄운 것이고 Office 16에는 숨은 XLMAIN 창이 있습니다 (Office 2007에서는 드러나지 않음).
  - 문서가 남아 있는 프로세스(COM 문서 수 > 0, 제목 있는 창, 창 제목에 A.xlsx 등)는 Quit도 WM_CLOSE도 하지 않습니다.
  - A5는 Excel을 띄우기 전후의 PID를 비교해 자기가 띄운 PID만 끝냅니다. 종료 정리는 실행 시작 뒤 생긴 빈 프로세스만, 실행 전부터 있던 Office는 문서가 없어도 끝내지 않습니다.
  - 같은 인스턴스가 두 번 잡히면 건너뛰고, Office 16의 빈 창 제목(`Excel`, `PowerPoint`)도 인식합니다.
  - 판단 규칙은 `tools/win_test_rules.py`로 분리해 오프라인 테스트(`tests/test_win_runner.py`, 가짜 Office/pywin32로 회사 PC 상황 재현)를 붙였습니다.
- JIT 복구: 그룹 시작 전과 문서 조회 때 A.xlsx/A.docx/A.pptx가 닫혀 있으면 준비 단계와 같은 방법(`os.startfile`)으로 다시 열고 `[WARN] A.xlsx가 닫혀 있어 다시 열었습니다`를 남깁니다.
  다시 열지 못하면 그 그룹의 남은 항목을 "테스트 문서 A.xlsx가 닫혀 다시 열지 못함" 하나의 이유로 바로 ERROR 처리합니다.
- `com_retry`가 '그 이름의 항목 없음'(`DISP_E_BADINDEX`)을 재시도하지 않습니다. 중첩된 재시도(최대 10x10x10회)로 멈춘 것처럼 보여 Ctrl+C로 끝내야 했습니다.
- 열린 문서 조회가 첫 번째 Excel 인스턴스만 보지 않고 모든 인스턴스를 찾습니다.
- `errors_*.txt`에 "러너 자동 복구와 창/프로세스 정리"(다시 연 문서, 닫은 문서, Quit/WM_CLOSE를 보낸 PID와 창, 보호한 PID)와 "도구 오류 로그"(이번 실행 중 `<테스트 폴더>/_data/logs/errors.txt`에 추가된 부분) 절을 넣습니다. 종료 정리 뒤에 한 번 더 써서 정리 기록까지 담습니다.

### 테스트
- (회사 PC 2차 실기 후 보완) 테스트용 docx를 폴더 템플릿으로 만들 때, 폴더에서 빠진 파일(회사 PC: `docProps/thumbnail.jpeg`)을 가리키는 관계는 빼고 엽니다 (`tests/sample_docs.py`). 도구 동작은 바뀌지 않습니다.
- DRM PC에서 python-pptx 기본 템플릿(`site-packages/pptx/templates/default.pptx`)이 zip이 아니라(암호화) `pptx.Presentation()`이 실패하던 문제(1 FAILED + 12 ERROR).
  템플릿이 필요한 테스트만 "python-pptx 기본 템플릿이 손상됨 (DRM 추정)"으로 건너뛰고, reader 샘플(docx/xlsx/pdf/eml/hwpx)은 형식별로 만들어 나머지 테스트는 그대로 돕니다.
  python-docx는 기본 .docx가 손상돼 있으면 폴더 템플릿(`docx/templates/default-docx-template`)으로 만듭니다 (`tests/sample_docs.py`). 도구 코드는 인자 없는 `Presentation()`/`Document()`를 쓰지 않습니다.

## [1.2.0] - 2026-10-28

저장소 지침(AGENTS.md 2026-10-28) 반영 1차: 사용자 확인 없이 덮어쓰거나 추측하던 동작을 멈춥니다.
근거 `docs/COMPLIANCE_REVIEW_2026-10-28.md` 2절, 구현 `CLI/README.md` R8(`[추천]`/`[후보]`).

### 기능 (추가만, 기존 인자·키 유지)
- 후보가 둘 이상이라 도구가 고를 수 없을 때의 오류 형식: `error_type: "ambiguous"`, `candidates`(최대 10개), message 끝 `[후보] a, b, c`,
  directive `STOP_RETRY: 후보가 여러 개라 ... 재시도하지 말고 [후보]를 사용자에게 보여주고 고르게 한 뒤 ...`. SKILL.md 결과 처리 표에 추가.
- `excel.py write --new-sheet`: 없는 시트를 새로 만들어 쓸 때만 붙입니다. 이미 있는 이름에 붙이면 만들지 않고 오류.
- `word.py write --occurrence N`, `office.py transfer --occurrence N`: `--anchor`가 여러 단락에 있을 때 몇 번째 단락인지 (오류의 `[후보]` 번호).
- `office.py transfer --to excel --overwrite`: `--sheet`로 준 시트가 이미 있을 때 그 시트에 덮어쓰기.

### 수정 (동작 변경)
- `excel.py write --sheet`(또는 `--range '시트'!A1`)에 없는 시트 이름을 주면 그 이름으로 새 시트를 조용히 만들던 문제. 오타가 새 시트가 되었습니다.
  이제 만들지 않고 오류를 냅니다.
  - 대소문자·공백·`_-.`만 다른 시트가 하나면 `[추천]` (예: `Sheet 1` -> `Sheet1`).
  - 비슷하지만 다른 이름이면 `[후보]`로 사용자에게 고르게 합니다 (예: `Sheet2`를 `Sheet1`의 오타로 단정해 덮어쓰지 않음).
  - 비슷한 것이 없으면 기존 시트 목록과 `--new-sheet` 안내.
- `office.py transfer --to excel --sheet 이름`에 이미 있는 시트를 주면 A1부터 덮어쓰던 문제. 덮어쓰지 않고 비어 있는 이름을 `[추천]`합니다(`--overwrite`로 덮어쓰기). `--sheet`를 생략하면 지금처럼 새 시트(`Word 내용 2` 등).
- `word.py write --anchor`가 여러 단락에 맞으면 첫 번째를 고르고, `--pos replace`면 그 단락을 지우던 문제. 아무것도 바꾸지 않고 `[후보]`(번호와 단락 앞부분 30자)로 오류를 냅니다. 같은 단락에 여러 번 나오면 한 곳으로 셉니다.
  `office.py transfer --anchor`도 같습니다. 이 오류는 차트 전달 방식을 바꿔도 같으므로 다음 방식으로 넘어가지 않습니다.
- `--anchor`를 찾지 못하면 문서에서 가장 비슷한 문구(그대로 다시 찾을 수 있는 원문 일부)를 안내합니다.
  공백·대소문자만 다를 때, 또는 앵커 글자 사이에 2자 이하만 끼어들고(`2026 계획` -> `2026년 계획`) `--pos replace`가 아닐 때만 `[추천]`.
  글자가 바뀌거나 빠진 문구(`Q2` -> `Q1`)는 뜻이 다를 수 있어 `[추천]` 없이 "비슷한 문구: ..."로만 알립니다.

### 실기 테스트 러너
- I그룹이 미리 만들지 않은 `I_DATA`, `I_BIG` 시트에 쓰던 첫 write에 `--new-sheet` 추가 (1.2.0 동작 변경으로 실패하던 문제).

### 다음으로 미룸
- `--save`(CSV/MD/텍스트)와 COM 내보내기가 기존 출력 파일을 덮어쓰는 문제는 공통 런타임 반영(R4) 때 함께 처리 (남은 할 일).
- 열린 문서 이름(`--target 보고.xlsx`, `office.py focus --name`)이 여러 문서에 맞으면(다른 폴더의 같은 파일명, 다른 Excel 창의 `Book1`) 첫 번째를 고르던 문제. `[후보]`(전체 경로)로 오류를 냅니다. 전체 경로를 주면 그 문서로 정해집니다.

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
- Windows 실기 검증: 집 PC(Office 2007)에서 A~F, H 자동 판정 통과(1.0.1). 회사 PC(Office 16) 1차(1.2.0)는 A5 정리가 A.xlsx를 닫아 중단, D1·D4(PDF)와 G1·G2·G4는 통과. 남은 것: 1.2.1로 회사 PC 전체 재실행(`errors_*.txt`의 정리 기록에서 A5가 두 번째 Excel PID만 끝냈는지 확인), 눈 확인 항목.
- 실제 HWP 5.0 파일과 DRM 문서로 `reader.py` 검증.
- 회사 PC에서 `office.py transfer --probe` 결과 확인. (집 PC Office 2007: export, redraw 성공 / relay는 "워드에 붙여넣기 안 됨"으로 실패)
- 남은 Office 2007 실기 확인: `.xls/.doc/.ppt`(OOXML 아님)는 문서 식별값이 없어 같은 경로 새 파일 판별을 하지 않습니다.

### 저장소 지침 반영 (AGENTS.md, 2026-10-28)
상세 근거: `docs/COMPLIANCE_REVIEW_2026-10-28.md`. 공통 키·함수는 `CLI/README.md` "공통 런타임 구현 규칙"(R1~R9)대로 구현. 우선순위 순.
- [ ] `_runtime.ok()`의 `VERIFIED:` 강제 제거. 쓰기 명령은 저장 후 다시 읽어 확인(값·단락·도형 수, 출력 파일 존재·크기)한 경우만 `VERIFIED:`. "다시 읽어서 확인하지 마세요" 문구 수정 (excel.py:513, word.py:445, ppt.py:623, office.py:570)
- [ ] 결과 JSON `recovered` 배열: 잠금 새 이름 저장, transfer 방식 대체, 색인 재생성, 오래된 스냅샷 정리 (공통 수집기는 `_runtime`)
- [ ] `require_lib()`: openpyxl(excel.py:215, reader.py:382), python-docx(reader.py:291, office.py:465), python-pptx(reader.py:329,346) 실패 시 STOP_RETRY + `python -m pip install ...` (회귀 테스트)
- [ ] COM 호출 거부(0x8001010A, 0x80010001) 재시도 `com_retry`를 `_office.py`에 (횟수·시간 상한, 넘으면 기존 office_busy STOP_RETRY)
- [ ] `remove_tree` 추가, `os.remove`(_office.py:314, _runtime.py:311, word.py:593)와 undo 복원 `shutil.copy2`(office.py:709,715,721)에 적용. retry_fs는 일시적 오류만 재시도
- [ ] COM 내보내기(excel.py:781,802; word.py:577,584; ppt.py:741,750; office.py:124)를 `save_with_lock_fallback`으로, 기존 출력 파일은 새 이름 저장 + `recovered`
- [ ] `--save`(read --save, export .csv/.md, `write_csv_rows`/`write_text`, `resolve_output_path`)가 기존 파일을 덮어쓰는 문제: R4대로 기존 파일이면 새 이름 저장 + `recovered`, `--overwrite`일 때만 덮어쓰기
- [ ] `--dry-run`: excel replace/range clear·move/sheet delete/chart delete --all, word replace/write --pos replace, ppt replace/slide delete·clear. 스냅샷이 없는 쓰기는 `undo_available: false`
- [ ] 빈 결과 `count: 0` + "찾은 항목 없음": excel read 빈 범위, word/ppt/reader read 0단위, reader list, outlook list, office windows, info --all, chart list, undo --list
- [ ] 잘리는 결과에 `truncated` + 전체 결과 파일 경로: excel read --search(50), excel replace cells(30), reader search(--save도 전체 hits), reader list(100), undo --list(20), outlook list/search. `body_truncated` 옆에 `truncated`
- [ ] next_commands: excel write 자리표시 `--title 차트` 제거(excel.py:509), word.py:136·ppt.py:183 transfer 명령에 `--from-target`
- [ ] `-h/--help` 출력을 stderr로 (stdout은 JSON 1줄)
- [ ] tools/run_win_tests.py `--agent` 모드: JsonArgumentParser와 최상위 예외 처리, 로그 태그 `[준비]` `[주의]` `[확인]` -> `[INFO]` `[WARN]`
- [ ] .md 문자 규칙: 유니코드 화살표 26개 -> `->` (SKILL.md:44, README.md:69,133-135,140, TEST_CHECKLIST.md:34, WORK_PLAN.md 7곳), 원문자 -> `1.` `2.` (WORK_PLAN.md:195)
- [ ] `_STOP_RETRY_ERRORS`에서 ValueError/KeyError 제외 (_runtime.py:79-80)
- [ ] pyproject.toml `target-version = "py313"`
- [ ] 인자 alias 정리(추가만): `-r`/`-c`/`-n` 충돌, `--limit` 대 `--top`, `--pages` 대 `--slides`
