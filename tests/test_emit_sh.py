"""플러그인 훅 입구 hooks/emit.sh (요구 이력 67·68·69, BUILD_PLAN §4.12·§4.13).

함께 실린 엔진이 돌면 그것에, 저장소 사본이면 파이썬 기록기에 넘기고, 둘 다 안 되면 세션 시작 때만 알린다.
저장소의 hooks/를 임시 플러그인 폴더로 복사해서 돌린다: 개발 중 빌드한 bin/nunchi-engine에 휩쓸리지 않게.
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


@pytest.fixture
def plugin(tmp_path):
    """저장소 사본처럼: hooks/emit.sh와 emit.py만, 엔진은 없음"""
    p = tmp_path / "plugin"
    (p / "hooks").mkdir(parents=True)
    for name in ("emit.sh", "emit.py"):
        (p / "hooks" / name).write_text((ROOT / "hooks" / name).read_text())
    return p


def add_engine(plugin, body):
    (plugin / "bin").mkdir(exist_ok=True)
    engine = plugin / "bin" / "nunchi-engine"
    engine.write_text("#!/bin/sh\n" + body)
    engine.chmod(0o755)
    return engine


def run(bindir, home, event, spaced=False, plugin=None):
    payload = {"session_id": "s1", "hook_event_name": event, "cwd": "/work/a",
               "transcript_path": "/none.jsonl"}
    text = json.dumps(payload) if spaced else json.dumps(payload, separators=(",", ":"))
    env = {"PATH": str(bindir), "HOME": str(home.parent), "CONTROL_TUI_HOME": str(home),
           "CONTROL_TUI_ANALYZE": "0"}
    return subprocess.run(["/bin/sh", str(plugin / "hooks" / "emit.sh")], input=text, capture_output=True, text=True,
                          env=env, timeout=20)


def events(home):
    path = home / "sessions" / "s1" / "events.jsonl"
    return [json.loads(l)["event"] for l in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("python", PYTHONS)
def test_hands_over_to_emit_py_when_python_is_usable(bindir, tmp_path, python, plugin):
    (bindir / "python3").symlink_to(python)
    home = tmp_path / "control"
    for event in ("SessionStart", "UserPromptSubmit", "Stop"):
        res = run(bindir, home, event, plugin=plugin)
        assert res.returncode == 0 and res.stdout == "", res.stderr
    assert events(home) == ["SessionStart", "UserPromptSubmit", "Stop"]


@pytest.mark.parametrize("spaced", [False, True])
def test_without_python_session_start_tells_user_and_agent(bindir, tmp_path, spaced, plugin):
    home = tmp_path / "control"
    res = run(bindir, home, "SessionStart", spaced=spaced, plugin=plugin)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert "python3" in out["systemMessage"] and "xcode-select --install" in out["systemMessage"]
    ctx = out["hookSpecificOutput"]
    assert ctx["hookEventName"] == "SessionStart"
    assert "Do not install anything unless the user agrees" in ctx["additionalContext"]
    assert events(home) == []


@pytest.mark.parametrize("event", ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"])
def test_without_python_other_hooks_end_quietly(bindir, tmp_path, event, plugin):
    res = run(bindir, tmp_path / "control", event, plugin=plugin)
    assert (res.returncode, res.stdout, res.stderr) == (0, "", "")


def test_python_older_than_3_9_counts_as_missing(bindir, tmp_path, plugin):
    fake = bindir / "python3"
    # 버전 확인(-c)에 1로 답하는 옛 파이썬 흉내. emit.py를 부르면 표시를 남긴다.
    fake.write_text(f'#!/bin/sh\n[ "$1" = -c ] && exit 1\n: > "{tmp_path}/ran"\n')
    fake.chmod(0o755)
    res = run(bindir, tmp_path / "control", "SessionStart", plugin=plugin)
    assert "systemMessage" in json.loads(res.stdout)
    assert not (tmp_path / "ran").exists()


def test_hands_over_to_the_rust_engine_when_it_is_shipped(tmp_path, bindir, plugin):
    """bin/nunchi-engine이 돌면 파이썬을 찾지 않고 그것을 부른다 (요구 이력 68)."""
    add_engine(plugin, f'[ "$1" = --version ] && exit 0\nread -r line\nprintf "%s|%s" "$1" "$line" > "{tmp_path}/called"\n')
    res = subprocess.run(["/bin/sh", str(plugin / "hooks" / "emit.sh")], input='{"hook_event_name":"Stop"}\n', capture_output=True,
                         text=True, env={"PATH": str(bindir)}, timeout=20)
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "called").read_text() == 'hook|{"hook_event_name":"Stop"}'


def test_engine_that_cannot_run_falls_back_to_python_in_a_repository_copy(tmp_path, bindir, plugin):
    """엔진이 --version에 답하지 못하면(다른 OS, 깨진 파일) exec하지 않는다. 저장소 사본이면 파이썬 기록기로 (요구 이력 69)"""
    add_engine(plugin, f': > "{tmp_path}/engine-ran"\nexit 126\n')
    (bindir / "python3").symlink_to(sys.executable)
    home = tmp_path / "control"
    res = run(bindir, home, "Stop", plugin=plugin)
    assert (res.returncode, res.stdout, res.stderr) == (0, "", "")
    assert events(home) == ["Stop"]


@pytest.mark.parametrize("event", ["SessionStart", "Stop"])
def test_distribution_with_an_engine_that_cannot_run_tells_once(tmp_path, bindir, plugin, event):
    """배포용 브랜치(파이썬 기록기 없음)에서 엔진이 돌지 못하면: 시작 때 한 번 알리고, 다른 훅은 조용히"""
    (plugin / "hooks" / "emit.py").unlink()
    add_engine(plugin, "exit 1\n")
    res = run(bindir, tmp_path / "control", event, plugin=plugin)
    assert res.returncode == 0 and res.stderr == ""
    if event == "SessionStart":
        out = json.loads(res.stdout)
        assert "bin/nunchi-engine" in out["systemMessage"] and "claude plugin update nunchi@nunchi" in out["systemMessage"]
        assert "Do not change anything unless the user agrees" in out["hookSpecificOutput"]["additionalContext"]
    else:
        assert res.stdout == ""
