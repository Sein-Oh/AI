# doc-classifier

Windows 11에서 지정한 폴더(하위 전체)의 파일을 **목록화 -> 파일명으로 분류 -> 표본만 살짝 읽어 확인 -> 엑셀 보고서**까지 하는 CLI 도구입니다.
12TB급 로컬 디스크(네트워크 공유 중)에서도 PC와 공유 사용자를 방해하지 않도록 설계했습니다. 설계와 진행 단계는 [WORK_PLAN.md](WORK_PLAN.md).

| 단계 | 명령 | 디스크 접근 |
|---|---|---|
| 1. 목록화 | `scan`, `jobs` | 폴더 목록만 (파일을 열지 않음) |
| 2. 파일명 분류 | `classify --rules rules.json` | 없음 (DB만) |
| 3. 표본 확인 | `peek` | 분류별 표본만, 앞부분만 |
| 4. 요약/엑셀 보고서, 조회 | `summary --save`, `list` | 없음 (DB만) |

```bat
python doc_classifier.py scan     --root "D:\자료" --job 자료
python doc_classifier.py classify --job 자료 --rules 내규칙.json
python doc_classifier.py peek     --job 자료
python doc_classifier.py summary  --job 자료 --save
python doc_classifier.py list     --job 자료 --category 계약서 --ext hwp --since 2025-01
```

## 1. 설치

표준 환경(WinPython, Python 3.13.13)에 이미 있는 라이브러리만 씁니다. 회사 PC에는 WinPython 폴더를 복사하고 이 폴더를 그대로 두면 됩니다.
- 목록화·분류·조회: 표준 라이브러리(sqlite3, os, ctypes)만.
- 확인(peek): pymupdf(PDF), olefile(HWP, 옛 Office), openpyxl(xlsx). docx/pptx/hwpx는 표준 zipfile로 앞부분만 읽습니다.
- 엑셀 보고서: openpyxl. 없으면 JSON 오류로 설치 명령을 안내합니다.

## 2. scan (목록화)

```bat
python doc_classifier.py scan --root "D:\자료"
python doc_classifier.py scan --root "D:" --job 회사D --time-limit 3600      :: 1시간마다 끊어서
python doc_classifier.py scan --job 회사D --resume --time-limit 3600         :: 이어서
python doc_classifier.py jobs
```

| 옵션 | 뜻 |
|---|---|
| `--root` | 목록을 만들 폴더 (`D:`, `D:\자료`). 공유 폴더가 있는 PC에서는 UNC가 아니라 로컬 경로로 실행 |
| `--job` | 작업 이름 (생략 시 `폴더명_날짜`). 작업마다 DB 파일 1개: `data\<작업>.db` (`DOCCLS_DATA_DIR`로 바꿈) |
| `--resume` | 끝나지 않은 작업을 이어서 (`--job` 없이 `--root`만 줘도 같은 폴더의 미완료 작업을 찾음) |
| `--overwrite` | 같은 이름의 작업을 지우고 처음부터 |
| `--exclude 패턴` | 제외할 경로 패턴 (여러 번, 대소문자 무시, 예: `*\node_modules*`, `*.tmp`) |
| `--max-depth N` | 이 깊이까지만 (대상 폴더 = 0) |
| `--max-files N`, `--time-limit 초` | 이번 실행 상한. 넘으면 저장하고 멈춤(`complete: false`, 이어서 명령 제공) |
| `--throttle-ms N` | 폴더마다 쉬기 (디스크 부하를 더 줄일 때) |
| `--include-system` | 드라이브 바로 아래 Windows, Program Files, ProgramData 등도 포함 |
| `--include-cloud` | 클라우드 자리표시자 폴더에도 들어감 (그 안의 파일은 여전히 열지 않음) |
| `--priority background\|normal` | 기본 background: CPU·디스크 I/O 우선순위를 낮춤 |

