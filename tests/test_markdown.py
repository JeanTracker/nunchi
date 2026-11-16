"""요청 37: 마지막 응답의 마크다운을 터미널에서 읽기 좋게 그린다 (SCREEN §2 ② 마지막 대화)."""

from rich.cells import cell_len

from control_tui.widgets.conversation import md_lines

TABLE = """1. git에 올라가지 않은 문서 3개 (`?? docs/`)

| 문서 | 상태 | 할 일 |
|---|---|---|
| `docs/native-titlebar.md` | 최신입니다. 9/16 절까지 들어 있습니다. | 커밋해야 합니다. |
| `docs/adotall-reauth-deeplink.md` | FAQ 재인증 링크 규격이 들어 있습니다. 기획·운영에 그대로 넘길 수 있는 내용입니다. | 커밋해야 합니다. |
"""


def plain(lines):
    return [ln.plain for ln in lines]


def test_table_is_drawn_with_columns_not_pipes():
    out = plain(md_lines(TABLE, 100))
    assert not any(ln.lstrip().startswith("|") for ln in out)
    assert not any("|---" in ln for ln in out)
    head = next(ln for ln in out if "문서" in ln and "상태" in ln)
    assert head.count("│") == 2
    assert any("─┼─" in ln for ln in out)
    assert all(cell_len(ln) <= 100 for ln in out)
    # 칸이 세로로 맞는다: 모든 표 줄에서 첫 │ 위치가 같다
    rows = [ln for ln in out if "│" in ln]
    assert len({cell_len(ln[:ln.index("│")]) for ln in rows}) == 1


def test_inline_code_and_bold_lose_their_marks():
    out = md_lines("**굵게** 그리고 `docs/a.md`와 [링크](https://x.y)", 80)
    assert out[0].plain == "굵게 그리고 docs/a.md와 링크"
    styles = {str(span.style) for span in out[0].spans}
    assert any("bold" in s for s in styles)


def test_numbered_list_continuation_is_indented():
    out = plain(md_lines("1. " + "가나다라 " * 20, 30))
    assert out[0].startswith("1. ")
    assert all(ln.startswith("   ") for ln in out[1:])


def test_code_block_is_marked_and_fences_hidden():
    out = plain(md_lines("앞\n```sh\nnpm test\n```\n뒤", 40))
    assert out == ["앞", "│ npm test", "뒤"]


def test_narrow_screen_turns_table_into_label_value_lines():
    out = plain(md_lines(TABLE, 20))
    assert any(ln.startswith("문서:") for ln in out)   # 긴 경로는 다음 줄에서 시작할 수 있다
    assert all(cell_len(ln) <= 20 for ln in out)


def test_english_wraps_at_word_boundaries():
    out = plain(md_lines("alpha beta gamma delta epsilon", 12))
    assert out == ["alpha beta", "gamma delta", "epsilon"]


def test_long_path_in_first_column_is_not_broken():
    text = ("| 문서 | 상태 |\n|---|---|\n| `docs/adotall-web-titlebar-plan.md` | " + "긴 설명입니다. " * 30 + "|\n")
    out = plain(md_lines(text, 100))
    assert any("docs/adotall-web-titlebar-plan.md" in ln for ln in out)


def test_hash_number_is_not_a_heading_and_rule_is_a_line():
    out = plain(md_lines("#33 작업이 남았습니다\n---\n# 제목", 40))
    assert out[0] == "#33 작업이 남았습니다"
    assert set(out[1]) == {"─"}
    assert out[2] == "제목"


def test_short_path_column_survives_when_another_column_has_a_long_word():
    text = ("| 문서 | 상태 |\n|---|---|\n| `docs/adotall-web-titlebar-plan.md` | 경로가 "
            + "components/account/AdotAllHeader.vue인데요가나다라마바사 " + "긴 설명입니다. " * 30 + "|\n")
    out = plain(md_lines(text, 70))
    assert any("docs/adotall-web-titlebar-plan.md" in ln for ln in out)
