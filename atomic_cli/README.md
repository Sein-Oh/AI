# [SYSTEM] atomic_cli (Micro Office & ML Automation System: Excel, Word, PowerPoint, Outlook)

> **Gemma 4 26B 전용 설계 & Solar Mini/Pro 지원: 마이크로 단위 Office 자동화 및 자율 진단 머신러닝 CLI 시스템**  
> 거대 모놀리식 CLI의 COM 프로세스 락(`RPC_E_CALL_REJECTED`)과 인지 부하를 해소하고, **선언적 Function Calling + 단일 COM 세션 주입(Single Connection) + 이벤트 분리형 자율 에이전트 엔진** 방식으로 100% 신뢰도의 무중단 오피스 제어 및 경영진 보고서 자동 생성을 보장합니다.

---

## [ARCH] 핵심 설계 원칙

1. **원자적 기능 블록 (Atomic Micro CLI)**:  
   각 모듈은 오직 1가지 역할만 전담하며, 독립 터미널 CLI 실행과 Python API 호출을 완벽 지원합니다.
2. **에이전트 인메모리 직결 조율 (Zero-JSON In-Memory Coordination)**:  
   복잡한 정적 레시피 작성 없이, AI 에이전트(`atomic_agent.py`)가 자연어 질의에 따라 실시간으로 마이크로 도구들을 직접 Function Calling으로 조율합니다. (Gemma 4 26B 전용 최적화 및 Solar Mini/Pro 완벽 지원)
3. **Agent Guardrail 1줄 JSON 출력 & 대용량 전송 최적화 (Clamped Data)**:  
   터미널 잡음(`print`)을 전면 차단하고, 오직 단 1줄의 정형화된 JSON(`status`, `action`, `preview`, `agent_directive`)만 반환합니다. 100행 이상의 대용량 표/데이터셋은 4KB 크기의 대표 통계 표본으로 자동 요약 압축(`clamp_tool_result`)하여 토큰 낭비 및 불필요한 페이징 루프를 원천 차단합니다.
4. **활성 창 In-Place 치환 우선 원칙 (In-Place Text Replacement)**:  
   번역, 문구 수정, 오타 교정 시 새 문서를 만들거나 끝에 덧붙이지 않고, 기존 문서의 양식과 서식을 100% 보존한 채 제자리에서 일괄 치환(`replace_map` 1회 호출)합니다.
5. **메인 엔진 & 인터랙티브 TUI 이원화 (`atomic_agent.py` & `atomic_agent_tui.py`)**:  
   단발성 일회성 작업(`atomic_agent.py`)과 대화 기억 모드(`atomic_agent_tui.py`)의 2개 진입점으로 단순화하여 직관성을 극대화했습니다.
6. **JIT 실시간 자가복구 (Just-In-Time Self-Healing)**:  
   COM 연결 중단(`0x800706BA` RPC 에러), 유령 프로세스 락, 파일 점유(`PermissionError`), 인코딩 불일치 발생 시 즉시 중단되지 않고, 실행 시점(JIT)에 백그라운드에서 유령 프로세스 정리 및 아파트먼트 리셋/섀도 복사를 거쳐 1회 자동 재시도하여 작업을 무중단 완료합니다.
7. **Windows 가상 데스크톱 격리 해제 & Native 창 직결 (Sandbox Desktop Bridge)**:  
   - Antigravity / 샌드박스 가상 데스크톱(`exebox-*`) 환경에서도 사용자의 실제 GUI 데스크톱(`Default`)으로 자동 연결(`SetThreadDesktop`).
   - Native 창 핸들(`EXCEL7`, `_WwG`, `paneClassDC`)을 oleacc `AccessibleObjectFromWindow`를 통해 100% 직결 바인딩하여, 백그라운드 유령 프로세스 개입을 완벽 차단하고 사용자 화면에 실시간으로 반영합니다.
8. **클린 터미널 원칙 (Clean Terminal & Zero Emoji Principle)**:  
   Windows 콘솔(CP949/UTF-8) 환경에서 유니코드 이모지로 인한 폭 계산 오차, 줄바꿈 꼬임, 로그 오염, 인코딩 에러(`UnicodeEncodeError`)를 원천 방지하기 위해 이모지 사용을 엄격히 금지하고 표준 태그(`[INFO]`, `[WARN]`, `[STATUS]` 등)만 사용합니다.
9. **윈도우 콘솔 프리징 방지 & 클립보드 안전성 (QuickEdit Freeze Prevention)**:  
   마우스 클릭 시 발생하는 터미널 일시 정지(QuickEdit Mode)를 자동 해제하며, `prompt_toolkit` 기반 Bracketed Paste 지원으로 대용량 프롬프트 복사-붙여넣기 시 꼬임을 방지합니다.
10. **타겟별 세션 및 이력 고립 (Target-Isolated Ledger)**:  
   머신러닝 실험 시 타겟별 독립 폴더(`atomic_cli/data/ml_sessions/{target}/`)에 장부(`history.jsonl`), 상관계수(`eda_correlation.json`), 챔피언 모델(`champion_model.joblib`)을 격리 보관합니다.

---

## [DIR] 디렉터리 구조

```text
atomic_cli/
├── README.md              # 본 사용 설명서
├── config.json            # 데이터 및 캐시 기본 저장 경로, 모델 API 설정
├── cache/                 # [캐시 폴더] 디스크 파일 대상 초고속 캐시 저장소 (최근 2개 유지)
│   └── prompt_history.txt # [터미널 UI] 사용자 프롬프트 영구 히스토리
├── data/                  # [데이터 폴더] 입력/출력 CSV, XLSX, DOCX, PPTX 및 styles.json
│   └── ml_sessions/       # [ML 장부] 타겟별 격리된 실험 이력, 상관분석, 챔피언 모델 저장소
│       └── {target}/      # 예: 인장강도/ (history.jsonl, eda_correlation.json, champion_model.joblib)
├── _com_guard.py          # [세션 가드] 활성창 캡처 & Excel/Word/PPT COM 수명주기 관리
├── _office_utils.py       # [공통 유틸] 단 1줄 UTF-8 JSON 출력, 색상 변환, CSV 파서
├── _config.py             # [설정 모듈] 동적 레시피/데이터/캐시 경로 자동 탐색
├── _cache.py              # [캐시 모듈] mtime + 절대경로 기반 무결성 검증 & 최근 2개 유지
│
├── [자율 에이전트 엔진 & 인터랙티브 TUI 블록]
│   ├── atomic_agent.py     # [메인 엔진] 코어 엔진 & 원샷 CLI 실행기 (python atomic_agent.py "명령")
│   └── atomic_agent_tui.py # [대화형 TUI] 멀티턴 세션 기억 대화 콘솔 (python atomic_agent_tui.py)
│
├── [Excel 블록]
│   ├── excel_sheet.py     # 시트 생성, 복제, 이름변경, 삭제, 활성화
│   ├── excel_fill.py      # 2D 배열 일괄 대입 초고속 CSV 표 주입 & 원스톱 테마(--theme)/수식/AutoFit
│   ├── excel_edit.py      # 셀 내용 수정(치환), 조건부 서식 룰(--rule '>=100:green') 및 다중 서식 일괄 적용
│   ├── excel_range.py     # AutoFit, 열너비/행높이, 테두리, 셀 병합/이동, 틀고정/숨김
│   ├── excel_chart.py     # 막대/꺾은선/원형/혼합 콤보(Combo) 차트 생성 및 위치/크기 배치
│   ├── excel_read.py      # 활성창 실시간 조회 / 디스크 파일 캐시(0.005초) & 검색
│   ├── excel_inspect.py   # 문서 상태 진단 (파일명, 시트목록, 글자수, 차트/이미지수)
│   └── excel_export.py    # 활성창 보존 CSV & XLSX 내보내기 (비연속 열 지원)
│
├── [Word 블록]
│   ├── word_read.py       # DOCX XML 초고속 파싱 & 단락/표 위치 추출 (캐시 0.001초)
│   ├── word_write.py      # 단락 텍스트, 목차(--component toc), 콜아웃 상자, 테마 표 생성, 앵커 위치 삽입
│   ├── word_edit.py       # 다중 단어 치환, 글꼴/색상/굵기/형광펜 서식 일괄 적용
│   ├── word_inspect.py    # 단락, 단어, 글자 수, 표 크기, 이미지 통계 진단
│   └── word_export.py     # 활성창 보존 PDF 및 복제본 DOCX 내보내기, 하단 페이지 번호 매김
│
├── [PowerPoint 블록]
│   ├── ppt_read.py        # PPTX XML 초고속 파싱 & 슬라이드별 텍스트 추출 (캐시 0.001초)
│   ├── ppt_slide.py       # 슬라이드 추가, 완전 복제(duplicate), 순서 이동, 삭제, 총 장수 확인
│   ├── ppt_write.py       # 스마트 누적(Smart Stacking) 기반 제목, 비주얼 카드, 테마 표 자동 생성
│   ├── ppt_edit.py        # 슬라이드/표/셰이프 텍스트 일괄 치환 및 글꼴 서식 적용
│   ├── ppt_inspect.py     # 프레젠테이션 진단 (슬라이드별 제목, 글자수, 표/도형 통계)
│   └── ppt_export.py      # 활성창 보존 PDF 및 복제본 PPTX 내보내기
│
├── [데이터 과학 및 머신러닝 (ACI Flywheel) & 복구 / 제어 블록]
│   ├── ml_pandas.py       # 판다스 수식 연산(AST eval), 이상치 탐지, Joblib 직렬화 & 활성창 SafeArray 통신
│   ├── ml_eda.py          # 심층 EDA, 타겟 누수(Leakage) 감사, 왜도/다중공선성, 비선형 MI 힌트
│   ├── ml_feature.py      # 도메인 전문가 수식 엔진(--expr), 0나누기 방지 epsilon, 타겟 100% 격리
│   ├── ml_train.py        # 목표 지향(R2>=0.9) ACI 학습기, Strict K-Fold, 서킷 브레이커, 타겟별 이력 장부
│   ├── ml_report.py       # [신규] C-Level 경영진 6단락 의사결정 보고서 자동 작성 엔진 (Word/PPT)
│   ├── clean.py           # 환경 복구, 백그라운드 유령 프로세스 정리, 캐시 청소 및 직전 작업 원클릭 되돌리기(Undo)
│   └── office_window.py   # 열려 있는 모든 Office(Excel/Word/PPT) 창/문서 실시간 탐색 및 최상단 포커스 전환
│
├── [비주얼 스타일링 & 테마 역공학 블록]
│   └── office_theme.py    # 기존 문서(Excel/Word/PPT) 스타일 DNA 역공학 추출 & 기업용 테마 프리셋 엔진
│
├── [크로스 오피스 통합 브릿지 블록]
│   └── office_bridge.py   # Excel 표/차트 원클릭 복사 및 Word/PowerPoint 정밀 배치 브릿지
│
├── [MS Outlook 메일 자동화 블록]
│   ├── _outlook_guard.py  # Outlook COM 수명주기 및 MAPI 네임스페이스 가드
│   ├── outlook_read.py    # 아웃룩 자체 검색 직결, 백그라운드 메일 읽기, 현재 보고 있는 메일 캡처, 폴더 트리
│   └── outlook_write.py   # 네이티브 답장/전달 원본 이력 100% 보존, 화면 팝업 기본(직접 발송), 첨부파일 연동
│
├── [외부 문서 파싱 블록 (PDF & HWP)]
│   ├── pdf_read.py        # PDF 고속 텍스트 추출, 페이지별 번호 색인, 검색 (캐시 0.001초)
│   └── hwp_read.py        # HWP 5.0 (OLE) 및 HWPX 텍스트 추출 & 단락 색인 (캐시 0.001초)
│
└── [통합 색인 검색 블록]
    └── search.py          # 자동 파일 경로 사전 해결, JSON 캐시 전수 탐색, 위치 기반 검색 (0.005초)
```

