"""Phase 1 완료 확인 테스트: 수집 (emit, statusline, install_hooks, fake_events)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EMIT = ROOT / "hooks" / "emit.py"
STATUSLINE = ROOT / "hooks" / "statusline.py"
INSTALL = ROOT / "scripts" / "install_hooks.py"
FAKE = ROOT / "scripts" / "fake_events.py"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "control"
    monkeypatch.setenv("CONTROL_TUI_HOME", str(h))
    return h


def run(script, stdin="", env=None, args=()):
    full_env = {**os.environ, **(env or {})}
    return subprocess.run([sys.executable, str(script), *args], input=stdin,
                          capture_output=True, text=True, env=full_env, timeout=20)


def payload(**kw):
    return json.dumps({"session_id": "s1", "cwd": "/work/a",
                       "transcript_path": "/none.jsonl", **kw})


# ---------- emit.py ----------

def test_emit_writes_one_line_per_event(home):
    run(EMIT, payload(hook_event_name="UserPromptSubmit", prompt="안녕"), env={"CONTROL_TUI_HOME": str(home)})
    lines = (home / "sessions" / "s1" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event"] == "UserPromptSubmit"
    assert rec["data"]["prompt"] == "안녕"
    assert rec["cwd"] == "/work/a"


def test_emit_takes_iterm_session_from_env(home):
    run(EMIT, payload(hook_event_name="Stop"),
        env={"CONTROL_TUI_HOME": str(home), "ITERM_SESSION_ID": "w0t1p0:ABCD"})
    rec = json.loads((home / "sessions" / "s1" / "events.jsonl").read_text(encoding="utf-8"))
    assert rec["iterm_session_id"] == "w0t1p0:ABCD"


def test_emit_cuts_long_text_to_500_chars(home):
    run(EMIT, payload(hook_event_name="UserPromptSubmit", prompt="가" * 2000),
        env={"CONTROL_TUI_HOME": str(home)})
    rec = json.loads((home / "sessions" / "s1" / "events.jsonl").read_text(encoding="utf-8"))
    assert len(rec["data"]["prompt"]) == 500


def test_analyzer_mode_records_nothing(home):
    res = run(EMIT, payload(hook_event_name="Stop"),
              env={"CONTROL_TUI_HOME": str(home), "CONTROL_TUI_ANALYZER": "1"})
    assert res.returncode == 0
    assert not (home / "sessions").exists()


def test_bad_input_exits_zero_and_logs_error(home):
    res = run(EMIT, "이건 JSON이 아님", env={"CONTROL_TUI_HOME": str(home)})
    assert res.returncode == 0
    assert (home / "errors.log").exists()


def test_precompact_saves_transcript_copy(home, tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text('{"x": 1}\n', encoding="utf-8")
    run(EMIT, payload(hook_event_name="PreCompact", transcript_path=str(transcript), trigger="manual"),
        env={"CONTROL_TUI_HOME": str(home)})
    assert (home / "sessions" / "s1" / "compact-1.jsonl").read_text(encoding="utf-8") == '{"x": 1}\n'


def test_emit_is_fast_enough(home):
    # 목표는 50ms지만, 파이썬 시작 시간이 포함되므로 여기서는 1초 안에 끝나는지만 본다.
    import time
    t0 = time.perf_counter()
    run(EMIT, payload(hook_event_name="Stop"), env={"CONTROL_TUI_HOME": str(home)})
    assert time.perf_counter() - t0 < 1.0


# ---------- statusline.py ----------

def test_statusline_records_context_and_prints_original(home):
    res = run(STATUSLINE, json.dumps({"session_id": "s1", "context_window": {"used_percentage": 44}}),
              env={"CONTROL_TUI_HOME": str(home), "CONTROL_TUI_ORIG_STATUSLINE": "echo 원래 줄"})
    assert res.stdout.strip() == "원래 줄"
    ctx = json.loads((home / "sessions" / "s1" / "context.json").read_text(encoding="utf-8"))
    assert ctx["used_percentage"] == 44


# ---------- install_hooks.py ----------

def test_preview_does_not_change_settings(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text('{"model": "x"}', encoding="utf-8")
    res = run(INSTALL, args=["--settings", str(s)])
    assert res.returncode == 0
    assert s.read_text(encoding="utf-8") == '{"model": "x"}'
    assert "미리보기" in res.stdout


def test_apply_adds_all_events_once_and_keeps_others(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"model": "x", "statusLine": {"type": "command", "command": "echo old"}}),
                 encoding="utf-8")
    run(INSTALL, args=["--settings", str(s), "--apply"])
    data = json.loads(s.read_text(encoding="utf-8"))
    assert data["model"] == "x"
    for ev in ["SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
               "PostToolUseFailure", "Stop", "Notification", "PreCompact", "PostCompact"]:
        assert ev in data["hooks"]
    assert "SubagentStart" not in data["hooks"]
    assert "SubagentStop" not in data["hooks"]
    assert "statusline.py" in data["statusLine"]["command"]
    assert "echo old" in data["statusLine"]["command"]
    # 두 번째 실행은 아무것도 바꾸지 않는다
    res = run(INSTALL, args=["--settings", str(s), "--apply"])
    assert "바뀔 내용이 없습니다" in res.stdout
    assert json.loads(s.read_text(encoding="utf-8")) == data


def test_apply_makes_backup(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text('{"model": "x"}', encoding="utf-8")
    run(INSTALL, args=["--settings", str(s), "--apply"])
    backups = list(tmp_path.glob("settings.json.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"model": "x"}'


def test_remove_restores_original_settings(tmp_path):
    original = {"model": "x",
                "statusLine": {"type": "command", "command": "bash ~/my status.sh", "padding": 0},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}
    s = tmp_path / "settings.json"
    s.write_text(json.dumps(original), encoding="utf-8")
    run(INSTALL, args=["--settings", str(s), "--apply"])
    assert json.loads(s.read_text(encoding="utf-8")) != original
    res = run(INSTALL, args=["--settings", str(s), "--remove", "--apply"])
    assert res.returncode == 0
    assert json.loads(s.read_text(encoding="utf-8")) == original
    # 두 번째 제거는 아무것도 바꾸지 않는다
    res = run(INSTALL, args=["--settings", str(s), "--remove", "--apply"])
    assert "지울 내용이 없습니다" in res.stdout


def test_remove_drops_statusline_we_added_alone(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text('{"model": "x"}', encoding="utf-8")
    run(INSTALL, args=["--settings", str(s), "--apply"])
    run(INSTALL, args=["--settings", str(s), "--remove", "--apply"])
    assert json.loads(s.read_text(encoding="utf-8")) == {"model": "x"}


def test_remove_leaves_rewrapped_statusline_and_warns(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text('{}', encoding="utf-8")
    run(INSTALL, args=["--settings", str(s), "--apply"])
    data = json.loads(s.read_text(encoding="utf-8"))
    data["statusLine"]["command"] = "other-tool --wrap " + data["statusLine"]["command"]
    s.write_text(json.dumps(data), encoding="utf-8")
    res = run(INSTALL, args=["--settings", str(s), "--remove", "--apply"])
    after = json.loads(s.read_text(encoding="utf-8"))
    assert after["statusLine"] == data["statusLine"]
    assert "hooks" not in after
    assert "statusLine 모양이 예상과 달라" in res.stderr


def test_check_exit_code_reports_pending_change(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text('{}', encoding="utf-8")
    assert run(INSTALL, args=["--settings", str(s), "--check"]).returncode == 1
    assert s.read_text(encoding="utf-8") == '{}'
    run(INSTALL, args=["--settings", str(s), "--apply"])
    assert run(INSTALL, args=["--settings", str(s), "--check"]).returncode == 0


def test_warns_when_another_folder_registered_hooks(tmp_path):
    s = tmp_path / "settings.json"
    other = {"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "/x/python /elsewhere/nunchi/hooks/emit.py"}]}]}}
    s.write_text(json.dumps(other), encoding="utf-8")
    res = run(INSTALL, args=["--settings", str(s)])
    assert "다른 폴더에서 등록한 관제 훅" in res.stderr


def test_plugin_mode_drops_hooks_of_every_folder_and_keeps_others(tmp_path):
    """플러그인이 훅을 맡으면 settings.json의 관제 훅은 어느 폴더 것이든 뺀다 (요구 이력 63)."""
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"model": "x", "statusLine": {"type": "command", "command": "echo old"}}),
                 encoding="utf-8")
    run(INSTALL, args=["--settings", str(s), "--apply"])        # 이 폴더의 옛 설치
    data = json.loads(s.read_text(encoding="utf-8"))
    data["hooks"]["Stop"].append({"hooks": [
        {"type": "command", "command": "/x/python /elsewhere/nunchi/hooks/emit.py"},
        {"type": "command", "command": "say done"}]})
    s.write_text(json.dumps(data), encoding="utf-8")

    res = run(INSTALL, args=["--settings", str(s), "--plugin", "--apply"])
    assert res.returncode == 0, res.stderr
    assert "/elsewhere/nunchi/hooks/emit.py" in res.stderr       # 다른 폴더 것도 뺀다고 알린다
    after = json.loads(s.read_text(encoding="utf-8"))
    assert "emit.py" not in json.dumps(after["hooks"])
    assert after["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}
    assert "statusline.py" in after["statusLine"]["command"]     # 상태 표시줄 감싸기는 둔다
    assert "echo old" in after["statusLine"]["command"]
    assert len(list(tmp_path.glob("settings.json.bak-*"))) == 2
    res = run(INSTALL, args=["--settings", str(s), "--plugin", "--apply"])
    assert "바뀔 내용이 없습니다" in res.stdout


def test_plugin_mode_then_remove_restores_original(tmp_path):
    original = {"model": "x", "statusLine": {"type": "command", "command": "bash ~/my status.sh"}}
    s = tmp_path / "settings.json"
    s.write_text(json.dumps(original), encoding="utf-8")
    run(INSTALL, args=["--settings", str(s), "--plugin", "--apply"])
    assert "hooks" not in json.loads(s.read_text(encoding="utf-8"))
    run(INSTALL, args=["--settings", str(s), "--remove", "--apply"])
    assert json.loads(s.read_text(encoding="utf-8")) == original


# ---------- fake_events.py ----------

def test_fake_normal_scenario_writes_five_events(home):
    res = run(FAKE, args=["normal"], env={"CONTROL_TUI_HOME": str(home)})
    assert res.returncode == 0
    lines = (home / "sessions" / "fake-normal" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert json.loads(lines[-1])["event"] == "Stop"
