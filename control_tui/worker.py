"""관제 화면 밖에서 도는 분석기 (요구 이력 52·53, BUILD_PLAN §4.7).

- 분석 요청은 `<관제 홈>/queue/<세션 ID>.json` 파일 하나다. 같은 세션의 요청은 최신 응답 시각 하나로 합친다.
  요청을 남기는 쪽: 훅(`/nunchi`로 켠 세션이나 analyze_scope=all이 응답을 끝낼 때), 관제(고른 세션, a·r 키).
- 분석기는 상주하지 않는다. 요청을 남긴 쪽이 `wake()`로 깨우고, 대기열이 비면 바로 끝난다
  (실측: 다시 띄우는 비용 약 0.2초, 다음 요청까지 중앙값 270초. SCREEN §8).
- 동시에 도는 분석기는 analyze_workers(1~2)개까지. 자리마다 잠금 파일(`analyzer-<n>.lock`)을 잡는다.
  한 세션은 한 분석기만 맡는다(`queue/<세션 ID>.claim`).
- 실제 분석은 analyzer.Analyzer를 그대로 쓴다: 한 건씩, 고른 세션 먼저, 밀린 같은 세션은 최신으로,
  실패하면 잠시 쉬었다가 정해진 횟수만 다시.
- 결과 파일(analysis.json, analysis_status.json, glossary.json)의 형식과 위치는 그대로다.
"""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from control_tui import analyzer as analyzer_mod
from control_tui import settings as settings_mod

QUEUE = "queue"
PRIORITY_FILE = "priority"     # 관제에서 지금 고른 세션 (먼저 분석)
WANT_FILE = "want"             # mod가 /nunchi로 켠 세션 표시 (요구 이력 53)
MAX_WORKERS = 2
POLL_SECONDS = 0.5
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


def want_state(home: Path, session_id: str):
    """세션에서 /nunchi로 켜고 끈 표시 (요구 이력 53·62). 켬 True, 끔 False, 표시 없음 None.
    on이 없는 옛 표시는 켬으로 본다."""
    path = Path(home) / "sessions" / session_id / "want"
    if not path.exists():
        return None
    return _read(path).get("on", True) is not False


def pending(home: Path) -> list:
    """기다리는 요청 목록 (오래된 것부터)."""
    out = []
    for p in sorted(queue_dir(home).glob("*.json")):
        item = _read(p)
        if item.get("session_id") and item.get("source_ts"):
            item["_path"] = p
            out.append(item)
    return sorted(out, key=lambda x: x.get("queued_at", ""))


def wants(home: Path, session_id: str) -> bool:
    return (Path(home) / "sessions" / session_id / WANT_FILE).exists()


# ---------- 자리 잠금과 세션 맡기 ----------

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


def claim(home: Path, session_id: str) -> bool:
    """이 세션을 이 분석기가 맡는다. 다른 분석기가 살아서 맡고 있으면 False. 죽은 분석기의 표시는 걷어 낸다."""
    path = queue_dir(home) / f"{session_id}.claim"
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                pid = int(path.read_text() or "0")
            except (OSError, ValueError):
                pid = 0
            if pid == os.getpid():
                return True
            if pid and _alive(pid):
                return False
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    return False


def release(home: Path, session_id: str) -> None:
    path = queue_dir(home) / f"{session_id}.claim"
    try:
        if path.read_text() == str(os.getpid()):
            path.unlink()
    except (OSError, ValueError):
        pass


def _drop(item: dict) -> None:
    """요청을 지운다. 그 사이 더 최신 요청으로 바뀌었으면 지우지 않는다."""
    path = item["_path"]
    if _read(path).get("source_ts") == item["source_ts"]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


# ---------- 깨우기 ----------

def worker_command(home: Path) -> list:
    py = REPO / ".venv" / "bin" / "python"
    exe = str(py) if py.exists() else sys.executable
    return [exe, "-m", "control_tui.worker", "--home", str(home)]


