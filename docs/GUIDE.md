# nunchi guide

nunchi is a Claude Code plugin that adds a side panel to a session. When you come back to
a session after a while, the panel shows where things stand: the current goal and how
the conversation got there, the requirements you settled, what the agent did and what it
is asking you, and which of your requests are still open. You read that, answer, and
carry on.

The panel only reads analysis results. A small engine that ships with the plugin records
each session's events through Claude Code hooks and, when a response ends, analyzes the
new turn in the background with `claude -p`.

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

The panel does not open on its own in sessions you have not turned on.

## Commands

All of them take effect at once, even while the agent is still answering; their replies
show up in the conversation once that answer ends.

| Command | What it does |
| --- | --- |
| `/nunchi` or `/nunchi on` | Turn nunchi on for this session and open the panel |
| `/nunchi off` | Stop analyzing this session and close the panel |
| `/nunchi status` | Show the state in five lines; changes nothing |
| `/nunchi language` | Pick the panel and analysis language (see below) |

`/nunchi off` keeps the results you already have. Until you run `/nunchi` again, the
session is not analyzed, even with `analyze_scope` set to `"all"`, and neither the panel
nor the line above the input box comes back on its own. An analysis that was already
running finishes first. Turning it back on picks up from where it stopped.

If you close the panel yourself, it stays closed for the rest of that session.
Analysis goes on; `/nunchi` opens the panel again.

`/nunchi status` answers like this:

```
Nunchi    on · analyzes after every answer
Analysis  through answer #12 · 14:03
State     idle
Hooks     recording
Language  English (Claude Code setting)
```

`Hooks` reads `not known yet` until the session's first message or answer.
An unknown argument changes nothing and lists these commands.

## Language

The panel's labels come in Korean and English. By default they follow Claude Code's
language setting (`/config`, the response language): Korean when it is Korean, English
otherwise. With no setting, the terminal's `LANG` decides. The first session after you
install tells you once which language it picked.

To change it, type `/nunchi language` and pick `English`, `한국어` or
`Follow the Claude Code setting`. The question is in the panel's language (on a Korean
panel the last choice reads `Claude Code 설정 따르기`); the language names are always
written in their own language. The panel switches right away, in every open session.
Press Esc to leave it as it is.

The summaries in the panel (goal, flow, decisions, questions, requests) are written by
the analysis, in the language picked when the session is first analyzed. A session keeps
that language so its summaries never mix; new sessions use the new choice. If Claude Code
is set to another language, such as Japanese, the labels are in English and the
summaries in that language (only Korean and English are tested). Quoted words are always
shown as they were said. When a session was analyzed in a different language from the
one you picked, a line under the header says so.

If you pick a language while the current session was analyzed in another one, a second
question follows, in the panel's language: `Keep it` (`그대로 두기`; new sessions use the
new language) comes first, then `Rebuild now` (`지금 다시 분석`). Rebuilding analyzes the
whole session again from the first turn, one `claude -p` call per turn, and the header
reads `Rebuilding from the start #k/#n` (`흐름 처음부터 만드는 중 #k/#n`) until it is done. The previous result is kept as
`analysis.prev.json` in the session folder until the rebuild finishes. To rebuild later,
run `/nunchi language` again and pick the same language.

## What the panel shows

