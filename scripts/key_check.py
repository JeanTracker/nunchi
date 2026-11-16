"""실제 키 확인 화면 (질문 32). 관제와 같은 Textual로, 누른 키를 관제가 받는 이름 그대로 보여 주고 파일에 적는다.

실행: .venv/bin/python scripts/key_check.py [기록 파일]
끝내기: Ctrl+Q
아무것도 보내지 않고, 화면에 보이기와 기록만 한다.
"""

import sys
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static

LOG = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/control-tui-keys.log")

GUIDE = """키 확인 — 아래 순서로 한 번씩 눌러 주세요 (영문 입력 상태)
 1 Enter   2 Shift+Enter   3 Option+Enter   4 Ctrl+J
 5 Fn+↑(PgUp)   6 Fn+↓(PgDn)   7 Fn+←(Home)   8 Fn+→(End)
 9 Shift+Tab   10 Esc
 11 한글로 바꾼 뒤: y   n   q   ㅇ자리(d)
 끝나면 Ctrl+Q
"""


class KeyCheck(App):
    def compose(self) -> ComposeResult:
        yield Static(GUIDE, id="guide")
        yield Static("", id="log")

    def on_mount(self) -> None:
        LOG.write_text("", encoding="utf-8")
        self.rows: list = []

    def on_key(self, event) -> None:
        if event.key == "ctrl+q":
            return
        row = f"{len(self.rows) + 1:>2}  key={event.key!r:<22} char={event.character!r:<8} aliases={event.aliases}"
        self.rows.append(row)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {row}\n")
        self.query_one("#log", Static).update("\n".join(self.rows[-20:]))
        event.stop()
        event.prevent_default()


if __name__ == "__main__":
    KeyCheck().run()
