"""같은 턴 응답이 뒤에 길어지면 그 턴을 다시 적는다 (요구 이력 64).

다른 세션의 알림처럼 사람이 치지 않은 입력이 오면 에이전트는 같은 턴 안에서 이어 일한다.
처음 분석 때는 '작업을 맡겼다'까지였던 응답이 뒤에 '구현을 마쳤다'로 늘어도, 그 턴을 다시 보지 않으면
요청 기록이 '못 했거나 미룸'에 머문다 (세션 e1aa 넷째 턴, SCREEN §8).
"""
import json

from control_tui import flow
from tests.test_flow_chain import out, turn

REQ1 = "취소 버튼 넣어줘"
T1 = turn(1, REQ1, "다른 세션에서 해야 합니다.")
SHORT = "다른 세션에 작업 요청을 보냈습니다."
LONG = SHORT + "\n\n그 세션이 구현을 마쳤습니다. UserTerms.vue에 취소 버튼을 넣었습니다."


def answer(index, quote, agent_quote, new=(), update=()):
    o = json.loads(out(index, quote, agent_quote, "취소 버튼", 1, "취소 버튼", first_goal="취소 버튼" if index == 1 else ""))
    o["requests_new"] = list(new)
    o["requests_update"] = list(update)
    return json.dumps(o, ensure_ascii=False)


def first_two(resp2):
    t2 = turn(2, "너가 직접 요청해줘", resp2)
    turns = [T1, t2]
    a1 = answer(1, "취소 버튼", "다른 세션에서", new=[{"summary": "취소 버튼", "quote": "취소 버튼 넣어줘",
                                                     "state": "deferred", "agent_quote": "다른 세션에서 해야"}])
    a2 = answer(2, "직접 요청해줘", "작업 요청을 보냈", new=[{"summary": "직접 요청", "quote": "직접 요청해줘",
                                                       "state": "addressed", "agent_quote": "작업 요청을 보냈습니다"}])
    f = flow.advance(flow.empty(), turns, T1, lambda p: a1)
    f = flow.advance(f, turns, t2, lambda p: a2)
    return f


def test_a_turn_whose_answer_grew_is_rewound_and_written_again():
    f = first_two(SHORT)
    assert [r["state"] for r in f["requests"]] == ["deferred", "addressed"]
    t2_long = turn(2, "너가 직접 요청해줘", LONG)
    turns = [T1, t2_long]
    assert flow.grown(f, turns)                          # 응답이 늘었다
    assert not flow.grown(f, [T1, turn(2, "너가 직접 요청해줘", SHORT)])   # 그대로면 아니다

    back = flow.rewind(f)
    assert back["until"] == 1 and [s["index"] for s in back["steps"]] == [1]
    assert [r["id"] for r in back["requests"]] == ["R1"] and back["requests"][0]["state"] == "deferred"

    again = answer(2, "직접 요청해줘", "취소 버튼을 넣었",
                   new=[{"summary": "직접 요청", "quote": "직접 요청해줘", "state": "addressed", "agent_quote": "작업 요청을 보냈습니다"}],
                   update=[{"id": "R1", "state": "addressed", "agent_quote": "취소 버튼을 넣었습니다", "superseded_by": 0}])
    f2 = flow.advance(back, turns, t2_long, lambda p: again)
    assert [s["index"] for s in f2["steps"]] == [1, 2]                     # 단계가 겹치지 않는다
    assert [(r["id"], r["state"]) for r in f2["requests"]] == [("R1", "addressed"), ("R2", "addressed")]   # 요청도 겹치지 않는다
    assert f2["requests"][0]["agent_quote"] == "취소 버튼을 넣었습니다"
    assert not flow.grown(f2, turns)


def test_prev_keeps_only_one_step_back():
    f = first_two(SHORT)
    assert "prev" in f and "prev" not in f["prev"]       # 한 단계 앞만 둔다 (파일이 커지지 않게)


