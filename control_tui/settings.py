"""사용자 설정 파일 (BUILD_PLAN §4.1, SCREEN §3 "사용자 설정 옵션").

파일: <관제 홈>/config.json (기본 ~/.claude-control/config.json, CONTROL_TUI_HOME로 바꿀 수 있음).
없거나 깨졌으면 기본값을 쓴다. 관제는 이 파일을 읽기만 한다 (사용자가 직접 고친다).
"""

import json
from dataclasses import dataclass, fields
from pathlib import Path

SCOPES = ("off", "selected", "all")     # 분석 대상: 끄기 / 고른 세션만 / 모든 세션
WHEN = ("auto", "manual")               # 실행 시점: 응답마다 / 키(a)를 눌렀을 때
LATEST_VIEWS = ("full", "summary")      # 마지막 응답 보기: 전체(기본) / 요약


@dataclass
class Settings:
    analyze_scope: str = "selected"
    analyze_when: str = "auto"
    analyze_model: str = ""             # 비우면 claude 기본 모델
    analyze_max_turns: int = 60
    analyze_workers: int = 1            # 분석을 동시에 몇 개까지 돌릴지 (1~2, 요구 이력 53). 사용량 한도를 함께 쓰므로 기본 1
    latest_view: str = "full"
    theme: str = "graphite"             # 테마 (요청 36, SCREEN §10): graphite midnight polar forest dusk contrast paper

    def normalized(self) -> "Settings":
        s = Settings(**{f.name: getattr(self, f.name) for f in fields(self)})
        if s.analyze_scope not in SCOPES:
            s.analyze_scope = "selected"
        if s.analyze_when not in WHEN:
            s.analyze_when = "auto"
        if s.latest_view not in LATEST_VIEWS:
            s.latest_view = "full"
        from control_tui.theme import THEMES, DEFAULT
        if s.theme not in THEMES:
            s.theme = DEFAULT
        try:
            s.analyze_max_turns = max(5, min(200, int(s.analyze_max_turns)))
        except (TypeError, ValueError):
            s.analyze_max_turns = 60
        try:
            s.analyze_workers = max(1, min(2, int(s.analyze_workers)))
        except (TypeError, ValueError):
            s.analyze_workers = 1
        s.analyze_model = str(s.analyze_model or "").strip()
        return s


def load(home: Path) -> Settings:
    path = Path(home) / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in data.items() if k in known}).normalized()
