# Phase 1 Windows 실기 테스트 체크리스트

## 자동 실행
`python tools/run_win_tests.py`를 실행하면 아래 항목을 순서대로 진행합니다.
- 테스트 파일은 `C:\atomic_test`에 자동으로 만듭니다.
- 눈으로 확인해야 하는 항목은 y/n으로 묻습니다.
- 결과는 `report_*.txt`로 저장됩니다.

옵션:
- `--only A,C`: 일부 그룹만 실행
- `--self-email 주소`: G3 실제 발송 테스트 포함
- `--skip-outlook`: Outlook 그룹 제외
- `--auto`: 질문 없이 자동 판정 항목만 실행

## 준비 (수동으로 진행할 때)
- 테스트 파일은 **복사본**으로 준비합니다. 아래 예시 경로는 `C:\test\`입니다.
  - `A.xlsx`: 저장된 파일. 화면에 열어 둡니다.
  - `B.xlsx`: 닫혀 있는 파일. 시트 2개 이상.
  - `A.docx`: 저장된 파일. 열어 둡니다.
  - `B.docx`: 닫혀 있음.
  - `A.pptx`: 저장된 파일. 슬라이드 3장 이상, 열어 둡니다.
  - `B.pptx`: 닫혀 있음.
- 명령은 `atomic-cli` 폴더에서 실행합니다.
- 각 명령 뒤에 `echo %ERRORLEVEL%`(PowerShell은 `$LASTEXITCODE`)로 종료 코드를 확인합니다. 성공은 0, 오류는 1입니다.
- 결과 공유 형식: 항목 번호 / 출력된 JSON 1줄 / 화면에서 관찰한 내용 / 종료 코드

---

## A. 사용자 창 간섭 (가장 중요)
| # | 상태 | 명령 | 기대 결과 |
|---|---|---|---|
| A1 | A.xlsx 열림 | `python excel_read.py --target "C:\test\B.xlsx"` | A.xlsx 창이 **닫히거나 깜빡이지 않음**. status ok. 작업 관리자에서 잠깐 생긴 EXCEL.EXE가 끝난 뒤 사라짐 |
| A2 | A.docx 열림 | `python word_read.py --target "C:\test\B.docx"` | A.docx 창 그대로. 추가 WINWORD.EXE는 끝난 뒤 사라짐 |
| A3 | A.pptx 열림 | `python ppt_inspect.py --target "C:\test\B.pptx"` | PowerPoint 창이 최소화되거나 깜빡이지 않음. B.pptx의 **수정한 날짜가 바뀌지 않음** |
| A4 | 엑셀 2개를 별도 프로세스로 실행 (Alt 키를 누른 채 Excel 실행) | `python excel_inspect.py --list-workbooks` | 두 프로세스의 통합문서가 모두 목록에 나옴 |

## B. 읽기 전용 동작
| # | 명령 | 기대 결과 |
|---|---|---|
| B1 | `python excel_read.py --target "C:\test\B.xlsx" --sheet 없는시트` | status error, 메시지에 실제 시트 목록이 나옴. B.xlsx에 시트가 추가되지 않고 수정한 날짜도 그대로 |
| B2 | (A.xlsx에서 Sheet1을 보고 있는 상태) `python excel_read.py --target active --sheet Sheet2` | Sheet2 내용을 읽되 **화면은 Sheet1 그대로** |
| B3 | `python excel_read.py --target active --sheet sheet2` (소문자) | Sheet2를 정상적으로 읽음 |
| B4 | `python word_read.py --target "C:\test\없는파일.docx"` | status error. **해당 파일이 생성되지 않음** |

## C. 되돌리기 (undo)
| # | 순서 | 기대 결과 |
|---|---|---|
| C1 | A.xlsx(저장됨, 열림): `python excel_fill.py --target active --range A1 --value 안녕` → `python clean.py --action undo --app excel` | 창이 잠시 닫혔다 다시 열리고 **A1이 원래 값으로 돌아옴**. JSON의 `restored_as`가 `reopened_in_office`이고 `pre_undo_backup`에 백업 경로가 있음 |
| C2 | C1 직후 `excel_fill`을 두 번(값 1, 값 2) 실행 → undo 두 번 | 첫 undo 뒤 값 1, 두 번째 undo 뒤 원래 값 |
| C3 | 새 통합문서(Book1, 저장 안 함)에서 C1과 같은 순서 | 제목 없는 새 통합문서가 하나 더 열리고, 그 안의 A1은 원래 값. `restored_as`=`new_untitled_document` |
| C4 | A.docx에 손으로 한 글자 입력(저장하지 않음) → `python word_write.py --target active --text "테스트 문장"` | 쓰기 성공(이전에는 항상 error). **입력 직후 A.docx가 자동 저장되지 않음**(파일 수정한 날짜가 그대로) |
| C5 | C4 직후 `python clean.py --action undo --app word` | "테스트 문장"이 사라지고 손으로 입력한 글자는 남음 |
| C6 | A.pptx: `python ppt_slide.py --target active --action add` → `python clean.py --action undo --app ppt` | 추가된 슬라이드가 사라짐 |
| C7 | 스냅샷이 없는 상태에서 `python clean.py --action undo --app ppt`를 반복 | status no_match |

## D. 내보내기
| # | 명령 | 기대 결과 |
|---|---|---|
| D1 | `python word_export.py --target active -o test.pdf --page-number` | PDF 하단 중앙에 페이지 번호가 있음. **A.docx 원본에는 바닥글이 추가되지 않고 저장 상태도 그대로** |
| D2 | `python word_export.py --target active -o x.docx --format pdf` | data 폴더에 `x.pdf`가 생성됨 |
| D3 | `python word_export.py --target active -o copy.docx` | `copy.docx`가 생성됨. A.docx 창의 파일 경로는 그대로 |
| D4 | `python ppt_export.py --target active -o deck.pdf` | PDF 생성 |
| D5 | `python excel_export.py --target active --output t.xlsx` | 화면에 새 통합문서 창이 남지 않음. `t.xlsx`를 열었을 때 정상적으로 보임 |

## E. Excel 편집
| # | 준비 및 명령 | 기대 결과 |
|---|---|---|
| E1 | A1:B3에 값 입력 → `python excel_range.py --target active --action move --range A1:B3 --dest B2` | 데이터가 B2:C4로 이동하고 **손실 없음** |
| E2 | `python excel_range.py --target active --action merge` | status error (범위가 필요하다는 메시지) |
| E3 | A1, B1에 모두 값 → `python excel_range.py --target active --action merge --range A1:B1` | 확인 대화상자 없이 병합됨 |
| E4 | 시트 이름 `My Sheet` 생성 → `python excel_range.py --target active --action width --range "'My Sheet'!A1" --width 30` | My Sheet의 A열 너비가 바뀜 |
| E5 | A1=1, B1=2, C1=`=A1+B1` → `python excel_edit.py --target active --find 3 --replace 9 --bg yellow` | C1은 **수식 `=A1+B1` 유지**, 배경만 노란색 |

## F. PowerPoint
| # | 명령 | 기대 결과 |
|---|---|---|
| F1 | `python ppt_slide.py --target active --action clear` | status error. 아무것도 지워지지 않음 |
| F2 | `python ppt_slide.py --target active --action clear --slide 2` | 2번 슬라이드의 요소만 삭제됨 |

## G. Outlook
| # | 명령 | 기대 결과 |
|---|---|---|
| G1 | `python outlook_write.py --action new --to "본인주소" --subject "테스트" --body "본문"` | 작성 창만 뜨고 발송되지 않음. JSON `"sent": false` |
| G2 | (선택) Outlook [파일 → 옵션 → 메일 → 서명]에 서명을 등록하고 G1을 다시 실행 | 본문 아래에 서명이 남아 있음 |
| G3 | `python outlook_write.py --action new --to "abc" --subject "테스트" --body "본문" --send` | **발송되지 않음**. 작성 창이 뜨고 status partial, `unresolved_recipients`에 "abc" |
| G4 | `python outlook_write.py --action new --to "본인주소" --subject "발송테스트" --body "본문" --send` | 본인에게 발송됨. `"sent": true` |
