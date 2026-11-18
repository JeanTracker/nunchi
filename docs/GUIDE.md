# nunchi guide

nunchi is a Claude Code plugin that adds a side panel to a session. When you come back to
a session after a while, the panel shows where things stand: the current goal and how
the conversation got there, the decisions you made, what the agent is asking you, and
which of your requests are still open. You read that, answer, and carry on.

The panel only reads analysis results. A small engine that ships with the plugin records
each session's events through Claude Code hooks and, when a response ends, analyzes the
new turn in the background with `claude -p`.

한국어 안내: [docs/ko/GUIDE.md](ko/GUIDE.md)

## What you need

- macOS (Apple silicon or Intel) or Linux (x86_64 or arm64). Windows is not supported.
  The plugin ships a native engine for each of these and picks the one for your machine,
  so installing is the same everywhere and no Python is needed. On Linux the engine
  passes its tests in CI, but it has not yet been tried in a live session.
- Claude Code. Tested with 2.1.322 to 2.1.325.
- The `claude` command on the PATH of the shell you start Claude Code from. The analyzer
  calls `claude -p` once per new turn on your account's quota (see "Analysis cost").
- While the repository is private, git access to it, to add the marketplace.

## Install

Run this inside Claude Code. It adds the marketplace and installs the plugin in one step:

```
/plugin install nunchi --marketplace JeanTracker/nunchi
```

From a terminal, the same in two steps:

```sh
claude plugin marketplace add JeanTracker/nunchi
claude plugin install nunchi@nunchi
claude plugin list                                   # look for nunchi@nunchi · enabled
```

The plugin brings the panel, the hooks that record each session into
`~/.claude-control`, and the engine. It adds no hook entries to `~/.claude/settings.json`
(Claude Code itself records the marketplace and the enabled plugin there), and it adds no
tokens to the conversation.

Claude Code keeps its own copy of the plugin. New sessions pick it up; restart a session
that is already open (`claude --resume <session ID>`). Hooks are read when a session
starts, so a session opened before the install is not recorded until it restarts.

**Update.** `claude plugin marketplace update nunchi`, then
`claude plugin update nunchi@nunchi`, and restart your sessions. Each version lives in its
own folder, so sessions already open, and analyses already running, finish on the old one.

If you copied the mod into `~/.claude/skills/nunchi` earlier, delete that copy
(`rm -rf ~/.claude/skills/nunchi`). The installed plugin takes precedence and the copy is
reported as "already taken" and not loaded.

## Turning nunchi on

Having the plugin installed does not analyze every session. Type `/nunchi` in a session
whose flow you want to follow. That session becomes an analysis target and the panel
opens. From then on it is analyzed after every response, and it stays on when you reopen
the session. Responses from before you turned it on are analyzed together, from the
start, when the next response ends.

The panel does not open on its own in sessions you have not turned on. Turning it off
again (`/nunchi off`) is not built yet.

## Language

The panel's labels come in Korean and English. By default they follow Claude Code's
language setting (`/config`, the response language): Korean when it is Korean, English
otherwise. With no setting, the terminal's `LANG` decides. The first session after you
install tells you once which language it picked.

To change it, type `/nunchi language` and pick `한국어`, `English` or
`Claude Code 설정 따르기` (follow the Claude Code setting). The panel switches right away,
in every open session. Press Esc to leave it as it is.

The summaries in the panel (goal, flow, decisions, questions, requests) are written by
the analysis, in the language picked when the session is first analyzed. A session keeps
that language so its summaries never mix; new sessions use the new choice. If Claude Code
is set to another language, such as Japanese, the labels are in English and the
summaries in that language (only Korean and English are tested). Quoted words are always
shown as they were said. When a session was analyzed in a different language from the
one you picked, a line under the header says so.

If you pick a language while the current session was analyzed in another one, a second
question follows: `그대로 두기` (keep it; new sessions use the new language) comes first,
then `지금 다시 분석` (rebuild now). Rebuilding analyzes the whole session again from the
first turn, one `claude -p` call per turn, and the header reads `흐름 처음부터 만드는 중
#k/#n` (rebuilding from the start) until it is done. The previous result is kept as
`analysis.prev.json` in the session folder until the rebuild finishes. To rebuild later,
run `/nunchi language` again and pick the same language.

## What the panel shows

The panel opens on the right when the window is 110 columns or wider and takes 40% of
the window. In a narrower window a single line appears above the input box instead:
`눈치 목표: … · 질문 n · 요청 n · #n 기준` (goal, the agent's open questions, your open
requests, analysis basis). The labels below are the Korean ones, with the English panel's
wording in parentheses, from top to bottom.

**Header.** `눈치 · #12 기준` means the results are based on turn 12. Next to it you may
see:

- `분석 대기...` (queued) or `분석 중...` (analyzing)
- `흐름 처음부터 만드는 중 #3/#12` (building the flow from the start) or `밀린 턴 반영 중`
  (catching up on turns), with progress
- `응답 2개 밀림`: two responses arrived since the last analysis
- `분석 실패 · <reason>` (analysis failed); it is retried a limited number of times
- `자동 분석 꺼짐 · /nunchi로 켜기`: the session has old results but is not turned on

