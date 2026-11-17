"""요청 33·34: ② 목표 흐름 세로 단계, 요청 체크(누적 요청 × 마지막 응답), c 전체 보기, 턴 사이 간격,
슬래시 명령 뒤 요청을 턴으로 (REQUIREMENTS R2·R8·R9, SCREEN §2 ②)."""

import json

import pytest

from control_tui import transcript
from tests.test_flow_view import ANALYSIS, app_for, make_session, ready, text_of


def write(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def user(text, ts, **extra):
    return dict({"type": "user", "timestamp": ts, "origin": {"kind": "human"},
                 "message": {"role": "user", "content": text}}, **extra)


def meta(text, ts):
    return {"type": "user", "timestamp": ts, "isMeta": True, "message": {"role": "user", "content": text}}


def answer(text, ts):
    return {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "text", "text": text}]}}


# ---------- 슬래시 명령 뒤 요청 (요청 34) ----------

def test_command_with_args_becomes_a_turn_and_its_expansion_is_not_a_request(tmp_path):
    tr = tmp_path / "t.jsonl"
    write(tr, [
        user("<command-message>design</command-message>\n<command-name>/design</command-name>\n"
             "<command-args>대화 화면을 고쳐줘</command-args>", "2026-11-10T00:00:00.000Z"),
        meta("`/design` was invoked: Call the Artifact tool …", "2026-11-10T00:00:01.000Z"),
        answer("시안을 만들었습니다", "2026-11-10T00:00:30.000Z"),
    ])
    turns = transcript.parse_turns(tr)
    assert [t.request for t in turns] == ["/design 대화 화면을 고쳐줘"]
    assert turns[0].response == "시안을 만들었습니다"
    assert "Artifact" not in turns[0].request


def test_builtin_command_output_and_commands_without_args_are_not_turns(tmp_path):
    tr = tmp_path / "t.jsonl"
    write(tr, [
        user("<command-name>/model</command-name>\n<command-message>model</command-message>\n"
             "<command-args>sonnet</command-args>", "2026-11-10T00:00:00.000Z"),
        user("<local-command-stdout>Set model to sonnet</local-command-stdout>", "2026-11-10T00:00:01.000Z"),
        user("<command-name>/clear</command-name>\n<command-message>clear</command-message>\n"
             "<command-args></command-args>", "2026-11-10T00:00:02.000Z"),
        user("가격표 만들어줘", "2026-11-10T00:00:03.000Z"),
        answer("만들었습니다", "2026-11-10T00:00:30.000Z"),
    ])
    turns = transcript.parse_turns(tr)
    assert [t.request for t in turns] == ["가격표 만들어줘"]
    assert turns[0].index == 1


def test_skill_expansion_in_the_middle_of_a_reply_does_not_cut_the_turn(tmp_path):
    """2026-11-10 이 세션 기록: 응답 도중 스킬이 펼친 지시문(isMeta)에서 턴이 끊겨 뒤 응답이 버려졌다."""
    tr = tmp_path / "t.jsonl"
    write(tr, [
        user("테마를 정리해줘 /design", "2026-11-10T00:00:00.000Z"),
        answer("먼저 살펴봅니다", "2026-11-10T00:00:10.000Z"),
        meta("스킬 본문 …", "2026-11-10T00:00:11.000Z"),
        answer("캔버스를 만들었습니다", "2026-11-10T00:00:30.000Z"),
    ])
    turns = transcript.parse_turns(tr)
    assert len(turns) == 1
    assert "캔버스를 만들었습니다" in turns[0].response


# ---------- 요청 원장은 사용자 원문에서만 (요청 33) ----------









# ---------- ② 화면 ----------

FLOW = dict(ANALYSIS, turns=[
    {"index": 1, "label": "시작", "summary": "가격표", "response_summary": "요약1"},
    {"index": 2, "label": "범위 축소", "summary": "한국만", "response_summary": "요약2"},
    {"index": 3, "label": "재정의", "summary": "원화 표", "response_summary": "요약3"},
    {"index": 4, "label": "범위 축소", "summary": "서울만", "response_summary": "요약4"},
], ledger=[
    {"condition": "출처 표시", "from_turn": 1, "status": "missed", "evidence": "링크 없음"},
    {"condition": "표로 정리", "from_turn": 1, "status": "kept", "evidence": "표 있음"},
    {"condition": "월 요금도", "from_turn": 2, "status": "unknown", "evidence": "알 수 없음"},
    {"condition": "일본도 포함", "from_turn": 1, "status": "superseded", "superseded_by": 2},
], last_turn=5)


