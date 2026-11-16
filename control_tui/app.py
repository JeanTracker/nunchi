"""관제 TUI 앱. SCREEN.md §1 (넓은 화면 배치).

Phase 3 범위: ③ 입력줄(SCREEN §4)을 채운다. 바로 보내기, 일하는 중이면 대기열, 허락 중이면 y/n만.
①②는 Phase 2에서 확인한 그대로다.
"""

import time
from datetime import datetime, timezone
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.widgets import Header, Static

import json
import os

from control_tui.glyphs import SymbolGap
from control_tui import analyzer as analyzer_mod
from control_tui import worker as worker_mod
from control_tui import clipboard as clipboard_mod, completion, config, lifecycle, outbox as outbox_rules, panels, settings as settings_mod, store, transcript
from control_tui.adapters.iterm2_adapter import ITerm2Adapter
from control_tui.adapters.terminal_base import TerminalError
from control_tui.outbox import Outbox
from control_tui.widgets.conversation import Conversation
from control_tui.widgets.input_line import CommandInput, suggestion_for
from control_tui.widgets.question_picker import QuestionPicker, key_label
from control_tui.widgets.session_list import fit
from control_tui.widgets.session_list import STATE_LABEL, SessionList
from control_tui import theme as theme_mod
from control_tui.theme import C

REFRESH_SECONDS = 1.0
FILE_CACHE_SECONDS = 15.0
CONTROL_FILE = "control.json"   # 관제 자신의 iTerm 패널과 pid (mod 관제로 버튼이 읽음, 요구 이력 56)
GOTO_FILE = "goto"              # mod 관제로 버튼이 남기는 {session, at}
GOTO_MAX_AGE = 30.0             # 이보다 오래된 goto는 버린다 (초)
SENT_MARGIN = 5.0               # 관제가 보낸 글의 입력 기록으로 보는 범위 (초)
SHIFT_TAB = "\x1b[Z"  # 터미널이 보내는 Shift+Tab. Claude Code는 이것으로 권한 모드를 바꾼다

# Claude Code 권한 모드 순서 (2.1.319 실행 파일 기준): default, acceptEdits, plan, auto, bypassPermissions, dontAsk
MODE_LABEL = {
    "default": "기본",
    "acceptEdits": "편집 자동 허용",
    "plan": "계획",
    "auto": "자동(auto)",
    "bypassPermissions": "모두 허용",
    "dontAsk": "묻지 않음",
}
PANEL_SCAN_SECONDS = 10.0  # iTerm 패널 훑기는 무겁다 (osascript). 1초마다 하지 않는다
RETRY_SECONDS = 10.0       # 대기열 전송이 실패한 세션은 이 시간 뒤에 다시 시도한다


class KeyBar(Static):
    """맨 아래 한 줄. 끌어서 고를 글이 아니다 (클립보드, 요청 32)."""
    ALLOW_SELECT = False


