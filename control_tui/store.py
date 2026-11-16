"""세션 기록을 읽고 상태를 계산한다 (BUILD_PLAN §3.1, SCREEN §2 ①).

- 입력: CONTROL_TUI_HOME/sessions/<id>/events.jsonl (hooks/emit.py가 쓴 기록)
- 출력: 목록에 보일 세션 요약 (상태, 현재 도구, 도구 기록, 응답 도착 시각)
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def base_dir() -> Path:
    return Path(os.environ.get("CONTROL_TUI_HOME", Path.home() / ".claude-control"))


@dataclass
class Tool:
    tool_use_id: str
    name: str
    status: str  # "running" | "ok" | "fail"


@dataclass
class SessionView:
    session_id: str
    cwd: str
    state: str  # idle | working | responded | permission | question | ended
    last_ts: str
    responded_ts: str = ""  # 응답이 도착한 시각 (Stop). 정렬 기준
    current_tool: str = ""
    tools: list = field(default_factory=list)
    iterm_session_id: str = ""
    transcript_path: str = ""
    permission_mode: str = ""  # 마지막 훅이 알려 준 권한 모드 (default, acceptEdits, plan, auto ...)
    missed: int = 0            # 분석기가 찾은 빠진 조건 수 (①에 ⚠로 표시)
    analysis_mark: str = ""    # ① 누락 표시 옆 분석 상태 기호: · 대기, ↻ 분석 중, ! 실패, 새 (요청 30)
    judged: bool = True        # 분석 결과가 있는지. 없으면 ①에 ◌ (판정 전)
    question_id: str = ""      # 질문 대기(question)일 때 그 AskUserQuestion 도구 호출 ID (요청 39)
    questions: list = field(default_factory=list)  # 그 질문 목록 (대화 기록에서 읽음, 훅 기록은 잘린다)
    ended_ts: str = ""         # 종료 시각. SessionEnd 훅, 또는 관제가 패널에서 claude가 사라진 것을 본 시각 (요청 35)

    @property
    def title(self) -> str:
        name = Path(self.cwd).name if self.cwd else self.session_id[:8]
        return name or self.session_id[:8]


def load_events(session_dir: Path) -> list:
    path = session_dir / "events.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 깨진 줄은 건너뛴다 (부분 기록 대비)
    return rows


def summarize(session_id: str, events: list) -> SessionView:
    view = SessionView(session_id=session_id, cwd="", state="idle", last_ts="")
    tools: dict = {}
    order: list = []
    for ev in events:
        name = ev.get("event", "")
        view.last_ts = ev.get("ts", view.last_ts)
        view.cwd = ev.get("cwd") or view.cwd
        view.iterm_session_id = ev.get("iterm_session_id") or view.iterm_session_id
        view.transcript_path = ev.get("transcript_path") or view.transcript_path
        data = ev.get("data", {}) or {}
        view.permission_mode = data.get("permission_mode") or view.permission_mode

        if name in ("UserPromptSubmit", "Stop"):
            # 새 요청이나 응답 끝: 앞 턴에서 끝을 못 받은 도구(거절하면 훅이 오지 않음)는 더 이상 '실행 중'이 아니다
            for t in tools.values():
                if t.status == "running":
                    t.status = "stopped"
        if name in ("UserPromptSubmit", "Stop", "SessionEnd"):
            view.question_id = ""
        if name in ("UserPromptSubmit",):
            view.state = "working"
        elif name == "PreToolUse":
            view.state = "working"
            tid = data.get("tool_use_id") or f"anon-{len(order)}"
            tools[tid] = Tool(tid, data.get("tool_name", "?"), "running")
            order.append(tid)
        elif name in ("PostToolUse", "PostToolUseFailure"):
            tid = data.get("tool_use_id")
            if tid in tools:
                tools[tid].status = "ok" if name == "PostToolUse" else "fail"
            elif tid:
                tools[tid] = Tool(tid, data.get("tool_name", "?"),
                                  "ok" if name == "PostToolUse" else "fail")
                order.append(tid)
            if view.state == "question" and tid == view.question_id:
                # 질문에 답이 갔다 (요청 39). 허락은 예전대로 다음 훅까지 둔다
                view.state, view.question_id = "working", ""
        elif name == "Stop":
            view.state = "responded"
            view.responded_ts = ev.get("ts", "")
        elif name == "Notification":
            kind = data.get("notification_type", "")
            if kind == "permission_prompt":
                # 질문 창(AskUserQuestion)도 같은 알림을 보낸다. 그때 실행 중인 도구로 가른다 (SCREEN §8, 요청 39)
                asking = [t for t in tools.values() if t.status == "running" and t.name == "AskUserQuestion"]
                if asking:
                    view.state, view.question_id = "question", asking[-1].tool_use_id
                else:
                    view.state = "permission"
            # idle_prompt는 응답 완료 상태를 덮지 않는다 (미확인 강조 유지)
        elif name == "SessionEnd":
            view.state = "ended"
            view.ended_ts = ev.get("ts", "")
        elif name == "SessionStart" and view.state in ("idle", "ended"):
            view.state = "idle"
            view.ended_ts = ""

    view.tools = [tools[t] for t in order]
    running = [t for t in view.tools if t.status == "running"]
    view.current_tool = running[-1].name if running else ""
    return view


def load_sessions(home: Path = None) -> list:
    home = home or base_dir()
    root = home / "sessions"
    if not root.exists():
        return []
    views = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        events = load_events(d)
        if events:
            view = summarize(d.name, events)
            _recover_after_interrupt(view)
            if view.state == "question":
                from control_tui.transcript import pending_questions
                view.questions = pending_questions(view.transcript_path, view.question_id)
            views.append(view)
    return sort_sessions(views)


def _recover_after_interrupt(view) -> None:
    """허락 창에서 거절하거나 사용자가 중단하면 훅이 더 오지 않아 '작업'·'허락'에 멈춘다.
    대화 기록에 그 뒤 중단·거절이 남아 있으면 대기로 돌린다 (2026-11-09 실험, BUILD_PLAN §3.1)."""
    if view.state not in ("working", "permission", "question") or not view.transcript_path:
        return
    from control_tui.transcript import interrupted_after
    if interrupted_after(view.transcript_path, view.last_ts):
        view.state = "idle"
        view.current_tool = ""
        view.question_id = ""


def sort_sessions(views: list) -> list:
    """응답이 도착한 순서(최신이 위)로 정렬하고, 응답이 없는 세션은 최근 활동순으로 뒤에 둔다."""
    responded = sorted([v for v in views if v.responded_ts],
                       key=lambda v: v.responded_ts, reverse=True)
    rest = sorted([v for v in views if not v.responded_ts],
                  key=lambda v: v.last_ts, reverse=True)
    return responded + rest
