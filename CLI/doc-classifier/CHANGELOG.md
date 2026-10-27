# CHANGELOG – doc-classifier

형식: 버전별 `구조 / 기능 / 수정` + 하단 `남은 할 일`. 설계는 [WORK_PLAN.md](WORK_PLAN.md).

## [0.9.2] - 2026-10-27

실기 결과와 실제 사용 중 오류를 AI가 읽고 판단할 수 있게 자동 기록, 경량 LLM용 SKILL.md 재작성.

### 기능
- 자동 오류 기록: 실패한 실행(exit 1, 인자 오류 exit 2)을 `data\logs\errors.txt`에 덧붙임. 시각, 버전, Python/OS, 명령 인자,
  오류 종류·메시지, 내부 오류는 traceback. 성공/사용자 중단은 기록 안 함. 2MB 넘으면 `errors.old.txt`로. 기록 실패가 응답 계약을 깨지 않음.
- 런타임에 `VERSION` 상수(SKILL.md 버전과 같음, 테스트로 확인).
- Windows 실기 러너가 `diag_<시각>.txt`(AI 판독용 진단 로그)를 추가로 저장: 환경(OS, Python, 라이브러리 버전, 메모리, 디스크·파일 시스템,
  도구 버전·git 커밋), 항목별 결과·시간, 모든 호출의 인자·종료코드·시간·JSON(4000자)·경고/오류/traceback, 도구 오류 로그.
  도구를 `DOCCLS_VERBOSE=1`로 실행해 내부 오류 traceback을 받음. 러너 오류나 Ctrl+C에도 결과 파일을 저장.
- SKILL.md를 26B~30B 경량 모델용으로 다시 씀: 처음에 `jobs`로 기존 작업 확인(재목록화 방지), 단계별 명령,
  사용자 기준으로 규칙 JSON 만드는 법, 명령별로 보고할 키, 결과 처리 표, 금지 사항(같은 명령 반복, 페이지 끝까지 넘기기, 파일 이동).

### 테스트
- 오프라인 89개: 오류 기록(성공 미기록, 입력/인자/내부 오류, traceback은 내부 오류만, 크기 넘김, 기록 실패해도 응답 유지),
  SKILL.md 형식·버전 일치·언급한 명령과 옵션이 실제로 있는지·길이 상한.

## [0.9.1] - 2026-10-27

엑셀 보고서의 파일 목록 처리 변경 (사용자 결정: 대량 목록은 엑셀 밖으로, CSV는 엑셀 한도마다 나눔).

### 기능
- `summary --save`(`--file-list auto`): 파일 목록이 **10만 행을 넘으면**(이전 300만 행) 엑셀에는 요약 시트만 두고 목록은 CSV로 따로 저장.
  엑셀 `요약` 시트의 `파일 목록` 항목에 CSV 이름을 적고, preview에도 CSV 경로를 붙입니다.
- 목록 CSV를 **1,048,575행마다 나눠** 저장(`_파일목록_1.csv`, `_2.csv` ..., 한 개면 `_파일목록.csv`, 파일마다 머리글). 어느 파일이든 엑셀에서 잘리지 않고 열립니다.
  결과 JSON에 `report.file_list_files`(전체 경로 목록) 추가, `report.file_list_csv`(첫 파일)는 그대로. 다시 저장해 개수가 줄면 남는 이전 CSV는 지움.
- CSV 쓰기 빠르게: 묶음 단위 `writerows`, 날짜는 시각 숫자에서 바로 글자로.

### 검토 (적용하지 않음)
- 파일 목록을 HTML로: 쓰기는 CSV와 비슷하게 빠르지만(100만 행 27초) 브라우저가 열지 못함. Chromium에서 10만 행 여는 데 95초,
  100만 행은 메모리 13.7GB까지 쓰다 멈춤. 수백만 행 목록에는 맞지 않아 CSV 유지.

