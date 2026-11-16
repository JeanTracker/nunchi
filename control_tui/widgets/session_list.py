"""① 세션 목록 (SCREEN.md §2 ①)."""

from rich.cells import cell_len
from rich.text import Text
from textual.binding import Binding
from textual.widgets import Static
from control_tui.theme import C

STATE_LABEL = {
    # 색은 역할 이름이다. 그릴 때 C.get()으로 지금 테마의 값을 찾는다 (요청 36, SCREEN §10)
    "working": ("⏺ 작업", "warn"),
    "responded": ("✔ 응답", "ok"),
    "permission": ("? 허락", "info"),  # 허락 대기는 y/n을 받는 세션 (3단계)
    "question": ("? 질문", "p3"),      # 선택지 질문 창이 답을 기다림. ③에서 답하므로 ③ 색 (요청 39)
    "idle": ("○ 대기", "muted"),
    "pending": ("○ 연결 대기", "muted"),  # 설치 전에 열린 세션 (BUILD_PLAN §3.4)
    "ended": ("· 종료", "subtle"),
}

NEW_MARK = "  ● 새 응답"  # 확인 안 한 응답 표시
INDENT = 4                 # "  1  " 번호 칸
LABEL_WIDTH = 12           # "○ 연결 대기"(11칸)가 잘리지 않도록
NAME_MIN, NAME_MAX = 6, 40   # 세션 제목이 들어가므로 넓힌다 (요구 이력 59)
SHORT_NEW_MARK = " ●"      # 칸이 좁을 때 "● 새 응답" 대신 쓰는 표시
FALLBACK_WIDTH = 40        # 아직 화면 크기를 모를 때
MISSED_SLOT = 4            # " ⚠12" 자리. 항상 비워 두어 누락이 생겨도 줄이 바뀌지 않는다


def fit(text: str, width: int) -> str:
    """칸 수 기준으로 자른다 (한글은 두 칸). 넘치면 …으로 줄인다."""
    if cell_len(text) <= width:
        return text + " " * (width - cell_len(text))
    out = ""
    for ch in text:
        if cell_len(out + ch) > width - 1:
            break
        out += ch
    return out + "…" + " " * (width - cell_len(out) - 1)


