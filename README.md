# nunchi

**Read the room across your Claude Code sessions.**

nunchi is a terminal app for people who run several Claude Code sessions at once.
It shows each session's goal, where the conversation changed direction, which earlier
requests may have been dropped, and what needs your attention next — and lets you send
the next instruction without leaving the screen.

> *Nunchi (눈치)* is the Korean art of quickly reading a situation and acting on it.

## Install

macOS, iTerm2, Python 3.11+ and git are required.

```sh
curl -fsSL https://raw.githubusercontent.com/JeanTracker/nunchi/main/install.sh | sh
```

While the repository is private, clone it and run `./install.sh` instead. The installer
shows a diff and asks before it touches `~/.claude/settings.json`.

Then run `nunchi` in an iTerm2 pane.

## Uninstall

```sh
~/.local/share/nunchi/install.sh --uninstall
```

Full install, usage and uninstall guide: [docs/GUIDE.md](docs/GUIDE.md)
(한국어: [docs/ko/GUIDE.md](docs/ko/GUIDE.md))

## Status

Early development. Expect rough edges; jumping to a session's pane (`p`) is not built yet.

nunchi is an independent project and is not affiliated with or endorsed by Anthropic.
