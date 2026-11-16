"""osascript가 멈추거나 없으면 TerminalError로 알린다. 관제(일꾼 스레드)가 통째로 꺼지지 않게 (리뷰 2026-11-16)."""
import importlib.util
import subprocess

import pytest

from control_tui.adapters.terminal_base import TerminalError


def real_module():
    # conftest가 _osascript를 막아 두므로, 같은 파일을 따로 읽어 진짜 함수를 쓴다
    import control_tui.adapters.iterm2_adapter as m
    spec = importlib.util.spec_from_file_location("iterm2_adapter_real", m.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("err", [subprocess.TimeoutExpired(["osascript"], 8), FileNotFoundError("osascript")])
def test_hang_or_missing_osascript_is_a_terminal_error(monkeypatch, err):
    mod = real_module()

    def boom(*a, **k):
        raise err
    monkeypatch.setattr(mod.subprocess, "run", boom)
    with pytest.raises(TerminalError):
        mod._osascript(["x"])
