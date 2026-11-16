"""요청 39: 선택지 질문 창(AskUserQuestion) 대기를 허락과 나누고, ③에서 골라 패널로 보낸다 (SCREEN §2 ③ 질문 답하기, §8)."""

import json

import pytest

from control_tui import config, store
from control_tui.transcript import pending_questions
from control_tui.widgets.question_picker import question_keys
from tests.test_flow_view import app_for, make_session, ready, text_of, write

LONG = "설명이 긴 선택지입니다. " * 20   # 훅 기록(500자에서 자름)으로는 다 못 읽는 길이
QUESTIONS = [
    {"question": "결제 화면 문구를 어디까지 바꿀까요?", "header": "문구 범위", "multiSelect": False,
     "options": [{"label": "버튼만", "description": LONG}, {"label": "버튼과 안내문", "description": "b"},
                 {"label": "화면 전체", "description": "c"}]},
    {"question": "어느 화면 크기에서 확인할까요?", "header": "확인 화면", "multiSelect": True,
     "options": [{"label": "모바일", "description": "360px"}, {"label": "태블릿", "description": "768px"},
                 {"label": "PC", "description": "1280px"}]},
]


class FakeTerminal:
    def __init__(self, screen="질문 창 … 버튼만 … Enter to select · Esc to cancel"):
        self.sent, self.screen = [], screen

    def send_text(self, target_id, text, enter=True):
        self.sent.append((text, enter))

    def screen_text(self, target_id):
        return self.screen


def asking(tmp_path, tool="AskUserQuestion", answered=False):
    """마지막 턴에서 질문 창을 띄우고 허락 알림까지 온 세션."""
    home, tr, _ = make_session(tmp_path, n=2)
    rows = [json.loads(l) for l in tr.read_text(encoding="utf-8").splitlines()]
    rows[3] = {"type": "assistant", "timestamp": "2026-11-09T00:02:30.000Z",
               "message": {"content": [{"type": "text", "text": "범위를 정하려고 두 가지를 묻겠습니다."},
                                        {"type": "tool_use", "id": "toolu_q1", "name": tool,
                                         "input": {"questions": QUESTIONS} if tool == "AskUserQuestion" else {"command": "ls"}}]}}
    if answered:
        rows.append({"type": "user", "timestamp": "2026-11-09T00:02:50.000Z",
                     "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_q1", "content": "answered"}]}})
    write(tr, rows)
    base = {"session_id": "s1", "cwd": "/work/pay-web", "transcript_path": str(tr), "iterm_session_id": "w0t0p0:PANEL-1"}
    events = [dict(base, ts="2026-11-09T00:01:40.000Z", event="Stop", data={}),
              dict(base, ts="2026-11-09T00:02:00.000Z", event="UserPromptSubmit", data={}),
              dict(base, ts="2026-11-09T00:02:30.000Z", event="PreToolUse", data={"tool_name": tool, "tool_use_id": "toolu_q1"}),
              dict(base, ts="2026-11-09T00:02:36.000Z", event="Notification", data={"notification_type": "permission_prompt"})]
    write(home / "sessions" / "s1" / "events.jsonl", events)
    return home, tr, events


# ---------- 상태 ----------

def test_question_window_is_question_not_permission_and_reads_full_questions(tmp_path):
    home, tr, _ = asking(tmp_path)
    [v] = store.load_sessions(home)
    assert v.state == "question" and v.question_id == "toolu_q1"
    assert v.questions[0]["options"][0]["description"] == LONG     # 잘리지 않은 전체
    assert [q["multiSelect"] for q in v.questions] == [False, True]


def test_permission_for_other_tools_stays_permission(tmp_path):
    home, _, _ = asking(tmp_path, tool="Bash")
    [v] = store.load_sessions(home)
    assert v.state == "permission" and v.questions == []


def test_answered_question_goes_back_to_working(tmp_path):
    _, tr, events = asking(tmp_path)
    events = events + [dict(events[-1], ts="2026-11-09T00:02:50.000Z", event="PostToolUse",
                            data={"tool_name": "AskUserQuestion", "tool_use_id": "toolu_q1"})]
    v = store.summarize("s1", events)
    assert v.state == "working" and v.question_id == ""


