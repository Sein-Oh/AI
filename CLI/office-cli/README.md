# office-cli 1.1

Excel, Word, PowerPoint, Outlook을 AI 에이전트(26B~30B 경량 LLM)가 명령 한 줄로 다루게 하는 CLI 도구입니다.
PDF, HWP, EML, Office 파일은 Office 없이 읽고 검색합니다.

- 에이전트용 요약: [`SKILL.md`](SKILL.md)
- 변경 이력과 남은 할 일: [`CHANGELOG.md`](CHANGELOG.md)
- 설계 배경과 결정 기록: [`WORK_PLAN.md`](WORK_PLAN.md)

## 1. 구성

```text
CLI/office-cli/
├── excel.py     엑셀   read / info / write / replace / style / export / sheet / range / chart
├── word.py      워드   read / info / write / replace / export
├── ppt.py       PPT    read / info / write / replace / export / slide
├── outlook.py   메일   list / search / read / current / folders / new / reply / forward
├── reader.py    파일   read / search / list   (Office 불필요: PDF, HWP, HWPX, EML, DOCX, PPTX, XLSX, CSV, TXT, MD)
├── office.py    공통   windows / focus / transfer / undo
├── _runtime.py  공통 런타임 (응답 계약, 경로, 입출력, 마크다운 해석)
├── _office.py   Office COM 공통 (세션, 스냅샷, 색/테마)
├── tools/run_win_tests.py  Windows 실기 테스트 러너
├── tools/office-cli-test/SKILL.md  실기 테스트를 에이전트가 돌리는 스킬 (스킬 폴더에 office-cli 옆으로 복사)
└── tests/       오프라인 테스트 (가짜 COM + 실제 샘플 파일)
```

설치 (폐쇄망은 [`docs/WINDOWS_OFFLINE.md`](../../docs/WINDOWS_OFFLINE.md) 참고):
```bat
python -m pip install -r CLI/office-cli/requirements.txt -c constraints.txt
```

## 2. 공통 규칙

### 출력 계약 (저장소 ACI 계약)
- stdout은 정확히 1줄 JSON입니다. 진행 로그는 stderr(`[PROGRESS]`, `[WARN]` 등)입니다.
- 종료 코드: 0 성공, 1 오류, 2 인자 오류, 130 중단.
- `agent_directive`:
  - `VERIFIED:` 완료
  - `STOP_RETRY:` 입력이나 대상 문제. `[추천]`이 있으면 그 값으로 1회만 다시 시도
  - `ERROR:` 내부 오류
- 공통 키: `status`, `tool`, `command`, `preview`, `agent_directive`. 오류 시 `error_type`, `message`가 추가됩니다. COM 오류는 `hresult`도 들어갑니다.
- `target_resolved`: 실제로 작업한 문서(앱, 이름, 경로, 시트/슬라이드)
- `next_commands`: 이어서 실행할 명령 `[{purpose, command}]`. 완성된 형태라 그대로 실행하면 됩니다.

### 대상 문서 (`--target`)
| 값 | 의미 |
|---|---|
| `active` (기본) | 그 앱에서 사용자가 보고 있는 문서 |
| 열린 문서 이름 | 예: `보고.xlsx` (대소문자 무시) |
| 파일 경로 | 닫힌 파일. 읽기는 라이브러리로, 쓰기는 사용자 창과 분리된 백그라운드 인스턴스로 열고 저장 후 닫음 |

### 화면과 안전
- **읽기는 화면을 움직이지 않습니다.** 활성 시트, 스크롤, PPT 슬라이드가 그대로입니다.
- **쓰기는 고친 시트/슬라이드로만 이동합니다.** `--no-focus`를 주면 이동하지 않습니다.
- **쓰기 전 스냅샷을 자동으로 만듭니다**(문서별 5개 보관, 50MB 초과 문서는 생략). 같은 경로에 다른 문서를 새로 만들면 이전 문서의 스냅샷은 되돌리기 대상에서 빠집니다(파일 속 만든 시각으로 판별).
  - 원본 문서는 저장하거나 경로를 바꾸지 않습니다.
  - `office.py undo`로 되돌립니다.
- **읽기는 아무것도 만들거나 저장하지 않습니다.** 없는 시트나 파일을 지정하면 `[추천]`과 함께 오류를 냅니다.
- **메일**: 기본은 작성 창만 띄웁니다. `--send`는 명시했을 때만 쓰고, 수신자 주소를 확인한 뒤 발송합니다.

### 파일과 폴더
| 항목 | 기본 위치 | 바꾸는 방법 |
|---|---|---|
| data 폴더 (파일명만 쓴 입력/출력) | `<도구폴더>\data` | 환경변수 `OFFICE_CLI_DATA_DIR` 또는 `config.json`의 `data_dir` |
| 작업 폴더 (`--save` 경로 생략 시, 7일 후 자동 정리) | `data\_work` | - |
| 캐시 (읽은 문서 색인, 스냅샷) | `<도구폴더>\cache` | `OFFICE_CLI_CACHE_DIR` 또는 `cache_dir` |
| 설정 (`transfer --probe` 결과 등) | `<도구폴더>\config.json` | - |