---

## [START] 빠른 시작 (Quick Start)

> [!NOTE] 실행 경로 안내
> 본 README의 CLI 명령어는 프로젝트 루트 디렉터리(`atomic_cli/`) 내에서 직접 실행(`python <모듈명>.py ...`)하거나, 상위 디렉터리에서 실행(`python <모듈명>.py ...`)할 수 있습니다. 아래 예시는 `atomic_cli/` 디렉터리 내 직접 실행 기준입니다.

### 1. 백엔드 LLM 설정 (`config.json`)

`atomic_cli/config.json`에서 LLM 엔드포인트와 데이터/캐시 경로를 설정합니다.  
본 시스템은 **Gemma 4 26B (vLLM/로컬 서빙)** 및 **Upstage Solar Mini/Pro (API)**를 모두 기본 지원합니다.

```json
{
  "data_dir": "C:/Users/JooJoo/Desktop/AI/cli/atomic_cli/data",
  "cache_dir": "C:/Users/JooJoo/Desktop/AI/cli/atomic_cli/cache",
  "base_url": "https://api.upstage.ai/v1",
  "model_name": "solar-mini4",
  "api_key": "your-api-key"
}
```

- **Gemma 4 26B 로컬 서빙 사용 시**: `"base_url": "http://localhost:8000/v1"`, `"model_name": "gemma-4-26b-it"`, `"api_key": "EMPTY"`
- **Solar Mini/Pro 사용 시**: `"base_url": "https://api.upstage.ai/v1"`, `"model_name": "solar-mini4"` 또는 `"solar-pro"`, `"api_key": "up_..."`

### 2. 에이전트 실행 진입점

```bash
# ① 원샷 CLI 모드: 단발성 일회성 작업 완결
python atomic_agent.py "파일 'data/sample_production.xlsx' 검사해줘"
python atomic_agent.py "열려 있는 엑셀 창에 A1부터 10행 표 채우고 navy 테마 적용해줘"

# ② 대화형 TUI 모드: 이전 작업 결과를 기억하는 멀티턴 대화 세션
python atomic_agent_tui.py
```

### 3. 마이크로 CLI 도구 단독 실행

에이전트 없이 터미널에서 30종 마이크로 도구를 단독 명령어로 즉시 호출할 수 있습니다:

```bash
# 엑셀 활성 시트 상태 진단
python excel_inspect.py --target active

# 워드 활성 문서에 본문 추가
python word_write.py --target active --text "자동화 보고서 생성 완료"

# 캐시된 원본 문서 목록 고속 조회
python search.py --list
```

---

## [EXCEL] Excel 마이크로 블록 레퍼런스

각 블록은 `atomic_agent.py`의 Function Calling 도구로 자동 조율되거나, 터미널에서 단독 CLI로도 실행 가능합니다.

### 1. `excel_sheet` (시트 관리)
- **`action`**:
  - `"ensure"`: 시트가 있으면 활성화, 없으면 새로 생성 (가장 권장)
  - `"add"`: 새 시트 추가 (`name`)
  - `"rename"`: 이름 변경 (`name`, `new_name`)
  - `"copy"`: 시트 복제 (`name`, `new_name`)
  - `"delete"`: 시트 삭제 (`name`)
  - `"select"`: 시트 전환 (`name`)
  - `"list"`: 전체 시트 목록 반환
- **단독 실행**:
  ```bash
  python excel_sheet.py --target active --action ensure --name "10월보고"
  ```

### 2. `excel_fill` (초고속 데이터 주입 & 수식/덧붙이기)
- 셀을 루프로 반복 대입하지 않고, 2차원 튜플을 `Range.Value`에 **1회 일괄 대입(속도 0.05초)**합니다.
- **주요 기능**:
  - **초고속 표 주입**: 대용량 2D SafeArray 일괄 대입
  - **스마트 덧붙이기 (`--mode append`)**: 기존 표의 마지막 행(`UsedRange` 최하단)을 자동 탐지하여 헤더 중복 없이 데이터를 연속 누적
  - **원터치 수식 계산 주입 (`--formula`)**: Excel 네이티브 수식(예: `"=SUM(C2:C10)"`, `"=AVERAGE(D2:D10)"`)을 주입하여 자동 계산 및 결과값 반영
  - **열너비 자동 최적화 (`--autofit` / `--no-autofit`)**: 주입 후 `###` 열너비 부족 현상을 방지하는 자동 너비 조정
- **파라미터**:
  - `range`: 시작 셀 (기본 `"A1"`)
  - `data_file`: 주입할 CSV 파일명 또는 경로 (`utf-8-sig`, `cp949`, `utf-8` 자동 감지)
  - `value`: 단일 셀에 쓸 텍스트/숫자
  - `formula`: 주입할 엑셀 수식 (예: `"=SUM(C2:C10)"`)
  - `mode`: `"overwrite"` (덮어쓰기, 기본) 또는 `"append"` (하단 덧붙이기)
  - `clear`: `true`일 경우 주입 전 기존 시트 내용 초기화
  - `autofit`: `true` (기본) / `false`
- **단독 실행**:
  ```bash
  # CSV 표 덮어쓰기 주입 (기본 A1부터 시작, 열너비 자동맞춤)
  python excel_fill.py --target active --range A1 --data-file "C:/cli_data/data/table.csv"

  # 기존 표 하단에 새 데이터 덧붙이기 (Append)
  python excel_fill.py --target active --data-file "C:/cli_data/data/append_data.csv" --mode append

  # 특정 셀에 합계 수식 주입
  python excel_fill.py --target active --range "E11" --formula "=SUM(E2:E10)"
  ```

### 3. `excel_edit` (셀 내용 수정/치환 & 다중 서식, `excel_style` 호환)
- `styles.json` 또는 `edit_rules.json` 매핑 파일 또는 인라인 단일 치환/스타일을 적용합니다.
- **내용 치환 및 숫자 셀 COM 버그 완벽 방어**: 셀 내용 치환(`--replace` 또는 `"text": "새내용"`)과 배경색/글자색/정렬/굵기 서식을 단 1회 호출로 원자적 적용.
- **`styles.json` (또는 `edit_rules.json`) 작성 규격**:
  ```json
  {
    "A1:E1": {"bg": "lightblue", "bold": true, "align": "center"},
    "19": {"text": "20", "bg": "yellow", "bold": true},
    "담당자": {"text": "김철수", "color": "blue", "bold": true}
  }
  ```
- **지원 속성**:
  - `text` / `replace`: 변경할 문자열/숫자
  - `bg`: 배경색 (`"red"`, `"lightblue"`, `"#RRGGBB"` 등)
  - `color`: 글자색
  - `bold`: `true` / `false`
  - `italic`: `true` / `false`
  - `size`: 글꼴 크기 (pt)
  - `align`: `"left"`, `"center"`, `"right"`
- **단독 실행**:
  ```bash
  # 매핑 파일 기반 일괄 수정 및 서식
  python excel_edit.py --target active --replace-map "C:/cli_data/data/styles.json"

  # 단일 텍스트 검색 및 치환 + 서식
  python excel_edit.py --target active --find "합계" --replace "총합계" --bg yellow --bold

  # 기존 excel_style.py 호출도 100% 호환 동작
  python excel_style.py --target active --replace-map "C:/cli_data/data/styles.json"
  ```

### 4. `excel_range` (셀 범위 조작 & 틀고정/숨김)
- **`action`**:
  - `"autofit"`: 열 너비 자동 맞춤 (`range: "A:E"`)
  - `"borders"`: 격자 테두리 긋기 (`weight: "thin"`, `"medium"`, `"thick"`, `"box": true`)
  - `"freeze"`: 대용량 시트 헤더/열 틀 고정 (`range: "A2"` 또는 `"B2"`, 기준 셀 좌상단 고정)
  - `"unfreeze"`: 시트 틀 고정 해제
  - `"hide"`: 행 또는 열 숨기기 (`range: "D:D"` 또는 `"5:10"`, `target_type: "col"` 또는 `"row"`)
  - `"unhide"`: 행 또는 열 숨기기 취소
  - `"width"` / `"height"`: 열 너비 / 행 높이 직접 지정
  - `"merge"` / `"unmerge"`: 셀 병합 / 병합 해제
  - `"clear"`: 범위 지우기 (`type: "all"`, `"contents"`, `"formats"`)
  - `"copy"` / `"move"`: 범위 복사 / 이동 (`range: "A1:D5"`, `dest: "Sheet2!A1"`)
- **단독 실행**:
  ```bash
  # 1행 헤더 틀 고정
  python excel_range.py --target active --action freeze --range "A2"

  # 불필요한 D열 숨기기
  python excel_range.py --target active --action hide --range "D:D"

  # 열 너비 자동 맞춤
  python excel_range.py --target active --action autofit --range "A:E"
  ```

