"""③ 질문 답하기 (요청 39, SCREEN §2 ③ 질문 답하기, BUILD_PLAN §5.1).

세션이 선택지 질문 창(AskUserQuestion)을 띄우고 기다릴 때 입력칸 대신 나온다.
여기서 답을 모두 고르고 확인한 뒤, 패널의 질문 창에 칠 키를 한 번에 보낸다.
고를 때마다 패널에 보내지 않는 것은, 패널 창이 숫자 하나에 다음 질문으로 넘어가거나 바로 제출되어
관제와 패널이 서로 다른 질문을 보게 될 수 있기 때문이다.
"""

from rich.cells import cell_len
from rich.text import Text
from textual.message import Message
from textual.widgets import Static

from control_tui.theme import C

TAB = "\t"


def question_keys(questions: list, answers: dict) -> list:
    """패널 질문 창에 칠 키 (2026-11-10 실험, SCREEN §8).

    질문마다 고른 번호들, 여러 개 고르기 질문 뒤에는 Tab, 끝에 '답 확인'의 1(제출).
    하나 고르기 질문 하나뿐이면 확인 단계가 없어 번호 하나로 바로 제출된다.
    """
    keys = []
    for n, q in enumerate(questions):
        keys += [str(k + 1) for k in sorted(answers.get(n, []))]
        if q.get("multiSelect"):
            keys.append(TAB)
    if len(questions) > 1 or any(q.get("multiSelect") for q in questions):
        keys.append("1")
    return keys


def key_label(key: str) -> str:
    return "Tab" if key == TAB else key


