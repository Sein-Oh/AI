# CLAUDE.md – 이 저장소를 수정하는 AI 에이전트용 규칙

## 저장소 성격
- `ml_kit/*.py` 는 **다른 LLM 에이전트(26B~30B 경량 모델)가 CLI로 호출하는 도구**입니다.
- 따라서 사람이 아닌 에이전트가 소비자입니다. 출력 형식의 작은 변화도 하위 에이전트를 깨뜨릴 수 있습니다.

## 반드시 지킬 ACI 계약
1. **stdout은 정확히 1줄 JSON** (`status`, `message`/`agent_directive` 등). 진행 로그·경고는 전부 stderr.
2. 성공 시 exit code 0, 실패 시 1 + `{"status": "error", ...}`.
3. 이모지/원문자 금지, 로그 태그는 `[INFO] [PROGRESS] [WARN] [ERROR] [STATUS]`만 사용 (CP949 콘솔 호환).
4. 기존 CLI 인자 이름·축약형은 삭제/의미 변경 금지. 바꿔야 하면 deprecated alias를 남깁니다.
5. 산출물 레이아웃(`<stem>_ml_data/history.jsonl`, `vX/model_<target>.joblib|json` 등)과
   `history.jsonl` 스키마는 하위 호환 유지 (필드 추가는 OK, 삭제·이름변경은 NO).
6. 각 스크립트는 단독 실행 가능해야 합니다 (`python ml_kit/ml_train.py ...`). 공통 모듈을 도입할 경우
   `ml_kit/` 내부에 두고 스크립트 위치 기준 import가 되도록 합니다.

## 작업 절차
1. 변경 전 `python -m pytest -q tests` 로 기준선 확인.
2. 리팩터링(동작 불변)과 기능/동작 변경은 **별도 커밋/PR**.
3. 동작이 바뀌면 `tests/`에 회귀 테스트 추가, `ml_kit/README.md`와 `docs/CHANGELOG.md` 갱신.
4. 처리한 항목은 `docs/ROADMAP.md`에서 체크.

## 환경
- Python 3.10+, `pip install -r requirements.txt`
- pandas 3.x 는 현재 미지원 (ROADMAP P0 참고).
