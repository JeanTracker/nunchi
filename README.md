# nunchi

**Read the room in your Claude Code session.**

nunchi adds a side panel to a Claude Code session. When you come back to a session, it
shows what you need first: what the agent is asking you, how the conversation got here,
and which of your requests are still open.

> *Nunchi (눈치)* is the Korean art of quickly reading a situation and acting on it.

## Install

Run this inside Claude Code:

```
/plugin install nunchi --marketplace JeanTracker/nunchi
```

macOS only. Nothing else to install: the plugin ships its own engine, so it needs no
Python. While the repository is private, adding the marketplace needs git access to it.

## Use

In a session you want to follow, type `/nunchi`. The panel opens on the right (or as one
line above the input box in a narrow window), and the session is analyzed after each
response from then on. Analysis runs `claude -p` in the background and uses your
account's quota; see the guide for how to limit it.

## Update and remove

```sh
claude plugin marketplace update nunchi && claude plugin update nunchi@nunchi
claude plugin uninstall nunchi@nunchi && claude plugin marketplace remove nunchi
```

Full guide: [docs/GUIDE.md](docs/GUIDE.md) (한국어: [docs/ko/GUIDE.md](docs/ko/GUIDE.md))

## Status

Early development. Turning the panel off for a session (`/nunchi off`) and a status
command are not built yet.

An earlier version also shipped a separate terminal app for watching several sessions at
once (the control screen, installed with `install.sh`). It has been removed and will be
rebuilt in Rust. If you installed it, run `install.sh --uninstall` from that version
before you update, so no hook is left pointing at a deleted script.

nunchi is an independent project and is not affiliated with or endorsed by Anthropic.
