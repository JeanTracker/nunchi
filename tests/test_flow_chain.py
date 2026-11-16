"""목표 흐름 원문 고정 연쇄 (요청 40, REQUIREMENTS R2, BUILD_PLAN §4.3, SCREEN §2 ② 머리)."""

import json
from pathlib import Path

import pytest

from control_tui import analyzer, flow
from control_tui.transcript import Turn

from tests.test_flow_view import app_for, make_session, ready, text_of


def turn(i, req, resp="", calls=()):
    t = Turn(index=i, time="", request=req, response=resp, final_response=resp)
    t.calls = list(calls)
    return t


T1 = turn(1, "관제 화면의 마지막 응답이 다르게 보이는 원인을 확인해줘", "원인은 옛 코드로 돌던 관제였습니다.")
T2 = turn(2, "목표 흐름 업데이트가 늦는 이유를 그림으로 알려줘", "응답이 끝난 뒤에만 분석하기 때문입니다.")
T3 = turn(3, "한글로", "응답이 끝난 뒤에만 분석합니다.")
TURNS = [T1, T2, T3]


def out(index, quote, agent_quote, goal, goal_turn, goal_quote, shift=False, direction="", how="", shift_quote="",
        label="시작", first_goal=""):
    return json.dumps({"turn": {"index": index, "label": label, "summary": f"요약 {index}", "quote": quote,
                                "agent_summary": f"에이전트 {index}", "agent_quote": agent_quote},
                       "topic_shift": shift, "goal_change": {"direction": direction, "how": how, "quote": shift_quote},
                       "current_goal": goal, "goal_turn": goal_turn, "goal_quote": goal_quote,
                       "first_goal": first_goal}, ensure_ascii=False)


GOOD1 = out(1, "마지막 응답이 다르게 보이는", "옛 코드로 돌던", "마지막 응답 불일치 원인 확인", 1, "원인을 확인해줘",
            first_goal="마지막 응답 불일치 원인 확인")
GOOD2 = out(2, "업데이트가 늦는 이유", "끝난 뒤에만 분석", "목표 흐름 갱신 지연 이유 설명", 2, "업데이트가 늦는 이유",
            shift=True, direction="옮김", how="앞 목표 응답 불일치에서 목표 흐름 지연으로", shift_quote="목표 흐름 업데이트가 늦는",
            label="구체화")
GOOD3 = out(3, "한글로", "끝난 뒤에만", "모델이 바꿔 쓴 목표", 2, "업데이트가 늦는 이유", label="정정")


def runner_of(*answers):
    calls = []

    def run(prompt):
        calls.append(prompt)
        return answers[min(len(calls), len(answers)) - 1]
    return run, calls


def chain(*answers, turns=TURNS):
    run, calls = runner_of(*answers)
    f = flow.empty()
    for t in turns[:len([a for a in answers])]:
        f = flow.advance(f, turns, t, run)
    return f, calls


# ---------- 이어 적기와 원문 대조 ----------

def test_each_turn_is_appended_with_quotes_checked_against_the_source():
    f, calls = chain(GOOD1, GOOD2, GOOD3)
    assert [s["index"] for s in f["steps"]] == [1, 2, 3] and f["until"] == 3
    assert all(s["grounded"] for s in f["steps"])
    assert f["first_goal"] == {"text": "마지막 응답 불일치 원인 확인", "turn": 1, "quote": "원인을 확인해줘"}
    s2 = f["steps"][1]
    assert s2["shift"] and s2["direction"] == "옮김" and s2["goal"] == "목표 흐름 갱신 지연 이유 설명"
    assert s2["prev_goal"] == "마지막 응답 불일치 원인 확인" and s2["shift_quote"] == "목표 흐름 업데이트가 늦는"
    assert len(calls) == 3


def test_when_the_subject_stays_the_goal_text_is_not_rewritten():
    f, _ = chain(GOOD1, GOOD2, GOOD3)
    assert f["current_goal"]["text"] == "목표 흐름 갱신 지연 이유 설명"   # 턴 3의 "모델이 바꿔 쓴 목표"는 쓰지 않는다
    assert f["current_goal"]["turn"] == 2 and not f["steps"][2]["shift"]


