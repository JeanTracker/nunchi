"""③ 입력줄 (SCREEN.md §4). Claude Code CLI 입력창의 기본 동작을 따른다.

- Enter: 보낸다. 글 끝이 \\ 이면 줄바꿈으로 바꾼다 (CLI와 같은 방식)
- Ctrl+J: 줄바꿈 (Shift+Enter는 터미널에 따라 Enter와 구분되지 않아 쓰지 않는다)
- ↑ ↓: 첫 줄/마지막 줄에서 보낸 글 기록을 넘긴다. 그 밖에는 커서를 움직인다
- Esc: 글을 지운다 (지운 글은 기록에 남는다)
- 한글 입력·삭제: TextArea가 글자 단위로 처리한다 (삭제는 Backspace, Delete)
- 여러 줄 붙여넣기, 파일 끌어다 놓기: 터미널은 둘 다 붙여넣기로 보내므로 그대로 입력칸에 넣는다
- Ctrl+V: 맥 클립보드를 읽어 넣는다. 끌어 고르고 놓으면 고른 글을 복사한다 (요청 32)
- Tab: 입력칸이 비어 있고 추천 문구가 있으면 채운다. 없으면 다음 구역으로 간다
- /스킬, @파일, !명령, #메모: 글자를 바꾸지 않고 그대로 전달한다 (Claude가 처리)

화면에서 나오는 자동완성 목록(/, @)은 아직 없다. 전달된 글은 Claude가 그대로 해석한다.
"""

from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea


# 추천 문구는 4단계(분석기) 이후에 만든다. 지금은 규칙으로 임의로 만들지 않는다.
SUGGESTIONS: dict = {}


def suggestion_for(state: str) -> str:
    return SUGGESTIONS.get(state, "")


