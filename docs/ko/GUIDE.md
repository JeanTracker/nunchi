# nunchi 설치·사용·삭제

nunchi는 iTerm2 패널 하나에 띄워 두고, 다른 패널에서 도는 Claude Code 세션들의 상태와 대화를 보면서 그 자리에서 다음 지시를 보내는 터미널 앱입니다. 설치와 삭제는 `install.sh` 하나로 합니다.

macOS, iTerm2, 파이썬 3.11 이상, git이 있어야 합니다. 분석 기능(목표·빠진 요청·요약)은 PATH에 있는 `claude` 명령을 씁니다.

## 설치

저장소가 공개되어 있으면 한 줄로 끝납니다.

```sh
curl -fsSL https://raw.githubusercontent.com/JeanTracker/nunchi/main/install.sh | sh
```

지금은 저장소가 비공개라서 위 주소는 404를 돌려줍니다. 저장소 권한이 있는 계정으로 받아서 그 폴더에서 실행하세요.

```sh
git clone https://github.com/JeanTracker/nunchi.git
cd nunchi
./install.sh
```

두 방법의 차이는 소스 위치뿐입니다. curl로 설치하면 `~/.local/share/nunchi`에 내려받고, 받아 둔 저장소에서 `./install.sh`를 실행하면 그 폴더에 그대로 설치합니다. 나머지는 같습니다.

1. 저장소 안에 `.venv`를 만들고 `textual`을 설치합니다.
2. `~/.local/bin/nunchi`를 저장소의 `bin/nunchi`에 링크합니다.
3. `~/.local/bin`이 PATH에 없으면 셸 설정 파일(zsh면 `~/.zshrc`)에 `# >>> nunchi >>>` ~ `# <<< nunchi <<<` 블록으로 넣습니다. 이 블록 밖은 건드리지 않습니다.
4. Claude Code 훅과 상태 표시줄을 `~/.claude/settings.json`에 등록합니다. 바뀔 내용을 diff로 먼저 보여주고 `적용할까요? [y/N]`로 묻습니다. 적용하면 같은 폴더에 `settings.json.bak-날짜시각` 백업이 생깁니다.

원래 쓰던 상태 표시줄은 그대로 보입니다. nunchi가 그 명령을 감싸서 컨텍스트 사용률만 따로 기록합니다.

curl 한 줄이나 `~/.local/share/nunchi/install.sh`를 다시 실행하면 갱신입니다. 내려받은 폴더를 `git pull`하고 의존성을 다시 맞추며, 이미 등록된 훅은 건드리지 않습니다. 그 폴더에 고친 파일이 있으면 갱신하지 않고 그대로 씁니다. 직접 받아 둔 저장소는 `git pull` 후 `./install.sh`를 다시 실행하세요.

옵션은 curl로 받을 때 `sh -s --` 뒤에 씁니다. 예를 들어 묻지 않고 설치하려면:

```sh
curl -fsSL https://raw.githubusercontent.com/JeanTracker/nunchi/main/install.sh | sh -s -- --yes
```

- `--no-hooks`: 훅 등록만 건너뜁니다. 나중에 `install.sh --hooks`로 등록합니다.
- `--link`, `--path`: 명령 링크만, PATH만 다시 맞춥니다.
- `--yes`: 확인 질문 없이 진행합니다. `~/.claude/settings.json` 변경도 포함됩니다.

설치 위치는 `NUNCHI_HOME`(내려받을 폴더), `NUNCHI_BIN`(명령 폴더), `NUNCHI_RC`(셸 설정 파일)로 바꿀 수 있습니다. 전체 목록은 `./install.sh --help`에 있습니다.

> 개발 폴더와 설치 폴더 양쪽에서 훅을 등록하면 이벤트가 두 번 기록됩니다. 설치 스크립트가 이 경우 경고를 띄우니, 한쪽에서 `python3 scripts/install_hooks.py --remove --apply`로 빼세요.

## 처음 켜기

iTerm2에서 패널을 하나 나누고 `nunchi`를 실행합니다. 새 터미널을 열기 전이라 명령을 못 찾으면 `source ~/.zshrc`를 먼저 하세요.

```sh
nunchi
```

다른 패널에서 Claude Code를 켜면 화면 위쪽 세션 목록에 나타납니다. nunchi를 설치하기 전부터 열려 있던 세션은 "연결 대기"로 보입니다. 훅은 세션이 시작될 때 읽히므로 그 세션을 한 번 종료하고 다시 시작해야 연결됩니다.

