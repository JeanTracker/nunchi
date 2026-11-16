"""테스트는 이 맥의 실제 iTerm 패널을 보지 않는다. 필요한 테스트만 가짜 스캐너를 넣는다."""

import pytest

from control_tui import panels
from control_tui.adapters import iterm2_adapter


@pytest.fixture(autouse=True)
def no_real_iterm_panels(monkeypatch):
    monkeypatch.setattr(panels, "scan", lambda known_panel_ids: [])


@pytest.fixture(autouse=True)
def no_real_iterm_send(monkeypatch):
    """테스트가 실제 iTerm 패널에 글을 보내지 못하게 막는다. 보내는 척은 가짜 터미널로만 한다."""
    def blocked(args):
        raise AssertionError(f"테스트에서 실제 iTerm 전송 시도: {args[0]}")
    monkeypatch.setattr(iterm2_adapter, "_osascript", blocked)


@pytest.fixture(autouse=True)
def no_real_analyzer(monkeypatch):
    """테스트에서는 분석기를 켜지 않는다 (claude를 실제로 부르지 않는다). 분석기 테스트는 직접 넣는다."""
    monkeypatch.setenv("CONTROL_TUI_ANALYZE", "0")


@pytest.fixture(autouse=True)
def no_real_claude_panel_check(monkeypatch):
    """테스트는 실제 프로세스 목록을 보지 않는다. 필요한 테스트만 패널 목록을 넣는다."""
    monkeypatch.setattr(panels, "claude_panel_ids", lambda: set())


@pytest.fixture(autouse=True)
def no_real_clipboard(monkeypatch):
    """테스트는 사용자의 맥 클립보드를 읽거나 덮어쓰지 않는다. 클립보드 테스트는 가짜를 넣는다."""
    from control_tui import clipboard
    monkeypatch.setattr(clipboard.MacClipboard, "write", lambda self, text: False)
    monkeypatch.setattr(clipboard.MacClipboard, "read", lambda self: None)


@pytest.fixture(autouse=True)
def no_real_liveness_check(monkeypatch):
    """닫힌 세션 판정은 기본적으로 '확인 못 함'(None)으로 둔다. 판정 테스트는 직접 넣는다."""
    monkeypatch.setattr(panels, "alive_panel_ids", lambda: None)


@pytest.fixture(autouse=True)
def no_real_control_home(monkeypatch, tmp_path_factory):
    """관제 홈을 주지 않은 테스트가 실제 ~/.claude-control에 control.json·goto를 쓰거나 지우지 않게 한다 (요구 이력 56)."""
    monkeypatch.setenv("CONTROL_TUI_HOME", str(tmp_path_factory.mktemp("control-home")))
