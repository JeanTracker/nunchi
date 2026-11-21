#!/usr/bin/env python3
"""Display one Codex launch's Nunchi analysis in a separate terminal pane."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID


def read_json(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def render(home, run):
    try:
        sid = (run / "session-id").read_text().strip()
    except FileNotFoundError:
        return "눈치 · 세션 연결 대기"
    if str(UUID(sid)) != sid:
        raise ValueError("invalid session identifier")
    folder = home / "sessions" / sid
    data = read_json(folder / "analysis.json")
    status = read_json(folder / "analysis_status.json")
    flow = data.get("flow", {})
    lines = ["눈치 · " + sid[:8] + "…" + sid[-6:]]
    state = status.get("state")
    if state in ("queued", "running", "failed"):
        lines.append({"queued": "분석 대기", "running": "분석 중", "failed": "분석 실패"}[state])
    if not flow:
        if len(lines) == 1:
            lines.append("눈치 켜짐 · 다음 응답이 끝나면 분석합니다")
        return "\n".join(lines)
    basis = flow.get("until", 0)
    lines.append(f"#{basis} 응답까지 반영")
    steps = [step for step in flow.get("steps", []) if step.get("grounded")]
    decision_labels = {}
    decisions = []
    for step in steps:
        entries = step.get("decisions", [])
        for i, decision in enumerate(entries, 1):
            turn = step["index"]
            key = decision.get("id") or f"D{turn}-{i}"
            decision_labels[key] = f"#{turn}-{i}" if len(entries) > 1 else f"#{turn}"
            decisions.append((key, decision, turn))
    replaced = {old for _, d, _ in decisions for old in d.get("replaces", [])}
    active = [(key, d) for key, d, _ in decisions if key not in replaced]
    checks = {c["id"]: c for step in steps for c in step.get("checks", [])}
    warnings = {key: checks[key] for key, _ in active
                if key in checks and checks[key].get("kind") != "고침"}
    marks = {"addressed": "✔", "in_progress": "◐", "deferred": "⊘",
             "open": "○", "no_result": "◇"}
    requests = flow.get("requests", [])
    last = next((step for step in steps if step["index"] == basis), {})
    handled = [f"⚠ 열린 빠뜨림 {len(warnings)}"] if warnings else []
    for check in last.get("checks", []):
        label = decision_labels.get(check["id"], "").strip()
        kind = check["kind"]
        mark = "✔" if kind == "고침" else "⚠"
        detail = f" · {check['what']}" if check.get("what") else ""
        handled.append(f"{mark} 결정 {label} {kind}{detail}")
    changed_quotes = set()
    for _, decision, turn in decisions:
        if turn != basis:
            continue
        for old in decision.get("replaces", []):
            label = decision_labels.get(old, "").strip()
            before, after = decision.get("from"), decision.get("to")
            change = f"{before} → {after}" if before and after else decision.get("text", "")
            handled.append(f"✔ 결정 {label} 바뀜 · {change}")
            if decision.get("quote"):
                changed_quotes.add(decision["quote"])
    for request in requests:
        mark = marks.get(request.get("state"))
        if (mark and request.get("summary") and request.get("quote") not in changed_quotes
                and basis in (request.get("from_turn"), request.get("by_turn"))):
            handled.append(f"{mark} {request['summary']}")
    if not handled and last.get("agent_summary"):
        handled.append(f"· {last['agent_summary']}")

    # Use the Claude panel's section names and request states.
    groups = [
        ("목표", [f"· {goal}"] if (goal := flow.get("current_goal", {}).get("text")) else []),
        ("결정 사항", [f"{'⚠' if key in warnings else '✔'} {d['text']}  {decision_labels[key]}"
                    for key, d in reversed(active) if d.get("text")]),
        (f"처리 결과 #{basis}", handled),
        ("에이전트 질문", [f"· {q['summary']}" for q in flow.get("asks", [])
                      if q.get("summary") and q.get("state") not in ("answered", "closed")] or ["없음"]),
        ("남은 요청", [f"{marks[r['state']]} {r['summary']}" for r in requests
                   if r.get("summary") and r.get("state") in ("open", "in_progress", "deferred")] or ["없음"]),
        ("알려진 문제", [f"◇ {r['summary']}" for r in requests
                    if r.get("summary") and r.get("state") == "no_result"]),
    ]
    for label, items in groups:
        if items:
            lines.extend(["", label, *items])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    home = Path(os.getenv("CONTROL_TUI_HOME", str(Path.home() / ".claude-control")))
    previous = None
    while True:
        try:
            frame = render(home, args.run)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            frame = "눈치 · 세션 결과를 읽을 수 없습니다."
        frame = "".join(c for c in frame if c.isprintable() or c == "\n")
        if frame != previous:
            if sys.stdout.isatty() and not args.once:
                sys.stdout.write("\033[H\033[2J")
            print(frame, flush=True)
            previous = frame
        if args.once:
            return
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