### 5. `excel_chart` (비즈니스 차트 생성 & 차트 삭제)
- **파라미터**:
  - `action`: `"create"` (기본, 차트 생성) 또는 `"delete"` / `"clear"` (시트 내 차트 삭제)
  - `range`: 차트 원본 데이터 영역 (예: `"A1:C74"`, create 시 필수)
  - `type`:
    - `"column"`: 묶은 세로 막대형
    - `"bar"`: 가로 막대형
    - `"line"`: 꺾은선형
    - `"pie"`: 원형
    - `"area"`: 영역형
    - `"combo"`: **[신규] 혼합 복합차트** (1계열 세로막대 기본축 + 2계열 꺾은선 보조축)
  - `title`: 차트 제목 (delete 시 특정 차트 지정 가능, 생략 시 시트 전체 차트 일괄 삭제)
  - `target_cell`: 차트 좌상단이 위치할 앵커 셀 (기본 `"G2"`)
  - `width` / `height`: 차트 크기 (기본 `450` x `260`)
  - `theme`: 비즈니스 테마 팔레트 (`navy`, `slate`, `teal`, `emerald`)
  - `data_labels`: 데이터 레이블(수치) 표시 (`true` / `false`)
  - `legend`: 범례 위치 (`"bottom"`, `"right"`, `"top"`, `"none"`)
- **단독 실행**:
  ```bash
  # 1. 꺾은선 차트 생성
  python excel_chart.py --target active --range "C1:C74" --type line --title "사인곡선" --target-cell "E2"

  # 2. 실적 & 달성률 혼합 콤보 차트 생성 (보조축 + 데이터 레이블 + 하단 범례)
  python excel_chart.py --target active --range "A1:C12" --type combo --title "월별 매출 및 달성률" --theme navy --data-labels --legend bottom

  # 3. 시트 내 모든 차트 일괄 삭제
  python excel_chart.py --target active --action delete
  ```

### 6. `excel_read` (데이터 조회 & 캐시)
- **File ON vs Active OFF 캐싱 원칙**:
  - **활성 창(`target="active"`)**: 화면의 미저장 실시간 데이터를 반영해야 하므로 **캐시를 100% 우회**하고 실시간 메모리 직접 조회
  - **디스크 파일(`target="파일경로"`)**:
    - 파일의 **절대경로 + mtime(수정시각)** 기반으로 캐시 무결성을 검증합니다.
    - 캐시 히트 시 **무거운 Excel 프로세스를 전혀 띄우지 않고 0.005초 만에 인메모리 반환**합니다.
    - **최근 2개 유지 정책**: 파일이 수정되어 새 캐시가 생성되면, 해당 원본 파일에 대해 **가장 최근 2개의 캐시 버전만 남기고 이전 캐시는 디스크에서 자동 삭제(Purge)**되어 용량을 영구적으로 아낍니다.
- **파라미터**:
  - `range`: 읽을 주소 (생략 시 `UsedRange`)
  - `search`: 특정 검색어가 포함된 셀 좌표 및 값 검색
  - `format`: `"table"` (2차원 리스트) 또는 `"summary"`
- **단독 실행**:
  ```bash
  python excel_read.py --target "C:/.../sample.xlsx" --search "중간부품"
  ```

### 7. `excel_inspect` (문서 상태 종합 검사 & 다중 창 전수 조사)
- 데이터 입력, 수정, 서식 적용이 제대로 반영되었는지 에이전트/사용자가 **0.05초 만에 신속 검증**하기 위한 필수 상태 진단 도구입니다.
- **다중 프로세스 지원**: 윈도우에서 엑셀이 여러 개(`EXCEL.EXE` 복수 프로세스) 실행 중이더라도, 실행 중인 모든 엑셀 인스턴스를 전수 탐색하여 열린 문서를 일괄 식별합니다.
- **기능**:
  - **열린 전체 문서 고속 목록 (`--list-workbooks` 또는 `--all`)**: 현재 실행 중인 모든 엑셀 창의 통합 문서 목록, 저장 상태, 시트 목록을 0.01초 만에 일괄 출력합니다.
  - **통합 문서 상세 검사 (`--sheet` 생략)**: 파일명, 전체 시트 목록, 활성 시트, 총 글자 수, 채워진 셀 수, 차트 수, 이미지/도형 수를 일괄 보고합니다. 특정 실행 중인 문서 이름을 `--target "Book1"`처럼 지정할 수 있습니다.
  - **특정 시트 상세 검사 (`--sheet "시트명"`)**: 해당 시트의 사용 범위(`A1:C74`), 행/열 크기, 글자 수, 차트 목록 및 제목, 이미지 수, 상위 행 내용 미리보기를 상세 보고합니다.
- **단독 실행**:
  ```bash
  # 실행 중인 모든 엑셀 프로세스의 열린 파일 목록 조회
  python excel_inspect.py --list-workbooks

  # 활성 문서 상태 요약 (파일명, 시트목록, 총글자수, 차트/이미지수)
  python excel_inspect.py --target active

  # 실행 중인 특정 문서(예: Book1) 지정 검사
  python excel_inspect.py --target "Book1"

  # 특정 시트만 상세 검사
  python excel_inspect.py --target active --sheet "사인2주기"
  ```

### 8. `excel_export` (안전한 CSV & XLSX 내보내기)
- **Active Window Preservation (활성 창 무결성 100% 보장)**:  
  기존 거대 CLI처럼 `wb.SaveAs("file.csv")`로 엑셀 창 자체가 CSV로 바뀌어버리는 치명적 부작용을 원천 차단하고, 화면의 엑셀 창은 온전히 유지한 채 파일만 깨끗하게 디스크에 저장합니다.
- **파라미터**:
  - `sheet`: 대상 시트명 (생략 시 현재 활성 시트)
  - `range`: 내보낼 셀 범위 (예: `"A1:C10"`, 생략 시 `UsedRange`)
  - `output_file`: 저장할 파일명 또는 경로 (`.csv` 또는 `.xlsx` 확장자에 따라 자동 포맷 감지, 파일명만 기입 시 `data_dir`에 자동 저장)
  - `format`: `"csv"` 또는 `"xlsx"` (선택 사항)
- **단독 실행**:
  ```bash
  # 활성 시트의 A1:C10 범위를 CSV로 저장 (utf-8-sig 한글 보존)
  python excel_export.py --target active --range "A1:C10" --output "sample.csv"

  # 비연속 열(A열, C열, E열만) 추출하여 CSV로 저장
  python excel_export.py --target active --columns "A,C,E" --output "selected_cols.csv"

  # 특정 시트 전체를 서식/수식이 보존된 독립 새 XLSX 파일로 저장
  python excel_export.py --target active --sheet "사인2주기" --output "sine_backup.xlsx"
  ```
- **JSON 레시피 내 활용**:
  ```json
  {
    "module": "excel_export",
    "params": {
      "sheet": "ML_데이터가공",
      "range": "A1:C10",
      "output_file": "exported_data.csv"
    }
  }
  ```

---

## [WORD] Word 마이크로 블록 상세 규격

Word 문서는 `target="active"` 또는 `"sample.docx"` 파일을 지정하여 제어합니다.

### 1. `word_write` (본문, 표, 이미지, 콜아웃 & 복합 마크다운 원샷 렌더러)
- **기능**:
  - 본문 텍스트 추가 (줄바꿈 지원) 및 불릿 글머리 기호 목록(`--bullet`)
  - **네이티브 복합 마크다운 렌더러 (`--component markdown`)**:
    마크다운 텍스트 전문을 단 1회 호출하여 Word 네이티브 서식 요소(대제목 `#`, 중제목 `##`, 소제목 `###`, 본문 단락, 테마 표 `|`, 불릿 `-`)로 원샷 일괄 자동 생성 (AI 보고서 작성 시 최우선 권장)
  - **시각적 강조 요약 콜아웃 박스 (`--component callout`)**: 문서 상단이나 결론부에 기업 테마 테두리와 은은한 배경색이 적용된 1x1 Callout 박스 생성
  - **고해상도 이미지 삽입 (`--image <path>`)**: 문서 내 지정 위치(너비 자동 맞춤)에 이미지/도표 원클릭 삽입
  - 마크다운 형식의 표 텍스트(`| 열1 | 열2 |`) 또는 CSV 파일을 Word 기본 네이티브 표(`Table`)로 자동 변환 생성
  - 특정 텍스트를 기준으로 앞(`before`), 뒤(`after`), 또는 대체(`replace`) 삽입하는 앵커(`anchor`) 기능
- **파라미터**:
  - `text`: 삽입할 일반 텍스트 또는 마크다운 전문 문자열
  - `component`: `"markdown"` (복합 마크다운 렌더러), `"callout"` (요약 강조 상자), `"table"` (표), `"toc"` (목차)
  - `data_file`: 표로 변환할 CSV 파일명 (data_dir 기준)
  - `image`: 삽입할 이미지 파일 경로 (`.png`, `.jpg` 등)
  - `bullet`: `true`일 경우 글머리 기호 리스트로 작성
  - `theme`: 적용할 테마 프리셋 (`navy`, `slate`, `teal`, `emerald`)
  - `anchor`: 삽입 기준이 될 기존 단락/키워드
  - `pos`: `"after"` (기본), `"before"`, `"replace"`
- **단독 실행**:
  ```bash
  # 1. 네이티브 복합 마크다운 보고서 원샷 생성 (제목, 본문, 테마 표, 불릿 일괄 렌더링)
  python word_write.py --target active --component markdown --text "# AI 혁신 공정 보고서\n\n본 보고서는 2026년 공정 최적화 결과입니다.\n\n| 공정 | 목표수율 | 달성수율 |\n|---|---|---|\n| 가열 | 95.0% | 98.2% |\n| 냉각 | 92.0% | 94.5% |\n\n- 이상치 0건 검증 완료\n- 차기 분기 양산 적용 권고"

  # 2. 핵심 요약 콜아웃 박스 삽입 (네이비 테마)
  python word_write.py --target active --component callout --text "핵심 요약: 시스템 전환 후 데이터 처리 속도가 8배 향상되었습니다." --theme navy

  # 3. 차트 이미지 삽입 (너비 420pt)
  python word_write.py --target active --image "C:/cli_data/data/chart.png" --width 420
  ```

### 2. `word_edit` (In-Place 제자리 치환 & 서식 적용, `word_style` 호환)
- **In-Place 치환 우선 원칙 (In-Place Text Replacement)**:
  - 활성 Word 문서를 번역하거나 문구를 수정할 때, **새 문서를 만들거나 끝에 덧붙이지 않고 기존 문서의 폰트/표/서식을 100% 보존한 채 제자리에서 내용을 치환**합니다.
  - `styles.json` 또는 `replace_map` 매핑 파일 1회 전달로 수십 개의 단어/문장 일괄 치환, 글꼴 색상, 굵기, 형광펜 하이라이트 동시 적용.
  - 단일 키워드 즉시 검색/치환(`--find`, `--replace`) 및 서식 옵션 제공.