The panel opens on the right when the window is 110 columns or wider and takes 40% of
the window. In a narrower window a single line appears above the input box instead:
`Nunchi Goal: … · asks n · open n · through #n` (goal, the agent's open questions, your
open requests, the last answer analyzed). The labels below are the English ones, from top
to bottom; with the panel in Korean (see [Language](#language)) the same items carry
Korean labels.

**Header.** `Nunchi · through answer #12` means the results cover your 12th message and
the agent's answer to it. Next to it you may see:

- `new request pending`: you sent a message after that answer and the results do not
  include it yet. Messages from other agents and sessions do not count.
- `Queued` or `Analyzing`
- `Rebuilding from the start #3/#12` or `Catching up #3/#12`, with progress
- `2 answers behind`: two responses arrived since the last analysis
- `Analysis failed · <reason>`; it is retried a limited number of times
- `Auto analysis off · /nunchi to turn on`: the session has old results but is not
  turned on
- `No hook records · restart the session (claude --resume)`, in red: nunchi saw a
  message or an answer in this session, but the hooks wrote nothing for it, so nothing
  gets analyzed

Before the first result the panel shows `Nunchi on · analyzes after the next answer`.

**Goal.** What the conversation is working on now, and from which turn (`since #10`). It
names the subject and the outcome you want, not a step or a decided value, so it does not
go stale as the work moves on. When the goal has changed since the first turn, the first
goal is shown dimmed on top (`Goal  first #1`) and the current one below it
(`Now  since #10 · moved on`; also `narrowed` and `widened`). Below it, dimmed because it
is the analyzer's estimate, `Flow` sums up in one paragraph how the conversation has gone
from the start.

**Decisions.** The requirements settled for the goal, the things that belong in the
design, newest first, each with the turn it was settled in. A decision counts when you
state it yourself, or when you accept the agent's proposal, even with a plain "go ahead"
or "commit it"; the accepted ones end with `· approved proposal`. The order of work,
approvals on their own, and questions are not decisions. When one turn settles several,
they are numbered `#3-1`, `#3-2`. A decision that a later one replaces disappears, and
the later one shows only what now holds.

When the agent's latest answer misses or goes against an earlier decision, that decision
shows ⚠ in yellow instead of ✔, with `· broken in #12` or `· missed in #12`. It stays
visible even when the list is folded, until the agent says it has fixed it or you change
the decision. nunchi judges this only from what the agent wrote, not from the code.

**Handled.** What the agent did about your messages in the last analyzed turn, one line
each: ✔ done, ◐ in progress, ⊘ not done, ○ not mentioned, ◇ looked into without a result.
Decision changes come first (`Decision #1-1 changed: five lines → six lines`), and so do
omissions found in that turn (`Decision #11 broken: …`) and fixes
(`Decision #11 fixed: …`). While any omission is open, the first line reads
`⚠ 1 open miss` with a `Copy prompt` button. It copies one request that covers every open
omission: each decision, what went wrong, and the agent's own words. Paste it into the
prompt box wherever you like and send it. If copying fails, the request text appears
under the button so you can select it.

**Agent questions.** What the agent is waiting on from you, asked in its last answer,
newest first: a number, a one-line summary, the turn it was last asked in (and
`· first #5` when it was first asked earlier), and the agent's own words in quotes.
`partly answered` means what it says. Questions from earlier answers that are still open
fold under `n earlier questions`; click it to see them. A question closes when you answer
it, including a blanket "go ahead as you suggest", or when the conversation moves past
it. In a short panel this section may sit below the visible area; scroll the panel.

**Open requests.** Your requests that are not done yet: ○ not handled, ◐ in progress (for
example a merge request waiting for review), ⊘ not done or deferred, with the agent's
words in quotes. Each shows the turn it came from. A request the agent looked into
without finding a cause or answer is not listed here; it moves to **Known issues** with
the agent's words.

**More and collapse.** Decisions, handled items and open requests show three items each.
When a list has more, its last line reads `… n more`: click it to open the whole list,
and the same line then reads `Collapse`. What you open stays open while you work in that
session, even as new analysis results come in.

**Full text and shorten.** Long text is cut to a few lines and ends with `…`: the goal
four lines, the flow three, each decision three, each question summary and open request
two, each handled item and each quote one. When something in a section is cut, its
heading shows `Full text` on the right: click it to see the shown items in full, and it
then reads `Shorten`. It never reveals items folded under `… n more`. The next analysis
result folds the text back.

**Numbers.** When the last response cites plan numbers such as R17, §4.5 or Phase 4c, the
panel looks them up in the project's `docs/*.md` and shows the original wording, up to
five. Numbers the response already explains in plain words right before them, like
`the open-requests list (R8)`, are left out, and the section disappears when all of them
are. This only works for documents written in that table and heading style.

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
