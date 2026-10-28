# 사내 PC OpenCode 배치 안내

사내 PC(Windows 11, 폐쇄망, OpenCode + 26B~30B 모델)에 도구 스킬과 전역 지침을 놓는 방법입니다.
저장소는 반입 후 `C:\CLI`에 `ml-kit`, `office-cli`가 있는 상태를 기준으로 합니다.

## 1. 스킬 연결 (한 번만)

스킬 폴더에 복사하는 대신 `C:\CLI`를 가리키는 연결(junction)을 만들면, 다음 반입 때 `C:\CLI`만 바꾸면 스킬도 함께 바뀝니다.
cmd에서 실행합니다.

```bat
mkdir "%USERPROFILE%\.config\opencode\skills"
mklink /J "%USERPROFILE%\.config\opencode\skills\ml-kit"          "C:\CLI\ml-kit"
mklink /J "%USERPROFILE%\.config\opencode\skills\office-cli"      "C:\CLI\office-cli"
mklink /J "%USERPROFILE%\.config\opencode\skills\office-cli-test" "C:\CLI\office-cli\tools\office-cli-test"
```

- `office-cli-test`(실기 테스트 스킬)는 `office-cli` **옆**에 있어야 합니다. 위 연결로 그렇게 됩니다.
- 복사로 배치해도 됩니다. 그때는 반입할 때마다 다시 복사해야 합니다.
- 도구 오류 로그는 `C:\CLI\<도구>\data\logs\errors.txt`에 쌓이고, `C:\CLI\run_all_tests.py --only diag`가 결과 파일에 붙여 줍니다.

## 2. 전역 지침 (AGENTS.md)

1. 이 폴더의 `AGENTS.md`를 `C:\Users\<사용자이름>\.config\opencode\AGENTS.md`로 복사합니다.
2. 파일 안의 `<사용자이름>`을 실제 Windows 사용자 이름으로 바꿉니다 (3장 2번).

이미 넣어 두신 내용은 아래처럼 반영했습니다.

| 기존 항목 | 반영 위치 |
|---|---|
| 한국어 우선 (답변, 설명, 주석) | 1장 1번. 명령어와 경로는 원문 그대로 쓰도록 구분 |
| 이모지 금지 | 1장 2번. 대신 쓸 글자 표시(`[OK]`, `->`)를 함께 줌 |
| 파일 삭제 전 명시적 승인 | 5장. 덮어쓰기, 메일 발송, 시트·슬라이드 삭제도 같은 규칙으로 묶음 |
| 폐쇄망, pip·인터넷 불가 | 2장. 도구가 설치 명령을 안내해도 직접 실행하지 않음(4장) |
| ml-kit, office-cli 적극 활용 | 3장. 요청별 스킬 표, 직접 파이썬 코드를 짜지 않는 규칙 |
| PowerShell, 한글 깨짐 방지 | 2장. 두 환경변수에 `[Console]::OutputEncoding`을 더함 (아래 참고) |

한글 깨짐: `PYTHONIOENCODING`, `PYTHONUTF8`은 파이썬이 UTF-8로 **내보내게** 하는 설정이고,
`[Console]::OutputEncoding=[Text.Encoding]::UTF8`은 PowerShell이 그 출력을 UTF-8로 **읽게** 하는 설정입니다. 둘 다 있어야 확실합니다.
두 환경변수는 cmd에서 한 번 `setx PYTHONIOENCODING utf-8`, `setx PYTHONUTF8 1`로 영구 설정해 두면 더 안전합니다 (새 창부터 적용).

## 3. 26B~30B 모델에 맞춘 작성 원칙

AGENTS.md와 각 SKILL.md는 아래 원칙으로 썼습니다. 고칠 때도 지켜 주세요.

1. 규칙은 번호 목록, 선택은 표로 씁니다. 긴 문단은 작은 모델이 놓칩니다.
2. 명령은 그대로 복사할 수 있는 템플릿으로 주고 `<...>`만 바꾸게 합니다. 옵션을 짐작하게 두지 않습니다.
3. 결과 해석은 `agent_directive` 첫 단어 하나로 정합니다 (`VERIFIED:`, `UNVERIFIED:`, `STOP_RETRY:` + `[추천]`/`[후보]`, `ERROR:`).
   전역 지침과 각 SKILL.md의 표가 같은 말을 하도록 맞춰 두었습니다.
4. "정확하게", "친절하게" 같은 일반론은 쓰지 않습니다. 할 행동과 하지 말 행동만 씁니다.
5. PowerShell에서 깨지기 쉬운 것(큰따옴표가 든 JSON 인자, `$`, 여러 줄 글)은 파일로 넘기게 합니다.
   예전 office-cli SKILL.md의 `--values "[[\"이름\",\"값\"]]"` 예시는 PowerShell에서 따옴표가 사라져 실패하므로 `--file "표.csv"`로 바꿨습니다.
6. SKILL.md 상세 설명은 README.md로 보냅니다. SKILL.md는 스킬을 쓸 때마다 컨텍스트에 들어갑니다.

## 4. 사내 LLM이 지침을 다듬게 할 때

처음부터 다시 쓰게 하지 말고, 실제로 틀린 대화를 보여 주고 고칠 곳만 제안하게 합니다.

```text
아래는 네가 office-cli 스킬을 쓰다가 틀린 대화와, 지금의 전역 지침(AGENTS.md)이다.
같은 실수를 다시 하지 않게 하려면 AGENTS.md에서 무엇을 바꾸면 되는지 제안해라.
- 최대 3줄만 추가하거나 고친다. 전체를 다시 쓰지 않는다.
- 각 SKILL.md에 이미 있는 내용은 반복하지 않는다.
- 형식: "바꿀 줄: ... / 새 문장: ... / 이유: ..."
```

제안은 사용자가 보고 반영한 뒤, 같은 요청을 다시 해서 고쳐졌는지 확인합니다. 바뀐 AGENTS.md는 이 폴더에도 올려 두면 다음 검토 때 함께 봅니다.