- **파라미터**:
  - `replace_map` / `mapping_file`: 스타일/치환 매핑 JSON 파일 경로 (예: `{"기존단어": "새단어", "원문": {"text": "번역문", "bold": true}}`)
  - `find`: 검색할 단어
  - `replace`: 치환할 단어 (생략 시 단어 유지한 채 서식만 적용)
  - `color`: 헥사코드(`"#0000FF"`) 또는 BGR 정수
  - `bold`: `true` / `false`
  - `highlight`: 형광펜 색상 (yellow, green, blue, red, pink, gray 등)
- **단독 실행**:
  ```bash
  # 1. 다중 단어 In-Place 일괄 치환 (서식 보존)
  python word_edit.py --target active --replace-map "C:/cli_data/data/styles.json"

  # 2. 특정 단어 검색 후 제자리 치환 및 글자색/굵게 적용
  python word_edit.py --target active --find "초안" --replace "최종본" --color "#0000FF" --bold
  ```

### 3. `word_inspect` (문서 상태 종합 진단 & 열린 문서 전수 조사)
- **기능**:
  - **열린 전체 문서 목록 (`--list-docs` 또는 `--all`)**: 현재 실행 중인 모든 Word 창의 문서 목록, 저장 상태, 전체 경로를 0.01초 만에 일괄 출력합니다.
  - **문서 상세 진단 (`--target` 지정)**: 단락 수, 전체 글자 수, 단어 수, 표 개수 및 행/열 크기, 이미지 수를 0.05초 만에 신속 진단합니다. 열려 있는 문서명을 `--target "word_test.docx"`처럼 직접 지정할 수 있습니다.
- **단독 실행**:
  ```bash
  # 실행 중인 모든 Word 문서 목록 조회
  python word_inspect.py --list-docs

  # 활성 Word 문서 상태 상세 진단
  python word_inspect.py --target active

  # 실행 중인 특정 문서 지정 진단
  python word_inspect.py --target "word_test.docx"
  ```

### 4. `word_export` (안전한 PDF, 복제본 DOCX 내보내기 & 페이지 번호)
- **기능**:
  - 현재 열려 있는 활성 창의 파일 경로나 편집 상태를 훼손하지 않고 디스크에 안전하게 저장
  - **하단 중앙 페이지 번호 자동 삽입 (`--page-number`)**: 문서 바닥글(Footer) 중앙에 `- 1 -` 스타일의 페이지 번호 자동 부여
  - `format="pdf"`: Office 2007~365 호환 PDF 내보내기
  - `format="docx"`: 현재 문서를 백업 또는 새 이름으로 복제 저장
- **단독 실행**:
  ```bash
  # 페이지 번호를 자동 삽입하여 완성형 PDF로 내보내기
  python word_export.py --target active --output "report_final.pdf" --format pdf --page-number

  # 안전 복제본 저장
  python word_export.py --target active --output "report_backup.docx"
  ```

---

## [PPT] PowerPoint 마이크로 블록 상세 규격

PowerPoint 프레젠테이션은 `target="active"` 또는 `"presentation.pptx"` 파일을 지정하여 제어합니다.

### 1. `ppt_slide` (슬라이드 관리)
- **기능**:
  - 슬라이드 추가 (`add`), 복제 (`duplicate`), 순서 이동 (`move`), 삭제 (`delete`)
- **파라미터**:
  - `action`: `"add"`, `"duplicate"`, `"delete"`, `"move"`, `"count"`
  - `slide`: 대상 슬라이드 번호 (1-based)
  - `dest`: 이동 시 목표 위치 슬라이드 번호
- **단독 실행**:
  ```bash
  # 맨 뒤에 빈 슬라이드 1장 추가
  python ppt_slide.py --target active --action add

  # 1번 슬라이드를 3번 슬라이드 뒤로 이동
  python ppt_slide.py --target active --action move --slide 1 --dest 3
  ```

### 2. `ppt_write` (텍스트 상자, 네이티브 표, 이미지 & 카드 레이아웃 생성)
- **기능**:
  - 슬라이드 제목(24pt Bold) 및 본문 텍스트 상자 자동 배치
  - **3~4열 카드 컨테이너 레이아웃 (`--component cards`, `--cards "제목:내용|..."`)**: 전략 기획, 단계별 프로세스, 핵심 가치 전달에 필수적인 모던 카드형 박스 자동 균등 분할 배치
  - **고해상도 이미지 삽입 (`--image <path>`)**: 슬라이드 내 지정 좌표 및 크기로 도표/사진 자동 삽입
  - 마크다운 표 또는 CSV 파일을 PowerPoint 네이티브 표(`Shapes.AddTable`)로 자동 생성 (Office 2007 75행 제한 안전 보호 & 행 수에 따른 글꼴 크기 스마트 최적화)
- **파라미터**:
  - `slide`: 대상 슬라이드 번호
  - `title`: 제목 텍스트 (상단 배치)
  - `text` / `body`: 본문 설명 텍스트
  - `table_data`: 마크다운 표 문자열 또는 2차원 리스트
  - `data_file`: 표로 변환할 CSV 파일 경로
  - `image`: 삽입할 이미지 파일 경로
  - `component`: `"cards"` (카드 컴포넌트)
  - `cards`: 카드 목록 문자열 (`"제목:내용|제목:내용"`)
  - `theme`: 적용할 테마 프리셋 (`navy`, `slate`, `teal`, `emerald`)
  - `left`, `top`, `width`, `height`: 위치 및 크기 지정 (선택)
- **단독 실행**:
  ```bash
  # 1. 제목 및 본문 텍스트 추가
  python ppt_write.py --target active --slide 1 --title "프로젝트 요약" --text "자동화 완료"

  # 2. 3열 카드 레이아웃 생성 (모던 비즈니스 스타일)
  python ppt_write.py --target active --slide 2 --title "추진 전략" --component cards --cards "안정성:COM 무중단 보장|확장성:마이크로 모듈 구조|보안성:폐쇄망 100% 호환" --theme navy

  # 3. 이미지 삽입
  python ppt_write.py --target active --slide 3 --image "C:/cli_data/data/diagram.png" --left 60 --top 120 --width 600
  ```

### 3. `ppt_edit` (In-Place 제자리 치환 & 서식 적용, `ppt_style` 호환)
- **In-Place 치환 우선 원칙 (In-Place Text Replacement)**:
  - 기존 슬라이드의 디자인, 레이아웃, 도형 위치를 100% 유지하면서 텍스트 상자 및 **표(Table) 내부 셀 텍스트까지 완벽하게 탐색**하여 제자리에서 치환합니다.
  - 무한 루프 방지 가드(`loop_count < 50` & 빠른 부분문자열 사전 검사) 탑재.
  - `replace_map` 매핑 파일 1회 호출로 슬라이드 전반의 다중 단어/문장 일괄 치환 및 서식 적용 지원.
- **파라미터**:
  - `slide`: 특정 슬라이드 번호 (생략 시 전체 슬라이드 일괄 검사)
  - `replace_map`: `styles.json` 매핑 파일 (예: `{"진행중": "완료", "Draft": "Final"}`)
  - `find`: 검색어
  - `replace`: 치환할 새 단어
  - `bold`, `italic`, `size`, `color`
- **단독 실행**:
  ```bash
  # 1. 다중 단어 In-Place 일괄 치환
  python ppt_edit.py --target active --replace-map "C:/cli_data/data/styles.json"

  # 2. 특정 단어 검색 및 제자리 치환 + 서식
  python ppt_edit.py --target active --find "진행중" --replace "완료" --color "#008800" --bold

  # 3. 특정 슬라이드만 지정 치환
  python ppt_edit.py --target active --slide 2 --find "초안" --replace "최종본"
  ```

### 4. `ppt_inspect` (프레젠테이션 종합 진단 & 열린 문서 전수 조사)
- **기능**:
  - **열린 전체 프레젠테이션 목록 (`--list-presentations` 또는 `--all`)**: 현재 실행 중인 모든 PowerPoint 창의 프레젠테이션 목록, 슬라이드 수, 저장 상태, 전체 경로를 0.01초 만에 일괄 출력합니다.
  - **프레젠테이션 상세 진단 (`--target` 지정)**: 프레젠테이션 전체 슬라이드 수, 총 글자 수, 표 개수, 각 슬라이드별 제목과 셰이프/표 개수를 상세 요약합니다. 열려 있는 프레젠테이션명을 `--target "교외체험학습_보고서_파워포인트.pptx"`처럼 직접 지정할 수 있습니다.
- **단독 실행**:
  ```bash
  # 실행 중인 모든 PowerPoint 프레젠테이션 목록 조회
  python ppt_inspect.py --list-presentations

  # 활성 PowerPoint 프레젠테이션 진단
  python ppt_inspect.py --target active

  # 실행 중인 특정 프레젠테이션 지정 진단
  python ppt_inspect.py --target "교외체험학습_보고서_파워포인트.pptx"
  ```

### 5. `ppt_export` (안전한 PDF & 복제본 PPTX 내보내기)
- **기능**:
  - 현재 활성 창을 유지하면서 PDF 또는 PPTX 복제본을 디스크에 저장
- **단독 실행**:
  ```bash
  python ppt_export.py --target active --output "presentation_out.pptx"
  ```

---

## [DOC] PDF & HWP 읽기 마이크로 블록 규격

외부 유입 문서(PDF, HWP, HWPX)를 무거운 외부 오피스 창이나 보안 팝업 없이 **0.005초 만에 순수 파이썬/C 수준에서 초고속 파싱**하고 mtime 기반 디스크 캐시를 제공합니다.

### 1. `pdf_read` (PDF 초고속 조회 & 검색)
- **특징**:
  - `pymupdf` (C기반 엔진) 탑재로 대용량 PDF도 0.01초 내외로 파싱 완료 (pypdf 자동 폴백 지원)
  - mtime 및 절대경로 기반 캐싱: 2회차 조회부터 **0.001초** 인메모리 반환 (최근 2개 캐시 자동 유지)
  - 특정 페이지 읽기 및 문서 전체 키워드 검색(전후 스니펫 반환) 지원
- **파라미터**:
  - `--target` / `--file`: PDF 파일 경로
  - `--page`: 특정 페이지 번호 (1-based)
  - `--search`: 검색할 키워드 (매칭된 페이지 번호 및 전후 문맥 스니펫 반환)
  - `--format`: `"text"` (전체 텍스트), `"pages"` (페이지별 분할 리스트), `"summary"` (페이지수, 글자수, 메타데이터 요약)
- **단독 실행**:
  ```bash
  # 문서 전체 텍스트 읽기
  python pdf_read.py --target "C:/.../report.pdf"

  # 특정 페이지(1페이지)만 읽기
  python pdf_read.py --target "C:/.../report.pdf" --page 1

  # 키워드 검색 및 스니펫 조회
  python pdf_read.py --target "C:/.../report.pdf" --search "푸꾸옥"

  # 메타데이터 및 글자 수 요약
  python pdf_read.py --target "C:/.../report.pdf" --format summary
  ```

