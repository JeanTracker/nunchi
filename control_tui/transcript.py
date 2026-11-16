"""Claude Code 대화 기록(transcript)을 턴 단위로 묶는다 (BUILD_PLAN §3.2).

턴 = 사용자 요청 하나 + 다음 요청 전까지의 응답, 도구 호출, 도구 결과.
하위 에이전트 줄(isSidechain: true)은 읽지 않는다 (R14).
명령 기록(/clear 등)과 시스템이 넣은 메시지는 턴이 아니다.
원문은 줄이지 않고 그대로 담는다. 줄이는 것은 화면에서만 한다.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

RESEARCH_TOOLS = {"WebSearch", "WebFetch", "Read", "Grep", "Glob"}
WORK_TOOLS = {"Write", "Edit"}

# 사용자가 친 요청이 아니라 Claude Code가 남긴 명령 기록 (SCREEN §9, 요청 24)
COMMAND_PREFIXES = ("<command-name>", "<command-message>", "<command-args>",
                    "<local-command-stdout>", "<local-command-stderr>", "<local-command-caveat>")
INTERRUPT_MARKS = ("[Request interrupted by user",)
# 실패가 아니라 사용자·권한 장치가 막은 도구 결과 (이 맥의 실제 기록 34개에서 20건 확인, 2026-11-09)
DENIED_MARKS = ("The user doesn't want to proceed", "Permission for this", "[Request interrupted by user")
TARGET_KEYS = ("description", "command", "file_path", "notebook_path", "url", "pattern", "query", "prompt")
TARGET_CUT = 120
_CONTROL = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"            # CSI (색, 커서)
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"   # OSC (끝 표시가 없어도)
    r"|\x1b[()*+][0-9A-Za-z]|\x1b."           # 문자 집합 지정, 그 밖의 ESC 두 글자
    r"|[\x00-\x08\x0b-\x1f\x7f-\x9f]"         # 나머지 제어 문자
    r"|[​-‏‪-‮⁦-⁩﻿]"  # 폭 0 문자, 방향 제어
)


@dataclass
class ToolCall:
    name: str
    target: str = ""            # 사람이 읽을 대상 한 줄 (설명, 명령, 파일, 주소 …)
    ok: Optional[bool] = None   # 성공 True / 실패 False / 결과 없음·거절 None
    denied: bool = False        # 사용자가 거절했거나 권한 장치가 막음 (실패와 따로 센다)


@dataclass
class Step:
    """응답까지 한 일의 한 단계: 에이전트가 중간에 한 말 + 그 뒤 도구들. 말 없이 시작하면 title이 빈 문자열."""
    title: str = ""
    calls: list = field(default_factory=list)


@dataclass
class Turn:
    index: int
    time: str
    request: str  # 사용자 요청 원문 전체
    response: str = ""  # 응답 원문 전체 (텍스트 블록을 모두 이어 붙인 것). 원문 보기와 분석기 입력
    tools: list = field(default_factory=list)  # (이름, 성공 True / 실패 False / 결과 없음 None)
    calls: list = field(default_factory=list)  # ToolCall 목록 (tools와 같은 순서)
    steps: list = field(default_factory=list)  # Step 목록 (최종 응답 앞까지)
    final_response: str = ""  # 마지막 도구 뒤의 텍스트. 도구로 끝났으면 빈 문자열
    ended_with_tool: bool = False  # 도구로 끝남 = 진행 중이거나 중단됨
    chars_user: int = 0  # 정보량: 사용자 글자 수
    chars_research: int = 0  # 정보량: 조사 결과 글자 수 (추정)
    chars_work: int = 0  # 정보량: 작업 글자 수 (추정)

    @property
    def response_summary(self) -> str:
        """화면 목록용 한 줄 요약. 원문은 그대로 둔다."""
        text = self.final_response or self.response
        return text.split("\n", 1)[0] if text else ""

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.calls if c.ok is False)

    @property
    def denied_count(self) -> int:
        return sum(1 for c in self.calls if c.denied)


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def is_denied(block: dict) -> bool:
    return bool(block.get("is_error")) and _result_text(block.get("content")).lstrip().startswith(DENIED_MARKS)


def clean_line(text: str, cut: int = TARGET_CUT) -> str:
    """제어 문자를 지우고 한 줄로 만든다. 길면 자른다 (화면에 터미널 제어 문자가 나가지 않게)."""
    one = " ".join(_CONTROL.sub("", str(text)).split())
    return one if len(one) <= cut else one[: cut - 1] + "…"


def target_of(name: str, inp) -> str:
    if not isinstance(inp, dict):
        return ""
    for key in TARGET_KEYS:
        value = inp.get(key)
        if isinstance(value, str) and value.strip():
            if key == "command":
                value = value.strip().splitlines()[0]
            return clean_line(value)
    return ""


def is_command_record(text: str) -> bool:
    head = text.lstrip()
    return head.startswith(COMMAND_PREFIXES) or head.startswith(INTERRUPT_MARKS) or head.startswith("<task-notification>")


LOCAL_COMMAND_PREFIXES = ("<local-command-stdout>", "<local-command-stderr>", "<local-command-caveat>")
_COMMAND_NAME = re.compile(r"<command-name>\s*(/?[^<\s]+)\s*</command-name>")
_COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)


def command_with_args(text: str) -> str:
    """슬래시 명령 뒤에 쓴 글을 요청으로 꺼낸다: '/design 글'. 글이 없거나 명령 기록이 아니면 빈 문자열 (요청 34)."""
    head = text.lstrip()
    if not head.startswith(("<command-name>", "<command-message>", "<command-args>")):
        return ""
    args = _COMMAND_ARGS.search(text)
    if not args or not args.group(1).strip():
        return ""
    name = _COMMAND_NAME.search(text)
    cmd = name.group(1) if name else ""
    if cmd and not cmd.startswith("/"):
        cmd = "/" + cmd
    return f"{cmd} {args.group(1).strip()}".strip()


def is_from_human(rec: dict) -> bool:
    """사람이 친 메시지인지. 새 기록은 origin.kind로 구별한다 (2026-11-09 실제 기록 확인:
    사람 = "human", 백그라운드 작업 완료 알림 = "task-notification"). origin이 없는 옛 기록은 사람으로 본다."""
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        return origin.get("kind") == "human"
    return True


def _text_of(content) -> Optional[str]:
    """사용자 메시지에서 실제 요청 글만 꺼낸다. 도구 결과 묶음이면 None."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(texts) if texts else None
    return None


