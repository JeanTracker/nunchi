"""맥 클립보드 읽기·쓰기 (BUILD_PLAN §5.1.1).

Textual은 터미널 제어 문자(OSC 52)로만 클립보드에 쓴다. iTerm2가 앱의 클립보드 접근을
허락하지 않으면 그 쓰기는 버려진다(SCREEN §8, 2026-11-10 이 맥에서 확인). 그래서 관제는
같은 맥에서 돌 때 pbcopy·pbpaste로 직접 읽고 쓴다.
"""

import os
import shutil
import subprocess

TIMEOUT = 2.0


def _env() -> dict:
    # 로캘이 UTF-8이 아니면 pbcopy·pbpaste가 한글을 깨뜨린다
    return {**os.environ, "LC_CTYPE": "UTF-8", "LANG": os.environ.get("LANG") or "en_US.UTF-8"}


class MacClipboard:
    def available(self) -> bool:
        return shutil.which("pbcopy") is not None and shutil.which("pbpaste") is not None

    def write(self, text: str) -> bool:
        """맥 클립보드에 쓴다. 썼으면 True."""
        if not self.available():
            return False
        try:
            r = subprocess.run(["pbcopy"], input=text, text=True, encoding="utf-8",
                               env=_env(), timeout=TIMEOUT, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            return False
        return r.returncode == 0

    def read(self) -> str | None:
        """맥 클립보드 글. 읽지 못하면 None."""
        if not self.available():
            return None
        try:
            r = subprocess.run(["pbpaste"], text=True, encoding="utf-8",
                               env=_env(), timeout=TIMEOUT, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout if r.returncode == 0 else None
