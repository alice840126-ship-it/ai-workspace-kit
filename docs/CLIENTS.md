# Codex · Aside · ChatGPT 연결

먼저 README의 로컬 데모, 기억 초기화, 문서 허용 경로 등록을 완료하세요.
각 클라이언트에서 같은 state 절대경로를 사용합니다. 아래 `/absolute/...`는 반드시 실제 경로로 바꿉니다.

## 제공 도구

| 도구 | 동작 |
|---|---|
| `workspace_recall(query)` | 최근 요약 → 정제 기억 검색 |
| `search_local(query, limit=5)` | 허용 문서 후보와 원본 식별자 반환 |
| `read_local_artifact(artifact_id, offset=0, limit=12000)` | 원본을 다시 열어 추출한 텍스트 반환 |
| `workspace_health()` | 상태·접근 범위 점검 |
| `workspace_checkpoint(checkpoint)` | 쓰기 허용 실행에서만 정제 요약 접수 |

원격 연결에는 `--read-only`를 권장하며 이때 checkpoint 도구는 등록하지 않습니다.
과거 세션 검색은 기본 비활성입니다. 별도 검증된 로컬 history 색인에 한해 `--allow-cold`로 허용할 수 있습니다.
도구 설명은 관련 요청에서 호출하도록 돕지만 모델이 매번 적절히 호출한다고 보장하지 않습니다.

## Codex

`codex mcp add --help`에서 현재 설치 버전의 등록 형식을 확인하세요.
현재 CLI의 stdio 등록 예시:

```bash
codex mcp add ai-workspace-kit -- /absolute/ai-workspace-kit/.venv/bin/ai-workspace-mcp --state /absolute/private-state --read-only
```

로컬 정제 요약 쓰기도 원하면 `--read-only`를 빼고 등록합니다. 이때도 임의 파일 쓰기가 아니라
엄격한 checkpoint 스키마만 허용됩니다. 기존 MCP 항목을 덮어쓰거나 인증 설정을 복사하지 마세요.
새 채팅에서 도구 목록을 확인한 후 `workspace_health`와 합성 자료 검색을 시험합니다.

에이전트에 다음 규칙을 프로젝트 지침으로 추가할 수 있습니다.

```text
이전 작업을 이어갈 때 현재 대화로 충분하지 않으면 workspace_recall을 사용한다.
주제가 분명하면 AI Workspace라는 명칭을 사용자에게 요구하지 않는다.
문서의 금액·조건·범위는 search_local 이후 read_local_artifact가 성공한 원본에만 근거한다.
중요한 결정·완료·TODO는 쓰기 도구가 있을 때 짧은 checkpoint로 기록한다.
원문 대화·비밀정보·확인하지 않은 추측을 기록하지 않는다.
도구가 없거나 실패하면 연결됐다고 말하지 않는다.
```

## Aside

Aside의 로컬 MCP 등록에서 실행 파일을 `.venv/bin/ai-workspace-mcp` 절대경로로,
인자를 `--state`, 상태 절대경로, 필요 시 `--read-only`로 설정합니다.
호스트마다 등록 UI/설정 형식이 달라질 수 있으므로 기존 항목 형식을 확인하세요.
작업 디렉터리는 코드 저장소로 설정할 수 있으나, 설치된 실행 파일은 cwd에 의존하지 않습니다.
등록 후 실제 도구가 보이는 새 채팅에서 아래 검증을 수행합니다.

## ChatGPT: GitHub 기억 읽기

ChatGPT의 GitHub 연결에 자신의 **비공개 기억 저장소**를 허용합니다.
공개 코드 저장소만 연결해도 개인 기억이 생기는 것은 아닙니다.
질문 시 `INDEX.md → memory/<topic>.md`를 읽도록 연결된 소스를 선택합니다.
검색 결과의 출처와 기록 시각으로 실제 조회 여부를 확인하세요.