def test_earlier_steps_are_copied_and_never_overwritten():
    f, _ = chain(GOOD1, GOOD2)
    snapshot = json.dumps(f["steps"], ensure_ascii=False)
    run, _ = runner_of(GOOD3)
    f3 = flow.advance(f, TURNS, T3, run)
    assert json.dumps(f3["steps"][:2], ensure_ascii=False) == snapshot


def test_quote_not_in_the_source_is_asked_again_then_replaced_by_the_raw_request():
    bad = out(1, "사용자가 하지 않은 말", "옛 코드로 돌던", "지어낸 목표", 1, "원인을 확인해줘", first_goal="지어낸 목표")
    run, calls = runner_of(bad, bad)
    f = flow.advance(flow.empty(), TURNS, T1, run)
    assert len(calls) == 2                           # 한 번 다시 묻는다
    s = f["steps"][0]
    assert not s["grounded"] and s["summary"] == T1.request[:60] and not s["shift"]
    assert f["first_goal"]["text"] == T1.request[:60]   # 지어낸 목표는 남지 않는다
    assert "지어낸" not in json.dumps(f, ensure_ascii=False)


def test_second_try_is_used_when_it_passes():
    bad = out(1, "없는 구절", "옛 코드로 돌던", "목표", 1, "원인을 확인해줘")
    run, calls = runner_of(bad, GOOD1)
    f = flow.advance(flow.empty(), TURNS, T1, run)
    assert len(calls) == 2 and f["steps"][0]["grounded"]


@pytest.mark.parametrize("change", [
    {"direction": "확장", "quote": "목표 흐름 업데이트가 늦는"},     # 정해진 방향이 아님
    {"direction": "옮김", "quote": "사용자가 한 적 없는 말"},       # 방향 근거가 원문에 없음
])
def test_shift_without_a_valid_direction_or_quote_is_not_kept(change):
    bad = json.loads(GOOD2)
    bad["goal_change"].update(change)
    run, _ = runner_of(json.dumps(bad, ensure_ascii=False))
    f, _ = chain(GOOD1)
    f2 = flow.advance(f, TURNS, T2, run)
    s = f2["steps"][1]
    assert not s["grounded"] and not s["shift"]
    assert f2["current_goal"]["text"] == "마지막 응답 불일치 원인 확인"


def test_very_long_new_turn_answer_is_not_cut():
    # 요청 47: 예전 12,000자 상한이면 끝의 결론·질문이 잘렸다
    long = "다" * 20000 + "끝에온질문?"
    t = turn(3, "길게 답해줘", long)
    f, _ = chain(GOOD1, GOOD2)
    p = flow.build_prompt(f, [T1, T2, t], t)
    assert "다" * 20000 + "끝에온질문?" in p
    assert not hasattr(flow, "RESPONSE_CUT")


def test_new_turn_prompt_has_the_whole_answer_and_retrieved_source_but_no_tools():
    from control_tui.transcript import ToolCall
    long = "가" * 5000 + " 중간에 영어 문장 Bars render now " + "나" * 5000
    t = turn(3, "한글로", long, [ToolCall("Edit", "README.md", False)])
    f, _ = chain(GOOD1, GOOD2)
    p = flow.build_prompt(f, [T1, T2, t], t)
    assert "Bars render now" in p
    assert "도구 내역" not in p and "Edit(README.md)" not in p and "tools" not in p   # 도구는 넣지 않는다 (요구 이력 48)
    assert "[턴 1] 요청:" in p and "[턴 2] 요청:" in p        # 처음 목표 턴, 지금 목표 근거 턴·직전 턴
    assert "요약 1" in p and "요약 2" in p                     # 지난 흐름


def test_changed_record_makes_the_flow_start_over():
    f, _ = chain(GOOD1, GOOD2)
    assert flow.valid_for(f, TURNS)
    rewound = [T1, turn(2, "되돌린 뒤 다른 요청", "")]
    assert not flow.valid_for(f, rewound)
    assert not flow.valid_for({"version": 0}, TURNS)


# ---------- 분석기와 이어 붙이기 ----------

