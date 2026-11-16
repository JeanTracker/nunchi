"""디자인 시스템: 색 역할과 테마 7개 (SCREEN §10, BUILD_PLAN §3.5, 요청 36).

위젯은 Rich 스타일에 색 이름("yellow", "grey50") 대신 역할(C.warn, C.subtle)만 쓴다.
값은 그리는 순간 읽으므로, 테마를 바꾸면 다음 그리기부터 새 색이 된다.
같은 값으로 Textual 테마도 만든다. 테두리·바탕처럼 CSS가 그리는 곳은 그쪽 변수를 쓴다.
"""

# 역할: pane.1~3 구역 색, idle 지금 구역이 아닌 테두리, text/muted/subtle/faint 글자 흐림 4단계,
# ok/warn/err/info 상태, bg 바탕, bar 머리·맨 아래 줄 바탕, sel 고른 줄 바탕.
# 값은 디자인 캔버스 '관제 TUI 디자인 시스템과 테마'의 시안과 같다. 호박·인광·모래는 넣지 않는다 (요청 36).
THEMES = {
    "graphite": {"label": "흑연", "dark": True,
                 "bg": "#121417", "text": "#e6e6e6", "muted": "#a8a8a8", "subtle": "#8c8c8c", "faint": "#5f6368",
                 "idle": "#3a3f45", "p1": "#4ea1ff", "p2": "#c58af9", "p3": "#ffa62b",
                 "ok": "#4ec27a", "warn": "#e5c07b", "err": "#f26d6d", "info": "#56c8d8",
                 "bar": "#1d2025", "sel": "#23324a"},
    "midnight": {"label": "심야", "dark": True,
                 "bg": "#0b1220", "text": "#dbe4f3", "muted": "#9fadc4", "subtle": "#8290a8", "faint": "#4a5672",
                 "idle": "#263453", "p1": "#5b9dff", "p2": "#b388ff", "p3": "#ff9e64",
                 "ok": "#5fd38d", "warn": "#f2c14e", "err": "#ff6b81", "info": "#4fd1e8",
                 "bar": "#111a2e", "sel": "#1b2b4d"},
    "polar": {"label": "극지", "dark": True,
              "bg": "#20252e", "text": "#e5e9f0", "muted": "#b4bcca", "subtle": "#97a1b2", "faint": "#5b6576",
              "idle": "#3b4252", "p1": "#81a1c1", "p2": "#b48ead", "p3": "#d08770",
              "ok": "#a3be8c", "warn": "#ebcb8b", "err": "#e07a84", "info": "#88c0d0",
              "bar": "#2a303b", "sel": "#363f50"},
    "forest": {"label": "숲", "dark": True,
               "bg": "#0f1a14", "text": "#dfe8df", "muted": "#a6b7a8", "subtle": "#88998c", "faint": "#4e6155",
               "idle": "#2c3d33", "p1": "#6fb3e0", "p2": "#d39be0", "p3": "#e8a95b",
               "ok": "#7fd18b", "warn": "#e3c567", "err": "#ef7a6c", "info": "#6fd0c4",
               "bar": "#15231b", "sel": "#1f3a2b"},
    "dusk": {"label": "황혼", "dark": True,
             "bg": "#17121f", "text": "#ece4f7", "muted": "#b8abcc", "subtle": "#9a8cb1", "faint": "#5d5074",
             "idle": "#3a2f4d", "p1": "#82aaff", "p2": "#c792ea", "p3": "#ffcb6b",
             "ok": "#a6e3a1", "warn": "#f9e2af", "err": "#f38ba8", "info": "#89dceb",
             "bar": "#1f1829", "sel": "#2d2340"},
    "contrast": {"label": "고대비", "dark": True,
                 "bg": "#000000", "text": "#ffffff", "muted": "#d6d6d6", "subtle": "#c2c2c2", "faint": "#8a8a8a",
                 "idle": "#6e6e6e", "p1": "#00b7ff", "p2": "#ff5cf4", "p3": "#ffd400",
                 "ok": "#00ff7f", "warn": "#ffd400", "err": "#ff4d4d", "info": "#00e5ff",
                 "bar": "#000000", "sel": "#00315c"},
    "paper": {"label": "종이 (밝은)", "dark": False,
              "bg": "#fbfaf7", "text": "#1f2328", "muted": "#57606a", "subtle": "#6e7781", "faint": "#a0a8b0",
              "idle": "#d0d7de", "p1": "#0969da", "p2": "#8250df", "p3": "#bc4c00",
              "ok": "#1a7f37", "warn": "#8a5d00", "err": "#cf222e", "info": "#0e7490",
              "bar": "#efede6", "sel": "#ddeafc"},
}
DEFAULT = "graphite"
PREFIX = "nunchi-"   # Textual 테마 이름. Textual 기본 테마와 섞이지 않게 붙인다
ROLES = ("bg", "text", "muted", "subtle", "faint", "idle", "p1", "p2", "p3", "ok", "warn", "err", "info", "bar", "sel")


class Palette:
    """지금 테마의 역할별 값. C.warn처럼 읽는다. 표에 담아 둔 역할 이름은 C.get("warn")으로 읽는다."""

    def __init__(self, name: str = DEFAULT):
        self.name = ""
        self.use(name)

    def use(self, name: str) -> str:
        name = name if name in THEMES else DEFAULT
        self.name = name
        for role in ROLES:
            setattr(self, role, THEMES[name][role])
        return name

    def get(self, role: str) -> str:
        """역할 이름의 값. 역할이 아니면 받은 글을 그대로 돌려준다 (이미 값인 경우)."""
        return getattr(self, role, role) if role in ROLES else role

    def pane(self, n: int) -> str:
        return {1: self.p1, 2: self.p2, 3: self.p3}.get(n, self.p1)


C = Palette()


def textual_name(name: str) -> str:
    return PREFIX + (name if name in THEMES else DEFAULT)


def plain_name(textual: str) -> str:
    """Textual 테마 이름 → 우리 테마 이름. 우리 것이 아니면 빈 글."""
    if textual.startswith(PREFIX) and textual[len(PREFIX):] in THEMES:
        return textual[len(PREFIX):]
    return ""


def textual_themes() -> list:
    """Textual에 등록할 테마. CSS가 그리는 테두리·바탕·명령 팔레트가 같은 값을 쓴다."""
    from textual.theme import Theme  # 분석기·훅은 textual 없이 이 파일을 읽는다 (설정의 테마 이름 확인)
    out = []
    for name, t in THEMES.items():
        out.append(Theme(
            name=textual_name(name), dark=t["dark"],
            primary=t["p1"], secondary=t["p2"], accent=t["p3"],
            foreground=t["text"], background=t["bg"], surface=t["bg"], panel=t["bar"],
            success=t["ok"], warning=t["warn"], error=t["err"],
            variables={"pane-1": t["p1"], "pane-2": t["p2"], "pane-3": t["p3"], "border-idle": t["idle"],
                       "text-subtle": t["subtle"], "bar": t["bar"], "footer-background": t["bar"],
                       "footer-key-foreground": t["p3"], "footer-description-foreground": t["text"]},
        ))
    return out