### 동작
- **파일을 열지 않습니다.** 폴더 목록 정보(이름, 크기, 수정일, 만든 날짜, 속성)만 읽으므로 다른 사람이 쓰고 있거나 잠긴 파일도 그대로 목록에 들어갑니다.
- **메모리 일정**: 결과와 방문할 폴더 대기열을 모두 SQLite에 묶음 단위로 기록합니다. 파일 수가 늘어도 메모리가 거의 늘지 않습니다.
- **중단해도 이어서**: 폴더 하나를 끝까지 읽어야 그 폴더의 결과가 함께 저장됩니다. Ctrl+C, 강제 종료, 상한 어느 경우든 `--resume`으로 중복 없이 이어집니다. Ctrl+C면 exit 130 + `STOP_RETRY` + 이어서 명령.
- **들어가지 않는 폴더** (결과 `skipped`에 이유와 예시):
  - `link`: 정션·심볼릭 링크 (반복·중복 방지)
  - `cloud`: 클라우드 자리표시자/오프라인 폴더 (열면 내려받기)
  - `system`: `$Recycle.Bin`, `System Volume Information` 등, 드라이브 바로 아래 Windows/Program Files/ProgramData 등, 숨김+시스템 폴더
  - `excluded`, `max_depth`: 옵션에 따른 제외
- **열면 안 되는 파일 표시**: 클라우드 자리표시자, 오프라인, 링크 파일은 목록에 넣되 `no_read=1`. peek에서 절대 열지 않습니다.
- **읽을 수 없는 폴더**(권한 없음 등)는 `errors`에 기록하고 계속합니다. 260자 넘는 경로도 처리합니다.
- 진행 로그는 stderr에 2초마다 `[PROGRESS] 폴더 N개, 파일 M개, 용량, 초당 K개`.
- 끝나면 `next_commands`로 분류 명령 2개를 줍니다: `[0]` 사용자 규칙 파일(`needs_input`), `[1]` 예시 규칙.

결과 JSON 주요 키: `job`, `db_file`, `root`, `complete`, `stopped_reason`(`max_files`/`time_limit`/`interrupted`), `this_run`, `totals`, `by_extension`, `skipped`/`errors`, `priority`, `peak_memory_mb`, `next_commands`.

## 3. classify (파일명 분류)

디스크를 읽지 않고 DB의 이름 정보만 씁니다. 규칙을 바꿔 여러 번 다시 돌려도 빠릅니다(가짜 100만 행 약 45초, 메모리 90MB 미만).

```bat
python doc_classifier.py classify --job 자료 --rules 내규칙.json
python doc_classifier.py classify --job 자료                   :: --rules 생략: 지난번 규칙 파일, 처음이면 rules.example.json
```

### 규칙 파일 (JSON)
```json
{
  "계약서": ["계약", "협약", "MOU"],
  "회의록": ["회의록", "회의자료"],
  "도면": [".dwg", ".dxf"],
  "인사": {"keywords": ["인사발령", "채용"], "exclude": ["계약직 채용공고"]}
}
```
- `.`으로 시작하면 **확장자**(정확히 일치), 그 외는 **글자 포함** 키워드입니다. 예시: [rules.example.json](rules.example.json).
- 비교할 때 대소문자, 한글 자모 분리(맥 파일명, NFC 정규화), 공백·`_`·`-` 차이는 무시합니다 (`시험 성적서` = `시험_성적서` = `시험성적서`).
- **영문·숫자 4글자 이하 키워드**(`PO`, `MOU`, `spec`)는 단어로만 비교합니다: 앞뒤가 영문자가 아니어야 맞습니다(`report` 속 `po`, `inspection` 속 `spec`은 안 맞음. `PO_2026`, `발주PO`는 맞음).
- 확장 형식 `{"keywords": [...], "exclude": [...]}`: `exclude` 글자가 파일명이나 폴더명에 있으면 그 카테고리에서 뺍니다.
- 오류(문법, 빈 목록, 문자열이 아닌 키워드, 같은 카테고리 두 번, `미분류`라는 이름)는 줄·위치를 짚어 `STOP_RETRY`. 1글자 키워드는 `[WARN]`.

### 점수와 결정
| 어디서 맞았나 | 점수 |
|---|---|
| 확장자 | 3 |
| 파일명(확장자 제외) | 2 |
| 바로 위 폴더 이름 | 1 |
| 더 위 폴더 이름 (대상 폴더 자신과 그 위는 보지 않음) | 0.5 |

- 키워드 하나는 가장 높은 위치에서 한 번만 세고, 같은 카테고리의 여러 키워드는 합산합니다.
- 1위가 `category`. 동점이면 **JSON에 먼저 적은 카테고리**. 아무것도 안 맞으면 `미분류`.
- 신뢰도: 2위가 없으면 1위 점수 2 이상 `high`, 1 이상 `medium`, 그 밖 `low`. 2위가 있으면 점수 차 2 이상 `high`, 1 이상 `medium`, 그 밖 `low`.
- 근거(`matches`): 상위 3개 카테고리의 점수와 맞은 키워드·위치. 엑셀에는 `계약서 4점(계약@파일명, .hwp@확장자)`처럼 표시.

