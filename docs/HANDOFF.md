# 인수인계 메모 (작업 이어가기용)

다른 기기·새 세션에서 이 저장소 작업을 이어갈 때 가장 먼저 읽는 문서입니다.
저장소 규칙과 사용자 환경은 루트 `AGENTS.md`(자동 로드)에 있습니다.

## 1. 현재 상태 (2026-10-27)

- 작업 브랜치: `ccr-4dce8067-cxbgb4` (PR 아직 없음)
- 도구: `CLI/ml-kit/` **1.0.0 첫 배포 버전 완성**, 실기(Windows PC) 테스트 전
- 자동 테스트 43개 통과 (사용자 환경 버전: Python 3.13, pandas 3.0.5, scikit-learn 1.9.0, matplotlib 3.11.1)

| 파일 | 역할 |
|---|---|
| `CLI/ml-kit/ml_train.py` | 학습 (회귀/분류, 피처 유형 자동 판별, 5개 모델 경쟁, next_commands) |
| `CLI/ml-kit/ml_predict.py` | 예측 + 공통 런타임. 이 파일 + 버전 폴더만으로 단독 배포 |
| `CLI/ml-kit/ml_report.py` | ML 결과 보고서 (Word, 버전 폴더 1개 = 문서 1개) |
| `CLI/ml-kit/SKILL.md` | OpenCode 스킬 (이름 `ml-kit`) |
| `CLI/ml-kit/CHANGELOG.md` | 1.0.0 내용 + **남은 할 일** |
| `CLI/ml-kit/samples/PC_TEST.md` | **실기 테스트 체크리스트** (예상 결과 포함) |

## 2. 사용자가 확정한 결정

- 에이전트: OpenCode + 26B~30B LLM, LLM 개입 최소화 (명령 1회 + JSON 1줄)
- 파일 수는 적게: ml-kit은 `.py` 3개 구성 (공통 코드는 `ml_predict.py` PART C)
- 예측 배포: `ml_predict.py`와 버전 폴더를 따로 복사 (B안)
- 작업 유형(`--task`)은 사용자가 지정, 기본값 회귀. 분류 챔피언 기준은 Macro-F1
- 예측·보고서는 버전 폴더를 직접 지정 (`-m <version_dir>`), 자동 선택 없음
- 보고서: 이름 "ML 결과 보고서", 버전의 모든 타겟을 문서 1개로, python-docx Word만, 회사 템플릿 불필요
- 첫 배포 전이라 하위 호환 불필요 → 1.0.0에서 인터페이스 정리 완료. 이후부터 호환 규칙 적용 (`AGENTS.md` 규칙 4, 5)
- 이전 개발 이력 문서는 정리하고 1.0.0부터 `CHANGELOG.md`로 관리

## 3. 다음 할 일

1. **PC 실기 테스트**: `CLI/ml-kit/samples/PC_TEST.md` 0~8번. 특히 확인할 것:
   - Word에서 보고서 글꼴(맑은 고딕)·레이아웃
   - OpenCode 명령 실행 시간 제한 (학습이 길 때 끊기는지)
   - 동시 실행 잠금 (Windows `msvcrt` 경로는 Linux에서 검증 못 함)
   - `next_commands` 명령을 cmd/PowerShell에 그대로 붙여 실행
2. **보고서 디자인 피드백 반영** (샘플 보고서는 `samples` 데이터로 `ml_report.py`를 실행하면 다시 만들 수 있음)
3. `CHANGELOG.md` 남은 할 일

## 4. 새 세션 시작 방법

```bat
git clone https://github.com/Sein-Oh/AI_WORK.git
cd AI_WORK
git checkout ccr-4dce8067-cxbgb4
python -m pytest -q
```
첫 요청 예시: "docs/HANDOFF.md를 읽고 ml-kit 작업을 이어가자. PC_TEST.md 0번부터 같이 진행하자."
