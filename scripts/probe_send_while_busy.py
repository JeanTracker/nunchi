#!/usr/bin/env python3
"""BUILD_PLAN §6 확인 1: 일하는 중인 패널에 글을 보내면 어떻게 되나.

대기열로 들어가는지, 끼어드는지, 무시되는지 본다.

안전 장치 (실험 세션 전용):
- 기본은 계획만 출력한다. --send를 줘야 실제로 보낸다.
- 대상은 --panel(iTerm 패널 UUID)로만 받는다. 아무 세션도 고르지 않는다.
- 보내기 전에 그 패널에 claude가 떠 있는지 확인한다.
- 실험용으로 연 세션의 UUID만 넣는다. 사용자의 라이브 세션 UUID에는 쓰지 않는다.

사용법:
    python3 scripts/probe_send_while_busy.py --panel <UUID>            # 계획만 보기
    python3 scripts/probe_send_while_busy.py --panel <UUID> --send     # 실제 전송
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from control_tui import panels  # noqa: E402
from control_tui.adapters.iterm2_adapter import ITerm2Adapter  # noqa: E402

# 첫 글: 오래 걸리는 일을 시킨다. 둘째 글: 일하는 도중에 보낸다.
FIRST = "1부터 40까지 한 줄에 하나씩 천천히 세어줘"
SECOND = "[실험] 이 글은 끼어들기 확인용입니다. 하던 일을 계속하고, 답은 마지막에 한 줄로만 주세요."


def plan(panel_id: str) -> list:
    return [
        f"1) 패널 {panel_id}에 첫 글 보내기: {FIRST}",
        "2) 몇 초 기다려 Claude가 일을 시작하게 하기",
        f"3) 일하는 중에 둘째 글 보내기: {SECOND}",
        "4) 확인: 세션 기록(events.jsonl)과 transcript에서 둘째 글이 어디에 찍혔는지 보기",
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="일하는 중 입력 실험 (§6 확인 1)")
    parser.add_argument("--panel", required=True, help="실험용 iTerm 패널 UUID")
    parser.add_argument("--send", action="store_true", help="실제로 보낸다 (없으면 계획만 출력)")
    parser.add_argument("--wait", type=float, default=5.0, help="첫 글 뒤 기다릴 초")
    args = parser.parse_args(argv)

    if args.panel not in panels.claude_panel_ids():
        print("중단: 그 패널에 claude가 떠 있지 않습니다. 실험 세션 UUID를 확인하세요.")
        return 2

    for line in plan(args.panel):
        print(line)
    if not args.send:
        print("계획만 출력했습니다 (dry-run). 실제로 보내려면 --send를 주세요.")
        return 0

    terminal = ITerm2Adapter()
    terminal.send_text(args.panel, FIRST)
    time.sleep(args.wait)
    terminal.send_text(args.panel, SECOND)
    print("두 글을 보냈습니다. 결과는 세션 기록과 transcript에서 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