처음으로 지시를 보낼 때 macOS가 iTerm2 제어를 허락할지 물을 수 있습니다. 허용해야 nunchi가 패널에 글을 입력할 수 있습니다.

## 세션 안 화면(mod) 붙이기

mod는 Claude Code 세션 화면 옆에 눈치 패널을 띄우는 플러그인입니다. 지금 에이전트가 나에게 묻는 것, 지금까지의 목표와 정한 것, 내 요청 중 남은 것을 보여 줍니다. mod는 분석하지 않고 분석 결과를 읽기만 합니다. 분석은 응답이 끝날 때 훅이 깨우는 백그라운드 분석기가 하므로, nunchi(관제) 화면을 켜지 않아도 됩니다. 분석기는 할 일이 있을 때만 돌고 끝나면 스스로 멈춥니다. 이름이 `~/.claude/skills` 폴더에 들어가지만 스킬은 아닙니다. 모델이 읽는 지시문이 없어서 대화에 더해지는 토큰도 없습니다.

Claude Code 2.1.322에서 확인했습니다. 저장소 자체가 플러그인 마켓플레이스(`.claude-plugin/marketplace.json`)이고, 플러그인은 `mod/nunchi`입니다.

**설치 (권장).** Claude Code 안에서 실행합니다. 마켓플레이스 등록과 플러그인 설치가 한 번에 됩니다.

```
/plugin install nunchi --marketplace JeanTracker/nunchi
```

터미널에서는 두 단계로 같은 일을 합니다.

```sh
claude plugin marketplace add JeanTracker/nunchi
claude plugin install nunchi@nunchi
claude plugin list                                   # nunchi@nunchi · enabled 가 보이면 됩니다
```

Claude Code가 플러그인을 따로 받아 두므로, 받아 둔 저장소 폴더를 옮기거나 지워도 영향이 없습니다. 새 세션부터 붙고, 열려 있는 세션에서는 `/reload-plugins`를 칩니다. 플러그인은 훅을 등록하거나 분석기를 설치하지 않으므로 분석에는 여전히 `install.sh`가 필요합니다. 저장소가 비공개인 동안에는 마켓플레이스를 받을 때 그 저장소에 대한 git 권한이 있어야 합니다.

**갱신.** `claude plugin marketplace update nunchi` 다음 `claude plugin update nunchi@nunchi`를 하고 세션을 다시 시작합니다.

예전에 `~/.claude/skills/nunchi`로 복사해 두었다면 그 복사본은 지우세요(`rm -rf ~/.claude/skills/nunchi`). 설치된 플러그인이 앞서므로 복사본은 "이름이 이미 있음"으로 붙지 않습니다.

**한 번만 붙이기.** 설치 없이 그 세션에만 폴더를 붙이려면 옵션으로 줍니다. 이미 열린 세션은 닫고 `--resume`으로 다시 열 때 붙입니다. 고치는 중인 mod를 시험할 때 씁니다.

```sh
claude --plugin-dir ~/.local/share/nunchi/mod/nunchi
claude --resume <세션 ID> --plugin-dir ~/.local/share/nunchi/mod/nunchi
```

**눈치 켜기.** 플러그인이 붙어 있어도 모든 세션을 분석하지는 않습니다. 흐름을 보고 싶은 세션에서 `/nunchi`를 치면 그 세션이 분석 대상이 되고 패널이 열립니다. 그 뒤로는 응답이 끝날 때마다 분석되고, 세션을 다시 열어도 켜진 채로 남습니다. 켜기 전 응답은 다음 응답이 끝날 때 처음부터 한꺼번에 분석합니다. 켜지 않은 세션에서는 패널이 열리지 않습니다. 다만 nunchi(관제)에서 고른 세션은 지금처럼 분석되고, 분석 결과가 있으면 패널도 열립니다.

창이 넓을 때(110칸 이상) 오른쪽에 패널이, 좁을 때는 입력창 위에 한 줄이 뜹니다. 패널 폭은 창의 40%이고 `~/.claude-control/config.json`의 `mod_width_ratio`로 바꿉니다. 분석을 기다리는 중이면 "분석 대기...", 도는 중이면 "분석 중...", 실패하면 "분석 실패 · 이유"가 보입니다.

