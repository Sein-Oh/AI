# OfficeCLI 완전 정복 매뉴얼 및 단독 레퍼런스 (GUIDE.md)

> **이 문서는 소스 코드를 단 한 줄도 열어보지 않고도 OfficeCLI의 모든 기능, 파라미터 조합, 데이터 형식, 예외 대처법을 100% 숙지하고 즉시 활용할 수 있도록 작성된 완전 자립형(Self-Contained) 가이드북입니다.**

---

## ⚡ 빠른 판단 가이드: 할 수 있는 것 (CAN DO) vs 할 수 없는 것 (CANNOT DO)

> **작업 시작 전 1초 확인!**  
> AI 에이전트와 사용자는 아래의 기능 경계를 확인하여 잘못된 명령 호출을 사전에 방지하세요.

| 대상 포맷 / 앱 | 🟢 할 수 있는 것 (CAN DO) | 🔴 할 수 없는 것 (CANNOT DO) | 비고 |
| :--- | :--- | :--- | :--- |
| **한글 (HWP / HWPX)** | • **로컬 파일 초고속 읽기 (`read --file <경로.hwp>`)**<br>• 하이브리드 검색 (`run --search ...`)<br>• 본문 문단 및 표 데이터 추출<br>• **Hwp.exe 실행 0%, 화면 간섭 0% 순수 파이썬 파싱** | ❌ **화면 활성 창 읽기 (`--active`) 불가**<br>❌ **한글 문서 쓰기/수정 (`write --to hwp`) 불가**<br>❌ 한글 창 초기화 (`--clear`) 불가<br>❌ 한글에 이미지 삽입 불가 | **PDF와 동일한 [읽기 전용]**<br>(화면 팝업 및 포커스 뺏김 원천 방지) |
| **PDF** | • **로컬 파일 고속 읽기 (`read --file <경로.pdf>`)**<br>• 하이브리드 검색 및 목차 요약 (`info`)<br>• 도면/이미지 분리 추출 (`--extract-images`) | ❌ **PDF 파일 쓰기/수정 불가**<br>❌ 활성 창 제어 불가 | **읽기/검색 전용** |
| **Microsoft Word** | • 로컬 파일 읽기/검색 (`.docx`, `.doc`)<br>• **실시간 활성 창 읽기/쓰기 (`--active`)**<br>• 키워드 앵커 위치 삽입 (`--anchor --pos`)<br>• 네이티브 표 자동 생성 & 본문 초기화 (`--clear`)<br>• 인라인 이미지 삽입 (`--image`)<br>• **작업 전 자동 백업 & 1초 롤백 (`restore`)** | ❌ 암호로 잠긴(비밀번호 보호) 문서 강제 해제 | **읽기 + 쓰기 + 활성 창 전면 지원** |
| **Microsoft Excel** | • 로컬 파일 읽기/검색 (`.xlsx`, `.xls`, `.csv`)<br>• **실시간 활성 시트 읽기/쓰기 (`--active`)**<br>• 2D 정규화 및 병합 셀 Forward-Fill 복원<br>• `=` 수식(`Formula`) 자동 인식 주입<br>• 윗행 서식 자동 상속 (`xlPasteFormats`)<br>• 이미지 삽입 (`--image`) & 시트 초기화 (`--clear`)<br>• **작업 전 자동 백업 & 1초 롤백 (`restore`)** | ❌ 매크로(VBA) 코드 직접 수정 | **읽기 + 쓰기 + 활성 창 전면 지원** |
| **PowerPoint** | • 로컬 파일 읽기/검색 (`.pptx`, `.ppt`)<br>• **실시간 활성 슬라이드 읽기/쓰기 (`--active`)**<br>• 중첩 그룹 도형 언패킹 & 시각적 순서 추출<br>• **지능형 동적 페이지네이션** (높이 초과 시 새 슬라이드 자동 생성 및 표 분할)<br>• 이미지 삽입 (`--image`) & 슬라이드 초기화 (`--clear`)<br>• **작업 전 자동 백업 & 1초 롤백 (`restore`)** | ❌ 복잡한 애니메이션/전환 효과 추가 | **읽기 + 쓰기 + 활성 창 전면 지원** |
| **Markdown / Text** | • 로컬 파일 읽기 및 쓰기 (`.md`, `.txt`)<br>• 하이브리드 검색 및 표 생성 | ❌ GUI 활성 창 개념 없음 | **로컬 파일 전용** |

---

