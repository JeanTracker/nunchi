"""iTerm2 어댑터 (BUILD_PLAN §5.1, §3.4와 같은 방식: osascript).

- 대상 패널은 훅이 기록한 iTerm 세션 UUID로 찾는다.
- 글자는 AppleScript 인자로 넘긴다. 스크립트 본문에 끼워 넣지 않으므로
  입력 글자에 따옴표나 역슬래시가 있어도 명령이 바뀌지 않는다.
- 이 파일의 실제 전송은 실험 전까지 검증하지 않았다 (실제 세션에는 아직 보내지 않는다).
"""

import subprocess

from control_tui.adapters.terminal_base import TerminalError

SEND_SCRIPT = """
on run argv
    set targetId to item 1 of argv
    set msg to item 2 of argv
    set withEnter to item 3 of argv
    tell application "iTerm2"
        repeat with w in windows
            repeat with t in tabs of w
                repeat with s in sessions of t
                    if (id of s) is targetId then
                        tell s to write text msg newline NO
                        if withEnter is "1" then
                            -- Enter는 줄바꿈 글자가 아니라 캐리지 리턴 글자(ASCII 13)로 보낸다 (BUILD_PLAN §5.1)
                            tell s to write text (ASCII character 13) newline NO
                        end if
                        return "ok"
                    end if
                end repeat
            end repeat
        end repeat
    end tell
    return "missing"
end run
"""


SCREEN_SCRIPT = """
on run argv
    set targetId to item 1 of argv
    tell application "iTerm2"
        repeat with w in windows
            repeat with t in tabs of w
                repeat with s in sessions of t
                    if (id of s) is targetId then return contents of s
                end repeat
            end repeat
        end repeat
    end tell
    return ""
end run
"""


FOCUS_SCRIPT = """
on run argv
    set targetId to item 1 of argv
    tell application "iTerm2"
        repeat with w in windows
            repeat with t in tabs of w
                repeat with s in sessions of t
                    if (id of s) is targetId then
                        select w
                        tell t to select
                        tell s to select
                        activate
                        return "ok"
                    end if
                end repeat
            end repeat
        end repeat
    end tell
    return "missing"
end run
"""


def _osascript(args: list, script: str = SEND_SCRIPT) -> str:
    try:
        result = subprocess.run(["osascript", "-", *args], input=script,
                                capture_output=True, text=True, timeout=8)
    except subprocess.TimeoutExpired:
        raise TerminalError("iTerm이 8초 안에 답하지 않았습니다(창에 대화상자가 떠 있는지 보세요)") from None
    except OSError as e:   # osascript가 없거나 실행할 수 없음
        raise TerminalError(f"osascript를 실행하지 못했습니다: {e}") from None
    if result.returncode != 0:
        raise TerminalError(result.stderr.strip() or "osascript 실패")
    return result.stdout.strip()


class ITerm2Adapter:
    def send_text(self, target_id: str, text: str, enter: bool = True) -> None:
        if not target_id:
            raise TerminalError("이 세션은 iTerm 패널과 짝이 없어 보낼 수 없습니다.")
        # 여러 줄 글은 붙여넣기 표시(ESC [200~ ... ESC [201~)로 감싼다.
        # 그래야 줄바꿈이 줄마다 제출되지 않고 입력창 안에 들어간다 (확인 전, BUILD_PLAN §5.1)
        payload = f"\x1b[200~{text}\x1b[201~" if "\n" in text else text
        out = _osascript([target_id, payload, "1" if enter else "0"])
        if out != "ok":
            raise TerminalError("패널을 찾지 못했습니다. iTerm2에서 패널이 닫혔는지 보세요.")

    def screen_text(self, target_id: str) -> str:
        """패널에 지금 보이는 글. 질문 창이 아직 떠 있는지 보내기 전에 확인할 때 쓴다 (요청 39)."""
        if not target_id:
            raise TerminalError("이 세션은 iTerm 패널과 짝이 없습니다.")
        return _osascript([target_id], SCREEN_SCRIPT)

    def focus(self, target_id: str) -> None:
        """그 패널의 창·탭·패널을 앞으로 가져온다 (요구 이력 56, SCREEN §8 2026-11-16 실험)."""
        if not target_id:
            raise TerminalError("이 세션은 iTerm 패널과 짝이 없습니다.")
        if _osascript([target_id], FOCUS_SCRIPT) != "ok":
            raise TerminalError("패널을 찾지 못했습니다. iTerm2에서 패널이 닫혔는지 보세요.")
