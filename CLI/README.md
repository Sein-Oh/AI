# CLI 도구 모음

AI 에이전트(26B~30B 경량 LLM)가 **스킬로 호출하는 CLI 도구**를 모아두는 곳입니다. 도구 1개 = 폴더 1개.

| 도구 | 설명 | 스킬 |
|---|---|---|
| [`ml-kit/`](ml-kit/) | 회귀·분류 ML 학습 / 예측(단독 배포 가능) / Word 감사 보고서(회귀) | [`ml-kit/SKILL.md`](ml-kit/SKILL.md) |
| [`office-cli/`](office-cli/) | Excel/Word/PowerPoint/Outlook 자동화(열린 문서 읽기·쓰기, 앱 간 전달, 되돌리기), PDF/HWP/EML 읽기와 검색 | [`office-cli/SKILL.md`](office-cli/SKILL.md) |
| [`doc-classifier/`](doc-classifier/) | 폴더 전체 파일 목록화 -> 파일명 분류 -> 표본 내용 확인 -> 엑셀 보고서 (0.9.2, Windows 실기 대기). 12TB급 대용량 대비 | [`doc-classifier/SKILL.md`](doc-classifier/SKILL.md) |

에이전트 런타임은 **OpenCode** 입니다. 각 도구 폴더가 그대로 OpenCode 스킬 폴더이며, 폴더 이름 = 스킬 이름
(소문자, 숫자, 하이픈만: `^[a-z0-9]+(-[a-z0-9]+)*$`) 이어야 합니다. 설치 위치: `C:\Users\<사용자>\.config\opencode\skills\<tool>\`.

## 새 도구 폴더 구성

```text
CLI/<tool>/           # 폴더명 = 스킬명 (예: ml-kit)
├── SKILL.md            # OpenCode 스킬. frontmatter: name(=폴더명), description(1024자 이하), license, compatibility, metadata
├── README.md           # 사람용 상세 설명서
├── CHANGELOG.md        # 변경 이력 + 남은 할 일
├── requirements.txt    # 런타임 의존성 (폐쇄망 wheel 반입 기준)
├── <tool>_*.py         # CLI 진입점 (폴더째 복사해도 단독 실행 가능)
└── tests/              # CLI 계약 테스트 (python -m pytest CLI 로 전체 실행)
```

## 모든 도구가 지키는 ACI 공통 계약

1. **stdout = 정확히 1줄 JSON.** 진행 로그·표·경고는 모두 stderr.
2. 성공: exit 0, `"status": "ok"`, `agent_directive`가 `VERIFIED:`로 시작.
3. 실패: exit 1(인자 오류 2, 중단 130), `"status": "error"`, `agent_directive`가
   - `STOP_RETRY:` – 입력/데이터 문제. message에 `[추천]`이 있으면 그 값으로 1회만 재시도.
   - `ERROR:` – 내부 오류. 재시도 금지.
4. 에이전트가 판단할 일을 줄인다: 이름 자동 매칭, 기본값, 자동 상속, 오타 추천을 도구가 처리.
5. 문자 규칙: 이모지·원문자·장식 기호 금지, 로그 태그는 `[INFO] [PROGRESS] [WARN] [ERROR] [STATUS]` ([`AGENTS.md`](../AGENTS.md) "문자 규칙").
6. 폐쇄망: 실행 중 네트워크 접근 금지. [표준 환경](../docs/ENVIRONMENT.md)에 있는 라이브러리만 사용 ([`docs/WINDOWS_OFFLINE.md`](../docs/WINDOWS_OFFLINE.md)).
7. 공통 결과 키 (해당할 때만 넣음):
   - `next_commands` – 이어서 그대로 실행할 전체 명령 목록.
   - `truncated` – 결과를 상한에서 잘랐으면 `true`, 전체 결과 파일 경로를 함께 제공.
   - `recovered` – 도구가 실패를 즉시 복구해 결과가 달라진 일 (예: 잠긴 파일 -> 새 이름 저장). `warnings`와 구분.
8. 실패한 실행(exit 1, 2)은 `<도구 데이터 폴더>/logs/errors.txt`에 자동 기록. 로그 경로는 stdout JSON에 넣지 않음.

설계 권장(사후 확인, 빈 결과 명시, 미리보기와 되돌리기, 인자 이름 일관성)과 JIT 자가복구 규칙은 [`AGENTS.md`](../AGENTS.md)에 있습니다.

## 공통 런타임 구현 규칙

세 도구가 같은 문제를 같은 모양으로 풀기 위한 규칙입니다. 도구 폴더는 단독 배포되므로 코드는 공유하지 않고,
각 도구의 공통 런타임(`ml_predict.py` PART C, `_runtime.py`, `_dc_runtime.py`)에 **같은 이름·같은 동작**으로 구현합니다.
경량 LLM이 도구마다 다른 키나 문구를 만나지 않게 하는 것이 목적입니다. 키 이름과 directive 첫 단어는 바꾸지 마십시오.

### R1. 성공 응답과 사후 확인 (`ok()`)
- 성공 응답은 항상 `"status": "ok"`와 `"verified": true|false`를 가진다.
- `verified: true` -> `agent_directive`는 `VERIFIED:`로 시작. 도구가 결과를 실제로 다시 읽어 확인한 경우만.
- `verified: false` -> `agent_directive`는 `UNVERIFIED:`로 시작하고, 확인하지 못한 내용을 적는다. `unverified` 키에 문구 목록.
  LLM 행동: 재시도하지 말고 결과와 확인하지 못한 내용을 사용자에게 그대로 보고.
- `ok()`는 directive 앞에 `VERIFIED:`를 강제로 붙이지 않는다. 호출하는 쪽이 `verified=`를 넘긴다 (기본값 없음).
- 확인 방법 (최소 기준):

  | 결과 | 확인 |
  |---|---|
  | 파일 저장 | 존재, 크기 > 0, 형식별로 다시 열기 (xlsx: openpyxl read_only, docx: python-docx, csv: 행 수 == 쓴 행 수) |
  | 열린 Office 문서 쓰기 | 쓴 범위 값·단락·도형 수를 COM으로 다시 읽어 기대값과 비교 |
  | DB/원장 기록 | 커밋 후 다시 조회한 건수 |
  | 모델 저장 | 저장된 파일을 다시 load |
- 확인을 마친 경우에만 "다시 읽어서 확인하지 마세요" 같은 문구를 쓸 수 있다.
- 새 첫 단어 `UNVERIFIED:`와 `[후보]`는 각 SKILL.md의 "agent_directive 첫 단어별 행동" 표에 같은 PR에서 추가한다.

### R2. 빈 결과와 잘린 결과
- 목록·검색·읽기 결과는 `count`(잘리기 전 전체 개수)를 가진다. 기존 개수 키(`total_matches` 등)는 그대로 두고 `count`를 추가한다.
- 0건: `status: ok`, `count: 0`, directive는 `VERIFIED: 0건. <조건>에 맞는 항목이 없습니다. 사용자에게 그대로 알리고 조건을 바꿔 다시 실행하지 마세요.`
  0건일 때 "다음 페이지", "다음 단계 실행" 같은 진행 안내를 넣지 않는다.
- 잘림: `truncated: true`, `shown`(JSON에 담은 개수), `count`, 그리고 전체 결과를 볼 방법 하나:
  `full_result_file`(도구가 `<데이터 폴더>/results/`에 자동 저장한 경로) 또는 `next_commands`(다음 페이지 명령). 안 잘렸으면 `truncated: false`.
- 예외: doc-classifier의 `truncated`(dict)는 1.0.0에서 `truncated_detail`로 옮기고 `truncated`를 bool로 바꾼다 (1.0 이전 도구, SKILL.md 함께 갱신).

### R3. JIT 복구 보고 (`note_recovered`)
- 공통 런타임에 `note_recovered(msg: str)`를 둔다. stderr에 `[WARN] <msg>`를 쓰고 실행 중 목록에 쌓는다.
- `ok()`와 오류 응답 모두 목록이 비어 있지 않으면 `recovered: [msg, ...]`를 붙인다. 비어 있으면 키를 생략.
- 문구: `<무엇이 실패> -> <어떻게 복구>` 한 줄, 200자 이하, 경로는 파일 이름만 (전체 경로는 결과의 경로 키에).
  예: `"report.xlsx 잠김 -> report_20261028_101500.xlsx로 저장"`
- 복구한 공통 함수(`save_with_lock_fallback`, 재시도 성공한 COM 호출 등)가 직접 `note_recovered`를 부른다. `warnings`는 주의 사항 전용으로 남긴다.

### R4. 파일 함수 (`retry_fs`, `remove_tree`, `save_with_lock_fallback`)
- `retry_fs(fn, attempts=6, delay=0.5)`: 대기 `delay * 시도번호`(합계 약 10.5초). 일시적 오류만 재시도:
  `PermissionError`, `winerror` 5/32/33(접근 거부, 공유 위반, 잠금 위반). 그 밖의 오류는 즉시 올린다.
  한도를 넘기면 `record_recovery_attempt("<작업> <파일명> <횟수>회 재시도 실패")`로 오류 로그(R6)의 `복구 시도:` 줄에 남기고 예외를 올린다.
- `remove_tree(path)`: 없는 경로는 성공. `shutil.rmtree(onexc=...)`에서 읽기 전용 속성을 풀고 다시 시도하며 전체를 `retry_fs`로 감싼다.
  **사용자가 준 경로를 지우지 않는다.** 도구가 만든 폴더(표식 파일 `.created_by_<tool>` 또는 도구 데이터 폴더 아래)만 지운다.
- `save_with_lock_fallback(path, writer, what)`: `retry_fs`로 먼저 재시도하고, 그래도 잠겨 있으면 `<이름>_<YYYYMMDD_HHMMSS><확장자>`로 저장하고 `note_recovered`.
  이름이 이미 `_YYYYMMDD_HHMMSS`로 끝나면 시각을 바꿔 붙인다 (두 번 붙이지 않는다). 실제 저장 경로를 반환한다.
- 덮어쓰기: 결과 파일이 이미 있으면 기본은 시각을 붙인 새 이름으로 저장하고 `note_recovered`. 덮어쓰기는 `--overwrite`가 있을 때만.
  (도구가 직접 관리하는 캐시·색인·스냅샷은 예외)

### R5. 오류 분류와 라이브러리 확인 (`require_lib`)
- `STOP_RETRY:` 대상: `InputError`(와 하위 클래스), `FileNotFoundError`, `NotADirectoryError`, `IsADirectoryError`, 복구 한도를 넘긴 `PermissionError`.
  일반 `ValueError`/`KeyError`는 `ERROR:`(내부 오류). 입력 때문에 나는 예외는 경계에서 `InputError`로 바꿔 올린다.
- `require_lib(module, pip_name, feature)`: import 실패 시 `InputError` 하위 클래스 `MissingLibraryError`를 올린다. 응답:
  - `error_type: "missing_library"`, `missing_package: <pip_name>`, `install_command: "python -m pip install <pip_name>"`
  - directive: `STOP_RETRY: <feature>에 필요한 <pip_name>이(가) 설치되어 있지 않습니다. install_command를 사용자에게 전달하세요. 직접 설치하지 마세요.`
- 공통 런타임 모듈은 최상단에서 표준 라이브러리만 import한다. 핵심 라이브러리(ml-kit의 pandas, sklearn 등)도 실패하면 같은 JSON을 내야 한다.

### R6. 오류 로그 (`write_error_log`)
- 기준 구현: doc-classifier `_dc_runtime.py`의 `write_error_log`. 형식과 규칙은 [`AGENTS.md`](../AGENTS.md) "오류 로그 저장".
- 호출 위치: `run_cli()`의 exit 1 경로와 `JsonArgumentParser.error()`(exit 2). 회전 실패와 기록 실패를 따로 감싸 회전이 실패해도 항목은 남긴다.
- 데이터 폴더 환경변수: `ML_KIT_DATA_DIR`, `OFFICE_CLI_DATA_DIR`, `DOCCLS_DATA_DIR`. 머리줄의 도구 이름은 폴더 이름(`ml-kit` 등).
- 공통 런타임에 `VERSION` 상수를 두고 SKILL.md `metadata.version`과 같은지 테스트로 확인한다.

### R7. 도움말 (`-h/--help`)
- `JsonArgumentParser`는 도움말 텍스트를 stderr로 쓰고, stdout에는
  `{"status": "ok", "command": "help", "verified": true, "agent_directive": "VERIFIED: 도움말을 stderr에 출력했습니다. SKILL.md의 명령 템플릿을 사용하세요."}` 1줄, exit 0.
- 서브명령 파서도 같은 클래스로 만든다.

### R8. 미리보기와 후보 (`--dry-run`, `[추천]`, `[후보]`)
- `--dry-run`: 검증까지 모두 하고 쓰기는 하지 않는다. 응답 `dry_run: true`, `planned: ["삭제: a.csv", "덮어쓰기: b.xlsx", "변경: Sheet1!A1:C10 (30셀)"]`,
  `next_commands[0]` = `--dry-run`을 뺀 같은 명령, directive `VERIFIED: 미리보기만 했습니다(변경 없음). planned를 사용자에게 보여주고 확인을 받은 뒤 next_commands[0]을 실행하세요.`
- 실제 실행은 수행한 파괴적 작업을 같은 형식의 `applied` 목록으로 보고한다.
- `[추천] <값>`: 바로 다시 실행할 수 있는 값 **하나**만. LLM은 그 값으로 1회만 재시도한다.
- `[후보] a, b, c`(최대 10개): 후보가 둘 이상이라 도구가 고를 수 없을 때. LLM은 재시도하지 않고 사용자에게 고르게 한다.

### R9. 테스트
각 도구는 위 규칙마다 회귀 테스트를 둔다: `verified`/`UNVERIFIED:`, 0건 응답, `truncated` 키, `recovered`(잠금 모의),
`retry_fs`의 재시도 대상 구분, `remove_tree`의 사용자 경로 거부, `missing_library` 응답, errors.txt(exit 1/2 기록, 130 미기록, 회전),
`-h` stdout 1줄, `--dry-run`이 파일을 바꾸지 않음.