class ControlApp(App):
    TITLE = "관제 TUI"

    CSS = """
    Grid {
        grid-size: 2 2;
        grid-columns: 1fr 2fr;
        grid-rows: 1fr auto;
        height: 1fr;
    }
    /* 지금 구역은 구역 색 굵은 테두리 + 색 띠 제목, 나머지는 흐린 얇은 테두리 (요청 36, SCREEN §10) */
    #sessions, #conversation, #input {
        border: round $border-idle;
        border-title-align: left;
        border-title-color: $text-subtle;
    }
    #sessions {
        overflow-y: auto;
    }
    #conversation {
        overflow: hidden hidden;
    }
    #input {
        column-span: 2;
        height: auto;
    }
    #sessions:focus-within {
        border: heavy $pane-1;
        border-title-color: $background;
        border-title-background: $pane-1;
        border-title-style: bold;
    }
    #conversation:focus-within {
        border: heavy $pane-2;
        border-title-color: $background;
        border-title-background: $pane-2;
        border-title-style: bold;
    }
    #input:focus-within {
        border: heavy $pane-3;
        border-title-color: $background;
        border-title-background: $pane-3;
        border-title-style: bold;
    }
    #keybar {
        dock: bottom;
        height: 1;
        background: $bar;
        text-wrap: nowrap;
        text-overflow: clip;
    }
    #input_info {
        height: 1;
    }
    #input_menu {
        height: auto;
        max-height: 8;
    }
    #question_picker {
        height: auto;
    }
    #input_box {
        height: auto;
        min-height: 3;
        max-height: 8;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "종료"),
        # 한글 입력기 상태에서는 Ctrl 조합도 한글로 온다 (2026-11-10 실제 키 확인: Ctrl+Q → ctrl+ㅂ)
        Binding("ctrl+ㅂ", "quit", "종료", show=False, priority=True),
        Binding("ctrl+ㅔ", "command_palette", "명령", show=False),
        Binding("tab", "focus_next", "다음 구역"),
        Binding("i", "focus_input", "입력", show=False),
        Binding("colon", "focus_input", "입력", show=False),
        Binding("y", "permit('y')", "허용", show=False),
        Binding("n", "permit('n')", "거절", show=False),
        Binding("a", "analyze_now", "분석", show=False),
        Binding("r", "analyze_now", "분석 다시", show=False),
        Binding("p", "jump_panel", "패널로", show=False),
        Binding("pageup", "conv_page(-1)", "대화 위로", show=False),
        Binding("pagedown", "conv_page(1)", "대화 아래로", show=False),
        # 복사·붙여넣기 (요청 32, SCREEN §3). 입력줄에 있을 때는 입력줄의 같은 키가 먼저 받는다
        Binding("ctrl+ㅊ", "screen.copy_text", "복사", show=False),  # 한글 상태의 Ctrl+C
        Binding("ctrl+v,ctrl+ㅍ", "paste_to_input", "붙여넣기", show=False),
    ]

    def __init__(self, home: Path | None = None, panel_scanner=None, terminal=None,
                 panel_checker=None, skill_home: Path | None = None, analyzer=None,
                 clipboard=None, liveness_checker=None, **kwargs):
        super().__init__(**kwargs)
        # 넓게 그려지는 기호(… → ◆ ●) 뒤에 글자가 붙으면 한 칸 띄운다 (요구 이력 58)
        self._filters.append(SymbolGap())
        self.home = home
        self.settings = settings_mod.load(home or store.base_dir())
        # 분석기: 설정 파일의 분석 대상이 '끄기'이거나 CONTROL_TUI_ANALYZE=0이면 끈다 (테스트는 끈다)
        if (analyzer is None and os.environ.get("CONTROL_TUI_ANALYZE", "1") != "0"
                and self.settings.analyze_scope != "off"):
            # 분석은 관제 밖 백그라운드 분석기가 한다. 관제는 요청을 남기고 결과·상태 파일을 읽는다 (요구 이력 52·53)
            analyzer = worker_mod.QueueAnalyzer(home or store.base_dir(), workers=self.settings.analyze_workers)
        self.analyzer = analyzer
        # 켤 때 이미 끝난 옛 응답은 한꺼번에 분석하지 않는다 (고른 세션만 예외)
        self.started_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        self._last_sent: dict = {}       # 세션 -> 마지막으로 보낸 시각 (UTC 문자열)
        self._seen_analysis: dict = {}   # 세션 -> 화면에서 본 분석 시각 (① '새' 표시용)
        self._glossary_sig: dict = {}    # 세션 -> 번호 풀이를 쓴 응답 (요구 이력 51)
        self.skill_home = skill_home or Path.home()  # 스킬과 명령 파일을 찾는 사용자 폴더
        self._command_cache: dict = {}
        self._file_cache: dict = {}  # 폴더 -> (읽은 시각, 파일 목록)
        self.panel_scanner = panel_scanner or panels.scan
        self.panel_checker = panel_checker or panels.claude_panel_ids  # 지금 claude가 떠 있는 패널 목록
        # 닫힌 세션 판정용 패널 확인. 확인 못 하면 None (요청 35, BUILD_PLAN §3.1.1)
        self.liveness_checker = liveness_checker or (lambda: panels.alive_panel_ids())
        self.closed = lifecycle.ClosedTracker()
        self._last_alive_check = None
        self._alive_busy = False  # 뒤에서 패널 확인이 도는 중
        self.terminal = terminal or ITerm2Adapter()
        # 맥 클립보드. Textual의 clipboard(관제 안 클립보드)와 이름이 겹치지 않게 따로 둔다
        self.system_clipboard = clipboard or clipboard_mod.MacClipboard()
        self.outbox = Outbox()
        self._pending: list = []
        self._last_scan = None
        self._retry_after: dict = {}
        self._message: tuple = ()  # (글, 색) 마지막 입력 결과
        self.session_list = SessionList()
        self.conversation = Conversation()
        self.input_box = CommandInput(placeholder="지시를 치고 Enter (\\ 끝 또는 Ctrl+J: 줄바꿈)", id="input_box")
        self.info_line = Static("", id="input_info")
        self.menu_box = Static("", id="input_menu")
        self.question_picker = QuestionPicker(id="question_picker")  # 질문 대기면 입력칸 대신 (요청 39)
        self.question_picker.display = False
        self.keybar = KeyBar("", id="keybar")
        for t in theme_mod.textual_themes():
            self.register_theme(t)
        self.theme = theme_mod.textual_name(C.use(self.settings.theme))

    def compose(self) -> ComposeResult:
        yield Header()
        with Grid():
            sessions = Vertical(self.session_list, id="sessions")
            sessions.border_title = "① 세션 목록"
            yield sessions
            conv = Vertical(self.conversation, id="conversation")
            conv.border_title = "② 고른 세션의 대화"
            yield conv
            inp = Vertical(self.info_line, self.menu_box, self.question_picker, self.input_box, id="input")
            inp.border_title = "③ 입력"
            yield inp
        yield self.keybar

    def get_css_variables(self) -> dict:
        """우리 테마의 변수(pane-1 등)를 늘 넣는다. Textual 기본 테마로 바꿔도 CSS가 깨지지 않게 (요청 36)."""
        variables = super().get_css_variables()
        t = theme_mod.THEMES[C.name]
        variables.setdefault("pane-1", t["p1"])
        variables.setdefault("pane-2", t["p2"])
        variables.setdefault("pane-3", t["p3"])
        variables.setdefault("border-idle", t["idle"])
        variables.setdefault("text-subtle", t["subtle"])
        variables.setdefault("bar", t["bar"])
        return variables

    def _on_theme_changed(self, textual_theme) -> None:
        """명령 팔레트로 테마를 바꾸면 Rich로 그리는 글자 색도 같은 테마로 바꾼다."""
        name = theme_mod.plain_name(getattr(textual_theme, "name", ""))
        if not name:
            return  # Textual 기본 테마: 글자 색은 지금 우리 테마 그대로
        C.use(name)
        self.session_list.refresh_content()
        self.conversation.refresh_content()
        self._render_info()
        self.refresh_keybar()

    def on_descendant_focus(self, event) -> None:
        self.refresh_keybar()

    def refresh_keybar(self) -> None:
        """맨 아래 줄: 지금 구역 이름 띠 + 그 자리에서 지금 쓸 수 있는 키 (SCREEN §10)."""
        if not self.is_mounted:
            return
        focused = self.focused
        view = self.session_list.selected()
        permission = view is not None and view.state == "permission" and config.PERMISSION_KEYS_VERIFIED
        question = view is not None and view.state == "question"
        conv = self.conversation
        if focused is self.question_picker:
            pane, name = 3, "③ 질문 답하기"
            keys = self.question_picker.keybar()
        elif focused is self.input_box or focused is self.menu_box:
            pane, name = 3, "③ 입력"
            keys = [("Enter", "보내기"), ("⇧Enter", "줄바꿈"), ("↑↓", "이전 글"), ("Tab", "추천·다음 구역"),
                    ("⇧Tab", "권한 모드"), ("PgUp/Dn", "대화 스크롤"), ("Esc", "지우기"), ("^q", "종료")]
        elif focused is conv and conv.askall:
            pane, name = 2, "② 묻는 것 전체"
            keys = [("PgUp/Dn", "스크롤"), ("k·Esc", "닫기"), ("q", "종료")]
        elif focused is conv and conv.flowall:
            pane, name = 2, "② 흐름 전체"
            keys = [("PgUp/Dn", "스크롤"), ("g·Esc", "닫기"), ("q", "종료")]
        elif focused is conv and conv.checklist:
            pane, name = 2, "② 요청 전체"
            keys = [("↑↓", "고르기"), ("Enter", "그 요청의 턴으로"), ("c·Esc", "닫기"), ("q", "종료")]
        elif focused is conv and conv.detail:
            pane, name = 2, "② 응답 상세"
            keys = [("Esc", "목록으로"), ("o", "원문"), ("PgUp/Dn", "스크롤"), ("q", "종료")]
        elif focused is conv:
            pane, name = 2, "② 대화"
            keys = [("↑↓", "턴"), ("Enter", "펼치기"), ("g", "흐름 전체"), ("k", "묻는 것"), ("c", "요청 전체"), ("d", "상세"), ("o", "원문"),
                    ("s", "요약 보기"), ("p", "세션 창"), ("PgUp/Dn", "스크롤"), ("]", "마지막"), ("Tab", "다음 구역")]
            if permission:  # 허락 대기면 입력줄이 잠기므로 y/n은 ①②에서 받는다
                keys = [("y", "허용"), ("n", "거절")] + keys
            elif question:  # 질문 대기는 ③ 질문 답하기로 (y/n은 질문에 쓰지 않는다, 요청 39)
                keys = [("i", "질문 답하기")] + keys
            keys += [("q", "종료")]
        else:
            pane, name = 1, "① 세션 목록"
            keys = [("↑↓", "세션 고르기"), ("p", "세션 창으로"), ("Tab", "다음 구역"), ("i", "입력"), ("a", "분석"), ("q", "종료")]
            if permission:
                keys = [("y", "허용"), ("n", "거절")] + keys
            elif question:
                keys = [("i", "질문 답하기")] + [k for k in keys if k[0] != "i"]
        color = C.pane(pane)
        out = Text()
        out.append(f" {name} ", style=f"bold {C.bg} on {color}")
        for key, desc in keys:
            out.append("  ")
            out.append(key, style=f"bold {color}")
            out.append(" " + desc, style=C.text)
        self.keybar.update(out)

    def on_mount(self) -> None:
        self._started_at = time.time()
        self._blurred_at = None
        self._write_control()
        self.theme_changed_signal.subscribe(self, self._on_theme_changed)
        self.refresh_keybar()
        self.refresh_sessions()
        self.set_interval(REFRESH_SECONDS, self.refresh_sessions)
        self.session_list.focus()

    def on_unmount(self) -> None:
        self._remove_control()
        if self.analyzer is not None:
            self.analyzer.shutdown()  # 기다리던 분석은 버리고 바로 끝낸다 (요청 25~29, BUILD_PLAN §4.1)

    # ---------- 관제로 돌아오기 (요구 이력 56, BUILD_PLAN §4.8) ----------

    def _control_path(self) -> Path:
        return (self.home or store.base_dir()) / CONTROL_FILE

    def _write_control(self) -> None:
        """mod의 관제로 버튼이 이 패널을 찾도록 자기 iTerm 패널과 pid를 남긴다. 다른 관제가 살아 있으면 두지 않는다."""
        sid = os.environ.get("ITERM_SESSION_ID", "")
        if not sid:
            return
        path = self._control_path()
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("pid") != os.getpid() and _pid_alive(old.get("pid")):
                return
        except (OSError, ValueError):
            pass
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"iterm_session_id": panels.panel_id_of(sid), "pid": os.getpid(),
                                        "at": time.time()}) + "\n", encoding="utf-8")
        except OSError:
            pass

    def _remove_control(self) -> None:
        path = self._control_path()
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
                path.unlink()
        except (OSError, ValueError):
            pass

    def on_app_blur(self, event) -> None:
        self._blurred_at = time.time()

    def on_app_focus(self, event) -> None:
        since, self._blurred_at = getattr(self, "_blurred_at", None), None
        if since is None:   # 떠난 기록이 없으면 돌아옴으로 보지 않는다 (SCREEN §8: 첫 focus가 오지 않은 경우)
            return
        self._return_to(since)

    def _take_goto(self, since: float) -> str:
        """mod 관제로 버튼이 남긴 요청. 읽으면 지운다. 관제가 켜지기 전·오래된 것은 버린다."""
        path = (self.home or store.base_dir()) / GOTO_FILE
        try:
            req = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        try:
            path.unlink()
        except OSError:
            pass
        at = float(req.get("at") or 0)
        started = getattr(self, "_started_at", 0.0)
        if at < max(since - 2, started) or time.time() - at > GOTO_MAX_AGE:
            return ""
        return str(req.get("session") or "")

    def _recent_prompt(self, since: float) -> str:
        """자리를 비운 사이 사용자가 세션에 직접 입력한 것 중 가장 최근. 관제가 보낸 글은 뺀다."""
        best, best_at = "", since
        for v in self.session_list.views:
            at = transcript._ts_value(v.prompt_ts) if v.prompt_ts else 0.0
            if at <= best_at:
                continue
            sent = self._last_sent.get(v.session_id)
            if sent and abs(transcript._ts_value(sent) - at) <= SENT_MARGIN:
                continue
            best, best_at = v.session_id, at
        return best

    def _return_to(self, since: float) -> None:
        target, why = self._take_goto(since), "mod에서 관제로"
        if not target:
            self.refresh_sessions()   # 그 사이 입력 기록을 읽는다
            target, why = self._recent_prompt(since), "방금 입력한 세션"
        self._select_returned(target, why)

    def _select_returned(self, target: str, why: str) -> None:
        current = self.session_list.selected()
        view = next((v for v in self.session_list.views if v.session_id == target), None)
        if view is None or (current is not None and current.session_id == target):
            return
        picking = (current is not None and current.state == "question"
                   and self.question_picker.answers and not self.question_picker.sent)
        if self.input_box.text.strip() or picking:
            # 쓰던 글이 다른 세션으로 가지 않게 고른 세션은 그대로 둔다
            self._say(f"{view.title} 세션에서 돌아옴 · 쓰던 글이 있어 고른 세션을 그대로 둠", f"{C.warn}")
            return
        self.session_list.selected_id = target
        self.session_list.acknowledged.add(target)
        self.refresh_sessions()
        self._say(f"{view.title} 세션을 골랐습니다 · {why}", f"{C.info}")

    # ---------- 세션 목록 ----------

    def _pending_views(self, linked_panel_ids: set) -> list:
        """연결 대기 세션. 패널 훑기는 PANEL_SCAN_SECONDS마다 한 번만 한다."""
        now = time.monotonic()
        if self._last_scan is None or now - self._last_scan >= PANEL_SCAN_SECONDS:
            self._last_scan = now
            try:
                self._pending = self.panel_scanner(linked_panel_ids)
            except Exception:  # 패널 훑기가 실패해도 기록 화면은 계속 돈다
                self._pending = []
        # 그 사이 훅 기록이 생긴 패널은 바로 뺀다
        return [v for v in self._pending if v.iterm_session_id not in linked_panel_ids]

    def _check_alive(self) -> None:
        """패널에 claude가 떠 있는지 PANEL_SCAN_SECONDS마다 확인한다 (닫힌 세션 판정)."""
        now = time.monotonic()
        if self._alive_busy or (self._last_alive_check is not None
                                and now - self._last_alive_check < PANEL_SCAN_SECONDS):
            return
        self._last_alive_check = now
        self._alive_busy = True
        # osascript와 ps로 0.5초쯤 걸린다(2026-11-10 이 맥에서 457ms). 화면이 멈추지 않게 뒤에서 돌린다
        self.run_worker(self._alive_worker, thread=True, group="alive", exit_on_error=False)

    def _alive_worker(self) -> None:
        at = lifecycle.now_iso()  # 확인 전에 시각을 잡는다. 확인 도중 생긴 기록은 다음 확인에서 판정한다
        try:
            alive = self.liveness_checker()
        except Exception:  # 확인이 실패하면 아무것도 바꾸지 않는다
            alive = None
        self.call_from_thread(self._alive_done, alive, at)

    def _alive_done(self, alive, at: str) -> None:
        self.closed.update_alive(alive, at)
        self._alive_busy = False

    def _wants_analysis(self, v, selected_id: str) -> bool:
        """설정에 따라 이 세션을 자동으로 분석할지 (BUILD_PLAN §4.1)."""
        if self.analyzer is None or not v.responded_ts or self.settings.analyze_when != "auto":
            return False
        if v.session_id == selected_id:
            return True
        return self.settings.analyze_scope == "all" and v.responded_ts > self.started_ts

    def _write_glossary(self, v, session_dir: Path) -> None:
        """mod가 읽을 번호 풀이 (요구 이력 51). 응답이 새로 끝났을 때만 마지막 응답을 읽어 세션 폴더에 쓴다."""
        sig = (v.responded_ts or "", v.transcript_path or "")
        if not v.responded_ts or not v.transcript_path or self._glossary_sig.get(v.session_id) == sig:
            return
        self._glossary_sig[v.session_id] = sig
        worker_mod.write_glossary(session_dir, v.transcript_path, v.cwd)   # 분석기도 같은 함수로 쓴다 (관제가 꺼져 있을 때)

    def refresh_sessions(self) -> None:
        if getattr(self, "_blurred_at", 1) is None and ((self.home or store.base_dir()) / GOTO_FILE).exists():
            # 관제가 이미 앞에 있을 때 mod 버튼이 누른 것 (focus 알림이 오지 않음)
            target = self._take_goto(time.time() - GOTO_MAX_AGE)
            if target:
                self.call_later(self._select_returned, target, "mod에서 관제로")
        views = store.load_sessions(self.home)
        linked = {panels.panel_id_of(v.iterm_session_id) for v in views if v.iterm_session_id}
        views = views + self._pending_views(linked)
        base = self.home or store.base_dir()
        current = self.session_list.selected()
        self._check_alive()
        self.closed.mark(views)
        views = lifecycle.arrange(views, selected_id=current.session_id if current else "")
        views = lifecycle.group_views(views)   # 프로젝트 폴더별로 (요구 이력 59)
        for v in views:
            v.name = transcript.session_title(v.transcript_path)
        selected_id = current.session_id if current else (views[0].session_id if views else "")
        if self.analyzer is not None:
            self.analyzer.prioritize(selected_id)
        for v in views:  # 분석 결과를 읽고, 설정에 맞으면 분석을 예약한다
            if v.state == "pending" or not v.session_id:
                continue
            session_dir = base / "sessions" / v.session_id
            analysis = analyzer_mod.read_analysis(session_dir)
            v.missed = analyzer_mod.missed_count(analysis) if analysis else 0
            v.judged = analysis is not None
            if self._wants_analysis(v, selected_id):
                self.analyzer.request(v.session_id, session_dir, v.transcript_path, v.responded_ts)
            v.analysis_mark = self._mark_for(v, analysis, selected_id)
            self._write_glossary(v, session_dir)
        self.session_list.set_views(views)
        self._flush_outbox(views)
        view = self.session_list.selected()
        turns = self._turns_of(view.transcript_path) if view and view.transcript_path else []
        analysis, note, status = None, "", {}
        if view is not None and view.session_id:
            analysis = analyzer_mod.read_analysis(base / "sessions" / view.session_id)
            if self.analyzer is None:
                note = "분석기 꺼짐"
            else:
                status = self.analyzer.status(view.session_id)
            if analysis:
                self._seen_analysis[view.session_id] = analysis.get("analyzed_at", "")
        sent = self._last_sent.get(view.session_id, "") if view else ""
        sent_after = bool(analysis and sent and view.responded_ts and sent > view.responded_ts)
        queued = self.outbox.queues.get(view.session_id, []) if view else []
        self.conversation.show(view, turns, analysis, note, status=status, queued=queued,
                               latest_view=self.settings.latest_view, sent_after=sent_after)
        self._sync_input(view)

    def _turns_of(self, path: str) -> list:
        """대화 기록은 바뀌었을 때만 다시 읽는다 (크기·수정 시각). 매초 긴 기록을 다시 읽지 않게 (Liner 리뷰)."""
        try:
            st = Path(path).stat()
            sig = (path, st.st_size, st.st_mtime_ns)
        except OSError:
            return []
        cached = getattr(self, "_turn_cache", None)
        if cached and cached[0] == sig:
            return cached[1]
        turns = transcript.parse_turns(Path(path))
        self._turn_cache = (sig, turns)
        return turns

    def _mark_for(self, v, analysis, selected_id: str) -> str:
        """① 누락 표시 옆 기호: · 대기, ↻ 분석 중, ! 실패, 새 (확인 안 한 새 빠짐)."""
        if self.analyzer is None:
            return ""
        st = self.analyzer.status(v.session_id).get("state", "")
        if st == "queued":
            return "·"
        if st == "running":
            return "↻"
        if st == "failed":
            return "!"
        changes = (analysis or {}).get("changes") or {}
        if (changes.get("new_missed") and v.session_id != selected_id
                and self._seen_analysis.get(v.session_id) != (analysis or {}).get("analyzed_at")):
            return "새"
        return ""

    def action_analyze_now(self) -> None:
        """a: 지금 고른 세션을 분석 (수동 모드), r: 실패한 분석 다시."""
        view = self.session_list.selected()
        if self.analyzer is None:
            self._say("분석기가 꺼져 있습니다 (설정 파일 analyze_scope).", f"{C.warn}")
            return
        if view is None or not view.responded_ts:
            self._say("분석할 응답이 없습니다.", f"{C.warn}")
            return
        base = self.home or store.base_dir()
        ok = self.analyzer.request(view.session_id, base / "sessions" / view.session_id,
                                   view.transcript_path, view.responded_ts, force=True)
        self._say("분석을 시작합니다." if ok else "이미 분석했거나 분석 중입니다.", f"{C.ok}" if ok else f"{C.muted}")

    # 한글 입력기가 켜져 있으면 단축키 글자가 한글 자모로 들어온다 (두벌식). 입력줄 밖에서는 같은 키로 받는다.
    # 2026-11-10 Liner 검토(review/out-keys): q·y·n 등이 ㅂ·ㅛ·ㅜ로 와서 듣지 않는다.
    JAMO_KEYS = {"ㅂ": "q", "ㅑ": "i", "ㅛ": "y", "ㅜ": "n", "ㅁ": "a", "ㄱ": "r", "ㅔ": "p",
                 "ㅐ": "o", "ㅇ": "d", "ㄴ": "s", "ㅊ": "c", "ㅎ": "g", "ㅏ": "k"}

    def on_key(self, event) -> None:
        key = self.JAMO_KEYS.get(event.character or "")
        if not key or self.focused is self.input_box:
            return  # 입력줄에서는 한글을 글자로 쓴다
        event.stop()
        event.prevent_default()
        if key == "q":
            self.exit()
        elif key == "i":
            self.action_focus_input()
        elif key in ("y", "n"):
            if self.check_action("permit", (key,)):
                self.action_permit(key)
        elif key in ("a", "r"):
            self.action_analyze_now()
        elif key == "p":
            self.action_jump_panel()
        elif self.focused is self.conversation:
            {"o": self.conversation.action_raw, "d": self.conversation.action_detail,
             "s": self.conversation.action_summary_view, "c": self.conversation.action_checklist,
             "g": self.conversation.action_flow_all, "k": self.conversation.action_ask_all}[key]()

    def action_jump_panel(self) -> None:
        """p: 고른 세션의 iTerm 패널을 앞으로 (요구 이력 56, SCREEN §3). 그 세션 옆에 mod 패널이 있다."""
        view = self.session_list.selected()
        if view is None:
            return
        focus = getattr(self.terminal, "focus", None)
        if focus is None:
            self._say("이 터미널에서는 패널로 옮겨 갈 수 없습니다.", f"{C.warn}")
            return
        if not view.iterm_session_id:
            self._say("이 세션은 iTerm 패널과 짝이 없어 옮겨 갈 수 없습니다.", f"{C.warn}")
            return
        try:
            alive = panels.panel_id_of(view.iterm_session_id) in self.panel_checker()
        except Exception:
            alive = True   # 확인하지 못하면 옮겨 가 본다 (보내기와 달리 글이 셸로 가지 않는다)
        if not alive:
            self._say("그 패널에 Claude가 떠 있지 않습니다. 패널이 닫혔는지 보세요.", f"{C.err}")
            return
        panel, title = panels.panel_id_of(view.iterm_session_id), view.title
        self.run_worker(lambda: self._focus_panel(focus, panel, title), thread=True, exclusive=True, group="focus")

    def _focus_panel(self, focus, panel: str, title: str) -> None:
        try:
            focus(panel)
        except TerminalError as e:
            self.call_from_thread(self._say, f"패널로 옮기지 못했습니다: {e}", f"{C.err}")
            return
        self.call_from_thread(self._say, f"{title} 패널로 옮겼습니다 · 돌아오려면 ⌘숫자 또는 mod의 관제로", f"{C.info}")

    def action_conv_page(self, delta: int) -> None:
        self.conversation.action_page(delta)

    def on_command_input_scroll_requested(self, event) -> None:
        self.conversation.action_page(event.delta)

    # ---------- 복사·붙여넣기 (요청 32, BUILD_PLAN §5.1.1) ----------

    def copy_to_clipboard(self, text: str) -> None:
        """관제 안 클립보드와 OSC 52에 더해 맥 클립보드에도 쓴다.

        iTerm2가 앱의 클립보드 접근을 막으면 OSC 52는 버려진다(SCREEN §8). 그래서 pbcopy로도 쓴다.
        """
        super().copy_to_clipboard(text)
        if self.system_clipboard.write(text):
            self._say(f"복사했습니다 · {len(text):,}자", f"{C.ok}")
        else:
            self._say("맥 클립보드에 복사하지 못했습니다 (pbcopy 실패). 관제 안에서는 Ctrl+V로 붙여 넣을 수 있습니다.", f"{C.err}")

    def read_clipboard(self) -> str:
        """붙여 넣을 글. 맥 클립보드가 먼저이고, 읽지 못하면 관제 안에서 복사한 글."""
        text = self.system_clipboard.read()
        return text if text is not None else self.clipboard

    def on_mouse_down(self, event) -> None:
        """끌기를 어디서 시작했는지 적어 둔다. 고를 수 없는 곳(맨 아래 줄 등)에서 시작한 끌기는 복사하지 않는다."""
        try:
            widget, _ = self.screen.get_widget_at(event.screen_x, event.screen_y)
        except Exception:
            widget = None
        self._drag_selectable = widget is None or widget.allow_select

    def on_text_selected(self, event) -> None:
        """②①에서 끌어 고르고 마우스를 놓으면 바로 복사한다 (iTerm2와 같은 동작)."""
        if self.focused is self.input_box and self.input_box.selected_text:
            return  # 입력줄 안에서 고른 글은 입력줄이 복사한다
        if not getattr(self, "_drag_selectable", True):
            return  # Textual은 고를 수 없는 곳에서 놓아도 TextSelected를 보내 옛 선택을 다시 복사하게 된다
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)

    def on_paste(self, event) -> None:
        """입력줄이 아닌 곳에 온 붙여넣기(Cmd+V). 입력줄에 온 것은 입력줄이 받고 멈춘다."""
        event.stop()
        self._paste_into_input(event.text)

    def action_paste_to_input(self) -> None:
        """입력줄 밖에서 Ctrl+V."""
        self._paste_into_input(self.read_clipboard())

    def _paste_into_input(self, text: str) -> None:
        if not text:
            return
        if self.question_picker.display:
            self._say("질문에 답을 기다리는 중이라 붙여 넣지 않았습니다. 직접 쓰는 답은 패널에서 하세요.", f"{C.warn}")
            return
        if self.input_box.disabled:
            self._say("허락을 기다리는 중이라 붙여 넣지 않았습니다. y 또는 n으로 답하세요.", f"{C.warn}")
            return
        self.input_box.focus()
        self.input_box.insert(text)

    # ---------- ③ 입력줄 ----------

    def _say(self, text: str, style: str = "") -> None:
        self._message = (text, style)
        self._render_info()

    def _render_info(self) -> None:
        view = self.session_list.selected()
        out = Text()
        if view is None:
            out.append("세션을 고르면 여기서 지시를 보냅니다.", style=f"{C.muted}")
        else:
            label, color = STATE_LABEL.get(view.state, (view.state, "text"))
            color = C.get(color)
            out.append(f"→ {view.title} #{view.session_id[:4]}", style="bold")
            out.append(f"  {label.strip()}", style=color)
            mode = MODE_LABEL.get(view.permission_mode, view.permission_mode) if view.permission_mode else "알 수 없음"
            out.append(f"  모드 {mode}", style=f"{C.info}")
            queued = self.outbox.count(view.session_id)
            if queued:
                out.append(f"  대기열 {queued}건", style=f"{C.warn}")
        if self._message:
            text, style = self._message
            out.append(f"   {text}", style=C.get(style) if style else C.muted)
        self.info_line.update(out)

    def _sync_input(self, view) -> None:
        """허락 기다리는 세션이면 글자 입력을 막는다 (SCREEN §4)."""
        question = view is not None and view.state == "question"
        locked = view is not None and view.state in ("permission", "question")
        self.question_picker.display = question
        self.input_box.display = not question
        if question:
            self.question_picker.load(view.question_id, view.questions)
        elif self.focused is self.question_picker:
            self.session_list.focus()
        self.conversation.question_answers = self.question_picker.answers if question else {}
        self.conversation.question_sent = question and self.question_picker.sent
        self.input_box.disabled = locked
        self.input_box.set_base_placeholder(
            "허락 기다리는 중: y 또는 n" if locked else "지시를 치고 Enter"
        )
        self.input_box.set_suggestion("" if locked or view is None else suggestion_for(view.state))
        self.input_box.set_commands([] if locked else self._commands_for(view))
        self.input_box.set_file_provider(lambda v=view: self._files_for(v))
        if locked and self.focused is self.input_box:
            self.session_list.focus()
        self._render_info()
        self.refresh_keybar()

    def _commands_for(self, view) -> list:
        """내장 명령 + 이 세션 폴더의 스킬과 명령 파일. 폴더별로 한 번만 읽는다."""
        project = Path(view.cwd) if view is not None and view.cwd else None
        key = str(project)
        if key not in self._command_cache:
            self._command_cache[key] = completion.gather(self.skill_home, project)
        return self._command_cache[key]

    def _files_for(self, view) -> list:
        """세션 폴더의 파일 목록. @를 칠 때만 불리고, 15초 동안 다시 읽지 않는다."""
        root = Path(view.cwd) if view is not None and view.cwd else None
        if root is None or not root.is_dir():
            return []
        key, now = str(root), time.monotonic()
        cached = self._file_cache.get(key)
        if cached is None or now - cached[0] > FILE_CACHE_SECONDS:
            self._file_cache[key] = (now, completion.list_files(root))
        return self._file_cache[key][1]

    def on_command_input_mode_cycle_requested(self, event: CommandInput.ModeCycleRequested) -> None:
        self.action_cycle_mode()

    def action_cycle_mode(self) -> None:
        """Shift+Tab을 세션에 보낸다. 보내기 전 패널 확인은 글 보내기와 같다."""
        view = self.session_list.selected()
        if view is None:
            self._say("먼저 ①에서 세션을 고르세요.", f"{C.warn}")
            return
        problem = self._send_problem(view)
        if problem:
            self._say(problem, f"{C.err}")
            return
        try:
            self.terminal.send_text(panels.panel_id_of(view.iterm_session_id), SHIFT_TAB, enter=False)
        except TerminalError as e:
            self._say(f"모드를 바꾸지 못했습니다: {e}", f"{C.err}")
            return
        self._say("권한 모드를 바꿨습니다. 표시는 세션이 다음에 알려 줄 때 갱신됩니다.", f"{C.ok}")

    def on_command_input_menu_changed(self, event: CommandInput.MenuChanged) -> None:
        if not event.items:
            self.menu_box.update("")
            return
        out = Text()
        for i, (name, desc, source) in enumerate(event.items[:6]):
            marker = "▸ " if i == event.index else "  "
            style = "bold" if i == event.index else f"{C.muted}"
            prefix = "/" if event.mode == "slash" else "@"
            out.append(fit(f"{marker}{prefix}{name}", 20), style=style)
            out.append(fit(desc, 30) + " ", style=f"{C.subtle}")
            out.append(f"[{source}]\n", style=f"{C.faint}")
        if len(event.items) > 6:
            out.append(f"  … 외 {len(event.items) - 6}개 (↑↓로 고르기)", style=f"{C.subtle}")
        self.menu_box.update(out)

    def _send_problem(self, view) -> str | None:
        """보내기 전 확인. 문제가 있으면 이유를 돌려준다 (BUILD_PLAN §5.1).

        기록이 낡았을 수 있다. 패널이 셸로 돌아갔으면 글이 셸 명령으로 실행되므로,
        claude가 그 패널에 떠 있을 때만 보낸다.
        """
        if not view.iterm_session_id:
            return "이 세션은 iTerm 패널과 짝이 없어 보낼 수 없습니다."
        try:
            alive = panels.panel_id_of(view.iterm_session_id) in self.panel_checker()
        except Exception:
            return "패널 상태를 확인하지 못해 보내지 않았습니다."
        if not alive:
            return "그 패널에 Claude가 떠 있지 않아 보내지 않았습니다. 패널을 확인하세요."
        return None

    def _flush_outbox(self, views: list) -> None:
        """응답이 도착한 세션의 대기열을 한 건씩 보낸다."""
        now = time.monotonic()
        for view, text in self.outbox.peek_ready(views, now):
            if self._retry_after.get(view.session_id, 0.0) > now:
                continue
            problem = self._send_problem(view)
            if problem:
                self._retry_after[view.session_id] = now + RETRY_SECONDS
                self._say(f"대기열 보류 ({view.title}): {problem}", f"{C.err}")
                continue
            try:
                self.terminal.send_text(panels.panel_id_of(view.iterm_session_id), text)
            except TerminalError as e:
                self._retry_after[view.session_id] = now + RETRY_SECONDS
                self._say(f"대기열 전송 실패 ({view.title}): {e}", f"{C.err}")
                continue
            self.outbox.mark_sent(view.session_id, view.last_ts, now)
            self._last_sent[view.session_id] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            self._say(f"대기열에서 보냈습니다: {text}", f"{C.ok}")

    def on_command_input_submitted(self, event: CommandInput.Submitted) -> None:
        text = event.text.strip()
        if not text:
            return
        view = self.session_list.selected()
        if view is None:
            self._say("먼저 ①에서 세션을 고르세요.", f"{C.warn}")
            return

        action = outbox_rules.decide(view.state)
        if action == outbox_rules.REFUSE:
            self._say(outbox_rules.REFUSE_REASON.get(view.state, "지금은 보낼 수 없습니다."), f"{C.warn}")
            return
        if action == outbox_rules.PERMISSION:
            self._say("허락을 기다리는 중입니다. y 또는 n만 받습니다.", f"{C.info}")
            return
        if action == outbox_rules.QUESTION:
            self._say("질문에 답을 기다리는 중입니다. i로 선택지를 고르거나 패널에서 답하세요.", f"{C.info}")
            return
        problem = self._send_problem(view)
        if problem:
            self._say(problem, f"{C.err}")  # 글은 남겨 둔다
            return
        # 대기열이 남아 있으면 바로 보내지 않고 뒤에 붙여 순서를 지킨다
        if action == outbox_rules.QUEUE or self.outbox.count(view.session_id):
            n = self.outbox.enqueue(view.session_id, text)
            self.input_box.remember(text)
            self.input_box.value = ""
            self._say(f"일하는 중이라 대기열에 넣었습니다 (지금 {n}건). 응답이 오면 보냅니다.", f"{C.warn}")
            return

        try:
            self.terminal.send_text(panels.panel_id_of(view.iterm_session_id), text)
        except TerminalError as e:
            self._say(f"보내지 못했습니다: {e}", f"{C.err}")  # 글은 남겨 둔다
            return
        self.input_box.remember(text)
        self.input_box.value = ""
        self._last_sent[view.session_id] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        self._say("보냈습니다.", f"{C.ok}")

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action == "permit":
            view = self.session_list.selected()
            return view is not None and view.state == "permission"
        return True

    def action_focus_input(self) -> None:
        if self.question_picker.display:
            self.question_picker.focus()
        elif not self.input_box.disabled:
            self.input_box.focus()

    # ---------- ③ 질문 답하기 (요청 39) ----------

    def on_question_picker_changed(self, event: QuestionPicker.Changed) -> None:
        self.conversation.question_answers = self.question_picker.answers
        self.conversation.refresh_content()

    def on_question_picker_leave(self, event: QuestionPicker.Leave) -> None:
        self.session_list.focus()

    def on_question_picker_submit(self, event: QuestionPicker.Submit) -> None:
        self.conversation.question_sent = True
        self.conversation.refresh_content()
        view = self.session_list.selected()
        if view is None or view.state != "question" or view.question_id != self.question_picker.question_id:
            self._say("질문이 이미 바뀌었거나 끝나 보내지 않았습니다.", f"{C.warn}")
            self.question_picker.back_to_choose()
            return
        problem = self._send_problem(view)
        if problem:
            self._say(problem, f"{C.err}")
            self.question_picker.back_to_choose()
            return
        panel = panels.panel_id_of(view.iterm_session_id)
        labels = [o["label"] for o in view.questions[0]["options"]] if view.questions else []
        self._say("패널의 질문 창을 확인하고 보내는 중…", f"{C.info}")
        self.run_worker(lambda: self._type_question_keys(panel, list(event.keys), labels),
                        thread=True, exclusive=True, group="question")

    def _type_question_keys(self, panel: str, keys: list, labels: list) -> None:
        """뒤에서 돈다: 패널 화면에 질문 창이 있는지 보고, 있으면 키를 한 개씩 보낸다."""
        reader = getattr(self.terminal, "screen_text", None)
        if reader is not None:
            try:
                screen = reader(panel)
            except TerminalError as e:
                self.call_from_thread(self._question_failed, f"패널 화면을 읽지 못해 보내지 않았습니다: {e}")
                return
            if config.QUESTION_SCREEN_MARK not in screen or not any(l and l in screen for l in labels):
                self.call_from_thread(self._question_failed,
                                      "패널에 질문 창이 보이지 않아 보내지 않았습니다. 패널에서 이미 답했는지 보세요.")
                return
        try:
            for k in keys:
                self.terminal.send_text(panel, k, enter=False)
                if config.QUESTION_KEY_GAP:
                    time.sleep(config.QUESTION_KEY_GAP)
        except TerminalError as e:
            self.call_from_thread(self._question_failed, f"보내는 중 멈췄습니다: {e}. 패널을 확인하세요.")
            return
        self.call_from_thread(self._say, "답을 보냈습니다 · 키 " + " ".join(key_label(k) for k in keys), f"{C.ok}")

    def _question_failed(self, text: str) -> None:
        self._say(text, f"{C.err}")
        self.conversation.question_sent = False
        self.conversation.refresh_content()
        self.question_picker.back_to_choose()

    def action_permit(self, key: str) -> None:
        view = self.session_list.selected()
        if view is None or view.state != "permission":
            return
        if not config.PERMISSION_KEYS_VERIFIED:
            self._say("허락 키는 실험 확인 뒤에 켭니다 (BUILD_PLAN §6 확인 2). 지금은 패널에서 직접 답하세요.", f"{C.warn}")
            return
        problem = self._send_problem(view)
        if problem:
            self._say(problem, f"{C.err}")
            return
        try:
            self.terminal.send_text(panels.panel_id_of(view.iterm_session_id),
                                    config.PERMISSION_KEYS[key], enter=False)
        except TerminalError as e:
            self._say(f"허락 응답을 보내지 못했습니다: {e}", f"{C.err}")
            return
        self._say(f"허락 응답 {key}을 보냈습니다.", f"{C.ok}")


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True
