"""① 세션 목록 폴더 묶기와 세션 제목 (요구 이력 59)."""
import json

from control_tui import lifecycle, transcript
from control_tui.store import SessionView
from textual.app import App

from control_tui.widgets.session_list import SessionList


def _v(sid, cwd, state="responded", missed=0, name=""):
    v = SessionView(session_id=sid, cwd=str(cwd), state=state, last_ts="2026-11-16T00:00:00Z")
    v.missed = missed
    v.name = name
    return v


def _repos(tmp_path):
    a = tmp_path / "WebProjects" / "plan"
    (a / ".git").mkdir(parents=True)
    (a / "기획문서" / "회원").mkdir(parents=True)
    b = tmp_path / "edu" / "nunchi"
    (b / ".git").mkdir(parents=True)
    c = tmp_path / "loose"
    c.mkdir()
    return a, b, c


def test_groups_by_git_root_in_first_seen_order(tmp_path):
    a, b, c = _repos(tmp_path)
    views = [_v("b1", b), _v("a1", a), _v("c1", c), _v("a2", a / "기획문서" / "회원"), _v("b2", b, "ended")]
    out = lifecycle.group_views(views)
    assert [v.session_id for v in out] == ["b1", "b2", "a1", "a2", "c1"]   # 폴더는 처음 나온 자리, 안은 원래 순서
    assert out[3].group == str(a) and out[3].subpath == "기획문서/회원"
    assert out[2].subpath == "" and out[2].group_label == "plan"
    assert out[4].group == str(c)                                            # git이 없으면 연 폴더


def test_same_name_folders_get_parent_name(tmp_path):
    x = tmp_path / "one" / "app"
    y = tmp_path / "two" / "app"
    for p in (x, y):
        (p / ".git").mkdir(parents=True)
    out = lifecycle.group_views([_v("x", x), _v("y", y)])
    assert [v.group_label for v in out] == ["one/app", "two/app"]


def test_session_title_prefers_custom_and_reads_only_new_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    rows = [{"type": "user", "message": {"content": "hi"}},
            {"type": "ai-title", "aiTitle": "멀티 페르소나 타겟 선택 GUI", "sessionId": "s"}]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    assert transcript.session_title(path) == "멀티 페르소나 타겟 선택 GUI"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "custom-title", "customTitle": "페르소나 작업"}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"type": "ai-title", "aiTitle": "다른 제목"}, ensure_ascii=False) + "\n")
    assert transcript.session_title(path) == "페르소나 작업"          # 사용자가 바꾼 이름이 먼저
    assert transcript.session_title(tmp_path / "없음.jsonl") == ""
    assert transcript.session_title("") == ""


class _Host(App):
    def compose(self):
        yield SessionList(id="list")


async def _list(views, selected):
    app = _Host()
    async with app.run_test(size=(80, 20)) as pilot:
        w = app.query_one(SessionList)
        w.views = views
        w.selected_id = selected
        return w.render_text().plain.splitlines(), w


async def test_list_shows_folder_lines_titles_and_id_in_parentheses(tmp_path):
    a, b, _ = _repos(tmp_path)
    views = lifecycle.group_views([
        _v("e8d48075", b, "working", name="마지막 응답 제한 이유"),
        _v("257ef4ed", a, "permission", missed=2, name="멀티 페르소나 타겟 선택 GUI"),
        _v("02660000", a / "기획문서" / "회원", "ended", name=""),
    ])
    text, _ = await _list(views, "e8d48075")
    assert text[0].startswith("nunchi  1")
    assert "마지막 응답 제한 이유 (e8d4)" in text[1] and text[1].lstrip().startswith("1")
    assert text[2].startswith("plan  1 · 허락 1 · ⚠2")
    assert "멀티 페르소나 타겟 선택 GUI (257e)" in text[3]
    assert "기획문서/회원 · 새 세션 (0266)" in text[4] and text[4].lstrip().startswith("3")
    assert "#e8d4" not in "\n".join(text)


async def test_single_folder_has_no_folder_line(tmp_path):
    _, b, _ = _repos(tmp_path)
    views = lifecycle.group_views([_v("e8d48075", b, name="제목 하나"), _v("363fc5ef", b)])
    text, _ = await _list(views, "e8d48075")
    assert len(text) == 2
    assert "nunchi · 제목 하나 (e8d4)" in text[0]
    assert "nunchi (363f)" in text[1]                  # 제목이 아직 없으면 폴더 이름


async def test_moving_skips_folder_lines(tmp_path):
    a, b, _ = _repos(tmp_path)
    views = lifecycle.group_views([_v("b1", b), _v("a1", a)])
    app = _Host()
    async with app.run_test(size=(80, 20)):
        w = app.query_one(SessionList)
        w.views = views
        w.selected_id = "b1"
        w.action_move(1)
        assert w.selected_id == "a1"
