"""이미 열린 세션 찾기 (BUILD_PLAN §3.4, SCREEN §2 ①).

관제 설치 전에 열린 claude 세션은 훅 이벤트가 없어서 목록에 나타나지 않는다.
그래서 iTerm2 패널을 훑어, claude 프로세스가 도는 패널을 "연결 대기"로 올린다.

- 패널 목록: iTerm2 AppleScript (패널 UUID, tty, 이름)
- claude 프로세스: ps (tty가 붙은 claude 실행 파일만)
- 짝짓기: tty만 쓴다. cwd로 짐작하지 않는다.
  claude 자신의 tty가 패널과 다르면 부모 프로세스를 따라 올라가 패널 tty에 닿는지 본다.
  amask처럼 claude를 자기 가상 터미널에서 돌리는 감싸기 도구가 있기 때문이다
  (2026-11-10 확인: 패널 ttys000 → amask ttys000 → claude ttys001).
- 훅 이벤트의 iterm_session_id와 패널 UUID가 같으면 이미 연결된 것이므로 제외한다.
"""

import os
import subprocess
from dataclasses import dataclass

from control_tui.store import SessionView

ITERM_SCRIPT = """
# "tab"은 iTerm2의 탭 객체 이름과 겹치므로 문자 코드를 쓴다
tell application "iTerm2"
    set out to ""
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                set out to out & (id of s) & (ASCII character 9) & (tty of s) & (ASCII character 9) & (name of s) & (ASCII character 10)
            end repeat
        end repeat
    end repeat
    return out
end tell
"""


@dataclass
class Panel:
    panel_id: str  # iTerm 패널 UUID (ITERM_SESSION_ID에서 콜론 뒤)
    tty: str  # /dev/ttysNNN
    name: str


PS_ARGS = ["ps", "-axo", "pid=,ppid=,tty=,command="]
MAX_ANCESTORS = 16  # 부모를 따라 올라가는 최대 단계 (고리 방지)


@dataclass
class ClaudeProc:
    pid: int
    tty: str  # /dev/ttysNNN (claude 자신)
    via: tuple = ()  # 부모 프로세스들의 tty, 가까운 순 (감싸기 도구가 있으면 여기에 패널 tty가 있다)

    def ttys(self) -> list:
        """이 claude가 걸쳐 있는 tty들. 자기 것이 먼저다."""
        out = [self.tty]
        for t in self.via:
            if t not in out:
                out.append(t)
        return out


def panel_id_of(iterm_session_id: str) -> str:
    """'w0t0p0:UUID' 형태에서 UUID만 꺼낸다."""
    return (iterm_session_id or "").split(":")[-1]


def parse_panels(text: str) -> list:
    panels = []
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2 or not parts[0].strip():
            continue
        name = parts[2] if len(parts) == 3 else ""
        panels.append(Panel(panel_id=parts[0].strip(), tty=parts[1].strip(), name=name))
    return panels


def _parse_ps(ps_text: str) -> dict:
    """ps -axo pid=,ppid=,tty=,command= 출력 → {pid: (ppid, tty, command)}."""
    table = {}
    for line in ps_text.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        try:
            table[int(parts[0])] = (int(parts[1]), parts[2], parts[3])
        except ValueError:
            continue
    return table


def _has_tty(tty: str) -> bool:
    return tty not in ("??", "?", "")


def _ancestor_ttys(table: dict, pid: int) -> tuple:
    out = []
    seen = {pid}
    ppid = table[pid][0]
    for _ in range(MAX_ANCESTORS):
        if ppid <= 1 or ppid in seen or ppid not in table:
            break
        seen.add(ppid)
        parent_ppid, tty, _cmd = table[ppid]
        if _has_tty(tty):
            out.append(f"/dev/{tty}")
        ppid = parent_ppid
    return tuple(out)


def parse_claude_procs(ps_text: str) -> list:
    """ps -axo pid=,ppid=,tty=,command= 출력에서 터미널에 붙은 claude 프로세스만 고른다.

    데스크톱 앱 내부 claude는 tty가 ??이므로 자연스럽게 제외된다.
    """
    table = _parse_ps(ps_text)
    procs = []
    for pid, (_ppid, tty, command) in table.items():
        if not _has_tty(tty):
            continue
        argv0 = command.split()[0]
        if os.path.basename(argv0) != "claude":
            continue
        procs.append(ClaudeProc(pid=pid, tty=f"/dev/{tty}", via=_ancestor_ttys(table, pid)))
    return procs


