"""4단계 분석기 (BUILD_PLAN §4·§4.1, SCREEN §2 ②, REQUIREMENTS R2·R8·R9).

- 세션이 응답을 끝내면(Stop), 그 턴 기록을 claude -p에 넘겨 목표·관계·조건 판정을 받는다.
- 결과는 세션 폴더의 analysis.json에 쓴다. source_ts가 응답 시각과 같으면 다시 분석하지 않는다.
- 분석기 자신의 세션은 훅이 기록하지 않는다 (CONTROL_TUI_ANALYZER=1, hooks/emit.py).
- 한 번에 한 건만 돈다. 지금 화면에서 고른 세션이 먼저, 나머지는 응답이 최근인 것부터 (요청 30).
- 같은 세션의 아직 시작하지 않은 옛 요청은 최신 요청으로 합친다.
- 분석을 시작할 때 그 응답 시각까지의 턴만 본다 (기다리는 사이 생긴 턴은 섞지 않는다).
- 실패하면 잠시 쉬었다가 정해진 횟수만 다시 한다. 관제를 끄면 기다리던 분석은 버리고 도는 것도 멈춘다.
- claude -p는 도구를 모두 끈다 (--tools ""). 모델은 설정 파일로 정할 수 있다.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from control_tui.transcript import _ts_value, parse_turns

RELATIONS = ("시작", "구체화", "재정의", "정정", "범위 축소", "문제 제기", "확정", "질문")
LEDGER_STATUSES = ("kept", "missed", "unknown", "superseded")
STATUS_LABEL = {"kept": "챙김", "missed": "빠짐", "unknown": "확인 안 됨", "superseded": "뒤 요청이 대신함"}
QUOTE_MIN = 2              # 원문 인용이 이보다 짧으면 사용자 요청에서 나왔다고 보지 않는다 (요청 33)

REQUEST_CUT = 600          # 프롬프트에 넣는 사용자 요청 글자 수 (턴마다)
RESPONSE_CUT = 400         # 프롬프트에 넣는 응답 글자 수 (마지막 턴을 뺀 턴마다)
MAX_TURNS = 60             # 최근 턴만 본다 (설정 파일 analyze_max_turns로 바꿀 수 있음)
SUMMARY_CUT = 120          # 응답 요약은 ② 폭 2줄(한글 약 90자) 안으로 쓰게 하고 이만큼에서 자른다
TIMEOUT_SECONDS = 150      # 실측 26~54초 (2026-11-10). 넉넉히 잡되 240초보다 줄였다
RETRY_SECONDS = 60.0       # 실패한 분석을 다시 하기 전 쉬는 시간
MAX_ATTEMPTS = 2           # 같은 응답에 대해 자동으로 해 보는 최대 횟수 (r 키로 다시 하면 초기화)
REPLY_WAIT_SECONDS = 5.0   # Stop 훅은 마지막 글이 기록에 적히기 전에 온다(SCREEN §8). 마지막 턴 글을 이만큼 기다린다
REPLY_POLL_SECONDS = 0.25
FLOW_STEPS_PER_JOB = 10    # 목표 흐름(요청 40)을 한 번에 이어 적는 최대 턴 수. 남으면 다음 차례에 이어서 (다른 세션을 오래 막지 않게)


class AnalyzerError(RuntimeError):
    pass


PROMPT_HEAD = """너는 대화 흐름 분석기다. 아래는 사용자가 Claude Code 세션에 보낸 요청들과 응답이다.
마지막 턴은 응답 전체, 그 앞 턴은 응답 앞부분만 있다.
반드시 JSON 객체 하나만 출력하라. 설명, 코드 블록, 머리말은 쓰지 마라.

출력 형식:
{"first_goal": "처음 목표 한 줄", "current_goal": "지금 목표 한 줄",
 "turns": [{"index": 1, "label": "시작", "summary": "요청 요약 한 줄", "response_summary": "응답 요약"}],
 "last_response_summary": "마지막 응답 요약",
 "ledger": [{"id": "R1", "condition": "요청 한 줄 요약", "from_turn": 1, "quote": "그 턴 사용자 글에서 그대로 따온 구절",
             "status": "kept", "superseded_by": 0, "evidence": "근거 한 줄"}],
 "forgotten": []}

