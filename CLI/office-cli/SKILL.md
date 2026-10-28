---
name: office-cli
description: 열려 있는 Excel/Word/PowerPoint 문서를 읽고 쓰며(값/표/수식/차트/서식, 본문/표/그림, 슬라이드), 앱 사이로 차트·표·내용을 옮기고(office.py transfer), Outlook 메일을 조회·작성하고, PDF/HWP/EML/Office 파일을 Office 없이 읽고 검색한다(reader.py). 작업 전 자동 스냅샷으로 되돌리기(office.py undo)를 지원한다. 엑셀 표/그래프 만들기, 보고서·발표자료 작성, 문서 내용 검색 후 다른 문서에 넣기, 메일 답장 작성 요청 시 사용.
license: Proprietary
compatibility: opencode
metadata:
  version: "1.2.1"
  platform: windows
---

# office-cli 스킬 (Windows)

`<SKILL_DIR>` 는 이 SKILL.md 가 있는 폴더의 절대 경로다. 모든 명령은 **1회 실행**으로 끝난다.
stdout 의 **1줄 JSON** 만 읽는다 (stderr 의 `[PROGRESS]` 로그는 무시).
`--target` 기본값은 `active`(사용자가 보고 있는 문서). 다른 열린 문서는 이름, 닫힌 파일은 경로를 쓴다.

## 1. 명령

| 할 일 | 명령 |
|---|---|
| 엑셀 읽기 / 셀 찾기 | `excel.py read [--range A1:D20] [--search 글자] [--save]` |
| 엑셀에 값/표/수식 쓰기 | `excel.py write --range A1 --file 표.csv` / `--values "[[\"이름\",\"값\"],[\"가\",1]]"` / `--range A2:B101 --formula "=..."` (`--header "x,y"`, `--append`, `--sheet 시트`, 새 시트는 `--sheet 이름 --new-sheet`) |
| 엑셀 차트 | `excel.py chart --range A1:B101 --type line --title "제목"` (`--action list` / `--action delete --name 제목`) |
| 엑셀 서식 | `excel.py style --range A1:E10 --theme navy` / `--bg yellow --bold` / `--highlight ">=100:pink"` |
| 엑셀 기타 | `excel.py info`, `replace --find A --replace B`, `sheet --action add --name 이름`, `range --action merge --range A1:B1`, `export --save 결과.csv` |
| 워드 읽기 / 쓰기 | `word.py read [--save]` / `word.py write --text "## 제목\n- 항목"` / `--file 내용.md` / `--image 그림.png` (`--anchor 글 --pos after`, 여러 곳이면 `--occurrence N`) |
| 워드 기타 | `word.py info`, `replace --find A --replace B [--bold]`, `export --save 보고서.pdf [--page-number]` |
| PPT 읽기 / 쓰기 | `ppt.py read [--slides 1-3]` / `ppt.py write --slide new --title 제목 --text "- 항목"` / `--file 내용.md` / `--image 그림.png` / `--cards "제목:내용|제목:내용"` |
| PPT 기타 | `ppt.py info`, `replace --find A --replace B`, `slide --action move --slide 1 --to 3`, `export --save 발표.pdf` |
| 차트를 워드/PPT에 그림으로 | `office.py transfer --from excel --chart "차트이름" --to word,ppt` |
| 엑셀 범위를 워드/PPT 표로 | `office.py transfer --from excel --range A1:D10 --to word` |
| 워드/PPT 내용을 엑셀로 | `office.py transfer --from word --what text --to excel` (`--what table --table 1`) |
| 파일 읽기 (PDF/HWP/EML 등) | `reader.py read --file "경로" [--pages 1-3] [--save]` |
| 읽은 문서에서 검색 | `reader.py search --query "A AND B" [--file 파일또는폴더] [--save]` |
| 메일 | `outlook.py current`, `search --query 말 [--from 이름]`, `read --id <id>`, `reply --body "내용"`, `new --to 주소 --subject 제목 --body 내용` |
| 되돌리기 / 창 | `office.py undo` (`--list`, `--pick N`), `office.py windows`, `office.py focus --app excel` |
| 결과 배치 확인 | `ppt.py info --detail --slides N`, `excel.py info --detail`, `word.py info --detail` (`layout_warnings`가 0이 아니면 `warnings`를 사용자에게 알림) |

모든 명령은 `python "<SKILL_DIR>\<파일>.py" <명령> ...` 형식이다.

## 2. 여러 단계 작업 (체이닝)
- 결과 JSON 에 `next_commands` 가 있으면 다음 단계는 **명령을 직접 만들지 말고 `next_commands[i].command` 를 그대로 실행**한다.
- 문서 내용을 다른 문서로 옮길 때는 내용을 직접 복사해 인자로 넣지 않는다. `--save` 로 파일을 만들고 `output_file` 경로를 `--file` 로 넘긴다.
- 예) 사인 그래프: `excel.py write --range A1:B101 --header "x,sin(x)" --formula "=(ROW()-2)*4*PI()/99" "=SIN(A2)"` → `excel.py chart --range A1:B101 --type line --title "사인 2주기"` → `next_commands[0]`(워드/PPT로 전달).

## 3. 결과 처리 규칙 (반드시 따른다)

| `agent_directive` 시작 | 할 일 |
|---|---|
| `VERIFIED:` | 완료. `preview` 를 사용자에게 보고. 같은 명령 재실행/결과 재조회 금지. |
| `STOP_RETRY:` + message 에 `[후보]` 있음 | 재시도 금지. `[후보]` 를 사용자에게 보여주고 고르게 한 뒤, 고른 값으로 실행 (시트: `--sheet 이름` 또는 `--new-sheet`, 앵커: `--occurrence 번호`, 문서: `--target 전체경로`). |
| `STOP_RETRY:` + message 에 `[추천]` 있음 | 추천된 이름으로 **1회만** 다시 실행. 또 실패하면 사용자에게 보고. |
| `STOP_RETRY:` (추천 없음) | 재시도 금지. `message` 를 사용자에게 그대로 보고. |
| `ERROR:` | 재시도 금지. `message` 를 사용자에게 그대로 보고. |

- 메일은 기본으로 작성 창만 띄운다. `--send` 는 사용자가 **발송을 분명히 요청한 경우에만** 붙인다.
- `ppt.py slide --action clear` 의 `--all-slides`, 시트/슬라이드 삭제는 사용자가 요청한 경우에만 쓴다.
- `--new-sheet`(새 시트), `transfer --overwrite`(기존 시트에 덮어쓰기)는 사용자가 원한 경우에만 붙인다.
- 잘못 고쳤으면 `office.py undo` 로 되돌린다.
- 파일 경로는 `file:///C:/...` 형식 링크로 보고한다. 이모지 금지.
