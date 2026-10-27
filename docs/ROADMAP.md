# ROADMAP – 개선/최적화 백로그

기준선 검토(2026-10-27) 중 발견한 항목입니다. 우선순위: P0 버그 > P1 구조 > P2 성능 > P3 문서.

## P0 – 버그 / 호환성
- [ ] **pandas 3.0 비호환**: `validate_and_sanitize_data()`가 `dtype == object`로 문자열 컬럼을 판별하는데,
      pandas 3.0의 기본 문자열 dtype은 `str`이라 숫자 변환이 건너뛰어짐 →
      `residuals = y - champion_oof`에서 `TypeError: unsupported operand type(s) for -: 'str' and 'float'`.
      (`pd.api.types.is_numeric_dtype` 기반 판별로 교체 필요. `ml_predict.py`도 동일 패턴 점검)
- [ ] **README 예시 B 수식 불일치**: `--eval "에너지집중도 = 소비전력 / (반응온도 + 1e-6)"`처럼 단위 없는 이름을 쓰지만,
      실제로는 전체 컬럼명(`소비전력(kW)`)이 필요하여 "허용되지 않은 식별자" 오류 발생. 문서 수정 또는 단위 생략 별칭 매칭 지원.
- [ ] `ml_kit/README.md`가 참조하는 `ml_train_spec.md`가 아카이브에 없음 – 추가하거나 참조 제거.

## P1 – 구조 (중복 제거)
- [ ] `emit_json_response`, `sanitize_filename`, AST 화이트리스트/검증, `load_data_file`(헤더 스니핑)이
      `ml_train.py` / `ml_predict.py` (일부 `ml_report.py`)에 중복 → `ml_kit/_common.py`로 통합.
      학습/추론 간 파생변수·로딩 로직이 어긋나면 train/serve skew가 생기므로 우선순위 높음.
- [ ] stdout UTF-8 재설정 블록 3중 중복 → 공통 모듈로 이동.

## P2 – 성능
- [ ] 5-Fold × 5모델 순차 학습 → `n_jobs`/병렬화, 트리 모델 파라미터 점검.
- [ ] 무거운 import(sklearn, docx)를 필요 시점 지연 로딩 → `--history` 등 경량 명령 응답 속도 개선.

## P3 – 테스트 / 문서
- [ ] `--eval` 보안 샌드박스 단위 테스트 (속성 접근, `__import__`, 타겟 누수 차단).
- [ ] xlsx 비표준 헤더(`--header-row/--unit-row/--data-row`) 테스트.
- [ ] 다중 타겟 학습 → 폴더 단위 추론 → 일괄 보고서 테스트.
