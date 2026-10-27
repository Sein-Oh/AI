# ROADMAP – ml_kit 개선/최적화 백로그

## 완료 (1.1.0)
- [x] pandas 3.0 비호환 (문자열 dtype) – `coerce_numeric`
- [x] README 예시 B 수식 불일치 – 단위 생략 이름 자동 매칭
- [x] 존재하지 않는 `ml_train_spec.md` 참조 제거
- [x] 학습/추론 중복 코드 통합 – `ml_common.py`
- [x] stdout UTF-8 재설정 중복 제거
- [x] `--eval` 보안 샌드박스 단위 테스트
- [x] report history.jsonl 폴백 버그, 버전 지정 오류 처리

## 남은 항목
### P1 – 기능 (LLM 개입 추가 감소)
- [ ] `-x` 생략 시 타겟을 제외한 수치형 컬럼 자동 선택 (ID/일련번호 컬럼 배제 규칙 필요)
- [ ] `recommendations`를 바로 실행 가능한 다음 명령(`next_command`) 형태로 제공
- [ ] 같은 데이터에 대한 동시 실행(버전 번호 충돌) 잠금

### P2 – 성능
- [ ] 무거운 import(sklearn, docx) 지연 로딩 -> `--history` 등 경량 명령 응답 속도 개선
- [ ] 대용량 데이터에서 순열 중요도 샘플링 (n_repeats, max_samples)
- [ ] 5-Fold x 5모델 병렬화 검토 (폐쇄망 PC 코어 수/메모리 고려)

### P3 – 테스트 / 문서
- [ ] xlsx 비표준 헤더 자동 감지(`--header-row` 생략) 테스트
- [ ] 다중 타겟 학습 -> 폴더 추론 -> 일괄 보고서 테스트
- [ ] Windows 실기 테스트 (파일 잠금, 긴 경로, cmd/PowerShell 인자 전달)
