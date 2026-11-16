"""닫힌 세션 판정과 ① 목록 배치·숨김 (요청 35, REQUIREMENTS R10, BUILD_PLAN §3.1.1).

- 종료 판정
  1. SessionEnd 훅: store가 그 시각으로 종료를 정한다.
  2. 같은 패널에 종료 안 된 세션이 여럿: 가장 최근 것만 살아 있다 (같은 패널에서 claude를 다시 켬).
  3. 패널 확인: 기록의 패널에 claude가 없으면 종료. 확인이 실패하면(None) 바꾸지 않는다.
     확인은 10초마다라 그 뒤에 기록이 생긴 세션은 판정하지 않는다 (막 켠 세션을 닫혔다고 보지 않게).
- 종료 시각: 관제가 처음 알아챈 시각. 관제를 켠 직후(첫 확인 전)에 알아챈 것은 마지막 기록 시각.
- 배치: 살아 있는 세션(기존 순서) 뒤에 종료 세션(최근 종료순). 종료 뒤 일정 시간이 지나면 숨긴다.
  지금 고른 세션은 숨기지 않는다. 기록 파일은 건드리지 않는다.
"""

from datetime import datetime, timezone

from control_tui import config
from control_tui.panels import panel_id_of

SKIP_STATES = ("ended", "pending")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse(ts: str):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


class ClosedTracker:
    """훅 없이 닫힌 세션을 기억한다. 화면 갱신(1초)마다 mark를 부르고, 패널 확인(10초) 결과는 update_alive로 넣는다."""

    def __init__(self):
        self.alive = None        # 마지막 확인 결과 (패널 UUID 모음). None이면 아직 모름
        self.checked_at = ""     # 마지막으로 확인에 성공한 시각 (UTC 문자열)
        self.noticed: dict = {}  # 세션 → 관제가 종료를 알아챈 시각

    def update_alive(self, alive, at: str) -> None:
        """패널 확인 결과. 실패(None)면 지난 결과를 버리지 않는다."""
        if alive is None:
            return
        self.alive = set(alive)
        self.checked_at = at

    def _close(self, v, now: str) -> None:
        if v.session_id not in self.noticed:
            # 첫 확인 전이면 언제 닫혔는지 모른다. 마지막 기록 시각을 쓴다
            self.noticed[v.session_id] = now if self.checked_at else (v.last_ts or now)
        v.state = "ended"
        v.current_tool = ""
        v.ended_ts = self.noticed[v.session_id]

    def mark(self, views: list, now: str = "") -> None:
        now = now or now_iso()
        closing = set()
        by_panel: dict = {}
        for v in views:
            if v.state in SKIP_STATES or not v.iterm_session_id:
                continue
            by_panel.setdefault(panel_id_of(v.iterm_session_id), []).append(v)
        for group in by_panel.values():
            group.sort(key=lambda v: v.last_ts, reverse=True)
            closing.update(v.session_id for v in group[1:])
            newest = group[0]
            if (self.alive is not None and newest.last_ts < self.checked_at
                    and panel_id_of(newest.iterm_session_id) not in self.alive):
                closing.add(newest.session_id)
        for v in views:
            if v.session_id in closing:
                self._close(v, now)
            elif v.state not in SKIP_STATES:
                self.noticed.pop(v.session_id, None)  # 다시 살아났으면 잊는다


def arrange(views: list, selected_id: str = "", now: str = "",
            hide_seconds: int = None) -> list:
    """살아 있는 세션 뒤에 종료 세션. 오래된 종료 세션은 숨긴다 (고른 세션은 예외)."""
    hide_seconds = config.ENDED_HIDE_SECONDS if hide_seconds is None else hide_seconds
    now_dt = _parse(now or now_iso())
    live = [v for v in views if v.state != "ended"]
    ended = sorted([v for v in views if v.state == "ended"],
                   key=lambda v: v.ended_ts or v.last_ts, reverse=True)
    shown = []
    for v in ended:
        at = _parse(v.ended_ts or v.last_ts)
        old = at is None or (now_dt - at).total_seconds() > hide_seconds
        if old and v.session_id != selected_id:
            continue
        shown.append(v)
    return live + shown


# 프로젝트 폴더로 묶기 (요구 이력 59, BUILD_PLAN §4.10)
_ROOTS: dict = {}


def project_root(cwd: str) -> str:
    """cwd에서 위로 올라가며 .git이 있는 첫 폴더. 없으면 cwd 그대로."""
    if not cwd:
        return ""
    if cwd in _ROOTS:
        return _ROOTS[cwd]
    from pathlib import Path
    start = Path(cwd)
    root = cwd
    for p in [start, *start.parents]:
        try:
            if (p / ".git").exists():
                root = str(p)
                break
        except OSError:
            break
    _ROOTS[cwd] = root
    return root


def group_views(views: list) -> list:
    """arrange 뒤의 목록을 프로젝트 폴더별로 다시 늘어놓는다. 폴더 순서는 처음 나온 자리, 폴더 안은 원래 순서.
    세션마다 group(폴더 경로), group_label(보일 이름), subpath(하위 폴더에서 열었으면 남은 경로)를 채운다."""
    from pathlib import Path
    order: list = []
    members: dict = {}
    for v in views:
        root = project_root(v.cwd) or v.cwd or ""
        v.group = root
        rel = ""
        if v.cwd and root and v.cwd != root:
            try:
                rel = str(Path(v.cwd).relative_to(root))
            except ValueError:
                rel = ""
        v.subpath = rel
        if root not in members:
            members[root] = []
            order.append(root)
        members[root].append(v)
    names: dict = {}
    for root in order:
        names.setdefault(Path(root).name if root else "", []).append(root)
    for name, roots in names.items():
        for root in roots:
            label = name or "폴더 모름"
            if len(roots) > 1 and root:
                label = f"{Path(root).parent.name}/{name}"
            for v in members[root]:
                v.group_label = label
    return [v for root in order for v in members[root]]
