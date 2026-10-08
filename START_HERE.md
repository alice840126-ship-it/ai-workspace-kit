# AI Workspace Local Search — 받는 분의 시작 안내

Mac의 로컬 폴더·Obsidian·연결된 외장 SSD 파일을 AI에서 검색하고 읽고 수정하는 MCP(도구 연결 규약) 서버입니다. 배포본에는 소스·테스트·합성 예제만 있습니다. 보내는 사람의 계정, 파일, 기억, 인증 키와 터널은 들어 있지 않습니다.

## 1. 설치

macOS와 Python 3.11 이상이 필요합니다. Windows 네이티브는 지원하지 않습니다. Linux는 이 배포에서 실기 검증하지 않았습니다. Codex가 없어도 설치할 수 있습니다.

ZIP을 풀거나 아래 공개 저장소를 복제한 뒤 그 폴더에서 실행합니다. `KIT_PYTHON`은 **자신이 설치하고 확인한 Python의 절대경로**로 바꾸세요. 예시 경로가 실제로 없으면 설치한 Python 경로를 먼저 확인하세요.

```bash
git clone https://github.com/alice840126-ship-it/ai-workspace-kit.git
cd ai-workspace-kit
KIT_PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
"$KIT_PYTHON" --version
"$KIT_PYTHON" -m venv .venv
./.venv/bin/python -m pip install .
./.venv/bin/ai-workspace-files-check
```

이미 `.venv`가 있는 폴더에 덮어 설치하지 말고 새 배포 폴더를 사용하세요. 마지막 명령은 임시 파일에서 **17개 도구 노출 → 생성 → 수정 → 실제 읽기 → 오래된 버전 거부 → 삭제 → 복구**를 확인하고 임시 파일을 정리합니다. `ok: true`는 로컬 MCP 시험 통과이며 ChatGPT 연결 성공을 뜻하지 않습니다.

파일 관리만 쓸 때 GitHub 개인 기억 저장소 초기화는 필요 없습니다. 기억 기능은 [README](README.md)의 별도 절차로 설정합니다.

## 2. 실행할 서버 명령

```text
/absolute/ai-workspace-kit/.venv/bin/ai-workspace-mcp --state /absolute/private-state --read-only --filesystem
```

두 경로를 본인 Mac의 실제 절대경로로 바꾸세요. 상태 폴더는 Git 밖의 비공개 로컬 폴더(예: 사용자 홈의 `.local/share/ai-workspace-files`)로 지정합니다. 설치 폴더 안에 두지 않습니다.

**`--filesystem`이 파일 쓰기 도구를 켭니다. `--read-only`는 기억 checkpoint 쓰기만 끕니다. 두 옵션을 함께 쓰면 파일 쓰기는 활성 상태입니다.** 파일을 읽기 전용으로 제한하려면 `--filesystem`을 빼고 기존 색인 검색·읽기만 연결하세요.

Codex/Aside 등 로컬 MCP 클라이언트에는 위 실행 파일과 인자를 등록합니다. 다른 사람의 설정 파일 전체를 복사하지 마세요.

## 3. ChatGPT 연결

ChatGPT에서 로컬 서버에 접근하려면 본인 계정의 **Secure MCP Tunnel(인증된 연결 통로)**이 필요합니다. 사용 가능 여부와 메뉴는 계정·조직 정책에 따라 다릅니다. 키나 계정을 이 ZIP으로 공유하지 않습니다.

