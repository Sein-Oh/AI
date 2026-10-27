# doc-classifier

Windows 11에서 지정한 폴더(하위 전체)의 파일을 **목록화 -> 파일명으로 분류 -> 표본만 살짝 읽어 확인**하는 CLI 도구입니다.
12TB급 로컬 디스크(네트워크 공유 중)에서도 PC와 공유 사용자를 방해하지 않도록 설계했습니다. 설계와 진행 단계는 [WORK_PLAN.md](WORK_PLAN.md).

| 단계 | 명령 | 상태 |
|---|---|---|
| 1. 목록화 | `scan`, `jobs` | **구현 (0.1.0)** |
| 2. 파일명 분류 | `classify --rules rules.json` | 예정 ([rules.example.json](rules.example.json)) |
| 3. 표본 확인 | `peek` | 예정 |
| 4. 요약/엑셀 보고서 | `summary --save 보고서.xlsx`, `list` | 예정 |

## 1. 설치

표준 환경(WinPython, Python 3.13.13)에 이미 있는 라이브러리만 씁니다. 목록화는 표준 라이브러리(sqlite3, os, ctypes)만으로 동작합니다.
회사 PC에는 WinPython 폴더를 복사하고 이 폴더를 그대로 두면 됩니다.

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
- **열면 안 되는 파일 표시**: 클라우드 자리표시자, 오프라인, 링크 파일은 목록에 넣되 `no_read=1`. 다음 단계(peek)에서 절대 열지 않습니다.
- **읽을 수 없는 폴더**(권한 없음 등)는 `errors`에 기록하고 계속합니다. 260자 넘는 경로도 처리합니다.
- 진행 로그는 stderr에 2초마다 `[PROGRESS] 폴더 N개, 파일 M개, 용량, 초당 K개`.

### 결과 JSON (주요 키)
`job`, `db_file`, `root`, `complete`, `stopped_reason`(`max_files`/`time_limit`/`interrupted`), `this_run`(이번 실행: 폴더, 파일, 용량, 초, 초당 개수),
`totals`(누적: 폴더 상태별 수, 파일 수, 용량, `no_read_files`), `by_extension`(상위 15), `skipped`/`errors`(이유별 수와 예시 5개),
`priority`, `peak_memory_mb`, `next_commands`.

### DB 구조 (`data\<작업>.db`)
- `meta`: 대상 폴더, 옵션, 상태(`scanning`/`partial`/`complete`)
- `dirs`: 폴더 경로, 깊이, 상태(`pending`/`done`/`skipped`/`error`), 이유, 파일 수, 용량
- `files`: 폴더 id, 이름, 확장자(소문자, `.pdf`), 크기, 수정일, 만든 날짜, 속성, 표시(`hidden,system,readonly,offline,cloud,link`), `no_read`.
  `kind`, `category`, `confidence`, `matches`, `peek_*` 열은 다음 단계가 채웁니다.

## 3. 테스트

```bat
python -m pytest -q CLI/doc-classifier           :: 오프라인 (Linux에서도 동작)
python CLI/doc-classifier/tools/run_win_tests.py  :: Windows 실기 (대량 트리, 강제 종료 후 재개, 정션, 긴 경로, 잠긴 파일, 실제 드라이브)
```
