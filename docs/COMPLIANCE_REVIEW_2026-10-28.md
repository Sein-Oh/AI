# 지침 준수 검토 (2026-10-28)

`AGENTS.md`(2026-10-28 개정판) 기준으로 `CLI/` 도구 3종을 읽기 전용으로 검토한 결과입니다.
코드는 지침보다 먼저 작성되었으므로 미준수 항목은 대부분 "새 지침을 아직 반영하지 않음"입니다.
수정할 일은 각 도구 `CHANGELOG.md` 하단 "남은 할 일"에 우선순위 순으로 등록했습니다. 수정은 도구별 브랜치에서 진행합니다.

- 2026-10-28 이후: doc-classifier는 다른 개발자 담당으로 `archive/doc-classifier/`에 보관. 아래 doc-classifier 내용은 기록용이며 후속 조치 대상이 아님.
- 기준 커밋: main `a07607e` (세 도구 브랜치 모두 병합된 상태)
- 테스트: `constraints.txt` 버전(pywin32 제외, Linux)으로 `python -m pytest -q` 282 통과, 2 건너뜀
- 판정: 준수 / 부분 = 부분 준수 / 미준수 / - = 해당 없음

## 1. 판정표

| 항목 | ml-kit | office-cli | doc-classifier |
|---|---|---|---|
| A1 stdout 1줄 JSON | 부분 (핵심 import 실패 시 traceback, `-h`) | 부분 (`-h`) | 부분 (`-h`) |
| A2 exit 코드 / directive | 부분 (`status: no_history`, ImportError가 `ERROR:`) | 준수 (ValueError/KeyError가 STOP_RETRY로 분류) | 준수 |
| A3 run_cli + JsonArgumentParser | 준수 | 부분 (러너 `--agent` 모드 미적용) | 준수 |
| B1 사후 확인 | 미준수 | 미준수 | 부분 (DB는 재조회, 보고서 파일은 미확인) |
| B2 빈 결과 명시 | 부분 | 부분 | 부분 |
| B3 next_commands | 준수 | 부분 (자리표시 인자, `--from-target` 누락) | 준수 |
| B4 출력 양 제한 / truncated | 부분 | 부분 | 부분 (`truncated`가 bool이 아님) |
| B5 인자 이름 일관성 | 부분 | 부분 (짧은 옵션 충돌 다수) | 부분 |
| B6 파괴적 작업 dry-run / undo | 미준수 | 부분 (undo 있음, dry-run 없음) | 미준수 |
| B7 판단 대행 | 부분 | 부분 | 준수 |
| C1 JIT 복구 종류 | 부분 | 부분 (`remove_tree`, COM 재시도 없음) | 부분 (`retry_fs`, `remove_tree` 없음) |
| C2 복구 한도 | 준수 | 준수 | 준수 |
| C3 복구 보고 (`recovered`) | 부분 (키 없음) | 부분 (키 없음) | 부분 (키 없음) |
| C4 자동이면 안 되는 복구 | 미준수 | 부분 | 미준수 |
| D 오류 로그 errors.txt | 미준수 | 미준수 | 부분 (기준 구현, 세부 2건) |
| E 문자 규칙 | 부분 (로그 태그 형식) | 부분 (.md 화살표 26, 원문자 2) | 준수 |
| F1 네트워크 | 준수 | 준수 | 준수 |
| F2 import 실패 JSON 안내 | 미준수 | 부분 | 준수 |
| F3 requirements 일치 | 부분 (matplotlib 누락) | 부분 (pyproject py38) | 준수 |
| F4 공통 파일 함수 사용 | 부분 | 부분 (COM 저장 미적용) | 부분 |
| F5 다른 도구 import 금지 | 준수 | 준수 | 준수 |
| F6 `python` 명령 | 부분 (`pip` 주석 1곳) | 준수 | 준수 |
| G1 SKILL.md 형식 | 준수 | 준수 (보조 스킬 포함) | 준수 |
| G2 남은 할 일 | 부분 (완료 항목 남음) | 준수 | 준수 |

## 2. 우선 처리할 문제 (데이터 손실, 잘못된 판단 위험)

JIT 자가복구 3번(복구 금지: 삭제, 덮어쓰기, 후보가 둘 이상인 추측)에 해당하는 자동 동작입니다.

| 도구 | 동작 | 위치 |
|---|---|---|
| ml-kit | `leaderboard.json`이나 `model_dataset.csv`가 없는 vN 폴더를 시작할 때 통째로 삭제 | `ml_train.py:904-914` |
| ml-kit | `--version`에 이미 있는 버전을 주면 아무 말 없이 교체 | `ml_train.py:917-921` |
| ml-kit | 원장 기록이 버전 폴더 커밋보다 먼저라서, 커밋이 실패하면 없는 버전이 원장에 남음 | `ml_train.py:1515-1518` |
| office-cli | 쓰기에서 오타 난 시트 이름으로 새 시트를 조용히 만듦 | `excel.py:426,430` |
| office-cli | `--anchor`가 여러 곳에 맞으면 첫 번째를 고르고, `--pos replace`면 그 단락을 지움 | `word.py:378-388` |
| doc-classifier | `scan --resume`이 미완료 작업 여러 개 중 가장 최근 것을 혼자 고름 | `doc_classifier.py:54-61` |
| doc-classifier | `summary --save`가 이전 CSV를 지우고 보고서를 덮어씀, 보고는 로그뿐 | `_dc_report.py:297-308` |
| ml-kit, doc-classifier | 실기 러너가 사용자가 준 `--dir`을 확인 없이 `rmtree` | `ml-kit/tools/run_win_tests.py:206`, `doc-classifier/tools/run_win_tests.py:636` |