규칙:
- label은 다음 중 하나만 쓴다: 시작, 구체화, 재정의, 정정, 범위 축소, 문제 제기, 확정, 질문
- response_summary와 last_response_summary는 한국어 90자 안으로 쓴다. 결론과 남은 일을 먼저 쓴다.
- last_response_summary에는 응답이 사용자에게 묻거나 확인을 요청한 내용이 있으면 반드시 넣는다.
- ledger는 사용자가 지금까지 요청한 것(해 달라는 일, 지켜 달라는 조건)을 쌓은 목록이다. 요청 하나에 할 일이 여럿이면 나눈다.
- ledger에 넣지 않는 것: 에이전트가 제안하거나 물은 일, 에이전트가 스스로 정한 계획, '응'·'좋아'·'그대로 둬' 같은 승인·보류 답, 명령이나 시스템이 넣은 지시문. 사용자가 에이전트 제안에 답하며 새로 요구한 내용은 넣는다.
- quote는 from_turn 턴의 '요청:' 글에서 글자 그대로 복사한 짧은 구절이다. 고쳐 쓰거나 응답에서 가져오지 마라.
- status는 마지막 턴의 응답만 보고 정한다: kept(마지막 응답이 이 요청을 반영하거나 지킴), missed(마지막 응답이 이 요청을 빠뜨리거나 어김), unknown(마지막 응답만으로는 알 수 없음), superseded(뒤 요청이 이 요청을 바꾸거나 취소함. superseded_by에 그 턴 번호).
- 요청은 두 종류다. 한 번 하면 끝나는 일(찾아보기, 리뷰, 커밋, 파일 만들기)과 계속 지켜야 하는 조건(형식, 범위, 사용할 모델, 하지 말 것).
- 한 번 하면 끝나는 일: 앞 턴 응답에서 이미 끝냈고 뒤 응답이 되돌리지 않았으면 kept다(근거에 끝낸 턴을 적는다). 아직 하지 않았는데 마지막 응답이 다른 일로 넘어갔으면 missed다.
- 계속 지켜야 하는 조건: 마지막 응답의 결과물이 그 조건과 관련 있을 때만 kept·missed로 판정한다. 관련 없는 응답이면 unknown이다.
- 중간 턴의 응답이 빠뜨렸다가 나중에 챙긴 것은 kept다.
- 추측하지 말고, 근거는 마지막 응답의 문장을 짧게 인용하거나 요약한다.

