---
name: cli_office
description: Windows MS Office(Excel, Word, PPT) 활성 창 제어, 표/텍스트 쓰기, 다중 서식, 시트/범위 조작, PDF/HWP 검색 및 내보내기를 수행하는 전용 CLI 도구입니다.
---

# CLI Office 에이전트 실행 규칙 (Gemma 4 최적화)

## 1. ⛔ 절대 금지 가드레일 (위반 시 즉시 작업 중단)
1. **외부 명령 및 스크립트 작성 금지**: `python -c`, `Format-Hex`, `Get-Content` 등 OS 디버깅 명령이나 `.py`/`.cmd` 파일 수정을 절대 금지합니다. 오직 `cli_office`만 호출하십시오.
2. **결과 재검증 금지**: `cli_office`가 `"status": "ok"`를 반환하면 화면에 100% 반영된 것입니다. 확인을 위해 `--export`로 CSV/PDF를 뽑거나 다시 읽지 마십시오.
3. **재시도 금지 (Zero-Retry)**: `"status": "no_match"` 또는 `"replacements": 0`, 에러 발생 시 **인자를 바꿔 재시도하지 말고** 즉시 해당 서식/단계를 생략한 채 사용자에게 완료 보고하십시오.
4. **다중 작업 일괄 처리**: 2개 이상의 단어 치환이나 셀 서식 지정은 `--find`를 여러 번 호출하지 말고 반드시 **`--replace-map` JSON 파일로 1회**에 실행하십시오.
5. **임시 파일 격리**: 모든 JSON/JSONL 입력 파일은 `C:\cli_temp\data\` 폴더에만 생성하십시오.

---

## 2. ⚡ 작업별 표준 실행 문법 (Copy-Paste Recipes)

> 아래 문법으로 해결되는 작업은 `--help`를 조회하지 말고 **즉시 실행**하십시오.

### A. Excel (활성 창 제어)
* **표 데이터 주입 (필수: JSONL 생성 후 주입)**
  1) `C:\cli_temp\data\input.jsonl` 파일 생성 (한 줄에 한 행씩 작성):
     ```jsonl
     {"type": "table_row", "data": ["2026년 10월", "", "", "", "", "", ""]}
     {"type": "table_row", "data": ["일", "월", "화", "수", "목", "금", "토"]}
     {"type": "table_row", "data": ["", "", "", "", 1, 2, 3]}
     ```
  2) 실행 (`--clear`는 기존 시트 초기화 필요 시에만 추가):
     `cli_office --from "C:\cli_temp\data\input.jsonl" --to excel --active-to`

* **다중 셀 서식 / 배경색 / 텍스트 일괄 변경 (권장)**
  1) `C:\cli_temp\data\styles.json` 생성 (`bg`: 배경색, `color`: 글자색, `bold`: 굵게, `text`: 바꿀글자):
     ```json
     {
       "일": {"color": "red", "bold": true},
       "토": {"color": "blue", "bold": true},
       "19": {"bg": "yellow", "bold": true}
     }
     ```
  2) 실행:
     `cli_office --to excel --active --replace-map "C:\cli_temp\data\styles.json"`

* **단일 셀 서식 / 치환 (1개 단어만 변경할 때)**
  `cli_office --to excel --active --find "합계" --style "bg:yellow; bold:true"`

* **시트 관리 (추가 / 복제 / 이름변경 / 삭제)**
  `cli_office --sheet-action add --sheet-name "10월달력" --to excel`
  `cli_office --sheet-action rename --sheet-name "Sheet1" --new-name "요약" --to excel`

* **셀 범위 이동 / 복사 / 지우기**
  `cli_office --range-action move --range "A9:C16" --dest "Sheet2!A1" --to excel`

### B. Word & PowerPoint (활성 창 제어)
* **Word 본문/마크다운 표 쓰기**:
  `cli_office --to word --active --data "| 항목 | 값 |\n| A | 100 |"`
* **Word/PPT 다중 치환 및 서식**:
  `cli_office --to word --active --replace-map "C:\cli_temp\data\styles.json"`
  `cli_office --to ppt --active --pages 2 --find "중요" --style "color:red; bold:true"`

### C. 문서 읽기 / 검색 / 복구
* **열린 창 목록 확인**: `cli_office --list-active`
* **문서 목차/시트 0.1초 요약**: `cli_office --info "문서.pdf"` (또는 `--info excel --active`)
* **키워드 하이브리드 검색**: `cli_office --from "보고서.hwp" --search "예산" --top 10`
* **PDF/CSV 내보내기**: `cli_office --export "결과.pdf" --from word --active`
* **직전 작업 되돌리기(Undo)**: `cli_office --undo`
* **오피스 멈춤/충돌 복구**: `cli_office --fix-env`
