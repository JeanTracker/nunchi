"""목표 흐름 읽기 (관제 화면 쪽. 요구 이력 68 R2).

흐름을 이어 적는 일(원문 고정 연쇄, 요청 40)은 러스트 엔진(crates/engine/src/flow.rs)이 한다.
여기에는 관제 화면이 저장된 흐름을 읽는 데 쓰는 것만 남았다. 관제 화면을 러스트로 옮길 때(R3) 함께 옮긴다.
"""


def open_asks(flow) -> list:
    """아직 답이 다 오지 않은 묻는 것 (최근에 물은 것부터)."""
    left = [a for a in (flow or {}).get("asks", []) if a.get("state") != "answered"]
    return sorted(left, key=lambda a: -(a.get("last_turn") or a.get("turn") or 0))