=== 턴 기록 ===
"""


def build_prompt(turns: list, max_turns: int = MAX_TURNS) -> str:
    """턴 목록을 프롬프트 본문으로 바꾼다. 긴 글은 자르고, 최근 max_turns개만 넣는다.
    마지막 턴은 최종 응답 전체를 길이 제한 없이 넣는다 (요청 29·46)."""
    recent = turns[-max_turns:]
    lines = []
    for k, t in enumerate(recent):
        request = " ".join(t.request.split())[:REQUEST_CUT]
        if k == len(recent) - 1:
            last = (getattr(t, "final_response", "") or t.response or "").strip()
            # 길이와 관계없이 전체를 넣는다. 결론·질문은 끝에 오는 일이 많다 (요청 29·46)
            lines.append(f"[턴 {t.index}] 요청: {request}\n  응답 전체(마지막 턴):\n{last or '(없음)'}")
        else:
            response = " ".join(t.response.split())[:RESPONSE_CUT]
            lines.append(f"[턴 {t.index}] 요청: {request}\n  응답: {response or '(없음)'}")
    return PROMPT_HEAD + "\n".join(lines) + "\n"


def _clip(value, limit=200) -> str:
    return " ".join(str(value or "").split())[:limit]


def _squash(text) -> str:
    return "".join(str(text or "").split())


def parse_result(text: str, turn_indexes: set, requests: dict | None = None) -> dict:
    """모델 출력에서 JSON을 꺼내 검증한다. 잘못된 값은 버리거나 바꾼다 (화면이 깨지지 않게).

    requests(턴 번호 -> 사용자 요청 원문)를 주면, 요청 원장 항목의 quote가 그 턴 사용자 글에 실제로 있는지 확인하고
    없으면 버린다. 에이전트가 꺼낸 일이 사용자 요청으로 섞이지 않게 하는 장치다 (요청 33)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise AnalyzerError("분석 결과에 JSON이 없습니다")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise AnalyzerError(f"분석 결과 JSON이 깨졌습니다: {e}") from e

    if not isinstance(data, dict):
        raise AnalyzerError("분석 결과 형식이 다릅니다")
    turns = []
    for item in data.get("turns", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if index not in turn_indexes:
            continue
        label = item.get("label", "")
        turns.append({
            "index": index,
            "label": label if label in RELATIONS else "",
            "summary": _clip(item.get("summary")),
            "response_summary": _clip(item.get("response_summary"), SUMMARY_CUT),
        })

    ledger = []
    for i, item in enumerate(data.get("ledger", []) or [], start=1):
        if not isinstance(item, dict):
            continue
        status = item.get("status", "unknown")
        try:
            from_turn = int(item.get("from_turn"))
        except (TypeError, ValueError):
            from_turn = 0
        quote = _clip(item.get("quote"))
        if requests is not None:
            q = _squash(quote)
            if from_turn not in requests or len(q) < QUOTE_MIN or q not in _squash(requests[from_turn]):
                continue
        try:
            superseded_by = int(item.get("superseded_by") or 0)
        except (TypeError, ValueError):
            superseded_by = 0
        ledger.append({
            "id": _clip(item.get("id") or f"R{i}", 20),
            "condition": _clip(item.get("condition")),
            "from_turn": from_turn,
            "quote": quote,
            "status": status if status in LEDGER_STATUSES else "unknown",
            "superseded_by": superseded_by,
            "evidence": _clip(item.get("evidence")),
        })

    return {
        "first_goal": _clip(data.get("first_goal")),
        "current_goal": _clip(data.get("current_goal")),
        "turns": turns,
        "last_response_summary": _clip(data.get("last_response_summary"), 300),
        "ledger": ledger,
        "forgotten": [_clip(x) for x in (data.get("forgotten") or [])][:10],
    }


def missed_count(analysis: dict) -> int:
    """① 목록의 수: 요청 기록(기억 관점)이 있으면 남은 것, 없으면 옛 빠짐 (요청 41)."""
    flow = analysis.get("flow") or {}
    if "requests" in flow:
        return sum(1 for r in flow["requests"] if r.get("state") in ("open", "deferred"))
    return sum(1 for c in analysis.get("ledger", []) if c.get("status") == "missed")


def _similar(a: str, b: str) -> float:
    """두 글이 얼마나 비슷한지 (글자 두 개씩 묶은 조각의 겹침, 0~1). 분석기가 같은 뜻을 말만 바꿔 쓰는 일을 걸러 낸다."""
    def grams(x):
        x = "".join(str(x or "").split())
        return {x[i:i + 2] for i in range(max(1, len(x) - 1))}
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else float(a == b)


SAME_THRESHOLD = 0.5   # 이만큼 비슷하면 같은 조건·같은 목표로 본다 (2026-11-10 실제 화면: 말만 바뀌어 '새 빠짐'으로 잘못 나옴)


def diff_analysis(old, new: dict) -> dict:
    """바뀐 것만 (요청 30). 조건 ID와 문장은 분석할 때마다 바뀔 수 있어, 같은 턴에서 나온 비슷한 글은 같은 조건으로 본다."""
    if not old:
        return {}
    old_missed = [c for c in old.get("ledger", []) if c.get("status") == "missed"]
    new_missed = [c for c in new.get("ledger", []) if c.get("status") == "missed"]

    def seen_before(c):
        return any(o.get("from_turn") == c.get("from_turn") and
                   _similar(o.get("condition", ""), c.get("condition", "")) >= SAME_THRESHOLD or
                   _similar(o.get("condition", ""), c.get("condition", "")) >= 0.8
                   for o in old_missed)

    return {
        "missed_before": len(old_missed),
        "missed_after": len(new_missed),
        "new_missed": [c.get("condition", "") for c in new_missed if not seen_before(c)],
        "goal_changed": _similar(old.get("current_goal", ""), new.get("current_goal", "")) < SAME_THRESHOLD,
        "prev_source_ts": old.get("source_ts", ""),
    }


def run_claude(prompt: str, model: str = "", register=None) -> str:
    """claude -p로 한 번 물어본다. 분석기 자신은 기록되지 않도록 표시하고, 저장과 도구는 모두 끈다."""
    env = dict(os.environ, CONTROL_TUI_ANALYZER="1")
    cmd = ["claude", "-p", "--output-format", "json", "--no-session-persistence",
           "--disable-slash-commands", "--tools", ""]
    if model:
        cmd += ["--model", model]
    cmd += ["--", prompt]
    try:
        # 관제 패널의 터미널을 물려받지 않게 떼어 낸다. 물려받으면 ps에 관제 패널 tty의 claude로 보여
        # 관제 자신이 "연결 대기" 세션이나 보낼 수 있는 claude 패널로 잡힌다 (panels.py, SCREEN §8).
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=env, start_new_session=True)
    except OSError as e:
        raise AnalyzerError(f"claude 실행 실패: {type(e).__name__}") from e
    if register:
        register(proc)
    try:
        out, _err = proc.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise AnalyzerError(f"시간 초과 ({TIMEOUT_SECONDS}초)") from None
    finally:
        if register:
            register(None)
    if proc.returncode != 0:
        raise AnalyzerError(f"claude 종료 코드 {proc.returncode}")
    try:
        return json.loads(out).get("result", "")
    except (json.JSONDecodeError, AttributeError) as e:
        raise AnalyzerError("claude 출력을 읽지 못했습니다") from e