def _by_tty(procs: list) -> dict:
    """tty → claude. claude 자신의 tty를 부모 쪽 tty보다 먼저 잡는다."""
    out = {}
    for p in procs:
        out.setdefault(p.tty, p)
    for p in procs:
        for t in p.ttys():
            out.setdefault(t, p)
    return out


def unlinked_panels(panels: list, procs: list, known_panel_ids: set) -> list:
    """claude가 도는 패널 중, 훅 기록과 아직 짝이 없는 패널만 돌려준다."""
    claude_ttys = _by_tty(procs)
    out = []
    for panel in panels:
        if panel.tty not in claude_ttys:
            continue
        if panel.panel_id in known_panel_ids:
            continue
        out.append((panel, claude_ttys[panel.tty]))
    return out


def to_pending_view(panel: Panel, proc: ClaudeProc, cwd: str) -> SessionView:
    return SessionView(
        session_id=panel.panel_id[:8],
        cwd=cwd,
        state="pending",
        last_ts="",
        iterm_session_id=panel.panel_id,
    )


def _run(args: list, script: str = None) -> str:
    result = subprocess.run(args, input=script, capture_output=True, text=True, timeout=8)
    return result.stdout if result.returncode == 0 else ""


def iterm_running(ps_comm: str = None) -> bool:
    """iTerm2가 켜져 있는지. pgrep 대신 ps를 본다.

    iTerm2 패널 안에서 돈 pgrep -x iTerm2는 iTerm2를 찾지 못했다(2026-11-09 실제 패널에서 확인, 종료 코드 1).
    관제는 늘 iTerm2 패널 안에서 돌기 때문에, 이 확인이 틀리면 보내기와 연결 대기 찾기가 모두 막힌다.
    """
    text = ps_comm if ps_comm is not None else _run(["ps", "-axo", "comm="])
    return any(os.path.basename(line.strip()) == "iTerm2" for line in text.splitlines())


def claude_panel_ids() -> set:
    """지금 claude가 떠 있는 iTerm 패널 UUID 모음. 글을 보내기 전 패널 상태를 확인한다 (읽기 전용).

    셸로 돌아간 패널이나 닫힌 패널에는 보내지 않기 위한 장치다. 명령으로 실행되면 안 되기 때문이다.
    """
    if not iterm_running():
        return set()
    panel_rows = parse_panels(_run(["osascript", "-"], script=ITERM_SCRIPT))
    procs = parse_claude_procs(_run(PS_ARGS))
    ttys = _by_tty(procs)
    return {p.panel_id for p in panel_rows if p.tty in ttys}


def alive_panel_ids() -> set | None:
    """claude가 떠 있는 패널 UUID 모음. 확인하지 못했으면 None (닫힌 세션 판정용, BUILD_PLAN §3.1.1).

    claude_panel_ids는 확인 실패도 빈 모음으로 돌려준다. 보내기에서는 그래도 안전하지만(안 보낼 뿐),
    닫힘 판정에서 그렇게 하면 모든 세션이 한꺼번에 종료로 바뀐다. 관제 자신이 iTerm 패널 안에서 돌므로
    패널 목록이 비었다면 확인이 실패한 것이다.
    """
    if not iterm_running():
        return None
    panel_rows = parse_panels(_run(["osascript", "-"], script=ITERM_SCRIPT))
    ps_text = _run(PS_ARGS)
    if not panel_rows or not ps_text.strip():
        return None
    ttys = _by_tty(parse_claude_procs(ps_text))
    return {p.panel_id for p in panel_rows if p.tty in ttys}


def _cwd_of(pid: int) -> str:
    out = _run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:]
    return ""


def scan(known_panel_ids: set) -> list:
    """현재 iTerm 패널 중 연결 대기 세션을 SessionView 목록으로 돌려준다.

    iTerm2가 켜져 있지 않으면 아무것도 하지 않는다 (osascript가 iTerm을 깨우지 않도록).
    """
    if not iterm_running():
        return []
    panels = parse_panels(_run(["osascript", "-"], script=ITERM_SCRIPT))
    procs = parse_claude_procs(_run(PS_ARGS))
    return [to_pending_view(panel, proc, _cwd_of(proc.pid))
            for panel, proc in unlinked_panels(panels, procs, known_panel_ids)]