@pytest.mark.asyncio
async def test_head_shows_vertical_goal_flow_and_only_missed_requests(tmp_path):
    home, _, _ = make_session(tmp_path, n=5, analysis=FLOW)
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        lines = text.splitlines()
        assert any(ln.startswith(" ● #1") and "가격표" in ln for ln in lines)
        assert " ┊ … 1단계 더" in text                       # 전환점 3개 중 앞쪽 1개는 접힘
        assert any(ln.startswith(" ◆ #3") and "재정의" in ln for ln in lines)
        assert any(ln.startswith(" ◉ #5") and "지금" in ln for ln in lines)
        assert "요청 체크  누적 3개" in text and "✘ 빠짐 1" in text and "c 전체 보기" in text
        assert "  ✘ 출처 표시 — 링크 없음" in text
        assert "표로 정리" not in text and "월 요금도" not in text  # 기본은 빠짐만
        assert "정보  사용자" not in text and "다음  " not in text
        assert "⚠" not in text


@pytest.mark.asyncio
async def test_c_opens_the_whole_request_list_and_esc_closes_it(tmp_path):
    home, _, _ = make_session(tmp_path, n=5, analysis=FLOW)
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("c")
        text = text_of(app)
        order = [text.index(x) for x in (" 빠짐 1", " 챙김 1", " 확인 안 됨 1", " 뒤 요청이 대신함 1")]
        assert order == sorted(order)
        assert "일본도 포함" in text and "#2에서 바뀜" in text
        assert "c 닫기" in text and "마지막 대화 · #5" not in text   # 대화 흐름 자리를 쓴다
        assert " ◉ #5" in text                                          # 머리는 그대로
        await pilot.press("escape")
        assert "마지막 대화 · #5" in text_of(app)


@pytest.mark.asyncio
async def test_enter_in_the_request_list_jumps_to_the_turn(tmp_path):
    home, _, _ = make_session(tmp_path, n=5, analysis=FLOW)
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("c", "down", "down", "enter")   # 빠짐(#1) → 챙김(#1) → 확인 안 됨(#2)
        assert not app.conversation.checklist
        assert app.conversation.selected == 1


@pytest.mark.asyncio
async def test_hangul_c_key_opens_the_request_list(tmp_path):
    home, _, _ = make_session(tmp_path, n=3, analysis=FLOW)
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("ㅊ")
        assert app.conversation.checklist


@pytest.mark.asyncio
async def test_turns_are_separated_by_a_blank_line(tmp_path):
    home, _, _ = make_session(tmp_path, n=4, analysis=FLOW)
    app = app_for(home)
    async with app.run_test(size=(160, 60)) as pilot:
        await ready(app, pilot)
        lines = text_of(app).splitlines()
        i2 = next(k for k, ln in enumerate(lines) if "#2 " in ln and "요청 2번" in ln)
        i3 = next(k for k, ln in enumerate(lines) if "#3 " in ln and "요청 3번" in ln)
        assert lines[i3 - 1].strip() == ""          # 턴 사이 빈 줄
        assert i3 - i2 >= 3                          # 요청 1줄 + 요약 1줄 이상 + 빈 줄


@pytest.mark.asyncio
async def test_low_screen_keeps_only_first_and_current_goal(tmp_path):
    home, _, _ = make_session(tmp_path, n=5, analysis=FLOW)
    app = app_for(home)
    async with app.run_test(size=(160, 26)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert " ● #1" in text and " ◉ #5" in text and " ◆ " not in text


# ---------- 검토에서 나온 것 (2026-11-10) ----------



@pytest.mark.asyncio
async def test_no_missed_does_not_claim_everything_was_kept(tmp_path):
    a = dict(FLOW, ledger=[{"condition": "표로 정리", "from_turn": 1, "status": "kept"},
                           {"condition": "월 요금도", "from_turn": 2, "status": "unknown"}])
    home, _, _ = make_session(tmp_path, n=5, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "빠짐 없음 · 챙김 1 · 확인 안 됨 1" in text
        assert "모두 챙김" not in text


@pytest.mark.asyncio
async def test_c_does_nothing_before_analysis_and_keys_keep_working(tmp_path):
    home, _, _ = make_session(tmp_path, n=3)
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("c")
        assert not app.conversation.checklist
        before = app.conversation.selected
        await pilot.press("up")
        assert app.conversation.selected == before - 1


# ---------- 요청 37 ----------

@pytest.mark.asyncio
async def test_unchanged_goal_is_one_line_even_over_several_turns(tmp_path):
    a = dict(FLOW, turns=[{"index": 1, "label": "시작", "summary": "가격표", "response_summary": "요약"}],
             first_goal="개발 문서 확인", current_goal="개발 문서 확인", last_turn=5)
    home, _, _ = make_session(tmp_path, n=5, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert " ◉ #1–5 처음·지금 개발 문서 확인" in text
        assert text.count("개발 문서 확인") == 1


@pytest.mark.asyncio
async def test_latest_header_is_followed_by_a_blank_line(tmp_path):
    home, _, _ = make_session(tmp_path, n=2, analysis=FLOW)
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        lines = text_of(app).splitlines()
        k = next(i for i, ln in enumerate(lines) if "마지막 대화 · #2" in ln)
        assert lines[k + 1].strip() == "" and lines[k + 2].startswith("요청")