### 2. `hwp_read` (HWP 5.0 & HWPX 초고속 파싱 & 검색)
- **특징**:
  - **Zero COM & Zero GUI**: 한글 오피스 프로그램(`HwpObject`)을 띄우지 않고, `olefile` + `zlib`로 HWP 5.0 레코드 스트림(`BodyText/Section*`)을 직접 바이너리 디코딩
  - 한컴 오피스의 지긋지긋한 **"보안 승인 / 파일 접근 허용" 모달 팝업이 100% 발생하지 않음**
  - **구형 `.hwp` (OLE) 및 신형 `.hwpx` (XML Zip) 자동 감지 및 동시 지원**
  - mtime 기반 디스크 캐싱 탑재 (0.001초 캐시 히트)
- **파라미터**:
  - `--target` / `--file`: HWP 또는 HWPX 파일 경로
  - `--search`: 검색할 키워드 (매칭된 단락 번호 및 전후 문맥 스니펫 반환)
  - `--format`: `"text"` (전체 텍스트), `"paragraphs"` (단락별 리스트), `"summary"` (포맷형식, 단락수, 글자수 요약)
- **단독 실행**:
  ```bash
  # 문서 전체 텍스트 읽기
  python hwp_read.py --target "C:/.../관용_보고서_양식.hwp"

  # 키워드 검색 및 스니펫 조회
  python hwp_read.py --target "C:/.../관용_보고서_양식.hwp" --search "결재일자"

  # 문서 요약 정보 조회
  python hwp_read.py --target "C:/.../관용_보고서_양식.hwp" --format summary
  ```

---

## [SEARCH] `search` (고성능 다중 조건 통합 색인 검색 블록)

모든 문서(PDF, HWP, Word, PPT, Excel)를 읽을 때 자동으로 생성되는 `atomic_cli/cache/*.json` 파일을 파싱하여, **오피스 COM 객체를 열지 않고 0.005초 만에 페이지 번호/슬라이드/단락 위치와 전후 문맥 스니펫을 일괄 검색**합니다.

- **주요 기능**:
  - **다중 논리 연산자 (`AND`, `OR`)**: `"A AND B"`, `"A OR B"` 다중 키워드 교집합/합집합 조건 검색 지원
  - **정규표현식 지원 (`--regex`)**: 날짜(`\d{4}-\d{2}-\d{2}`), 금액, 전화번호 등 패턴 검색
  - **스마트 하이라이팅**: 매칭된 핵심 키워드를 스니펫 본문 내에 `**키워드**` 볼드 태그로 자동 강조
  - **범위 필터링 (`--pages`, `--slides`)**: 특정 페이지 번호(예: `1-3`, `2`) 또는 슬라이드 번호만 한정 검색
  - **인간 친화적 위치 태깅 (Page & Heading 계층)**:
    - 단순 단락 번호 대신 **`Page 1 > [Heading: 2. 분기별 마일스톤]`**, **`Page 2 > [추진 배경] (Para 4)`**, **`Page 1 > [Table 1: 주요 추진 내용]`**과 같이 페이지 번호와 소제목(Heading) 및 표 컬럼명을 결합하여 사람이 문서를 보듯 직관적으로 표시
    - Word 및 HWP 문서에도 자동 조판/페이지네이션 및 목차(TOC) 인덱싱 적용
  - **특정 파일 검색 (`--target "문서명"`)**: 대상 파일의 캐시를 즉시 검색하며, 캐시가 없을 경우 해당 포맷 리더를 자동 호출하여 캐시를 사전 빌드한 후 결과를 반환
  - **전역 캐시 검색 (`--target` 생략)**: 지금까지 읽거나 점검했던 모든 문서의 캐시를 전수 스캔하여 다중 문서 통합 검색 수행
- **파라미터**:
  - `--query`, `-q`: 검색할 키워드 또는 다중 조건/정규식 (필수)
  - `--target`, `-f`: 특정 대상 파일명 또는 경로 (생략 시 전체 캐시 대상 검색)
  - `--regex`, `-r`: 정규표현식 패턴 검색 활성화
  - `--case-sensitive`, `-c`: 대소문자 정확 일치 구분
  - `--context`, `-C`: 스니펫 전후 문맥 글자 수 (기본 80자)
  - `--full-text`: 스니펫 요약 대신 매칭된 단락/슬라이드 전체 텍스트 반환
  - `--pages`, `-p`: 대상 페이지 번호 필터 (예: `"1-3"`, `"2"`)
  - `--slides`, `-s`: 대상 슬라이드 번호 필터 (예: `"1-5"`, `"2"`)
  - `--top`, `-n`: 반환할 최대 매칭 건수 (기본 10건)
  - `--to`: 검색 결과를 지정한 Office 앱 (`word`, `excel`, `ppt`)으로 즉시 서식화 전송 및 주입
  - `--dest`: 전송 대상 문서 (기본: `active`)
- **단독 실행**:
  ```bash
  # 1. 다중 AND 조건 검색
  python search.py --target "C:/.../보고서.pdf" --query "푸꾸옥 AND 케이블카"

  # 2. 다중 OR 조건 검색
  python search.py --target "C:/.../보고서.pdf" --query "케이블카 OR 사파리"

  # 3. 정규표현식(Regex) 거리 단위 검색
  python search.py --target "C:/.../보고서.pdf" --query "\d+\.\d+km" --regex

  # 4. 전체 단락 원문 반환 및 2페이지 한정 검색
  python search.py --target "C:/.../기획서.docx" --query "마일스톤" --full-text --pages 1-3

  # 5. 캐시된 모든 문서(PDF, Word, HWP 등) 전역 통합 검색
  python search.py --query "2026 OR 베트남" --top 10

  # 6. 캐시된 순수 원본 문서 목록만 빠르게 조회 (스냅샷/백업 제외)
  python search.py --list

  # 7. 원스톱 체이닝: 검색 결과를 활성 Word 창으로 구조화 마크다운 리스트 형태로 전송
  python search.py --target "C:/.../기획서.docx" --query "추진 배경" --to word
  ```

---

## [CHAIN] 원스톱 파이프라인 & 에이전트 데이터 체이닝

검색 결과나 가공된 데이터를 다른 오피스 문서로 전송할 때 별도의 수동 복사 없이 원스톱 파이프라인 및 에이전트 자동 체이닝을 제공합니다:

1. **`search.py` 원스톱 오피스 전송 (`--to word|excel|ppt`)**:
   - 검색된 문맥 스니펫과 출처 위치(`Page X > [Heading]`)를 지정한 오피스 문서로 직접 서식화하여 자동 주입합니다:
   ```bash
   # 검색 결과를 현재 열린 Word 문서 끝에 구조화 마크다운 리스트로 즉시 주입
   python search.py --target "C:/.../기획서.docx" --query "마일스톤" --to word
   ```

2. **`atomic_agent.py` 자율 인메모리 체이닝**:
   - 에이전트가 `search`로 찾은 문서 경로를 내부 컨텍스트(`AGENT_CONTEXT["last_searched_file"]`)에 기억하고, 이어서 `word_write_content` 또는 `excel_fill_table`의 인자로 자동 전달하여 다단계 작업을 무중단으로 완결합니다.

---

## [WINDOW] `office_window` (오피스 활성 창 탐색 및 포커스)

현재 사용자가 열어놓은 엑셀, 워드, 파워포인트의 모든 열린 창을 탐색하거나 특정 애플리케이션 창을 포커스(최상위 활성화)합니다:

- **주요 기능**:
  - 열린 모든 오피스 문서(`Excel`, `Word`, `PowerPoint`)의 문서명, 파일 경로, 활성 시트/슬라이드 정보 일괄 목록화
  - 백그라운드에 숨어있는 오피스 창을 화면 맨 앞으로 포커스
- **파라미터**:
  - `--list`: 열린 모든 오피스 창 목록 조회
  - `--focus`: 특정 앱 창을 화면 전면으로 활성화
  - `--to`: 대상 앱 (`excel`, `word`, `ppt`)
- **단독 실행**:
  ```bash
  # 열린 오피스 창 목록 조회
  python office_window.py --list

  # Word 창 화면 맨 앞으로 가져오기
  python office_window.py --focus --to word
  ```

---

## [CLEAN] `clean` (환경 복구, 캐시 청소 및 직전 작업 되돌리기)

좀비 프로세스 복구, 캐시 청소, 캐시 기반 자동 스냅샷 복원(Undo)을 지원합니다:

- **캐시 기반 자동 스냅샷 & 2개 유지 정책**:
  - `excel_fill`, `excel_edit`, `excel_range`, `word_write`, `word_edit`, `ppt_write`, `ppt_edit` 등 파괴적 쓰기 도구가 실행될 때, COM 화면을 방해하지 않고 **수정 직전 상태를 캐시(`atomic_cli/cache/snapshot_*`)에 0.02초 만에 자동 백업**합니다.
  - 동일 문서에 대해 쓰기가 반복되어도 **가장 최근 2개의 스냅샷 버전만 자동 유지**하고 이전 버전은 디스크에서 자동 삭제(FIFO Purge)되어 용량이 낭비되지 않습니다.
- **주요 기능**:
  - `--action undo`: 직전 작업으로 변경된 문서의 캐시 스냅샷 복원 (실수/오동작 시 즉각 롤백)
  - `--action cache`: `atomic_cli/cache/` 내의 모든 색인 캐시 JSON 및 임시 스냅샷 파일 완전 정리
  - `--action fix-env`: 사용자가 열어놓은 정상 오피스 창은 절대 건드리지 않고, 화면 없는 백그라운드 고아/좀비 오피스 프로세스(`MainWindowHandle == 0`)만 타겟팅하여 안전 종료
  - `--action all`: 캐시 정리 및 환경 복구 동시 수행
- **단독 실행**:
  ```bash
  # 직전 작업 되돌리기 (Undo)
  python clean.py --action undo

  # 캐시 및 스냅샷 전체 청소
  python clean.py --action cache

  # 백그라운드 오피스 좀비 프로세스 안전 정리
  python clean.py --action fix-env
  ```

---

## [HEAL] JIT 실시간 자가복구 시스템 (Just-In-Time Self-Healing)

오피스 자동화 및 대용량 데이터 처리 중 발생하는 예기치 못한 Windows/COM 오류에 대해 **실행 시점(Just-In-Time)에 인라인으로 감지하고 스스로 치유한 뒤 작업을 완수**하는 자가복구 아키텍처가 전 모듈에 내장되어 있습니다:

