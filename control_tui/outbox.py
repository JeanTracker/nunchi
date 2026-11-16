"""③ 입력줄의 전송 규칙과 대기열 (SCREEN.md §4, BUILD_PLAN §5.1).

화면과 무관한 순수 로직이다. 실제 전송은 app이 어댑터로 한다.

- 대기 / 응답 도착 / 연결 대기가 아닌 idle: 바로 보낸다
- 일하는 중: 대기열에 넣고, 응답이 도착하면(Stop) 한 건씩 보낸다
- 허락 기다림: 글자를 막는다 (y/n만)
- 질문 기다림: 글자를 막고 ③ 질문 답하기로 답한다 (요청 39)
- 끝난 세션, 연결 대기: 보내지 않고 이유를 보여준다
"""

from dataclasses import dataclass, field

SEND = "send"
QUEUE = "queue"
PERMISSION = "permission"
QUESTION = "question"
REFUSE = "refuse"

REFUSE_REASON = {
    "ended": "끝난 세션이라 보낼 수 없습니다.",
    "pending": "연결 대기 세션은 Claude를 한 번 다시 시작한 뒤 보낼 수 있습니다.",
}

# 보낸 뒤 이 시간 안에 세션 기록이 바뀌지 않으면 다시 보내지 않고 기다린다
IN_FLIGHT_SECONDS = 30.0


def decide(state: str) -> str:
    if state in ("idle", "responded"):
        return SEND
    if state == "working":
        return QUEUE
    if state == "permission":
        return PERMISSION
    if state == "question":
        return QUESTION   # 글 대신 ③ 질문 답하기로 답한다 (요청 39)
    return REFUSE


@dataclass
class Outbox:
    queues: dict = field(default_factory=dict)     # session_id -> [text, ...]
    in_flight: dict = field(default_factory=dict)  # session_id -> (last_ts, monotonic time)

    def enqueue(self, session_id: str, text: str) -> int:
        self.queues.setdefault(session_id, []).append(text)
        return len(self.queues[session_id])

    def count(self, session_id: str) -> int:
        return len(self.queues.get(session_id, []))

    def peek_ready(self, views: list, now: float) -> list:
        """지금 보내도 되는 (세션, 글) 목록. 상태는 바꾸지 않는다."""
        ready = []
        for v in views:
            if not self.queues.get(v.session_id):
                continue
            if v.state not in ("idle", "responded"):
                continue
            sent = self.in_flight.get(v.session_id)
            if sent is not None:
                last_ts, when = sent
                if v.last_ts == last_ts and now - when < IN_FLIGHT_SECONDS:
                    continue  # 방금 보낸 것이 아직 기록에 안 보인다
            ready.append((v, self.queues[v.session_id][0]))
        return ready

    def mark_sent(self, session_id: str, last_ts: str, now: float) -> None:
        """어댑터 전송이 성공한 뒤 호출한다. 대기열 맨 앞 한 건을 뺀다."""
        queue = self.queues.get(session_id, [])
        if queue:
            queue.pop(0)
        if not queue:
            self.queues.pop(session_id, None)
        self.in_flight[session_id] = (last_ts, now)
