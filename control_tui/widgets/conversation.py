"""② 고른 세션의 대화 (SCREEN.md §2 ②, 요청 24~31).

구조
- 머리(고정): 분석 상태 줄, 한 줄 목표 흐름, 다음 할 일·누락·지켜짐, 빠진 조건, 바뀐 것 알림, 정보 줄.
- 대화 흐름(스크롤): 시간순으로 [옛 대화 묶음] → [최근 턴] → [마지막 대화]. 이 위젯이 직접 보이는 줄을 고른다.
  - 기본 위치: 마지막 대화가 칸보다 짧으면 아래에 붙이고, 길면 마지막 요청을 칸 맨 위에 둔다.
  - 위로 올라가 있으면 칸 맨 아래에 마지막 대화 한 줄을 고정한다.
- 마지막 대화: 응답 원문 전체(기본). s로 요약 보기(요약 + 질문 줄은 원문 + o 펼치기).
- 이전 턴: 요청 원문 1줄 + 응답 요약 최대 2줄. 요약이 없으면 원문 앞 2줄(+ 요약 준비 중).
- 사실(요청·응답 원문)은 기록되는 즉시, 추정(요약·라벨·목표·누락)은 분석이 끝나면 (요청 31).
키: ↑↓ 고르기, Enter 묶음 펼치기 / 턴은 응답까지 한 일, o 원문, d 상세, PgUp/PgDn 스크롤, End 마지막, Home 처음, s 요약 보기.
"""

import re
import time
from datetime import datetime, timezone

from rich.cells import cell_len
from rich.text import Text
from textual.binding import Binding
from textual.widgets import Static

from control_tui import flow as flowlib
from control_tui import glossary
from control_tui.analyzer import STATUS_LABEL, _similar as similar
from control_tui.store import SessionView
from control_tui.transcript import Turn, _ts_value
from control_tui.theme import C

FALLBACK_WIDTH = 100    # 아직 화면 크기를 모를 때
FALLBACK_HEIGHT = 40
INDENT = 6              # 펼친 카드의 들여쓰기
CARD_MAX = 96           # 카드 최대 폭
GROUP = 10              # 옛 대화 묶음 크기 (요청 26 첫 버전)
RECENT_MIN = 3          # 마지막 앞에 묶지 않고 보이는 최소 턴 수
TITLE_CUT = 16          # 접힌 단계 요약 줄의 짧은 이름 길이 (요청 41)
FLOW_POINTS = 2         # 목표 흐름에 보이는 전환점 수. 넘으면 앞쪽을 "… n단계 더"로 접는다 (요청 33)
COMPACT_HEIGHT = 24     # ② 칸이 이보다 낮으면 목표 흐름을 처음·지금 두 줄로
SAME_GOAL = 0.8         # 처음·지금 목표가 이만큼 비슷하면 같은 목표로 본다
CHECK_SHOWN = 3         # 머리에 펼치는 빠진 요청 수
ASKS_SHOWN = 2          # 머리에 펼치는 에이전트가 묻는 것 수 (요구 이력 56)
CHANGE_SECONDS = 5.0    # 분석이 바뀐 것을 강조하는 시간
CHANGE_AFTER_SENT = 30.0  # 답을 보낸 뒤 바뀌었으면 더 오래
QUESTION_MARKS = ("알려 주세요", "알려주세요", "확인해 주세요", "확인 부탁", "선택해 주세요", "정해 주세요",
                  "골라 주세요", "여부", "할까요", "될까요", "주실래요")


def _one_line(text: str, width: int) -> str:
    """한 줄로 펴고 칸 수(한글 2칸) 기준으로 자른다."""
    if width <= 1:
        return ""
    one = " ".join(text.split())
    if len(one) <= width and cell_len(one) <= width:
        return one
    out, used = "", 0
    for ch in one:
        w = cell_len(ch)
        if used + w > width - 1:
            break
        out += ch
        used += w
    return out + "…"


def _wrap(text: str, width: int, max_lines: int = 0) -> list:
    """칸 수 기준 줄바꿈. max_lines를 넘으면 마지막 줄 끝에 …"""
    one = " ".join(text.split())
    lines, cur, used = [], "", 0
    for ch in one:
        w = cell_len(ch)
        if used + w > width:
            lines.append(cur)
            cur, used = "", 0
        cur += ch
        used += w
    if cur or not lines:
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _one_line(lines[-1] + "…", width)
    return lines


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - cell_len(text))


def _clock(ts: str) -> str:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except (ValueError, TypeError, AttributeError):
        return "--:--"


def strip_md(text: str) -> str:
    return re.sub(r"(?m)^#+ ", "", text).replace("**", "")


_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_NUMBERED = re.compile(r"^(\s*)(\d+[.)]) (.*)$")
_BULLET = re.compile(r"^(\s*)[-*+] (.*)$")
TABLE_MIN_COL = 6   # 칸 하나에 이보다 적게 주게 되면 표 대신 '머리: 값'으로 풀어 쓴다


def _inline(text: str, base: str = "") -> list:
    """한 줄 안의 마크다운: **굵게**, `코드`, [글](주소) → (글, 스타일) 조각들 (요청 37)."""
    out = []
    for k, part in enumerate(_INLINE.split(text)):
        if not part:
            continue
        if k % 2 == 0:
            out.append((part, base))
        elif part.startswith("**"):
            out.append((part[2:-2], f"bold {base}".strip()))
        elif part.startswith("`"):
            out.append((part[1:-1], C.info))
        else:
            out.append((part[1:part.index("]")], f"underline {base}".strip()))
    return out


def _wrap_segments(segs: list, width: int, indent: str = "") -> list:
    """(글, 스타일) 조각들을 칸 수 기준으로 줄바꿈. 영문은 낱말 경계에서, 한글·긴 낱말은 글자에서 끊는다."""
    width = max(4, width)
    words = []   # (글, 스타일) — 공백도 하나의 낱말
    for text, style in segs:
        for w in re.split(r"( +)", text):
            if w:
                words.append((w, style))
    rows, cur, used = [], [], 0
    first = True

    def newline():
        nonlocal cur, used, first
        rows.append(cur)
        first = False
        cur, used = ([(indent, "")] if indent else []), cell_len(indent)

    for w, style in words:
        wl = cell_len(w)
        if w.isspace():
            if used + wl <= width and used > (0 if first else cell_len(indent)):
                cur.append((w, style))
                used += wl
            continue
        if used + wl <= width:
            cur.append((w, style))
            used += wl
            continue
        if wl <= width - cell_len(indent) and used > cell_len(indent if not first else ""):
            newline()
            cur.append((w, style))
            used += wl
            continue
        if wl > width and used > cell_len(indent if not first else "") and w.isascii():
            newline()   # 칸보다 긴 영문 낱말(경로 등)은 새 줄에서 시작한다
        for ch in w:   # 칸보다 긴 낱말 또는 한글 문장: 글자 단위
            cw = cell_len(ch)
            if used + cw > width:
                newline()
            cur.append((ch, style))
            used += cw
    rows.append(cur)
    out = []
    for row in rows:
        line = Text()
        for text, style in row:
            line.append(text, style=style or None)
        line.rstrip()   # 줄 끝 공백은 지운다 (칸 맞춤은 부르는 쪽이 한다)
        out.append(line)
    return out


