"""관제 화면 쪽 분석 요청 (요구 이력 52·53·68, BUILD_PLAN §4.7·§4.13).

분석은 러스트 엔진의 분석기(`nunchi-engine worker`)가 한다. 관제 화면은 여기서
- 요청을 `<관제 홈>/queue/<세션 ID>.json`에 남기고(같은 세션은 최신 응답 하나로 합침, 훅이 쓰는 것과 같은 꼴),
- 빈 자리가 있으면 분석기를 깨우고,
- 상태 파일(analysis_status.json)과 대기열로 화면 상태를 읽고,
- mod가 읽을 번호 풀이(glossary.json)를 쓴다.
관제 화면을 러스트로 옮길 때(R3) 함께 옮긴다.
"""

import fcntl
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from control_tui import analyzer as analyzer_mod

QUEUE = "queue"

PRIORITY_FILE = "priority"     # 관제에서 지금 고른 세션 (먼저 분석)

MAX_WORKERS = 2

SPAWN_GAP_SECONDS = 5.0        # 관제가 매초 깨우더라도 분석기를 띄우는 것은 이 간격에 한 번까지

REPO = Path(__file__).resolve().parent.parent


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def queue_dir(home: Path) -> Path:
    return Path(home) / QUEUE


def enqueue(home: Path, session_id: str, transcript_path: str, source_ts: str, force: bool = False,
            by: str = "hook") -> Path:
    """분석 요청을 남긴다. 이미 있으면 더 최신 응답 시각으로 합치고, force는 한 번이라도 있으면 남긴다.
    by는 누가 넣었나(hook·control). 관제가 한 번이라도 넣었으면 control로 남긴다(꺼진 세션도 관제 요청은 분석, 요구 이력 62)."""
    path = queue_dir(home) / f"{session_id}.json"
    old = _read(path)
    if old.get("source_ts", "") > source_ts:
        source_ts, transcript_path = old["source_ts"], old.get("transcript_path") or transcript_path
    _write(path, {"session_id": session_id, "transcript_path": transcript_path, "source_ts": source_ts,
                  "force": bool(force or old.get("force")), "queued_at": old.get("queued_at") or _now(),
                  "by": "control" if "control" in (by, old.get("by")) else by})
    return path


def pending(home: Path) -> list:
    """기다리는 요청 목록 (오래된 것부터)."""
    out = []
    for p in sorted(queue_dir(home).glob("*.json")):
        item = _read(p)
        if item.get("session_id") and item.get("source_ts"):
            item["_path"] = p
            out.append(item)
    return sorted(out, key=lambda x: x.get("queued_at", ""))


def _try_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        os.close(fd)
        return None


def _unlock(fd) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def take_slot(home: Path, workers: int):
    """비어 있는 분석기 자리의 잠금을 잡는다. 모두 차 있으면 None."""
    for n in range(max(1, min(MAX_WORKERS, workers))):
        fd = _try_lock(Path(home) / f"analyzer-{n}.lock")
        if fd is not None:
            return fd
    return None


def free_slot(home: Path, workers: int) -> bool:
    fd = take_slot(home, workers)
    if fd is None:
        return False
    _unlock(fd)
    return True


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True



ENGINE = Path("bin") / "nunchi-engine"


