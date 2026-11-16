"""Phase 1 보완: 설치 전에 열린 세션을 "연결 대기"로 올린다 (BUILD_PLAN §3.4, SCREEN §2 ①)."""

import json

import pytest

from control_tui import panels
from control_tui.app import ControlApp

# conftest가 테스트마다 panels.claude_panel_ids를 빈 결과로 바꾸므로, 원래 함수는 불러올 때 잡아 둔다
REAL_CLAUDE_PANEL_IDS = panels.claude_panel_ids


# ---------- 순수 함수 ----------

def test_parse_panels_keeps_names_with_commas():
    text = "AAAA-1\t/dev/ttys000\tclaude, 테스트 (node)\nBBBB-2\t/dev/ttys001\t셸\n"
    got = panels.parse_panels(text)
    assert [p.panel_id for p in got] == ["AAAA-1", "BBBB-2"]
    assert got[0].tty == "/dev/ttys000" and got[0].name == "claude, 테스트 (node)"


def test_claude_procs_only_terminal_attached_claude():
    # ps -axo pid=,ppid=,tty=,command= 형식
    ps = "\n".join([
        "13195   900 ??       /Users/x/Library/Application Support/Claude/claude-code/2.1/claude --output-format stream-json",
        "23140   901 ttys000  claude --continue",
        "24179   902 ttys001  claude",
        "25000   903 ttys002  /bin/zsh -c source snapshot.sh && claude",
        "26000   904 ttys003  node /usr/lib/claude-helper.js",
    ])
    got = panels.parse_claude_procs(ps)
    assert [(p.pid, p.tty) for p in got] == [(23140, "/dev/ttys000"), (24179, "/dev/ttys001")]


# 2026-11-10 이 맥의 실제 모양: amask가 claude를 자기 가상 터미널(ttys001)에서 돌린다.
AMASK_PS = "\n".join([
    "  600     1 ??       /Applications/iTerm.app/Contents/MacOS/iTerm2",
    " 4390   600 ttys000  /usr/bin/login -fpl user /Applications/iTerm.app/Contents/MacOS/ShellLauncher",
    " 4398  4390 ttys000  -zsh",
    " 4830  4398 ttys000  /opt/homebrew/.../Python /Users/x/.local/bin/amask claude",
    " 4833  4830 ttys001  claude --settings {\"hooks\":{}} --plugin-dir /Users/x/.local/share/amask/mod",
    " 4991   600 ttys002  -zsh",
])


def test_claude_under_wrapper_is_found_on_the_panel_tty():
    [proc] = panels.parse_claude_procs(AMASK_PS)
    assert proc.pid == 4833 and proc.tty == "/dev/ttys001"
    assert proc.ttys() == ["/dev/ttys001", "/dev/ttys000"]
    pans = [panels.Panel("WRAPPED", "/dev/ttys000", ""), panels.Panel("SHELL", "/dev/ttys002", "")]
    got = panels.unlinked_panels(pans, [proc], known_panel_ids=set())
    assert [p.panel_id for p, _ in got] == ["WRAPPED"]


def test_wrapper_without_claude_is_not_a_claude_panel():
    # claude가 끝나 amask만 남았거나, 셸로 돌아간 패널은 claude 패널이 아니다
    ps = "\n".join(l for l in AMASK_PS.splitlines() if " 4833 " not in l)
    assert panels.parse_claude_procs(ps) == []


def test_claude_panel_ids_uses_parent_ttys(monkeypatch):
    rows = "WRAPPED\t/dev/ttys000\tclaude\nSHELL\t/dev/ttys002\tzsh\n"
    monkeypatch.setattr(panels, "iterm_running", lambda *a: True)
    monkeypatch.setattr(panels, "_run", lambda args, script=None: rows if args[0] == "osascript" else AMASK_PS)
    assert REAL_CLAUDE_PANEL_IDS() == {"WRAPPED"}