Before the first result the panel shows `눈치 켜짐 · 다음 응답이 끝나면 분석합니다`
(on; analysis starts when the next response ends).

**목표 (goal).** What the conversation is working on now, and from which turn
(`#10부터`). Two dimmed lines follow, because they are the analyzer's estimate:

- `흐름` (flow): one paragraph on how the conversation has gone from the start.
- `방금` (just now): the agent's summary of the last turn.

**의사결정 (decisions).** Decisions you made, marked ✔, newest first: what you decided in
one line (or a short title when the analyzer wrote none), and the turn it was made in.
The wording is the analyzer's summary, so the turn number lets you check it in the
conversation. The section is left out when there are none.

**에이전트 질문 (the agent's questions).** Decisions, confirmations or information the
agent is waiting on, newest first. Each item has a number, a one-line summary, the turn it
was asked in, and the agent's own words in quotes. `#5부터 답 없음` means it has gone
unanswered since turn 5; `일부 답함` means partly answered. An item closes when one of
your messages answers it. Items closed by a blanket approval such as "go ahead as you
suggest" are counted separately (`통째 승인으로 닫은 것`). In a short panel this section
may sit below the visible area; scroll the panel to reach it.

**남은 요청 (open requests).** Your requests that are not done yet: ○ not handled, ◐ in
progress (for example a merge request waiting for review), ⊘ the agent could not do it or
deferred it. Each shows the turn it came from.

**More and collapse.** Decisions, questions and open requests show three items each. When
a list has more, its last line reads `… n개 더` (n more): click it to open the whole list,
and the same line then reads `접기` (Collapse) and takes it back to three. What you open
stays open while you work in that session, even as new analysis results come in; each
session keeps its own, and a new session starts with three.

The goal, the flow summary and the last step show two lines each, so the lists below
stay on the first screen.

**번호 풀이 (numbers explained).** When the last response cites plan numbers such as R17,
§4.5, Phase 4c or 요구 이력 41, the panel looks them up in the project's `docs/*.md` and
shows the original wording, up to five. This only works for documents written in that
table and heading style.

Links in the panel (bare URLs and Markdown links) can be clicked.

## Analysis cost

Each new turn of a turned-on session costs one `claude -p` call, run by the engine
outside your session; it does not add to the session's context. Settings live in
`~/.claude-control/config.json`:

```json
{
  "analyze_scope": "selected",
  "analyze_model": "",
  "analyze_workers": 1,
  "mod_width_ratio": 0.4
}
```

- `analyze_scope`: `"off"` stops all analysis. `"all"` analyzes every session, turned on
  or not. The default analyzes only sessions turned on with `/nunchi`.
- `analyze_model`: the model for analysis; empty uses the `claude` default.
- `analyze_workers`: how many analyses may run at once (1 or 2). They share your
  account's quota.
- `mod_width_ratio`: panel width as a share of the window (0.2 to 0.45).

When several sessions finish at once, the most recent responses go first. The engine
starts only when there is work and exits when the queue is empty.

## When something is off

- **The panel never fills in.** Check that the session was started after the plugin was
  installed, and that `claude` runs from that shell. Errors are logged to
  `~/.claude-control/errors.log`.
- **A message at session start says the engine could not run.** Update or reinstall the
  plugin (`claude plugin update nunchi@nunchi`) and restart the session.
- **Using it with amask.** amask adds its own hooks and mod when it opens a session. The
  two mods have different names and listen to different events. A session under amask
  with nunchi's hooks in the plugin has not been checked yet.

## Removing it

```sh
claude plugin uninstall nunchi@nunchi
claude plugin marketplace remove nunchi
```

Open sessions run without the panel and stop being recorded after a restart. Session
records and settings stay in `~/.claude-control`; delete that folder if you no longer
need it.

## For developers

The engine is Rust (`crates/engine`). The main branch holds sources only. Build the
engine into `bin/` and attach your clone to a session:

```sh
rustup target add aarch64-apple-darwin x86_64-apple-darwin \
  x86_64-unknown-linux-musl aarch64-unknown-linux-musl
scripts/build-engine.sh
claude --plugin-dir ~/src/nunchi
```

With the plugin installed, the folder you pass replaces it for that session; only one copy
loads (checked with Claude Code 2.1.325). On macOS the script builds all three engines
(macOS universal, Linux x86_64 and arm64; the Linux ones are static musl builds linked
with `rust-lld`). On Linux it builds only the one for that CPU and needs only its musl
target. `cargo test` runs the engine tests. Releases are cut by pushing a tag `v<version>` that matches
`.claude-plugin/plugin.json`: a workflow builds the engines on macOS, tests them on Linux (arm64 through
qemu), and replaces the `dist` branch, which the marketplace entry points at. Pushing a
`ci/**` branch runs the same build and tests without publishing.

## Upgrading from the control screen

Earlier versions also shipped the control screen: a terminal app you kept in one iTerm2
pane to watch several sessions at once. It has been removed and will be rebuilt in Rust.
If you installed it, run `install.sh --uninstall` from that version before you update
your clone. It removes the hooks and the status line wrapper it put in
`~/.claude/settings.json`; a hook that points at a deleted script blocks every session.