def test_old_flows_without_a_mark_are_left_alone():
    f = first_two(SHORT)
    f["steps"][-1].pop("resp")
    assert not flow.grown(f, [T1, turn(2, "너가 직접 요청해줘", LONG)])
    g = first_two(SHORT)
    g.pop("prev")
    assert not flow.grown(g, [T1, turn(2, "너가 직접 요청해줘", LONG)])


def test_analyzer_writes_the_grown_last_turn_again(tmp_path):
    from control_tui import analyzer
    from tests.test_flow_chain import LEDGER, flow_answer
    from tests.test_flow_view import make_session, write
    home, tr, stop = make_session(tmp_path, n=2)
    d = home / "sessions" / "s1"
    seen = []

    def run(prompt):
        seen.append(int(prompt.split("=== 새 턴 ===\n[턴 ")[1].split("]")[0]))
        return flow_answer(prompt)
    a = analyzer.Analyzer(runner=lambda p: LEDGER, flow_runner=run, reply_wait=0)
    a.request("s1", d, str(tr), stop)
    a.wait_idle(10)
    assert seen == [1, 2]
    rows = [json.loads(x) for x in tr.read_text(encoding="utf-8").splitlines()]
    rows.append({"type": "assistant", "timestamp": "2026-11-09T00:02:50.000Z",   # 같은 턴에서 이어 한 말 (사람 입력 없음)
                 "message": {"content": [{"type": "text", "text": "그 세션이 구현을 마쳤습니다."}]}})
    write(tr, rows)
    later = "2026-11-09T00:03:00.000Z"
    assert a.request("s1", d, str(tr), later)
    a.wait_idle(10)
    assert seen == [1, 2, 2]                               # 둘째 턴만 다시 적는다
    f = json.loads((d / "analysis.json").read_text())["flow"]
    assert [s["index"] for s in f["steps"]] == [1, 2] and f["until"] == 2
    assert not flow.grown(f, analyzer.parse_turns(tr, until_ts=later))
    a.shutdown()


def test_a_shorter_or_same_length_answer_does_not_rewind():
    f = first_two(LONG.replace("그 세션이 구현을 마쳤습니다. ", ""))   # 적을 때가 더 길었다
    assert not flow.grown(f, [T1, turn(2, "너가 직접 요청해줘", SHORT)])   # 짧게 읽혀도 옛 응답으로 덮어쓰지 않는다
    g = first_two(SHORT)
    same = SHORT.replace("보냈습니다", "보냈어요요")                        # 길이만 같고 글이 다르면 그대로
    assert len(same) == len(SHORT)
    assert not flow.grown(g, [T1, turn(2, "너가 직접 요청해줘", same)])


def test_a_failed_rewrite_keeps_the_earlier_good_step(tmp_path):
    """다시 적기가 근거 확인에 두 번 실패하면(대체 단계) 앞서 잘 적은 그 턴을 둔다."""
    from control_tui import analyzer
    from tests.test_flow_chain import LEDGER, flow_answer
    from tests.test_flow_view import make_session, write
    home, tr, stop = make_session(tmp_path, n=2)
    d = home / "sessions" / "s1"
    bad = {"on": False}

    def run(prompt):
        return "엉뚱한 답" if bad["on"] else flow_answer(prompt)
    a = analyzer.Analyzer(runner=lambda p: LEDGER, flow_runner=run, reply_wait=0)
    a.request("s1", d, str(tr), stop)
    a.wait_idle(10)
    good = json.loads((d / "analysis.json").read_text())["flow"]["steps"][-1]
    rows = [json.loads(x) for x in tr.read_text(encoding="utf-8").splitlines()]
    rows.append({"type": "assistant", "timestamp": "2026-11-09T00:02:50.000Z",
                 "message": {"content": [{"type": "text", "text": "그 세션이 구현을 마쳤습니다."}]}})
    write(tr, rows)
    bad["on"] = True
    a.request("s1", d, str(tr), "2026-11-09T00:03:00.000Z")
    a.wait_idle(10)
    f = json.loads((d / "analysis.json").read_text())["flow"]
    assert f["steps"][-1] == good and not f["steps"][-1].get("fallback")
    a.shutdown()