### 함께 기록 (규칙과 무관)
- 형식(`kind`): 문서, 표, 발표, PDF, 한글, 메일, 이미지, 도면, 압축, 코드/데이터, 미디어, 실행파일, 임시/시스템, 기타.
- 파일명 속 정보: 날짜(`20260301`, `2026-03`, `26년 3월`, `260301` -> `2026-03-01`/`2026-03`/`2026`), 버전(`v2`, `rev3`, `최종`, `최최종`, `초안`, `final`), 표시(`copy`: `복사본`, `(1)`; `temp`: `~$`, `.tmp`, `.bak`).
- 중복 후보: 같은 이름(대소문자 무시) + 같은 크기 묶음 수, 줄일 수 있는 용량, 큰 순서 예시 200개 (내용 해시는 하지 않으므로 후보일 뿐).
- 규칙 보완용: 카테고리별로 가장 많이 맞은 키워드, 미분류 파일명에 자주 나오는 단어.
- 규칙이 바뀌면 이전 peek 결과는 판정 기준이 달라졌으므로 지웁니다(preview에 알림). 같은 규칙으로 다시 돌리면 유지.
- 목록화가 끝나지 않은 작업도 분류할 수 있습니다(지금까지 목록화된 파일만). 나중에 scan을 이어서 하면 summary가 다시 classify하라고 알려 줍니다.
- 0.1.0으로 목록화한 DB도 다시 scan하지 않고 그대로 classify할 수 있습니다(열을 추가만 함).

결과 JSON 주요 키: `rules_file`, `rules_warnings`, `scan_complete`, `this_run`, `by_category`(파일 수, 용량, 비율, high/medium/low), `by_kind`, `keyword_hits`, `unclassified_words`, `duplicates`, `peek_estimate`, `next_commands`(peek, summary).

## 4. peek (표본만 살짝 읽어 확인)

```bat
python doc_classifier.py peek --job 자료
python doc_classifier.py peek --job 자료 --per-category 50 --max-files 1000 --timeout 10 --time-limit 1800
```

| 옵션 | 뜻 |
|---|---|
| `--per-category N` | 카테고리마다 확인할 표본 수 (기본 20, 미분류 포함). 이미 확인한 표본은 다시 읽지 않고 모자란 만큼만 더 고름 |
| `--max-files N` | 이번 실행 전체 상한 (기본 500). 카테고리를 돌아가며 하나씩 배분 |
| `--timeout 초` | 파일당 시간 상한 (기본 10). 넘으면 `timeout`으로 기록하고 다음 파일 |
| `--max-mb N` | 이보다 큰 파일은 표본에서 뺌 (기본 200MB) |
| `--time-limit 초` | 이번 실행 시간 상한. 넘으면 멈춤(`complete: false`), 같은 명령으로 이어서 |
| `--throttle-ms N` | 파일마다 쉬기 |
| `--redo` | 이전 확인 결과를 지우고 표본을 새로 고름 |

### 표본 고르기
- 열지 않음(`no_read`: 클라우드 자리표시자, 오프라인, 링크), 임시 파일, 크기 상한 초과, 내용을 읽지 않는 형식(이미지, 압축 등)은 표본에서 뺍니다.
  단, 확장자만으로 분류하는 카테고리(예: 도면 `.dwg`)는 파일 앞부분 서명만 읽어 형식을 확인합니다.
- 신뢰도 `low` -> `medium` -> `high` 순, 같은 신뢰도 안에서는 여러 폴더에 고르게 퍼지도록 섞은 순서. 읽기는 폴더 순서로(디스크 이동 줄이기).

### 읽는 양 (앞부분만)
| 형식 | 읽는 것 |
|---|---|
| PDF | 첫 2쪽 텍스트 (pymupdf) |
| DOCX | 앞 단락 20개 (zip 안 XML을 앞에서부터 흘려 읽고 멈춤) |
| PPTX | 앞 슬라이드 10장의 글자 |
| XLSX | 시트 이름 + 시트마다 첫 10행 (5개 시트까지, openpyxl 읽기 전용) |
| HWP 5.0 | 미리보기 텍스트(`PrvText`), 없으면 첫 구역 본문 앞부분 |
| HWPX | `Preview/PrvText.txt`, 없으면 첫 구역 앞부분 |
| TXT, CSV, MD, LOG, JSON, XML, HTML | 앞 8KB (UTF-8/BOM/UTF-16/CP949 자동) |
| EML | 제목, 보낸·받는 사람, 본문 앞부분 (앞 64KB) |
| DOC, XLS, PPT, MSG (옛 Office) | 본문 스트림에서 글자만 대략 뽑음 (형식 해석 없이 UTF-16 한글·영문) |

