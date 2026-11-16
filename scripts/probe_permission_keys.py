#!/usr/bin/env python3
"""BUILD_PLAN §6 확인 2: 허락 창에 보낼 안전한 키 (y/n 대신 쓸 것이 있나).

실험 순서:
1) 실험용 세션에서 허락이 필요한 명령을 직접 시켜 허락 창을 띄운다.
2) 이 스크립트로 키 하나를 보내고, 결과를 본다.

안전 장치 (실험 세션 전용):
- 기본은 계획만 출력한다. --send와 --confirm-prompt-open을 함께 줘야 보낸다.
- --confirm-prompt-open은 "허락 창이 지금 떠 있다"는 사람의 확인이다.
- 키는 y 또는 n만 받는다. Enter는 보내지 않는다.
- 대상은 --panel(실험용 패널 UUID)로만 받는다.

사용법:
    python3 scripts/probe_permission_keys.py --panel <UUID> --key y
    python3 scripts/probe_permission_keys.py --panel <UUID> --key y --send --confirm-prompt-open
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from control_tui import panels  # noqa: E402
from control_tui.adapters.iterm2_adapter import ITerm2Adapter  # noqa: E402

ALLOWED_KEYS = ("y", "n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="허락 창 키 실험 (§6 확인 2)")
    parser.add_argument("--panel", required=True, help="실험용 iTerm 패널 UUID")
    parser.add_argument("--key", required=True, choices=ALLOWED_KEYS)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--confirm-prompt-open", action="store_true",
                        help="허락 창이 지금 떠 있다고 사람이 확인했다")
    args = parser.parse_args(argv)

    if args.panel not in panels.claude_panel_ids():
        print("중단: 그 패널에 claude가 떠 있지 않습니다. 실험 세션 UUID를 확인하세요.")
        return 2

    print(f"계획: 패널 {args.panel}에 키 '{args.key}'만 보냅니다 (Enter 없이).")
    if not args.send:
        print("계획만 출력했습니다 (dry-run). 보내려면 --send와 --confirm-prompt-open을 함께 주세요.")
        return 0
    if not args.confirm_prompt_open:
        print("중단: 허락 창이 떠 있는지 확인하지 않았습니다. --confirm-prompt-open을 주세요.")
        return 2

    ITerm2Adapter().send_text(args.panel, args.key, enter=False)
    print(f"키 '{args.key}'를 보냈습니다. 허락 창이 어떻게 바뀌었는지 화면에서 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
