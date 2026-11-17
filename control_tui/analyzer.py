"""분석 결과 읽기 (관제 화면 쪽. 요구 이력 68 R2).

분석은 러스트 엔진(crates/engine, nunchi-engine worker)이 하고 세션 폴더에 analysis.json과 analysis_status.json을 쓴다.
여기에는 관제 화면이 그 파일을 읽는 데 쓰는 것만 남았다. 관제 화면을 러스트로 옮길 때(R3) 함께 옮긴다.
"""

from __future__ import annotations

import json
from pathlib import Path

STATUS_LABEL = {"kept": "챙김", "missed": "빠짐", "unknown": "확인 안 됨", "superseded": "뒤 요청이 대신함"}

MAX_ATTEMPTS = 2           # 같은 응답에 대해 자동으로 해 보는 최대 횟수 (r 키로 다시 하면 초기화)

FORMAT = 2   # 2 = 요청 원장(사용자 원문 인용, 마지막 응답 기준) + 슬래시 명령 턴 (요청 33·34)

STATUS_FILE = "analysis_status.json"   # 분석 상태를 관제 밖(mod)에서도 읽게 남긴다 (요청 41, R17)


def read_analysis(session_dir: Path):
    """형식이 옛것이면 없는 것으로 본다. 옛 결과는 턴 번호(슬래시 명령 턴이 끼면 밀림)와 원장 뜻이 달라
    새 이름표로 보이면 틀린 말이 된다. 없는 것으로 보면 미판정으로 보이고 다시 분석된다."""
    path = session_dir / "analysis.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("format", 1) < FORMAT:
        return None
    return data


def read_status(session_dir: Path) -> dict:
    try:
        data = json.loads((Path(session_dir) / STATUS_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def missed_count(analysis: dict) -> int:
    """① 목록의 수: 요청 기록(기억 관점)이 있으면 남은 것, 없으면 옛 빠짐 (요청 41)."""
    flow = analysis.get("flow") or {}
    if "requests" in flow:
        return sum(1 for r in flow["requests"] if r.get("state") in ("open", "deferred", "in_progress"))   # 진행 중도 남은 것 (요구 이력 66)
    return sum(1 for c in analysis.get("ledger", []) if c.get("status") == "missed")


def _similar(a: str, b: str) -> float:
    """두 글이 얼마나 비슷한지 (글자 두 개씩 묶은 조각의 겹침, 0~1). 분석기가 같은 뜻을 말만 바꿔 쓰는 일을 걸러 낸다."""
    def grams(x):
        x = "".join(str(x or "").split())
        return {x[i:i + 2] for i in range(max(1, len(x) - 1))}
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else float(a == b)