LEDGER = json.dumps({"first_goal": "요청 체크 쪽 목표", "current_goal": "요청 체크 쪽 지금", "turns": [],
                     "last_response_summary": "", "ledger": [], "forgotten": []}, ensure_ascii=False)


def session(tmp_path, n=3):
    home, tr, stop = make_session(tmp_path, n=n)
    return home / "sessions" / "s1", tr, stop


def flow_answer(prompt):
    """새 턴 번호를 프롬프트에서 읽어 원문 그대로 인용하는 가짜 기록기."""
    k = int(prompt.split("=== 새 턴 ===\n[턴 ")[1].split("]")[0])
    shift = k == 2
    return out(k, f"요청 {k}번", f"응답 {k}번", f"목표 {k}" if shift or k == 1 else "그대로", 2 if k >= 2 else 1,
               f"요청 {2 if k >= 2 else 1}번", shift=shift, direction="옮김" if shift else "",
               how="앞 목표 1에서 2로" if shift else "", shift_quote="요청 2번" if shift else "",
               first_goal="목표 1" if k == 1 else "")


def test_analyzer_appends_the_flow_without_the_old_request_check(tmp_path):
    d, tr, stop = session(tmp_path)
    seen = []
    a = analyzer.Analyzer(runner=lambda p: seen.append(p) or LEDGER, flow_runner=flow_answer, reply_wait=0)
    assert a.request("s1", d, str(tr), stop)
    a.wait_idle(10)
    data = json.loads((d / "analysis.json").read_text())
    assert data["flow"]["until"] == 3 and len(data["flow"]["steps"]) == 3
    assert data["current_goal"] == "목표 2" and data["first_goal"] == "목표 1"   # 목표 글은 흐름 것을 쓴다
    assert not a.request("s1", d, str(tr), stop)      # 다 이어 적었으면 다시 하지 않는다
    assert len(seen) == 0                             # 요청 기록도 흐름 분석에 들어 있어 옛 요청 체크는 부르지 않는다 (요청 41)
    a.shutdown()


def test_long_backlog_is_written_a_few_turns_per_job_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(analyzer, "FLOW_STEPS_PER_JOB", 2)
    d, tr, stop = session(tmp_path, n=5)
    seen = []
    a = analyzer.Analyzer(runner=lambda p: seen.append(p) or LEDGER, flow_runner=flow_answer, reply_wait=0)
    a.request("s1", d, str(tr), stop)
    a.wait_idle(10)
    assert json.loads((d / "analysis.json").read_text())["flow"]["until"] == 2
    assert a.request("s1", d, str(tr), stop)          # 남은 턴이 있으면 다시 줄 선다
    a.wait_idle(10)
    a.request("s1", d, str(tr), stop)
    a.wait_idle(10)
    data = json.loads((d / "analysis.json").read_text())
    assert data["flow"]["until"] == 5 and [s["index"] for s in data["flow"]["steps"]] == [1, 2, 3, 4, 5]
    assert len(seen) == 0                             # 옛 요청 체크 호출은 없다 (요청 41)
    a.shutdown()


def test_without_a_flow_runner_nothing_changes(tmp_path):
    d, tr, stop = session(tmp_path)
    a = analyzer.Analyzer(runner=lambda p: LEDGER, reply_wait=0)
    a.request("s1", d, str(tr), stop)
    a.wait_idle(10)
    assert "flow" not in json.loads((d / "analysis.json").read_text())
    assert not a.request("s1", d, str(tr), stop)
    a.shutdown()


# ---------- 화면 ----------

def flow_analysis(shift_turns=(2,)):
    steps = []
    for k in range(1, 7):
        s = {"index": k, "label": "구체화", "summary": f"요약 {k}", "quote": f"요청 {k}번", "grounded": True,
             "shift": k in shift_turns, "fp": ""}
        if k in shift_turns:
            s.update(direction="옮김" if k % 2 else "넓힘", how=f"앞 목표에서 목표 {k}로 이어짐",
                     shift_quote=f"요청 {k}번에 있는 아주 긴 근거 구절입니다 끝까지", goal=f"목표 {k}", prev_goal="")
        steps.append(s)
    cur = max(shift_turns) if shift_turns else 1
    return {"first_goal": "목표 1", "current_goal": f"목표 {cur}", "turns": [], "ledger": [], "format": 2,
            "last_turn": 6, "flow": {"version": 1, "first_goal": {"text": "목표 1", "turn": 1, "quote": "요청 1번"},
                                     "current_goal": {"text": f"목표 {cur}", "turn": cur, "quote": f"요청 {cur}번"},
                                     "steps": steps, "until": 6}}