class QuestionPicker(Static, can_focus=True):
    """질문 탭 · 선택지 · 보낼 답 확인. 보내기는 앱이 한다 (Submit 메시지)."""

    class Changed(Message):
        """고른 답이 바뀜. ②가 '고른 답'을 다시 그린다."""

    class Submit(Message):
        def __init__(self, keys: list) -> None:
            super().__init__()
            self.keys = keys

    class Leave(Message):
        """Esc: ③을 떠난다."""

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self.question_id = ""
        self.questions: list = []
        self.answers: dict = {}   # 질문 번호 -> 고른 선택지 번호 목록 (0부터)
        self.q = 0                # 지금 질문
        self.cursor = 0
        self.review = False       # 보낼 답 확인 단계
        self.sent = False         # 보냈음 (세션이 이어서 일하기를 기다림)
        self.note = ""            # 한 줄 알림 (고르지 않고 넘어가려 할 때 등)

    # ---------- 바깥에서 부르는 것 ----------

    def load(self, question_id: str, questions: list) -> None:
        """다른 질문이면 처음부터. 같은 질문이면 고르던 답을 그대로 둔다."""
        if question_id == self.question_id and questions == self.questions:
            return
        self.question_id, self.questions = question_id, questions
        self.answers, self.q, self.cursor, self.review, self.sent, self.note = {}, 0, 0, False, False, ""
        self.paint()

    def back_to_choose(self) -> None:
        """보내지 못했을 때 확인 단계에 머문다 (다시 Enter로 보낼 수 있게)."""
        self.sent = False
        self.paint()

    def keys(self) -> list:
        return question_keys(self.questions, self.answers)

    def keybar(self) -> list:
        if not self.questions or self.sent:
            return [("Esc", "나가기"), ("q", "종료")]
        if self.review:
            return [("Enter", "패널로 보내기"), ("Esc", "다시 고르기"), ("q", "종료")]
        keys = [(f"1~{len(self.questions[self.q]['options'])}", "고르기"), ("↑↓", "옮기기")]
        if self.questions[self.q].get("multiSelect"):
            keys.append(("Space", "켜기·끄기"))
        keys += [("Enter", "고르기·다음"), ("Tab", "다음 질문"), ("Esc", "나가기"), ("q", "종료")]
        return keys

    # ---------- 그리기 ----------

    def paint(self) -> None:
        self.update(self._content())

    def _content(self) -> Text:
        out = Text()
        if not self.questions:
            out.append("  질문 내용을 읽지 못했습니다 · 패널에서 직접 답하세요", style=f"{C.warn}")
            return out
        tabs = Text("  ")
        for n, q in enumerate(self.questions):
            done = n in self.answers
            here = n == self.q and not self.review
            style = f"bold {C.bg} on {C.p3}" if here else (C.ok if done else C.muted)
            tabs.append(f" {'☒' if done else '☐'} {q.get('header') or f'Q{n + 1}'} ", style=style)
            tabs.append(" ")
        ready = self._all_answered()
        tabs.append(" ✔ 보내기 ", style=(f"bold {C.bg} on {C.p3}" if self.review else (C.ok if ready else C.faint)))
        out.append_text(tabs)
        out.append("\n")
        if self.sent:
            out.append("  보냈습니다 · 세션이 이어서 일하기를 기다립니다", style=f"bold {C.ok}")
            return out
        if self.review:
            out.append("  보낼 답\n", style="bold")
            width = max(cell_len(q.get("header") or f"Q{n + 1}") for n, q in enumerate(self.questions))
            for n, q in enumerate(self.questions):
                head = q.get("header") or f"Q{n + 1}"
                out.append(f"    {head}{' ' * (width - cell_len(head))}  ", style=C.muted)
                out.append("→ " + ", ".join(q["options"][k]["label"] for k in sorted(self.answers.get(n, []))) + "\n")
            out.append("  패널에 보낼 키  " + " · ".join(key_label(k) for k in self.keys()), style=C.subtle)
            out.append("   보내기 전에 패널에 질문 창이 떠 있는지 확인합니다", style=C.faint)
            return out
        q = self.questions[self.q]
        multi = q.get("multiSelect")
        out.append(f"  Q{self.q + 1}/{len(self.questions)} ", style=f"bold {C.p3}")
        out.append(q["question"], style="bold")
        out.append("   " + ("여러 개 고르기" if multi else "하나 고르기"), style=C.subtle)
        out.append("\n")
        chosen = self.answers.get(self.q, [])
        width = max(cell_len(o["label"]) for o in q["options"])
        for k, o in enumerate(q["options"]):
            here = k == self.cursor
            box = ("[✔] " if k in chosen else "[ ] ") if multi else ""
            line = Text()
            line.append("  ❯ " if here else "    ", style=f"bold {C.p3}")
            label = f"{k + 1}. {box}{o['label']}"
            line.append(label + " " * (width - cell_len(o["label"])), style=(f"bold {C.p3}" if here else ""))
            line.append("   " + " ".join(o.get("description", "").split()), style=C.subtle)
            line.truncate(self._width(), overflow="ellipsis")   # 설명은 한 줄로 (전문은 패널에)
            out.append_text(line)
            out.append("\n")
        out.append(f"    {len(q['options']) + 1}. 직접 쓰기 — 지금은 패널에서", style=C.faint)
        if self.note:
            out.append(f"\n  {self.note}", style=C.warn)
        return out

    def _width(self) -> int:
        return max(20, self.size.width or 120)

    # ---------- 고르기 ----------

    def _all_answered(self) -> bool:
        return bool(self.questions) and all(self.answers.get(n) for n in range(len(self.questions)))

    def _next(self) -> None:
        """다음 질문으로. 마지막이면 보낼 답 확인 (모두 골랐을 때만)."""
        if self.q + 1 < len(self.questions):
            self.q, self.cursor = self.q + 1, 0
        elif self._all_answered():
            self.review = True
        else:
            self.q = next(n for n in range(len(self.questions)) if not self.answers.get(n))
            self.cursor = 0
            self.note = "고르지 않은 질문이 있습니다"

    def _pick(self, k: int) -> None:
        q = self.questions[self.q]
        self.cursor = k
        if q.get("multiSelect"):
            chosen = self.answers.setdefault(self.q, [])
            chosen.remove(k) if k in chosen else chosen.append(k)
            if not chosen:
                del self.answers[self.q]
        else:
            self.answers[self.q] = [k]
            self._next()
        self.post_message(self.Changed())

    def on_key(self, event) -> None:
        if not self.questions or self.sent:
            if event.key == "escape":
                self.post_message(self.Leave())
                event.stop()
            return
        key = event.key
        handled = True
        self.note = ""
        if self.review:
            if key == "enter":
                self.sent = True
                self.post_message(self.Submit(self.keys()))
            elif key in ("escape", "left", "shift+tab"):
                self.review = False
            else:
                handled = False
        else:
            q = self.questions[self.q]
            count = len(q["options"])
            if key.isdigit() and 1 <= int(key) <= count:
                self._pick(int(key) - 1)
            elif key.isdigit() and int(key) == count + 1:
                self.note = "직접 쓰기는 패널에서 답하세요 (관제에서는 아직 보내지 않습니다)"
            elif key == "down":
                self.cursor = min(self.cursor + 1, count - 1)
            elif key == "up":
                self.cursor = max(self.cursor - 1, 0)
            elif key == "space" and q.get("multiSelect"):
                self._pick(self.cursor)
            elif key == "enter":
                if q.get("multiSelect"):
                    if self.answers.get(self.q):
                        self._next()
                    else:
                        self.note = "하나 이상 고르세요"
                else:
                    self._pick(self.cursor)
            elif key in ("tab", "right"):
                self._next()
            elif key in ("shift+tab", "left"):
                self.q, self.cursor = max(self.q - 1, 0), 0
            elif key == "escape":
                self.post_message(self.Leave())
            else:
                handled = False
        if handled:
            event.stop()
            event.prevent_default()
            self.paint()
            self.app.refresh_keybar()