## 3. 세 도구 공통 문제 (공통 런타임에서 같은 방식으로 고칠 것)

1. **확인 없는 `VERIFIED:`**: office-cli와 doc-classifier는 `ok()`가 directive 앞에 `VERIFIED:`를 무조건 붙이고
   (`office-cli/_runtime.py:153-156`, `doc-classifier/_dc_runtime.py:95-98`), ml-kit은 각 진입점이 저장 후 확인 없이 `VERIFIED:`를 쓴다.
   office-cli는 쓰기 후 "다시 읽어서 확인하지 마세요"라고 지시한다(`excel.py:513` 등).
   -> 사후 확인에 성공했을 때만 `VERIFIED:`. 확인하지 못했으면 무엇을 확인하지 못했는지 적는다.
2. **`-h/--help`가 stdout에 여러 줄**: argparse 기본 동작. `JsonArgumentParser`에서 help를 stderr로 보내고 JSON 1줄을 낸다.
3. **`recovered` 키 없음**: 잠금 새 이름 저장은 세 도구 모두 실제 경로와 `[WARN]`은 남기지만 JSON에 복구 사실이 없다.
   -> `save_with_lock_fallback` 등이 복구 문구를 모으고 `ok()`가 `recovered` 배열을 붙이는 구조.
4. **`--dry-run` 없음**: 세 도구 모두 0건.
5. **빈 결과**: 0건이어도 기본 문구("다음 페이지를 실행하세요", "classify를 실행하세요" 등)를 내는 경로가 있다. `count` 키 이름도 제각각이다.
6. **선택 라이브러리 import 실패**: pip 안내 없이 `ERROR:`(office-cli의 openpyxl/docx/pptx) 또는 traceback(ml-kit의 numpy/pandas/joblib/sklearn)으로 끝난다.
   -> `require_lib()` 공통 함수로 `STOP_RETRY:` + `python -m pip install ...`.

## 4. 인자 이름 비교 (B5)

| 개념 | ml-kit | office-cli | doc-classifier |
|---|---|---|---|
| 입력 파일 | `--file/-f` | `--file/-f` | - (`--root` 폴더) |
| 결과 저장 | `--out/-o` | `--save` | `--save` |
| 타겟/대상 | `--targets/-y`(train, predict), `--target/-t`(report) | `--target/-t`(열린 문서) | - |
| 개수 상한 | - | `--limit/-n`(outlook), `--top/-n`(reader), `--max-rows` | `--max-files`, `--top`, `--page-size` |
| 버전/작업 | `--version/-v` | - | `--job` |

- 같은 이름인데 의미가 다른 것: `--target`(ml-kit 예측 대상 열 / office-cli 문서), `--history`(ml_train 조회 플래그 / ml_report 폴더 별칭),
  office-cli 안의 `-r`, `-c`, `-n`, `--to`, `--all`, `--title`.
- 제안 (기존 인자는 유지하고 alias만 추가): ml-kit에 `--save`(`--out` alias), ml_report에 `--targets/-y`, office-cli outlook에 `--top`(`--limit` alias).

## 5. 이번 검토로 고친 지침 문구 (AGENTS.md)

- `-h/--help` 텍스트도 stderr로 보낸다는 규칙 추가 (세 도구 공통 위반이었고 지침에 없었음).
- 사람용 실기 테스트 러너는 계약 대상이 아니고, 에이전트용 모드만 계약을 지킨다는 범위 명시.
- 인자 오류(exit 2)는 `run_cli()`가 아니라 `JsonArgumentParser.error()`가 기록한다 (doc-classifier 구현에 맞춤).
- 가운뎃점(·), 곱셈(×), 도(°) 같은 CP949 일반 기호는 허용한다고 명시.

## 6. 공통 구현 규칙

3절 공통 문제의 구현 방식은 [`CLI/README.md`](../CLI/README.md) "공통 런타임 구현 규칙"(R1~R9)으로 정했다.
각 도구의 "남은 할 일" 중 `VERIFIED:`, `recovered`, `retry_fs`/`remove_tree`, 오류 로그, `require_lib`, `-h`, `--dry-run`, 빈 결과, `truncated` 항목은 그 규칙대로 구현한다.

## 7. 참고 (지침 위반은 아님)

- office-cli `WORK_PLAN.md`에 예전 파일명(`_cache.py` 등)이 남아 있다.
- doc-classifier `SKILL.md:69`는 LLM에게 `<SKILL_DIR>\data\logs\errors.txt`를 고정 경로로 안내한다. `DOCCLS_DATA_DIR`를 바꾸면 틀린 경로가 된다.
- doc-classifier 테스트 도우미는 pymupdf가 없으면 SKIP이 아니라 ERROR가 난다(`tests/dc_samples.py:128`).
