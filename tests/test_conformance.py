"""파이썬 엔진과 러스트 엔진이 같은 입력에 같은 결과를 내는지 (요구 이력 68, BUILD_PLAN §4.13).

crates/engine/tests/scenarios/*.json의 단계(대화 기록 쓰기, 훅, 분석기, 가짜 claude 대본 바꾸기)를
두 엔진으로 따로 돌리고, 관제 홈에 남은 파일을 비교한다. 시각·pid·작업 폴더 경로만 자리표로 바꾼다.

파이썬 엔진의 결과는 crates/engine/tests/golden/에 정답으로 남긴다(NUNCHI_UPDATE_GOLDEN=1일 때 다시 씀).
파이썬 엔진을 지운 뒤에는 `cargo test`가 이 정답으로 러스트 엔진을 확인한다.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCEN = ROOT / "crates" / "engine" / "tests" / "scenarios"
GOLDEN = ROOT / "crates" / "engine" / "tests" / "golden"
TARGET = ROOT / "target" / "debug"
PY_WORKER = ("import os, sys, pathlib; sys.path.insert(0, %r); from control_tui import worker, analyzer; "
             "analyzer.RETRY_SECONDS = float(os.environ['CONTROL_TUI_RETRY_SECONDS']); "
             "worker.drain(pathlib.Path(os.environ['CONTROL_TUI_HOME']), reply_wait=float(os.environ['CONTROL_TUI_REPLY_WAIT']))") % str(ROOT)
ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)?$")
TIME_KEYS = {"at", "since", "analyzed_at", "queued_at"}


@pytest.fixture(scope="module")
def built():
    res = subprocess.run(["cargo", "build", "-q", "--features", "dev"], cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return TARGET


# ---------- 단계 실행 ----------

def transcript_lines(session, turns, cwd):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    out, k = [], 0

    def rec(kind, content):
        nonlocal k
        k += 1
        ts = datetime.fromtimestamp(base + k * 10, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        out.append({"type": kind, "message": {"role": kind, "content": content}, "timestamp": ts,
                    "uuid": f"u{k}", "sessionId": session, "cwd": cwd})

    for turn in turns:
        rec("user", turn["req"])
        for item in turn["resp"]:
            if isinstance(item, str):
                rec("assistant", [{"type": "text", "text": item}])
            else:
                tid = f"tu{k}"
                rec("assistant", [{"type": "tool_use", "id": tid, "name": item["tool"], "input": {}}])
                rec("user", [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}])
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out)


class Bench:
    def __init__(self, work: Path, engine: str, scenario: dict, built: Path):
        self.w, self.engine, self.sc, self.built = work, engine, scenario, built
        self.home, self.proj = work / "home", work / "proj"
        for d in (self.home, self.proj / "docs", work / "transcripts", work / "fakebin", work / "fake"):
            d.mkdir(parents=True, exist_ok=True)
        (work / "fakebin" / "claude").symlink_to(built / "fake-claude")
        for name, text in (scenario.get("docs") or {}).items():
            (self.proj / "docs" / name).write_text(text, encoding="utf-8")
        self.write_fake(scenario.get("fake") or {})

    def write_fake(self, script):
        (self.w / "fake" / "script.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")

    def env(self, extra=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CONTROL_TUI_", "FAKE_CLAUDE_"))}
        env.update(PATH=f"{self.w / 'fakebin'}:{os.environ['PATH']}", CONTROL_TUI_HOME=str(self.home),
                   CONTROL_TUI_ANALYZE="1", CONTROL_TUI_WORKER="0", CONTROL_TUI_RETRY_SECONDS="1",
                   CONTROL_TUI_REPLY_WAIT="0.3", ITERM_SESSION_ID="w0t0p0:FAKE",
                   FAKE_CLAUDE_SCRIPT=str(self.w / "fake" / "script.json"), FAKE_CLAUDE_STATE=str(self.w / "fake"))
        env.update(extra or {})
        return env

    def tpath(self, session):
        return self.w / "transcripts" / f"{session}.jsonl"

    def run_hook(self, stdin, env=None):
        cmd = [sys.executable, str(ROOT / "hooks" / "emit.py")] if self.engine == "python" else [str(self.built / "nunchi-engine"), "hook"]
        res = subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=self.env(env), timeout=30)
        assert res.returncode == 0, res.stderr

    def step(self, st):
        (kind, arg), = st.items()
        if kind == "transcript":
            self.tpath(arg["session"]).write_text(transcript_lines(arg["session"], arg["turns"], str(self.proj)), encoding="utf-8")
        elif kind == "want":
            d = self.home / "sessions" / arg["session"]
            d.mkdir(parents=True, exist_ok=True)
            (d / "want").write_text(json.dumps({"at": "2026-06-01T00:00:00Z", "by": "test", "on": arg["on"]}), encoding="utf-8")
        elif kind == "file":
            p = self.home / arg["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(arg["text"] if "text" in arg else json.dumps(arg["json"], ensure_ascii=False), encoding="utf-8")
        elif kind == "config":
            (self.home / "config.json").write_text(json.dumps(arg), encoding="utf-8")
        elif kind == "fake":
            self.write_fake(arg)
        elif kind == "queue":
            p = self.home / "queue" / f"{arg['session']}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"session_id": arg["session"], "transcript_path": str(self.tpath(arg["session"])),
                                     "source_ts": "2026-06-01T00:00:00.000Z", "force": arg["force"],
                                     "queued_at": "2026-06-01T00:00:00.000000Z", "by": arg["by"]}), encoding="utf-8")
        elif kind == "hook":
            payload = {"session_id": arg["session"], "hook_event_name": arg["event"], "cwd": str(self.proj),
                       "transcript_path": str(self.tpath(arg["session"])), **(arg.get("extra") or {})}
            self.run_hook(json.dumps(payload, ensure_ascii=False))
            time.sleep(0.002)   # 훅 기록 시각이 겹치지 않게
        elif kind == "hook_raw":
            self.run_hook(arg["stdin"], arg.get("env"))
        elif kind == "worker":
            cmd = ([sys.executable, "-c", PY_WORKER] if self.engine == "python"
                   else [str(self.built / "nunchi-engine"), "worker", "--home", str(self.home)])
            res = subprocess.run(cmd, capture_output=True, text=True, env=self.env(), timeout=120)
            assert res.returncode == 0, res.stderr
        else:
            raise AssertionError(f"모르는 단계 {kind}")

    def run(self):
        for st in self.sc["steps"]:
            self.step(st)
        return snapshot(self.w)


# ---------- 결과 모으기 ----------

def snapshot(work: Path) -> dict:
    home = work / "home"
    names: dict = {}

    def norm(v, key=""):
        if isinstance(v, dict):
            return {k: norm(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [norm(x) for x in v]
        if key == "pid":
            return "<pid>"
        if isinstance(v, str):
            if key in TIME_KEYS:
                return "<time>"
            if ISO.match(v) and not v.startswith(("2026-01-01", "2026-06-01")):
                return names.setdefault(v, f"<ts{len(names) + 1}>")
            return v.replace(str(work), "<W>")
        return v

    files = {}
    for p in sorted(home.rglob("*")):
        if p.is_dir():
            continue
        rel = str(p.relative_to(home))
        if p.suffix == ".lock":
            files[rel] = "<lock>"
        elif rel == "errors.log":
            files[rel] = {"lines": len(p.read_text(encoding="utf-8").splitlines())}
        elif p.name == "events.jsonl":
            files[rel] = [norm(json.loads(l)) for l in p.read_text(encoding="utf-8").splitlines()]
        elif p.suffix == ".json" or p.name in ("want",):
            files[rel] = norm(json.loads(p.read_text(encoding="utf-8")))
        else:
            files[rel] = norm(p.read_text(encoding="utf-8"))
    log = work / "fake" / "log"
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return {"files": files, "claude_calls": calls}


SCENARIOS = sorted(p.stem for p in SCEN.glob("*.json"))


@pytest.mark.parametrize("name", SCENARIOS)
def test_engines_agree(name, tmp_path, built):
    sc = json.loads((SCEN / f"{name}.json").read_text(encoding="utf-8"))
    got = {e: Bench(tmp_path / e, e, sc, built).run() for e in ("python", "rust")}
    py, rs = got["python"], got["rust"]
    if any("worker" in s for s in sc["steps"]):
        assert py["claude_calls"], "가짜 claude가 한 번도 불리지 않음 (비교가 아무것도 증명하지 못함)"
    if py != rs:
        for rel in sorted(set(py["files"]) | set(rs["files"])):
            if py["files"].get(rel) != rs["files"].get(rel):
                print(f"--- {rel}\npython: {json.dumps(py['files'].get(rel), ensure_ascii=False)[:1500]}\n"
                      f"rust:   {json.dumps(rs['files'].get(rel), ensure_ascii=False)[:1500]}")
        if py["claude_calls"] != rs["claude_calls"]:
            print("--- claude calls\npython:", py["claude_calls"], "\nrust:  ", rs["claude_calls"])
    assert py == rs
    golden = GOLDEN / f"{name}.json"
    text = json.dumps(py, ensure_ascii=False, indent=1) + "\n"
    if os.environ.get("NUNCHI_UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        golden.write_text(text, encoding="utf-8")
    assert golden.exists() and golden.read_text(encoding="utf-8") == text, "정답 파일이 없거나 옛것 (NUNCHI_UPDATE_GOLDEN=1로 다시 쓰기)"


# ---------- 두 엔진이 섞여 돌 때 (옮기는 동안) ----------

def _one_turn_bench(tmp_path, built, engine):
    sc = {"steps": [{"want": {"session": "s1", "on": True}},
                    {"transcript": {"session": "s1", "turns": [{"req": "기능을 고쳐줘", "resp": ["고쳤습니다."]}]}},
                    {"hook": {"session": "s1", "event": "Stop"}}]}
    b = Bench(tmp_path / engine, engine, sc, built)
    for st in sc["steps"]:
        b.step(st)
    return b


def test_rust_worker_stands_down_while_python_holds_the_slot(tmp_path, built):
    import fcntl
    b = _one_turn_bench(tmp_path, built, "rust")
    fd = os.open(b.home / "analyzer-0.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # 파이썬 분석기가 쥔 자리
    try:
        t = time.monotonic()
        b.step({"worker": {}})
        assert time.monotonic() - t < 2
        assert not (b.w / "fake" / "log").exists()
    finally:
        os.close(fd)
    b.step({"worker": {}})
    assert (b.home / "sessions" / "s1" / "analysis.json").exists()


def test_python_worker_stands_down_while_rust_holds_the_slot(tmp_path, built):
    b = _one_turn_bench(tmp_path, built, "rust")
    b.write_fake({"default": "slow"})
    rust = subprocess.Popen([str(built / "nunchi-engine"), "worker", "--home", str(b.home)], env=b.env())
    try:
        deadline = time.monotonic() + 5
        while not (b.w / "fake" / "log").exists():   # 러스트 분석기가 자리를 잡고 claude를 부를 때까지
            assert time.monotonic() < deadline
            time.sleep(0.05)
        b.engine = "python"
        t = time.monotonic()
        b.step({"worker": {}})
        assert time.monotonic() - t < 2, "파이썬 분석기가 자리를 기다렸다"
        assert len((b.w / "fake" / "log").read_text().splitlines()) == 1
    finally:
        rust.wait(timeout=30)
    assert (b.home / "sessions" / "s1" / "analysis.json").exists()
