# 실기 테스트 기록

회사 PC(Windows 11, Office 16, 문서 보안 프로그램 있음)에서 받은 테스트 결과 원본입니다. 기록용이며 편집하지 않습니다.
새 결과는 `CLI/run_all_tests.py`가 만든 `test_result_<라벨>_<시각>.txt`를 이 폴더에 올립니다 (`CLI/` 폴더에 두면 반입할 때마다 함께 따라갑니다).

| 파일 | 도구 버전 | 결과 | 반영 |
|---|---|---|---|
| `test_log_20261028_1차실기.txt` | ml-kit 2.3.0, office-cli 1.2.0 | ml-kit 실기 12/14, office-cli 실기 중단(A5 이후 Excel 닫힘), 오프라인 실패 다수 | PR #15 (ml-kit 2.3.1, office-cli 1.2.1) |
| `test_result_PC_20261028_150604.txt` | ml-kit 2.3.1, office-cli 1.2.1 | ml-kit 실기 14/14, office-cli 실기 65/65, 오프라인 실패 4건 | PR #16 (ml-kit 2.3.2) |
| `261029_test_log.md` | ml-kit 2.4.0, office-cli 1.4.0 | ml-kit 실기 14/14, office-cli 실기 71/71(E3, K1~K5 포함), office-cli 오프라인 실패 4건·오류 10건, OpenCode 대화 6개(스킬 불러오기 실패: ripgrep) | office-cli 1.4.1 |