def wake(home: Path, workers: int = 1, spawner=None) -> bool:
    """빈 자리가 있으면 분석기를 하나 띄운다. 세션·터미널과 떼어 내 세션을 닫아도 살아남는다 (SCREEN §8).
    CONTROL_TUI_WORKER=0이면 띄우지 않는다(테스트). 띄웠으면 True."""
    if os.environ.get("CONTROL_TUI_WORKER", "1") == "0" or not free_slot(home, workers):
        return False
    cmd = worker_command(home)
    if spawner is not None:
        spawner(cmd)
        return True
    env = dict(os.environ, CONTROL_TUI_HOME=str(home))
    env.pop("CONTROL_TUI_ANALYZER", None)
    subprocess.Popen(cmd, cwd=str(REPO), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    return True


# ---------- 분석기 본체 ----------

def drain(home: Path, runner=None, flow_runner=None, poll: float = POLL_SECONDS, reply_wait=None,
          max_seconds: float = 0) -> int:
    """대기열이 빌 때까지 분석한다. 처리를 끝낸 요청 수를 돌려준다. 자리가 없으면 바로 0."""
    home = Path(home)
    st = settings_mod.load(home)
    slot = take_slot(home, st.analyze_workers)
    if slot is None:
        return 0
    kw = {"model": st.analyze_model, "max_turns": st.analyze_max_turns}
    if runner is not None:
        kw.update(runner=runner, flow_runner=flow_runner)
    if reply_wait is not None:
        kw["reply_wait"] = reply_wait
    an = analyzer_mod.Analyzer(**kw)
    mine: set = set()
    done = 0
    started = time.monotonic()
    try:
        while True:
            # 관제에서 고른 세션을 먼저 넘긴다. 넘기는 즉시 분석이 시작되므로 순서가 곧 우선순위다
            try:
                prio = (home / QUEUE / PRIORITY_FILE).read_text().strip()
            except OSError:
                prio = ""
            an.prioritize(prio)
            items = sorted(pending(home), key=lambda i: i["session_id"] != prio)
            for item in items:
                sid = item["session_id"]
                if sid not in mine and item.get("by") != "control" and want_state(home, sid) is False:
                    _drop(item)   # /nunchi off로 끈 세션: 훅이 넣은 요청은 버린다 (돌던 분석은 끝까지 감)
                    continue
                if sid not in mine:
                    if not claim(home, sid):
                        continue
                    mine.add(sid)
                sdir = home / "sessions" / sid
                key = (sid, item["source_ts"])
                existing = analyzer_mod.read_analysis(sdir)
                if (existing and existing.get("source_ts") == item["source_ts"]
                        and not an._flow_pending(existing) and an._running is None and sid not in an._jobs):
                    _drop(item)
                    release(home, sid)
                    mine.discard(sid)
                    write_glossary(sdir)
                    done += 1
                    continue
                attempts = an._failed.get(key, (0, 0.0))[0]
                if attempts >= analyzer_mod.MAX_ATTEMPTS and not item.get("force"):
                    _drop(item)   # 정해진 횟수를 다 썼다. 상태 파일에 실패가 남아 있다 (r로 다시)
                    release(home, sid)
                    mine.discard(sid)
                    continue
                if item.get("force"):
                    an.request(sid, sdir, item.get("transcript_path", ""), item["source_ts"], force=True)
                    item2 = {k: v for k, v in item.items() if k != "_path"}
                    item2["force"] = False
                    if _read(item["_path"]).get("source_ts") == item["source_ts"]:
                        _write(item["_path"], item2)
                else:
                    an.request(sid, sdir, item.get("transcript_path", ""), item["source_ts"])
            idle = an._running is None and not an._jobs
            if not mine and idle:
                # 끝내기 전에 자리를 내놓고 한 번 더 본다: 그 사이 들어온 요청을 놓치지 않는다 (§4.7)
                _unlock(slot)
                slot = None
                if not [i for i in pending(home) if claim_free(home, i["session_id"])]:
                    break
                slot = take_slot(home, st.analyze_workers)
                if slot is None:
                    break   # 다른 분석기가 이어 받았다
            if max_seconds and time.monotonic() - started > max_seconds:
                break
            time.sleep(poll)
    finally:
        an.shutdown()
        for sid in list(mine):
            release(home, sid)
        if slot is not None:
            _unlock(slot)
    return done


def claim_free(home: Path, session_id: str) -> bool:
    """다른 살아 있는 분석기가 맡고 있지 않은 요청인지."""
    path = queue_dir(home) / f"{session_id}.claim"
    try:
        pid = int(path.read_text() or "0")
    except (OSError, ValueError):
        return True
    return not (pid and pid != os.getpid() and _alive(pid))


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
        analyzer_mod._write_json(Path(session_dir) / "glossary.json", got)
    except (OSError, ValueError):
        pass


# ---------- 관제가 쓰는 쪽 ----------

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
            return {"state": "queued", "ahead": ahead, "source_ts": mine[0]["source_ts"]}
        if state == "failed":
            return {"state": "failed", "error": st.get("error", ""), "source_ts": st.get("source_ts", "")}
        return {"state": ""}

    def shutdown(self) -> None:
        """관제를 꺼도 돌던 분석은 끝까지 간다 (§4.7)."""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="눈치 백그라운드 분석기 (대기열이 비면 끝난다)")
    ap.add_argument("--home", default=os.environ.get("CONTROL_TUI_HOME", str(Path.home() / ".claude-control")))
    args = ap.parse_args(argv)
    try:
        drain(Path(args.home))
    except Exception as e:  # noqa: BLE001 — 분석기는 조용히 끝난다. 이유는 errors.log에
        try:
            with open(Path(args.home) / "errors.log", "a", encoding="utf-8") as f:
                f.write(f"{_now()} worker 실패: {type(e).__name__}: {e}\n")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