**amask와 함께 쓰기.** amask는 세션을 열 때 자기 훅(`--settings`)과 자기 mod(`--plugin-dir`)를 명령줄에 덧붙입니다. 눈치 mod와 이름이 다르고, 붙잡는 이벤트도 겹치지 않으며(amask mod는 턴 끝만 받고 화면을 그리지 않음), 눈치 훅은 `~/.claude/settings.json`에 있어 함께 불립니다. 그래서 플러그인으로 설치하든 `--plugin-dir`로 붙이든 amask 아래에서 그대로 씁니다. 다만 `claude --settings …`처럼 직접 `--settings`를 주면 amask가 자기 훅과 mod를 끕니다(amask의 동작이며 눈치는 영향받지 않음).

**떼기.** 플러그인을 지우고 마켓플레이스를 뺍니다. 열려 있던 세션은 다시 시작하면 mod 없이 돕니다.

```sh
claude plugin uninstall nunchi@nunchi
claude plugin marketplace remove nunchi
```

## 화면과 키

화면은 세 구역입니다. 가로 140칸 이상이면 세션 목록이 왼쪽, 대화가 오른쪽에 놓이고, 좁으면 위아래로 쌓입니다. 입력줄은 항상 맨 아래입니다.

**세션 목록.** 응답이 먼저 도착한 세션이 위로 올라옵니다. 줄마다 상태(작업·응답·허락·질문·대기·종료)와 남은 요청 수(`⚠1`)가 붙습니다. 도구 이름은 보이지 않습니다. ↑↓로 고릅니다.

**대화.** 고른 세션의 목표 흐름(처음 → 주제가 옮겨 간 턴 → 지금)과, 지금까지 보낸 요청 중 아직 다루지 않았거나 에이전트가 못 했다고 한 것이 맨 위에 고정되고, 그 아래로 대화가 시간순으로 흐릅니다. 오래된 대화는 10턴씩 한 줄로 묶이고 마지막 대화는 응답 원문 전체가 보입니다.

- ↑↓ 턴 고르기, Enter 묶음이나 턴 펼치기
- `d` 응답 상세 화면(요청·최종 응답·에이전트가 중간에 한 말), Esc로 돌아오기, ←→ 이전·다음 턴
- `c` 쌓인 요청 전체(아직 다루지 않음·못 했거나 미룸·다룸·뒤 요청이 대신함), Enter로 그 요청의 턴으로, c나 Esc로 닫기
- `o` 원문 펼치기, `s` 마지막 응답을 요약으로 보기
- End(또는 `]`) 마지막 대화로, Home(또는 `[`) 맨 위로, PgUp/PgDn 스크롤

**입력줄.** `i`나 `:`로 들어가서 쓰고 Enter로 보내면, 고른 세션 패널에 직접 친 것처럼 입력됩니다. 세션이 일하는 중이면 대기열에 넣었다가 응답이 끝나면 보냅니다. 세션이 허락을 기다리면 글자 입력을 막고 `y`(허용) 또는 `n`(거절)만 받습니다. 엉뚱한 선택지가 눌리지 않게 하려는 것입니다.

세션이 선택지 질문 창을 띄우고 기다리면 목록에 `? 질문`으로 보이고, 대화 칸에 질문과 지금까지 고른 답이 나옵니다. `i`로 입력줄에 들어가면 입력칸 대신 선택지가 펼쳐집니다. 숫자나 ↑↓·Enter로 고르고, 여러 개 고르는 질문은 Space로 켜고 끈 뒤 Enter로 넘어갑니다. 모두 고르면 보낼 답을 한 번 더 보여 주고, Enter를 누르면 패널에 질문 창이 아직 있는지 확인한 뒤 답을 보냅니다. 직접 글로 쓰는 답은 아직 패널에서 해야 합니다. 질문에는 `y`/`n`이 동작하지 않습니다.

- 줄바꿈은 Shift+Enter, Option+Enter, Ctrl+J
- `/`로 시작하면 Claude Code 명령과 스킬 목록이 뜨고 Tab으로 채웁니다
- ↑↓ 보낸 글 기록, Shift+Tab 세션의 권한 모드 바꾸기, PgUp/PgDn은 입력 중에도 대화를 스크롤합니다

입력줄 밖에서는 Tab으로 세 구역을 옮겨 다니고, `q`나 Ctrl+Q로 끕니다. 한글 입력 상태에서도 같은 자리의 키가 동작합니다(ㅂ=q, ㅇ=d처럼). `p`(고른 세션 패널로 이동)는 아직 만들지 않았습니다.