1. **COM RPC & 유령 좀비 프로세스 락 JIT 복구 (`_com_guard.py`)**:
   - `0x800706BA` (RPC 서버를 사용할 수 없음) 또는 백그라운드 프로세스 충돌 시 즉시 실패하지 않습니다.
   - 유령 오피스 프로세스(`MainWindowHandle == 0`)를 실시간 감지하여 자동 정리하고, COM 아파트먼트(`pythoncom`)를 리셋한 뒤 1회 투명 재시도를 수행합니다.
   - 사용자가 보고 있는 정상 작업 창은 절대 종료되지 않고 100% 안전하게 보호됩니다.

2. **파일 락 & 인코딩 JIT 우회 복구 (`ml_pandas.py`)**:
   - 엑셀 등 외부 프로세스가 CSV/데이터 파일을 배타적으로 점유하여 `PermissionError`가 발생할 경우, 실시간 섀도 복사본(`.jit_shadow_*`)을 생성해 즉시 읽어 들인 후 안전하게 삭제합니다.
   - 인코딩 충돌 시 `utf-8-sig` -> `cp949` -> `euc-kr` -> `latin1` 순으로 JIT 자동 Fallback을 수행합니다.

3. **원자적 스냅샷 롤백 (JIT Undo)**:
   - 다단계 작업이나 파괴적 변경 중단 시, 직전 캐시 스냅샷(`snapshot_*.xlsx/docx/pptx`)을 통해 `python clean.py --action undo` 단 1줄로 즉각 롤백할 수 있습니다.

---

## [DATA] `ml_pandas` (초고속 판다스 데이터 가공 & Joblib 직렬화 블록)

폐쇄망 환경에 최적화된 Zero-Dependency 머신러닝 데이터 파이프라인 블록으로, **실행 중인 엑셀 화면 내용과 CSV/XLSX/Joblib 데이터를 원스톱으로 흡수하여 정제, 이상치 제거, 안전 수식 계산, 통계 요약**을 수행합니다:

- **주요 기능**:
  - **시퀀스/좌표 즉석 생성 (`--from "generate:100"`, `"range:0,10,100"`)**: 외부 파일 없이도 0~1 균등 좌표, 임의 범위 수열, 정수 인덱스를 0.001초 만에 DataFrame으로 직접 생성
  - **수학/과학 안전 수식 평가 (`--eval`)**: `sin`, `cos`, `tan`, `exp`, `log`, `sqrt`, `pi`, `e` 등이 내장된 AST 샌드박스를 통해 파생 변수 및 파동/통계 수식 고속 계산
  - **활성 엑셀 실시간 흡수 (`--from active`)**: 화면에 열려 있는 엑셀 시트 데이터를 파일 저장 없이 **0.01초 만에 DataFrame으로 직접 메모리 로드**
  - **활성 엑셀 직접 주입 (`--to active`)**: 연산 결과를 엑셀 활성 시트에 SafeArray로 0.1초 만에 직접 주입
  - **에이전트 도구 등록**: `atomic_agent.py`의 `data_transform_tool`을 통해 LLM이 토큰 낭비 없이 복합 데이터/차트 소스를 1턴 만에 생성 가능
  - **다중 파일 일괄 병합 (`--from "p1.csv,p2.csv"` 또는 와일드카드)**: 여러 CSV/Joblib 파일을 한 번에 읽어 단일 DataFrame으로 고속 수직 연결(Concat)
  - **피벗 테이블 생성 (`--action pivot`)**: 다차원 행/열 인덱스 및 집계 함수를 평탄화(Flat Column)하여 표 형태로 즉시 변환
  - **그룹 집계 연산 (`--action groupby`)**: 지정한 컬럼 기준(`--by`)으로 숫자형 컬럼에 대한 일괄 집계(`sum`, `mean`, `count` 등) 수행
  - **시계열 날짜 피처 자동 추출 (`--action date-features`)**: 날짜 컬럼을 자동 감지하여 연(`_year`), 월(`_month`), 일(`_day`), 분기(`_quarter`), 요일(`_dayofweek`) 파생 변수 일괄 생성
  - **Scikit-learn 직결 압축 직렬화 (`joblib`, compress=3)**: 파이썬 내장 C-엔진을 통해 컬럼 타입과 결측치 손실 0%로 고속 입출력
  - **방탄 수식 엔진 (`--eval`)**: 
    - 한글/공백/특수문자 컬럼 자동 안전 식별자 매핑
    - 0 나누기(Division-by-Zero) 시 `inf` 자동 감지 및 `NaN` 방어
    - 필수 수학 함수(`log`, `log1p`, `sqrt`, `exp`, `abs`, `clip` 등) 바인딩
    - 세미콜론(`;`) 구분으로 복수 파생변수 동시 생성
  - **실무형 로더 옵션**: `--skiprows` (상위 결재란 스킵), `--header`, 다중 인코딩(UTF-8, CP949, EUC-KR) 자동 감지
  - **풍부한 판다스 액션**: `info`, `head`, `tail`, `describe`, `stats`, `clean` (결측치 채우기), `outlier` (IQR/Z-score), `filter`, `query`, `corr` (타겟 상관 랭킹), `value_counts`, `pivot`, `groupby`, `date-features`
  - **양방향 엑셀 주입 (`--to active`)**: 가공된 데이터를 0.05초 만에 엑셀 화면으로 실시간 주입
- **파라미터**:
  - `--from`, `-f`: 입력원 (`active`, `*.joblib`, `*.csv`, `*.xlsx`, `*.jsonl`, 쉼표 구분 다중 파일)
  - `--action`, `-a`: 수행할 액션 (`info`, `head`, `tail`, `describe`, `stats`, `clean`, `outlier`, `eval`, `filter`, `query`, `corr`, `value_counts`, `pivot`, `groupby`, `date-features`)
  - `--to`, `-t`: 출력 목적지 (`active`, `*.joblib`, `*.csv`, `*.jsonl`)
  - `--eval`: 판다스 벡터 수식 (예: `"비율 = 공정온도 / 가압압력; 로그시간 = log1p(처리시간)"`)
  - `--query`, `-q`: 행 필터링 조건식 (예: `"공정온도 > 160 and 인장강도 >= 500"`)
  - `--pivot-index`: 피벗 행 기준 컬럼
  - `--pivot-columns`: 피벗 열 컬럼
  - `--pivot-values`: 피벗 집계 대상 값 컬럼
  - `--by`: groupby 집계 기준 컬럼 (쉼표 구분)
  - `--aggfunc`: 집계 함수 (`sum`, `mean`, `count`, `min`, `max` 등, 기본: `sum`)
  - `--column`, `--date-col`: 단일 대상 컬럼 (`value_counts` 또는 날짜 피처 추출용)
  - `--skiprows`: 상위 건너뛸 행 수 (예: `3`)
  - `--impute`: 결측치 대치 방법 (`mean`, `median`, `zero`, `drop`)
  - `--method`: 이상치 제거 알고리즘 (`iqr`, `zscore`)
  - `--target-col`: 상관분석 기준 타겟 컬럼 (피처 중요도 순위 자동 정렬)
- **단독 실행**:
  ```bash
  # 1. 실행 중인 엑셀 창에서 데이터 바로 읽어 info 요약
  python ml_pandas.py --from active --action info

  # 2. 다중 CSV 파일 병합 후 날짜 피처 자동 추출
  python ml_pandas.py --from "sales_p1.csv,sales_p2.csv" --action date-features --column Date --to "sales_dated.csv"

  # 3. 피벗 테이블 생성 (지역별, 카테고리별 매출 합계)
  python ml_pandas.py --from "sales_dated.csv" --action pivot --pivot-index Region --pivot-columns Category --pivot-values Sales --to "sales_pivot.csv"

  # 4. 부서별 평균 실적 GroupBy 집계
  python ml_pandas.py --from "sales_dated.csv" --action groupby --by Region --aggfunc mean --to "sales_summary.csv"

  # 5. CSV 파일 상단 3행 스킵 후 로드 & 파생변수 2개 생성 후 joblib 압축 저장
  python ml_pandas.py --from "raw.csv" --skiprows 3 --eval "비율 = 공정온도 / 가압압력; 로그시간 = log1p(처리시간)" --to "data/step1.joblib"

  # 6. joblib 데이터에서 타겟 컬럼 상관계수 랭킹 계산
  python ml_pandas.py --from "data/step1.joblib" --action corr --target-col "인장강도"

  # 7. 조건 필터링 후 결과를 활성 엑셀 화면 A1으로 즉시 표 주입
  python ml_pandas.py --from "data/step1.joblib" --action query --query "공정온도 > 160" --to active --range "A1"
  ```

---

## [ML] 자율 진단형 머신러닝 파이프라인 (`ml_eda`, `ml_feature`, `ml_train`, `ml_report`)

> **Agent-Computer Interface (ACI) 기반 목표 지향($R^2 \ge 0.9$) 자율 수렴 머신러닝 & 경영진 보고서 자동화 엔진**  
> "단순 블랙박스 학습"의 한계를 극복하고, **현업 실전 가드레일(타겟 누수 차단, 0 나누기 방지 epsilon, Strict K-Fold Pipeline, 4중 서킷 브레이커, 타겟별 격리 장부, C-Level 보고서 자동화)**을 바탕으로 에이전트가 도메인 전문가 관점에서 가설을 세우고 최적 성능에 도달한 후 완성형 보고서까지 원클릭 작성합니다.

### 1. 핵심 아키텍처 및 현업 가드레일

1. **실시간 진행 상황(%) 스트리밍**:
   - 모든 도구는 `[ 5%] ... [100%]` 형태의 진행률 프로그레스 바를 `stderr`로 실시간 스트리밍하여 장시간 학습 시 멈춤 착시를 방지하고, `stdout`에는 단 1줄의 정형 JSON만 출력합니다.
2. **타겟 누수(Target Leakage) 및 순환참조 원천 차단**:
   - `ml_eda.py`가 타겟과의 상관계수 $|r| \ge 0.95$인 사후 결과/ID 변수를 자동 탐지하여 `CRITICAL_LEAKAGE_RISK` 경고 및 배제 지침을 하달합니다.
3. **다중 타겟(Multiple Targets) 격리 및 독립 모델링**:
   - `--targets "y1,y2"` 지정 시, $y_1$ 모델을 학습할 때는 $y_2$를 포함한 모든 타겟 컬럼이 $X$ 특성 풀에서 100% 원천 배제됩니다. 각 타겟마다 독립 파이프라인 모델이 구축됩니다.
