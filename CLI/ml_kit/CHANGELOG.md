# CHANGELOG

## [1.1.0] - 2026-10-27

### 구조
- 저장소 위치를 `CLI/ml_kit/`로 이동 (CLI 도구 모음 구조).
- `ml_common.py` 신설: 학습/추론에 중복되던 데이터 로더, 수식 엔진, JSON 출력, 파일명 처리를 한 곳으로 통합
  (학습/추론 처리 불일치 방지).
- `SKILL.md`(경량 LLM용 짧은 스킬), `install_offline.bat`, `requirements-dev.txt` 추가.

### 버그 수정
- **pandas 3.0에서 학습 실패** (`TypeError: unsupported operand type(s) for -: 'str' and 'float'`):
  문자열 컬럼 판별을 `dtype == object`에서 dtype 무관 수치 변환(`coerce_numeric`)으로 교체. pandas 2.x/3.x 모두 지원.
- **추론 시 천단위 콤마(`1,234`)/`-` 문자열 컬럼 처리 누락**: 학습과 동일한 수치 변환 적용.
- **`--eval` README 예시 B 실패** (단위 없는 이름 '허용되지 않은 식별자'): 단위를 뺀 고유 이름 자동 매칭 지원.
  저장되는 수식은 항상 전체 컬럼명.
- **`ml_report.py` history.jsonl 폴백이 history.json을 다시 읽던 버그** 수정.
- **`ml_report.py --version` 미존재 버전 지정 시 다른 버전으로 조용히 대체**되던 문제 -> 사용 가능 버전 목록과 함께 오류.
  `-v 2`/`-v v2` 모두 허용, 같은 버전 재학습 시 최신 기록 사용.
- **Ctrl+C 시 임시 폴더 미롤백 + JSON 미출력**: `KeyboardInterrupt`도 롤백하고 `error_type: interrupted` JSON(exit 130) 반환.
- **문서에 정의된 `STOP_RETRY` 지시어가 실제로는 출력되지 않던 문제**: 입력/데이터 오류는 `STOP_RETRY:`, 내부 오류는 `ERROR:`.
- **잘못된 CLI 인자 시 JSON 없이 argparse 텍스트만 출력**되던 문제 -> JSON 오류(exit 2).
- **상수 컬럼 상관계수 NaN이 원장에 `NaN`(비표준 JSON)으로 기록**되던 문제 -> `null`.
- **보고서 슬롯4가 상관행렬과 무관하게 "다중공선성 없음"을 고정 출력** -> 실제 |r|>=0.85 쌍을 검사해 기술.
  슬롯1(과적합 간극), 슬롯3(최저 MAE 문구)도 실제 수치 기반으로 수정.
- `missing_imputed` 집계가 파생변수 포함 시 잘못 계산되던 문제 수정.
- 추론 외삽 경고가 타겟 수만큼 중복되던 문제 수정.

### 개선 (LLM 개입 최소화)
- `-x`/`-y`/`--eval`/`--input` 키/`--target`에 단위 생략 이름 허용 (`생산효율` -> `생산효율(%)`), 매칭 내역은 `column_aliases`로 반환.
- 컬럼명 오타 시 `[추천]` 후보 제시 (경량 LLM이 1회 자가 수정 가능).
- `ml_predict.py`: 문서에 정의된 `drift_warning`, `extrapolation_warnings`, `total_rows` 키 추가 (기존 키 유지).
- `ml_predict.py -i`에 `.json` 파일 경로 허용 (Windows 셸 따옴표 이스케이프 회피).
- `ml_train.py --history`: 표는 stderr, 요약 JSON은 stdout (1줄 JSON 계약 준수).

### Windows 11 / 폐쇄망
- 결과 CSV/Excel/Word 파일이 열려 있으면 타임스탬프 파일명으로 자동 분기 저장.
- 버전 폴더 이름 변경/삭제 시 백신·탐색기 잠금 재시도, 읽기 전용 파일 처리.
- txt/json 입력 파일 인코딩 자동 인식 (UTF-8, UTF-8 BOM, UTF-16(PowerShell), CP949).
- `history.json` 원자적 쓰기, 긴 경로(>240자) 경고, `.xls` 입력 시 명확한 안내.
- 모델 메타데이터에 `sklearn_version` 기록, 추론 PC 버전 불일치 시 경고.

## [baseline] - 2026-10-27
- 업로드된 `ml_kit.7z` 원본 코드를 평문으로 저장소에 등록 (코드 변경 없음).
