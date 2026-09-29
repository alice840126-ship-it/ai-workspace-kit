# 운영 안내

## 1. 세 위치를 분리하기

- 코드: clone한 `ai-workspace-kit`. 업데이트는 여기서 `git pull --ff-only` 후 의존성을 다시 설치합니다.
- 기억: 기본 `~/ai-workspace-memory`. 개인 **비공개 GitHub 저장소**의 작업 사본입니다.
- 상태: 기본 `~/.local/share/ai-workspace-kit`. 원장·문서 색인·허용 경로·기기별 연결 정보가 있습니다.

상태는 Git 폴더 아래에 두지 마세요. 공개 코드 저장소 안에 기억이나 원본 문서를 넣지 마세요.
클라이언트별로 같은 상태 경로를 써야 같은 기억을 읽습니다. 여러 프로세스는 공통 잠금을 사용합니다.

## 2. GitHub 연결

`ai-workspace status`는 마지막 GitHub 게시 검증 시각과 짧은 commit, 현재 로컬 정제 이벤트 수,
미승격 checkpoint 수를 보여줍니다. `last_sync_verified`는 **그 당시의 게시 성공**이며 현재 원격을
실시간 조회한 결과가 아닙니다. `local_refined_updates_after_sync`라면 로컬 정제 기억이 마지막 게시
시점과 달라진 상태입니다. `prior_receipt_without_event_baseline`은 구버전 게시 기록으로 비교 기준이
없다는 뜻입니다. `sync` 후 새 게시 기록을 만드세요. 미승격 checkpoint는 자동 게시 대상이 아닙니다.
MCP의 `workspace_health`·`workspace_recall`에도 같은 `publication` 요약이 있습니다.


`gh`, `git`, `gitleaks`를 설치하고 `gh auth login`을 완료합니다.
아래 명령의 `YOUR_NAME/my-ai-memory`를 자신의 비공개 저장소 이름으로 바꾸세요.
설치 후 `ai-workspace init`을 이미 실행했다면 그대로 다음을 진행합니다.

```bash
cd "$HOME/ai-workspace-memory"
git init -b main
# Git 사용자 이름/이메일이 설정되어 있어야 합니다.
gitleaks dir . --no-banner --redact
git add .
git commit -m "Initialize private refined memory"
gh repo create YOUR_NAME/my-ai-memory --private --source . --remote origin --push
# 동기화는 HTTPS origin을 요구합니다. gh 설정이 SSH라면 아래처럼 통일합니다.
git remote set-url origin https://github.com/YOUR_NAME/my-ai-memory.git
ai-workspace bind-github YOUR_NAME/my-ai-memory
ai-workspace sync
```

위 `git add .`는 방금 초기화한 **기억 전용 폴더** 안에서만 실행합니다. 이미 요약을 넣었다면 생성된 `events/`, `memory/`, `daily/`도 함께 초기 commit에 포함되어야 합니다. 다른 파일을 그 폴더에 넣지 마세요.
초기 commit 전에 로컬 Markdown을 수동 수정하지 마세요. 생성 문서가 정제 이벤트와 달라지면 중단합니다.
`bind-github`는 저장소가 private인지, origin이 정확한지 확인하고 로컬 binding만 저장합니다.
`sync`도 매번 private 상태를 재확인합니다. public으로 바뀐 저장소에는 게시하지 않습니다.
`gitleaks`가 없거나 검사 실패·충돌이 있으면 게시를 중단합니다. 보안 검사를 우회하지 마세요.

### 두 번째 컴퓨터

먼저 이 코드 저장소와 Python 환경을 설치합니다. 기억 저장소를 별도로 clone합니다.
**이미 자료가 있는 clone에 `init`을 실행하지 마세요.**

```bash
git clone https://github.com/YOUR_NAME/my-ai-memory.git "$HOME/ai-workspace-memory"
ai-workspace bind-github YOUR_NAME/my-ai-memory
ai-workspace restore
ai-workspace recall '프로젝트 키워드'
```

`restore`는 원격 정제 이벤트로 로컬 원장을 복원합니다. 문서 경로와 SSD 등록은 기기별로 다시 합니다.
원격에 접근할 수 없는 동안 bound 상태의 쓰기는 중단됩니다. 데이터는 보존하고 연결 회복 뒤 재시도하세요.

## 3. 기록·승격·수정

`checkpoint`는 표준 입력으로 `examples/checkpoint.json` 형식의 요약을 받습니다.
MCP의 쓰기 도구는 동일 스키마를 받습니다. 접수와 GitHub 게시를 구분하세요.

- `session`, `checkpoint`: 안정적인 식별자. 재전송할 때 같은 값을 사용합니다.
- `stamp`: 시간대가 있는 실제 기록 시각. 미래 시각은 거절됩니다.
- `verified=true`: 확인한 내용만 저장합니다.
- `explicit_memory`: 사용자가 명시적으로 기억하라고 한 경우 true입니다.
- `memory.repo`: 연결된 프로젝트의 저장소 basename 또는 빈 문자열. 허용 목록은 기억 폴더의 `audit/repositories.json`에서 관리합니다.
- `completed_todo`: 완료가 확인된 기존 TODO의 정확한 문구만 넣습니다.
- 원문 대화, 코드 블록, 개인정보, 로컬 절대경로, 키/토큰은 요약에 넣지 않습니다.

최근 3일의 요약에서 명시적 기억 요청, 결정/TODO/업무 관련성, 프로젝트 연결,
여러 세션 반복 등의 신호를 사용합니다. Candidate는 추천 상태이며 새 GitHub 프로젝트를 자동 생성하지 않습니다.
이벤트는 불변입니다. 과거 JSON을 고치지 말고 새 checkpoint로 정정 이유와 현재 상태를 기록하세요.
현재 기본 렌더러의 일자 구분은 Asia/Seoul입니다.