def _result_len(content) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(b.get("text", "")) for b in content if isinstance(b, dict))
    return 0


def _finish(turn: Turn, segments: list) -> None:
    """기록 순서(글, 도구)를 단계와 최종 응답으로 나눈다 (BUILD_PLAN §3.2)."""
    texts = [s for kind, s in segments if kind == "text"]
    turn.response = "\n\n".join(texts)
    last_tool = max((i for i, (kind, _) in enumerate(segments) if kind == "tool"), default=-1)
    if last_tool < 0:
        turn.final_response = turn.response
        return
    turn.final_response = "\n\n".join(s for kind, s in segments[last_tool + 1:] if kind == "text")
    turn.ended_with_tool = not turn.final_response
    step = None
    for kind, item in segments[: last_tool + 1]:
        if kind == "text":
            if step is not None and not step.calls:
                step.title += "\n" + item  # 도구 없이 말이 이어지면 같은 단계 제목으로
            else:
                step = Step(title=item)
                turn.steps.append(step)
        else:
            if step is None:
                step = Step()
                turn.steps.append(step)
            step.calls.append(item)


def parse_turns(path: Path, until_ts: str = "") -> list:
    """until_ts가 있으면 그 시각 뒤에 적힌 기록은 읽지 않는다 (분석 입력 고정, 요청 30)."""
    if not path or not Path(path).exists():
        return []
    limit = _ts_value(until_ts) if until_ts else 0.0
    turns: list = []
    segments: dict = {}  # turn index -> [("text", 글) | ("tool", ToolCall)]
    current: Optional[Turn] = None
    owner: dict = {}  # tool_use_id -> (Turn, tools 인덱스). 결과가 늦게 와도 원래 턴에 붙인다
    names: dict = {}  # tool_use_id -> 도구 이름

    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("isSidechain"):
            continue
        if limit and rec.get("timestamp") and _ts_value(rec.get("timestamp")) > limit:
            continue
        kind = rec.get("type")
        msg = rec.get("message") or {}
        content = msg.get("content")

        if kind == "user":
            text = _text_of(content)
            if text is None:
                for b in content or []:
                    if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                        continue
                    tid = b.get("tool_use_id")
                    ok = not b.get("is_error", False)
                    if tid in owner:
                        turn, idx = owner.pop(tid)
                        if is_denied(b):
                            turn.calls[idx].denied = True  # 거절은 실패로 세지 않는다
                            turn.tools[idx] = (turn.tools[idx][0], None)  # 두 자료가 같은 상태를 말하도록
                        else:
                            turn.calls[idx].ok = ok
                            turn.tools[idx] = (turn.tools[idx][0], ok)
                        name = names.get(tid, "")
                        if name in RESEARCH_TOOLS or name.startswith("mcp__"):
                            turn.chars_research += _result_len(b.get("content"))
                continue
            command_request = command_with_args(text) if is_from_human(rec) and not rec.get("isMeta") else ""
            if current is not None and current.request.startswith("/") and not segments[current.index]:
                # 슬래시 명령 턴 바로 뒤 (요청 34)
                if rec.get("isMeta"):
                    continue  # 명령이 펼친 지시문: 턴을 끊지 않고 요청에도 넣지 않는다
                if text.lstrip().startswith(LOCAL_COMMAND_PREFIXES):
                    turns.pop()  # 내장 명령(/model 등)의 결과: 요청 턴이 아니다
                    segments.pop(current.index, None)
                    current = None
                    continue
            if rec.get("isMeta") and current is not None and segments[current.index]:
                continue  # 응답 도중 스킬이 펼친 지시문: 턴을 끊으면 뒤 응답이 버려진다 (2026-11-10 이 세션 기록)
            if command_request:
                text = command_request
            elif (rec.get("isMeta") or rec.get("isCompactSummary") or not is_from_human(rec)
                    or is_command_record(text)):
                # 명령 기록, 시스템 메시지는 턴이 아니다. 뒤에 오는 응답이 앞 턴에 붙지 않도록 턴을 끊는다.
                # 단, 사용자 중단 표시는 지금 턴에 대한 것이라 끊지 않는다.
                if not text.lstrip().startswith(INTERRUPT_MARKS):
                    current = None
                continue
            current = Turn(index=len(turns) + 1, time=str(rec.get("timestamp") or ""), request=text.strip())
            current.chars_user = len(text)
            turns.append(current)
            segments[current.index] = []

        elif kind == "assistant" and current is not None:
            for b in content or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    segments[current.index].append(("text", b["text"].strip()))
                    current.chars_work += len(b["text"])
                elif b.get("type") == "tool_use":
                    tid = b.get("id", "")
                    name = b.get("name", "?")
                    inp = b.get("input") or {}
                    call = ToolCall(name=name, target=target_of(name, inp))
                    names[tid] = name
                    current.tools.append((name, None))
                    current.calls.append(call)
                    owner[tid] = (current, len(current.tools) - 1)
                    segments[current.index].append(("tool", call))
                    if name in WORK_TOOLS:
                        current.chars_work += len(str(inp.get("content") or inp.get("new_string") or ""))

    for t in turns:
        _finish(t, segments.get(t.index, []))
    return turns