4. **타겟별 세션 장부 고립 (Target-Isolated Lineage Ledger)**:
   - 실험 이력 장부와 모델 아티팩트는 타겟별로 고립된 디렉터리(`atomic_cli/data/ml_sessions/{target}/`)에 저장됩니다:
     - `history.jsonl`: 회차별 Val $R^2$, $\Delta R^2$, MAE, 과적합 갭, 챔피언 여부(`[* BEST]`)
     - `eda_correlation.json`: 피어슨 상관계수 행렬 및 상호정보량(MI) 점수
     - `champion_model.joblib`: 교차검증 최고 성능 챔피언 모델 파이프라인
     - `session_meta.json`: 세션 메타데이터
5. **도메인 전문가 수식 엔진 (`ml_feature.py`)**:
   - 물리, 화학, 금융 등 임의의 도메인 방정식(아레니우스 식, 종횡비, 비율 등)을 `--expr` 및 `--recipe-file`로 안전하게 합성합니다.
   - 모든 나눗셈 연산에 자동 $\epsilon(+10^{-7})$ 클리핑 및 `nan/inf` 자동 보간을 적용하여 Zero-Crash를 보장합니다.
6. **무한루프 방지 4중 서킷 브레이커 (Loop Circuit Breaker)**:
   - 최대 반복수 상한(`--max-iter 10`).
   - 3회 연속 $R^2$ 개선폭 $< 0.005$ 시 데이터 내재 노이즈 한계 도달로 판정하고 즉시 정지 (`STOP_RETRY`).
   - Train-Val 과적합 갭 $> 0.20$ 시 수식 단순화 지침 하달.

---

### 2. 도구별 CLI 명령어 가이드

#### ① `ml_eda.py` (심층 EDA 및 누수 감사)
```bash
# 기본 사용: 타겟 y 지정, X는 자동 풀 인식, 불필요한 메타 컬럼 제외
python ml_eda.py --file "C:/cli_data/data/chemical_process.csv" --targets "reaction_yield" --exclude "batch_id"

# 다중 타겟 감사 및 상호정보량(MI) 기반 수식 힌트 추출
python ml_eda.py --file "data.csv" --targets "yield,purity" --out-report "C:/cli_data/data/eda_report.json"
```

#### ② `ml_feature.py` (도메인 전문가 수식 주입)
```bash
# 단일/복수 인라인 수식 생성 (타겟 자동 격리, 0나누기 안전망)
python ml_feature.py --file "C:/cli_data/data/chemical_process.csv" --targets "reaction_yield" \
  --expr "arrhenius = exp(-2500 / (temp + 273.15))" \
  --expr "residence_time = 30.0 / flow_rate" \
  --expr "domain_kinetics = arrhenius * residence_time * (conc_A ** 1.5) * sqrt(catalyst)" \
  --out "C:/cli_data/data/chemical_features_v1.csv"

# JSON 레시피 배치 파일 적용
python ml_feature.py --file "data.csv" --targets "target_y" \
  --recipe-file "C:/cli_data/data/domain_recipes.json" --out "engineered.csv"
```

#### ③ `ml_train.py` (목표 수렴 학습 & 실험 이력 관리)
```bash
# 1. 목표 지향 ACI 학습 (R2 >= 0.90 수렴 목표, 실시간 % 진행률 출력)
python ml_train.py --file "C:/cli_data/data/chemical_features_v1.csv" --targets "reaction_yield" \
  --exclude "batch_id,byproduct_yield" --session "chemical_linear" --model-type ridge --target-metric "r2>=0.9"

# 2. 지금까지의 실험 이력 장부(Ledger) 터미널 표 조회
python ml_train.py --history --session "chemical_linear"

# 3. 최고 성능 챔피언 체크포인트 정보 조회
python ml_train.py --get-best --session "chemical_linear"
```

#### ④ `ml_report.py` (C-Level 경영진 6단락 의사결정 보고서 자동 생성)
- **듀얼 모드**: Word 활성 창 실시간 주입(`--target active`) 또는 독립 DOCX/PPTX 파일 생성(`--target report.docx`).
- **보고서 6대 구성**:
  1. 제목 & 문서 메타데이터 (타겟명, 데이터셋, 일시, 검증관)
  2. Executive Summary 강조 콜아웃 박스 (결론 우선 제시, 핵심 지표 하이라이트, 배포 권고)
  3. SLA 품질 검증 감사 매트릭스 표 (Val R2, Baseline R2, Target Gap, Overfit Gap, Best Fold R2, Iterations)
  4. 순열 특성 중요도(Permutation Feature Importance) 계층 표
  5. 상관계수 매트릭스 히트맵 표 (임계치별 셀 색상 음영, 다중공선성 위험 특성 자동 식별)
  6. 실험 이력 장부 및 단계별 엔지니어링 감사 일지 (전체 회차 이력, 도메인 수식 설계 사유, 배포 지침)
```bash
# 1. 열려 있는 Word 활성 문서에 보고서 실시간 주입
python ml_report.py --session "인장강도" --target "active"

# 2. 파일로 직접 완제품 DOCX 보고서 생성
python ml_report.py --session "인장강도" --target "solar_heat_treatment_report.docx"

# 3. PowerPoint 슬라이드 형태로 보고서 내보내기
python ml_report.py --session "인장강도" --target "active" --format pptx
```

---

## [THEME] `office_theme` (스타일 역공학 추출 & 기업용 테마 엔진)

기존 회사 표준 문서(Excel, Word, PowerPoint)에서 **스타일 DNA(헤더 배경색, 폰트 패밀리, 행 높이, 숫자 서식, 테두리, 주요 컬러 팔레트)**를 정밀 추출하여 재사용 가능한 테마 프로필(`*.json`)로 내보내거나, 내장된 비즈니스 테마 프리셋을 제공합니다:

- **주요 기능**:
  - **스타일 DNA 역공학 추출 (`--action extract`)**:
    - **Excel**: 헤더 행 배경/글자색/볼드/정렬, 교차 행(Zebra) 패턴, 숫자 열 표시 형식(`#,##0` 등), 요약/합계 행 감지(이중선/배경).
    - **PowerPoint**: 슬라이드/도형 채우기 및 텍스트 폰트 색상 히스토그램을 분석하여 지배적 컬러 팔레트 Top 5, 제목/본문 타이포그래피 추출.
    - **Word**: 본문/제목 글꼴 및 크기, 표 헤더 음영 색상 추출.
  - **내장 비즈니스 테마 프리셋 (`--action list-presets`)**:
    - `navy`: 신뢰감 있는 클래식 비즈니스 네이비 테마 (`#1B365D`)
    - `slate`: 미니멀하고 세련된 차콜/슬레이트 테마 (`#2B2D42`)
    - `teal`: 전략/재무 보고서에 최적화된 다크 틸 & 민트 테마 (`#004D40`)
    - `emerald`: 안정적이고 차분한 에메랄드 그린 테마 (`#1E4620`)
  - **`excel_edit.py` 원클릭 연동**:
    - 추출된 테마 파일 또는 프리셋 이름을 `excel_edit.py --theme <name_or_file>`로 지정하면 **표 헤더 + 줄무늬 행 + 숫자 콤마 + 합계 이중선**이 단 1초 만에 일괄 완성됩니다.
- **단독 실행**:
  ```bash
  # 1. 내장 테마 프리셋 목록 조회
  python office_theme.py --action list-presets

  # 2. 열려 있는 엑셀 양식에서 스타일 DNA 추출 및 JSON 저장
  python office_theme.py --target active --export-theme "company_theme.json"

  # 3. 추출한 회사 테마를 새로운 시트에 그대로 적용 (스포이트 & 도장)
  python excel_edit.py --target active --range "A1:G15" --theme "company_theme.json"

  # 4. 내장 비즈니스 네이비 테마 + Zebra 줄무늬 + 천단위 콤마 일괄 적용
  python excel_edit.py --target active --theme navy --zebra --format-num "#,##0"
  ```

---

## [BRIDGE] `office_bridge` (Cross-Office 콘텐츠 복사 & 전송 브릿지 블록)

Excel에서 집계한 표나 생성한 비즈니스 차트를 **Word 보고서 문서나 PowerPoint 발표 슬라이드로 서식 손실 없이 원클릭 복사/배치**합니다:

- **주요 기능**:
  - **Excel 표 -> Word 문서 복사 (`--from-app excel --to-app word`)**:
    - Excel 원본 서식과 표 구조를 100% 보존한 네이티브 Word Table로 문서 맨 끝 또는 특정 북마크(`--bookmark`) 위치에 자동 삽입
    - 그림 형태(`--copy-as picture`) 복사 옵션도 동시 지원
  - **Excel 표/차트 -> PowerPoint 슬라이드 배치 (`--from-app excel --to-app ppt`)**:
    - Excel의 차트 오브젝트(`--chart 1`) 또는 표 영역(`--range A1:E10`)을 지정한 PPT 슬라이드(`--slide 2`)의 원하는 좌표/크기로 정밀 배치
    - 위치 미지정 시 슬라이드 중앙(`Center`) 자동 정렬
  - **클립보드 마칭 앤츠(Marching Ants) 자동 해제**:
    - 복사 완료 후 Excel의 `CutCopyMode = False`를 자동 실행하여 깔끔한 화면 상태 유지
  - **`atomic_agent` 크로스 오피스 파이프라인 완벽 결합**:
    - `ml_pandas` 데이터 분석 -> `excel_fill` 데이터 주입 -> `excel_chart` 차트 생성 -> `office_bridge` Word/PPT 보고서 삽입까지 단일 자연어 명령으로 원스톱 자동 조율
- **파라미터**:
  - `--from-app`: 원본 Office 앱 (기본: `excel`)
  - `--from`, `--from-target`: 원본 파일 경로 또는 `active`
  - `--sheet`: 엑셀 시트명
  - `--range`: 엑셀 복사 대상 범위 (예: `"A1:E10"`)
  - `--chart`: 복사할 엑셀 차트 번호 (1부터 시작)
  - `--copy-as`: 복사 형식 (`table` 또는 `picture`)
  - `--to-app`: 대상 Office 앱 (`word` 또는 `ppt`)
  - `--to`, `--to-target`: 대상 파일 경로 또는 `active`
  - `--slide`: PPT 대상 슬라이드 번호 (기본: `1`)
  - `--bookmark`: Word 대상 북마크명
  - `--left`, `--top`, `--width`, `--height`: PPT 내 배치 좌표 및 크기 (pt)
- **단독 실행**:
  ```bash
  # 1. Excel A1:E10 표를 열려 있는 Word 문서 끝으로 복사 (서식 유지)
  python office_bridge.py --from active --range "A1:E10" --to-app word --to active

  # 2. Excel 1번 차트를 열려 있는 PowerPoint 2번 슬라이드 중앙에 자동 배치
  python office_bridge.py --from active --chart 1 --to-app ppt --to active --slide 2

  # 3. Excel 범위를 이미지로 캡처하여 PPT 1번 슬라이드 지정 위치에 삽입
  python office_bridge.py --from active --range "A1:F8" --copy-as picture --to-app ppt --to active --slide 1 --top 120 --left 80
  ```

