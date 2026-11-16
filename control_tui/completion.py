"""③ 입력줄의 / 자동완성 목록 (내장 명령 + 스킬 + 명령 파일).

- 내장 명령: 설치된 Claude Code 2.1.319의 명령 이름과 설명을 기준으로 골랐다.
  공식 명령 목록은 검색으로 확인하지 못했다. Claude Code 버전이 바뀌면 이 목록도 점검한다.
- 스킬: ~/.claude/skills/<이름>/SKILL.md, 세션 폴더의 .claude/skills/<이름>/SKILL.md
- 명령 파일: ~/.claude/commands/*.md, 세션 폴더의 .claude/commands/*.md
  (플러그인이 제공하는 스킬은 위치를 아직 확인하지 않아 목록에 없다)
"""

import os
import re
import subprocess
from pathlib import Path

# (이름, 설명). 사용자가 입력창에서 쓸 만한 명령만 골랐다.
BUILTIN = [
    ("add-dir", "작업 폴더 추가"),
    ("background", "세션을 백그라운드로 보내기"),
    ("batch", "큰 변경을 나눠 병렬로 실행"),
    ("branch", "현재 대화에서 분기"),
    ("brief", "짧게 답하는 모드 켜기/끄기"),
    ("btw", "본작업을 멈추지 않고 짧게 질문"),
    ("bug", "버그 신고 또는 대화 공유"),
    ("chrome", "Chrome 연동 설정"),
    ("clear", "새 대화 시작 (맥락 비우기)"),
    ("color", "입력 막대 색 바꾸기"),
    ("compact", "대화를 요약해 맥락 줄이기"),
    ("config", "설정 열기"),
    ("context", "맥락 사용량 보기"),
    ("copy", "마지막 응답 복사"),
    ("debug", "이 세션의 디버그 로그 켜기"),
    ("doctor", "설치 상태 점검"),
    ("effort", "추론 강도 설정"),
    ("exit", "종료"),
    ("export", "대화를 파일이나 클립보드로 내보내기"),
    ("feedback", "피드백 보내기"),
    ("focus", "입력·요약·응답만 보기"),
    ("fork", "전체 대화를 물려받은 백그라운드 에이전트"),
    ("goal", "멈추기 전에 확인할 목표 설정"),
    ("help", "도움말과 명령 목록"),
    ("hooks", "훅 설정 보기"),
    ("ide", "IDE 연동 관리"),
    ("init", "CLAUDE.md 초안 만들기"),
    ("insights", "세션 분석 리포트"),
    ("keybindings", "단축키 파일 열기"),
    ("login", "로그인"),
    ("logout", "로그아웃"),
    ("mcp", "MCP 서버 관리"),
    ("memory", "CLAUDE.md와 메모리 설정"),
    ("mobile", "모바일 앱 QR 코드 보기"),
    ("model", "모델 설정"),
    ("output-style", "출력 스타일 고르기"),
    ("permissions", "허용과 거부 규칙 보기"),
    ("plan", "계획 모드 켜기"),
    ("plugin", "플러그인 관리"),
    ("powerup", "기능 익히기"),
    ("recap", "한 줄 요약 만들기"),
    ("reload-plugins", "플러그인 변경 적용"),
    ("reload-skills", "스킬 변경 적용"),
    ("remote-control", "폰이나 claude.ai/code에서 조작"),
    ("rename", "대화 이름 바꾸기"),
    ("resume", "이전 대화 이어가기"),
    ("rewind", "이전 시점으로 되돌리기"),
    ("schedule", "예약 에이전트 관리"),
    ("skills", "사용 가능한 스킬 목록"),
    ("status", "버전, 모델, 계정, 연결 상태"),
    ("statusline", "상태 줄 설정"),
    ("stop", "백그라운드 세션 중지"),
    ("tasks", "백그라운드 작업 보기"),
    ("terminal-setup", "터미널 설정"),
    ("theme", "테마 바꾸기"),
    ("usage", "사용량 보기"),
    ("version", "버전 보기"),
    ("voice", "음성 모드 켜기/끄기"),
]


def _frontmatter(text: str) -> dict:
    """파일 맨 위 --- 사이의 key: value 줄만 읽는다 (외부 라이브러리 없이)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


def _scan_skill_dir(root: Path, source: str) -> list:
    out = []
    if not root.is_dir():
        return out
    for skill_md in sorted(root.glob("*/SKILL.md")):
        try:
            meta = _frontmatter(skill_md.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        name = meta.get("name") or skill_md.parent.name
        out.append((name, meta.get("description", ""), source))
    return out


def _scan_command_dir(root: Path, source: str) -> list:
    out = []
    if not root.is_dir():
        return out
    for md in sorted(root.glob("*.md")):
        try:
            meta = _frontmatter(md.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            meta = {}
        out.append((md.stem, meta.get("description", ""), source))
    return out


def gather(home: Path, project: Path | None) -> list:
    """목록 전체. 같은 이름이 여러 번 나오면 먼저 나온 것을 쓴다 (프로젝트 > 사용자 > 내장)."""
    items = []
    if project is not None:
        items += _scan_skill_dir(project / ".claude" / "skills", "프로젝트 스킬")
        items += _scan_command_dir(project / ".claude" / "commands", "프로젝트 명령")
    items += _scan_skill_dir(home / ".claude" / "skills", "사용자 스킬")
    items += _scan_command_dir(home / ".claude" / "commands", "사용자 명령")
    items += [(name, desc, "내장") for name, desc in BUILTIN]
    seen, unique = set(), []
    for name, desc, source in items:
        if name not in seen:
            seen.add(name)
            unique.append((name, desc, source))
    return unique


def slash_prefix(text: str):
    """입력이 /로 시작하고 아직 공백이 없으면 그 뒤 글자(접두어)를 돌려준다. 아니면 None."""
    if not text.startswith("/"):
        return None
    body = text[1:]
    if any(ch.isspace() for ch in body):
        return None
    return body


def matches(items: list, prefix: str) -> list:
    return [item for item in items if item[0].startswith(prefix)]


# ---------- @ 파일 목록 ----------

SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build"}
FILE_LIMIT = 3000
MAX_DEPTH = 6


def list_files(root: Path) -> list:
    """세션 폴더의 파일 목록 (상대 경로). git 저장소면 git이 아는 파일만, 아니면 직접 훑는다."""
    try:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"],
                                capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            return [line for line in result.stdout.splitlines() if line][:FILE_LIMIT]
    except (OSError, subprocess.SubprocessError):
        pass
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if len(rel_dir.parts) >= MAX_DEPTH:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        for name in filenames:
            if name.startswith("."):
                continue
            found.append(str(rel_dir / name).replace(os.sep, "/") if rel_dir.parts else name)
            if len(found) >= FILE_LIMIT:
                return sorted(found)
    return sorted(found)


def file_token(text: str):
    """커서가 있는 끝 낱말이 @로 시작하면 그 낱말을 돌려준다. 아니면 None."""
    if not text or text[-1].isspace():
        return None
    token = re.split(r"\s", text)[-1]
    return token if token.startswith("@") else None


def match_files(files: list, prefix: str) -> list:
    """앞부분이 맞는 파일을 먼저, 그다음 가운데가 맞는 파일 순서로 돌려준다."""
    p = prefix.lower()
    starts = [f for f in files if f.lower().startswith(p)]
    inside = [f for f in files if p in f.lower() and f not in starts]
    return starts + inside
