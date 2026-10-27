# CHANGELOG – atomic-cli

형식: 버전별 `구조 / 기능 / 수정` + 하단 `남은 할 일`. 1.0.0부터 관리합니다.

## [1.0.0] - 2026-10-27

첫 배포. 기존 atomic_cli(마이크로 CLI 34개)를 진입점 6개로 다시 설계했습니다. 이전 버전과의 CLI 호환은 없습니다.

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
- Windows 실기 검증: `tools/run_win_tests.py`를 1.0 명령 체계로 갱신한 뒤 회사 PC에서 실행.
- 실제 HWP 5.0 파일과 DRM 문서로 `reader.py` 검증.
- 회사 PC에서 `office.py transfer --probe` 결과 확인.
