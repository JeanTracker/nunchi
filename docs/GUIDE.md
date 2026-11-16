# Installing and using nunchi

nunchi is a terminal app you keep open in one iTerm2 pane. It shows the state and
conversation of the Claude Code sessions running in your other panes, and lets you send
the next instruction from where you are. It comes in two parts: a Claude Code plugin that
records your sessions, analyzes them in the background and adds a side panel inside each
session, and the control screen (the `nunchi` command), which `install.sh` installs.

You need macOS, iTerm2 and git. The plugin's hooks run with the `python3` on your PATH
(3.9 or later; the one that ships with macOS works). The control screen needs Python 3.11
or later. The analysis features (goals, dropped requests, summaries) use the `claude`
command on your PATH.

한국어 안내: [docs/ko/GUIDE.md](ko/GUIDE.md)

## Install

Install the plugin first. Without it no session is recorded and the control screen
stays empty.

### 1. The plugin

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

The plugin brings three things: the hooks that record each session's events into
`~/.claude-control`, the background analyzer that the hooks wake when a response ends,
and the side panel (the mod, described below). It does not change
`~/.claude/settings.json`, and it adds no tokens to the conversation. Claude Code keeps
its own copy of the whole repository, so moving or deleting your clone does not affect
it. New sessions pick it up; restart a session that is already open
(`claude --resume <session ID>`). While the repository is private, adding the
marketplace needs git access to it.

**Update.** `claude plugin marketplace update nunchi`, then
`claude plugin update nunchi@nunchi`, and restart your sessions. Claude Code keeps each
version in its own folder, so sessions that were already open, and analyses already
running, finish on the old version.

### 2. The control screen

Once the repository is public, one line is enough:

```sh
curl -fsSL https://raw.githubusercontent.com/JeanTracker/nunchi/main/install.sh | sh
```

The repository is private for now, so that URL returns 404. Clone it with an account
that has access and run the installer from the clone:

```sh
git clone https://github.com/JeanTracker/nunchi.git
cd nunchi
./install.sh
```

The two methods differ only in where the source lives. The curl install downloads to
`~/.local/share/nunchi`; running `./install.sh` in a clone installs in place. Everything
else is the same:

1. Creates `.venv` inside the repository and installs `textual`.
2. Links `~/.local/bin/nunchi` to the repository's `bin/nunchi`.
3. If `~/.local/bin` is not on your PATH, adds it to your shell rc file (`~/.zshrc` for
   zsh) inside a `# >>> nunchi >>>` … `# <<< nunchi <<<` block. Nothing outside the
   block is touched.
4. Tidies `~/.claude/settings.json`: removes nunchi hooks that an earlier version put
   there, from any folder (the plugin records now, and keeping both records every event
   twice), and wraps your status line to record context usage. It shows the change as a
   diff first and asks `적용할까요? [y/N]` (apply?). If you accept, a backup
   `settings.json.bak-<timestamp>` is written next to it.

Your existing status line keeps working. nunchi wraps that command and only records the
context usage on the side. At the end the installer says whether the plugin is
installed, and if it is not, shows the command to install it. It does not install the
plugin itself, because that changes `~/.claude`.

Running the curl line or `~/.local/share/nunchi/install.sh` again updates the install:
it runs `git pull` in the download folder and re-syncs dependencies, and leaves settings
that are already in place alone. If you have edited files in that folder, it skips the
update and keeps them. For a clone, run `git pull` and then `./install.sh` again.

With curl, pass options after `sh -s --`. For example, to install without prompts:

```sh
curl -fsSL https://raw.githubusercontent.com/JeanTracker/nunchi/main/install.sh | sh -s -- --yes
```

- `--no-hooks`: leave `~/.claude/settings.json` alone. Tidy it later with
  `install.sh --settings`.
- `--settings`: only tidy `~/.claude/settings.json`, as in step 4.
- `--hooks`: for using nunchi without the plugin, register the hooks in
  `~/.claude/settings.json` as earlier versions did. Do not combine it with the plugin.
- `--link`, `--path`: redo only the command link, or only the PATH entry.
- `--yes`: proceed without confirmation, including the `~/.claude/settings.json` change.

You can change locations with `NUNCHI_HOME` (download folder), `NUNCHI_BIN` (command
folder) and `NUNCHI_RC` (shell rc file). `./install.sh --help` lists everything.

> Hooks in `~/.claude/settings.json` and the plugin's hooks both record, so every event
> is recorded twice when both are present. If you installed an earlier version, run
> `./install.sh --settings` once after installing the plugin.