def test_own_tty_wins_over_parent_tty():
    # 패널 A에서 바로 띄운 claude와, 패널 A의 무언가가 낳은 다른 claude가 있으면 A는 자기 tty의 claude와 짝짓는다
    direct = panels.ClaudeProc(pid=10, tty="/dev/ttys000")
    nested = panels.ClaudeProc(pid=20, tty="/dev/ttys009", via=("/dev/ttys000",))
    got = panels.unlinked_panels([panels.Panel("A", "/dev/ttys000", "")], [nested, direct], set())
    assert got[0][1].pid == 10


def test_parent_walk_stops_on_cycles():
    ps = "\n".join(["10 20 ttys001  claude", "20 10 ttys000  amask claude"])
    [proc] = panels.parse_claude_procs(ps)
    assert proc.ttys() == ["/dev/ttys001", "/dev/ttys000"]


def test_unlinked_panels_skips_panels_with_events_and_without_claude():
    ps = [panels.ClaudeProc(pid=1, tty="/dev/ttys000"), panels.ClaudeProc(pid=2, tty="/dev/ttys001")]
    pans = [
        panels.Panel("LINKED", "/dev/ttys000", ""),   # 훅 기록이 있는 패널
        panels.Panel("PENDING", "/dev/ttys001", ""),  # 설치 전에 열림
        panels.Panel("SHELL", "/dev/ttys009", ""),    # claude 없는 셸
    ]
    got = panels.unlinked_panels(pans, ps, known_panel_ids={"LINKED"})
    assert [p.panel_id for p, _ in got] == ["PENDING"]


def test_panel_id_is_taken_from_iterm_session_env():
    assert panels.panel_id_of("w0t0p0:0F0E4DA4-176A") == "0F0E4DA4-176A"
    assert panels.panel_id_of("") == ""


# ---------- 화면 ----------

class FakeScanner:
    def __init__(self, views):
        self.views = views
        self.calls = 0

    def __call__(self, known_ids):
        self.calls += 1
        return [v for v in self.views if v.iterm_session_id not in known_ids]


def write_events(home, sid, rows):
    d = home / "sessions" / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def pending_view(panel_id="PANEL-AAAA-1111"):
    return panels.to_pending_view(panels.Panel(panel_id, "/dev/ttys000", ""),
                                  panels.ClaudeProc(1, "/dev/ttys000"), "/work/demo")


@pytest.mark.asyncio
async def test_pending_panel_shows_as_connecting_then_links_after_restart(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    scanner = FakeScanner([pending_view()])
    app = ControlApp(home=home, panel_scanner=scanner)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        text = str(app.session_list.render_text())
        assert "연결 대기" in text and "demo" in text
        assert "설치 전에 열린 세션" in str(app.conversation.render_text())

        # 같은 패널에서 Claude를 다시 시작하면 훅 기록이 생긴다
        write_events(home, "new-session", [{
            "ts": "2026-11-09T01:00:00.000Z", "session_id": "new-session", "event": "SessionStart",
            "cwd": "/work/demo", "transcript_path": "", "iterm_session_id": "w0t0p0:PANEL-AAAA-1111",
            "data": {"source": "startup"}}])
        app.refresh_sessions()
        await pilot.pause()
        text = str(app.session_list.render_text())
        assert "연결 대기" not in text
        assert [v.session_id for v in app.session_list.views] == ["new-session"]


@pytest.mark.asyncio
async def test_scan_is_throttled_not_every_tick(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    scanner = FakeScanner([pending_view()])
    app = ControlApp(home=home, panel_scanner=scanner)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        for _ in range(5):
            app.refresh_sessions()
        assert scanner.calls == 1


def test_iterm_running_reads_ps_comm_not_pgrep():
    """iTerm2 패널 안에서는 pgrep -x iTerm2가 iTerm2를 못 찾았다 (2026-11-09 실험). ps comm으로 판정한다."""
    from control_tui import panels as p
    ps_comm = "/sbin/launchd\n/Applications/iTerm.app/Contents/MacOS/iTerm2\n-zsh\n"
    assert p.iterm_running(ps_comm) is True
    assert p.iterm_running("/sbin/launchd\n/Applications/iTermHelper\n") is False
