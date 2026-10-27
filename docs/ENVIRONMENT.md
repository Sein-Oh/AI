# 표준 사용자 환경

`CLI/` 아래 모든 도구는 이 환경에서 **추가 설치 없이** 동작하는 것을 기본 목표로 합니다.
버전 고정 목록: 루트 [`constraints.txt`](../constraints.txt)

| 항목 | 값 |
|---|---|
| OS | Windows 11 (폐쇄망) |
| Python | 3.13.13 |
| 에이전트 LLM | 26B~30B 경량 모델 (스킬로 도구 호출) |

## 설치된 주요 라이브러리

| 분류 | 패키지 (버전) |
|---|---|
| 데이터/ML | pandas 3.0.5, scikit-learn 1.9.0, scipy 1.18.1 (numpy, joblib은 의존성으로 포함) |
| 시각화 | matplotlib 3.11.1, seaborn 0.13.2 |
| 문서 | openpyxl 3.1.5 (xlsx), pymupdf 1.28.2 / pymupdf4llm 1.28.2 (PDF) |
| 영상 | opencv-python 5.0.0.93 |
| 에이전트/서버 | fastapi 0.141.1, fastmcp 3.4.7, mcp 1.28.1, langgraph 1.2.11, openai 2.54.0 |
| Windows | pywin32 312 |
| 테스트 | pytest 9.1.1 |

## 도구별 호환 현황

| 도구 | 상태 | 비고 |
|---|---|---|
| `ml_kit` 학습/예측 | 추가 설치 없이 동작 | 동일 버전(pandas 3.0.5, scikit-learn 1.9.0, openpyxl 3.1.5)으로 테스트 통과 |
| `ml_kit` 보고서 (`ml_report.py`) | **python-docx 필요 (표준 환경에 없음)** | 미설치 시 `STOP_RETRY` JSON으로 안내 후 종료 |

## 새 도구를 만들 때 규칙

1. 위 목록에 있는 라이브러리만 사용합니다. 폐쇄망이라 새 패키지 반입은 비용이 큽니다.
2. 목록에 없는 패키지가 꼭 필요하면 이 문서의 "도구별 호환 현황"에 기록하고, 없을 때도 JSON 오류로 안내되게 합니다.
3. 테스트는 `constraints.txt` 버전으로 실행해 통과해야 합니다.