FORMAT = 2   # 2 = 요청 원장(사용자 원문 인용, 마지막 응답 기준) + 슬래시 명령 턴 (요청 33·34)


def read_analysis(session_dir: Path):
    """형식이 옛것이면 없는 것으로 본다. 옛 결과는 턴 번호(슬래시 명령 턴이 끼면 밀림)와 원장 뜻이 달라
    새 이름표로 보이면 틀린 말이 된다. 없는 것으로 보면 미판정으로 보이고 다시 분석된다."""
    path = session_dir / "analysis.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("format", 1) < FORMAT:
        return None
    return data


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # 쓰는 도중 화면이 깨진 파일을 읽지 않도록 한 번에 바꾼다


STATUS_FILE = "analysis_status.json"   # 분석 상태를 관제 밖(mod)에서도 읽게 남긴다 (요청 41, R17)


def write_status(session_dir: Path, state: str, turn: int = 0, **extra) -> None:
    """state: queued·running·idle·failed. mod와 관제가 '분석 중...'·'분석 실패'를 보이는 데 쓴다.
    분석기가 관제 밖에서 돌므로(요구 이력 52·53) 실패 이유(error)·시작 시각(since)·프로세스(pid)도 남긴다.
    쓰기에 실패해도 분석은 이어 간다."""
    try:
        data = {"state": state, "turn": turn, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "pid": os.getpid()}
        data.update({k: v for k, v in extra.items() if v not in (None, "")})
        _write_json(Path(session_dir) / STATUS_FILE, data)
    except OSError:
        pass


