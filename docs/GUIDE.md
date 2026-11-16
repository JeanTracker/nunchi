# Installing and using nunchi

nunchi is a terminal app you keep open in one iTerm2 pane. It shows the state and
conversation of the Claude Code sessions running in your other panes, and lets you send
the next instruction from where you are. One script, `install.sh`, installs and removes it.

You need macOS, iTerm2, Python 3.11 or later, and git. The analysis features (goals,
dropped requests, summaries) use the `claude` command on your PATH.

한국어 안내: [docs/ko/GUIDE.md](ko/GUIDE.md)

## Install

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
4. Registers the Claude Code hooks and status line in `~/.claude/settings.json`. It shows
   the change as a diff first and asks `적용할까요? [y/N]` (apply?). If you accept, a
   backup `settings.json.bak-<timestamp>` is written next to it.

Your existing status line keeps working. nunchi wraps that command and only records the
context usage on the side.

Running the curl line or `~/.local/share/nunchi/install.sh` again updates the install:
it runs `git pull` in the download folder and re-syncs dependencies, and leaves hooks
that are already registered alone. If you have edited files in that folder, it skips the
update and keeps them. For a clone, run `git pull` and then `./install.sh` again.

With curl, pass options after `sh -s --`. For example, to install without prompts:

```sh
curl -fsSL https://raw.githubusercontent.com/JeanTracker/nunchi/main/install.sh | sh -s -- --yes
```

- `--no-hooks`: skip hook registration only. Register later with `install.sh --hooks`.
- `--link`, `--path`: redo only the command link, or only the PATH entry.
- `--yes`: proceed without confirmation, including the `~/.claude/settings.json` change.

You can change locations with `NUNCHI_HOME` (download folder), `NUNCHI_BIN` (command
folder) and `NUNCHI_RC` (shell rc file). `./install.sh --help` lists everything.

> If you register hooks from both a development clone and an install folder, every event
> is recorded twice. The installer warns about this; remove one side with
> `python3 scripts/install_hooks.py --remove --apply`.

## First run

Split an iTerm2 pane and run `nunchi`. If the command is not found because you have not
opened a new terminal yet, run `source ~/.zshrc` first.

```sh
nunchi
```

When you start Claude Code in another pane, it appears in the session list at the top.
Sessions that were already open before you installed nunchi show as "연결 대기"
(waiting to connect). Hooks are read when a session starts, so end that session once and
start it again to connect it.

The first time you send an instruction, macOS may ask whether to allow control of
iTerm2. Allow it, otherwise nunchi cannot type into the panes.

## Attaching the in-session panel (mod)

The mod is a plugin that opens a nunchi panel beside a Claude Code session. It shows what
the agent is asking you right now, the goal and decisions so far, and which of your
requests are still open. The mod does not analyze anything; it only reads analysis
results. Analysis is done by a background analyzer that the hook wakes when a response
ends, so you do not need the nunchi control screen running. The analyzer runs only when
there is work and stops by itself when done. Although it lives under `~/.claude/skills`,
it is not a skill: it has no instructions for the model, so it adds no tokens to the
conversation.

Verified with Claude Code 2.1.322. The plugin folder is `mod/nunchi` in the repository
(`~/.local/share/nunchi/mod/nunchi` for a curl install).

**Attach it always (recommended).** When a session opens, Claude Code automatically
loads plugins under `~/.claude/skills` (the place for your own plugins, not only skills).
Copy the repository's mod folder there and a plain `claude` picks it up. Copy rather than
link: a link breaks when you move or delete the clone. The mod only reads analysis files
in `~/.claude-control`, so the copy works on its own. The catch is that you must copy
again when the repository's mod changes (`install.sh` does not do this copy).

```sh
mkdir -p ~/.claude/skills
rm -rf ~/.claude/skills/nunchi                                    # when copying again
cp -R ~/.local/share/nunchi/mod/nunchi ~/.claude/skills/nunchi    # or mod/nunchi in your clone
claude plugin list                                                # look for nunchi@skills-dir · loaded
```

**Attach it once.** To attach it to a single session without copying, pass it as an
option. For a session that is already open, close it and reopen it with `--resume`. If a
copy is also installed, the folder given by the option wins and the copy is not loaded
(only one plugin per name). Use this to test a mod you are editing.

```sh
claude --plugin-dir ~/.local/share/nunchi/mod/nunchi
claude --resume <session ID> --plugin-dir ~/.local/share/nunchi/mod/nunchi
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
different name, the events they listen to do not overlap (the amask mod only receives
turn ends and draws nothing), and the nunchi hooks live in `~/.claude/settings.json`, so
both are called. Whether you copy the mod or pass `--plugin-dir`, it works under amask
unchanged. If you pass `--settings` yourself, as in `claude --settings …`, amask turns
its own hooks and mod off (that is amask's behavior; nunchi is not affected).

**Detaching.** Delete the copy. Open sessions run without the mod after a restart.

```sh
rm -rf ~/.claude/skills/nunchi
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

Uninstalling reverses the install. First it removes the nunchi hooks from
`~/.claude/settings.json` and restores the original status line command, again showing a
diff, asking, and writing a backup. If you decline this step, or another tool has wrapped
the status line again so it cannot be restored, it stops without removing anything else:
if the files disappeared while the hooks stayed, every Claude Code session would call a
missing file.

Next it removes the `~/.local/bin/nunchi` link and the nunchi block in your shell rc
file, then the curl download folder. If that folder contains edited or new files, they
are kept and reported. A clone you made yourself is kept; only the `.venv` created during
install is removed.

`~/.claude-control`, which holds session records and settings, is kept. If you no longer
need it, quit nunchi and delete it:

```sh
rm -rf ~/.claude-control
```

Open Claude Code sessions run without the hooks after a restart. `install.sh --uninstall`
does not remove a copied mod; delete it with `rm -rf ~/.claude/skills/nunchi`.

If you deleted the folder first and the hooks are left behind, reinstall to the same
location and run `--uninstall` to remove them cleanly. If you installed elsewhere, delete
the entries containing `hooks/emit.py` and `hooks/statusline.py` from settings.json by
hand.