class SessionList(Static, can_focus=True):
    BINDINGS = [
        Binding("up", "move(-1)", "위", show=False),
        Binding("down", "move(1)", "아래", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.views: list = []
        self.selected_id: str = ""
        self.acknowledged: set = set()

    def set_views(self, views: list) -> None:
        self.views = views
        if not any(v.session_id == self.selected_id for v in views):
            self.selected_id = views[0].session_id if views else ""
        self.refresh_content()

    def selected(self):
        for v in self.views:
            if v.session_id == self.selected_id:
                return v
        return None

    def action_move(self, delta: int) -> None:
        if not self.views:
            return
        ids = [v.session_id for v in self.views]
        i = ids.index(self.selected_id) if self.selected_id in ids else 0
        self.selected_id = ids[max(0, min(len(ids) - 1, i + delta))]
        self.acknowledged.add(self.selected_id)  # 고른 응답은 확인한 것으로 본다
        self.refresh_content()
        if hasattr(self.app, "refresh_sessions"):
            self.app.refresh_sessions()  # ②도 바로 바꾼다

    def on_resize(self, event) -> None:
        self.refresh_content()  # 칸이 바뀌면 이름 길이를 다시 맞춘다

    def line_layout(self, missed: int, is_new: bool, mark: str = "", judged: bool = True):
        """한 줄의 이름 칸 너비와 뒤에 붙일 표시. 줄이 칸을 넘으면 새 응답 표시를 짧게 줄인다.
        mark: 분석 상태 기호(· 대기, ↻ 분석 중, ! 실패, 새). judged가 False면 판정 전 ◌ (요청 30)."""
        width = self.size.width or FALLBACK_WIDTH
        base = width - INDENT - 1 - LABEL_WIDTH - 2  # 2: 테두리와 여백
        if missed:
            missed_txt = f" ⚠{missed}" + (f" {mark}" if mark == "새" else mark)
        elif not judged:
            missed_txt = " ◌" + mark if mark else ""
        else:
            missed_txt = f" {mark}" if mark else ""
        new_txt = NEW_MARK if is_new else ""
        if is_new and base - cell_len(missed_txt) - cell_len(new_txt) < NAME_MIN:
            new_txt = SHORT_NEW_MARK
        name_w = max(NAME_MIN, min(NAME_MAX, base - cell_len(missed_txt) - cell_len(new_txt)))
        return name_w, missed_txt, new_txt

    def _group_line(self, group: str) -> Text:
        """폴더 줄: 이름, 살아 있는 세션 수, 볼 것(허락·질문·남은 것) 수. 0인 것은 뺀다."""
        members = [v for v in self.views if getattr(v, "group", "") == group]
        label = getattr(members[0], "group_label", "") if members else ""
        live = sum(1 for v in members if v.state != "ended")
        parts = []
        if live:
            parts.append(str(live))
        asks = sum(1 for v in members if v.state == "permission")
        if asks:
            parts.append(f"허락 {asks}")
        qs = sum(1 for v in members if v.state == "question")
        if qs:
            parts.append(f"질문 {qs}")
        missed = sum(v.missed or 0 for v in members)
        line = Text()
        line.append(label or "폴더 모름", style=f"bold {C.p1}" if live else f"bold {C.subtle}")
        if parts:
            line.append("  " + " · ".join(parts), style=f"{C.muted}")
        if missed:
            line.append(f" · ⚠{missed}", style=f"{C.err}")
        return line

    def refresh_content(self) -> None:
        self.update(self.render_text())

    def render_text(self) -> Text:
        if not self.views:
            return Text("아직 기록된 세션이 없습니다.\n세션을 열면 여기에 나타납니다.", style=f"{C.muted}")
        out = Text()
        groups = {getattr(v, "group", "") for v in self.views}
        headed = len(groups) > 1     # 열린 폴더가 하나면 폴더 줄을 두지 않는다 (요구 이력 59)
        last_group = None
        for i, v in enumerate(self.views, start=1):
            group = getattr(v, "group", "")
            if headed and group != last_group:
                out.append_text(self._group_line(group))
                out.append("\n")
            last_group = group
            label, color = STATE_LABEL.get(v.state, (v.state, "text"))
            color = C.get(color)
            is_new = v.state == "responded" and v.session_id not in self.acknowledged
            name_w, missed_txt, new_txt = self.line_layout(v.missed, is_new, getattr(v, "analysis_mark", ""),
                                                           getattr(v, "judged", True))
            line = Text()
            line.append(f"{i:>2}  ", style=f"{C.subtle}")
            # 세션 제목이 앞, ID 앞 4글자는 괄호로 흐리게 (요구 이력 59)
            ident = f" ({v.session_id[:4]})" if v.session_id else ""
            title = getattr(v, "name", "") or ("새 세션" if headed else v.title)
            sub = getattr(v, "subpath", "")
            if sub:
                title = f"{sub} · {title}"
            if not headed and getattr(v, "name", ""):
                title = f"{v.title} · {title}"     # 폴더 줄이 없으면 폴더 이름을 앞에
            room = max(1, name_w - cell_len(ident))
            shown = fit(title, room).rstrip()
            line.append(shown, style="bold")
            line.append(ident, style=f"{C.subtle}")
            line.append(" " * max(0, name_w - cell_len(shown) - cell_len(ident)))
            line.append(" " + fit(label, LABEL_WIDTH), style=color)
            # 지금 도구 이름은 보이지 않는다 (요구 이력 48)
            if missed_txt:
                line.append(missed_txt, style=f"bold {C.err}")
            if new_txt:
                line.append(new_txt, style=f"bold {C.ok}")
            if v.state == "ended":
                line.stylize("dim")  # 닫힌 세션은 흐리게 (요청 35)
            if v.session_id == self.selected_id:
                line.stylize(f"on {C.sel}")
            out.append_text(line)
            out.append("\n")
        return out