이 연결은 로컬 파일 검색이나 ChatGPT 대화 자동 저장을 제공하지 않습니다.
쓰기 도구가 없는 ChatGPT에서는 요약 JSON을 만들어 로컬 `checkpoint`에 입력하는 경로를 사용할 수 있습니다.

## ChatGPT: 로컬 원본 읽기

ChatGPT는 내 컴퓨터의 stdio 프로세스에 직접 접속하지 못합니다.
사용자 계정에서 제공되는 **인증된 Secure MCP Tunnel**로 연결합니다.
이 프로젝트는 터널 계정·키를 만들거나 공개 HTTP 포트를 자동 개방하지 않습니다.

공식 문서: [연결·테스트](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
메뉴와 사용 가능 여부는 계정·조직·제품 버전에 따라 달라집니다. 해당 기능이 보이지 않으면
무인증 공개 서버로 우회하지 말고 GitHub 정제 기억 연결 또는 로컬 Codex/Aside를 사용하세요.

검증된 구성 방식:

1. 공식 클라이언트를 설치하고 릴리스의 체크섬을 검증합니다.
2. 본인 조직에서 터널을 등록합니다. 기존 터널이 있으면 재사용합니다.
3. 아래 명령으로 읽기 전용 MCP 실행 파일을 연결합니다. 키는 비공개 환경/키 저장소에서 주입합니다.
4. ChatGPT 개인 MCP 앱 생성 화면에서 터널 ID를 연결합니다. 조직·접근 범위를 본인 용도로 제한합니다.
5. 새 텍스트 채팅에서 도구 호출과 원본 읽기를 실제 확인합니다.

```bash
# CONTROL_PLANE_API_KEY는 외부 비공개 저장소에서 주입. 키 값을 인자로 쓰지 않습니다.
tunnel-client runtimes connect \
  --alias ai-workspace-kit \
  --profile ai-workspace-kit \
  --profile-dir /absolute/private-tunnel-profiles \
  --tunnel-id YOUR_TUNNEL_ID \
  --runtime-api-key env:CONTROL_PLANE_API_KEY \
  --mcp-command '/absolute/ai-workspace-kit/.venv/bin/ai-workspace-mcp --state /absolute/private-state --read-only'

tunnel-client runtimes status ai-workspace-kit --json
tunnel-client runtimes stop ai-workspace-kit
```

위 명령 형식은 운영본에서 사용한 클라이언트 0.0.15 기준입니다. 다른 버전은 `--help`로 확인하세요.
profile/state는 Git 밖에 두고 비공개 권한을 유지합니다. 이 코드 배포와 외부 서비스 계정·과금 조건은 별개입니다.
컴퓨터가 잠자기 상태이거나 터널이 꺼지면 원본은 읽을 수 없습니다. 터널 건강 상태만으로 ChatGPT 호출 성공을 주장하지 마세요.

## 실제 검증 질문

합성 `ExampleCo` 견적서를 허용 경로에 복사하고 색인한 뒤:

1. “ExampleCo 견적서 찾아서 열어봐.”
2. “그 견적서의 VAT 포함 금액과 교육 횟수는?”
3. 파일을 안전한 임시 폴더에서 이동한 뒤 같은 원본 읽기를 시도합니다.

성공은 `search_local`과 `read_local_artifact`의 실제 호출, 원본에 있는 금액·횟수와 출처 확인입니다.
기억이나 검색 snippet만 사용한 답변은 실패입니다. 세 번째는 원본 접근 실패를 사실대로 반환해야 합니다.
필요하면 MCP에 `--audit-calls`를 추가해 로컬에 tool/성공 여부/ID만 기록할 수 있습니다.
쿼리·경로·본문은 해당 감사 로그에 기록하지 않습니다. 테스트 후 옵션을 제거해도 됩니다.

음성은 텍스트 성공과 별도로 같은 tool 호출이 발생하는지 확인해야 합니다.
이 배포판은 실제 음성 검증을 완료하지 않았으며 자동 지원을 약속하지 않습니다.
