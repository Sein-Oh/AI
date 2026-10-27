---
name: doc-classifier
description: Windows 폴더(하위 전체)의 파일 목록을 만들고(scan), 파일명으로 분류하고(classify), 표본만 살짝 읽어 확인하고(peek), 엑셀 보고서로 요약한다(summary). 12TB급 디스크도 파일을 열지 않고 목록화하며 중단돼도 이어서 실행한다. 폴더 자료 현황 파악, 파일 목록, 자료 분류, 문서 종류별 개수/용량 요청 시 사용.
license: Proprietary
compatibility: opencode
metadata:
  version: "0.9.1"
  platform: windows
---

# doc-classifier 스킬 (Windows)

`<SKILL_DIR>` 는 이 SKILL.md 가 있는 폴더의 절대 경로다. 모든 명령은 **1회 실행**으로 끝난다.
stdout 의 **1줄 JSON** 만 읽는다 (stderr 의 `[PROGRESS]` 로그는 무시). `<DC>` = `python "<SKILL_DIR>\doc_classifier.py"`.

## 1. 순서 (각 단계 결과의 `next_commands` 를 따라가면 된다)

| 단계 | 명령 |
|---|---|
| 1. 목록화 | `<DC> scan --root "D:\자료"` (큰 드라이브: `--time-limit 3600`, 끝나지 않으면 `next_commands[0]`) |
| 2. 분류 | `<DC> classify --job 작업이름 --rules "규칙.json"` (규칙 파일이 없으면 `--rules` 생략: 예시 규칙) |
| 3. 확인 | `<DC> peek --job 작업이름` (분류마다 표본 20개만 앞부분을 읽음) |
| 4. 요약/엑셀 | `<DC> summary --job 작업이름 --save` (보고서 `report.report_file`, 파일이 10만 개를 넘으면 목록은 CSV `report.file_list_files`) |
| 목록 조회 | `<DC> list --job 작업이름 --category 계약서 [--ext hwp] [--since 2025-01] [--folder 경로] [--page 2]` |
| 작업 목록 | `<DC> jobs` |

- 규칙 파일 형식: `{"계약서": ["계약", "협약"], "도면": [".dwg", ".dxf"]}` (`.`으로 시작하면 확장자, 먼저 적은 카테고리가 동점 우선).
- 사용자가 분류 기준을 말하면 이 형식으로 JSON 파일을 만들어 `--rules`에 준다. 규칙을 고치면 classify부터 다시.
- 원본 파일은 바꾸지 않는다(읽기 전용). 클라우드 자리표시자/링크 파일은 열지 않는다.
- 결과 JSON에서 볼 것: `preview`, `complete`, `recommendations`(summary), `next_commands`.

## 2. 결과 처리 규칙 (반드시 따른다)

| 상황 | 할 일 |
|---|---|
| `VERIFIED:` + `complete` 가 없거나 `true` | 완료. `preview` 를 사용자에게 보고. 같은 명령 재실행 금지. |
| `VERIFIED:` + `complete: false` | 상한에 걸려 일부만 됨(저장됨). 사용자에게 알리고, 계속하라고 하면 `next_commands[0].command` 를 그대로 실행. |
| `STOP_RETRY:` + `error_type: interrupted` | 중단됨(저장됨). 사용자에게 확인한 뒤에만 `next_commands[0]` 실행. |
| `STOP_RETRY:` + message 에 `[추천]` | 추천된 명령/값으로 **1회만** 다시 실행. |
| `STOP_RETRY:` (추천 없음), `ERROR:` | 재시도 금지. `message` 를 사용자에게 그대로 보고. |

- `next_commands` 항목의 `needs_input: true` 는 자리표시자(`<...>`)가 있는 명령이다. 사용자가 준 값으로 바꿔 실행하고, 없으면 먼저 묻는다.
- 이모지 금지. 파일 경로는 `file:///C:/...` 형식 링크로 보고한다.
