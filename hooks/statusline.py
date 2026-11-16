#!/usr/bin/env python3
"""상태 표시줄 입력을 기록하고, 기존 상태 표시줄 출력을 그대로 보여준다 (BUILD_PLAN §2.3).

- stdin JSON의 context_window.used_percentage를 sessions/<id>/context.json에 쓴다.
- 기존 statusLine 명령이 있으면 CONTROL_TUI_ORIG_STATUSLINE 환경변수로 받아 그 출력을 그대로 낸다.
- 실패해도 한 줄은 출력한다.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def base_dir() -> Path:
    return Path(os.environ.get("CONTROL_TUI_HOME", Path.home() / ".claude-control"))


def record_context(raw: str) -> None:
    payload = json.loads(raw)
    session_id = payload.get("session_id")
    pct = (payload.get("context_window") or {}).get("used_percentage")
    if not session_id or pct is None:
        return
    d = base_dir() / "sessions" / session_id
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    (d / "context.json").write_text(json.dumps({"used_percentage": pct}), encoding="utf-8")


def original_line(raw: str) -> str:
    cmd = os.environ.get("CONTROL_TUI_ORIG_STATUSLINE", "")
    if not cmd:
        return ""
    try:
        out = subprocess.run(cmd, shell=True, input=raw, capture_output=True, text=True, timeout=5)
        return out.stdout.strip()
    except Exception:
        return ""


def main() -> int:
    raw = sys.stdin.read()
    try:
        record_context(raw)
    except Exception as e:  # noqa: BLE001
        d = base_dir()
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(d / "errors.log", "a", encoding="utf-8") as f:
            f.write(f"statusline 기록 실패: {type(e).__name__}: {e}\n")
    print(original_line(raw) or "관제 기록 중")
    return 0


if __name__ == "__main__":
    sys.exit(main())
