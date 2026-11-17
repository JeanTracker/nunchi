"""플러그인 훅 입구 hooks/emit.sh (요구 이력 67·68·69, BUILD_PLAN §4.12·§4.13).

함께 실린 엔진이 돌면 그것에 넘기고, 엔진이 없거나 돌지 못하면 세션 시작 때만 알린다.
저장소의 hooks/emit.sh를 임시 플러그인 폴더로 복사해서 돌린다: 개발 중 빌드한 bin/nunchi-engine에 휩쓸리지 않게.
PATH는 비워 둔다 (sh는 /bin/sh 절대 경로로 부른다). 셸 내장 기능만으로 돌아야 한다.
"""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def plugin(tmp_path):
    p = tmp_path / "plugin"
    (p / "hooks").mkdir(parents=True)
    (p / "hooks" / "emit.sh").write_text((ROOT / "hooks" / "emit.sh").read_text())
    (tmp_path / "empty-path").mkdir()
    return p


def add_engine(plugin, body):
    (plugin / "bin").mkdir(exist_ok=True)
    engine = plugin / "bin" / "nunchi-engine"
    engine.write_text("#!/bin/sh\n" + body)
    engine.chmod(0o755)
    return engine


def run(plugin, event, spaced=False):
    payload = {"session_id": "s1", "hook_event_name": event, "cwd": "/work/a", "transcript_path": "/none.jsonl"}
    text = json.dumps(payload) if spaced else json.dumps(payload, separators=(",", ":"))
    return subprocess.run(["/bin/sh", str(plugin / "hooks" / "emit.sh")], input=text, capture_output=True, text=True,
                          env={"PATH": str(plugin.parent / "empty-path")}, timeout=20)


def test_hands_over_to_the_engine(tmp_path, plugin):
    add_engine(plugin, f'[ "$1" = --version ] && exit 0\nread -r line\nprintf "%s|%s" "$1" "$line" > "{tmp_path}/called"\n')
    res = run(plugin, "Stop")
    assert (res.returncode, res.stdout, res.stderr) == (0, "", "")
    assert (tmp_path / "called").read_text() == 'hook|{"session_id":"s1","hook_event_name":"Stop","cwd":"/work/a","transcript_path":"/none.jsonl"}'


@pytest.mark.parametrize("spaced", [False, True])
def test_engine_that_cannot_run_tells_once_at_session_start(tmp_path, plugin, spaced):
    """실행 권한이 있어도 --version에 답하지 못하면(다른 OS, 깨진 파일) exec하지 않는다 (요구 이력 69)"""
    add_engine(plugin, f': > "{tmp_path}/engine-ran"\nexit 126\n')
    res = run(plugin, "SessionStart", spaced=spaced)
    assert res.returncode == 0 and res.stderr == ""
    out = json.loads(res.stdout)
    assert "실행하지 못해" in out["systemMessage"] and "claude plugin update nunchi@nunchi" in out["systemMessage"]
    ctx = out["hookSpecificOutput"]
    assert ctx["hookEventName"] == "SessionStart"
    assert "Do not change anything unless the user agrees" in ctx["additionalContext"]


def test_missing_engine_tells_how_to_build_or_reinstall(plugin):
    res = run(plugin, "SessionStart")
    out = json.loads(res.stdout)
    assert "없어" in out["systemMessage"] and "scripts/build-engine.sh" in out["systemMessage"]
    assert "Do not change anything unless the user agrees" in out["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("with_engine", [False, True])
@pytest.mark.parametrize("event", ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"])
def test_other_hooks_end_quietly_without_a_working_engine(plugin, event, with_engine):
    if with_engine:
        add_engine(plugin, "exit 1\n")
    res = run(plugin, event)
    assert (res.returncode, res.stdout, res.stderr) == (0, "", "")
