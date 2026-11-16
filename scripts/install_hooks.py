#!/usr/bin/env python3
"""~/.claude/settings.json에 관제 훅을 병합한다 (BUILD_PLAN §2.2, §2.3, §7 Phase 1).

기본은 미리보기다. 파일을 바꾸지 않고 바뀔 내용을 diff로 보여준다.
실제로 쓰려면 --apply 를 준다. 쓰기 전에 항상 백업을 만든다.
사용자 허락 없이 --apply 를 실행하지 않는다 (CLAUDE.md 작업 규칙 6).

    python3 scripts/install_hooks.py                  # 미리보기
    python3 scripts/install_hooks.py --apply          # 백업 후 쓰기
    python3 scripts/install_hooks.py --settings PATH  # 다른 설정 파일 (테스트용)
    python3 scripts/install_hooks.py --remove         # 우리 훅만 빼는 미리보기 (--apply로 쓰기)
    python3 scripts/install_hooks.py --check          # diff만 보이고, 바뀔 게 있으면 종료 코드 1
    python3 scripts/install_hooks.py --plugin         # 플러그인이 훅을 맡을 때: 옛 훅(모든 폴더)을 빼고 상태 표시줄만 둔다

훅은 플러그인(저장소 맨 위 hooks/hooks.json)이 등록한다 (요구 이력 63, BUILD_PLAN §4.12).
settings.json에 훅을 넣는 기본 동작은 플러그인 없이 쓸 때를 위해 남겨 둔다.
"""

import argparse
import copy
import difflib
import json
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMIT = ROOT / "hooks" / "emit.py"
STATUSLINE = ROOT / "hooks" / "statusline.py"

# SubagentStart/SubagentStop은 등록하지 않는다 (R14, BUILD_PLAN §2.2).
EVENTS = [
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PostToolUseFailure", "Stop", "Notification", "PreCompact", "PostCompact",
]
MARK = "control_tui/hooks/emit.py"  # 우리 훅을 알아보는 표식 (경로 끝부분)


ORIG_ENV = "CONTROL_TUI_ORIG_STATUSLINE"


def emit_command() -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(EMIT))}"


def statusline_command() -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(STATUSLINE))}"


def is_ours(command: str) -> bool:
    return "hooks/emit.py" in command and str(ROOT) in command


def is_our_statusline(command: str) -> bool:
    return "hooks/statusline.py" in command and str(ROOT) in command


def is_settings_emit(command: str) -> bool:
    """settings.json에 넣은 관제 훅이면 폴더와 관계없이 참. 플러그인 훅(CLAUDE_PLUGIN_ROOT)은 settings.json에 오지 않는다."""
    return "hooks/emit.py" in command and "CLAUDE_PLUGIN_ROOT" not in command


def other_installs(settings: dict) -> list:
    """다른 폴더(예: 개발 폴더와 설치 폴더)에서 등록한 관제 훅. 둘 다 있으면 기록이 두 번 남는다."""
    found = []
    for groups in (settings.get("hooks") or {}).values():
        for g in groups if isinstance(groups, list) else []:
            for h in g.get("hooks", []) if isinstance(g, dict) else []:
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                if "hooks/emit.py" in cmd and not is_ours(cmd) and cmd not in found:
                    found.append(cmd)
    return found


def merge_hooks(settings: dict) -> dict:
    out = copy.deepcopy(settings)
    hooks = out.setdefault("hooks", {})
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        already = any(
            is_ours(h.get("command", ""))
            for g in groups for h in g.get("hooks", [])
        )
        if not already:
            groups.append({"hooks": [{"type": "command", "command": emit_command()}]})
    return out


def merge_statusline(settings: dict) -> dict:
    out = copy.deepcopy(settings)
    current = out.get("statusLine", {}) or {}
    cmd = current.get("command", "")
    if "hooks/statusline.py" in cmd:
        return out  # 이미 우리 것
    wrapped = statusline_command()
    if cmd:
        wrapped = f"{ORIG_ENV}={shlex.quote(cmd)} {wrapped}"
    out["statusLine"] = {**current, "type": "command", "command": wrapped}
    return out


def build_new(settings: dict) -> dict:
    return merge_statusline(merge_hooks(settings))


def remove_hooks(settings: dict, match=is_ours) -> dict:
    """우리 훅 항목만 뺀다(match가 참인 명령). 우리 것만 들어 있던 그룹·이벤트·hooks 키는 함께 정리한다."""
    out = copy.deepcopy(settings)
    hooks = out.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept = []
        for g in groups:
            items = g.get("hooks") if isinstance(g, dict) else None
            if not isinstance(items, list) or not items:
                kept.append(g)
                continue
            rest = [h for h in items if not (isinstance(h, dict) and match(h.get("command", "")))]
            if rest:
                kept.append({**g, "hooks": rest})
        if kept:
            hooks[event] = kept
        elif groups:
            del hooks[event]
    if not hooks and settings.get("hooks"):
        del out["hooks"]
    return out


