"""Phase 1 완료 확인 테스트: 수집 (statusline, install_hooks, fake_events).

훅 기록기는 러스트 엔진으로 옮겼다(요구 이력 68 R2). 그 시험은 crates/engine/tests(hook_records 시나리오, engine_details)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
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


def test_backups_in_the_same_second_keep_the_first(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text('{"model": "x"}', encoding="utf-8")
    run(INSTALL, args=["--settings", str(s), "--apply"])
    run(INSTALL, args=["--settings", str(s), "--remove", "--apply"])
    run(INSTALL, args=["--settings", str(s), "--apply"])
    texts = sorted(b.read_text(encoding="utf-8") for b in tmp_path.glob("settings.json.bak-*"))
    assert len(texts) == 3
    assert '{"model": "x"}' in texts


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
    assert "emit.py" not in json.dumps(after["hooks"]) and "emit.sh" not in json.dumps(after["hooks"])
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

@pytest.fixture(scope="module")
def built_engine():
    res = subprocess.run(["cargo", "build", "-q", "-p", "nunchi-engine", "--bin", "nunchi-engine"], cwd=ROOT,
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return ROOT / "target" / "debug" / "nunchi-engine"


def test_fake_normal_scenario_writes_five_events(home, built_engine):
    res = run(FAKE, args=["normal"], env={"CONTROL_TUI_HOME": str(home), "NUNCHI_ENGINE": str(built_engine)})
    assert res.returncode == 0
    lines = (home / "sessions" / "fake-normal" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert json.loads(lines[-1])["event"] == "Stop"


def test_registering_again_replaces_this_folders_old_python_hook(tmp_path):
    """예전 설치가 넣은 이 폴더의 emit.py 훅(파일은 지웠다)은 emit.sh로 바꾼다. 다른 폴더 것은 그대로 알린다 (요구 이력 68)"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import install_hooks
    old = f"/x/python {ROOT}/hooks/emit.py"
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": old}]}]}}), encoding="utf-8")
    run(INSTALL, args=["--settings", str(s), "--apply"])
    cmds = [h["command"] for g in json.loads(s.read_text())["hooks"]["Stop"] for h in g["hooks"]]
    assert cmds == [install_hooks.emit_command()] and "hooks/emit.sh" in cmds[0]
    run(INSTALL, args=["--settings", str(s), "--remove", "--apply"])
    assert "hooks" not in json.loads(s.read_text())