@pytest.mark.asyncio
async def test_screen_shows_shift_steps_with_direction_lines_and_source_quotes(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=flow_analysis(shift_turns=(2, 4)))
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "주제 이동과 결정" in text
        assert "◆ #2 넓힘 목표 2" in text and "◉ 지금 #4–6 넓힘 목표 4" in text   # 목표가 #4부터 #6까지 이어짐 (요청 42)
        assert "└ 앞 목표에서 목표 2로 이어짐 “요청 2번에 있는 아주 긴 근거 구절…”" in text   # 원문 구절은 20자까지
        assert "└ 앞 목표에서 목표 4로 이어짐" in text
        assert "방향이 바뀐 턴만" not in text


@pytest.mark.asyncio
async def test_many_shifts_fold_the_middle_with_a_summary_line(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=flow_analysis(shift_turns=(2, 3, 4, 5, 6)))
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "┊ #2–#3 2단계 · 목표 2 → 목표 3 · g 흐름 전체" in text   # 접힌 단계가 무엇인지 보인다 (요청 41)
        assert "◆ #4" in text and "◆ #5" in text and "◉ 지금 #6" in text
        assert "◆ #2" not in text


@pytest.mark.asyncio
async def test_no_shift_is_one_line(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=flow_analysis(shift_turns=()))
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "◉ #1–6 처음·지금 목표 1" in text and "◆" not in text


@pytest.mark.asyncio
async def test_low_screen_keeps_first_and_current_with_its_direction_line(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=flow_analysis(shift_turns=(2, 4)))
    app = app_for(home)
    async with app.run_test(size=(160, 30)) as pilot:   # ② 칸이 24줄보다 낮은 창
        await ready(app, pilot)
        text = text_of(app)
        assert "● #1 시작 목표 1" in text and "◉ 지금 #4–6 넓힘 목표 4" in text
        assert "└ 앞 목표에서 목표 4로 이어짐" in text      # 지금 목표가 어떻게 이어졌는지는 남는다
        assert "◆" not in text and "목표 2로 이어짐" not in text


def decided(analysis, turns=(3, 5), titles=None):
    for s in analysis["flow"]["steps"]:
        if s["index"] in turns:
            s.update(label="확정", decision=f"정한 것 {s['index']}", quote=f"요청 {s['index']}번")
        if titles and s["index"] in titles:
            s["title"] = titles[s["index"]]
    return analysis


@pytest.mark.asyncio
async def test_decision_turns_show_with_a_check_mark_and_after_the_goal_are_indented(tmp_path):
    a = decided(flow_analysis(shift_turns=(2, 4)), turns=(3, 5))
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "✔ #3 확정 정한 것 3 “요청 3번”" in text            # 지금 목표 앞의 결정
        assert "   ✔ #5 확정 정한 것 5 “요청 5번”" in text        # 지금 목표(#4) 뒤의 결정은 ◉ 아래 들여 씀


@pytest.mark.asyncio
async def test_g_opens_the_whole_flow_and_escape_closes(tmp_path):
    a = decided(flow_analysis(shift_turns=(2, 3, 4, 5, 6)), turns=(), titles={2: "짧은 이름 2"})
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        assert "짧은 이름 2 → 목표 3" in text_of(app)              # 분석이 낸 짧은 이름을 쓴다
        app.conversation.focus()
        await pilot.press("g")
        text = text_of(app)
        assert "목표 흐름 전체" in text and "◆ #2 넓힘 목표 2" in text and "◆ #3 옮김 목표 3" in text
        assert "◉ 지금 #6" in text
        await pilot.press("escape")
        assert "목표 흐름 전체" not in text_of(app)


