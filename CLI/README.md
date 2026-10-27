# CLI 도구 모음

AI 에이전트(26B~30B 경량 LLM)가 **스킬로 호출하는 CLI 도구**를 모아두는 곳입니다. 도구 1개 = 폴더 1개.

| 도구 | 설명 | 스킬 |
|---|---|---|
| [`ml-kit/`](ml-kit/) | 회귀·분류 ML 학습 / 예측(단독 배포 가능) / Word 감사 보고서(회귀) | [`ml-kit/SKILL.md`](ml-kit/SKILL.md) |
| [`atomic-cli/`](atomic-cli/) | Excel/Word/PowerPoint/Outlook 자동화(열린 문서 읽기·쓰기, 앱 간 전달, 되돌리기), PDF/HWP/EML 읽기와 검색 | [`atomic-cli/SKILL.md`](atomic-cli/SKILL.md) |
| [`doc-classifier/`](doc-classifier/) | 폴더 전체 파일 목록화 -> 파일명 분류 -> 표본 내용 확인 -> 엑셀 보고서 (0.9.0, Windows 실기 대기). 12TB급 대용량 대비 | [`doc-classifier/SKILL.md`](doc-classifier/SKILL.md) |

에이전트 런타임은 **OpenCode** 입니다. 각 도구 폴더가 그대로 OpenCode 스킬 폴더이며, 폴더 이름 = 스킬 이름
(소문자, 숫자, 하이픈만: `^[a-z0-9]+(-[a-z0-9]+)*$`) 이어야 합니다. 설치 위치: `C:\Users\<사용자>\.config\opencode\skills\<tool>\`.

## 새 도구 폴더 구성

```text
CLI/<tool>/           # 폴더명 = 스킬명 (예: ml-kit)
├── SKILL.md            # OpenCode 스킬. frontmatter: name(=폴더명), description(1024자 이하), license, compatibility, metadata
├── README.md           # 사람용 상세 설명서
├── CHANGELOG.md        # 변경 이력 + 남은 할 일
├── requirements.txt    # 런타임 의존성 (폐쇄망 wheel 반입 기준)
├── <tool>_*.py         # CLI 진입점 (폴더째 복사해도 단독 실행 가능)
└── tests/              # CLI 계약 테스트 (python -m pytest CLI 로 전체 실행)
```

## 모든 도구가 지키는 ACI 공통 계약

1. **stdout = 정확히 1줄 JSON.** 진행 로그·표·경고는 모두 stderr.
2. 성공: exit 0, `"status": "ok"`, `agent_directive`가 `VERIFIED:`로 시작.
3. 실패: exit 1(인자 오류 2, 중단 130), `"status": "error"`, `agent_directive`가
   - `STOP_RETRY:` – 입력/데이터 문제. message에 `[추천]`이 있으면 그 값으로 1회만 재시도.
   - `ERROR:` – 내부 오류. 재시도 금지.
4. 에이전트가 판단할 일을 줄인다: 이름 자동 매칭, 기본값, 자동 상속, 오타 추천을 도구가 처리.
5. 이모지 금지, 로그 태그는 `[INFO] [PROGRESS] [WARN] [ERROR] [STATUS]`.
6. 폐쇄망: 실행 중 네트워크 접근 금지. [표준 환경](../docs/ENVIRONMENT.md)에 있는 라이브러리만 사용 ([`docs/WINDOWS_OFFLINE.md`](../docs/WINDOWS_OFFLINE.md)).