### 테스트
- 오프라인 84개 (CSV 나누기, 이어짐(빠짐·중복 없음), 이전 CSV 정리, 기준값). Windows 러너 S13은 CSV 목록 행 수도 셉니다.
- Linux 가짜 100만 행: `summary --save` 206초 -> **37초**(엑셀 29KB + CSV 246MB), 최대 메모리 94MB.

## [0.9.0] - 2026-10-27

WORK_PLAN 2~4단계: 파일명 분류(classify), 표본 확인(peek), 요약/엑셀 보고서(summary), 조건 조회(list).
기능은 1.0 범위를 모두 갖췄고, Windows 실기(5단계, `tools/run_win_tests.py` S10~S15)를 통과하면 1.0.0으로 올립니다.

### 구조
- 새 내부 모듈: `_dc_rules.py`(규칙 JSON 검증, 정규화, 점수, 형식 표, 파일명 속 정보), `_dc_classify.py`(DB 묶음 분류, 상위 폴더, 중복 후보),
  `_dc_peek.py`(형식별 앞부분 읽기, 작업 프로세스와 시간 상한, 표본 고르기, 판정), `_dc_report.py`(요약, 엑셀, list 조회).
- DB 스키마 2: `dirs.top_id`, `files.name_date/name_version/name_flags/peek_category/peek_reason/peek_ms` 추가.
  0.1.0 DB는 열을 추가만 하므로 다시 scan하지 않고 그대로 classify할 수 있습니다. classify가 `files(category)` 색인을 만듭니다.
- 런타임에 `read_text_file`(UTF-8/BOM/UTF-16/CP949)과 `save_with_lock_fallback`(임시 파일 후 교체, 잠겼으면 `이름_시각`으로) 추가.
- SQLite `temp_store`를 MEMORY에서 FILE로: 큰 GROUP BY/색인 정렬이 메모리를 키우지 않게 (가짜 100만 행 classify 최대 메모리 171MB -> 88MB).

### 기능
- `classify --job --rules`: 규칙 JSON `{"카테고리": ["키워드", ".확장자"]}`(확장 형식 `{"keywords", "exclude"}`)으로 디스크를 읽지 않고 분류.
  - 점수: 확장자 3, 파일명 2, 바로 위 폴더 1, 더 위 폴더 0.5 (대상 폴더 자신은 보지 않음). 키워드는 가장 높은 위치에서 한 번, 카테고리 안에서 합산.
    동점은 JSON에 먼저 적은 카테고리. 신뢰도 high/medium/low. 근거(`matches`)를 기록.
  - 비교: NFC(맥 자모 분리), 대소문자, 공백·`_`·`-` 무시. 영문·숫자 4글자 이하 키워드(`PO`, `MOU`, `spec`)는 단어로만 비교(`report` 속 `po` 제외).
  - 함께 기록: 형식(kind 14종), 파일명 속 날짜/버전/사본·임시 표시, 상위 폴더, 중복 후보(이름+크기), 키워드별 맞은 수, 미분류 파일명의 자주 나오는 단어.
  - `--rules` 생략 시 지난번 규칙 파일, 처음이면 `rules.example.json`. 규칙 오류는 줄·위치를 짚어 `STOP_RETRY`, 1글자 키워드는 `[WARN]`.
  - 규칙이 바뀌면 이전 peek 결과를 지움(같은 규칙이면 유지). 목록화가 덜 된 작업도 분류 가능(알림 + 이어서 목록화 명령).
- `peek --job`: 분류별 표본(기본 20개, 전체 500개)만 앞부분을 읽어 `confirmed/changed/no_match/no_text/encrypted_or_drm/unreadable/timeout/...` 판정.
  - PDF 2쪽, DOCX 단락 20개, PPTX 슬라이드 10장, XLSX 시트 이름+10행, HWP/HWPX 미리보기 텍스트, 텍스트 8KB, EML, 옛 Office(doc/xls/ppt/msg) 본문 스트림 글자.
  - 별도 작업 프로세스가 읽고, 파일당 시간 상한(`--timeout`, 기본 10초)을 넘기거나 죽으면 새로 띄워 다음 파일로. 크기 상한 200MB.
  - `no_read`(클라우드/오프라인/링크)는 절대 열지 않고, 열기 직전에도 속성을 다시 확인. 서명이 형식과 다르면 DRM/암호로 판별.
  - 신뢰도 low부터, 여러 폴더에 고르게. 다시 실행하면 모자란 표본만 더 읽음(`--redo`로 새로). `--time-limit`, Ctrl+C(exit 130) 후 같은 명령으로 이어서.