@pytest.mark.asyncio
async def test_previous_turns_show_the_flow_summary_without_tools_and_enter_opens_the_raw_text(tmp_path):
    a = flow_analysis(shift_turns=(2,))
    for s in a["flow"]["steps"]:
        s["agent_summary"] = f"에이전트 {s['index']}"
    home, tr, _ = make_session(tmp_path, n=6, analysis=a)
    rows = [json.loads(x) for x in tr.read_text().splitlines()]
    rows[3]["message"]["content"].append({"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}})
    tr.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "요약 요약 2 → 에이전트 2" in text                   # 요청 → 에이전트가 한 말·일
        assert "도구 1" not in text                                 # 이전 턴에는 도구 수를 두지 않는다
        app.conversation.focus()
        await pilot.press("up")
        await pilot.press("enter")
        assert "응답 5번 끝" in text_of(app) and "응답까지 한 일" not in text_of(app).split("마지막 대화")[0]


@pytest.mark.asyncio
async def test_while_analyzing_now_moves_to_the_last_turn_with_dots(tmp_path):
    """분석 중 (요청 42): '지금'을 마지막 턴으로 먼저 옮기고, 옛 지금 목표는 일반 단계. 블록 대신 같은 색 점."""
    a = flow_analysis(shift_turns=(2, 4))
    a["flow"]["until"] = 5
    a["flow"]["steps"] = a["flow"]["steps"][:5]
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        conv = app.conversation
        conv.show(conv.view, conv.turns, conv.analysis, status={"state": "running", "seconds": 3, "turn": 6})
        await pilot.pause()
        text = text_of(app)
        assert "◆ #4 넓힘 목표 4" in text                    # 옛 지금 목표는 일반 단계로
        assert "◉ 지금 #6 분석 중." in text                 # 지금은 마지막 턴, '분석 중'과 점으로
        assert "░" not in text and "▒" not in text and "반영 중" not in text
        assert "#6 분석 중." in text.split("요청 체크")[1].split("\n")[0]   # 요청 체크 줄 끝


def test_dots_cycle_and_keep_three_cells(monkeypatch):
    from control_tui.widgets import conversation as cv
    seen = set()
    for sec in (0, 1, 2):
        monkeypatch.setattr(cv.time, "time", lambda s=sec: float(s))
        d = cv.ConversationView._dots() if hasattr(cv, "ConversationView") else None
        if d is None:
            d = [v for v in vars(cv).values() if isinstance(v, type) and hasattr(v, "_dots")][0]._dots()
        assert d.startswith("분석 중") and len(d) == len("분석 중") + 3
        seen.add(d[len("분석 중"):].strip())
    assert seen == {".", "..", "..."}


@pytest.mark.asyncio
async def test_folded_line_breaks_only_between_steps(tmp_path):
    a = decided(flow_analysis(shift_turns=(2, 3, 4, 5, 6)), turns=(),
                titles={2: "Claude Code 확장", 3: "관제와 패널 오가기"})
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(110, 46)) as pilot:
        await ready(app, pilot)
        fold = [ln for ln in text_of(app).splitlines() if ln.lstrip().startswith("┊")]
        assert fold and all("Claude Code 확장" in ln or "Claude" not in ln for ln in fold)   # 이름 중간에서 끊지 않는다
        assert fold[-1].rstrip().endswith("g 흐름 전체")



# ---------- 요청 기록 (기억 관점, 요청 41) ----------

from control_tui.transcript import ToolCall  # noqa: E402

R_TURN1 = turn(1, "README에 설치 방법 절을 추가하고, 영어는 쓰지 마", "README에 설치 방법 절을 추가했습니다. 영어 문장은 없습니다.",
               [ToolCall("Edit", "README.md", False)])
R_TURN2 = turn(2, "설치 절은 빼고 CHANGELOG만 만들어줘", "CHANGELOG.md를 만들었습니다. 테스트는 아직 못 돌렸습니다.",
               [ToolCall("Write", "CHANGELOG.md", True)])


def rec_out(index, new=(), updates=(), **kw):
    d = json.loads(out(index, R_TURN1.request[:10] if index == 1 else "CHANGELOG만 만들어줘",
                       "설치 방법 절을 추가했습니다" if index == 1 else "CHANGELOG.md를 만들었습니다",
                       "목표", 1, "README에 설치", first_goal="목표" if index == 1 else "", label="시작" if index == 1 else "재정의"))
    d.update(requests_new=list(new), requests_update=list(updates), digest=f"흐름 {index}")
    d.update(kw)
    return json.dumps(d, ensure_ascii=False)


def test_requests_are_facts_with_source_quotes_and_ignore_tools():
    r = rec_out(1, new=[
        {"summary": "README 설치 절 추가", "quote": "README에 설치 방법 절을 추가하고", "state": "addressed",
         "agent_quote": "설치 방법 절을 추가했습니다", "tools": ["Edit"]},
        {"summary": "영어 쓰지 않기", "quote": "영어는 쓰지 마", "state": "addressed", "agent_quote": "영어 문장은 없습니다", "tools": []},
        {"summary": "지어낸 요청", "quote": "사용자가 하지 않은 말", "state": "open"},
    ])
    f = flow.advance(flow.empty(), [R_TURN1], R_TURN1, lambda p: r)
    reqs = f["requests"]
    assert [x["id"] for x in reqs] == ["R1", "R2"]                  # 원문에 없는 요청은 버린다
    assert reqs[0]["state"] == "addressed"                          # 에이전트의 말로만 정한다
    assert all("tool_failed" not in x for x in reqs)                # 도구 실패는 기록하지 않는다 (요구 이력 48)
    assert f["steps"][0]["digest"] == "흐름 1"
    assert flow.remaining(f) == []


def test_later_turn_updates_state_supersedes_and_keeps_ids():
    r1 = rec_out(1, new=[{"summary": "README 설치 절 추가", "quote": "README에 설치 방법 절을 추가하고", "state": "open"}])
    f = flow.advance(flow.empty(), [R_TURN1, R_TURN2], R_TURN1, lambda p: r1)
    r2 = rec_out(2, new=[{"summary": "CHANGELOG 만들기", "quote": "CHANGELOG만 만들어줘", "state": "addressed",
                          "agent_quote": "CHANGELOG.md를 만들었습니다", "tools": ["Write"]},
                         {"summary": "테스트", "quote": "CHANGELOG만", "state": "deferred", "agent_quote": "테스트는 아직 못 돌렸습니다"}],
                 updates=[{"id": "R1", "state": "superseded"}, {"id": "R9", "state": "open"}])
    f2 = flow.advance(f, [R_TURN1, R_TURN2], R_TURN2, lambda p: r2)
    by = {x["id"]: x for x in f2["requests"]}
    assert by["R1"]["state"] == "superseded" and by["R1"]["superseded_by"] == 2 and by["R1"]["summary"] == "README 설치 절 추가"
    assert by["R2"]["state"] == "addressed" and "tool_failed" not in by["R2"]
    assert by["R3"]["state"] == "deferred"
    assert "R9" not in by                                            # 없는 번호는 버린다
    assert [x["id"] for x in flow.remaining(f2)] == ["R3"]
    assert analyzer.missed_count({"flow": f2}) == 1
    p = flow.build_prompt(f2, [R_TURN1, R_TURN2], R_TURN2)
    assert '"id": "R2"' in p and '"id": "R1"' not in p.split("=== 지난 요청 기록 ===")[1].split("===")[0]   # 대신한 것은 빼고 넣는다



def recorded(analysis):
    analysis["flow"]["requests"] = [
        {"id": "R1", "from_turn": 2, "summary": "설치 절 추가", "quote": "요청 2번", "state": "addressed", "tool_failed": True, "agent_quote": "추가했습니다"},
        {"id": "R2", "from_turn": 3, "summary": "CHANGELOG 만들기", "quote": "요청 3번", "state": "open", "tool_failed": False, "agent_quote": ""},
        {"id": "R3", "from_turn": 4, "summary": "테스트 돌리기", "quote": "요청 4번", "state": "deferred", "tool_failed": False, "agent_quote": "아직 못 돌렸습니다"},
        {"id": "R4", "from_turn": 4, "summary": "옛 요청", "quote": "요청 4번", "state": "superseded", "superseded_by": 5},
        {"id": "R5", "from_turn": 5, "summary": "한글로", "quote": "요청 5번", "state": "addressed", "tool_failed": False, "agent_quote": "한글로 씁니다"},
    ]
    analysis["flow"]["version"] = 2
    return analysis


@pytest.mark.asyncio
async def test_request_record_shows_remaining_facts_not_scores(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=recorded(flow_analysis(shift_turns=(2,))))
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "요청 기록  누적 4개 · #6 기준  남은 것 2" in text
        assert "○ CHANGELOG 만들기 “요청 3번”" in text
        assert "⊘ 테스트 돌리기 — 에이전트: 못 했거나 미룸 “아직 못 돌렸습니다”" in text
        assert "△" not in text and "도구 실패" not in text      # 옛 기록의 tool_failed도 보이지 않는다 (요구 이력 48)
        assert "빠짐" not in text.split("──")[0] and "챙김" not in text
        assert app.session_list.selected() is not None
        app.conversation.focus()
        await pilot.press("c")
        text = text_of(app)
        for title in ("아직 다루지 않음 1", "못 했거나 미룸 1", "다룸 2", "뒤 요청이 대신함 1"):
            assert title in text
        assert "도구 실패" not in text
        assert "한글로 — 에이전트: “한글로 씁니다”" in text


def test_analysis_state_is_written_for_the_mod(tmp_path):
    d, tr, stop = session(tmp_path)
    seen_states = []

    def runner(p):
        seen_states.append(json.loads((d / analyzer.STATUS_FILE).read_text())["state"])
        return flow_answer(p)
    a = analyzer.Analyzer(runner=lambda p: LEDGER, flow_runner=runner, reply_wait=0)
    a.request("s1", d, str(tr), stop)
    a.wait_idle(10)
    assert set(seen_states) == {"running"}
    assert json.loads((d / analyzer.STATUS_FILE).read_text())["state"] == "idle"
    a.shutdown()


def test_version_1_flow_is_moved_without_calls_and_requests_start_after_it():
    f, _ = chain(GOOD1, GOOD2)
    old = dict(f, version=1)
    old.pop("requests", None)
    moved = flow.migrate(old, TURNS)
    assert moved["version"] == flow.VERSION and moved["requests"] == [] and moved["requests_from"] == 3
    assert moved["steps"] == f["steps"] and flow.valid_for(moved, TURNS)
    rewound = [T1, turn(2, "되돌린 뒤 다른 요청", "")]
    assert flow.migrate(old, rewound)["version"] == 1          # 기록이 바뀌었으면 옮겨 담지 않는다 (처음부터)


def test_analyzer_moves_an_old_flow_instead_of_rebuilding(tmp_path):
    d, tr, stop = session(tmp_path, n=3)
    calls = []

    def runner(p):
        calls.append(p)
        return flow_answer(p)
    a = analyzer.Analyzer(runner=lambda p: LEDGER, flow_runner=runner, reply_wait=0)
    a.request("s1", d, str(tr), stop)
    a.wait_idle(10)
    data = json.loads((d / "analysis.json").read_text())
    data["flow"]["version"] = 1
    data["flow"].pop("requests")
    data["flow"]["steps"] = data["flow"]["steps"][:2]
    data["flow"]["until"] = 2
    data["source_ts"] = "old"
    (d / "analysis.json").write_text(json.dumps(data, ensure_ascii=False))
    calls.clear()
    a.request("s1", d, str(tr), stop)
    a.wait_idle(10)
    data = json.loads((d / "analysis.json").read_text())
    assert len(calls) == 1 and data["flow"]["until"] == 3          # 턴 3만 새로 분석
    assert data["flow"]["requests_from"] == 3
    a.shutdown()


@pytest.mark.asyncio
async def test_moved_flow_says_older_requests_are_not_recorded(tmp_path):
    a = recorded(flow_analysis(shift_turns=(2,)))
    a["flow"]["requests_from"] = 4
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(180, 46)) as pilot:
        await ready(app, pilot)
        assert "#3 이전 요청은 기록 전" in text_of(app)


