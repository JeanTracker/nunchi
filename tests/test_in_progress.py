"""요청 상태 '진행 중' (요구 이력 66): 다른 세션에 맡겼거나 MR 병합 전이면 남은 것에 ◐로 남는다."""
import json

from control_tui import analyzer, flow
from tests.test_flow_chain import out, turn

T1 = turn(1, "취소 버튼 넣어줘", "MR !3016을 만들었습니다. 병합은 하지 않았습니다.")


def answer(state, update=()):
    o = json.loads(out(1, "취소 버튼", "MR !3016", "취소 버튼", 1, "취소 버튼", first_goal="취소 버튼"))
    o["requests_new"] = [{"summary": "취소 버튼", "quote": "취소 버튼 넣어줘", "state": state, "agent_quote": "병합은 하지 않았습니다"}]
    o["requests_update"] = list(update)
    return json.dumps(o, ensure_ascii=False)


def test_in_progress_is_kept_and_counted_as_left():
    f = flow.advance(flow.empty(), [T1], T1, lambda p: answer("in_progress"))
    assert f["requests"][0]["state"] == "in_progress"
    assert [r["id"] for r in flow.remaining(f)] == ["R1"]
    assert analyzer.missed_count({"flow": f}) == 1


def test_later_merge_turns_it_addressed():
    f = flow.advance(flow.empty(), [T1], T1, lambda p: answer("in_progress"))
    t2 = turn(2, "병합됐어?", "MR !3016이 병합됐습니다.")
    o = json.loads(out(2, "병합됐어", "병합됐습니다", "취소 버튼", 1, "취소 버튼"))
    o["requests_update"] = [{"id": "R1", "state": "addressed", "agent_quote": "MR !3016이 병합됐습니다", "superseded_by": 0}]
    f = flow.advance(f, [T1, t2], t2, lambda p: json.dumps(o, ensure_ascii=False))
    assert f["requests"][0]["state"] == "addressed" and flow.remaining(f) == []


def test_prompt_orders_in_progress_first_and_names_it_in_the_answer_shape():
    p = flow.build_prompt(flow.empty(), [T1], T1)
    assert "in_progress(진행 중)" in p and "병합은 하지 않았습니다" in p
    assert '"state": "open|addressed|in_progress|deferred"' in p


async def test_control_shows_in_progress_with_its_mark(tmp_path):
    from tests.test_flow_chain import flow_analysis, recorded
    from tests.test_flow_view import app_for, make_session, ready, text_of
    a = recorded(flow_analysis(shift_turns=(2,)))
    a["flow"]["requests"].append({"id": "R6", "from_turn": 5, "by_turn": 6, "summary": "취소 버튼", "quote": "요청 5번",
                                  "state": "in_progress", "agent_quote": "병합은 하지 않았습니다"})
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "남은 것 3" in text
        assert "◐ 취소 버튼 — 진행 중 “병합은 하지 않았습니다”" in text
        app.conversation.focus()
        await pilot.press("c")
        assert "진행 중 1" in text_of(app)