- `summary --job [--save [경로]]`: 카테고리·형식·상위 폴더·수정 시기·중복 후보·확인 결과·권장 사항(JSON은 상위 N개로 자름).
  엑셀 시트 7개(요약, 카테고리별, 확인 결과, 미분류 단어, 중복 후보, 오류·건너뜀, 파일 목록). 시트 한도 넘으면 시트 분할, 300만 행 넘으면 목록은 CSV.
  `=`로 시작하는 파일명이 수식이 되지 않게 문자열로 고정. 보고서가 열려 있으면 다른 이름으로 저장.
- `list --job`: `--category --ext --kind --confidence --peek --since --until --folder --name --min-size --flag`, 정렬, 페이지(기본 100행),
  다음 페이지와 atomic-cli `reader.py read` 명령을 `next_commands`로. 없는 카테고리/형식은 `[추천]`.
- `scan` 완료 시 `next_commands`로 분류 명령 2개(`[0]` 사용자 규칙 `needs_input`, `[1]` 예시 규칙). `jobs`에 `classify_status`, `peek_files`.
- classify/peek/summary 결과에 `peak_memory_mb`.

### 테스트
- 오프라인 82개 (기존 13 + 규칙 39, classify 11, peek 12, 보고서/list 8). 실제 형식 샘플(docx/pptx/xlsx/pdf/hwp/hwpx/eml/doc)을 테스트 안에서 만듭니다
  (HWP/doc은 `tests/dc_samples.py`의 최소 OLE 작성기). 가짜 작업 프로세스로 시간 초과·비정상 종료 후 재시작을 확인.
- Linux 가짜 100만 행 측정 (파일을 만들지 않고 DB에 직접 넣은 이름 데이터):
  - classify 42초(초당 약 2.4만 개), 최대 메모리 88MB. DB 90MB -> 227MB(색인과 분류 열 포함, 파일당 약 230바이트)
  - summary(JSON) 6.4초 61MB, `--save` 엑셀(파일 목록 100만 행) 206초 84MB, 80MB 파일
  - list 조회 0.4~1.2초, peek 표본 고르기 약 8초
- Windows 실기 러너에 S10~S15 추가(분류 속도, 형식별 확인과 잠긴 파일, OneDrive 자리표시자, 엑셀 보고서와 열린 보고서, Windows 경로 list, 실제 드라이브 전체 흐름).
  Linux에서 S10, S14, S11(독점 잠금 제외)을 미리 돌려 확인. 결과 SKIP(조건 없음)도 보고서에 표시. 계약 검사(S9)는 맨 마지막에.

## [0.1.0] - 2026-10-27

WORK_PLAN 0~1단계: 뼈대와 목록화(scan).

### 구조
- 진입점 `doc_classifier.py` (`scan`, `jobs`). 내부 모듈 `_dc_runtime.py`(응답 계약), `_dc_store.py`(SQLite, 작업 잠금), `_dc_scan.py`(목록화).
  저장소 pytest가 한 세션에서 모든 도구를 돌리므로 atomic-cli의 `_runtime`과 겹치지 않게 `_dc_` 접두어를 씁니다.
- 작업 1개 = SQLite 파일 1개(`data\<작업>.db`, `DOCCLS_DATA_DIR`로 변경). classify/peek가 채울 열을 미리 둡니다.
- 저장소 ACI 계약: stdout 1줄 JSON, exit 0/1/2/130, `VERIFIED:`/`STOP_RETRY:`/`ERROR:`, `next_commands`의 `needs_input`.