def test_pending_questions_is_empty_once_answered(tmp_path):
    _, tr, _ = asking(tmp_path, answered=True)
    assert pending_questions(tr, "toolu_q1") == []
    assert pending_questions(tmp_path / "없음.jsonl") == []


# ---------- 패널에 보낼 키 (2026-11-10 실험) ----------

def test_keys_follow_the_experiment():
    single, multi = QUESTIONS
    assert question_keys([single, multi], {0: [1], 1: [0, 2]}) == ["2", "1", "3", "\t", "1"]
    assert question_keys([single], {0: [2]}) == ["3"]                     # 하나뿐이면 바로 제출
    assert question_keys([multi], {0: [2, 0]}) == ["1", "3", "\t", "1"]   # 여러 개 고르기 하나: 확인 단계 있음
    assert question_keys([multi, single], {0: [1], 1: [0]}) == ["2", "\t", "1", "1"]


# ---------- 화면과 보내기 ----------

@pytest.mark.asyncio
async def test_screen_shows_question_and_y_does_not_answer(tmp_path):
    home, _, _ = asking(tmp_path)
    term = FakeTerminal()
    app = app_for(home, terminal=term)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        assert "? 질문" in str(app.session_list.render_line(0).text) or app.session_list.selected().state == "question"
        bar = str(app.keybar.render())
        assert "i 질문 답하기" in bar and "y 허용" not in bar
        text = text_of(app)
        assert "질문 2개에 답을 기다립니다" in text and "Q1 문구 범위" in text and "아직 고르지 않음" in text
        assert "y 허용" not in text
        await pilot.press("y", "n")
        assert term.sent == []                                   # y/n이 질문에 답해 버리지 않는다
        assert app.question_picker.display and not app.input_box.display


@pytest.mark.asyncio
async def test_pick_in_input_zone_then_send_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "QUESTION_KEY_GAP", 0)
    home, _, _ = asking(tmp_path)
    term = FakeTerminal()
    app = app_for(home, terminal=term)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        await pilot.press("i")
        assert app.focused is app.question_picker
        assert str(app.keybar.render()).startswith(" ③ 질문 답하기 ")
        await pilot.press("2")                                   # Q1 → 버튼과 안내문, Q2로
        assert "→ 버튼과 안내문" in text_of(app)
        await pilot.press("1", "3", "enter")                     # Q2 → 모바일, PC, 확인 단계
        picker = str(app.question_picker.render())
        assert "보낼 답" in picker and "2 · 1 · 3 · Tab · 1" in picker
        assert term.sent == []                                   # 확인 전에는 보내지 않는다
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert term.sent == [("2", False), ("1", False), ("3", False), ("\t", False), ("1", False)]
        assert "답을 보냈습니다" in str(app.info_line.render())


@pytest.mark.asyncio
async def test_nothing_is_sent_when_the_panel_has_no_question_window(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "QUESTION_KEY_GAP", 0)
    home, _, _ = asking(tmp_path)
    term = FakeTerminal(screen="❯ \n  ⏵⏵ auto mode on")              # 사용자가 패널에서 이미 답함
    app = app_for(home, terminal=term)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        await pilot.press("i", "1", "1", "enter", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert term.sent == []
        assert "질문 창이 보이지 않아" in str(app.info_line.render())
        assert app.question_picker.review and not app.question_picker.sent


@pytest.mark.asyncio
async def test_multi_needs_one_choice_and_free_text_is_left_to_the_panel(tmp_path):
    home, _, _ = asking(tmp_path)
    app = app_for(home, terminal=FakeTerminal())
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        await pilot.press("i", "4")                              # 직접 쓰기
        assert "패널에서 답하세요" in str(app.question_picker.render())
        await pilot.press("1", "enter")                          # Q2에서 아무것도 안 고르고 Enter
        assert "하나 이상 고르세요" in str(app.question_picker.render())
        assert not app.question_picker.review
        await pilot.press("escape")
        assert app.focused is app.session_list