## 📑 목차 (Table of Contents)
1. [빠른 판단 가이드: 할 수 있는 것 vs 할 수 없는 것](#-빠른-판단-가이드-할-수-있는-것-can-do-vs-할-수-없는-것-cannot-do)
2. [핵심 개념 및 아키텍처 (Concepts & Architecture)](#1-핵심-개념-및-아키텍처)
3. [표준 입출력 데이터 규격 (Data Schema)](#2-표준-입출력-데이터-규격)
4. [전체 CLI 명령어 및 옵션 완전 분석 (CLI Reference)](#3-전체-cli-명령어-및-옵션-완전-분석)
   - [4.1 run (올인원 실행: 읽기 ➔ 검색 ➔ 쓰기/출력)](#31-run-올인원-실행)
   - [4.2 read (범위/활성창 정밀 추출)](#32-read-정밀-추출)
   - [4.3 write (독립 쓰기 / 이미지 / 초기화 / 파이프)](#33-write-독립-쓰기)
   - [4.4 info (0.1초 고속 메타데이터 요약)](#34-info-고속-메타데이터-요약)
   - [4.5 restore (작업 전 1초 롤백 복원)](#35-restore-작업-전-1초-롤백-복원)
   - [4.6 backup (백업 스냅샷 이력 조회)](#36-backup-백업-스냅샷-이력-조회)
5. [오피스 프로그램별 지원 범위 및 특성](#4-오피스-프로그램별-지원-범위-및-특성)
6. [실무 상황별 명령어 치트시트 (Cookbook & Cheatsheet)](#5-실무-상황별-명령어-치트시트)
7. [자주 묻는 질문 및 트러블슈팅 (FAQ & Troubleshooting)](#6-자주-묻는-질문-및-트러블슈팅)

---

## 1. 핵심 개념 및 아키텍처

OfficeCLI는 Windows 11 폐쇄망 및 WinPython 환경에서 AI 에이전트가 로컬 오피스 문서를 탐색하고, 화면에 열려 있는 활성 창을 실시간으로 제어하기 위해 제작된 단일 스크립트 도구입니다.

### 🌟 7대 핵심 원칙
1. **완전 무간섭 백그라운드 읽기 (`DispatchEx`)**:
   - 오프라인 파일 경로(`--file "보고서.docx"`, `"기안서.hwp"`, `"매뉴얼.pdf"`)로 명령을 실행하면 사용자가 화면에서 오피스 프로그램을 열고 작업 중이더라도 **0% 간섭하는 독립 백그라운드 프로세스**로 파일을 읽고 깔끔하게 종료합니다.
2. **3대 오피스 활성 창 안전 제어 (`--active`)**:
   - 화면에 열려 있는 저장 전 상태의 문서(Word, Excel, PowerPoint)를 읽거나 수정할 때는 `--active` 플래그를 붙이며, 사전에 열려 있는 창 핸들(`HWND`)을 안전하게 가져와 조작합니다.
3. **한글(HWP) 및 PDF: 무간섭 읽기 전용(Read-Only)**:
   - 한컴오피스 한글(HWP)과 PDF는 사용자의 화면 간섭, 보안 팝업, 키보드 포커스 충돌을 원천 방지하기 위해 **100% 무간섭 백그라운드 읽기/검색 전용**으로 안전하게 동작합니다. (쓰기는 Word, Excel, PPT, Markdown 대상)
4. **윈도우 오프스크린 자동 복원 (`ensure_window_visible`)**:
   - 다중 모니터 분리, 가상 데스크톱 전환, 최소화 상태 등으로 활성 창이 화면 밖(음수 좌표)에 숨겨져 있으면, 자동으로 **주 모니터 안전 영역(`x=100, y=100`, `1100×750`)으로 창을 이동하고 포커스를 복원**합니다.
5. **안전 제일! 작업 전 자동 스냅샷 & 원터치 롤백 (`BackupManager` & `restore`)**:
   - 에이전트가 문서를 수정(`write`)하거나 비우는(`--clear`) 모든 작업 직전, 원본 파일 및 활성 창 본문 전체를 `.officecli_backup/` 폴더에 타임스탬프와 함께 자동 보관합니다. 실수 시 `restore` 단 한 줄로 1초 만에 작업 전 상태로 되돌립니다.
6. **초고속 캐싱 엔진 (`.officecli_cache/`)**:
   - 파일의 절대 경로와 수정 시각(`mtime`) 해시를 기반으로 1회 파싱 결과를 JSONL 캐시로 저장합니다. 수백 쪽짜리 대용량 문서도 2회차 조회부터는 0.01초 내에 즉각 응답합니다.
7. **지능형 하이브리드 검색 & PPT 동적 페이지네이션**:
   - 정규식(Regex) + 희소 단어 BM25/IDF + 목차 가중치를 결합하여 외부 무거운 벡터 모델 없이도 관련도 높은 상위 N개 문단을 초고속 랭킹하며, PPT 삽입 시 슬라이드 높이 초과 시 새 슬라이드를 자동 생성합니다.

---

## 2. 표준 입출력 데이터 규격

OfficeCLI의 모든 읽기/검색 결과는 표준 **JSONL (JSON Lines)** 형식으로 출력되며, 각 줄은 독립된 단일 레코드입니다.

### 2.1 JSONL 레코드 스키마
```json
{
  "id": 14,
  "src": "2026_사업계획서.docx",
  "ext": "docx",
  "page": 3,
  "section": "2. 소요 예산 계획",
  "coord": "Tbl:2/Row:1",
  "type": "table_row",
  "data": ["연구개발비", "150,000,000", "정부지원금 매칭"],
  "score": 18.5
}
```

### 2.2 필드 정의서
| 필드명 | 타입 | 설명 |
| :--- | :--- | :--- |
| `id` | `int` | 문서 전체 내 고유 등장 순번 (0부터 1씩 증가, 문서 앞뒤 문맥 보존용) |
| `src` | `str` | 소스 파일명(예: `report.pdf`, `sample.hwp`) 또는 활성 창 제목(예: `문서1 - Microsoft Word`) |
| `ext` | `str` | 확장자: `pdf`, `docx`, `xlsx`, `pptx`, `hwp`, `hwpx`, `md`, `txt` |
| `page` | `int` | 실제 인쇄 쪽 번호, PPT 슬라이드 번호, Excel 시트 순번 (1부터 시작) |
| `section` | `str` | 직전 상위 목차(Heading), 엑셀 시트명, PPT 슬라이드 제목 |
| `coord` | `str` | 정밀 좌표: `Para:14`(14번째 문단), `Row:12`(12번째 행), `Tbl:2/Row:1`(2번째 표의 1행), `Shape:3`(3번째 도형) |
| `type` | `str` | `text`(일반 문단), `table_row`(표의 한 행), `heading`(제목/목차) |
| `data` | `str` \| `list` | 실제 내용: 일반 문단은 `str`, 표의 행은 셀 값 목록 `list[str]` |
| `score` | `float` | (`--search` 시에만 출력) 검색어 연관도 점수 (높을수록 일치율 높음) |

---

## 3. 전체 CLI 명령어 및 옵션 완전 분석

```
python officecli.py <COMMAND> [OPTIONS...]
```

OfficeCLI는 목적에 따라 6개의 서브 명령어를 제공합니다:
1. `run`: 읽기, 검색, 쓰기를 한 번에 수행하는 메인 명령어.
2. `read`: 문서나 활성 창의 내용을 JSONL로 스트리밍 추출.
3. `write`: 텍스트, 이미지 삽입, 문서 초기화, 파이프 입력 기록.
4. `info`: 파일이나 활성 창의 쪽수, 목차, 크기 메타데이터 요약.
5. `restore`: 작업 전 백업 스냅샷으로 1초 만에 롤백 복원.
6. `backup`: 백업 스냅샷 이력 확인.

---

### 3.1 `run` (올인원 실행)
가장 핵심이 되는 명령어로, 원본 문서를 읽어 검색한 뒤 화면에 출력하거나 대상 문서에 즉시 주입합니다.

```bash
python officecli.py run --file <경로|앱별칭> [옵션...]
```

#### 옵션 상세 테이블
| 옵션 | 단축 | 타입 | 기본값 | 설명 및 유효값 |
| :--- | :--- | :--- | :--- | :--- |
| `--file` | - | `str` | **(필수)** | 원본 파일 경로 (`.pdf`, `.docx`, `.xlsx`, `.pptx`, `.hwp`, `.md`, `.txt`) 또는 활성 앱 별칭 (`word`, `excel`, `ppt`) |
| `--active` | - | 플래그 | `False` | 활성 창 제어 여부. `--file`이 앱 별칭일 때 활성 창에서 읽고, `--to`가 지정되면 쓰기 대상 창에 적용 |
| `--search` | - | `str` | `None` | 검색할 키워드 또는 정규식. 공백으로 여러 단어 입력 시 BM25 희소 단어 랭킹 적용 |
| `--top` | - | `int` | `0` (전체) | 상위 N개 레코드만 제한하여 추출/쓰기 |
| `--pages` | - | `str` | `None` | 추출/기록할 페이지 또는 슬라이드 범위 (예: `1`, `1-3`, `1,3,5-7`) |
| `--to` | - | `str` | `None` | 검색 결과를 기록할 대상 파일 경로 또는 활성 앱 별칭 (`word`, `excel`, `ppt`). 생략 시 stdout 출력 |
| `--anchor` | - | `str` | `None` | 대상 문서에서 삽입 위치를 찾을 기준 텍스트 키워드 |
| `--pos` | - | `str` | `after` | 앵커 기준 상대 위치: `after`(뒤), `before`(앞), `replace`(해당 문단/행 교체) |
| `--prefix` | - | `str` | `None` | 기록할 각 문단/표 첫 셀 앞단에 붙일 접두사 (예: `"[출처: 기안서]"`)|
| `--clear` | - | 플래그 | `False` | 기록 전 대상 시트나 문서 본문 전체를 삭제 (자동 백업 동시 수행) |
| `--extract-images`| - | 플래그 | `False` | PDF 파싱 시 `{파일명}_images/` 폴더를 생성하여 포함된 이미지 파일들을 저장 |

---

### 3.2 `read` (정밀 추출)
특정 문서나 활성 창의 전체 내용 또는 특정 페이지를 순수 JSONL 규격으로 추출할 때 사용합니다.

```bash
python officecli.py read --file <경로|앱별칭> [옵션...]
```

#### 옵션 상세 테이블
| 옵션 | 타입 | 기본값 | 설명 |
| :--- | :--- | :--- | :--- |
| `--file` | `str` | **(필수)** | 파일 경로 또는 활성 앱 별칭 (`word`, `excel`, `ppt`) |
| `--active` | 플래그 | `False` | 활성 창에서 직접 읽기 수행 (Word, Excel, PPT) |
| `--pages` | `str` | `None` | 특정 페이지/슬라이드 범위 추출 (`1-5`, `2,4`) |
| `--extract-images`| 플래그 | `False` | PDF 이미지 추출 여부 |

---

### 3.3 `write` (독립 쓰기)
검색 단계 없이 직접 텍스트나 이미지를 삽입하거나, 문서를 초기화하거나, 파이프라인(stdin) 데이터를 대상 문서에 기록할 때 사용합니다.

```bash
python officecli.py write --to <경로|앱별칭> [옵션...]
```

#### 옵션 상세 테이블
| 옵션 | 타입 | 기본값 | 설명 |
| :--- | :--- | :--- | :--- |
| `--to` | `str` | **(필수)** | 대상 파일 경로 또는 활성 앱 별칭 (`word`, `excel`, `ppt`) |
| `--active` | 플래그 | `False` | 현재 화면에 열려 있는 활성 창에 쓰기 |
| `--text` | `str` | `None` | 기록할 단일 텍스트 내용 |
| `--image` | `str` | `None` | 삽입할 이미지 파일 경로 (`.png`, `.jpg`, `.bmp` 등) |
| `--clear` | 플래그 | `False` | 쓰기 전 대상 문서/시트/슬라이드를 완전히 비움 (자동 백업 자동 수행) |
| `--anchor` | `str` | `None` | 기준 위치 검색 키워드 |
| `--pos` | `str` | `after` | 앵커 상대 위치 (`after`, `before`, `replace`) |
| `--prefix` | `str` | `None` | 삽입 데이터 각 행에 붙일 접두사 |

> **💡 파이프라인(stdin) 지원**:  
> `--text`나 `--image`를 주지 않고 표준 입력을 전달하면 stdin의 JSONL 또는 일반 텍스트 라인을 그대로 대상 문서에 순서대로 기록합니다.  
> 예: `python officecli.py read --file a.xlsx | python officecli.py write --to word --active`

---

### 3.4 `info` (고속 메타데이터 요약)
대용량 문서를 전체 파싱하지 않고, 0.1초 만에 페이지 수, 크기, 목차(TOC)/시트명 구조를 빠르게 파악하여 후속 작업(검색/페이지 지정) 전략을 수립합니다.

```bash
python officecli.py info --file <경로|앱별칭> [--active]
```

#### 반환 JSON 예시
```json
{
  "src": "2026_신규사업계획서.pdf",
  "ext": "pdf",
  "size_kb": 2450.8,
  "page_count": 48,
  "toc": ["1. 사업 개요", "2. 시장 분석", "3. 기술 개발 계획", "4. 소요 예산"],
  "total_records": 312
}
```

---

### 3.5 `restore` (작업 전 1초 롤백 복원)
OfficeCLI가 수행한 모든 쓰기 및 초기화 작업은 사전에 백업 스냅샷이 생성됩니다. 결과가 마음에 들지 않거나 원복이 필요할 때 단 한 줄로 직전 상태로 복원합니다.

```bash
python officecli.py restore --target <앱별칭|파일경로> [--snapshot <스냅샷ID>]
```

#### 옵션 상세 테이블
| 옵션 | 타입 | 기본값 | 설명 |
| :--- | :--- | :--- | :--- |
| `--target` | `str` | **(필수)** | 복원 대상 앱 별칭 (`word`, `excel`, `ppt`) 또는 파일 경로 (상대/절대/파일명 모두 지원) |
| `--snapshot`| `str` | `None` | 특정 스냅샷 ID 지정 (생략 시 해당 대상의 **가장 최신 스냅샷**으로 자동 롤백) |

#### 반환 JSON 예시
```json
{
  "status": "ok",
  "action": "restored",
  "target": "excel",
  "from": "C:\\Users\\...\\excel_active_20261014_221750.xlsx",
  "snapshot_id": "active_excel_20261014_221750"
}
```

---

### 3.6 `backup` (백업 스냅샷 이력 조회)
현재 `.officecli_backup/` 폴더에 저장된 모든 백업 스냅샷 목록을 조회합니다.

```bash
python officecli.py backup list
```

---

## 4. 오피스 프로그램별 지원 범위 및 특성

| 포맷 / 프로그램 | 지원 모드 | 읽기 / 검색 방식 | 쓰기 / 편집 지원 범위 |
| :--- | :--- | :--- | :--- |
| **Microsoft Word** | 오프라인 파일 + **활성 창 제어** | 문단과 표의 실제 인쇄 배치 순서 100% 보장. 실제 쪽번호(`wdActiveEndPageNumber`) 추적 | 텍스트 추가, 네이티브 Word Table 자동 렌더링, 인라인 이미지 삽입(`InlineShapes`), 본문 초기화(`--clear`) |
| **Microsoft Excel** | 오프라인 파일 + **활성 창 제어** | 시트별 2D 정규화, 병합 셀 Forward-Fill 복원 | `=` 수식 자동 인식(`Formula`), 이전 행 서식 자동 상속(`xlPasteFormats`), 이미지 삽입(`Shapes`), 시트 초기화(`--clear`) |
| **PowerPoint** | 오프라인 파일 + **활성 창 제어** | 도형 중첩 그룹 재귀 언패킹, (Top, Left) 시각적 순서 정렬 추출 | **지능형 동적 페이지네이션** (슬라이드 높이 초과 시 자동 새 슬라이드 생성 및 표 분할), 이미지 삽입(`Shapes`), 슬라이드 초기화(`--clear`) |
| **한컴오피스 한글 (HWP)** | **로컬 파일 전용 (Read-Only)** | 화면 간섭 0% 백그라운드 엔진 구동, 본문 및 표 원천 순서 보장 고속 추출 | ❌ **읽기 전용 (PDF와 동일)**<br>(화면 포커스 뺏김, 보안 팝업, 키보드 간섭 원천 차단) |
| **PDF** | **로컬 파일 전용 (Read-Only)** | PyMuPDF 기반 고속 파싱, 목차(TOC) 요약, 이미지 분리 추출 | ❌ 읽기 전용 |
| **Markdown / Text** | 로컬 파일 읽기/쓰기 | 줄 단위 및 표 파싱 | 앵커 기준 텍스트 및 마크다운 표 삽입 |

---

## 5. 실무 상황별 명령어 치트시트 (Cookbook & Cheatsheet)

### 1) 로컬 한글(HWP) 문서에서 화면 간섭 없이 내용 검색
```bash
# 한글 창을 화면에 띄우지 않고 0.1초 만에 기안서에서 "추진 과제" 검색
python officecli.py run --file "C:\Docs\기안서.hwp" --search "추진 과제" --top 3
```

### 2) 대용량 PDF 문서에서 핵심 내용 초고속 검색
```bash
# 500페이지 분량의 규격서에서 "암호화 모듈" 관련 상위 3개 문단 추출 (2회차부터 0.01초 캐시)
python officecli.py run --file "C:\Docs\보안규격서.pdf" --search "암호화 모듈" --top 3
```

### 3) 한글(HWP) 파일에서 읽은 표 데이터를 활성 PPT 슬라이드에 바로 주입
```bash
# 한글 파일에서 "소요 예산" 표를 검색하여 현재 열린 PPT 슬라이드에 출처 태그를 달아 삽입
python officecli.py run --file "기안서.hwp" --search "소요 예산" \
  --to ppt --active --prefix "[한글 기안서 발췌] "
```

### 4) 열려 있는 엑셀 활성 시트에 수식 및 데이터 기입 (서식 상속)
```bash
# 열려있는 엑셀 창의 "소계" 행 아래에 새 데이터 행 추가 (윗행 서식 자동 복사)
python officecli.py write --to excel --active --anchor "소계" --pos after --text "신규사업비"
```

### 5) 작업 전 자동 백업 및 즉각적인 원상 복구 (롤백)
```bash
# 1. 엑셀 활성 시트를 실수로 비우고 새 내용을 적었을 때
python officecli.py write --to excel --active --clear --text "실수 데이터"

# 2. 1초 만에 작업 직전 원래 시트 상태로 완벽 복원!
python officecli.py restore --target excel
```

### 6) 3대 오피스 프로그램(Word, Excel, PPT)에 차트/그래프 이미지 삽입
```bash
# 워드 활성 문서에 차트 삽입
python officecli.py write --to word --active --image "chart.png"

# 파워포인트 활성 슬라이드에 차트 삽입
python officecli.py write --to ppt --active --image "chart.png"

# 엑셀 활성 시트에 차트 삽입
python officecli.py write --to excel --active --image "chart.png"
```

### 7) 활성 문서 완전 초기화 (새 작업 준비)
```bash
# PPT의 모든 슬라이드를 지우고 1번 빈 슬라이드로 초기화 (자동 백업 동시 수행)
python officecli.py write --to ppt --active --clear

# 워드 활성 문서 본문 완전 삭제
python officecli.py write --to word --active --clear
```

### 8) 파이프라인(stdin)을 통한 복합 문서 변환 및 전송
```bash
# 엑셀 시트의 데이터를 읽어서 워드 활성 문서로 직접 파이프 전송
python officecli.py read --file "원천데이터.xlsx" | python officecli.py write --to word --active
```

---

## 6. 자주 묻는 질문 및 트러블슈팅 (FAQ & Troubleshooting)

### Q1. 한글(HWP) 문서를 수정하거나 한글에 글을 쓸 수는 없나요?
- **답변**: 한컴오피스 한글은 Windows 보안 모듈 팝업 및 화면 포커스 간섭 이슈가 있어, 안정성을 위해 **PDF와 동일하게 '초고속 무간섭 백그라운드 읽기 전용'으로 정책이 고정**되어 있습니다.
- 한글 문서의 내용을 읽어서 Word, Excel, PowerPoint 등으로 변환하거나 전송하는 방향으로 활용하시기를 권장합니다.

### Q2. 활성 창(`--active`)을 제어하려는데 프로그램을 찾지 못한다고 나옵니다.
- **원인**: 해당 오피스 프로그램(Word, Excel, PowerPoint)이 실행되어 있지 않거나, 문서가 열려 있지 않은 상태입니다.
- **해결**: Word, Excel, PowerPoint 프로그램을 실행하고 빈 문서라도 하나 열어둔 상태에서 실행하세요.

### Q3. 복원(`restore`)할 때 어떤 대상명을 지정해야 하나요?
- 활성 창이었던 경우 앱 별칭(`word`, `excel`, `ppt`)을 지정합니다.
- 오프라인 파일이었던 경우 전체 경로(`C:\test\sample.docx`), 상대 경로(`test/sample.docx`), 또는 순수 파일명(`sample.docx`) 중 편한 형식을 지정하면 가장 최근 백업을 찾아 복원합니다.
- 특정 시점으로 가고 싶다면 `python officecli.py backup list`에서 ID를 확인한 뒤 `--snapshot <ID>`를 넘기면 됩니다.

### Q4. 캐시를 강제로 비우고 처음부터 다시 파싱하고 싶습니다.
- 프로젝트 디렉토리에 있는 `.officecli_cache/` 폴더를 삭제하면 다음 실행 시 원본 문서를 처음부터 새로 파싱합니다.
- 마찬가지로 백업 파일 용량을 정리하고 싶을 때는 `.officecli_backup/` 폴더 내의 오래된 스냅샷을 삭제하시면 됩니다.
