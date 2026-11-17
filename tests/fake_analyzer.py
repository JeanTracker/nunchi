"""관제 화면 시험용 분석기 대역 (요구 이력 68 R2).

관제 화면 시험은 예전에 파이썬 분석기(analyzer.Analyzer)에 가짜 실행기를 넣어 화면에 결과·상태를 만들었다.
파이썬 분석기를 지우며, 그 분석기가 이 시험들의 입력에 써 두던 결과를 frozen_analyses.json에 얼려 두고
이 대역이 같은 때(요청 → 대기 → 실행 → 저장 또는 실패)에 같은 파일을 쓴다. 분석 판단은 하지 않는다.
분석 자체는 러스트 엔진이 하고 cargo test가 확인한다.
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from control_tui import analyzer, transcript

FROZEN = json.loads((Path(__file__).with_name("frozen_analyses.json")).read_text(encoding="utf-8"))

# 예전 test_analyzer.py의 대화 기록 (화면 시험이 같이 쓰던 것)
def make_transcript(tmp_path):
    path = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "uuid": "a", "timestamp": "2026-11-09T01:00:00.000Z",
         "message": {"role": "user", "content": "가격표 조사해줘"}},
        {"type": "assistant", "uuid": "b", "timestamp": "2026-11-09T01:01:00.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "찾았습니다"}]}},
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


class FakeAnalyzer:
    """request·status·prioritize·shutdown·wait_idle (관제가 쓰던 분석기와 같은 모양).

    result: 저장할 분석 결과(FROZEN의 하나), error: 실패 이유, gate: 실행을 붙잡아 두는 Event,
    calls: 실행할 때마다 (세션, 응답 시각)을 붙인다."""

    def __init__(self, result=None, error=None, gate=None, calls=None):
        self.result, self.error, self.gate = result, error, gate
        self.calls = calls if calls is not None else []
        self._cv = threading.Condition()
        self._jobs: dict = {}
        self._running = None
        self._started = 0.0
        self._failed: set = set()
        self.last_error: dict = {}
        self._priority = ""
        self._stopped = False
        threading.Thread(target=self._loop, daemon=True).start()

    def request(self, session_id, session_dir, transcript_path, source_ts, force=False) -> bool:
        if not transcript_path or not source_ts:
            return False
        key = (session_id, source_ts)
        with self._cv:
            if self._stopped:
                return False
            existing = analyzer.read_analysis(Path(session_dir))
            if existing and existing.get("source_ts") == source_ts and not force:
                return False
            if (self._running and self._running["key"] == key) or (self._jobs.get(session_id) or {}).get("key") == key:
                return False
            if key in self._failed and not force:
                return False
            self._failed.discard(key)
            self._jobs[session_id] = {"key": key, "dir": Path(session_dir), "transcript": Path(transcript_path)}
            self._cv.notify_all()
        return True

    def prioritize(self, session_id) -> None:
        with self._cv:
            self._priority = session_id or ""

    def status(self, session_id) -> dict:
        with self._cv:
            if self._running and self._running["key"][0] == session_id:
                return {"state": "running", "seconds": int(time.monotonic() - self._started),
                        "source_ts": self._running["key"][1], "turn": 0}
            if session_id in self._jobs:
                ahead = (1 if self._running else 0) + (0 if session_id == self._priority else
                                                       sum(1 for s in self._jobs if s != session_id))
                return {"state": "queued", "ahead": ahead, "source_ts": self._jobs[session_id]["key"][1]}
            failed = [k for k in self._failed if k[0] == session_id]
            if failed and session_id in self.last_error:
                return {"state": "failed", "error": self.last_error[session_id], "source_ts": failed[-1][1]}
        return {"state": ""}

    def shutdown(self) -> None:
        with self._cv:
            self._stopped = True
            self._jobs.clear()
            self._cv.notify_all()

    def wait_idle(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        with self._cv:
            while self._jobs or self._running:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("분석이 끝나지 않았습니다")
                self._cv.wait(left)

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._jobs and not self._stopped:
                    self._cv.wait()
                if self._stopped:
                    return
                sid = self._priority if self._priority in self._jobs else next(iter(self._jobs))
                job = self._jobs.pop(sid)
                self._running, self._started = job, time.monotonic()
            try:
                self.calls.append(job["key"])
                if self.gate is not None:
                    self.gate.wait(10)
                if self.error:
                    with self._cv:
                        self.last_error[sid] = self.error
                        self._failed.add(job["key"])
                elif not self._stopped:
                    turns = transcript.parse_turns(job["transcript"], until_ts=job["key"][1])
                    payload = dict(self.result or {}, format=analyzer.FORMAT, source_ts=job["key"][1],
                                   last_turn=turns[-1].index if turns else 0, changes={},
                                   analyzed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
                    (job["dir"] / "analysis.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            finally:
                with self._cv:
                    self._running = None
                    self._cv.notify_all()
