#!/bin/sh
# Start after configuring and trusting the Nunchi Codex hooks for this project.
set -eu
here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if [ "${1:-}" = "--print-hooks" ]; then
    python3 - "$here/../target/debug/nunchi-engine" <<'PYHOOK'
from pathlib import Path
import json, shlex, sys
engine = Path(sys.argv[1]).resolve()
command = shlex.quote(str(engine)) + " codex-hook"
entry = [{"hooks": [{"type": "command", "command": command}]}]
print(json.dumps({"hooks": {event: entry for event in ("SessionStart", "UserPromptSubmit", "Stop")}}, indent=2))
PYHOOK
    exit 0
fi
run=$(mktemp -d "${TMPDIR:-/tmp}/nunchi-panel.XXXXXXXX")
name="nunchi-${run##*.}"
control=${CONTROL_TUI_HOME:-"$HOME/.nunchi-codex"}
model=${CONTROL_TUI_CODEX_MODEL:-gpt-6.2-sol}
# Set the launch environment explicitly even when a tmux server already exists.
tmux new-session -d -s "$name" -c "$PWD" \
    -e "CONTROL_TUI_CODEX_RUN=$run" -e "CONTROL_TUI_HOME=$control" \
    -e "CODEX_HOME=${CODEX_HOME:-$HOME/.codex}" -e "CONTROL_TUI_CODEX_MODEL=$model" \
    codex --no-daemon "$@"
tmux split-window -d -h -l 40% -t "$name:" python3 "$here/codex-panel.py" --run "$run"
if [ -n "${TMUX:-}" ]; then
    exec tmux switch-client -t "$name"
fi
exec tmux attach-session -t "$name"