class CommandInput(TextArea):
    BINDINGS = [
        Binding("enter", "submit", "보내기", priority=True, show=False),
        Binding("ctrl+j", "newline", "줄바꿈", priority=True, show=False),
        Binding("ctrl+ㅓ", "newline", "줄바꿈", priority=True, show=False),  # 한글 상태의 Ctrl+J (실제 키 확인)
        Binding("shift+enter", "newline", "줄바꿈", priority=True, show=False),
        Binding("alt+enter", "newline", "줄바꿈", priority=True, show=False),
        Binding("shift+tab", "cycle_mode", "권한 모드 바꾸기", priority=True, show=False),
        Binding("escape", "clear_draft", "지우기", priority=True, show=False),
        Binding("up", "history_prev", "이전 글", priority=True, show=False),
        Binding("down", "history_next", "다음 글", priority=True, show=False),
        Binding("tab", "accept_suggestion", "추천 채우기", priority=True, show=False),
        Binding("pageup", "scroll_conversation(-1)", "대화 위로", priority=True, show=False),
        Binding("pagedown", "scroll_conversation(1)", "대화 아래로", priority=True, show=False),
        Binding("ctrl+ㅍ", "paste", "붙여넣기", show=False),  # 한글 상태의 Ctrl+V
        Binding("ctrl+ㅊ", "copy", "복사", show=False),       # 한글 상태의 Ctrl+C
    ]

    class MenuChanged(Message):
        """/ 목록이 바뀌었다. 앱이 입력칸 위에 그린다."""

        def __init__(self, items: list, index: int, mode: str = "slash") -> None:
            super().__init__()
            self.items = items
            self.index = index
            self.mode = mode  # "slash" 또는 "file"

    class ModeCycleRequested(Message):
        """Shift+Tab: 세션의 권한 모드를 다음 것으로 넘긴다. 실제 전송은 앱이 한다."""

    class ScrollRequested(Message):
        """PgUp/PgDn: 글을 쓰는 중에도 ② 대화를 스크롤한다 (요청 28). 입력 커서는 그대로."""

        def __init__(self, delta: int) -> None:
            super().__init__()
            self.delta = delta

    class Submitted(Message):
        """사용자가 Enter로 보내려 할 때. 실제로 보냈는지는 앱이 정하고, 입력칸은 앱이 비운다."""

        def __init__(self, input_widget: "CommandInput", text: str) -> None:
            super().__init__()
            self.input = input_widget
            self.text = text

        @property
        def value(self) -> str:  # 예전 Input 이벤트와 같은 이름
            return self.text

    def __init__(self, **kwargs):
        self.base_placeholder = kwargs.get("placeholder", "")
        super().__init__(soft_wrap=True, tab_behavior="focus", **kwargs)
        self.sent_history: list = []
        self._browse_index = None  # None이면 기록을 넘기지 않는 중
        self._draft = ""
        self.suggestion = ""       # 입력칸이 비었을 때 Tab으로 채울 추천 문구
        self.commands: list = []   # (이름, 설명, 출처) 전체 목록. 앱이 채운다
        self.menu_items: list = []  # 지금 거른 목록
        self.menu_index = 0
        self.menu_open = False     # Esc로 닫으면 다시 / 를 칠 때까지 닫힌 상태
        self.menu_mode = "slash"   # 지금 목록이 명령 목록인지 파일 목록인지
        self.file_provider = None  # @를 칠 때만 파일 목록을 가져오는 함수 (앱이 정한다)

    def set_base_placeholder(self, text: str) -> None:
        self.base_placeholder = text
        self._show_placeholder()

    def set_suggestion(self, text: str) -> None:
        """추천 문구를 정한다. 입력칸 안내문에 보이고, 비었을 때 Tab으로 채운다."""
        self.suggestion = text
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        if self.suggestion:
            self.placeholder = f"Tab: {self.suggestion}"
        else:
            self.placeholder = self.base_placeholder

    # 예전 Input과 맞춘 이름 (앱과 테스트가 쓴다)
    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, new: str) -> None:
        self.load_text(new)
        self.move_cursor(self.document.end)

    def clear(self) -> None:  # noqa: D401 - TextArea.clear와 같은 이름을 쓴다
        self.load_text("")

    def remember(self, text: str) -> None:
        """보낸 글을 기록에 남기고, 기록 넘기기를 멈춘다."""
        if text and (not self.sent_history or self.sent_history[-1] != text):
            self.sent_history.append(text)
        self._browse_index = None
        self._draft = ""

    # ---------- 동작 ----------

    def action_submit(self) -> None:
        text = self.text
        if text.endswith("\\") and self.cursor_location == self._end_location():
            self.action_delete_left()  # 역슬래시를 지우고 줄바꿈으로 바꾼다
            self.insert("\n")
            return
        if not text.strip():
            return
        self.post_message(self.Submitted(self, text))

    def action_cycle_mode(self) -> None:
        self.post_message(self.ModeCycleRequested())

    def action_scroll_conversation(self, delta: int) -> None:
        self.post_message(self.ScrollRequested(delta))

    def action_newline(self) -> None:
        self.insert("\n")

    def on_text_area_changed(self, event) -> None:
        self._update_menu()

    def _update_menu(self) -> None:
        from control_tui import completion
        token = completion.file_token(self.text)
        if token is not None and self.file_provider is not None:
            self.menu_mode = "file"
            files = self.file_provider()
            items = [(f, "", "파일") for f in completion.match_files(files, token[1:])[:20]]
            self.menu_open = bool(items)
            self._set_menu(items, 0)
            return
        self.menu_mode = "slash"
        prefix = completion.slash_prefix(self.text)
        if prefix is None or "\n" in self.text or not self.commands:
            self._set_menu([], 0)
            return
        self.menu_open = True
        self._set_menu(completion.matches(self.commands, prefix), 0)

    def set_commands(self, items: list) -> None:
        self.commands = items
        self._update_menu()

    def set_file_provider(self, provider) -> None:
        self.file_provider = provider

    def _set_menu(self, items: list, index: int) -> None:
        self.menu_items = items
        self.menu_index = min(index, max(0, len(items) - 1))
        self.post_message(self.MenuChanged(self.menu_items, self.menu_index, self.menu_mode))

    def _complete_selected(self) -> bool:
        """고른 명령이나 파일을 입력칸에 채운다. 뒤에 공백을 붙여 목록을 닫는다."""
        if not self.menu_items:
            return False
        name = self.menu_items[self.menu_index][0]
        if self.menu_mode == "file":
            from control_tui.completion import file_token
            token = file_token(self.text) or ""
            self.load_text(self.text[: len(self.text) - len(token)] + f"@{name} ")
        else:
            self.load_text(f"/{name} ")
        self.move_cursor(self.document.end)
        self._set_menu([], 0)
        return True

    def action_accept_suggestion(self) -> None:
        if self._complete_selected():
            return
        if not self.text and self.suggestion:
            self.load_text(self.suggestion)
            self.move_cursor(self.document.end)
            self.suggestion = ""
            self._show_placeholder()
            return
        self.app.action_focus_next()

    def _on_paste(self, event) -> None:
        """터미널의 붙여넣기와 파일 끌어다 놓기 모두 여기로 온다. 글을 그대로 넣는다."""
        event.stop()
        event.prevent_default()
        if event.text:
            self.insert(event.text)

    def action_paste(self) -> None:
        """Ctrl+V. TextArea 기본은 관제 안 클립보드만 읽는다. 맥 클립보드를 먼저 읽는다."""
        if self.read_only:
            return
        text = self.app.read_clipboard() if hasattr(self.app, "read_clipboard") else self.app.clipboard
        if text and (result := self._replace_via_keyboard(text, *self.selection)):
            self.move_cursor(result.end_location)

    def on_mouse_up(self, event) -> None:
        """입력줄 안에서 끌어 고르고 놓으면 복사한다."""
        if self.selected_text:
            self.app.copy_to_clipboard(self.selected_text)

    def action_clear_draft(self) -> None:
        if self.menu_open:
            self.menu_open = False
            self._set_menu([], 0)
            return
        if self.text:
            self.remember(self.text)
            self.load_text("")

    def action_history_prev(self) -> None:
        if self.menu_items:
            self._set_menu(self.menu_items, self.menu_index - 1 if self.menu_index > 0 else len(self.menu_items) - 1)
            return
        row, _ = self.cursor_location
        if row > 0 or not self.sent_history:
            self.action_cursor_up()
            return
        if self._browse_index is None:
            self._draft = self.text
            self._browse_index = len(self.sent_history)
        if self._browse_index > 0:
            self._browse_index -= 1
            self.load_text(self.sent_history[self._browse_index])
            self.move_cursor(self.document.end)

    def action_history_next(self) -> None:
        if self.menu_items:
            self._set_menu(self.menu_items, (self.menu_index + 1) % len(self.menu_items))
            return
        row, _ = self.cursor_location
        last_row = self.document.line_count - 1
        if self._browse_index is None or row < last_row:
            self.action_cursor_down()
            return
        self._browse_index += 1
        if self._browse_index >= len(self.sent_history):
            self._browse_index = None
            self.load_text(self._draft)
        else:
            self.load_text(self.sent_history[self._browse_index])
        self.move_cursor(self.document.end)

    def _end_location(self):
        last = self.document.line_count - 1
        return (last, len(self.document.get_line(last)))
