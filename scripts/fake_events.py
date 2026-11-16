#!/usr/bin/env python3
"""가짜 세션 이벤트를 만든다 (BUILD_PLAN §7 Phase 1, 테스트용).

사용법:
    python3 scripts/fake_events.py normal    # 정상 응답 시나리오
    python3 scripts/fake_events.py compact   # 압축 시나리오

실제 Claude Code 없이 hooks/emit.py에 같은 형식의 JSON을 넣어 준다.
CONTROL_TUI_HOME을 지정하면 그 아래에 기록한다.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMIT = ROOT / "hooks" / "emit.py"


def scenario(name: str, session_id: str):
    cwd = "/tmp/fake-project"
    base = {"session_id": session_id, "cwd": cwd, "transcript_path": "/tmp/none.jsonl"}
    if name == "normal":
        return [
            {"hook_event_name": "SessionStart", "source": "startup"},
            {"hook_event_name": "UserPromptSubmit", "prompt": "3곳 가격 조사해줘"},
            {"hook_event_name": "PreToolUse", "tool_name": "WebSearch", "tool_use_id": "t1",
             "tool_input": {"query": "가격 비교"}},
            {"hook_event_name": "PostToolUse", "tool_name": "WebSearch", "tool_use_id": "t1",
             "tool_response": "결과 3건"},
            {"hook_event_name": "Stop"},
        ]
    if name == "compact":
        return [
            {"hook_event_name": "UserPromptSubmit", "prompt": "요구사항 정리"},
            {"hook_event_name": "PreCompact", "trigger": "manual"},
            {"hook_event_name": "PostCompact", "compact_summary": "요구사항 요약"},
        ]
    raise SystemExit(f"알 수 없는 시나리오: {name}")


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "normal"
    session_id = f"fake-{name}"
    for event in scenario(name, session_id):
        payload = {"session_id": session_id, "cwd": "/tmp/fake-project",
                   "transcript_path": "/tmp/none.jsonl", **event}
        subprocess.run([sys.executable, str(EMIT)], input=json.dumps(payload), text=True, check=False)
    print(f"기록 완료: {session_id}")


if __name__ == "__main__":
    main()