def read_status(session_dir: Path) -> dict:
    try:
        data = json.loads((Path(session_dir) / STATUS_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_analysis(session_dir: Path, result: dict, source_ts: str, changes: dict | None = None,
                   last_turn: int = 0) -> Path:
    payload = dict(result, format=FORMAT, source_ts=source_ts, last_turn=last_turn, changes=changes or {},
                   analyzed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
    path = session_dir / "analysis.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # 쓰는 도중 화면이 깨진 파일을 읽지 않도록 한 번에 바꾼다
    return path


class Analyzer:
    """한 번에 한 건씩, 고른 세션 먼저 분석한다. 상태를 화면에 알려 준다."""

    def __init__(self, runner=None, model: str = "", max_turns: int = MAX_TURNS,
                 reply_wait: float = REPLY_WAIT_SECONDS, flow_runner=None):
        self.model = model
        self.reply_wait = reply_wait
        self.max_turns = max_turns
        real = lambda prompt: run_claude(prompt, self.model, self._register)  # noqa: E731
        self.runner = runner or real
        # 목표 흐름(요청 40)은 따로 부른다. 실행기를 직접 준 경우(테스트)에는 flow_runner를 줄 때만 켠다.
        self.flow_runner = flow_runner if flow_runner is not None else (real if runner is None else None)
        self._cv = threading.Condition()
        self._jobs: dict = {}        # session_id -> 기다리는 일 (시작 전)
        self._running = None         # 지금 도는 일
        self._started = 0.0          # 지금 도는 일의 시작 시각 (monotonic)
        self._since = ""             # 같은 시각 (UTC 문자열, 상태 파일용)
        self._failed: dict = {}      # (session_id, source_ts) -> (시도 횟수, 마지막 실패 시각)
        self._priority = ""          # 먼저 할 세션 (화면에서 고른 세션)
        self._flow_turn = 0          # 목표 흐름을 지금 이어 적는 턴 (화면의 스켈레톤 자리, 요청 41)
        self._proc = None
        self._stopped = False
        self.last_error: dict = {}   # 세션 -> 마지막 오류 한 줄
        self._thread = threading.Thread(target=self._loop, name="analyzer", daemon=True)
        self._thread.start()

    # ---------- 바깥에서 부르는 것 ----------

    def request(self, session_id: str, session_dir: Path, transcript_path: str, source_ts: str,
                force: bool = False) -> bool:
        """응답 시각(source_ts)에 대한 분석이 없으면 예약한다. 예약했으면 True."""
        if not transcript_path or not source_ts:
            return False
        key = (session_id, source_ts)
        with self._cv:
            if self._stopped:
                return False
            existing = read_analysis(session_dir)  # 잠금 안에서 다시 본다 (막 저장된 결과와 겹치지 않게)
            if existing and existing.get("source_ts") == source_ts and not self._flow_pending(existing):
                return False
            if self._running and self._running["key"] == key:
                return False
            pending = self._jobs.get(session_id)
            if pending and pending["key"] == key:
                return False
            if force:
                self._failed.pop(key, None)
            elif key in self._failed:
                attempts, when = self._failed[key]
                if attempts >= MAX_ATTEMPTS or time.monotonic() - when < RETRY_SECONDS:
                    return False
            # 같은 세션의 옛 요청은 최신 것으로 바꾼다
            self._jobs[session_id] = {"key": key, "dir": Path(session_dir), "transcript": Path(transcript_path)}
            self._cv.notify_all()
        write_status(session_dir, "queued")
        return True

    def _flow_pending(self, analysis: dict) -> bool:
        """요청 체크는 끝났지만 목표 흐름을 아직 마지막 턴까지 이어 적지 못했는지."""
        if self.flow_runner is None:
            return False
        flow = analysis.get("flow") or {}
        return (flow.get("until") or 0) < (analysis.get("last_turn") or 0)

    def prioritize(self, session_id: str) -> None:
        with self._cv:
            self._priority = session_id or ""

    def status(self, session_id: str) -> dict:
        """화면용 상태: running(경과 초) / queued(앞에 몇 건) / failed(이유) / '' (할 일 없음)."""
        with self._cv:
            if self._running and self._running["key"][0] == session_id:
                return {"state": "running", "seconds": int(time.monotonic() - self._started),
                        "source_ts": self._running["key"][1], "turn": self._flow_turn}
            if session_id in self._jobs:
                order = self._order()
                ahead = order.index(session_id) + (1 if self._running else 0)
                return {"state": "queued", "ahead": ahead, "source_ts": self._jobs[session_id]["key"][1]}
            failed = [k for k in self._failed if k[0] == session_id]
            if failed and session_id in self.last_error:
                return {"state": "failed", "error": self.last_error[session_id], "source_ts": failed[-1][1]}
        return {"state": ""}

    def shutdown(self) -> None:
        """관제를 끌 때: 기다리던 분석은 버리고, 도는 claude -p는 멈춘다."""
        with self._cv:
            self._stopped = True
            self._jobs.clear()
            proc = self._proc
            self._cv.notify_all()
        if proc is not None and proc.poll() is None:
            proc.kill()

    def wait_idle(self, timeout: float = 5.0) -> None:
        """테스트용: 기다리는 일과 도는 일이 모두 끝날 때까지 기다린다."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._jobs or self._running:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("분석이 끝나지 않았습니다")
                self._cv.wait(left)

    # ---------- 안쪽 ----------

    def _register(self, proc) -> None:
        with self._cv:
            self._proc = proc
            stopped = self._stopped
        if stopped and proc is not None and proc.poll() is None:
            proc.kill()  # 끄는 중에 막 띄운 claude -p도 멈춘다

    def _order(self) -> list:
        """기다리는 세션 순서: 고른 세션 먼저, 나머지는 응답 시각이 최근인 것부터."""
        ids = sorted(self._jobs, key=lambda s: self._jobs[s]["key"][1], reverse=True)
        if self._priority in self._jobs:
            ids.remove(self._priority)
            ids.insert(0, self._priority)
        return ids

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._jobs and not self._stopped:
                    self._cv.wait()
                if self._stopped:
                    return
                session_id = self._order()[0]
                job = self._jobs.pop(session_id)
                self._running = job
                self._started = time.monotonic()
                self._since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")   # 상태 파일에 남겨 관제 밖에서도 경과 시간을 보인다
            try:
                self._run(job)
            except Exception as e:  # noqa: BLE001 — 어떤 오류에도 분석 스레드가 죽지 않게
                self.last_error[job["key"][0]] = f"분석 오류: {type(e).__name__}"
                with self._cv:
                    attempts, _ = self._failed.get(job["key"], (0, 0.0))
                    self._failed[job["key"]] = (attempts + 1, time.monotonic())
            finally:
                with self._cv:
                    self._running = None
                    self._cv.notify_all()

    def _advance_flow(self, session_dir: Path, turns: list) -> None:
        """목표 흐름을 새 턴만큼 이어 적는다 (요청 40, BUILD_PLAN §4.3). 한 턴마다 저장해 화면이 따라오게 한다."""
        from control_tui import flow as flow_mod
        data = read_analysis(session_dir) or {}
        flow = flow_mod.migrate(data.get("flow"), turns)   # 형식 1은 버리지 않고 옮겨 담는다 (요구 이력 44)
        if not flow_mod.valid_for(flow, turns):
            flow = flow_mod.empty()  # 형식이 다르거나 압축·되돌리기로 기록이 바뀌었으면 처음부터
        rebuilt = not flow.get("steps")
        before = len(flow_mod.shifts(flow))
        left_before = {r["id"] for r in flow_mod.remaining(flow)}
        todo = [t for t in turns if t.index > (flow.get("until") or 0)][:FLOW_STEPS_PER_JOB]
        for t in todo:
            if self._stopped:
                return
            self._flow_turn = t.index
            write_status(session_dir, "running", t.index, since=self._since)
            flow = flow_mod.advance(flow, turns, t, self.flow_runner)
            data = read_analysis(session_dir) or data
            data["flow"] = flow
            if flow.get("current_goal", {}).get("text"):
                data["first_goal"] = flow["first_goal"].get("text", data.get("first_goal", ""))
                data["current_goal"] = flow["current_goal"]["text"]
            if not rebuilt:
                left = flow_mod.remaining(flow)
                data["changes"] = {"missed_before": len(left_before), "missed_after": len(left),
                                   "new_missed": [r["summary"] for r in left if r["id"] not in left_before],
                                   "goal_changed": len(flow_mod.shifts(flow)) > before,  # 목표 바뀜은 주제 이동이 있을 때만
                                   "prev_source_ts": data.get("source_ts", "")}
                data["analyzed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            _write_json(session_dir / "analysis.json", data)

    def _read_turns(self, transcript: Path, source_ts: str) -> list:
        """응답 시각까지의 턴. 마지막 턴에 글이 아직 없으면 기록에 적힐 때까지 잠깐 기다린다.
        Claude Code는 Stop 훅을 부른 뒤에 마지막 글을 적는다 (실험, SCREEN §8). 바로 읽으면
        분석기가 '마지막 응답이 없다'고 판정한다. 도구로 끝난 턴(중단)은 기다려도 글이 없으니 시간만 지나고 그대로 간다."""
        deadline = time.monotonic() + self.reply_wait
        while True:
            turns = parse_turns(transcript, until_ts=source_ts) if transcript.exists() else []
            last = turns[-1] if turns else None
            if last is not None and (last.final_response or "").strip():
                return turns
            if self._stopped or time.monotonic() >= deadline:
                return turns
            time.sleep(REPLY_POLL_SECONDS)

    def _run(self, job) -> None:
        session_id, source_ts = job["key"]
        try:
            # 이 응답 시각까지 적힌 기록만 본다 (기다리는 사이 생긴 턴·응답·도구 결과는 섞지 않는다)
            turns = self._read_turns(job["transcript"], source_ts)
            if not turns:
                raise AnalyzerError("턴 기록이 없어 분석하지 않았습니다")
            old = read_analysis(job["dir"])
            if self.flow_runner is not None:
                # 요청 기록도 목표 흐름의 한 턴 분석에 들어 있으므로 옛 요청 체크 호출은 하지 않는다 (요청 41, Phase 4c)
                if not (old and old.get("source_ts") == source_ts):
                    base = {"first_goal": (old or {}).get("first_goal", ""), "current_goal": (old or {}).get("current_goal", ""),
                            "turns": [], "last_response_summary": "", "ledger": [], "forgotten": []}
                    if old and old.get("flow"):
                        base["flow"] = old["flow"]
                    write_analysis(job["dir"], base, source_ts, {}, turns[-1].index)
                write_status(job["dir"], "running", turns[-1].index, since=self._since, source_ts=source_ts)
                try:
                    self._advance_flow(job["dir"], turns)
                finally:
                    self._flow_turn = 0
                    write_status(job["dir"], "idle")
                self.last_error.pop(session_id, None)
                with self._cv:
                    self._failed.pop(job["key"], None)
                return
            if not (old and old.get("source_ts") == source_ts):  # 요청 체크가 이미 끝났으면 목표 흐름만 이어 적는다
                prompt = build_prompt(turns, self.max_turns)
                text = self.runner(prompt)
                if self._stopped:
                    return
                result = parse_result(text, {t.index for t in turns}, {t.index: t.request for t in turns})
                if old and old.get("flow"):
                    result["flow"] = old["flow"]  # 목표 흐름은 이어 적는 것이라 그대로 넘긴다
                    if (old["flow"].get("current_goal") or {}).get("text"):  # 목표 글도 흐름 것을 쓴다 (매번 다시 쓰지 않게)
                        result["first_goal"] = old["flow"]["first_goal"].get("text", result["first_goal"])
                        result["current_goal"] = old["flow"]["current_goal"]["text"]
                write_analysis(job["dir"], result, source_ts, diff_analysis(old, result), turns[-1].index)
            self.last_error.pop(session_id, None)
            with self._cv:
                self._failed.pop(job["key"], None)
        except (AnalyzerError, OSError) as e:
            if self._stopped:
                return
            self.last_error[session_id] = str(e)[:120]
            with self._cv:
                attempts, _ = self._failed.get(job["key"], (0, 0.0))
                self._failed[job["key"]] = (attempts + 1, time.monotonic())
            write_status(job["dir"], "failed", error=str(e)[:120], source_ts=source_ts, attempts=attempts + 1)