# ---------- 에이전트가 묻는 것 (요구 이력 45) ----------

A_TURN1 = turn(1, "로그 화면을 만들어줘", "로그 화면을 만들었습니다. 색은 파랑과 주황 중 어느 쪽으로 할까요? 폭은 몇 칸으로 할지 알려 주세요.")
A_TURN2 = turn(2, "색은 주황으로 해", "주황으로 바꿨습니다. 폭은 몇 칸으로 할지 알려 주세요.")
A_TURN3 = turn(3, "권장대로 진행", "40칸으로 했습니다.")
A_TURNS = [A_TURN1, A_TURN2, A_TURN3]


def ask_out(index, quote, agent_quote, **kw):
    d = json.loads(out(index, quote, agent_quote, "로그 화면", 1, "로그 화면을 만들어줘",
                       first_goal="로그 화면" if index == 1 else "", label="시작" if index == 1 else "구체화"))
    d.update(kw)
    return json.dumps(d, ensure_ascii=False)


def test_agent_asks_are_recorded_reasked_and_closed_by_answers():
    o1 = ask_out(1, "로그 화면을 만들어줘", "로그 화면을 만들었습니다", asks_new=[
        {"summary": "색 고르기", "quote": "색은 파랑과 주황 중 어느 쪽으로 할까요?", "kind": "결정"},
        {"summary": "폭 정하기", "quote": "폭은 몇 칸으로 할지 알려 주세요", "kind": "정보"},
        {"summary": "지어낸 물음", "quote": "응답에 없는 말", "kind": "결정"}])
    f = flow.advance(flow.empty(), A_TURNS, A_TURN1, lambda p: o1)
    assert [a["id"] for a in f["asks"]] == ["Q1", "Q2"] and all(a["state"] == "open" for a in f["asks"])
    o2 = ask_out(2, "색은 주황으로 해", "주황으로 바꿨습니다", asks_reask=["Q2"],
                 asks_update=[{"id": "Q1", "state": "answered", "quote": "색은 주황으로 해"}, {"id": "Q9", "state": "answered", "quote": "색은"}])
    f2 = flow.advance(f, A_TURNS, A_TURN2, lambda p: o2)
    by = {a["id"]: a for a in f2["asks"]}
    assert by["Q1"]["state"] == "answered" and by["Q1"]["answered_at"] == 2
    assert by["Q2"]["state"] == "open" and by["Q2"]["last_turn"] == 2       # 다시 물은 것은 그 턴으로 옮긴다
    assert [a["id"] for a in flow.open_asks(f2)] == ["Q2"]
    p = flow.build_prompt(f2, A_TURNS, A_TURN3)
    assert '"id": "Q2"' in p.split("=== 지난 묻는 것")[1] and '"id": "Q1"' not in p.split("=== 지난 묻는 것")[1].split("===")[1]
    o3 = ask_out(3, "권장대로 진행", "40칸으로 했습니다", asks_update=[{"id": "Q2", "state": "answered", "quote": "권장대로 진행", "blanket": True}])
    f3 = flow.advance(f2, A_TURNS, A_TURN3, lambda p: o3)
    q2 = {a["id"]: a for a in f3["asks"]}["Q2"]
    assert q2["state"] == "answered" and q2["by_blanket"] is True              # 통째 승인으로 닫힌 것은 따로 표시
    assert flow.open_asks(f3) == []


def test_version_2_flow_is_moved_with_asks_starting_after_it():
    f, _ = chain(GOOD1, GOOD2)
    old = dict(f, version=2)
    old.pop("asks", None)
    moved = flow.migrate(old, TURNS)
    assert moved["version"] == flow.VERSION and moved["asks"] == [] and moved["asks_from"] == 3
    assert "requests_from" not in moved                                     # 요청 기록은 버전 2에 이미 있다


def test_old_tool_failure_marks_are_dropped_when_a_request_is_updated():
    """요구 이력 48: 도구 사용은 보지 않는다. 옛 기록에 남은 tool_failed는 상태가 바뀔 때 버린다."""
    t = turn(5, "다시 해줘", "고쳤습니다")
    old = [{"id": "R1", "from_turn": 1, "summary": "설치 절", "quote": "설치", "state": "addressed", "tool_failed": True}]
    out = flow.apply_requests(old, {"updates": [{"id": "R1", "state": "addressed", "agent_quote": "고쳤습니다", "superseded_by": 0}], "new": []}, t)
    assert "tool_failed" not in out[0] and not hasattr(flow, "_tool_failed")