1. [공식 설치 안내](https://github.com/openai/tunnel-client)에 따라 `tunnel-client`를 설치합니다.
2. [Platform Tunnels](https://platform.openai.com/settings/organization/tunnels)에서 본인 ChatGPT 작업공간에 연결된 터널을 준비합니다. [공식 운영 안내](https://github.com/openai/tunnel-client/blob/master/docs/end-user-guide.md)에 따라 실행 키에 Tunnels Read + Use 권한을 부여합니다. 관리용 키를 상시 실행에 사용하지 않습니다.
3. 키는 본인의 비공개 환경/키 저장소에서 `CONTROL_PLANE_API_KEY`로 주입합니다. 키를 명령문·문서·ZIP·Git에 적지 않습니다.
4. 아래 경로와 `YOUR_TUNNEL_ID`를 자신의 값으로 바꿔 실행합니다. 공백이 없는 설치 경로를 권장합니다.

```bash
tunnel-client runtimes connect \
  --alias ai-workspace-files \
  --profile ai-workspace-files \
  --profile-dir /absolute/private-tunnel-profiles \
  --tunnel-id YOUR_TUNNEL_ID \
  --runtime-api-key env:CONTROL_PLANE_API_KEY \
  --mcp-command '/absolute/ai-workspace-kit/.venv/bin/ai-workspace-mcp --state /absolute/private-state --read-only --filesystem'
tunnel-client runtimes status ai-workspace-files --json
```

5. ChatGPT의 사용자 MCP 연결 화면에서 **동일한 터널**을 연결하고 도구 목록을 새로고침합니다. `local_file_create`, `local_file_edit`, `local_file_read`가 실제로 보여야 합니다. [공식 ChatGPT 연결 안내](https://developers.openai.com/plugins/deploy/connect-chatgpt)를 참고하세요.
6. 새 채팅에서 아래 실사용 시험을 합니다. 자신의 임시 폴더 절대경로를 넣으세요.

```text
연결된 AI Workspace 도구로 /본인의/임시폴더/mcp-test.txt를 "첫 번째" 내용으로 만들어줘.
읽은 현재 버전을 사용해 "두 번째"로 수정하고, 다시 읽어 실제 저장 내용을 검증해줘.
호출한 도구명과 검증 결과를 보여줘. 파일이 이미 있으면 덮어쓰지 말고 알려줘.
```

도구가 읽기 전용 네 개만 보이면 실행 명령의 `--filesystem`과 ChatGPT 도구 새로고침을 확인합니다. 연결 화면에 등록됐다는 사실만으로 파일 쓰기 성공으로 판단하지 마세요.

## 4. 접근 범위와 macOS 권한

특정 업무 폴더 화이트리스트는 없습니다. 실행 사용자에게 OS가 허용한 일반 파일·폴더를 절대경로로 다룹니다. SSD가 연결되고 마운트되어 있어야 합니다. 기존 `search_local` 색인 기능의 허용 폴더 설정은 별도로 유지됩니다.

macOS가 접근을 거부하면 시스템 설정 → 개인정보 보호 및 보안에서 실제 실행 앱/프로그램의 **파일 및 폴더**, 필요 시 **전체 디스크 접근 권한**을 직접 확인하세요. 관리자 권한 상승·보안 우회는 하지 않습니다. 권한을 준 뒤 실행 프로그램을 재시작하고 같은 파일을 다시 읽어 검증하세요. 읽기 전용 볼륨, 파일 소유권, 분리된 SSD 문제는 전체 디스크 접근만으로 해결되지 않습니다.

파일 원문과 경로는 호출한 AI 서비스로 전달됩니다. 신뢰하는 계정과 클라이언트에만 연결하세요. 도구의 범위·복구 한계는 [파일 도구 설명](docs/FILESYSTEM.md)에 있습니다.

## 5. 재부팅·연결 끊김

`Tunnel-client has not been seen for 300 seconds`가 나오면 Mac의 터널 프로세스가 연결되어 있는지 확인합니다. Mac 전원·네트워크·잠자기·키 만료를 점검하고 `runtimes status`를 확인한 뒤 위 `runtimes connect`로 재연결합니다. 로컬 점검 성공 후 ChatGPT에서 실제 읽기를 다시 호출하세요.

**이 키트는 로그인 자동실행을 설치하지 않습니다.** 재부팅 후 본인 키를 다시 주입하고 터널을 연결해야 할 수 있습니다. 상시 운영하려면 본인 환경의 로그인 실행 서비스에 위 명령을 등록하고, 키는 안전한 저장소에서 읽게 구성해야 합니다. plist에 키를 직접 넣지 않습니다. 설치 경로·키 저장 방식이 사람마다 달라 개인 운영 설정은 배포하지 않습니다. 자동실행을 설정했다면 실제 로그아웃/로그인 또는 재부팅 뒤 ChatGPT 호출까지 별도 시험하세요.

정지할 때는 `tunnel-client runtimes stop ai-workspace-files`를 사용합니다. 상태 폴더나 `.ai-workspace-recovery-*`를 삭제하면 복구 자료가 사라질 수 있으므로 일반 정리 대상으로 지우지 마세요.
