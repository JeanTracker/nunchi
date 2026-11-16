"""터미널 어댑터의 공통 모양 (BUILD_PLAN §5.1).

구현은 패널 ID(UUID)로 대상을 찾는다. 지금은 입력 보내기만 필요하다.
패널 포커스 이동(원문 보기 "터미널 창" 옵션)은 그 기능을 만들 때 추가한다.
"""

from typing import Protocol


class TerminalError(RuntimeError):
    """패널을 못 찾았거나 터미널 명령이 실패했을 때."""


class TerminalAdapter(Protocol):
    def send_text(self, target_id: str, text: str, enter: bool = True) -> None:
        """패널에 글자를 친다. enter=True이면 Enter까지 누른 것과 같다."""
        ...

    def screen_text(self, target_id: str) -> str:
        """패널에 지금 보이는 글. 읽을 수 없는 어댑터는 이 메서드를 두지 않는다 (요청 39)."""
        ...