## First run

Split an iTerm2 pane and run `nunchi`. If the command is not found because you have not
opened a new terminal yet, run `source ~/.zshrc` first.

```sh
nunchi
```

When you start Claude Code in another pane, it appears in the session list at the top.
Sessions that were already open before you installed the plugin show as "연결 대기"
(waiting to connect). Hooks are read when a session starts, so end that session once and
start it again to connect it.

The first time you send an instruction, macOS may ask whether to allow control of
iTerm2. Allow it, otherwise nunchi cannot type into the panes.

## Attaching the in-session panel (mod)

The mod is the part of the plugin that opens a nunchi panel beside a Claude Code session.
It shows what the agent is asking you right now, the goal and decisions so far, and which
of your requests are still open. The mod does not analyze anything; it only reads
analysis results. Analysis is done by the background analyzer from the same plugin,
which the hooks wake when a response ends, so you do not need the nunchi control screen
running. The analyzer runs only when there is work and stops by itself when done. The
plugin is not a skill: it has no instructions for the model, so it adds no tokens to the
conversation.

Verified with Claude Code 2.1.322. The repository is also a plugin marketplace
(`.claude-plugin/marketplace.json`); the plugin is the repository itself. Install and
update it as described in "Install" above.

If you copied the mod into `~/.claude/skills/nunchi` earlier, delete that copy
(`rm -rf ~/.claude/skills/nunchi`). The installed plugin takes precedence and the copy
is reported as "already taken" and not loaded.

**Attach it once.** To attach a folder to a single session without installing, pass it
as an option. For a session that is already open, close it and reopen it with `--resume`.
The repository folder attaches the whole plugin (mod and hooks); `mod/nunchi` attaches
only the mod, which is what you want while editing the mod with the plugin installed.
Attaching the whole folder while the plugin is installed records every event twice.

```sh
claude --plugin-dir ~/.local/share/nunchi                                       # mod and hooks
claude --resume <session ID> --plugin-dir ~/.local/share/nunchi/mod/nunchi      # mod only
```

**Turning nunchi on.** Having the plugin attached does not analyze every session. Type
`/nunchi` in a session whose flow you want to follow: that session becomes an analysis
target and the panel opens. From then on it is analyzed after every response, and it
stays on when you reopen the session. Responses from before you turned it on are
analyzed together, from the start, when the next response ends. The panel does not open
in sessions that are not turned on. Sessions selected in the nunchi control screen are
still analyzed as before, and the panel opens if they have results.

In a wide window (110 columns or more) the panel opens on the right; in a narrow one a
single line appears above the input box. The panel takes 40% of the window; change it
with `mod_width_ratio` in `~/.claude-control/config.json`. While waiting it shows
"분석 대기..." (queued), while running "분석 중..." (analyzing), and on failure
"분석 실패 · <reason>" (analysis failed).

