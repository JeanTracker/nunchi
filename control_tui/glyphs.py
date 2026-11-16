"""기호 뒤 한 칸 띄우기 (요구 이력 58, SCREEN §8 2026-11-16 기호 겹침).

iTerm이 영문 외 글자를 Noto Sans CJK KR로 그리면, 터미널은 한 칸으로 세는 기호(… → ◆ ● ① ⚠ 등)를
글꼴은 한 칸의 약 1.7배 폭으로 그려 바로 뒤 글자를 덮는다. 그런 기호 바로 뒤에 글자가 붙어 있으면
빈칸을 하나 넣는다. 줄 폭은 그대로 둔다: 넣은 만큼 뒤쪽의 겹친 빈칸(또는 줄 끝 빈칸) 하나를 뺀다.
뺄 빈칸이 없으면 그 기호는 그대로 둔다(줄이 밀리지 않게).

괘선(─ │ ┊ └)과 블록(░ ▒)은 iTerm이 직접 그려 칸에 맞으므로 넣지 않는다.
mod(mod/nunchi/hooks/register.tsx의 WIDE)도 같은 범위를 쓴다.
"""
from __future__ import annotations

from rich.segment import Segment
from textual.filter import LineFilter

# Noto Sans CJK KR에서 폭이 0.65em(한 칸 0.6em)을 넘는 기호 범위. 글꼴 hmtx를 재서 뽑았다.
WIDE_RANGES: tuple[tuple[int, int], ...] = (
    (0x00A7, 0x00A7), (0x00A9, 0x00A9), (0x00B1, 0x00B1), (0x00B6, 0x00B6), (0x00BC, 0x00BE),
    (0x00D7, 0x00D7), (0x00F7, 0x00F7),
    (0x2010, 0x2010), (0x2014, 0x2016), (0x2020, 0x2021), (0x2025, 0x2027), (0x2030, 0x2030),
    (0x2035, 0x2035), (0x203B, 0x203B), (0x2042, 0x2042), (0x2047, 0x2049), (0x2051, 0x2051),
    (0x2100, 0x214F),
    (0x2190, 0x23FF),
    (0x2460, 0x24FF),
    (0x25A0, 0x27BF),
)

_WIDE = frozenset(o for a, b in WIDE_RANGES for o in range(a, b + 1))


def is_wide(ch: str) -> bool:
    return len(ch) == 1 and ord(ch) in _WIDE


def _needs_gap(ch: str, after: str) -> bool:
    return is_wide(ch) and after not in (" ", "")


def gap_text(text: str) -> str:
    """글줄(폭을 아직 정하지 않은 글)에 쓴다: 붙은 기호 뒤에 빈칸을 넣는다."""
    if not any(ord(c) in _WIDE for c in text):
        return text
    out = []
    for i, ch in enumerate(text):
        out.append(ch)
        if _needs_gap(ch, text[i + 1] if i + 1 < len(text) else ""):
            out.append(" ")
    return "".join(out)


def gap_cells(chars: list[str]) -> list[int] | None:
    """폭이 정해진 한 줄의 글자 목록에서 빈칸을 넣을 자리와 뺄 자리를 고른다.

    돌려주는 것: 새 줄의 원래 글자 번호 목록(-1은 넣은 빈칸). 바꿀 것이 없으면 None.
    """
    n = len(chars)
    drop: set[int] = set()
    insert: set[int] = set()
    for i in range(n - 1):
        if not _needs_gap(chars[i], chars[i + 1]):
            continue
        # i+1부터 뒤로 가며 뺄 빈칸: 겹친 빈칸의 앞 칸, 또는 줄 끝 빈칸
        j = i + 1
        found = -1
        while j < n:
            if chars[j] == " " and j not in drop and (j == n - 1 or chars[j + 1] == " "):
                found = j
                break
            j += 1
        if found < 0:
            continue
        drop.add(found)
        insert.add(i)
    if not insert:
        return None
    order: list[int] = []
    for i in range(n):
        if i in drop:
            continue
        order.append(i)
        if i in insert:
            order.append(-1)
    return order


class SymbolGap(LineFilter):
    """관제 화면 모든 줄에 거는 필터. 줄 폭과 글자 모양(색)은 그대로 둔다."""

    def apply(self, segments: list[Segment], background) -> list[Segment]:
        if any(seg.control for seg in segments):
            return segments
        if not any(ord(c) in _WIDE for seg in segments for c in seg.text):
            return segments
        chars: list[str] = []
        styles: list = []
        for seg in segments:
            for c in seg.text:
                chars.append(c)
                styles.append(seg.style)
        order = gap_cells(chars)
        if order is None:
            return segments
        out: list[Segment] = []
        prev = 0
        for k in order:
            if k < 0:
                ch, style = " ", styles[prev]
            else:
                ch, style = chars[k], styles[k]
                prev = k
            if out and out[-1].style == style:
                out[-1] = Segment(out[-1].text + ch, style)
            else:
                out.append(Segment(ch, style))
        return out