---

## [MAIL] `outlook_read` & `outlook_write` (MS Outlook 메일 자동화 파이프라인)

> **순수 네이티브 Windows COM 직결 + 실무 안전 발송 가드레일 탑재**  
> 모놀리식 코드의 복잡성을 배제하고, **화면 간섭 없는 무중단 백그라운드 읽기**, **아웃룩 자체 초고속 검색 엔진 직결**, **현재 활성 메일 실시간 캡처**, **원본 대화 이력 100% 보존 네이티브 답장**, **화면 팝업 기본(직접 발송 확인)**을 보장합니다.

### 1. 주요 특징 및 실무 원칙

1. **가상 Mock 배제 및 100% 네이티브 COM 직결**:
   - 가짜 인터페이스로 인한 실무 오작동을 원천 차단하고, 실제 PC의 `Outlook.Application` MAPI 네임스페이스와 1:1 직결.
2. **무중단 백그라운드 읽기 (Zero Screen Interference)**:
   - 아웃룩 창이 켜져 있든 꺼져 있든 화면에 창을 띄우지 않고 백그라운드에서 메일 검색, 본문 읽기, 첨부 저장을 조용히 완료.
3. **아웃룩 자체 DASL 고속 검색 엔진 직결**:
   - 외부 캐시 파일 동기화 없이, 아웃룩의 윈도우 인덱서 및 DASL 쿼리를 직접 호출하여 수만 통의 사서함에서 0.1초 만에 실시간 검색.
4. **현재 보고 있는 메일 실시간 캡처 (`--action current`)**:
   - 사용자가 아웃룩 화면에서 마우스로 클릭해 둔 메일(`ActiveExplorer.Selection`)이나 독립 창으로 열어둔 메일(`ActiveInspector.CurrentItem`)을 1초 만에 자동 인식.
5. **네이티브 답장 이력 100% 보존 (`--action reply / forward`)**:
   - 텍스트를 손으로 덧붙이지 않고 아웃룩 자체의 `Reply()` / `Forward()` 메서드를 직접 호출하여, **제목 `RE:`, 수신자, 원본 헤더 및 기존 HTML 대화 이력을 완전히 보존**.
6. **휴먼-인-더-루프(Human-in-the-Loop) 안전 발송**:
   - 메일 작성/답장 시 기본 동작은 **화면에 아웃룩 창(`Display()`)만 띄워두고 멈추는 것**입니다. 사용자가 최종 확인 후 직접 [보내기]를 누르며, 오직 `--send` 플래그 명시 시에만 자동 발송됩니다.

---

### 2. 단독 CLI 실행 가이드

#### ① `outlook_read.py` (메일 수신 및 조회)
```bash
# 1. 현재 화면에서 내가 보고 있거나 선택한 메일 캡처
python outlook_read.py --action current

# 2. 받은편지함 최신 메일 목록 (안 읽은 메일만 5통)
python outlook_read.py --action list --unread --limit 5

# 3. 아웃룩 자체 검색 엔진으로 키워드 검색
python outlook_read.py --action search --query "공정분석" --limit 5

# 4. 특정 보낸사람 메일 검색
python outlook_read.py --action search --from "김팀장" --limit 3

# 5. 특정 메일 본문 읽기 및 첨부파일 자동 다운로드 (atomic_cli/data/ 에 저장)
python outlook_read.py --action read --id "<entry_id>" --save-attach

# 6. 편지함 전체 폴더 트리 및 안읽은 메일 수 확인
python outlook_read.py --action folders
```

#### ② `outlook_write.py` (메일 작성 및 답장)
```bash
# 1. 새 메일 작성 후 화면 팝업 (사용자가 직접 보내기 클릭, 첨부파일 data_dir 자동 연동)
python outlook_write.py --action new --to "lead@company.com" \
  --subject "10월 공정 분석 결과 보고" --body "요청하신 분석 보고서 첨부합니다." --attach "chemical_process.csv"

# 2. 현재 내가 보고 있는 메일에 원본 대화 이력 유지하며 답장 창 화면 팝업
python outlook_write.py --action reply --body "요청하신 데이터 보완하여 회신드립니다."

# 3. 현재 메일을 원본 유지하며 다른 수신자에게 전달 창 화면 팝업
python outlook_write.py --action forward --to "qa@company.com" --body "참고 바랍니다."

# 4. 자동 즉시 발송 (명시적 요청 시에만 백그라운드 발송)
python outlook_write.py --action new --to "lead@company.com" --subject "자동 알림" --body "완료되었습니다." --send
```

---

## [SPEC] 에이전트 표준 응답 규격 & 대용량 전송 최적화

모든 마이크로 도구의 최종 출력은 Gemma 4 26B 및 Solar Mini/Pro의 파싱 안정성과 재시도 폭주 방지를 위해 **오직 단 1줄의 정형화된 JSON**만 출력합니다:

```json
{"status": "ok", "module": "excel_fill", "action": "csv_fill", "preview": "Successfully filled 101 rows into 'Sheet1!A1:D101'", "agent_directive": "VERIFIED: Table data injected. Do not re-verify.", "rows": 101}
```

- `"status": "ok"` 및 `"VERIFIED"`: 작업이 화면에 100% 반영 완료되었음을 보증. 추가 재검증(다시 읽기) 금지.
- `"status": "no_match"` 및 `"STOP_RETRY"`: 매칭 대상 없음. 인자를 바꿔 재시도하지 말고 즉시 사용자에게 보고.
- **대용량 데이터 전송 압축 (`clamp_tool_result`)**:
  - `excel_read`, `search` 등에서 100행 이상의 대용량 표/데이터를 조회할 경우, 상위 표본 및 통계 요약으로 **약 4KB 크기로 압축 전달**합니다.
  - LLM이 수천 줄의 데이터를 한꺼번에 읽으려다 범위를 잘게 쪼개어 무한 페이징 루프를 도는 현상을 원천 방지합니다.

---

## [AGENT] 2대 에이전트 아키텍처 (`atomic_agent.py` & `atomic_agent_tui.py`)

기존에 분산되어 있던 에이전트 및 레시피 파일들을 오직 **`atomic_agent.py` (메인 엔진 및 원샷 실행기)**와 **`atomic_agent_tui.py` (대화형 인터랙티브 세션)**의 2개 파일로 단순화·통합하였습니다:

```text
[User / Terminal / GUI]
         │
         ├── python atomic_agent.py "명령" ──> [atomic_agent.py] (메인 엔진 원샷 완결)
         │
         ▼ (대화형 세션 실행)
[atomic_agent_tui.py] (대화형 콘솔 & 세션 대화 기억)
  ├── prompt_toolkit: Bracketed Paste 모드 (대용량 복사-붙여넣기 꼬임 방지)
  ├── conversation_history: 세션 멀티턴 대화 자동 기억 (/history, /clear)
  ├── prompt_history.txt: 영구 검색 가능한 입력 이력 장부
  ├── rich Console: 클린 터미널 (이모지 0%, 글자 폭 깨짐 방어)
  └── disable_quick_edit_mode(): Windows 터미널 마우스 클릭 프리징 원천 방어
         │
         ▼  (AgentEngine Generator Streaming)
[atomic_agent.py] (Main Core Engine)
  ├── AgentEngine: LLM 클라이언트 (Gemma 4 26B 타겟 최적화 & Solar Mini/Pro 완벽 지원)
  ├── 30종 마이크로 도구 디스패처: search, office, ml_analysis, ml_train, ml_report 등
  └── AgentEvent: PROMPT, THOUGHT, TOOL_CALL, TOOL_RESULT, MESSAGE, ERROR
```

### 1. 설계 이점 및 실무 효과
1. **단순화된 2대 파일 구조**:
   - `atomic_agent.py`: 솔라 및 Gemma AI 에이전트의 모든 기능(코어 엔진, 30개 도구 조율, 시스템 프롬프트 19종 가드레일)을 내장하여 단발성 일회성 명령을 즉시 완결합니다.
   - `atomic_agent_tui.py`: `atomic_agent.py`를 호출하여 멀티턴 대화 세션을 유지하며, 이전 턴의 작업 결과와 지시를 온전히 기억합니다.
2. **세션 대화 기억 (Conversation History)**:
   - 사용자와 주고받은 질의와 답변을 세션 동안 자동 누적하여 "아까 작성한 표에 컬럼 추가해줘", "위 파일에서 수율 이상치만 다시 확인해줘"와 같은 연속 지시를 완벽히 수행합니다.
   - `/history`로 현재 기억 중인 대화 내역을 조회하고, `/clear`로 언제든 새로운 세션으로 초기화할 수 있습니다.
3. **윈도우 콘솔 프리징 완벽 방어 (`disable_quick_edit_mode`)**:
   - Windows 터미널(PowerShell/CMD) 환경에서 사용자가 실수로 화면을 클릭하면 `QuickEdit Mode`가 발동하여 프로세스 stdout 출력이 영구 정지(Freeze)되는 치명적 문제를 실행 시점에 `kernel32.SetConsoleMode`로 비활성화하여 원천 차단했습니다.
4. **클립보드 멀티라인 붙여넣기 무결성 (Bracketed Paste)**:
   - 복잡한 데이터 분석 프롬프트, 도메인 수식, 수십 줄의 텍스트를 복사하여 터미널에 붙여넣더라도 엔터가 중간에 트리거되지 않고 완벽한 단일 블록으로 입력됩니다.
5. **클린 터미널 원칙 준수 (Zero Emoji Guardrail)**:
   - 터미널 폰트 호환성과 CP949/UTF-8 인코딩 충돌을 방지하기 위해 이모지를 일체 배제하고 `[INFO]`, `[TOOL]`, `[THOUGHT]`, `[STATUS]` 표준 텍스트 태그로 렌더링합니다.

### 2. 실행 명령어

```bash
# 1. 원샷 일회성 명령 실행 (단발성 완결)
python atomic_agent.py "파일 'data/sample_production.xlsx' 검사해줘"
python -u atomic_agent.py "열려 있는 오피스 창 상태 확인해줘"
python -u atomic_agent.py "heat_treatment.csv의 인장강도 타겟으로 R2 0.9 이상 모델을 학습하고 워드 보고서까지 써줘"

# 2. 대화형 인터랙티브 세션 시작 (멀티턴 대화 기억 모드)
python atomic_agent_tui.py
```