- 읽기는 **별도 작업 프로세스**가 합니다. 시간 상한을 넘기거나 작업 프로세스가 죽으면 그 프로세스를 끝내고 새로 띄워 다음 파일로 갑니다. 깨진 파일이나 거대한 파일이 전체를 멈추지 못합니다.
- 작업 프로세스도 백그라운드 우선순위로 돕니다. 파일은 읽기 전용, 다른 프로세스의 읽기·쓰기를 막지 않는 방식으로만 엽니다. 열기 직전에 속성을 다시 확인해 그 사이 클라우드 자리표시자가 된 파일은 열지 않습니다.
- DRM/암호: 파일 앞부분 서명이 형식과 다르면(docx인데 ZIP이 아님, hwp인데 OLE가 아님 등) `encrypted_or_drm`. 암호 PDF, 암호/배포용 HWP, 암호 Office도 같은 상태. 회사 PC처럼 DRM 문서가 라이브러리로 바로 읽히는 환경에서는 그대로 읽습니다.

### 판정
| 상태 | 뜻 |
|---|---|
| `confirmed` | 본문에 그 카테고리 키워드가 있고 다른 카테고리보다 적지 않음. 확장자 카테고리는 파일 서명이 맞음 |
| `changed` | 다른 카테고리 키워드가 더 많음 -> `peek_category`에 제안 (미분류였다면 새 분류 후보) |
| `no_match` | 본문 앞부분에 규칙 키워드가 없음 |
| `no_text` | 글자가 없음 (스캔 PDF, 빈 파일) |
| `encrypted_or_drm`, `unreadable`, `timeout`, `missing`, `skipped`, `not_checked` | 읽지 못함 (이유는 `peek_reason`) |

- 확인율 = `confirmed / (confirmed + changed + no_match)`. 확인율이 낮은 분류(표본 3개 이상, 50% 미만)는 `weak_categories`와 summary `recommendations`에 나옵니다.
- DB에는 판정, 이유, 발췌(앞 200자), 읽은 시간만 남기고 원문은 저장하지 않습니다.
- 파일을 읽으면 NTFS 마지막 접근 시각이 바뀔 수 있습니다(대용량 볼륨은 Windows가 보통 갱신을 끔). 수정 시각과 내용은 바뀌지 않습니다.

## 5. summary (요약, 엑셀 보고서)

```bat
python doc_classifier.py summary --job 자료                       :: JSON 요약만
python doc_classifier.py summary --job 자료 --save                :: data\자료_보고서.xlsx
python doc_classifier.py summary --job 자료 --save "D:\보고\자료.xlsx" --file-list csv
```

- JSON: `totals`, `by_category`(파일 수, 비율, 용량, 신뢰도 분포, 많이 모인 폴더 3개), `by_kind`, `top_folders`(대상 폴더 바로 아래 폴더별), `age`(수정 시기), `duplicates`, `unclassified_words`, `peek`(확인 결과), `recommendations`(규칙 보완 등 권장 사항), `truncated`. LLM에 맞게 상위 N개로 자릅니다(`--top`).
- 엑셀 시트: `요약`(항목, 카테고리별, 형식별, 수정 시기, 권장 사항), `카테고리별`(카테고리마다 상위 폴더 30개와 많이 모인 폴더 20개), `확인 결과`(peek 표본, 판정, 제안, 발췌, 이유), `미분류 단어`(규칙 보완용 + 키워드별 맞은 수), `중복 후보`, `오류·건너뜀`, `파일 목록`(경로, 형식, 카테고리, 신뢰도, 근거, 크기, 날짜, 이름 속 날짜/버전/표시, 확인 결과).
- 파일 목록(`--file-list auto`): **10만 행 이하**면 엑셀 `파일 목록` 시트에 넣고, **넘으면** 엑셀에는 요약 시트만 두고(`요약` 시트에 CSV 이름 표시) 목록은 CSV로 따로 저장합니다.
  - CSV는 UTF-8 BOM이라 엑셀에서 바로 열리고, 엑셀 한도(1,048,575행)마다 파일을 나눕니다: 한 개면 `<보고서>_파일목록.csv`, 여러 개면 `<보고서>_파일목록_1.csv`, `_2.csv` ... (파일마다 머리글).
  - 같은 이름으로 다시 저장해 나눈 개수가 줄면, 이전 실행의 남는 목록 CSV는 지웁니다.
  - 결과 JSON `report.file_list_files`에 CSV 경로 전체, `report.file_list_csv`에 첫 파일.
  - 이유: 엑셀(xlsx) 쓰기가 CSV보다 6~8배 느리고 큰 시트는 열기도 어렵습니다. HTML도 검토했으나 10만 행에서 브라우저 여는 데 95초, 100만 행은 메모리 13.7GB 후 멈춰 쓰지 않습니다.
  - `--file-list xlsx|csv|none`으로 직접 정할 수 있습니다(`xlsx`는 시트 한도마다 `파일 목록 2`, `3`...으로 나눔).