### 기능
- `scan`: 파일을 열지 않고 폴더 목록 정보(이름, 확장자, 크기, 수정일, 만든 날짜, 속성)만 기록. 방문할 폴더 대기열도 DB에 두어 메모리가 파일 수와 무관.
- 중단/재개: 폴더 단위로 결과를 함께 커밋. Ctrl+C(exit 130), 강제 종료, `--max-files`/`--time-limit` 어느 경우든 `--resume`으로 중복 없이 이어짐. `--root`만으로도 미완료 작업을 찾음.
- 들어가지 않는 폴더와 이유 기록: 정션/심볼릭 링크, 클라우드 자리표시자/오프라인 폴더, 시스템 폴더(어느 깊이든 `$Recycle.Bin` 등, 드라이브 바로 아래 Windows/Program Files 등, 숨김+시스템), `--exclude`, `--max-depth`.
- 클라우드 자리표시자/오프라인/링크 파일은 `no_read=1`로 표시 (다음 단계에서 절대 열지 않음).
- CPU·디스크 I/O 백그라운드 우선순위(기본), `--throttle-ms`, 260자 초과 경로, 권한 오류 폴더는 기록 후 계속, 같은 작업 동시 실행 차단.
- `jobs`: 작업 목록과 진행 상태.

### 수정
- 기본 작업 이름(`job_name_for`)이 호스트 OS 경로 규칙을 써서 Linux에서 `D:\자료\2026 계약`이 `D_자료_2026_계약_...`이 되던 문제.
  호스트 OS와 무관하게 Windows 규칙(`ntpath`)으로 마지막 폴더를 잘라 냅니다. Windows 동작(드라이브 루트 `D:\` -> `D드라이브_...` 포함)은 그대로이며, 드라이브 루트 테스트도 모든 OS에서 실행합니다.

### 테스트
- 오프라인 13개 (Linux에서도 동작, Windows 전용 1개는 건너뜀).
- Windows 실기 러너 `tools/run_win_tests.py` (S1~S9). 집 PC(Windows 11, NTFS SSD) 9개 모두 통과:
  - 10만 파일 트리 1.4초(초당 약 7만 개), 최대 메모리 32MB (1만 파일 때 25MB: 파일 수와 거의 무관)
  - 목록화 중 강제 종료(4만 개 기록 시점) -> 재개 후 10만 개, 중복 없음
  - 정션 고리 건너뜀, 333자 경로, 다른 프로세스가 독점 중인 파일도 목록에 포함
  - 실제 C:\ 20초 상한: 초당 약 1.1만 개, 2회 누적 54만 개(83.5GB) -> 재개로 이어짐. 정션 54개(`Documents and Settings` 등)와 시스템 폴더 408개 건너뜀, 오류 0
  - DB 크기: 파일 54만 개에 61.5MB(파일당 약 114바이트). 2천만 개면 약 2.3GB로 추정

## 남은 할 일
- [ ] 집 PC에서 `tools/run_win_tests.py` S10~S15 (특히 S11 독점 중 파일, S13 열린 보고서, S15 실제 문서로 peek 속도와 판정) -> 통과하면 1.0.0
- [ ] 회사 PC(12TB, 네트워크 공유 중)에서 실제 드라이브 목록화 -> 분류 -> 확인 -> 보고서: 속도, DB 크기, 공유 사용자 체감
- [ ] 실제 OneDrive 클라우드 자리표시자로 `cloud` 판정과 peek 제외 확인 (S12, 집 PC에는 자리표시자 파일이 없었음)
- [ ] 회사 PC DRM 문서: HWP/HWPX가 olefile/zip으로 읽히는지, 공유 중인 파일을 다른 PC가 열고 있을 때 peek 동작 (WORK_PLAN 9절 남은 확인)
- [ ] 1.1 후보: 증분 스캔(바뀐 폴더만), peek 확인 결과를 학습 데이터로 한 파일명 n-gram 분류기, 압축 파일 내부 목록, 내용 해시 중복
