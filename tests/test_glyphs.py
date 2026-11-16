"""기호 뒤 한 칸 띄우기 (요구 이력 58)."""
from rich.segment import Segment
from rich.style import Style

from control_tui.glyphs import SymbolGap, gap_text, is_wide
from rich.cells import cell_len


def test_wide_symbols_and_box_drawing():
    for ch in "…→◆◉●○⊘①⚠—§":
        assert is_wide(ch), ch
    for ch in "─│┊└░·“”–a가":     # 괘선·블록은 iTerm이 직접 그리고, 나머지는 칸에 맞는다
        assert not is_wide(ch), ch


def test_gap_text_only_where_a_letter_touches():
    assert gap_text("…3개") == "… 3개"
    assert gap_text("A→B") == "A→ B"
    assert gap_text("◆ #3") == "◆ #3"          # 이미 띄어 있으면 그대로
    assert gap_text("끝…") == "끝…"             # 줄 끝
    assert gap_text("①②") == "① ②"             # 붙은 것마다


def _apply(segments):
    return SymbolGap().apply(segments, None)


def test_filter_keeps_line_width_and_styles():
    red, dim = Style(color="red"), Style(dim=True)
    line = [Segment("◆", red), Segment("#3 지금 목표", dim), Segment("    ")]
    out = _apply(line)
    text = "".join(s.text for s in out)
    assert text.startswith("◆ #3 지금 목표")
    assert cell_len(text) == cell_len("".join(s.text for s in line))
    assert out[0].style == red and out[0].text == "◆ "     # 넣은 빈칸은 기호 색
    assert any(s.style == dim and s.text.startswith("#3") for s in out)


def test_filter_takes_space_from_the_nearest_gap_so_columns_stay():
    line = [Segment("a→b  │ x")]
    out = "".join(s.text for s in _apply(line))
    assert out == "a→ b │ x"       # 칸막이 │ 자리는 그대로
    assert len(out) == len("a→b  │ x")


def test_filter_leaves_line_alone_when_no_space_to_take():
    line = [Segment("a→bc")]
    assert _apply(line) == line


def test_control_segments_untouched():
    line = [Segment("→x"), Segment("", None, [(1,)])]
    assert _apply(line) == line
