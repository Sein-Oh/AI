---
name: cli_office
description: Windows MS Office(Excel, Word, PowerPoint) 활성 창 제어, 표/텍스트 쓰기, 다중 서식, 시트/범위 조작, PDF/HWP 검색 및 내보내기를 수행하는 전용 CLI 도구입니다.
---

# CLI Office 에이전트 실행 규칙 (Gemma 4 26B & OpenCode 최적화)

## 1. ⛔ 절대 금지 가드레일 (위반 시 즉시 작업 중단)
1. **외부 스크립트/디버깅 명령 금지**: `python -c`, `powershell`, `Format-Hex`, `Get-Content`, `type`, `cat` 등 우회 명령이나 `.py` 스크립트 작성을 절대 금지합니다. 오직 `cli_office`만 호출하십시오.
2. **결과 재검증 절대 금지 (One-Shot Finale)**: `cli_office` 실행 결과 JSON에 `"status": "ok"` 또는 `"VERIFIED"`가 포함되면 화면에 100% 반영된 것입니다. 확인을 위해 다시 읽거나(`--from`), `--export`를 호출하지 말고 **즉시 사용자에게 완료 보고**하십시오.
3. **재시도 금지 (Zero-Retry)**: `"status": "no_match"`, `"replacements": 0`, 또는 `"STOP_RETRY"`가 반환되면 **인자를 바꾸어 재시도하지 말고** 즉시 다음 단계로 넘어가거나 작업을 종료하십시오.
4. **다중 서식/치환은 무조건 1회 일괄 처리**: 2개 이상의 단어 치환이나 셀 서식(색상/배경/굵게) 변경 시 `--find`를 여러 번 실행하지 말고, 반드시 `C:\cli_temp\data\styles.json` 파일을 만든 뒤 **`--replace-map`으로 단 1회**만 실행하십시오.
5. **임시 데이터 격리**: 모든 입력용 `.jsonl` 및 `.json` 파일은 반드시 `C:\cli_temp\data\` 경로에만 생성하십시오.

---

## 2. ⚡ 작업별 표준 실행 문법 (Copy-Paste Recipes)

> 아래 문법으로 해결되는 작업은 `--help`를 조회하지 말고 **즉시 실행**하십시오.

### A. Excel (활성 창 제어)

#### 1) 표 데이터 주입 (필수: JSONL 파일 생성 후 주입)
* **1단계**: 파일 쓰기 도구로 `C:\cli_temp\data\input.jsonl` 생성 (한 줄에 하나의 JSON 객체 작성):
  ```jsonl
  {"type": "table_row", "data": ["2026년 10월", "", "", "", "", "", ""]}
  {"type": "table_row", "data": ["일", "월", "화", "수", "목", "금", "토"]}
  {"type": "table_row", "data": ["", "", "", "", 1, 2, 3]}
  ```
* **2단계**: 터미널에서 주입 실행 (`--clear`는 기존 시트 내용을 모두 지울 때만 추가, 특정 시트 지정은 `--pages "시트명"`):
  ```bash
  cli_office --from "C:\cli_temp\data\input.jsonl" --to excel --active
  ```

#### 2) 다중 셀 서식 / 배경색 / 텍스트 일괄 변경 (`--replace-map`)
* **1단계**: 파일 쓰기 도구로 `C:\cli_temp\data\styles.json` 생성
  - **지원 속성**: `"bg"`(배경색), `"color"`(글자색), `"bold"`(true/false), `"italic"`(true/false), `"text"`(변경할 문자열 - 생략 시 서식만 적용)
  - **지원 색상**: `red`, `blue`, `green`, `yellow`, `orange`, `purple`, `gray`, `lightgray`, `lightblue`, `lightgreen`, `lightyellow`, `pink`, `black`, `white` 또는 `#RRGGBB`
  ```json
  {
    "일": {"color": "red", "bold": true},
    "토": {"color": "blue", "bold": true},
    "19": {"bg": "yellow", "bold": true}
  }
  ```
* **2단계**: 터미널에서 일괄 적용 실행 (특정 시트만 적용할 때는 `--pages "시트명"` 추가):
  ```bash
  cli_office --to excel --active --replace-map "C:\cli_temp\data\styles.json"
  ```

#### 3) 단일 셀 서식 / 치환 (딱 1개 단어만 바꿀 때)
```bash
cli_office --to excel --active --find "합계" --style "bg:yellow; bold:true"
```

#### 4) 시트 관리 (추가 / 복제 / 이름변경 / 삭제)
```bash
cli_office --sheet-action add --sheet-name "10월달력" --to excel
cli_office --sheet-action copy --sheet-name "양식" --new-name "11월달력" --to excel
cli_office --sheet-action rename --sheet-name "Sheet1" --new-name "요약" --to excel
cli_office --sheet-action delete --sheet-name "임시시트" --to excel
```

#### 5) 셀 범위 이동 / 복사 / 지우기 (서식·수식 100% 보존 원자적 이동)
```bash
cli_office --range-action move --range "A9:C16" --dest "Sheet2!A1" --to excel
cli_office --range-action copy --range "Sheet1!A1:G10" --dest "Sheet2!A1" --to excel
cli_office --range-action clear --range "A9:C16" --to excel
```

#### 6) 표 주입과 동시에 차트 생성
```bash
cli_office --from "C:\cli_temp\data\input.jsonl" --to excel --active --chart column --chart-title "월별 실적"
```

---

### B. Word & PowerPoint (활성 창 제어)

#### 1) Word 본문 / 마크다운 표 바로 쓰기
```bash
cli_office --to word --active --data "| 항목 | 값 |\n| A | 100 |"
```

#### 2) Word / PPT 특정 앵커 위치에 내용 삽입 (`before` | `after` | `replace`)
```bash
cli_office --to word --active --anchor "[붙임]" --pos before --data "추가할 단락 내용"
```

#### 3) Word / PPT 다중 치환 및 서식 일괄 적용
```bash
cli_office --to word --active --replace-map "C:\cli_temp\data\styles.json"
cli_office --to ppt --active --pages 2 --replace-map "C:\cli_temp\data\styles.json"
```

---

### C. 문서 읽기 / 검색 / 내보내기 / 복구

#### 1) 열린 Office 창 및 시트 목록 확인
```bash
cli_office --list-active
```

#### 2) 문서 쪽수 / 목차 / 시트 0.1초 요약
```bash
cli_office --info "문서.pdf"
cli_office --info excel --active
```

#### 3) 키워드 하이브리드 검색 (PDF, HWP, HWPX, Word, Excel, PPT)
```bash
cli_office --from "보고서.hwp" --search "예산 편성" --top 10
```

#### 4) 검색 결과를 활성 Word / Excel 창으로 원스톱 전송
```bash
cli_office --from "보고서.pdf" --search "매출" --to excel --active
```

#### 5) PDF / CSV 내보내기
```bash
cli_office --export "결과.pdf" --from word --active
cli_office --export "데이터.csv" --from excel --active
```

#### 6) 직전 작업 되돌리기 (Undo) 및 오피스 멈춤 복구
```bash
cli_office --undo
cli_office --fix-env
```