## 4. 모델 호출 없는 유지 작업

```bash
ai-workspace tick
```

최근 체크포인트 승격, Markdown 갱신, 등록된 문서의 제한 시간 증분 검사,
GitHub 연결 시 기억 동기화만 수행합니다. 과거 채팅 전수 검사·LLM 요약은 하지 않습니다.
체크포인트가 없으면 새 대화 내용은 알 수 없습니다. MCP를 붙였다고 모든 대화가 자동 기록되지는 않습니다.

기존 예약 실행기에 10~30분 주기로 넣으세요. 새 scheduler를 중복 생성하지 않습니다.
예약 실행은 절대 실행 파일 경로, 동일 `--memory`·`--state`,
`PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin`을 사용하세요.
출력은 로컬 비공개 로그에 보관하고 정상 실행마다 알림을 보내지 않는 구성을 권장합니다.
macOS launchd/systemd의 설치·부팅 자동 실행은 이 미리보기에서 자동 구성하지 않습니다.

## 5. 원본 검색·SSD

`allow-root`는 지정 폴더만 등록합니다. SSD 폴더는 연결된 상태에서 등록해야 합니다.
macOS 외장 볼륨은 UUID와 디렉터리 식별자를 확인합니다. 경로만 같은 다른 디스크는 거절합니다.
`index --budget 10`은 10초 예산으로 수행하므로 큰 폴더는 반복 실행하여 초기 색인을 완료하세요.
이후 디렉터리 순회 위치와 파일 지문으로 변경된 내용을 갱신합니다. 무변경 파일 본문은 매번 재추출하지 않습니다.

JSON/JSONL은 파싱 후 본문 검사, DOCX는 내부 문서 XML, PDF는 로컬 `pdftotext`를 사용합니다.
숨김 파일·인증 파일·패키지·캐시·시스템 폴더·심볼릭 링크를 제외합니다.
필터는 완전한 개인정보 탐지기가 아닙니다. 허용 폴더 자체에 공유해도 되는 자료만 넣으세요.

| 응답 | 의미와 조치 |
|---|---|
| `external_ssd_disconnected` / `root_unavailable` | 디스크·폴더를 연결한 후 재시도 |
| `source_unavailable` | 원본 삭제·이동 여부 확인; 실제 위치를 허용하고 재색인 |
| `root_identity_changed` / `volume_identity_changed` | 폴더·디스크가 교체됨; 원본 확인 후 로컬 등록을 다시 구성 |
| `source_changed` 등 stale 결과 | 재색인·재검색 후 새 ID로 읽기 |
| `workspace_busy` | 다른 실행이 잠금 사용 중. 잠금을 삭제하지 말고 다음 실행에서 재시도 |
| `artifact_request_rejected` | 허용 경로·파일 형식·추출 도구 점검 |
| 검색 결과 없음 | 검색어를 줄이고 인덱스 범위·색인 결과를 확인. 파일 부재의 증거로 단정하지 않음 |

CLI 결과 JSON의 status/ok와 실제 `text`를 확인하세요. 검색의 excerpt는 원본 읽기 성공이 아닙니다.
긴 문서는 read의 offset/limit로 필요한 구간을 추가 확인합니다.

## 6. 충돌과 복구

`generated_manual_edit`: 생성 Markdown을 수동 수정했을 수 있습니다. 수정본을 비공개 별도 폴더에
먼저 보존하고, 의도한 변경을 새 checkpoint로 옮기세요. `reset --hard`로 자동 해결하지 않습니다.
`diverged_history`: 여러 기기에서 동시 commit한 상태입니다. 양쪽을 보존한 뒤 Git 이력과 불변 이벤트를
검토해야 합니다. 강제 push·자동 덮어쓰기를 하지 않습니다.
`secret_scan_blocked`: 입력·이력에서 보안 검사 문제가 발견됐습니다. 키가 실제 노출됐다면 먼저 폐기·교체하고
이력 정리는 따로 판단하세요. 검사 출력을 공개 Issue에 통째로 붙이지 마세요.

삭제/재설치 전 원본, private GitHub 최신 commit, 로컬 미게시 요약을 구분해 보관하세요.
원본은 이 프로그램이 삭제하지 않습니다. 색인은 다시 만들 수 있지만 미게시 Warm 요약은
로컬 원장에만 있을 수 있습니다. 상태 폴더를 통째로 Git에 올려 백업하지 마세요.

## 7. 정지·재시작

stdio MCP는 클라이언트 연결을 종료하면 멈춥니다. 로컬 파일·DB는 유지됩니다.
터널은 [CLIENTS.md](docs/CLIENTS.md)의 별칭으로 중지합니다. 수동 tick은 한 번 실행 후 종료합니다.
예약 실행을 추가했다면 해당 소유 예약기에서 중지해야 합니다. 삭제와 서비스 중지는 다른 동작입니다.

## 8. 고급 기능 경계

`workspace/history.py`는 Codex JSONL 및 네이티브 DB용 읽기 전용 과거 검색 엔진입니다.
기본 CLI/tick은 이를 호출하지 않습니다. 네이티브 스키마는 제품 버전에 따라 달라질 수 있으므로,
별도 동의를 받은 범위와 테스트된 스키마에만 연결하세요. 원본 DB를 수정하거나 Git에 업로드하지 않습니다.
`runtime.py`의 legacy 수집/요약 함수와 `alerts.py`는 기존 엔진 호환용이며 공개판 기본 진입점에서 호출하지 않습니다.