### 분석 비용 줄이기

목표 흐름·요약·요청 기록은 세션이 응답을 끝낼 때마다 새 턴 하나에 `claude -p`를 한 번씩 불러서 만듭니다. 그만큼 사용량이 듭니다. `~/.claude-control/config.json`을 만들어 조절하세요.

```json
{
  "analyze_scope": "selected",
  "analyze_when": "auto",
  "analyze_model": "",
  "analyze_max_turns": 60,
  "analyze_workers": 1,
  "latest_view": "full",
  "theme": "graphite"
}
```

`analyze_scope`를 `"off"`로 두면 분석을 끄고, `"all"`로 두면 모든 세션을 분석합니다. 기본값 `"selected"`는 지금 고른 세션만 분석합니다. `analyze_when`을 `"manual"`로 바꾸면 `a`를 눌렀을 때만 돕니다. 한 번만 끄고 켜려면 `CONTROL_TUI_ANALYZE=0 nunchi`로 실행합니다.

분석은 nunchi 화면 밖의 백그라운드 분석기가 합니다. 분석 대상은 nunchi에서 고른 세션과 `/nunchi`로 켠 세션입니다(`"all"`이면 모든 세션). `analyze_workers`는 분석을 동시에 몇 개까지 돌릴지입니다(1 또는 2, 기본 1). 여러 세션이 한꺼번에 응답을 끝내면 고른 세션부터, 그다음은 최근 응답부터 차례로 분석합니다. 2로 올리면 기다림이 줄지만, 분석도 같은 계정의 사용량을 쓰므로 그만큼 한꺼번에 몰립니다. nunchi를 꺼도 돌던 분석은 끝까지 갑니다.

`theme`은 화면 색입니다. `graphite`(기본), `midnight`, `polar`, `forest`, `dusk`, `contrast`(고대비), `paper`(밝은 바탕) 중 하나를 씁니다. 실행 중에는 Ctrl+P → 테마 바꾸기로 바로 바꿔 볼 수 있습니다(이때 바꾼 것은 저장되지 않습니다).

## 삭제

```sh
~/.local/share/nunchi/install.sh --uninstall   # curl로 설치했을 때
./install.sh --uninstall                       # 받아 둔 저장소에서 설치했을 때
```

내려받은 폴더가 이미 지워졌어도 curl 형태로 남은 것을 정리할 수 있습니다. 설치 때와 마찬가지로 저장소가 공개된 뒤에만 됩니다.

```sh
curl -fsSL https://raw.githubusercontent.com/JeanTracker/nunchi/main/install.sh | sh -s -- --uninstall
```

삭제는 설치의 역순입니다. 먼저 `~/.claude/settings.json`에서 nunchi 훅을 빼고 상태 표시줄을 원래 명령으로 되돌립니다. 이때도 diff를 보여주고 묻고, 백업을 만듭니다. 이 단계를 거절하거나, 다른 도구가 상태 표시줄을 다시 감싸 놓아 되돌리지 못하면 나머지를 지우지 않고 멈춥니다. 훅만 남은 채 파일이 사라지면 모든 Claude Code 세션이 없는 파일을 부르게 되기 때문입니다.

그다음 `~/.local/bin/nunchi` 링크와 셸 설정 파일의 nunchi 블록을 지우고, curl로 내려받은 폴더를 지웁니다. 그 폴더에 고치거나 새로 만든 파일이 있으면 지우지 않고 알려 줍니다. 직접 받아 둔 저장소는 남기고, 설치 때 만든 `.venv`만 지웁니다.

세션 기록과 설정 파일이 있는 `~/.claude-control`은 남깁니다. 필요 없으면 nunchi를 끈 뒤 지우세요.

```sh
rm -rf ~/.claude-control
```

열려 있던 Claude Code 세션은 다시 시작하면 훅 없이 돕니다. `install.sh --uninstall`은 플러그인을 지우지 않으니 위 "떼기"대로 따로 지우세요.

폴더를 먼저 지워 버려서 훅이 남았다면, 같은 위치에 다시 설치한 뒤 `--uninstall`을 실행하면 깨끗하게 빠집니다. 다른 위치에 설치했다면 settings.json에서 `hooks/emit.py`와 `hooks/statusline.py`가 들어간 항목을 직접 지워야 합니다.