def _installed_plugin_roots() -> list:
    """설치된 눈치 플러그인 폴더들 (Claude Code의 installed_plugins.json). 최근에 바뀐 것부터."""
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        data = json.loads((config / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    installs = []
    for key, items in ((data or {}).get("plugins") or {}).items():
        if key.split("@")[0] == "nunchi" and isinstance(items, list):
            installs += [i for i in items if isinstance(i, dict) and i.get("installPath")]
    installs.sort(key=lambda i: str(i.get("lastUpdated") or i.get("installedAt") or ""), reverse=True)
    return [Path(i["installPath"]) for i in installs]


def engine_path():
    """깨울 분석기 실행 파일: 이 저장소에서 빌드한 것(scripts/build-engine.sh), 없으면 설치된 플러그인에 실린 것. 없으면 None."""
    for root in [REPO] + _installed_plugin_roots():
        exe = root / ENGINE
        if os.access(exe, os.X_OK):
            return exe
    return None


def worker_command(home: Path):
    """분석기 실행 명령. 엔진이 없으면 None (요청은 대기열에 남고, 훅이 깨우는 분석기가 가져간다)."""
    exe = engine_path()
    return [str(exe), "worker", "--home", str(home)] if exe else None


def wake(home: Path, workers: int = 1, spawner=None) -> bool:
    """빈 자리가 있으면 분석기를 하나 띄운다. 세션·터미널과 떼어 내 세션을 닫아도 살아남는다 (SCREEN §8).
    CONTROL_TUI_WORKER=0이면 띄우지 않는다(테스트). 띄웠으면 True."""
    if os.environ.get("CONTROL_TUI_WORKER", "1") == "0" or not free_slot(home, workers):
        return False
    cmd = worker_command(home)
    if cmd is None:
        return False
    if spawner is not None:
        spawner(cmd)
        return True
    env = dict(os.environ, CONTROL_TUI_HOME=str(home))
    env.pop("CONTROL_TUI_ANALYZER", None)
    subprocess.Popen(cmd, cwd=str(REPO), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    return True


def _session_cwd(session_dir: Path) -> str:
    cwd = ""
    try:
        with open(session_dir / "events.jsonl", encoding="utf-8") as f:
            for line in f:
                try:
                    cwd = json.loads(line).get("cwd") or cwd
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return cwd


def write_glossary(session_dir: Path, transcript_path: str = "", cwd: str = "") -> None:
    """mod가 읽을 번호 풀이 (요구 이력 51). 관제가 꺼져 있어도 분석이 끝나면 쓴다. 보조 정보라 실패해도 넘어간다."""
    from control_tui import glossary as glossary_mod
    from control_tui import transcript
    try:
        if not transcript_path:
            for line in open(session_dir / "events.jsonl", encoding="utf-8"):
                try:
                    transcript_path = json.loads(line).get("transcript_path") or transcript_path
                except json.JSONDecodeError:
                    continue
        cwd = cwd or _session_cwd(session_dir)
        turns = transcript.parse_turns(Path(transcript_path)) if transcript_path else []
        last = turns[-1] if turns else None
        body = (last.final_response or last.response) if last else ""
        got = glossary_mod.explain(body, cwd)
        got["turn"] = last.index if last else 0
        path = Path(session_dir) / "glossary.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(got, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)   # 쓰는 도중의 파일을 mod가 읽지 않도록 한 번에 바꾼다
    except (OSError, ValueError):
        pass


class QueueAnalyzer:
    """관제 앱이 쓰던 Analyzer와 같은 모양(request·status·prioritize·shutdown)으로,
    분석은 하지 않고 요청을 남기고 분석기를 깨운다. 상태는 파일에서 읽는다."""

    def __init__(self, home: Path, workers: int = 1, spawner=None):
        self.home = Path(home)
        self.workers = workers
        self.spawner = spawner
        self._priority = ""
        self._last_wake = 0.0

    def _wake(self) -> None:
        if time.monotonic() - self._last_wake < SPAWN_GAP_SECONDS:
            return
        self._last_wake = time.monotonic()
        wake(self.home, self.workers, self.spawner)

    def request(self, session_id: str, session_dir: Path, transcript_path: str, source_ts: str,
                force: bool = False) -> bool:
        if not transcript_path or not source_ts:
            return False
        existing = analyzer_mod.read_analysis(session_dir)
        flow = (existing or {}).get("flow") or {}
        flow_left = (flow.get("until") or 0) < ((existing or {}).get("last_turn") or 0)
        if not force and existing and existing.get("source_ts") == source_ts and not flow_left:
            return False
        if not force:
            st = analyzer_mod.read_status(session_dir)
            if (st.get("state") == "failed" and st.get("source_ts") == source_ts
                    and int(st.get("attempts") or 0) >= analyzer_mod.MAX_ATTEMPTS):
                return False   # 정해진 횟수를 다 쓴 실패는 r로만 다시 한다
            queued = _read(queue_dir(self.home) / f"{session_id}.json")
            if queued.get("source_ts") == source_ts:
                self._wake()   # 이미 줄에 있다. 분석기가 죽었으면 다시 띄운다
                return False
        enqueue(self.home, session_id, transcript_path, source_ts, force=force, by="control")
        if force:
            self._last_wake = 0.0
        self._wake()
        return True

    def prioritize(self, session_id: str) -> None:
        if session_id == self._priority:
            return
        self._priority = session_id
        try:
            path = queue_dir(self.home) / PRIORITY_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(session_id, encoding="utf-8")
        except OSError:
            pass

    def status(self, session_id: str) -> dict:
        """화면용 상태: running(경과 초·턴) / queued(앞에 몇 건) / failed(이유) / ''."""
        sdir = self.home / "sessions" / session_id
        st = analyzer_mod.read_status(sdir)
        state = st.get("state", "")
        if state == "running" and _alive(int(st.get("pid") or 0)):
            try:
                since = datetime.fromisoformat(str(st.get("since") or st.get("at")).replace("Z", "+00:00"))
                seconds = int((datetime.now(timezone.utc) - since).total_seconds())
            except ValueError:
                seconds = 0
            return {"state": "running", "seconds": max(0, seconds), "source_ts": st.get("source_ts", ""),
                    "turn": st.get("turn", 0)}
        items = pending(self.home)
        mine = [i for i in items if i["session_id"] == session_id]
        if mine:
            others = [i for i in items if i["session_id"] != session_id]
            ahead = 0 if session_id == self._priority else len(others)
            if engine_path() is None:   # 깨울 분석기가 어디에도 없다: 기다려도 분석되지 않는다
                return {"state": "failed", "error": "분석 엔진 없음 · 눈치 플러그인을 설치하세요", "source_ts": mine[0]["source_ts"]}
            return {"state": "queued", "ahead": ahead, "source_ts": mine[0]["source_ts"]}
        if state == "failed":
            return {"state": "failed", "error": st.get("error", ""), "source_ts": st.get("source_ts", "")}
        return {"state": ""}

    def shutdown(self) -> None:
        """관제를 꺼도 돌던 분석은 끝까지 간다 (§4.7)."""