- 입력 파일은 절대경로 → data 폴더 → 작업 폴더 순서로 찾습니다. 없으면 비슷한 파일명을 `[추천]`으로 알려 줍니다.
- 텍스트 입력은 UTF-8, UTF-16, CP949를 자동으로 판별합니다. CSV 출력은 기본 utf-8-sig입니다(Excel에서 한글 정상).
- 결과가 길면 기본 200행 또는 약 8,000자에서 자르고 `truncated: true`와 이어 읽기 명령을 줍니다.

## 3. 명령 요약

### excel.py
| 명령 | 주요 옵션 |
|---|---|
| `read` | `--range`, `--sheet`, `--search 글자`(셀 주소 반환), `--max-rows`, `--save [경로.csv]` |
| `info` | 시트별 사용 범위와 차트. `--all`: 열린 통합문서 전체. `--detail`: 차트 종류·계열 수·위치와 데이터를 가리는 차트 경고 |
| `write` | `--range` 시작 셀 또는 범위. 입력은 `--value`, `--values JSON`, `--file (.csv/.md 표/.txt)`, `--formula F1 [F2 ...]` 중 하나. `--header "a,b"`, `--append`(같은 머리글 생략), `--sheet`(없으면 생성) |
| `replace` | `--find/--replace` 또는 `--map JSON`, `--whole`, `--all-sheets`, 서식 옵션. 수식 셀은 내용 보존 |
| `style` | `--theme navy\|slate\|teal\|emerald`, `--bg`, `--color`, `--bold`, `--align`, `--number-format`, `--border`, `--highlight ">=100:pink"`(조건부 서식), `--clear` |
| `export` | `--save 경로.csv\|.xlsx\|.pdf`, `--columns A,C,E` |
| `sheet` | `--action list\|add\|rename\|copy\|delete\|select --name --new-name` |
| `range` | `--action autofit\|width\|height\|merge\|unmerge\|freeze\|unfreeze\|hide\|unhide\|clear\|copy\|move\|border` |
| `chart` | `--action create\|list\|delete`, `--range`, `--type column\|bar\|line\|line_markers\|pie\|area\|scatter\|scatter_lines\|combo`, `--title`, `--at`, `--labels`, `--legend`, `--theme` |

- 수식이 1개면 범위 전체에 넣고 상대참조가 자동으로 조정됩니다. 여러 개면 열마다 하나씩 넣습니다.
- 첫 열이 숫자인 `line` 차트는 x축이 숫자 축이 되도록 `scatter_lines`로 그립니다(예: 사인 그래프).
- `--at`을 생략하면 차트는 시트의 데이터(사용 범위) 오른쪽에 놓여 다른 데이터를 가리지 않습니다.

### word.py
| 명령 | 주요 옵션 |
|---|---|
| `read` | `--start N`, `--save [경로.md]`. 제목 구조(개요 수준) 포함. 본문 그림은 `[그림]`으로 표시 |
| `info` | 쪽/단어/글자 수, 표, 그림, 제목 목록. `--all`. `--detail`: 그림 크기(쪽 너비 대비)와 제목 수준, 쪽보다 넓은 그림 경고 |
| `write` | `--text`(마크다운 자동 변환, 줄바꿈 `\n`), `--file (.md/.txt, .csv는 표)`, `--image`, `--width`, `--heading N`, `--title`, `--callout`, `--toc`, `--page-break`, `--anchor 글 --pos after\|before\|replace`, `--theme` |
| `replace` | `--find/--replace`(빈 문자열은 삭제) 또는 `--map`, `--match-case`, `--whole-word`, `--bold`, `--color`, `--highlight`. 머리글/바닥글/글상자 포함 |
| `export` | `--save 경로.pdf\|.docx`, `--page-number`(사본에만) |

### ppt.py
| 명령 | 주요 옵션 |
|---|---|
| `read` | `--slides 1-3`, `--save` |
| `info` | 슬라이드별 제목, 도형/표/그림 수. `--all`. `--detail [--slides 2-4]`: 도형별 위치·크기·글자 크기·목록 종류와 배치 경고(슬라이드 밖, 글자 넘침, 겹침) |
| `write` | `--slide N\|new`, `--title`, `--text`(`-` 줄은 글머리표, `1.` 줄은 번호), `--file (.md: 제목마다 새 슬라이드, .csv: 표)`, `--image`, `--cards "제목:내용\|..."`, `--theme` |
| `replace` | `--find/--replace` 또는 `--map`, `--slide`, 서식 옵션. 표와 그룹 도형 포함 |
| `export` | `--save 경로.pdf\|.pptx`. PDF 기능이 없는 Office(2007 기본 설치 등)는 `.pptx`로 저장하라는 STOP_RETRY를 돌려줍니다 |
| `slide` | `--action list\|add\|duplicate\|move\|delete\|clear --slide --to --layout`. `clear`는 `--slide` 또는 `--all-slides`가 필요 |