def remove_statusline(settings: dict) -> tuple:
    """감싸기 전의 상태 표시줄로 되돌린다. 모양이 예상과 다르면 손대지 않고 경고를 돌려준다."""
    out = copy.deepcopy(settings)
    current = out.get("statusLine")
    cmd = current.get("command", "") if isinstance(current, dict) else ""
    if not is_our_statusline(cmd):
        return out, ""
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = []
    orig = None
    if tokens and tokens[0].startswith(ORIG_ENV + "="):
        orig = tokens[0].split("=", 1)[1]
        tokens = tokens[1:]
    if len(tokens) != 2 or not tokens[1].endswith("hooks/statusline.py"):
        return out, f"statusLine 모양이 예상과 달라 그대로 둡니다. 직접 확인하세요: {cmd}"
    if orig:
        out["statusLine"] = {**current, "command": orig}
    else:
        del out["statusLine"]
    return out, ""


def build_plugin_mode(settings: dict) -> dict:
    """플러그인이 훅을 맡는다: settings.json의 관제 훅은 어느 폴더 것이든 빼고(두 번 기록 방지), 상태 표시줄 감싸기는 둔다.
    상태 표시줄은 mod가 컨텍스트 사용률을 기록하게 되면 없앤다 (BUILD_PLAN §4.12)."""
    return merge_statusline(remove_hooks(settings, match=is_settings_emit))


def build_removed(settings: dict) -> tuple:
    return remove_statusline(remove_hooks(settings))


def show_diff(old_text: str, new_text: str, name: str) -> str:
    return "".join(difflib.unified_diff(
        old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
        fromfile=f"{name} (지금)", tofile=f"{name} (바뀐 뒤)"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", default=str(Path.home() / ".claude" / "settings.json"))
    ap.add_argument("--apply", action="store_true", help="실제로 파일을 쓴다 (백업 후)")
    ap.add_argument("--remove", action="store_true", help="등록 대신 우리 훅과 상태 표시줄을 뺀다")
    ap.add_argument("--plugin", action="store_true",
                    help="훅은 플러그인이 맡는다: settings.json의 관제 훅(모든 폴더)을 빼고 상태 표시줄만 둔다")
    ap.add_argument("--check", action="store_true",
                    help="diff만 보이고 쓰지 않는다. 바뀔 내용이 있으면 종료 코드 1")
    args = ap.parse_args()

    path = Path(args.settings)
    if not path.exists() and args.remove:
        print(f"{path} 가 없습니다. 지울 내용이 없습니다.")
        return 0
    old_text = path.read_text(encoding="utf-8") if path.exists() else "{}\n"
    old = json.loads(old_text)
    if args.remove:
        new, warning = build_removed(old)
    elif args.plugin:
        new, warning = build_plugin_mode(old), ""
        others = other_installs(old)
        if others:
            warning = "다른 폴더에서 등록한 관제 훅도 함께 뺍니다 (플러그인 훅과 겹치면 기록이 두 번 남습니다):\n  " + "\n  ".join(others)
    else:
        new, warning = build_new(old), ""
        others = other_installs(old)
        if others:
            warning = ("다른 폴더에서 등록한 관제 훅이 이미 있습니다. 둘 다 두면 기록이 두 번 남습니다. "
                       "그 폴더에서 --remove로 먼저 빼세요:\n  " + "\n  ".join(others))
    if warning:
        print(f"경고: {warning}", file=sys.stderr)
    new_text = json.dumps(new, ensure_ascii=False, indent=2) + "\n"

    if new == old:
        print("지울 내용이 없습니다." if args.remove else "바뀔 내용이 없습니다. 이미 설치되어 있습니다.")
        return 0

    print(show_diff(old_text, new_text, str(path)) or "(차이 없음)")
    if args.check:
        return 1
    if not args.apply:
        print("\n미리보기입니다. 아무것도 바꾸지 않았습니다. 적용하려면 --apply 를 주세요.")
        return 0

    stamp = f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}"
    backup, n = path.with_name(stamp), 1
    while backup.exists():   # 같은 초에 두 번 바꾸면 앞 백업(원본)을 덮어쓰지 않는다
        backup, n = path.with_name(f"{stamp}-{n}"), n + 1
    if path.exists():
        shutil.copy2(path, backup)
        print(f"백업: {backup}")
    path.write_text(new_text, encoding="utf-8")
    print(f"적용 완료: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
