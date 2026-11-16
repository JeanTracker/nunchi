#!/usr/bin/env python3
"""모든 Claude Code 훅이 부르는 단일 기록기 (BUILD_PLAN §2.1, §2.2).

- Claude Code가 stdin으로 준 JSON을 한 줄로 줄여 events.jsonl에 덧붙인다.
- 항상 exit 0. 실패는 errors.log에만 남긴다. 세션을 절대 막지 않는다.
- CONTROL_TUI_ANALYZER=1 이면 아무것도 기록하지 않는다 (분석기 재귀 방지).
- 기록 위치는 CONTROL_TUI_HOME 환경변수로 바꿀 수 있다 (기본 ~/.claude-control).
"""

import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TRUNC = 500


def base_dir() -> Path:
    return Path(os.environ.get("CONTROL_TUI_HOME", Path.home() / ".claude-control"))


def log_error(msg: str) -> None:
    try:
        d = base_dir()
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(d / "errors.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
    except Exception:
        pass


def cut(value):
    """긴 값은 앞 500자로 자른다. 문자열이 아니면 JSON 문자열로 바꾼 뒤 자른다."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:TRUNC]


def build_record(payload: dict, env: dict) -> dict:
    event = payload.get("hook_event_name", "")
    data = {}
    # 도구는 세션 상태(작업·허락·질문) 판단에 쓰는 이름과 호출 ID만 남긴다. 입력·결과·오류는 저장하지 않는다 (요구 이력 48)
    for key in ("prompt", "tool_name", "tool_use_id", "notification_type",
                "trigger", "compact_summary", "source", "permission_mode"):
        if key in payload and payload[key] is not None:
            data[key] = cut(payload[key]) if key in ("prompt", "compact_summary") else payload[key]
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "session_id": payload.get("session_id", ""),
        "event": event,
        "cwd": payload.get("cwd", ""),
        "transcript_path": payload.get("transcript_path", ""),
        "iterm_session_id": env.get("ITERM_SESSION_ID", ""),
        "data": data,
    }


def save_compact_copy(record: dict) -> None:
    """PreCompact 때 transcript 사본을 남긴다 (R7 비교용, BUILD_PLAN §2.2)."""
    src = record.get("transcript_path")
    if record.get("event") != "PreCompact" or not src or not os.path.exists(src):
        return
    session_dir = base_dir() / "sessions" / record["session_id"]
    n = 1
    while (session_dir / f"compact-{n}.jsonl").exists():
        n += 1
    shutil.copyfile(src, session_dir / f"compact-{n}.jsonl")


def request_analysis(record: dict) -> None:
    """응답이 끝나면(Stop) 분석 대상 세션의 분석을 대기열에 넣고 분석기를 깨운다 (요구 이력 52·53, BUILD_PLAN §4.7).
    대상: 세션에서 /nunchi로 켠 세션(세션 폴더의 want), 또는 설정 analyze_scope가 all. off·manual이면 하지 않는다.
    분석은 하지 않고 바로 끝난다. 분석기는 떼어 낸 백그라운드 프로세스로 돈다."""
    if record.get("event") != "Stop" or os.environ.get("CONTROL_TUI_ANALYZE", "1") == "0":
        return
    home = base_dir()
    sid = record["session_id"]
    try:
        cfg = json.loads((home / "config.json").read_text(encoding="utf-8"))
        cfg = cfg if isinstance(cfg, dict) else {}
    except (OSError, json.JSONDecodeError):
        cfg = {}
    if cfg.get("analyze_scope", "selected") == "off" or cfg.get("analyze_when", "auto") == "manual":
        return
    if cfg.get("analyze_scope") != "all" and not (home / "sessions" / sid / "want").exists():
        return
    if not record.get("transcript_path"):
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from control_tui import worker
    worker.enqueue(home, sid, record["transcript_path"], record["ts"])
    try:
        workers = int(cfg.get("analyze_workers", 1))
    except (TypeError, ValueError):
        workers = 1
    worker.wake(home, workers)


def main() -> int:
    try:
        if os.environ.get("CONTROL_TUI_ANALYZER") == "1":
            return 0
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not payload.get("session_id"):
            log_error("session_id 없음")
            return 0
        record = build_record(payload, dict(os.environ))
        session_dir = base_dir() / "sessions" / record["session_id"]
        session_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        fd = os.open(session_dir / "events.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        save_compact_copy(record)
        request_analysis(record)
    except Exception as e:  # noqa: BLE001
        log_error(f"emit 실패: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    t0 = time.perf_counter()
    code = main()
    if os.environ.get("CONTROL_TUI_TIMING") == "1":
        log_error(f"elapsed_ms={(time.perf_counter() - t0) * 1000:.1f}")
    sys.exit(code)
