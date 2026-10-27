# CHANGELOG – doc-classifier

형식: 버전별 `구조 / 기능 / 수정` + 하단 `남은 할 일`. 설계는 [WORK_PLAN.md](WORK_PLAN.md).

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
- [ ] 2단계 `classify` (규칙 JSON), 3단계 `peek`, 4단계 `summary`/`list`/엑셀 보고서 (WORK_PLAN 6절)
- [ ] 회사 PC(12TB, 네트워크 공유 중)에서 `tools/run_win_tests.py`와 실제 드라이브 목록화: 속도, DB 크기, 공유 사용자 체감
- [ ] 실제 OneDrive 클라우드 자리표시자로 `cloud` 판정 확인 (집 PC에는 자리표시자 파일이 없음)
- [ ] 증분 스캔(바뀐 폴더만), 1.1 후보
