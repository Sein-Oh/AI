---
name: doc-classifier
description: Windows 폴더(하위 전체)의 파일 목록을 만들고(scan) 이후 파일명 기반으로 분류한다. 12TB급 디스크도 파일을 열지 않고 목록화하며, 중단돼도 이어서 실행할 수 있다. 폴더 안 자료 현황 파악, 파일 목록 만들기, 자료 분류 요청 시 사용. 현재 구현은 목록화(scan)와 작업 목록(jobs)까지.
license: Proprietary
compatibility: opencode
metadata:
  version: "0.1.0"
  platform: windows
---

# doc-classifier 스킬 (Windows)

`<SKILL_DIR>` 는 이 SKILL.md 가 있는 폴더의 절대 경로다. 모든 명령은 **1회 실행**으로 끝난다.
stdout 의 **1줄 JSON** 만 읽는다 (stderr 의 `[PROGRESS]` 로그는 무시).

## 1. 명령

| 할 일 | 명령 |
|---|---|
| 폴더 목록화 | `python "<SKILL_DIR>\doc_classifier.py" scan --root "D:\자료"` |
| 큰 드라이브 (시간 나눠서) | `scan --root "D:" --time-limit 3600` -> 끝나지 않으면 `next_commands[0]` (이어서) |
| 일부 폴더 제외 | `scan --root "D:\자료" --exclude "*\백업*" --exclude "*.tmp"` |
| 작업 목록과 진행 상태 | `python "<SKILL_DIR>\doc_classifier.py" jobs` |

- 파일은 열지 않는다(이름, 크기, 날짜, 속성만). 업무용 PC와 공유 사용자를 방해하지 않도록 낮은 우선순위로 돈다.
- 정션/링크 폴더, Windows/Program Files 같은 시스템 폴더, 클라우드 자리표시자 폴더는 들어가지 않는다(결과의 `skipped`).
- 결과 JSON에서 볼 것: `preview`, `complete`, `totals`(파일 수, 용량), `by_extension`, `skipped`, `errors`, `next_commands`.

## 2. 결과 처리 규칙 (반드시 따른다)

| 상황 | 할 일 |
|---|---|
| `VERIFIED:` + `complete: true` | 완료. `preview` 를 사용자에게 보고. 같은 명령 재실행 금지. |
| `VERIFIED:` + `complete: false` | 상한에 걸려 일부만 됨(저장됨). 사용자에게 알리고, 계속하라고 하면 `next_commands[0].command` 를 그대로 실행. |
| `STOP_RETRY:` + `error_type: interrupted` | 중단됨(저장됨). 사용자에게 확인한 뒤에만 `next_commands[0]` 실행. |
| `STOP_RETRY:` + message 에 `[추천]` | 추천된 명령/이름으로 **1회만** 다시 실행. |
| `STOP_RETRY:` (추천 없음), `ERROR:` | 재시도 금지. `message` 를 사용자에게 그대로 보고. |

- `next_commands` 항목의 `needs_input: true` 는 자리표시자가 있는 명령이다. 사용자가 준 값으로 바꿔 실행하고, 없으면 먼저 묻는다.
- 이모지 금지. 파일 경로는 `file:///C:/...` 형식 링크로 보고한다.