**Using it with amask.** amask adds its own hooks (`--settings`) and its own mod
(`--plugin-dir`) to the command line when it opens a session. The nunchi mod has a
different name and the events they listen to do not overlap (the amask mod only receives
turn ends and draws nothing). Both worked together while nunchi's hooks lived in
`~/.claude/settings.json`; with the hooks in the plugin, a session under amask has not
been checked yet. If you pass `--settings` yourself, as in `claude --settings …`, amask
turns its own hooks and mod off (that is amask's behavior).

**Detaching.** Uninstall the plugin and remove the marketplace. Open sessions run
without the mod and the hooks after a restart, and are no longer recorded.

```sh
claude plugin uninstall nunchi@nunchi
claude plugin marketplace remove nunchi
```

## Screen and keys

The screen has three areas. At 140 columns or wider the session list is on the left and
the conversation on the right; narrower, they stack vertically. The input line is always
at the bottom.

**Session list.** Sessions whose response arrived first move to the top. Each row shows
a state (작업 working · 응답 responded · 허락 permission · 질문 question · 대기 idle ·
종료 ended) and the number of open requests (`⚠1`). Tool names are not shown. Use ↑↓ to
select.

**Conversation.** For the selected session, the goal flow (start → turns where the topic
moved → now) and the requests you sent that are not yet handled, or that the agent said
it could not do, are pinned at the top. The conversation flows below in time order. Older
turns are folded ten at a time into one line, and the last turn shows the full response
text.

- ↑↓ select a turn, Enter expand a fold or a turn
- `d` response detail (request, final response, what the agent said along the way), Esc
  to go back, ←→ previous/next turn
- `c` all accumulated requests (not handled · could not do or deferred · handled ·
  replaced by a later request), Enter to jump to that request's turn, c or Esc to close
- `o` expand the original text, `s` show the last response as a summary
- End (or `]`) jump to the last turn, Home (or `[`) to the top, PgUp/PgDn scroll

**Input line.** Enter it with `i` or `:`, type, and press Enter: the text is typed into
the selected session's pane as if you had typed it there. If the session is busy, it is
queued and sent when the response ends. If the session is waiting for permission, text
input is blocked and only `y` (allow) or `n` (deny) is accepted, so that no unintended
option gets pressed.

When a session shows a multiple-choice question and waits, the list shows `? 질문`
(question) and the conversation area shows the question and the answers chosen so far.
Press `i` and the options open in place of the input box. Choose with a number or
↑↓ and Enter; for multi-select questions, toggle with Space and continue with Enter. When
everything is chosen, the answer is shown once more; press Enter and nunchi checks that
the question is still open in the pane before sending. Free-text answers still have to be
typed in the pane. `y`/`n` do not work on questions.

- New line: Shift+Enter, Option+Enter, or Ctrl+J
- Starting with `/` lists Claude Code commands and skills; Tab completes
- ↑↓ input history, Shift+Tab cycles the session's permission mode, PgUp/PgDn scroll the
  conversation even while typing

Outside the input line, Tab moves between the three areas, and `q` or Ctrl+Q quits. Keys
work by position even with Korean input active (ㅂ=q, ㅇ=d, and so on). `p` (jump to the
selected session's pane) is not built yet.

### Reducing analysis cost

The goal flow, summaries and request log are built by calling `claude -p` once for each
new turn whenever a session finishes a response. That uses your quota. Tune it in
`~/.claude-control/config.json`:

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

Set `analyze_scope` to `"off"` to turn analysis off, or `"all"` to analyze every session.
The default `"selected"` analyzes only the selected session. With `analyze_when` set to
`"manual"`, analysis runs only when you press `a`. To turn it off for one run, start with
`CONTROL_TUI_ANALYZE=0 nunchi`.

Analysis is done by a background analyzer outside the nunchi screen. Its targets are the
session selected in nunchi and sessions turned on with `/nunchi` (every session with
`"all"`). `analyze_workers` is how many analyses may run at once (1 or 2, default 1).
When several sessions finish at the same time, the selected session goes first, then the
most recent responses. Raising it to 2 shortens the wait, but analysis uses the same
account's quota, so usage arrives in bursts. Analyses already running finish even if you
quit nunchi.

`theme` sets the colors: `graphite` (default), `midnight`, `polar`, `forest`, `dusk`,
`contrast` (high contrast) or `paper` (light background). While running, try one with
Ctrl+P → 테마 바꾸기 (change theme); a theme chosen this way is not saved.

## Uninstall

```sh
~/.local/share/nunchi/install.sh --uninstall   # curl install
./install.sh --uninstall                       # install from a clone
```

Even if the download folder is already gone, the curl form can clean up what is left.
As with installing, this works only once the repository is public.

```sh
curl -fsSL https://raw.githubusercontent.com/JeanTracker/nunchi/main/install.sh | sh -s -- --uninstall
```

This removes the control screen. Remove the plugin as described in "Detaching" above.

Uninstalling reverses the install. First it removes this folder's nunchi hooks (if
`--hooks` put any there) from `~/.claude/settings.json` and restores the original status
line command, again showing a diff, asking, and writing a backup. If you decline this
step, or another tool has wrapped the status line again so it cannot be restored, it
stops without removing anything else: if the files disappeared while the hooks or the
status line stayed, every Claude Code session would call a missing file.

Next it removes the `~/.local/bin/nunchi` link and the nunchi block in your shell rc
file, then the curl download folder. If that folder contains edited or new files, they
are kept and reported. A clone you made yourself is kept; only the `.venv` created during
install is removed.

`~/.claude-control`, which holds session records and settings, is kept. If you no longer
need it, quit nunchi and delete it:

```sh
rm -rf ~/.claude-control
```

`install.sh --uninstall` does not remove the plugin, so sessions keep being recorded
until you uninstall it.

If you deleted the folder first and the hooks are left behind, reinstall to the same
location and run `--uninstall` to remove them cleanly. If you installed elsewhere, delete
the entries containing `hooks/emit.py` and `hooks/statusline.py` from settings.json by
hand.
