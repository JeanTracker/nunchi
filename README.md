# nunchi

**Read the room in your Claude Code session.**

Long Claude Code sessions are hard to pick up again, for you and, once the session is
compacted, for the agent too. nunchi keeps a side panel next to the conversation that
tells you where things stand, so you can answer and move on.

- **Back from a break?** The goal, how you got here and what is still open, on one screen.
- **What you decided stays in view**, each decision with the turn it came from.
- **Misses get flagged.** An answer that skips or goes against a decision is marked ⚠,
  and one click copies a fix request.
- **Questions don't get buried.** What the agent asks you is pulled out of long answers.
- **Requests don't fall through.** What you asked for and is not done yet stays listed.
- **Compaction doesn't erase what you settled.** The agent keeps only a summary; the
  panel keeps the decisions, open questions, requests and known issues from before, and
  checks new answers against them. [How](#across-compactions)

![A Claude Code session on a small team todo API with the nunchi panel on the right, showing the goal and flow, the decisions settled so far, what was handled in the last turn, the agent's questions and the open requests](docs/images/panel.png)

> *Nunchi (눈치)* is the Korean art of quickly reading a situation and acting on it.

## Install

Run this inside Claude Code:

```
/plugin install nunchi --marketplace JeanTracker/nunchi
```

Runs on macOS (Apple silicon or Intel) and Linux (x86_64 or arm64); Windows is not
supported. Installing is the same everywhere: the plugin ships an engine for each platform
and picks the right one, so it needs no Python. On Linux the engine passes its tests in
CI, but it has not yet been tried in a live session.

## Use

In a session you want to follow, type `/nunchi`. The panel opens on the right (or as one
line above the input box in a narrow window), and the session is analyzed after each
response from then on. By default, sessions you have not turned on are not analyzed.

| Command | What it does |
| --- | --- |
| `/nunchi` | Turn nunchi on for this session and open the panel |
| `/nunchi build` | Analyze the conversation so far now, without waiting for the next answer |
| `/nunchi off` | Stop analyzing this session and close the panel |
| `/nunchi status` | Show the session's state; changes nothing |
| `/nunchi language` | Pick the panel and analysis language |

`/nunchi build` also works in a session where nunchi was never on: it reads the
conversation from the start. After an update, it redoes a session that an older version
analyzed, so the newer sections fill in. It also works after a compaction; see
[Across compactions](#across-compactions). Before it begins, it tells you how many
answers it will analyze and asks you to confirm.

## The panel, top to bottom

- **Goal** and **Flow**: what the session is working on now, and in one paragraph how it
  got there. When the goal has shifted, the first goal is shown dimmed above it.
- **Decisions**: newest first. A decision that a later one replaces disappears.
- **Handled**: one line for each of your messages in the last turn: done, in progress,
  not done, not mentioned, or looked into without a result. Changed decisions and open
  misses come first, with the `Copy prompt` button.
- **Agent questions**: only what the last answer asks; older open questions fold.
- **Open requests**: what is not done yet. An investigation that found no answer moves
  to **Known issues** with the agent's words.

Long text is cut with `…`; `Full text` on a section heading shows it in full. Labels are
in Korean or English, following Claude Code's language setting, or pick with
`/nunchi language`. Every symbol (✔ ◐ ○ ⊘ ◇ ⚠ and the rest) is explained in
[Panel symbols](docs/GUIDE.md#panel-symbols).

The omission check reads only what the agent wrote, not the code, so it can be wrong. In
our tests (a scripted conversation with six decisions and unrelated requests, three real
sessions and this project's own session, 97 turns in all), no request unrelated to a
decision was flagged as a miss.

## Across compactions

When Claude Code compacts a long session, the agent keeps only a summary. nunchi does
not work from that summary:

- **What was settled is already recorded.** Each answer is analyzed as it arrives, and
  the results go in their own file, `~/.claude-control/sessions/<id>/analysis.json`.
  Compaction does not touch it.
- **New answers are checked against those results, not the agent's memory.** Each
  analysis is a separate `claude -p` call that receives the decisions that still hold,
  the open misses, your recent requests and the agent's open questions, with the new turn.
- **The conversation file keeps the earlier part.** Claude Code adds to it when it
  compacts instead of rewriting it, so `/nunchi build` can start from your first request
  after a compaction, and an answer cut midway by a compaction is read in full. In our
  check, 25 pre-compaction copies from 15 sessions all matched the start of the current file.

We tried this on one scripted four-turn conversation, compacted twice: between answers
and in the middle of one. The summary left a decision out, and the next answer changed a
decided 4-second toast to 8 seconds. nunchi marked that decision ⚠, kept an unexplained
test failure under Known issues, and flagged nothing in the unrelated last turn. That is
one run, and the omission check can be wrong (see above).

nunchi does not keep its own copy of the conversation, so this holds only while Claude
Code keeps the session's conversation file. `/clear` starts a new session.

## Cost

Analysis runs in the background with `claude -p`, on your account's quota and outside
your conversation, so it adds nothing to the session's context. By default only sessions
you turned on are analyzed, at one call per answer (more if a call fails and is
retried). `/nunchi build` costs one call for each answer it analyzes. The engine exits
when there is nothing to do, and `/nunchi off` stops analysis for that session. Analysis
uses Claude Code's default model unless you set `analyze_model` in
`~/.claude-control/config.json`; see the guide, section
[Analysis cost](docs/GUIDE.md#analysis-cost).

## Update and remove

```sh
claude plugin marketplace update nunchi && claude plugin update nunchi@nunchi
claude plugin uninstall nunchi@nunchi && claude plugin marketplace remove nunchi
```

Full guide: [docs/GUIDE.md](docs/GUIDE.md)

## Status

Early development. The panel's behavior is described in the guide, section
[What the panel shows](docs/GUIDE.md#what-the-panel-shows).

An earlier version also shipped a separate terminal app for watching several sessions at
once (the control screen, installed with `install.sh`). It has been removed and will be
rebuilt in Rust. If you installed it, run `install.sh --uninstall` from that version
before you update, so no hook is left pointing at a deleted script.

## License

[MIT](LICENSE)

nunchi is an independent project and is not affiliated with or endorsed by Anthropic.