### outlook.py
- 조회: `list [--folder --unread --limit]`, `search --query [--from --where all|subject|body]`, `read --id [--save-attach --save]`, `current`, `folders`
- 작성: `new --to --subject --body [--cc --attach --body-file --send]`, `reply [--id --all --body]`, `forward [--id --to --body]`
- 첨부는 `data\_work\mail_attachments\`에 저장합니다. 같은 이름 첨부는 번호를 붙이고, 본문 삽입 이미지와 실행 파일 형식은 저장하지 않습니다.

### reader.py
- `read --file 경로 [--pages 1-3] [--format summary] [--save]`
- `search --query "A AND B" | "A OR B" [--regex --file 파일또는폴더 --top --full --save 결과.md|결과.csv]`
- `list`: 읽은 적 있는 문서(색인)
- 읽은 문서는 자동으로 캐시와 색인에 등록됩니다. 파일이 바뀌면 다시 읽습니다.
- DRM으로 암호화된 Office 파일은 라이브러리로 열 수 없으므로, `excel.py`/`word.py`/`ppt.py read --target 경로`로 Office에서 읽으라고 안내합니다.

### office.py
- `windows`: 열린 Office 문서 목록과 실행 중인 Office 버전, PDF 내보내기 가능 여부(`office`). PDF 기능이 없는 Office에서는 `export --save *.pdf`가 시도 없이 바로 안내합니다
- `focus --app excel|word|ppt [--name]`: 창을 앞으로 가져옵니다. 최대화 상태는 유지합니다.
- `transfer`: 아래 4절 참고
- `undo [--app] [--list] [--pick N]`

## 4. 앱 간 전달 (transfer)과 회사 DRM

| 전달 | 명령 | 방식 |
|---|---|---|
| 엑셀 차트 → 워드/PPT | `--from excel --chart 이름 --to word,ppt` | 그림 (아래 3방식) |
| 엑셀 범위 → 워드/PPT | `--from excel --range A1:D10 --to word` | 네이티브 표 (값 전달, 클립보드 없음) |
| 워드/PPT → 엑셀 | `--from word --what text\|table [--table N] --to excel` | 새 시트에 표로 |

차트 그림은 다음 순서로 자동 시도하고, 결과 JSON의 `method`에 실제로 쓴 방식을 적습니다.
1. `export`: Excel의 `Chart.Export` PNG를 씁니다. **파일 앞부분이 PNG가 아니면(DRM 암호화) 건너뜁니다.**
2. `redraw`: 차트의 계열 값을 COM으로 읽고 matplotlib으로 다시 그립니다. Python이 쓴 파일을 쓰고 클립보드는 쓰지 않습니다. 원본 서식은 근사치입니다.
3. `relay`: 엑셀 → 워드 → PPT 클립보드 경유입니다.

회사 PC에서 처음 한 번 `python office.py transfer --probe`를 실행하면, 세 방식을 실제로 시험해 대상 앱별로 되는 순서를 `config.json`에 저장합니다.

## 5. 체이닝 예

```bat
:: 사인 2주기 그래프 -> 워드/PPT
python excel.py write --range A1:B101 --header "x,sin(x)" --formula "=(ROW()-2)*4*PI()/99" "=SIN(A2)"
python excel.py chart --range A1:B101 --type line --title "사인 2주기"
python office.py transfer --from excel --chart "사인 2주기" --to word,ppt

:: 워드/PPT 내용 -> 엑셀
python office.py transfer --from word --what text --to excel
python office.py transfer --from ppt --what text --to excel

:: 문서 검색 -> 워드에 넣기
python reader.py search --query "마일스톤" --file "C:\docs\기획" --save
python word.py write --file "<결과의 output_file>"
```

## 6. 테스트

```bat
python -m pytest -q CLI/office-cli          :: 오프라인 (가짜 COM + 실제 샘플 파일)
python CLI/office-cli/tools/run_win_tests.py  :: Windows + Office 실기 (자세한 내용: TEST_CHECKLIST.md)
```
- 실기 테스트는 테스트 폴더에 `report_*.txt`(요약)와 `errors_*.txt`(분석용 상세 로그)를 남깁니다. 문제가 있으면 `errors_*.txt`를 그대로 Claude에게 전달하세요.
- OpenCode 에이전트에게 실기 테스트를 맡기려면 `tools/office-cli-test` 폴더를 스킬 폴더의 `office-cli` 옆에 복사합니다. 에이전트는 `--agent`로 실행해 결과 JSON 1줄만 읽습니다.
- 대상은 Office 16.0(2016/2019/2021/365)입니다. Word 2007의 `SaveAs2` 부재는 `SaveAs`로 대체하므로 Office 2007에서도 실기 테스트가 돕니다. 다만 PDF 추가 기능이 없으면 PDF 내보내기 항목은 `ENV-SKIP`으로 기록됩니다.