TAIL_BYTES = 64 * 1024


def _ts_value(ts: str) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def interrupted_after(path, since_ts: str) -> bool:
    """since_ts 뒤에 사용자 중단·거절이 기록됐는지. 기록 끝부분만 읽는다.

    허락 창에서 거절(Esc)하면 Claude Code는 훅을 더 보내지 않는다(2026-11-09 실험).
    대신 대화 기록에 "[Request interrupted by user …"와 거절된 도구 결과가 남으므로 이것으로 상태를 푼다.
    """
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode("utf-8", "replace")
    except (OSError, TypeError):
        return False
    since = _ts_value(since_ts)
    for line in reversed(tail.splitlines()):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "user":
            continue
        if _ts_value(rec.get("timestamp")) <= since:
            return False  # 이 뒤로는 모두 since_ts보다 앞선 기록
        content = (rec.get("message") or {}).get("content")
        text = _text_of(content)
        if text is not None and text.lstrip().startswith(INTERRUPT_MARKS):
            return True
        if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                             and is_denied(b) for b in content):
            return True
    return False


QUESTION_TAIL_BYTES = 1024 * 1024


def pending_questions(path, tool_use_id: str = "") -> list:
    """답을 기다리는 질문 창(AskUserQuestion)의 질문 목록. 없거나 이미 답했으면 빈 목록 (요청 39).

    훅 기록의 tool_input은 500자에서 잘리므로 대화 기록의 도구 호출 입력을 읽는다. 끝부분만 본다.
    tool_use_id가 있으면 그 호출만, 없으면 마지막 AskUserQuestion 호출을 본다.
    """
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - QUESTION_TAIL_BYTES))
            tail = f.read().decode("utf-8", "replace")
    except (OSError, TypeError):
        return []
    found, answered = None, set()
    for line in tail.splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if (b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion"
                    and (not tool_use_id or b.get("id") == tool_use_id)):
                found = b
            elif b.get("type") == "tool_result":
                answered.add(b.get("tool_use_id"))
    if found is None or found.get("id") in answered:
        return []
    questions = (found.get("input") or {}).get("questions")
    if not isinstance(questions, list):
        return []
    out = []
    for q in questions:
        if not isinstance(q, dict) or not isinstance(q.get("options"), list) or not q["options"]:
            return []   # 모양이 다르면 관제에서 답하지 않는다 (패널에서)
        out.append({"question": str(q.get("question", "")), "header": str(q.get("header", "")),
                    "multiSelect": bool(q.get("multiSelect")),
                    "options": [{"label": str(o.get("label", "")), "description": str(o.get("description", ""))}
                                for o in q["options"] if isinstance(o, dict)]})
    return out


def totals(turns: list) -> dict:
    """정보량 합계. 값은 글자 수이며 추정이다 (SCREEN §6)."""
    return {
        "user": sum(t.chars_user for t in turns),
        "research": sum(t.chars_research for t in turns),
        "work": sum(t.chars_work for t in turns),
    }