- 쓰기 전용 모드로 메모리 일정. 가짜 100만 행: 보고서 + 목록 CSV 37초(이전 엑셀 시트 방식 206초).
- 같은 이름의 보고서가 엑셀에 열려 있으면(잠김) `이름_시각.xlsx`로 따로 저장하고 `[WARN]`. 파일명이 `=`로 시작해도 수식으로 바뀌지 않습니다.

## 6. list (조건 조회)

```bat
python doc_classifier.py list --job 자료 --category 회의록 --ext hwp,hwpx --since 2025-01
python doc_classifier.py list --job 자료 --folder "D:\자료\영업" --sort size --desc
python doc_classifier.py list --job 자료 --category 미분류 --page 2
```

| 옵션 | 뜻 |
|---|---|
| `--category` | 카테고리 (쉼표로 여러 개, `미분류` 가능). 없는 이름이면 `[추천]` |
| `--ext`, `--kind` | 확장자(`hwp,.pdf`), 형식(`문서`, `한글`, `도면` ...) |
| `--confidence`, `--peek` | 신뢰도(`high/medium/low`), 확인 결과(`any`, `confirmed`, `changed` ...) |
| `--since`, `--until` | 수정일 (`2025`, `2025-03`, `2025-03-15`, 끝 날짜 포함) |
| `--folder` | 절대 경로면 그 폴더와 하위 폴더, 아니면 경로에 포함된 글자 |
| `--name`, `--min-size`, `--flag` | 파일명 글자, 최소 크기(`100MB`), 표시(`copy`/`temp`) |
| `--sort path\|size\|mtime\|name`, `--desc` | 정렬 |
| `--page`, `--page-size` | 페이지 (기본 100행, 최대 1000) |

- 결과: `total`, `total_size`, `page`, `pages`, `items`(경로, 크기, 수정일, 형식, 카테고리, 신뢰도, 확인 결과), `next_commands`(다음 페이지, atomic-cli `reader.py read`로 내용 읽기).
- 분류 전에도 `--ext`, `--folder` 등 목록 정보 조회는 됩니다.

## 7. DB 구조 (`data\<작업>.db`)
- `meta`: 대상 폴더, 옵션, 상태(`scan_status`, `classify_status`), 규칙(원문과 경로), 키워드 통계, 미분류 단어, 중복 후보 요약, peek 수
- `dirs`: 폴더 경로, 깊이, 상위 폴더(`top_id`), 상태(`pending`/`done`/`skipped`/`error`), 이유, 파일 수, 용량
- `files`: 폴더 id, 이름, 확장자(소문자, `.pdf`), 크기, 수정일, 만든 날짜, 속성, 표시, `no_read`,
  `kind`, `category`, `confidence`, `matches`(JSON: `[[카테고리, 점수, ["키워드@위치"]]]`, 위치 `e` 확장자/`n` 파일명/`d1` 바로 위 폴더/`d2` 더 위 폴더),
  `name_date`, `name_version`, `name_flags`, `peek_status`, `peek_category`, `peek_reason`, `peek_excerpt`, `peek_ms`
- 색인: `files(dir_id)`, `files(category)` (classify가 만듦)

## 8. 테스트

```bat
python -m pytest -q CLI/doc-classifier           :: 오프라인 (Linux에서도 동작)
python CLI/doc-classifier/tools/run_win_tests.py  :: Windows 실기 (S1~S9 목록화, S10~S15 분류/확인/보고서)
```