def _table(rows: list, width: int) -> list:
    """마크다운 표 → 칸을 맞춘 글 줄들 (요청 37). rows[0]은 머리."""
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    n = max(len(r) for r in cells)
    cells = [r + [""] * (n - len(r)) for r in cells]
    plain = [[Text.assemble(*_inline(c)).plain for c in r] for r in cells]
    sep = 3   # " │ "
    room = width - sep * (n - 1)
    if room < TABLE_MIN_COL * n:   # 너무 좁다: 행마다 '머리: 값'
        out = []
        head = cells[0]
        for r in cells[1:]:
            for h, c in zip(head, r):
                if c:
                    out += _wrap_segments([(h + ": ", f"bold {C.muted}")] + _inline(c), width, "  ")
            out.append(Text(""))
        return out[:-1] if out else out
    natural = [max(cell_len(p[i]) for p in plain) or 1 for i in range(n)]
    # 칸마다 가장 긴 낱말(파일 경로 등)은 끊기지 않게 먼저 주고, 남는 너비는 긴 글 칸에 나눈다
    longest = [max((cell_len(w) for p in plain for w in p[i].split()), default=1) for i in range(n)]
    # 낱말을 지켜 주는 것은 내용이 거의 그 낱말뿐인 칸(경로·이름 칸)만. 긴 글 칸은 남는 폭을 고르게 나눈다
    widths = [max(TABLE_MIN_COL, min(natural[i], longest[i], room // 2)) if natural[i] <= longest[i] * 1.5
              else TABLE_MIN_COL for i in range(n)]
    while sum(widths) > room:   # 넘치면 몫이 가장 큰 칸부터 줄인다 (짧은 경로 칸은 지킨다)
        i = max(range(n), key=lambda k: widths[k])
        if widths[i] <= TABLE_MIN_COL:
            break
        widths[i] -= 1
    left = room - sum(widths)
    while left > 0:   # 아직 덜 받은 칸에 한 칸씩 (원래 너비까지만)
        grow = [i for i in range(n) if widths[i] < natural[i]]
        if not grow:
            break
        for i in grow:
            if left <= 0:
                break
            widths[i] += 1
            left -= 1
    rule = Text("─┼─".join("─" * w for w in widths), style=C.faint)
    out = []
    bodies = []
    for r, row in enumerate(cells):
        base = "bold" if r == 0 else ""
        wrapped = [_wrap_segments(_inline(c, base), widths[i]) for i, c in enumerate(row)]
        height = max(len(w) for w in wrapped)
        lines = []
        for k in range(height):
            line = Text()
            for i, w in enumerate(wrapped):
                if i:
                    line.append(" │ ", style=C.faint)
                part = w[k] if k < len(w) else Text("")
                line.append_text(part)
                line.append(" " * max(0, widths[i] - cell_len(part.plain)))
            lines.append(line)
        bodies.append(lines)
    multi = any(len(b) > 1 for b in bodies[1:])
    for r, lines in enumerate(bodies):
        if r == 1 or (r > 1 and multi):
            out.append(rule.copy())
        out += lines
    return out


def md_lines(text: str, width: int) -> list:
    """마크다운을 터미널 글 줄로 (SCREEN §2 ② 마지막 대화, 요청 37). 칸 수 기준 줄바꿈."""
    out = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if stripped.startswith("```"):   # 코드 블록: 흐린 글, 앞에 │
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                for part in _wrap(lines[i].replace("\t", "    "), max(4, width - 2)) if lines[i].strip() else [""]:
                    row = Text("│ ", style=C.faint)
                    row.append(part, style=C.muted)
                    out.append(row)
                i += 1
            i += 1
            continue
        if (stripped.startswith("|") and i + 1 < len(lines) and _TABLE_RULE.match(lines[i + 1])):
            block = [raw]
            i += 2   # 머리 + 구분 줄
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            out += _table(block, width)
            continue
        i += 1
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):   # 가로줄
            out.append(Text("─" * max(4, min(width, 40)), style=C.faint))
            continue
        if re.match(r"#{1,6} ", stripped):   # '# 제목'만. '#33 작업'은 본문이다
            out += _wrap_segments(_inline(stripped.lstrip("#").strip(), f"bold {C.info}"), width)
            continue
        m = _BULLET.match(raw)
        n = _NUMBERED.match(raw)
        if m:
            lead = m.group(1) + "• "
            out += _wrap_segments([(lead, "")] + _inline(m.group(2)), width, " " * cell_len(lead))
        elif n:
            lead = f"{n.group(1)}{n.group(2)} "
            out += _wrap_segments([(lead, "bold")] + _inline(n.group(3)), width, " " * cell_len(lead))
        else:
            out += _wrap_segments(_inline(raw), width)
    return out


def extract_questions(text: str, limit: int = 4) -> list:
    """응답에서 사용자에게 묻거나 확인을 청하는 줄 (규칙으로, 원문 그대로). SCREEN §6."""
    lines = [strip_md(ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("|")]
    found = [ln for ln in lines if ln.endswith("?") or ln.endswith("?)") or any(m in ln for m in QUESTION_MARKS)]
    if lines and lines[-1] not in found:
        found.append(lines[-1])  # 마지막 문단
    seen, out = set(), []
    for ln in found:
        if ln not in seen:
            seen.add(ln)
            out.append(ln)
    return out[:limit]


def _now_utc() -> float:
    return datetime.now(timezone.utc).timestamp()


class Conversation(Static, can_focus=True):
    BINDINGS = [
        Binding("up", "move(-1)", "이전", show=False),
        Binding("down", "move(1)", "다음", show=False),
        Binding("enter", "toggle", "펼치기", show=False),
        Binding("o", "raw", "원문", show=False),
        Binding("d", "detail", "응답 상세", show=False),
        Binding("s", "summary_view", "요약 보기", show=False),
        Binding("c", "checklist", "요청 전체", show=False),
        Binding("g", "flow_all", "흐름 전체", show=False),
        Binding("k", "ask_all", "묻는 것 전체", show=False),
        Binding("pageup", "page(-1)", "위로", show=False),
        Binding("pagedown", "page(1)", "아래로", show=False),
        Binding("end", "latest", "마지막 대화", show=False),
        Binding("home", "top", "처음", show=False),
        # Home/End가 없는 키보드용 (2026-11-10 실제 키 확인). 괄호는 한글 입력기에서도 그대로 온다
        Binding("right_square_bracket", "latest", "마지막 대화", show=False),
        Binding("left_square_bracket", "top", "처음", show=False),
        Binding("escape", "close_detail", "목록으로", show=False),
        Binding("left", "detail_move(-1)", "이전 응답", show=False),
        Binding("right", "detail_move(1)", "다음 응답", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.view: SessionView | None = None
        self.question_answers: dict = {}   # ③ 질문 답하기에서 고른 답 (요청 39)
        self.question_sent = False         # 그 답을 패널로 보냈는지
        self.turns: list = []
        self.analysis = None
        self.note = ""
        self.status: dict = {}
        self.queued: list = []
        self.latest_view = "full"      # 설정 파일 기본값
        self.view_override = None      # s 키로 바꾼 값 (이번 실행 동안)
        self.sent_after = False        # 답을 보낸 뒤 분석이 바뀜
        self.selected: int = -1        # 고른 턴 인덱스(0부터). 묶음을 고르면 -1
        self.cursor_group: int = 0     # 고른 묶음의 시작 턴 번호(1부터). 턴을 고르면 0
        self.expanded: set = set()     # 단계 카드를 펼친 턴
        self.raw: set = set()          # 원문을 펼친 턴
        self.open_groups: set = set()  # 펼친 묶음 (시작 턴 번호)
        self.detail: bool = False      # 응답 상세 화면(보조)
        self.checklist: bool = False   # 누적 요청 전체 (c, 요청 33)
        self.flowall: bool = False     # 목표 흐름 전체 (g, 요청 41)
        self.askall: bool = False      # 에이전트가 묻는 것 전체 (k, 요구 이력 56)
        self.check_cursor: int = 0     # 요청 전체에서 고른 줄
        self.scroll_top = None             # 대화 흐름 맨 위에 보이는 줄. None이면 기본 위치
        self._session_id = ""
        self._seen_latest = (0, False)  # 기본 위치에서 마지막으로 본 마지막 응답 (턴 번호, 응답 있음)
        self._items: list = []         # (종류, 키, 시작 줄, 줄 수) — 커서와 스크롤에 쓴다
        self._latest_start = 0
        self._fallback_turn = 0        # 요약 보기에서 요약이 없어 전체를 보이던 턴 (요약이 와도 자동으로 접지 않음)

    # ---------- 데이터 ----------

    def show(self, view: SessionView | None, turns: list, analysis=None, note: str = "", status=None,
             queued=None, latest_view: str = "full", sent_after: bool = False) -> None:
        self.analysis = analysis
        self.note = note
        self.status = status or {}
        self.queued = list(queued or [])
        self.latest_view = latest_view
        self.sent_after = sent_after
        sid = view.session_id if view else ""
        if sid != self._session_id:  # 다른 세션으로 바뀌면 처음 상태로
            self._session_id = sid
            self.expanded, self.raw, self.open_groups = set(), set(), set()
            self.detail = False
            self.checklist = False
            self.flowall = False
            self.askall = False
            self.scroll_top = None
            self.cursor_group = 0
            self.selected = len(turns) - 1
            self._seen_latest = self._latest_sig(turns)
        new_turn = len(turns) > len(self.turns) and self.selected == len(self.turns) - 1
        if new_turn and self.scroll_top is not None and getattr(self, "_at_latest", False):
            self.scroll_top = None   # 마지막 대화를 보던 중이면 새 응답으로 따라간다
        self.view = view
        self.turns = turns
        if new_turn and self.scroll_top is None:
            self.selected = len(turns) - 1  # 기본 위치에서는 새 마지막 턴을 따라간다
        if self.selected >= len(turns) or (self.selected < 0 and not self.cursor_group and turns):
            self.selected = len(turns) - 1  # 첫 턴이 생기면 바로 고른다
        if self.scroll_top is None:
            self._seen_latest = self._latest_sig(turns)
        self.refresh_content()

    @staticmethod
    def _latest_sig(turns: list) -> tuple:
        """마지막 응답의 표시: (턴 번호, 최종 응답이 있는지). 요청만 늘어난 것은 새 응답이 아니다."""
        if not turns:
            return (0, False)
        return (turns[-1].index, bool(turns[-1].final_response))

    @property
    def summary_mode(self) -> bool:
        return (self.view_override or self.latest_view) == "summary"

    # ---------- 키 ----------

    def check_action(self, action: str, parameters) -> bool | None:
        """Esc와 ←→는 응답 상세 화면에서만 쓴다. 목록에서는 다른 위젯이 받도록 넘긴다."""
        if action == "close_detail":
            return self.full_view
        if action == "detail_move":
            return self.detail
        return True

    @property
    def full_view(self) -> bool:
        """대화 흐름 자리를 다른 화면(상세, 요청 전체, 흐름 전체, 묻는 것 전체)이 차지하는지."""
        return self.detail or self.checklist or self.flowall or self.askall

    def _item_keys(self) -> list:
        return [(kind, key) for kind, key, _s, _n in self._items]

    def action_move(self, delta: int) -> None:
        if not self.turns:
            return
        if self.checklist:
            n = len(self._check_order())
            self.check_cursor = max(0, min(n - 1, self.check_cursor + delta)) if n else 0
            self.refresh_content()
            return
        if self.detail:
            self.selected = max(0, min(len(self.turns) - 1, self.selected + delta))
            self.refresh_content()
            return
        keys = self._item_keys()
        cur = ("group", self.cursor_group) if self.cursor_group else ("turn", self.selected)
        i = keys.index(cur) if cur in keys else len(keys) - 1
        kind, key = keys[max(0, min(len(keys) - 1, i + delta))]
        if kind == "group":
            self.cursor_group, self.selected = key, -1
        else:
            self.cursor_group, self.selected = 0, key
        self._reveal = True
        self.refresh_content()

    def action_toggle(self) -> None:
        if self.checklist:  # Enter: 그 요청을 보낸 턴으로
            order = self._check_order()
            if order:
                turn = order[min(self.check_cursor, len(order) - 1)].get("from_turn", 0)
                for k, t in enumerate(self.turns):
                    if t.index == turn:
                        self.cursor_group, self.selected = 0, k
                        start = ((k) // GROUP) * GROUP + 1
                        self.open_groups.add(start)  # 묶음 안이면 펼친다
                self.checklist = False
                self.scroll_top = None
                self._reveal = True
                self.refresh_content()
            return
        if self.detail:
            return
        if self.cursor_group:
            self.open_groups.symmetric_difference_update({self.cursor_group})
        elif 0 <= self.selected < len(self.turns) - 1:
            self.raw.symmetric_difference_update({self.selected})  # 이전 턴은 원문 펼치기 (요청 41: 단계·도구는 마지막 대화에서만)
        elif self.selected == len(self.turns) - 1:
            self.expanded.symmetric_difference_update({self.selected})
        self._reveal = True
        self.refresh_content()

    def action_raw(self) -> None:
        if self.turns and self.selected == len(self.turns) - 1 and self._fallback_turn == self.turns[-1].index:
            self._fallback_turn = 0   # 요약 도착 뒤 o: 이제 요약으로 접는다
            self.refresh_content()
            return
        if 0 <= self.selected < len(self.turns):
            self.raw.symmetric_difference_update({self.selected})
            self._reveal = True
            self.refresh_content()

    def action_detail(self) -> None:
        if self.turns and self.selected == len(self.turns) - 1:  # 응답 상세는 마지막 대화에서만 (요청 41)
            self.detail = True
            self.scroll_top = 0
            self.refresh_content()

    def action_checklist(self) -> None:
        if not self.analysis:  # 판정 전에는 열 것이 없다. 켜 두면 ↑↓·Enter가 먹통이 된다
            self.checklist = False
            self.app.bell()
            return
        self.checklist = not self.checklist
        self.check_cursor = 0
        self.detail = False
        self.flowall = False
        self.askall = False
        self.scroll_top = 0 if self.checklist else None
        self.refresh_content()

    def action_flow_all(self) -> None:
        """g: 목표 흐름 전체 (요청 41). 머리에서 접힌 단계를 모두 본다."""
        if not ((self.analysis or {}).get("flow") or {}).get("steps"):
            self.flowall = False
            self.app.bell()
            return
        self.flowall = not self.flowall
        self.checklist = False
        self.detail = False
        self.askall = False
        self.scroll_top = 0 if self.flowall else None
        self.refresh_content()

    def action_ask_all(self) -> None:
        """k: 에이전트가 묻는 것 전체 (요구 이력 56). mod가 '관제에서'라고 가리키는 내용."""
        if "asks" not in ((self.analysis or {}).get("flow") or {}):
            self.askall = False
            self.app.bell()
            return
        self.askall = not self.askall
        self.checklist = False
        self.flowall = False
        self.detail = False
        self.scroll_top = 0 if self.askall else None
        self.refresh_content()

    def action_close_detail(self) -> None:
        if self.askall:
            self.askall = False
            self.scroll_top = None
            self.refresh_content()
            return
        if self.flowall:
            self.flowall = False
            self.scroll_top = None
            self.refresh_content()
            return
        if self.checklist:
            self.checklist = False
            self.scroll_top = None
            self.refresh_content()
            return
        if self.detail:
            self.detail = False  # 고른 턴은 그대로 둔다
            self.scroll_top = None
            self.refresh_content()

    def action_detail_move(self, delta: int) -> None:
        return  # 응답 상세는 마지막 대화만 보므로 이전·다음으로 옮기지 않는다 (요청 41)

    def action_summary_view(self) -> None:
        current = self.view_override or self.latest_view
        self.view_override = "full" if current == "summary" else "summary"
        self.refresh_content()

    def action_page(self, delta: int) -> None:
        """PgUp/PgDn. ③에서 글을 쓰는 중에도 앱이 이것을 부른다."""
        room = max(3, self._room)
        start = self.scroll_top if self.scroll_top is not None else self._default_offset
        new = max(0, min(self._max_offset, start + delta * max(1, room - 2)))
        # 기본 위치(마지막 대화 시작)로 돌아오면 다시 새 응답을 따라간다
        self.scroll_top = None if new == self._default_offset else new
        self.refresh_content()

    def action_latest(self) -> None:
        self.scroll_top = None
        self.cursor_group, self.selected = 0, len(self.turns) - 1
        self._seen_latest = self._latest_sig(self.turns)
        self.refresh_content()

    def action_top(self) -> None:
        self.scroll_top = 0
        self.refresh_content()

    def on_resize(self, event) -> None:
        self.refresh_content()

    def refresh_content(self) -> None:
        self.update(self.render_text())
        refresh = getattr(self.app, "refresh_keybar", None) if self.is_mounted else None
        if refresh:
            refresh()  # 상세·요청 전체를 열고 닫으면 맨 아래 키 안내도 바뀐다

    # ---------- 크기 ----------

    def _width(self) -> int:
        """글을 놓을 수 있는 칸 수 (테두리·여백 제외)."""
        return max(20, (self.content_size.width or FALLBACK_WIDTH) - 1)

    def _height(self) -> int:
        parent = self.parent
        h = 0
        if parent is not None:
            h = parent.content_region.height
        return h or FALLBACK_HEIGHT

    # ---------- 그리기 ----------

    _room = 20
    _default_offset = 0
    _max_offset = 0
    _reveal = False

    def render_text(self) -> Text:
        if self.view is None:
            return Text("왼쪽 목록에서 세션을 고르면 대화가 보입니다.", style=f"{C.muted}")
        width = self._width()
        head = self._head(width)
        v = self.view
        if v.state == "pending":
            head.append("\n설치 전에 열린 세션이라 대화 기록이 없습니다.\n", style=f"{C.muted}")
            head.append("이 패널에서 Claude를 한 번 다시 시작하면 연결됩니다.\n", style=f"{C.muted}")
            return head
        if not self.turns:
            head.append("\n아직 대화 기록을 읽지 못했습니다.\n", style=f"{C.muted}")
            return head

        if self.askall and (self.analysis or {}).get("flow"):
            body = self._asks_all(width)
            self._items, self._latest_start = [], 0
        elif self.flowall and (self.analysis or {}).get("flow"):
            body = self._flow_all(width)
            self._items, self._latest_start = [], 0
        elif self.checklist and self.analysis:
            body = self._checklist(width)
            self._items, self._latest_start = [], 0
        elif self.detail and 0 <= self.selected < len(self.turns):
            body = list(self._detail(self.turns[self.selected], width).split("\n"))
            self._items, self._latest_start = [], 0
        else:
            body = self._flow(width)
        return self._viewport(head, body, width)

    def _viewport(self, head: Text, body: list, width: int) -> Text:
        while body and not body[-1].plain:
            body.pop()
        head_lines = len(head.plain.splitlines())
        room = max(3, self._height() - head_lines - 2)  # 위 표시 1줄 + 아래 표시 1줄
        total = len(body)
        latest_len = total - self._latest_start
        if self.full_view:
            default = 0
        elif total <= room:
            default = 0
        elif latest_len <= room:
            default = total - room   # 마지막 대화가 짧으면 아래에 붙여 옛 대화도 보이게
        else:
            default = self._latest_start  # 길면 마지막 요청을 칸 맨 위에
        self._default_offset = default
        self._max_offset = max(0, total - room)
        offset = default if self.scroll_top is None else self.scroll_top
        if self._reveal and not self.detail:  # 고른 것이 보이게 옮긴다
            self._reveal = False
            for kind, key, start, n in self._items:
                if (kind == "group" and key == self.cursor_group) or (kind == "turn" and key == self.selected):
                    if start < offset:
                        offset = start
                    elif start + n > offset + room:
                        offset = max(0, min(start, start + n - room))
                    self.scroll_top = None if offset == default else offset
        offset = max(0, min(offset, self._max_offset))
        pinned = (not self.detail and self.scroll_top is not None and self._latest_start
                  and offset + room <= self._latest_start)
        self._at_latest = not self.detail and not pinned
        view_room = room - (1 if pinned else 0)
        self._room = view_room
        view = body[offset:offset + view_room]
        out = head
        out.append((f"  ↑ 위로 {offset}줄 (PgUp)" if offset else "  ↑ 처음") + "\n", style=f"{C.subtle}")
        if total <= view_room and not self.full_view:
            out.append("\n" * (view_room - len(view)))  # 전체가 칸보다 짧으면 아래에 붙인다
        for ln in view:
            out.append_text(ln)
            out.append("\n")
        below = max(0, total - offset - len(view))
        if pinned:
            t = self.turns[-1]
            bar = Text()
            sig = self._latest_sig(self.turns)
            if sig != self._seen_latest and sig[1]:
                bar.append(f" ● 새 응답 #{t.index} 도착 ", style=f"bold {C.bg} on {C.ok}")
                bar.append(" · End로 마지막 대화 보기", style=f"bold {C.ok}")
            else:
                bar.append(f" ▼ 마지막 대화 #{t.index} ", style=f"bold {C.bg} on {C.info}")
                bar.append(" " + _one_line(t.request, max(10, width - 40)), style=f"{C.info}")
                bar.append("  · End로 돌아가기", style=f"bold {C.info}")
            out.append_text(bar)
            out.append("\n")
        # 키 안내는 맨 아래 줄이 한다 (요청 36). 여기에는 읽기 위치와 다음 할 행동만 둔다
        if (self.checklist and self.analysis) or self.detail or self.flowall or self.askall:
            out.append(f"  ↓ {below}줄 더 (PgDn)" if below else "  ── 끝 ──", style=f"{C.subtle}")
        elif below:
            out.append(f"  ↓ 아래로 {below}줄 더 (PgDn) · 다 읽으면 ③에서 바로 답하기", style=f"{C.subtle}")
        elif self._working() and self.view.state == "question":
            out.append("  ── 답을 보냈습니다 · 세션이 이어서 일하기를 기다림 ──" if self.question_sent
                       else "  ── 질문에 답을 기다리는 중 · ③에서 고르기 (i) ──", style=f"bold {C.p3}")
        elif self._working():
            out.append("  ── 에이전트가 답하는 중 · ③에 다음 지시를 써 두면 응답 뒤 보냄 ──", style=f"bold {C.warn}")
        else:
            out.append("  ── 응답 끝 · ③에서 답하기 ──",
                       style=f"{C.ok}")
        return out

    # ---------- 머리 (고정) ----------

    def _label_of(self, index: int) -> str:
        fs = self._flow_step(index)
        return (fs or {}).get("label") or self._turn_info(index).get("label", "")

    def _flow_step(self, index: int) -> dict:
        """목표 흐름(원문 고정 연쇄)의 그 턴 단계. 원문 대조를 통과한 것만."""
        for s in ((self.analysis or {}).get("flow") or {}).get("steps", []):
            if s.get("index") == index:
                return s if s.get("grounded") else {}
        return {}

    def _turn_summary(self, index: int) -> str:
        """이전 턴 요약: 사용자가 요청한 것 → 에이전트가 한 말·일 (요청 41). 흐름이 없으면 옛 응답 요약."""
        fs = self._flow_step(index)
        if fs.get("summary"):
            agent = fs.get("agent_summary") or ""
            return f"{fs['summary']} → {agent}" if agent else fs["summary"]
        return self._turn_info(index).get("response_summary", "")

    def _turn_info(self, index: int) -> dict:
        for item in (self.analysis or {}).get("turns", []):
            if item.get("index") == index:
                return item
        return {}

    def _has_missed(self, index: int) -> bool:
        return any(c.get("from_turn") == index and c.get("status") == "missed"
                   for c in (self.analysis or {}).get("ledger", []))

    def _basis(self) -> str:
        a = self.analysis or {}
        n = a.get("last_turn") or ""
        return f"#{n}" if n else "이전 응답"

    def _stale(self) -> bool:
        a = self.analysis
        v = self.view
        return bool(a and v and v.responded_ts and a.get("source_ts") != v.responded_ts)

    def _status_line(self) -> Text:
        st = self.status.get("state", "")
        a = self.analysis
        line = Text()
        note = ""
        if self.note == "분석기 꺼짐":
            line.append("분석기 꺼짐", style=f"{C.subtle}")
            if a and not self._stale():
                note = f"저장된 결과는 {self._basis()} 기준"
        elif st == "running":
            line.append(f"↻ 분석 중 · {self.status.get('seconds', 0)}초", style=f"bold {C.warn}")
        elif st == "queued":
            line.append(f"◌ 분석 대기 · 앞에 {self.status.get('ahead', 0)}건", style=f"bold {C.warn}")
        elif st == "failed":
            line.append(f"✘ 분석 실패 · {self.status.get('error', '')[:40]} · r 다시", style=f"bold {C.err}")
        elif self.note:
            line.append(self.note[:60], style=f"{C.subtle}")
        elif a and not self._stale():
            line.append(f"✔ 분석 완료 · {self._basis()} 기준", style=f"{C.ok}")
        elif self._stale() or not a:
            line.append("분석 안 함 · a 키로 분석", style=f"{C.subtle}")
        if not note and a and self._stale():
            note = f"아래는 {self._basis()} 응답 기준 · #{len(self.turns)} 반영 전"
        if not a and st in ("running", "queued"):
            note = "이 세션은 아직 판정 전"
        if note:
            line.append(f"   {note}", style=f"{C.muted}")
        return line

    def _head(self, width: int) -> Text:
        """머리: 늘 보인다. 분석이 늦으면 지난 판정을 흐리게 남기고 기준을 밝힌다 (요청 30)."""
        v = self.view
        out = Text()
        out.append(_one_line(v.title, max(10, width // 3)), style="bold")
        out.append("   " + _one_line(v.cwd, max(10, width - cell_len(_one_line(v.title, max(10, width // 3))) - 4)) + "\n",
                   style=f"{C.subtle}")
        status = self._status_line()
        out.append_text(Text(_one_line(status.plain, width), style=status.spans[0].style if status.spans else "")
                        if cell_len(status.plain) > width else status)
        out.append("\n")
        a = self.analysis
        if not a:
            out.append("목표 흐름·요청 체크: 아직 판정 전", style=f"{C.subtle} italic")
            out.append("   요청 체크 미판정\n", style=f"{C.subtle}")
        else:
            stale = self._stale()
            tone = f"{C.faint}" if stale else ""
            for ln in self._flow_steps(a, width, tone):
                out.append_text(ln)
                out.append("\n")
            out.append("\n")
            for ln in self._asks_head(a, width, stale):   # 에이전트가 묻는 것 (요구 이력 56)
                out.append_text(ln)
                out.append("\n")
            out.append_text(self._check_head(a, width, stale))
            out.append("\n")
            if not self.checklist:
                new_missed = set(self._changes().get("new_missed", []))
                missed = self._remaining()
                marks = {"open": "○", "deferred": "⊘", "in_progress": "◐", "missed": "✘"}
                color = C.warn if self._record_mode() else C.err
                for c in missed[:CHECK_SHOWN]:
                    out.append_text(self._check_line(c, width, marks.get(c.get("status"), "✘"), f"{C.faint}" if stale else f"{color}",
                                                     c.get("condition") in new_missed))
                    out.append("\n")
                if len(missed) > CHECK_SHOWN:
                    out.append(f"  … {len(missed) - CHECK_SHOWN}개 더 · c 전체 보기\n", style=f"{C.subtle}")
            ch = self._changes()
            if ch:
                parts = ["답 보낸 뒤 바뀜" if self.sent_after else "갱신됨"]
                if ch.get("missed_before") != ch.get("missed_after"):
                    parts.append(f"{'남은 것' if self._record_mode() else '빠짐'} {ch.get('missed_before')}→{ch.get('missed_after')}")
                if ch.get("new_missed"):
                    parts.append(f"{'새로 남음' if self._record_mode() else '새 빠짐'} {len(ch['new_missed'])}")
                if ch.get("goal_changed"):
                    parts.append("목표 바뀜")
                if len(parts) > 1:
                    out.append("  " + " · ".join(parts) + "\n", style=f"bold {C.warn}")
        out.append("─" * width + "\n", style=f"{C.faint}")
        return out

    def _changes(self) -> dict:
        """방금 끝난 분석에서 바뀐 것. 강조는 잠깐만 (답을 보낸 뒤면 더 오래)."""
        a = self.analysis or {}
        ch = a.get("changes") or {}
        if not ch or self._stale():
            return {}
        age = _now_utc() - _ts_value(a.get("analyzed_at", ""))
        limit = CHANGE_AFTER_SENT if self.sent_after else CHANGE_SECONDS
        return ch if 0 <= age <= limit else {}

    def _flow_steps(self, a: dict, width: int, tone: str) -> list:
        """목표 흐름을 세로 단계로 (요청 33): ● 처음 → ◆ 방향이 바뀐 턴 → ◉ 지금. 한 단계에 한 줄.
        이어 적은 흐름(요청 40)이 있으면 ◆는 주제가 옮겨 가 목표를 다시 정한 턴이고, 그 아래 방향 줄을 붙인다."""
        if (a.get("flow") or {}).get("steps"):
            return self._chain_steps(a["flow"], width, tone)
        points = [t for t in a.get("turns", []) if t.get("label") in ("재정의", "범위 축소")]
        compact = self._height() < COMPACT_HEIGHT
        hidden = 0
        if compact:
            points = []
        elif len(points) > FLOW_POINTS:
            hidden = len(points) - FLOW_POINTS
            points = points[-FLOW_POINTS:]
        first_turn = min((t.get("index", 1) for t in a.get("turns", [])), default=1)
        rows = [("●", f"#{first_turn}", "시작", a.get("first_goal") or "-", f"{C.info}")]
        if hidden:
            rows.append(("┊", "", "", f"… {hidden}단계 더", f"{C.subtle}"))
        for t in points:
            rows.append(("◆", f"#{t['index']}", t.get("label", ""), t.get("summary", "") or "-", f"{C.warn}"))
        last = a.get("last_turn") or 0
        same_turn = not last or last == first_turn
        unchanged = similar(a.get("first_goal") or "", a.get("current_goal") or "") >= SAME_GOAL
        if not points and not hidden and (same_turn or unchanged):
            # 전환점이 없고 처음과 지금이 같으면 한 줄 (요청 37: 요청 하나인 세션에서 같은 글이 두 번 나왔다)
            span = f"#{first_turn}" if same_turn else f"#{first_turn}–{last}"
            rows = [("◉", span, "처음·지금", a.get("current_goal") or a.get("first_goal") or "-", f"{C.p2}")]
        else:
            rows.append(("◉", f"#{last}" if last else "", "지금", a.get("current_goal") or "-", f"{C.p2}"))
        out = [Text("목표 흐름", style=tone or "bold")]
        if not compact:
            out[0].append("  방향이 바뀐 턴만", style=f"{C.subtle}")
        for k, (mark, num, label, text, color) in enumerate(rows):
            if k and not compact:
                out.append(Text(" │", style=f"{C.faint}"))
            ln = Text(f" {mark} ", style=tone or f"bold {color}")
            if mark == "┊":
                ln.append(text, style=f"{C.subtle}")
                out.append(ln)
                continue
            ln.append(f"{num:<4} ", style=f"{C.subtle}")
            ln.append(f"{label} " if label else "", style=tone or color)
            ln.append(_one_line(text, max(10, width - cell_len(ln.plain))),
                      style=tone or ("bold" if mark == "◉" else ""))
            out.append(ln)
        return out

    def _chain_steps(self, flow: dict, width: int, tone: str) -> list:
        """원문 고정 연쇄 목표 흐름 (요청 40·41, SCREEN §2 ② 머리): ● 처음 → ◆ 주제 이동·✔ 결정 → ◉ 지금.
        ◆와 지금(주제 이동으로 정해졌으면) 아래에 흐린 방향 줄. 가운데를 접으면 접힌 단계의 짧은 이름을 한 줄로.
        지금 목표가 정해진 뒤의 결정 턴은 ◉ 아래에 들여 쓴다. 분석 중이면 맨 아래에 틀(스켈레톤)."""
        steps = flow.get("steps", [])
        first = flow.get("first_goal") or {}
        cur = flow.get("current_goal") or {}
        cur_turn = cur.get("turn") or 0
        by_turn = {s.get("index"): s for s in steps}
        first_turn = first.get("turn") or (steps[0].get("index") if steps else 1)
        points = [s for s in steps if (s.get("shift") or s.get("label") == "확정")
                  and s.get("index") != cur_turn and s.get("index") != first_turn and s.get("index", 0) < cur_turn]
        after = [s for s in steps if s.get("label") == "확정" and s.get("index", 0) > cur_turn and not s.get("shift")]
        compact = self._height() < COMPACT_HEIGHT
        hidden = []
        if compact:
            hidden, points, after = [], [], after[-1:]
        elif len(points) > FLOW_POINTS:
            hidden = points[:-FLOW_POINTS]
            points = points[-FLOW_POINTS:]
        if len(after) > FLOW_POINTS:
            after = after[-FLOW_POINTS:]
        rows = []  # (표, 번호, 이름, 글, 색, 방향 줄에 쓸 단계, 들여쓰기)
        last = flow.get("until") or 0
        pending = self._pending_turn()
        if pending and pending > cur_turn:
            # 분석 중: '지금'을 마지막 대화 턴으로 먼저 옮긴다 (요청 42). 옛 지금 목표와 그 뒤 결정은 일반 단계로
            return self._pending_steps(flow, steps, first, first_turn, cur, cur_turn, by_turn, compact, width, tone, pending)
        if not points and not hidden and not after and (cur_turn == first_turn or not cur.get("text")):
            span = f"#{first_turn}" if last <= first_turn else f"#{first_turn}–{last}"
            rows.append(("◉", span, "처음·지금", cur.get("text") or first.get("text") or "-", f"{C.p2}", None, ""))
        else:
            rows.append(("●", f"#{first_turn}", "시작", first.get("text") or "-", f"{C.info}", None, ""))
            if hidden:
                rows.append(("┊", "", "", self._fold_text(hidden), f"{C.subtle}", None, ""))
            for s in points:
                rows.append(self._point_row(s))
            cs = by_turn.get(cur_turn)
            shift = bool((cs or {}).get("shift"))
            span = f"#{cur_turn}–{last}" if cur_turn and last > cur_turn else f"#{cur_turn}"   # 목표가 그 턴부터 이어짐 (요청 42)
            rows.append(("◉", f"지금 {span}" if cur_turn else "지금", (cs or {}).get("direction", "") if shift else "",
                         cur.get("text") or "-", f"{C.p2}", cs if shift else None, ""))
            for s in after:
                rows.append(self._point_row(s, indent="  "))
        out = [Text("목표 흐름", style=tone or "bold")]
        if not compact:
            out[0].append("  주제 이동과 결정 · 추정, “ ”는 원문", style=f"{C.subtle}")
        for k, (mark, num, label, text, color, step, indent) in enumerate(rows):
            if k and not compact and not indent:
                out.append(Text(" │", style=f"{C.faint}"))
            ln = Text(f" {indent}{mark} ", style=tone or f"bold {color}")
            if mark == "┊":
                for part in self._fold_lines(hidden, width):
                    out.append(Text(f" ┊ {part}", style=f"{C.subtle}"))
                continue
            ln.append(f"{num} ", style=f"{C.subtle}")
            ln.append(f"{label} " if label else "", style=tone or color)
            body = text
            if mark == "✔" and step and step.get("quote"):
                body = f"{text} “{step['quote'][:20]}{'…' if len(step['quote']) > 20 else ''}”"
            ln.append(_one_line(body, max(10, width - cell_len(ln.plain))),
                      style=tone or ("bold" if mark == "◉" else ""))
            out.append(ln)
            if step and step.get("shift") and (not compact or mark == "◉"):
                out.append(self._direction_line(step, width, tone))  # 낮은 화면에서도 지금 목표의 방향 줄은 남긴다 (요청 40)
        return out

    def _pending_steps(self, flow, steps, first, first_turn, cur, cur_turn, by_turn, compact, width, tone, pending) -> list:
        """분석 중인 턴이 있을 때의 목표 흐름: … → 옛 지금(일반 단계) → 결정 → ◉ 지금 #n ... (요청 42)."""
        marks = [s for s in steps if (s.get("shift") or s.get("label") == "확정") and s.get("index") != first_turn]
        hidden = []
        if compact:
            marks = []
        elif len(marks) > FLOW_POINTS:
            hidden, marks = marks[:-FLOW_POINTS], marks[-FLOW_POINTS:]
        out = [Text("목표 흐름", style=tone or "bold")]
        if not compact:
            out[0].append("  주제 이동과 결정 · 추정, “ ”는 원문", style=f"{C.subtle}")
        ln = Text(" ● ", style=tone or f"bold {C.info}")
        ln.append(f"#{first_turn} ", style=f"{C.subtle}")
        ln.append("시작 ", style=tone or f"{C.info}")
        ln.append(_one_line(first.get("text") or "-", max(10, width - 12)))
        out.append(ln)
        if hidden:
            if not compact:
                out.append(Text(" │", style=f"{C.faint}"))
            for part in self._fold_lines(hidden, width):
                out.append(Text(f" ┊ {part}", style=f"{C.subtle}"))
        for s in marks:
            if not compact:
                out.append(Text(" │", style=f"{C.faint}"))
            mark, num, label, text, color, step, _ = self._point_row(s)
            row = Text(f" {mark} ", style=tone or f"bold {color}")
            row.append(f"{num} ", style=f"{C.subtle}")
            row.append(f"{label} " if label else "", style=tone or color)
            body = text if s.get("shift") else f"{text} “{s.get('quote', '')[:20]}”"
            row.append(_one_line(body, max(10, width - cell_len(row.plain))))
            out.append(row)
            if s.get("shift") and not compact:
                out.append(self._direction_line(s, width, tone))
        if not compact:
            out.append(Text(" │", style=f"{C.faint}"))
        now = Text(" ◉ ", style=f"bold {C.p2}")
        latest = self.turns[-1].index if self.turns else pending
        now.append(f"지금 #{latest} ", style=f"{C.subtle}")
        now.append(self._dots(), style=f"bold {C.warn}")   # 분석 중 색은 상태 줄과 같은 주황 (턴 48)
        out.append(now)
        return out

    def _point_row(self, s: dict, indent: str = "") -> tuple:
        if s.get("shift"):
            return ("◆", f"#{s['index']}", s.get("direction", ""), s.get("goal") or s.get("summary") or "-", f"{C.warn}", s, indent)
        return ("✔", f"#{s['index']}", "확정", s.get("decision") or s.get("summary") or "-", f"{C.ok}", s, indent)

    @staticmethod
    def _title_of(s: dict) -> str:
        """접힌 단계 요약 줄에 쓰는 짧은 이름 (분석이 낸 title, 없으면 목표 글 앞부분)."""
        name = s.get("title") or s.get("goal") or s.get("decision") or s.get("summary") or ""
        name = " ".join(name.split())
        return name if len(name) <= TITLE_CUT else name[:TITLE_CUT] + "…"

    def _fold_lines(self, hidden: list, width: int, max_lines: int = 2) -> list:
        """접힌 단계 요약을 단계 사이(→)에서만 줄 바꿈한다. 넘치면 마지막 줄 끝을 …로."""
        names = [("✔" if not s.get("shift") else "") + self._title_of(s) for s in hidden]
        span = f"#{hidden[0]['index']}–#{hidden[-1]['index']} {len(hidden)}단계 · "
        tail = " · g 흐름 전체"
        room = max(10, width - 4)
        lines, cur = [], span
        for k, name in enumerate(names):
            piece = name if k == 0 else " → " + name
            if cell_len(cur + piece) > room and cur.strip():
                lines.append(cur)
                cur = "  " + name
            else:
                cur += piece
        lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = _one_line(lines[-1] + " → …", room - cell_len(tail))
        if cell_len(lines[-1] + tail) > room:
            lines[-1] = _one_line(lines[-1], room - cell_len(tail))
        lines[-1] += tail
        return lines

    def _fold_text(self, hidden: list) -> str:
        names = [("✔" if not s.get("shift") else "") + self._title_of(s) for s in hidden]
        span = f"#{hidden[0]['index']}–#{hidden[-1]['index']}"
        return f"{span} {len(hidden)}단계 · " + " → ".join(names) + " · g 흐름 전체"

    def _pending_turn(self) -> int:
        """분석이 지금 이어 적는(또는 곧 이어 적을) 턴 번호. 없으면 0 (스켈레톤, 요청 41)."""
        st = self.status or {}
        if st.get("state") not in ("running", "queued") or not self.turns:
            return 0
        if st.get("turn"):
            return st["turn"]
        until = (((self.analysis or {}).get("flow") or {}).get("until")) or 0
        for t in self.turns:
            if t.index > until and (t.final_response or t.response):
                return t.index
        return 0

    @staticmethod
    def _dots() -> str:
        """분석 중 자리 표시: '분석 중' 뒤 점이 1초마다 . → .. → ... (요청 42·턴 46). 점 폭은 늘 세 칸."""
        return "분석 중" + (".", "..", "...")[int(time.time()) % 3].ljust(3)

    def _flow_all(self, width: int) -> list:
        """g: 목표 흐름 전체 (요청 41). 처음부터 모든 주제 이동·결정과 방향 줄."""
        flow = (self.analysis or {}).get("flow") or {}
        steps = flow.get("steps", [])
        first = flow.get("first_goal") or {}
        cur = flow.get("current_goal") or {}
        cur_turn = cur.get("turn") or 0
        marks = [s for s in steps if s.get("shift") or s.get("label") == "확정"]
        head = Text("목표 흐름 전체", style="bold")
        head.append(f"  {len(marks) + 1}단계 · #{flow.get('until') or 0} 기준 · 추정, “ ”는 원문  g·Esc 닫기", style=f"{C.subtle}")
        lines = [head, Text("")]
        ln = Text(" ● ", style=f"bold {C.info}")
        ln.append(f"#{first.get('turn') or 1} ", style=f"{C.subtle}")
        ln.append("시작 ", style=f"{C.info}")
        ln.append(_one_line(first.get("text") or "-", max(10, width - 12)))
        lines.append(ln)
        for s in marks:
            mark, num, label, text, color, step, _ = self._point_row(s)
            if s.get("index") == cur_turn:
                mark, color, num = "◉", f"{C.p2}", f"지금 #{cur_turn}"
            lines.append(Text(" │", style=f"{C.faint}"))
            row = Text(f" {mark} ", style=f"bold {color}")
            row.append(f"{num} ", style=f"{C.subtle}")
            row.append(f"{label} " if label else "", style=color)
            body = text if s.get("shift") else f"{text} “{s.get('quote', '')[:20]}”"
            row.append(_one_line(body, max(10, width - cell_len(row.plain))))
            lines.append(row)
            if s.get("shift"):
                lines.append(self._direction_line(s, width, ""))
        if not any(s.get("index") == cur_turn for s in marks) and cur_turn and cur_turn != (first.get("turn") or 1):
            lines.append(Text(" │", style=f"{C.faint}"))
            row = Text(" ◉ ", style=f"bold {C.p2}")
            row.append(f"지금 #{cur_turn} ", style=f"{C.subtle}")
            row.append(_one_line(cur.get("text") or "-", max(10, width - 14)))
            lines.append(row)
        return lines

    def _direction_line(self, step: dict, width: int, tone: str) -> Text:
        """앞 목표에서 어떻게 이어졌는지 한 줄 (요청 40). 끝의 근거 구절은 사용자 원문이라 일반 색 (SCREEN §6)."""
        quote = step.get("shift_quote") or ""
        q = f" “{quote[:20]}{'…' if len(quote) > 20 else ''}”" if quote else ""
        ln = Text("    └ ", style=f"{C.faint}")
        room = max(10, width - cell_len(ln.plain) - cell_len(q))
        ln.append(_one_line(step.get("how") or "", room), style=tone or f"{C.subtle}")
        if q:
            ln.append(q, style=tone or "")
        return ln

    def _ask_line(self, q: dict, width: int, basis: int, style: str, mark: str = "?") -> Text:
        """한 줄: ? 요약 “응답 원문” #턴(부터 답 없음)(· 일부 답함). mod와 같은 표시 (SCREEN §11)."""
        last = q.get("last_turn") or q.get("turn") or 0
        tail = f"#{q.get('turn') or last}"
        if q.get("state") != "answered" and basis and last < basis - 1:
            tail += "부터 답 없음"
        if q.get("state") == "partial":
            tail += " · 일부 답함"
        if q.get("state") == "answered" and q.get("by_blanket"):
            tail += " · 통째 승인"
        line = Text("  ")
        line.append(f"{mark} ", style=f"bold {style}")
        body = q.get("summary", "") + (f" “{q['quote'][:30]}”" if q.get("quote") else "")
        room = max(10, width - 4 - cell_len(tail) - 2)
        shown = _one_line(body, room)
        line.append(shown, style=f"{C.faint}" if style == f"{C.faint}" else "")
        line.append(" " * max(0, room - cell_len(shown)))
        line.append("  " + tail, style=f"{C.subtle}")
        return line

    def _asks_head(self, a: dict, width: int, stale: bool) -> list:
        """② 머리의 '에이전트가 묻는 것' (요구 이력 56). 묻는 것을 뽑기 전 흐름이면 두지 않는다."""
        flow = a.get("flow") or {}
        if "asks" not in flow:
            return []
        left = flowlib.open_asks(flow)
        basis = flow.get("until") or 0
        head = Text("에이전트가 묻는 것", style=f"{C.faint}" if stale else "bold")
        if left:
            head.append(f" {len(left)}", style=f"{C.faint}" if stale else f"bold {C.warn}")
        else:
            head.append(" 없음", style=f"{C.faint}" if stale else f"{C.ok}")
        tail = "   k 닫기" if self.askall else "   k 전체 보기"
        if cell_len(head.plain) + cell_len(tail) <= width:
            head.append(tail, style=f"{C.muted}")
        out = [head]
        if self._height() < COMPACT_HEIGHT:   # 낮은 화면: 수 한 줄만 (목표 흐름처럼, 마지막 대화 자리를 남긴다)
            return out
        if not self.askall:
            for q in left[:ASKS_SHOWN]:
                out.append(self._ask_line(q, width, basis, f"{C.faint}" if stale else f"{C.warn}"))
            if len(left) > ASKS_SHOWN:
                out.append(Text(f"  … {len(left) - ASKS_SHOWN}개 더 · k", style=f"{C.subtle}"))
        return out

    def _asks_all(self, width: int) -> list:
        """k: 묻는 것 전체. 아직 답 없음(최근 것부터) → 일부 답함 → 답함."""
        flow = (self.analysis or {}).get("flow") or {}
        asks = flow.get("asks") or []
        basis = flow.get("until") or 0
        recent = lambda q: -(q.get("last_turn") or q.get("turn") or 0)
        groups = (("open", "?", C.warn, "아직 답 없음"), ("partial", "◐", C.warn, "일부 답함"), ("answered", "✔", C.ok, "답함"))
        lines = [Text("")]
        for state, mark, color, title in groups:
            items = sorted([q for q in asks if q.get("state", "open") == state], key=recent)
            if not items:
                continue
            head = Text(f" {title} {len(items)}", style=f"bold {color}")
            if state == "answered":
                n = sum(1 for q in items if q.get("by_blanket"))
                if n:
                    head.append(f"  통째 승인으로 닫은 것 {n} (답하지 않았을 수 있음)", style=f"{C.subtle}")
            lines.append(head)
            for q in items:
                lines.append(self._ask_line(q, width, basis, color, mark))
            lines.append(Text(""))
        if len(lines) == 1:
            lines.append(Text("  에이전트가 물은 것이 없습니다.", style=f"{C.subtle}"))
        since = flow.get("asks_from") or 0
        if since > 1:
            lines.append(Text(f"  #{since - 1} 이전 응답의 묻는 것은 기록 전", style=f"{C.subtle}"))
        return lines

    def _record_mode(self) -> bool:
        """요청 기록(기억 관점, 요청 41)이 있으면 그것을, 없으면 옛 요청 체크를 보인다."""
        return "requests" in (((self.analysis or {}).get("flow")) or {})

    def _records(self) -> list:
        """요청 기록을 화면 항목으로. 도구 실패는 보지 않는다 (요구 이력 48)."""
        out = []
        for r in ((self.analysis or {}).get("flow") or {}).get("requests", []):
            st = r.get("state", "open")
            out.append({"condition": r.get("summary", ""), "from_turn": r.get("from_turn", 0), "status": st,
                        "quote": r.get("quote", ""), "agent_quote": r.get("agent_quote", ""),
                        "pending_quote": r.get("pending_quote", ""),
                        "superseded_by": r.get("superseded_by", 0), "record": True})
        return out

    def _ledger(self, status: str) -> list:
        if self._record_mode():
            return [c for c in self._records() if c["status"] == status]
        return [c for c in (self.analysis or {}).get("ledger", []) if c.get("status") == status]

    def _remaining(self) -> list:
        """머리에 보이는 것: 옛 방식은 빠짐, 기억 관점은 남은 것(아직 다루지 않음·못 했거나 미룸)."""
        if self._record_mode():
            return self._ledger("open") + self._ledger("deferred") + self._ledger("in_progress")
        return self._ledger("missed")

    def _record_head(self, a: dict, width: int, stale: bool) -> Text:
        """요청 기록 한 줄 (요청 41): 누적 n개 · #n 기준 · 남은 것 k."""
        recs = [c for c in self._records() if c["status"] != "superseded"]
        left = self._remaining()
        line = Text("요청 기록", style=f"{C.faint}" if stale else "bold")
        line.append(f"  누적 {len(recs)}개 · {self._basis()} 기준  ", style=f"{C.subtle}")
        if left:
            line.append(f"남은 것 {len(left)}", style=f"{C.faint}" if stale else f"bold {C.warn}")
        elif recs:
            line.append("남은 것 없음", style=f"{C.faint}" if stale else f"{C.ok}")
            line.append(f" · 다룸 {len(self._ledger('addressed'))}", style=f"{C.subtle}")
        else:
            line.append("쌓인 요청 없음", style=f"{C.subtle}")
        since = ((a.get("flow") or {}).get("requests_from")) or 0
        if since > 1:
            line.append(f" · #{since - 1} 이전 요청은 기록 전", style=f"{C.subtle}")   # 옮겨 담은 흐름 (요구 이력 44)
        return line

    def _check_head(self, a: dict, width: int, stale: bool) -> Text:
        if self._record_mode():
            line = self._record_head(a, width, stale)
            return self._check_tail(line, width, stale)
        live = [c for c in a.get("ledger", []) if c.get("status") != "superseded"]
        missed = self._ledger("missed")
        line = Text("요청 체크", style=f"{C.faint}" if stale else "bold")
        line.append(f"  누적 {len(live)}개 · {self._basis()} 마지막 응답 기준 · 추정  ", style=f"{C.subtle}")
        if missed:
            line.append(f"✘ 빠짐 {len(missed)}", style=f"{C.faint}" if stale else f"bold {C.err}")
        elif live:
            kept, unknown = len(self._ledger("kept")), len(self._ledger("unknown"))
            line.append("빠짐 없음", style=f"{C.faint}" if stale else f"{C.ok}")
            line.append(f" · 챙김 {kept}" + (f" · 확인 안 됨 {unknown}" if unknown else ""), style=f"{C.subtle}")
        else:
            line.append("쌓인 요청 없음", style=f"{C.subtle}")
        return self._check_tail(line, width, stale)

    def _check_tail(self, line: Text, width: int, stale: bool) -> Text:
        pending = self._pending_turn()
        if pending:
            line.append(f"  #{self.turns[-1].index} ", style=f"{C.subtle}")   # 목표 흐름의 '지금'과 같은 턴 (요청 42)
            line.append(self._dots(), style=f"{C.warn}")
        tail = "  c 닫기" if self.checklist else "  c 전체 보기"
        if cell_len(line.plain) + cell_len(tail) <= width:
            line.append(tail, style=f"{C.muted}")
        if stale:
            line.append(f"  ({self._basis()} 기준)", style=f"{C.subtle}")
        return line

    def _check_line(self, c: dict, width: int, mark: str, style: str, new: bool = False) -> Text:
        turn = f"#{c.get('from_turn')}" if c.get("from_turn") else ""
        line = Text("  ")
        line.append(f"{mark} ", style=f"bold {style}")
        body = c.get("condition", "")
        if c.get("record"):
            st = c["status"]
            if st == "open" and c.get("quote"):
                body += f" “{c['quote'][:24]}”"
            elif st == "deferred":
                body += " — 에이전트: 못 했거나 미룸" + (f" “{c['agent_quote'][:24]}”" if c.get("agent_quote") else "")
            elif st == "in_progress":   # 아직 안 끝난 이유가 있으면 그것을, 없으면 한 일을 보인다 (요구 이력 66)
                why = c.get("pending_quote") or c.get("agent_quote")
                body += " — 진행 중" + (f" “{why[:24]}”" if why else "")
            elif st == "addressed" and c.get("agent_quote"):
                body += f" — 에이전트: “{c['agent_quote'][:24]}”"
            elif st == "superseded" and c.get("superseded_by"):
                body += f" → #{c['superseded_by']}에서 바뀜"
        elif c.get("status") == "superseded" and c.get("superseded_by"):
            body += f" → #{c['superseded_by']}에서 바뀜"
        elif c.get("evidence") and c.get("status") in ("missed", "unknown"):
            body += f" — {c['evidence']}"
        room = max(10, width - cell_len(line.plain) - cell_len(turn) - (4 if new else 0) - 2)
        shown = _one_line(body, room)
        line.append(shown, style=f"{C.subtle} strike" if c.get("status") == "superseded" else (f"{C.faint}" if style == f"{C.faint}" else ""))
        line.append(" " * max(0, room - cell_len(shown)))
        if new:
            line.append(" 새", style=f"bold {C.bg} on {C.err}")
        line.append("  " + turn, style=f"{C.subtle}")
        return line

    CHECK_GROUPS = (("missed", "✘", "err", "빠짐"), ("kept", "✔", "ok", "챙김"),   # 색은 역할 이름 (요청 36)
                    ("unknown", "?", "warn", "확인 안 됨"), ("superseded", "⊖", "subtle", "뒤 요청이 대신함"))

    RECORD_GROUPS = (("open", "○", "warn", "아직 다루지 않음"), ("deferred", "⊘", "warn", "못 했거나 미룸"),
                     ("in_progress", "◐", "warn", "진행 중"),   # 요구 이력 66
                     ("addressed", "✔", "ok", "다룸"),
                     ("superseded", "⊖", "subtle", "뒤 요청이 대신함"))   # 요청 41: 채점이 아니라 사실

    def _groups(self) -> tuple:
        return self.RECORD_GROUPS if self._record_mode() else self.CHECK_GROUPS

    def _check_order(self) -> list:
        out = []
        for status, *_ in self._groups():
            out += sorted(self._ledger(status), key=lambda c: c.get("from_turn", 0))
        return out

    def _checklist(self, width: int) -> list:
        """c 키: 누적 요청 전체 (요청 33). 빠짐 → 챙김 → 확인 안 됨 → 뒤 요청이 대신함."""
        lines = [Text("")]
        k = 0
        for status, mark, color, title in self._groups():
            color = C.get(color)
            items = sorted(self._ledger(status), key=lambda c: c.get("from_turn", 0))
            if not items:
                continue
            head = Text(f" {title} {len(items)}", style=f"bold {color}")
            if status == "unknown":
                head.append("  마지막 응답만으로는 판단 못 함", style=f"{C.subtle}")
            if status == "superseded":
                head.append("  체크하지 않음", style=f"{C.subtle}")
            lines.append(head)
            for c in items:
                ln = self._check_line(c, width, mark, color)
                if k == self.check_cursor:
                    ln.stylize(f"on {C.sel}")
                lines.append(ln)
                k += 1
            lines.append(Text(""))
        if len(lines) == 1:
            lines.append(Text("  쌓인 요청이 없습니다.", style=f"{C.subtle}"))
        return lines

    # ---------- 대화 흐름 ----------

    def _working(self) -> bool:
        if not self.turns or self.view is None:
            return False
        t = self.turns[-1]
        return self.view.state in ("working", "permission", "question") and not t.final_response

    def _flow(self, width: int) -> list:
        """시간순 대화 흐름의 줄 목록. 항목(묶음·턴)마다 시작 줄을 적어 둔다."""
        lines: list = []
        items: list = []
        n = len(self.turns)
        if n > GROUP + RECENT_MIN:
            recent_from = ((n - 1 - RECENT_MIN) // GROUP) * GROUP + 1  # 10턴 경계에 맞춘다
        else:
            recent_from = 1
        for s in range(1, recent_from, GROUP):
            e = min(s + GROUP - 1, recent_from - 1)
            start = len(lines)
            lines.append(self._group_line(s, e, width))
            items.append(("group", s, start, 1))
            if s in self.open_groups:
                for i in range(s - 1, e):
                    lines.append(Text(""))
                    st = len(lines)
                    lines += self._turn_lines(i, width)
                    items.append(("turn", i, st, len(lines) - st))
            lines.append(Text(""))  # 묶음·턴 사이를 띄운다 (요청 33)
        for i in range(recent_from - 1, n - 1):
            st = len(lines)
            lines += self._turn_lines(i, width)
            items.append(("turn", i, st, len(lines) - st))
            lines.append(Text(""))
        if lines:
            lines.pop()
        lines.append(Text(""))
        self._latest_start = len(lines)
        st = len(lines)
        lines += self._latest(width)
        items.append(("turn", n - 1, st, len(lines) - st))
        self._items = items
        return lines

    def _group_line(self, s: int, e: int, width: int) -> Text:
        """옛 대화 묶음 한 줄: 시작 요청 → 주제 이동·결정 (요청 41: 도구 정보는 두지 않는다)."""
        a = self.analysis
        turns = self.turns[s - 1:e]
        sel = self.cursor_group == s
        line = Text()
        line.append("▸ " if sel else "  ", style="bold")
        line.append("▾ " if s in self.open_groups else "▸ ", style="bold")
        line.append(f"#{s}–{e} ", style="bold")
        room = width - cell_len(line.plain) - 2
        steps = [x for x in ((a or {}).get("flow") or {}).get("steps", []) if s <= x.get("index", 0) <= e and x.get("grounded")]
        infos = [self._turn_info(i) for i in range(s, e + 1)]
        if steps:
            pts = [self._title_of(x) for x in steps[1:] if x.get("shift") or x.get("label") == "확정"]
            text = " → ".join([steps[0].get("summary", "")] + pts)
            line.append(_pad(_one_line(text, room), room))
        elif a and infos[0]:
            pts = [x.get("summary", "") for x in infos[1:] if x and x.get("label") in ("재정의", "범위 축소", "확정")]
            text = " → ".join([infos[0].get("summary", "")] + pts)
            line.append(_pad(_one_line(text, room), room))
        else:
            half = max(8, room // 2 - 2)
            both = f"{_one_line(turns[0].request, half)} ~ {_one_line(turns[-1].request, half)}"
            line.append(_pad(_one_line(both, room), room), style=f"{C.muted}")
        if sel:
            line.stylize(f"on {C.sel}")
        return line

    def _badge(self, t: Turn) -> Text:
        """도구 수·실패 수는 보이지 않는다 (요구 이력 48)."""
        return Text()

    def _turn_head(self, i: int, width: int, sel: bool) -> Text:
        t = self.turns[i]
        line = Text()
        line.append("▸ " if sel else "  ", style="bold")
        line.append(f"{_clock(t.time)} ", style=f"{C.subtle}")
        line.append(f"#{t.index} ", style=f"bold {C.text}")
        label = self._label_of(t.index)
        if label:
            line.append(f"[{label}] ", style=f"{C.info}")
        return line

    def _turn_lines(self, i: int, width: int) -> list:
        """이전 턴: 요청 원문 1줄 + 요약 최대 2줄 (요약이 없으면 원문 앞 2줄).
        단계·도구 정보는 두지 않는다 (요청 41). Enter·o로 원문을 펼친다."""
        t = self.turns[i]
        sel = self.selected == i and not self.cursor_group
        head = self._turn_head(i, width, sel)
        head.append(_one_line(t.request, max(10, width - cell_len(head.plain))))
        lines = [head]
        summary = self._turn_summary(t.index)
        lead = "    "
        pending = self._pending_turn() == t.index and not summary
        tag = "요약 " if summary or pending else "원문 "
        room = max(10, width - cell_len(lead + tag))
        if pending:
            row = Text(lead)
            row.append(tag, style=f"{C.subtle}")
            row.append(self._dots(), style=f"{C.warn}")   # 분석 중: 요약이 들어갈 자리, 상태 줄과 같은 주황 (턴 48)
            lines.append(row)
        else:
            text = summary or strip_md(t.final_response or ("(최종 응답 없음: 진행 중이거나 중단됨)" if t.ended_with_tool else t.response))
            for k, part in enumerate(_wrap(text, room, 2)):
                row = Text(lead if k == 0 else " " * len(lead))
                row.append(tag if k == 0 else " " * cell_len(tag), style=f"{C.subtle}")
                row.append(_pad(part, room), style=f"{C.muted}" if summary else "")
                lines.append(row)
            analyzed_upto = max((self.analysis or {}).get("last_turn") or 0,
                                (((self.analysis or {}).get("flow") or {}).get("until")) or 0)
            if (not summary and self.analysis is not None and t.final_response and self.note != "분석기 꺼짐"
                    and t.index > analyzed_upto):
                lines.append(Text(f"    ↻ 요약 준비 중 (#{t.index} 분석 전)", style=f"{C.warn}"))
        if sel:
            for ln in lines[:1]:
                ln.stylize(f"on {C.sel}")
        if i in self.raw:
            lines += list(self._raw(t).split("\n"))
        return [ln for ln in lines]

    def _latest(self, width: int) -> list:
        """마지막 대화: 요청 원문 전체 + 응답 원문 전체(기본) 또는 요약 보기."""
        i = len(self.turns) - 1
        t = self.turns[i]
        sel = self.selected == i and not self.cursor_group
        lines = []
        head = Text()
        head.append(("▸ " if sel else "") + f"── 마지막 대화 · #{t.index} {_clock(t.time)} ", style=f"bold {C.info}")
        mode = self._latest_mode_text(t)
        head.append(mode, style=f"{C.subtle}")
        head.append(" " + "─" * max(0, width - cell_len(head.plain) - 1), style=f"{C.info}")
        lines.append(head)
        lines.append(Text(""))  # 구분선과 요청 사이를 띄운다 (요청 37)
        label = self._label_of(t.index)
        first = Text("요청  ", style=f"bold {C.info}")
        if label and not self._stale():
            first.append(f"[{label}] ", style=f"{C.info}")
        elif self.status.get("state") == "queued":
            first.append("[분석 대기] ", style=f"{C.warn}")
        elif self.status.get("state") == "running":
            first.append("[분석 중] ", style=f"{C.warn}")
        req_lines = _wrap(t.request, max(10, width - cell_len(first.plain)))
        first.append(req_lines[0])
        lines.append(first)
        for extra in req_lines[1:]:
            lines.append(Text(" " * 6 + extra))
        if self._working():
            lines.append(Text(""))
            if self.view.state == "question":
                lines += self._question_lines(t, width)
            elif self.view.state == "permission":
                lines.append(Text("  ? 허락을 기다리는 중 · y 허용 / n 거절 (패널의 허락 창)", style=f"bold {C.info}"))
            else:
                secs = int(max(0, _now_utc() - _ts_value(t.time))) if t.time else 0
                lines.append(Text(f"  ↻ 에이전트 작업 중 · {secs}초   (지금 쓰는 도구는 ① 세션 목록에)",
                                  style=f"bold {C.warn}"))
        else:
            body = t.final_response or ("(최종 응답 없음: 진행 중이거나 중단됨)" if t.ended_with_tool else t.response)
            summary = (self.analysis or {}).get("last_response_summary", "") if not self._stale() else ""
            if self.summary_mode and not summary:
                self._fallback_turn = t.index          # 요약이 없어 전체를 보이는 중
            arrived_while_reading = self.summary_mode and summary and self._fallback_turn == t.index
            if arrived_while_reading:
                lines.append(Text("  요약이 도착했습니다 · o로 요약 보기 (읽던 전체는 그대로 둡니다)", style=f"{C.warn}"))
            if self.summary_mode and summary and i not in self.raw and not arrived_while_reading:
                row = Text("요약  ", style=f"bold {C.ok}")
                parts = _wrap(summary, max(10, width - 6))
                row.append(parts[0], style=f"{C.muted}")
                lines.append(row)
                for p in parts[1:]:
                    lines.append(Text(" " * 6 + p, style=f"{C.muted}"))
                qs = extract_questions(body)
                for q in qs:
                    for k, p in enumerate(_wrap(q, max(10, width - 8))):
                        lines.append(Text(("  ❓ " if k == 0 else "     ") + p))
                total = len(md_lines(body, width - 2))
                lines.append(Text(f"  o 전체 펼치기 ({total}줄) · 요약은 추정, ❓ 줄은 원문", style=f"{C.subtle}"))
            else:
                lines.append(Text("응답", style=f"bold {C.ok}"))
                for ln in md_lines(body, width - 2):
                    row = Text("  ")
                    row.append_text(ln)
                    lines.append(row)
            lines += self._glossary_lines(body, width)
        badge = self._badge(t)
        tail = Text("  ")
        if badge.plain:
            tail.append_text(badge)
            tail.append(" · ")
        tail.append("Enter 응답까지 한 일 · d 상세", style=f"{C.subtle}")
        lines.append(tail)
        if i in self.expanded:
            lines += list(self._work(t, 2, True).split("\n"))
        for q in self.queued:
            row = Text(f"  ⏳ 보낼 예정 (대기열 {len(self.queued)}건) ", style=f"bold {C.p2}")
            row.append(_one_line(f'"{q}"', max(10, width - cell_len(row.plain) - 2)), style=f"{C.p2}")
            lines.append(Text(""))
            lines.append(row)
            lines.append(Text("     응답이 끝나면 자동으로 보냅니다", style=f"{C.subtle}"))
        if sel and lines:
            lines[0].stylize(f"on {C.sel}")
        return lines

    def _glossary_lines(self, body: str, width: int) -> list:
        """번호 풀이 (요구 이력 51): 마지막 응답의 기획 번호를 프로젝트 문서 원문으로. 분석을 기다리지 않는다."""
        if self.view is None:
            return []
        got = glossary.explain(body, self.view.cwd)
        if not got["items"]:
            return []
        lines = [Text(""), Text("번호 풀이", style="bold")]
        lines[-1].append("  이번 응답 · 문서 원문", style=f"{C.subtle}")
        key_w = min(14, max(cell_len(it["id"]) for it in got["items"]) + 2)
        for it in got["items"]:
            means = it["means"] or ["문서에 없음"]
            for k, mean in enumerate(means[:2]):
                row = Text("  ")
                row.append(_pad(it["id"] if k == 0 else "", key_w), style=f"bold {C.warn}" if k == 0 else "")
                mark = f"{'①②'[k]} " if len(means) > 1 else ""
                row.append(_one_line(mark + mean, max(10, width - key_w - 3)),
                           style=f"{C.subtle}" if not it["means"] else "")
                lines.append(row)
        more = got["total"] - len(got["items"])
        if more > 0:
            lines.append(Text(f"  … {more}개 더", style=f"{C.subtle}"))
        return lines

    def _question_lines(self, t: Turn, width: int) -> list:
        """질문 대기(요청 39): 질문 앞에 에이전트가 한 말 + 질문마다 한 줄과 ③에서 고른 답. 선택지 설명은 ③에만."""
        lines = []
        said = (t.response or "").strip()
        if said:
            lines.append(Text("응답", style=f"bold {C.ok}"))
            for ln in md_lines(said, width - 2):
                row = Text("  ")
                row.append_text(ln)
                lines.append(row)
            lines.append(Text(""))
        qs = self.view.questions
        if not qs:
            lines.append(Text("  ? 질문 창이 답을 기다립니다 · 내용을 읽지 못했으니 패널에서 답하세요", style=f"bold {C.p3}"))
            return lines
        lines.append(Text(f"  ? 질문 {len(qs)}개에 답을 기다립니다 · ③에서 고르거나 패널에서 직접 답하세요",
                          style=f"bold {C.p3}"))
        lines.append(Text(""))
        for n, q in enumerate(qs):
            head = Text()
            head.append(f"  Q{n + 1} ", style=f"bold {C.p3}")
            head.append(q.get("header") or "", style="bold")
            head.append(f" · {'여러 개' if q.get('multiSelect') else '하나'} 고르기 · 선택지 {len(q['options'])}개  ",
                        style=f"{C.subtle}")
            for k, part in enumerate(_wrap(q["question"], max(10, width - cell_len(head.plain)))):
                if k == 0:
                    head.append(part)
                    lines.append(head)
                else:
                    lines.append(Text(" " * cell_len(head.plain) + part))
            got = self.question_answers.get(n)
            row = Text("     → ", style=f"{C.subtle}")
            if got:
                row.append(", ".join(q["options"][k]["label"] for k in sorted(got)), style=f"bold {C.ok}")
                row.append("  (보냄 · 세션 응답 기다림)" if self.question_sent else "  (③에서 고름, 아직 안 보냄)",
                           style=f"{C.subtle}")
            else:
                row.append("아직 고르지 않음", style=f"{C.faint}")
            lines.append(row)
        return lines

    def _latest_mode_text(self, t: Turn) -> str:
        if self._working():
            return "· 작업 중 "
        if not self.summary_mode:
            return "· 마지막 응답 전체 (s 요약 보기) "
        a = self.analysis or {}
        has_summary = bool(a.get("last_response_summary")) and not self._stale()
        if has_summary:  # 화면에 실제로 요약을 보일 때와 같은 조건 (_latest)
            return "· 요약 보기 (s 전체) "
        if self.note == "분석기 꺼짐":
            return "· 분석 꺼짐 → 전체 표시 "
        return "· 요약 준비 중 → 전체 표시 "

    # ---------- 단계 카드 · 원문 · 상세 ----------

    def _work(self, t: Turn, indent: int, fold: bool) -> Text:
        """응답까지 한 일: 에이전트가 중간에 한 말을 단계 카드로. 도구는 보이지 않는다 (요구 이력 48)."""
        out = Text()
        pad = " " * indent
        said = [step for step in t.steps if step.title]
        if not said:
            msg = "중간에 한 말 없이 바로 답했습니다" if t.response else "아직 응답이 없습니다"
            out.append(pad + f"응답까지 한 일: {msg}\n", style=f"{C.subtle}")
            return out
        out.append(pad + f"응답까지 한 일 · 단계 {len(said)}\n", style="bold")
        card_w = min(CARD_MAX, self._width() - indent)
        for n, step in enumerate(said, start=1):
            out.append_text(self._card(n, step, pad, card_w, fold))
        return out

    def _card(self, n: int, step, pad: str, width: int, fold: bool) -> Text:
        """단계 한 줄: 번호와 에이전트가 중간에 한 말. 도구 줄이 없어 상자 대신 한 줄로 둔다 (요구 이력 48)."""
        head = f"{n}. "
        out = Text(pad)
        out.append(head, style=f"{C.subtle}")
        out.append(_one_line(step.title, max(4, width - cell_len(head))))
        out.append("\n")
        return out

    def _raw(self, t: Turn) -> Text:
        out = Text()
        out.append("      ── 원문 ──\n", style=f"{C.subtle}")
        out.append("      요청\n", style=f"{C.subtle}")
        out.append(_indent(t.request, self._width()) + "\n")
        if t.response:
            out.append("      응답\n", style=f"{C.subtle}")
            out.append(_indent(t.response, self._width()) + "\n")
        return out

    def _detail(self, t: Turn, width: int) -> Text:
        """응답 상세 화면 (보조): 요청·최종 응답 전체와 접지 않은 단계 카드."""
        out = Text()
        out.append("← Esc 대화 목록   ", style=f"{C.subtle}")
        label = self._label_of(t.index)
        out.append(f"#{t.index}{f' [{label}]' if label else ''} 응답 상세", style="bold")
        out.append(f"   ({self.selected + 1}/{len(self.turns)}, ←→ 이전·다음 응답)\n\n", style=f"{C.subtle}")
        out.append("사용자 요청\n", style=f"bold {C.info}")
        for part in _wrap(t.request, max(10, width - 1)):
            out.append(part + "\n")
        out.append("\n")
        out.append("에이전트 응답\n", style=f"bold {C.ok}")
        body = t.final_response or ("(최종 응답 없음: 진행 중이거나 중단됨)" if t.ended_with_tool else t.response)
        for ln in md_lines(body, width - 2):
            out.append_text(ln)
            out.append("\n")
        out.append("\n")
        out.append_text(self._work(t, 0, False))
        if self.selected in self.raw:
            out.append("\n")
            out.append_text(self._raw(t))
        return out


def _indent(text: str, width: int = 0) -> str:
    rows = []
    for row in text.splitlines() or [""]:
        if width:
            rows += ["        " + part for part in _wrap(row, max(10, width - 9))] if row.strip() else ["        "]
        else:
            rows.append("        " + row)
    return "\n".join(rows)
