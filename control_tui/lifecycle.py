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
