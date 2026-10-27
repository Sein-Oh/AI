---
name: doc-classifier
description: Windows 폴더(하위 전체, 드라이브 전체 가능)의 파일을 목록화하고(scan), 파일명으로 종류를 분류하고(classify), 표본만 살짝 읽어 확인하고(peek), 엑셀 보고서를 만든다(summary). 원본은 바꾸지 않는다. "폴더에 무슨 자료가 있는지", "파일 목록", "문서 종류별 개수/용량", "자료 분류", "계약서/회의록 찾기" 요청 시 사용.
license: Proprietary
compatibility: opencode
metadata:
  version: "0.9.2"
  platform: windows
---

# doc-classifier 스킬 (Windows)

`<SKILL_DIR>` = 이 SKILL.md 가 있는 폴더의 절대 경로. `<DC>` = `python "<SKILL_DIR>\doc_classifier.py"`.
명령은 **한 번만** 실행하고 stdout 의 **마지막 1줄 JSON** 만 읽는다 (stderr 의 `[PROGRESS]` 는 무시).
다음 명령은 JSON 의 `next_commands[n].command` 를 **그대로** 복사해 실행한다. 명령을 직접 조립하지 않는다.

## 1. 순서

| 단계 | 언제 | 명령 |
|---|---|---|
| 0. 작업 확인 | 처음에 항상 | `<DC> jobs` -> 같은 폴더(`root`)의 작업이 있으면 그 `job` 을 쓰고 1단계를 건너뛴다 |
| 1. 목록화 | 새 폴더 | `<DC> scan --root "D:\자료" --time-limit 3600` |
| 2. 분류 | 목록화 후 | 규칙 파일이 있으면 `<DC> classify --job <job> --rules "<규칙.json>"`, 없으면 `<DC> classify --job <job>` |
| 3. 확인 | 분류 후 | `<DC> peek --job <job>` |
| 4. 보고서 | 마지막 | `<DC> summary --job <job> --save` |
| 찾기 | 필요할 때 | `<DC> list --job <job> --category 계약서` (+ `--ext hwp`, `--since 2025-01`, `--folder "D:\자료\영업"`, `--name 견적`) |

- `<job>` 은 scan 결과 JSON 의 `job` 값이다. 사용자가 이름을 주면 scan 에 `--job <이름>` 을 붙인다.
- 드라이브 전체는 오래 걸린다(수십 분~수 시간). `complete: false` 면 사용자에게 알리고, 계속하라고 하면 `next_commands[0]` 을 실행한다.
- 보고서: `report.report_file`(엑셀). 파일이 10만 개를 넘으면 전체 목록은 CSV(`report.file_list_files`)로 따로 저장된다.
  엑셀/CSV 내용을 직접 읽지 않는다. 경로만 알린다.

## 2. 분류 규칙 파일 만들기 (사용자가 분류 기준을 말했을 때)

사용자가 말한 종류마다 이름과 키워드를 넣어 UTF-8 JSON 파일로 저장한다 (예: `<SKILL_DIR>\data\rules_<job>.json`).
```json
{
  "계약서": ["계약", "협약", "MOU"],
  "회의록": ["회의록", "회의자료"],
  "도면": [".dwg", ".dxf"]
}
```
- `.` 으로 시작하면 확장자, 아니면 파일명/폴더명에 들어 있는 글자. 띄어쓰기와 `_` `-` 차이, 대소문자는 무시된다.
- 위에 적은 종류가 우선이다. `미분류` 는 이름으로 쓸 수 없다. 키워드는 2글자 이상으로 쓴다.
- 규칙을 고친 뒤에는 classify 부터 다시 실행한다 (scan 은 다시 하지 않는다).

## 3. 사용자에게 보고할 것

| 명령 | 보고 내용 |
|---|---|
| scan | `preview` (파일 수, 용량, 건너뛴 폴더 수) |
| classify | `preview` (종류별 개수, 미분류 비율). `unclassified_words` 상위 5개를 "규칙에 추가할 만한 단어"로 함께 |
| peek | `preview` (확인율). `weak_categories` 가 있으면 "이 종류는 파일명만으로는 부정확" 이라고 함께 |
| summary | `preview` + `recommendations` 전부 + 보고서 경로 |
| list | `total` 과 `items` 의 `path` 몇 개. 더 보려면 `next_commands` 의 다음 페이지 |

- 파일 경로는 `file:///D:/자료/보고서.xlsx` 형식 링크로 쓴다. 이모지 금지.
- 규칙을 바꾸자고 제안만 하고, 사용자가 동의해야 규칙 파일을 고친다.

## 4. 결과 처리 규칙 (반드시 따른다)

| JSON | 할 일 |
|---|---|
| `VERIFIED:` (`complete` 없음 또는 `true`) | 완료. 3절대로 보고. 같은 명령을 다시 실행하지 않는다. |
| `VERIFIED:` + `complete: false` | 일부만 됨(저장됨). 알리고, 계속하라고 하면 `next_commands[0]` 실행. |
| `STOP_RETRY:` + `error_type: interrupted` | 중단됨(저장됨). 사용자에게 물은 뒤에만 `next_commands[0]` 실행. |
| `STOP_RETRY:` + `message` 에 `[추천]` | `[추천]` 뒤의 값(명령/이름/경로)으로 **1회만** 다시 실행. 또 실패하면 보고. |
| `STOP_RETRY:` (추천 없음) | 재시도 금지. `message` 를 그대로 보고. |
| `ERROR:` | 재시도 금지. `message` 와 오류 기록 파일 `<SKILL_DIR>\data\logs\errors.txt` 경로를 보고. |

- `needs_input: true` 인 명령에는 `<...>` 자리표시자가 있다. 사용자가 준 값으로 바꿔 실행하고, 값이 없으면 먼저 묻는다.
- 금지: 파일 이동/삭제/이름 바꾸기 제안을 실행하는 것(이 도구는 읽기 전용), 같은 명령 반복 실행, 모든 페이지를 끝까지 넘기는 것.
