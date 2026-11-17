"""플러그인 훅 입구 hooks/emit.sh (요구 이력 67, BUILD_PLAN §4.12).

쓸 수 있는 python3가 있으면 emit.py로 넘기고, 없으면 세션 시작 때만 알린다.
PATH는 테스트마다 임시 폴더로 바꾼다 (sh는 /bin/sh 절대 경로로 부른다).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EMIT_SH = ROOT / "hooks" / "emit.sh"
PYTHONS = [sys.executable] + [p for p in ("/usr/bin/python3",) if Path(p).exists()]


@pytest.fixture
def bindir(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    return d


def run(bindir, home, event, spaced=False):
    payload = {"session_id": "s1", "hook_event_name": event, "cwd": "/work/a",
               "transcript_path": "/none.jsonl"}
    text = json.dumps(payload) if spaced else json.dumps(payload, separators=(",", ":"))
    env = {"PATH": str(bindir), "HOME": str(home.parent), "CONTROL_TUI_HOME": str(home),
           "CONTROL_TUI_ANALYZE": "0"}
    return subprocess.run(["/bin/sh", str(EMIT_SH)], input=text, capture_output=True, text=True,
                          env=env, timeout=20)


def events(home):
    path = home / "sessions" / "s1" / "events.jsonl"
    return [json.loads(l)["event"] for l in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("python", PYTHONS)
def test_hands_over_to_emit_py_when_python_is_usable(bindir, tmp_path, python):
    (bindir / "python3").symlink_to(python)
    home = tmp_path / "control"
    for event in ("SessionStart", "UserPromptSubmit", "Stop"):
        res = run(bindir, home, event)
        assert res.returncode == 0 and res.stdout == "", res.stderr
    assert events(home) == ["SessionStart", "UserPromptSubmit", "Stop"]


@pytest.mark.parametrize("spaced", [False, True])
def test_without_python_session_start_tells_user_and_agent(bindir, tmp_path, spaced):
    home = tmp_path / "control"
    res = run(bindir, home, "SessionStart", spaced=spaced)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert "python3" in out["systemMessage"] and "xcode-select --install" in out["systemMessage"]
    ctx = out["hookSpecificOutput"]
    assert ctx["hookEventName"] == "SessionStart"
    assert "Do not install anything unless the user agrees" in ctx["additionalContext"]
    assert events(home) == []


@pytest.mark.parametrize("event", ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"])
def test_without_python_other_hooks_end_quietly(bindir, tmp_path, event):
    res = run(bindir, tmp_path / "control", event)
    assert (res.returncode, res.stdout, res.stderr) == (0, "", "")


def test_python_older_than_3_9_counts_as_missing(bindir, tmp_path):
    fake = bindir / "python3"
    # 버전 확인(-c)에 1로 답하는 옛 파이썬 흉내. emit.py를 부르면 표시를 남긴다.
    fake.write_text(f'#!/bin/sh\n[ "$1" = -c ] && exit 1\n: > "{tmp_path}/ran"\n')
    fake.chmod(0o755)
    res = run(bindir, tmp_path / "control", "SessionStart")
    assert "systemMessage" in json.loads(res.stdout)
    assert not (tmp_path / "ran").exists()


def test_hands_over_to_the_rust_engine_when_it_is_shipped(tmp_path, bindir):
    """bin/nunchi-engine이 있으면 파이썬을 찾지 않고 그것을 부른다 (요구 이력 68)."""
    plugin = tmp_path / "plugin"
    (plugin / "hooks").mkdir(parents=True)
    (plugin / "bin").mkdir()
    script = plugin / "hooks" / "emit.sh"
    script.write_text(EMIT_SH.read_text())
    engine = plugin / "bin" / "nunchi-engine"
    engine.write_text(f'#!/bin/sh\nread -r line\nprintf "%s|%s" "$1" "$line" > "{tmp_path}/called"\n')
    engine.chmod(0o755)
    res = subprocess.run(["/bin/sh", str(script)], input='{"hook_event_name":"Stop"}\n', capture_output=True, text=True,
                         env={"PATH": str(bindir)}, timeout=20)
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "called").read_text() == 'hook|{"hook_event_name":"Stop"}'
