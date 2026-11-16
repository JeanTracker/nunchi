"""§6 실험 스크립트의 안전 장치 확인. 실제 iTerm에는 아무것도 보내지 않는다."""

import importlib.util
from pathlib import Path

import pytest

from control_tui import panels
from control_tui.adapters import iterm2_adapter

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def no_send(monkeypatch):
    """어떤 경로로든 전송이 일어나면 테스트를 실패시킨다."""
    def boom(self, target_id, text, enter=True):
        raise AssertionError(f"실험 스크립트가 테스트 중 전송을 시도: {target_id}")
    monkeypatch.setattr(iterm2_adapter.ITerm2Adapter, "send_text", boom)


def alive(monkeypatch, ids):
    monkeypatch.setattr(panels, "claude_panel_ids", lambda: set(ids))


# ---------- 일하는 중 입력 실험 ----------

def test_busy_probe_refuses_when_no_claude_on_panel(monkeypatch, no_send, capsys):
    alive(monkeypatch, [])
    mod = load("probe_send_while_busy")
    assert mod.main(["--panel", "EXP-1", "--send"]) == 2
    assert "claude가 떠 있지 않습니다" in capsys.readouterr().out


def test_busy_probe_is_dry_run_by_default(monkeypatch, no_send, capsys):
    alive(monkeypatch, ["EXP-1"])
    mod = load("probe_send_while_busy")
    assert mod.main(["--panel", "EXP-1"]) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out and "EXP-1" in out


def test_busy_probe_sends_two_steps_only_with_send_flag(monkeypatch, capsys):
    alive(monkeypatch, ["EXP-1"])
    calls = []
    monkeypatch.setattr(iterm2_adapter.ITerm2Adapter, "send_text",
                        lambda self, t, text, enter=True: calls.append((t, text)))
    mod = load("probe_send_while_busy")
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    assert mod.main(["--panel", "EXP-1", "--send"]) == 0
    assert [t for t, _ in calls] == ["EXP-1", "EXP-1"]
    assert calls[0][1] == mod.FIRST and calls[1][1] == mod.SECOND


# ---------- 허락 창 키 실험 ----------

def test_permission_probe_refuses_without_claude(monkeypatch, no_send, capsys):
    alive(monkeypatch, [])
    mod = load("probe_permission_keys")
    assert mod.main(["--panel", "EXP-1", "--key", "y", "--send", "--confirm-prompt-open"]) == 2


def test_permission_probe_needs_both_flags_to_send(monkeypatch, no_send, capsys):
    alive(monkeypatch, ["EXP-1"])
    mod = load("probe_permission_keys")
    assert mod.main(["--panel", "EXP-1", "--key", "y"]) == 0          # dry-run
    assert mod.main(["--panel", "EXP-1", "--key", "y", "--send"]) == 2  # 확인 없이 보내기 거부
    assert "--confirm-prompt-open" in capsys.readouterr().out


def test_permission_probe_only_accepts_y_or_n():
    mod = load("probe_permission_keys")
    with pytest.raises(SystemExit):
        mod.main(["--panel", "EXP-1", "--key", "\r"])  # Enter는 받지 않는다


def test_permission_probe_sends_key_without_enter(monkeypatch):
    alive(monkeypatch, ["EXP-1"])
    calls = []
    monkeypatch.setattr(iterm2_adapter.ITerm2Adapter, "send_text",
                        lambda self, t, text, enter=True: calls.append((t, text, enter)))
    mod = load("probe_permission_keys")
    assert mod.main(["--panel", "EXP-1", "--key", "n", "--send", "--confirm-prompt-open"]) == 0
    assert calls == [("EXP-1", "n", False)]
