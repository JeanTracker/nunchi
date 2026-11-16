"""목표 흐름: 원문 고정 연쇄 (요청 40, REQUIREMENTS R2, BUILD_PLAN §4.3, SCREEN §2 ② 머리).

- 분석 n = 분석 n-1의 흐름 + 대화 n 전체 + 찾아 온 원문. 응답이 끝날 때마다 새 턴만 이어 적는다.
- 앞 단계는 코드가 그대로 두고 모델 출력으로 덮지 않는다.
- 모든 항목에 원문 인용을 받아 코드가 대조한다. 맞지 않으면 한 번 다시 묻고, 그래도 안 되면
  그 턴은 요청 원문 앞부분으로 적고 주제 이동은 판단하지 않는다 (지어낸 말을 남기지 않음).
- 지금 목표는 상위 목표가 아니라 지금 다루는 구체적 대상이다. 대상이 바뀌면 다시 정하고
  앞 목표에서 넓힘·좁힘·옮김 중 어느 쪽인지와 이어진 방식을 한 줄로 남긴다 (실측: SCREEN §8).
"""

import json

from control_tui.analyzer import RELATIONS

VERSION = 3               # 2: 요청 기록(기억 관점), 3: 에이전트가 묻는 것 (요구 이력 41·45)
STATES = ("addressed", "open", "deferred", "superseded")   # 다룸, 아직 다루지 않음, 못 했거나 미룸, 뒤 요청이 대신함
DIGEST_CUT = 90
ASKS_SHOWN = 30           # 프롬프트에 넣는 열린 묻는 것 수
REQUESTS_SHOWN = 80       # 프롬프트에 넣는 지난 요청 수 (대신한 것은 빼고 최근 것부터)
DIRECTIONS = ("넓힘", "좁힘", "옮김")
QUOTE_MIN = 2
REQUEST_CUT = 3000        # 새 턴 요청
DOC_REQUEST_CUT = 800     # 찾아 온 원문: 턴마다 요청 앞부분
DOC_RESPONSE_TAIL = 600   # 찾아 온 원문: 응답 끝부분
SIMILAR_DOCS = 2          # 새 요청과 가장 비슷한 옛 턴 수
TITLE_CUT = 16            # 접힌 단계 요약 줄의 짧은 이름 (요청 41)
FALLBACK_CUT = 60         # 근거 확인에 실패한 턴은 요청 원문을 이만큼 적는다

HEAD = """너는 대화 흐름 기록기다. 사용자가 Claude Code 세션에서 에이전트와 나눈 대화의 '목표 흐름'을 한 턴씩 이어 적는다.
목적은 채점이 아니라, 사용자가 지금까지 어떤 대화를 이어 왔는지 빠르게 되짚게 하는 것이다. 에이전트가 틀린 답을 했어도 그 사실을 그대로 적는다.

반드시 지킬 것 (근거 없는 말 금지):
- 아래 '새 턴'과 '찾아 온 원문'에 있는 내용만 쓴다. 없는 사실, 추측, 일반 상식으로 채우지 마라.
- quote는 새 턴의 '요청:' 글에서, agent_quote는 새 턴의 '응답:' 글에서 글자 그대로 복사한 짧은 구절(5~40자)이다. 고쳐 쓰지 마라. 응답이 없으면 agent_quote는 빈 문자열.
- goal_quote는 goal_turn 번호 턴의 사용자 요청 글에서 글자 그대로 복사한 구절이다.
- 지난 흐름(앞 턴 항목)은 다시 쓰지 마라. 새 턴 항목 하나와 지금 목표만 낸다.
- label은 다음 중 하나: 시작, 구체화, 재정의, 정정, 범위 축소, 문제 제기, 확정, 질문. 지난 흐름과 찾아 온 원문을 보고 새 요청이 앞 흐름과 어떤 관계인지 정한다.
- current_goal은 상위 목표가 아니라 "지금 대화가 다루는 구체적 대상과 할 일"이다. 최근 요청만큼 구체적으로 쓴다. 프로젝트 전체를 감싸는 말로 넓히지 마라.
- 주제 판단: 새 요청이 다루는 대상(무엇을)이 지난 current_goal의 대상과 같으면 topic_shift는 false, current_goal과 goal_turn은 지난 것을 그대로 쓴다.
  대상이 달라졌으면 topic_shift는 true로 하고 current_goal을 새 대상으로 다시 정하고 goal_turn은 새 턴 번호로 한다. 같은 프로젝트 안이라는 이유로, 관계 이름이 구체화·질문이라는 이유로 같은 목표로 보지 마라.
  말투 요청('한글로'), 짧은 승인·정정처럼 대상이 그대로인 요청은 false다.
- topic_shift가 true면 goal_change를 채운다: direction은 넓힘(새 대상이 앞 대상을 그대로 포함하며 범위가 커짐), 좁힘(새 대상이 앞 대상의 일부), 옮김(앞 대상에서 나온 다른 대상) 중 하나. 넓힘은 새 요청이 앞 대상을 분명히 포함할 때만 쓴다.
  how는 "앞 목표 ○○에서 △△로 …" 꼴로 앞 목표와 새 목표가 어떻게 이어지는지 한 줄. quote는 그 근거가 되는 새 턴 '요청:' 글의 구절을 글자 그대로.
- 첫 턴이면 first_goal에 처음 목표를 쓰고 topic_shift는 false.
- title: 이 턴이 주제 이동이거나 관계가 확정이면 그 단계를 부르는 짧은 이름(16자 안, 예: "지침서 실측", "이어 쌓기로 결정"). 아니면 빈 문자열.
- decision: 관계가 확정이면 사용자가 이 턴에 정한 것 한 줄. 아니면 빈 문자열.
- digest: 처음부터 이 턴까지 대화가 어떻게 흘러왔는지 한 줄(90자 안). 지난 흐름과 새 턴만 보고 쓴다.

요청 기록 (채점하지 마라. 맞게 했는지가 아니라 다뤘는지 사실만 적는다):
- requests_new: 새 턴 사용자 글에서 나온 요청만(해 달라는 일, 지켜 달라는 조건). 요청 하나에 할 일이 여럿이면 나눈다.
  넣지 않는 것: 에이전트가 제안하거나 물은 일, '응'·'좋아'·'그대로 둬' 같은 승인·보류 답, 명령이나 시스템이 넣은 지시문. 사용자가 에이전트 제안에 답하며 새로 요구한 내용은 넣는다.
  quote는 새 턴 '요청:' 글에서 글자 그대로 복사한 구절.
  state: 새 턴 응답이 그 요청을 다뤘다고 말했으면 addressed, 못 했다·나중에·확인 못 했다고 밝혔으면 deferred, 언급이 없으면 open.
  agent_quote: addressed·deferred면 새 턴 '응답:' 글에서 그 근거를 글자 그대로 복사한 구절.
- requests_update: 지난 요청 기록 중 이번 턴에서 상태가 바뀐 것만(id 그대로). 바뀌지 않은 것은 넣지 마라.
  뒤 요청이 앞 요청을 바꾸거나 취소했으면 state는 superseded, superseded_by는 새 턴 번호. 나머지 칸은 requests_new와 같다.

에이전트가 묻는 것 (사용자가 세션에 돌아왔을 때 '지금 에이전트가 나에게 무엇을 묻나'를 알게 하려는 것):
- asks_new: 새 턴 '응답:' 글에서 에이전트가 사용자에게 결정·확인·정보를 구하고 그 답을 기다리는 것만.
  예: "~할까요?", "~할지 알려 주세요", "정해 주시면 ~", "확인해 주시면 ~하겠습니다", 선택지를 주고 고르게 하는 것.
  넣지 않는 것: 에이전트 자신의 진행 보고, 기다린다는 안내, 답이 없어도 되는 일반 제안, 설명 속 예문.
  한 문장에 묻는 것이 여럿이면 나눈다. summary는 사용자가 답할 것 한 줄(30자 안), quote는 응답 글에서 글자 그대로, kind는 결정·확인·정보 중 하나.
- asks_reask: 지난 묻는 것(아래 목록) 중 새 응답이 다시 묻는 것의 id. asks_new에 또 넣지 마라.
- asks_update: 지난 묻는 것 중 새 턴 '요청:' 글이 답한 것만. state는 answered 또는 partial, quote는 답이 된 요청 구절을 글자 그대로.
  요청이 '권장대로 진행', '반영해줘', '진행해', '응, 그렇게 해'처럼 바로 앞 응답의 제안·물음을 통째로 받아들이면, 바로 앞 턴에서 묻거나 다시 물은 것을 모두 answered로 하고 blanket을 true로, quote는 그 승인 구절로 한다.
  요청이 다른 이야기만 하고 답하지 않으면 넣지 마라(답 없음으로 남는다).

JSON 객체 하나만 출력하라. 설명, 코드 블록은 쓰지 마라.
{"turn": {"index": 0, "label": "", "summary": "사용자가 이 턴에 요청한 것 한 줄", "quote": "", "agent_summary": "에이전트가 이 턴에 한 말 한 줄", "agent_quote": "", "title": "", "decision": ""},
 "topic_shift": false, "goal_change": {"direction": "", "how": "", "quote": ""},
 "current_goal": "", "goal_turn": 0, "goal_quote": "", "first_goal": "", "digest": "",
 "requests_new": [{"summary": "", "quote": "", "state": "open", "agent_quote": ""}],
 "requests_update": [{"id": "R1", "state": "addressed", "agent_quote": "", "superseded_by": 0}],
 "asks_new": [{"summary": "", "quote": "", "kind": "결정"}], "asks_reask": ["Q1"],
 "asks_update": [{"id": "Q1", "state": "answered", "quote": "", "blanket": false}]}
"""


class FlowError(ValueError):
    pass


def _sq(text) -> str:
    return "".join(str(text or "").split())


def _one(text, limit=200) -> str:
    return " ".join(str(text or "").split())[:limit]


def _grams(text) -> set:
    x = _sq(text)
    return {x[i:i + 2] for i in range(max(1, len(x) - 1))} if x else set()


def _sim(a, b) -> float:
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


def _contains(quote, source) -> bool:
    q = _sq(quote)
    return len(q) >= QUOTE_MIN and q in _sq(source)


def fingerprint(turn) -> str:
    """턴이 같은 턴인지 알아보는 표시. 압축·되돌리기로 기록이 바뀌었는지 볼 때 쓴다."""
    return _sq(turn.request)[:40]


def retrieve(flow, turns: list, t) -> list:
    """찾아 올 원문의 턴 번호: 처음 목표 턴, 지금 목표 근거 턴, 직전 턴, 새 요청과 가장 비슷한 옛 턴."""
    k = t.index
    if k <= 1:
        return []
    goal_turn = ((flow or {}).get("current_goal") or {}).get("turn") or 1
    first_turn = ((flow or {}).get("first_goal") or {}).get("turn") or 1
    picks = [first_turn, goal_turn, k - 1]
    older = [x for x in turns if x.index < k - 1]
    older.sort(key=lambda x: -_sim(x.request, t.request))
    picks += [x.index for x in older[:SIMILAR_DOCS]]
    out = []
    for i in picks:
        if 1 <= i < k and i not in out:
            out.append(i)
    return sorted(out)


def build_prompt(flow, turns: list, t) -> str:
    by_index = {x.index: x for x in turns}
    past = {
        "first_goal": ((flow or {}).get("first_goal") or {}).get("text", ""),
        "current_goal": ((flow or {}).get("current_goal") or {}).get("text", ""),
        "goal_turn": ((flow or {}).get("current_goal") or {}).get("turn", 0),
        "turns": [{k: s.get(k, "") for k in ("index", "label", "summary", "agent_summary")}
                  for s in (flow or {}).get("steps", [])],
    }
    docs = []
    for i in retrieve(flow, turns, t):
        x = by_index.get(i)
        if x is None:
            continue
        tail = _one(x.final_response or x.response, 100000)[-DOC_RESPONSE_TAIL:]
        docs.append(f"[턴 {i}] 요청: {_one(x.request, DOC_REQUEST_CUT)}\n  응답 끝부분: {tail}")
    reqs = [r for r in (flow or {}).get("requests", []) if r.get("state") != "superseded"][-REQUESTS_SHOWN:]
    past_requests = [{"id": r["id"], "from_turn": r.get("from_turn"), "summary": r.get("summary", ""), "state": r.get("state")}
                     for r in reqs]
    open_asks = [{"id": a["id"], "turn": a.get("last_turn") or a.get("turn"), "summary": a.get("summary", ""), "state": a.get("state")}
                 for a in (flow or {}).get("asks", []) if a.get("state") != "answered"][-ASKS_SHOWN:]
    return (HEAD + "\n=== 지난 흐름 ===\n" + json.dumps(past, ensure_ascii=False)
            + "\n\n=== 지난 묻는 것 (아직 답이 다 오지 않은 것) ===\n" + (json.dumps(open_asks, ensure_ascii=False) if open_asks else "(없음)")
            + "\n\n=== 지난 요청 기록 ===\n" + (json.dumps(past_requests, ensure_ascii=False) if past_requests else "(없음)")
            + "\n\n=== 찾아 온 원문 ===\n" + ("\n".join(docs) or "(없음)")
            + f"\n\n=== 새 턴 ===\n[턴 {t.index}] 요청: {t.request.strip()[:REQUEST_CUT]}"
            + f"\n  응답: {(t.response or '').strip() or '(없음)'}\n")  # 새 턴 응답은 중간 글까지 전체, 길이 제한 없음 (요청 47)


def parse_step(text: str, flow, turns: list, t) -> dict:
    """모델 출력을 검사한다. 원문과 맞지 않는 인용이 하나라도 있으면 FlowError."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise FlowError("JSON이 없습니다")
    try:
        o = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise FlowError(f"JSON이 깨졌습니다: {e}") from e
    if not isinstance(o, dict):
        raise FlowError("형식이 다릅니다")
    tu = o.get("turn") if isinstance(o.get("turn"), dict) else {}
    by_index = {x.index: x for x in turns}
    label = tu.get("label", "")
    if label not in RELATIONS:
        raise FlowError(f"관계 이름이 정해진 것이 아닙니다: {label}")
    if not _contains(tu.get("quote"), t.request):
        raise FlowError("요청 인용이 원문에 없습니다")
    agent_quote = tu.get("agent_quote") or ""
    if (t.response or "").strip():
        if not _contains(agent_quote, t.response):
            raise FlowError("응답 인용이 원문에 없습니다")
    else:
        agent_quote = ""
    first = t.index == 1 or not (flow or {}).get("steps")
    shift = bool(o.get("topic_shift")) and not first
    try:
        goal_turn = int(o.get("goal_turn") or 0)
    except (TypeError, ValueError):
        goal_turn = 0
    prev_goal = ((flow or {}).get("current_goal") or {})
    if shift or first:
        goal_turn = t.index
    elif not goal_turn:
        goal_turn = prev_goal.get("turn") or t.index
    if goal_turn not in by_index or goal_turn > t.index:
        raise FlowError("목표 근거 턴 번호가 맞지 않습니다")
    goal_quote = o.get("goal_quote") or ""
    if not _contains(goal_quote, by_index[goal_turn].request):
        if not shift and not first and prev_goal.get("quote"):
            goal_quote = prev_goal["quote"]  # 목표가 그대로면 앞 근거를 그대로 쓴다
        else:
            raise FlowError("목표 인용이 원문에 없습니다")
    step = {
        "index": t.index, "label": label, "summary": _one(tu.get("summary")),
        "quote": _one(tu.get("quote"), 80), "agent_summary": _one(tu.get("agent_summary")),
        "agent_quote": _one(agent_quote, 80), "fp": fingerprint(t), "grounded": True, "shift": shift,
        "title": _one(tu.get("title"), TITLE_CUT),   # 짧은 이름·정한 것은 원문 대조를 못 하므로 화면에서 추정으로 보인다
        "decision": _one(tu.get("decision")) if label == "확정" else "",
    }
    goal_text = _one(o.get("current_goal"))
    if not shift and not first:
        goal_text = prev_goal.get("text") or goal_text  # 대상이 그대로면 지난 목표 글을 바꾸지 않는다
    if not goal_text:
        raise FlowError("지금 목표가 비었습니다")
    if shift:
        ch = o.get("goal_change") if isinstance(o.get("goal_change"), dict) else {}
        if ch.get("direction") not in DIRECTIONS:
            raise FlowError("방향이 넓힘·좁힘·옮김이 아닙니다")
        if not _contains(ch.get("quote"), t.request):
            raise FlowError("방향 근거 인용이 원문에 없습니다")
        step.update(direction=ch["direction"], how=_one(ch.get("how")), shift_quote=_one(ch.get("quote"), 80),
                    goal=goal_text, prev_goal=prev_goal.get("text", ""))
    step["digest"] = _one(o.get("digest"), DIGEST_CUT)   # 지금까지 한 줄 (mod, 추정)
    result = {"step": step, "current_goal": {"text": goal_text, "turn": goal_turn, "quote": _one(goal_quote, 80)},
              "requests": parse_requests(o, flow, t), "asks": parse_asks(o, flow, t)}
    if first:
        fg = _one(o.get("first_goal")) or goal_text
        result["first_goal"] = {"text": fg, "turn": t.index, "quote": _one(goal_quote, 80)}
    return result


def parse_requests(o, flow, t) -> dict:
    """요청 기록 변경을 검사한다. 원문과 맞지 않는 항목만 버리고 나머지는 남긴다 (요청 41, 기억 관점)."""
    known = {r["id"]: r for r in (flow or {}).get("requests", [])}
    new, updates, dropped = [], [], 0
    for item in o.get("requests_new") or []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        state = item.get("state") if item.get("state") in ("addressed", "open", "deferred") else "open"
        aq = item.get("agent_quote") or ""
        if not _contains(item.get("quote"), t.request) or (state != "open" and aq and not _contains(aq, t.response)):
            dropped += 1
            continue
        new.append({"summary": _one(item.get("summary")), "quote": _one(item.get("quote"), 80), "state": state,
                    "agent_quote": _one(aq, 80) if state != "open" else ""})  # 도구는 보지 않는다 (요청 48)
    for item in o.get("requests_update") or []:
        if not isinstance(item, dict) or item.get("id") not in known or item.get("state") not in STATES:
            dropped += 1
            continue
        aq = item.get("agent_quote") or ""
        if item["state"] in ("addressed", "deferred") and aq and not _contains(aq, t.response):
            dropped += 1
            continue
        updates.append({"id": item["id"], "state": item["state"], "agent_quote": _one(aq, 80),
                        "superseded_by": t.index if item["state"] == "superseded" else 0})
    return {"new": new, "updates": updates, "dropped": dropped}


def parse_asks(o, flow, t) -> dict:
    """묻는 것 변경을 검사한다 (요구 이력 45). 원문과 맞지 않거나 없는 번호는 그 항목만 버린다."""
    known = {a["id"]: a for a in (flow or {}).get("asks", [])}
    new, reask, updates, dropped = [], [], [], 0
    for n in o.get("asks_new") or []:
        if isinstance(n, dict) and _contains(n.get("quote"), t.response):
            kind = n.get("kind") if n.get("kind") in ("결정", "확인", "정보") else "확인"
            new.append({"summary": _one(n.get("summary"), 60), "quote": _one(n.get("quote"), 80), "kind": kind})
        else:
            dropped += 1
    for i in o.get("asks_reask") or []:
        if i in known and known[i].get("state") != "answered":
            reask.append(i)
        else:
            dropped += 1
    for u in o.get("asks_update") or []:
        if (isinstance(u, dict) and u.get("id") in known and u.get("state") in ("answered", "partial")
                and _contains(u.get("quote"), t.request)):
            updates.append({"id": u["id"], "state": u["state"], "quote": _one(u["quote"], 80), "blanket": bool(u.get("blanket"))})
        else:
            dropped += 1
    return {"new": new, "reask": reask, "updates": updates, "dropped": dropped}


def apply_asks(asks: list, change: dict, t) -> list:
    """묻는 것에 이번 턴 변경을 더한다. 답은 이번 턴 요청이, 새로 묻거나 다시 묻는 것은 이번 턴 응답이 준다."""
    out = [dict(a) for a in asks]
    by_id = {a["id"]: a for a in out}
    for u in change.get("updates", []):
        a = by_id.get(u["id"])
        if a is not None:
            a.update(state=u["state"], answered_at=t.index, answer_quote=u["quote"], by_blanket=u["blanket"])
    for i in change.get("reask", []):
        a = by_id.get(i)
        if a is not None and a.get("state") != "answered":
            a["last_turn"] = t.index
    for n in change.get("new", []):
        out.append(dict(n, id=f"Q{len(out) + 1}", turn=t.index, last_turn=t.index, state="open"))
    return out


def apply_requests(requests: list, change: dict, t) -> list:
    """요청 기록에 이번 턴 변경을 더한다. 번호·요약·사용자 원문은 처음 그대로 둔다."""
    out = [dict(r) for r in requests]
    by_id = {r["id"]: r for r in out}
    for u in change.get("updates", []):
        r = by_id.get(u["id"])
        if r is None:
            continue
        r["state"], r["by_turn"] = u["state"], t.index
        if u.get("agent_quote"):
            r["agent_quote"] = u["agent_quote"]
        r.pop("tool_failed", None)  # 옛 기록의 도구 실패 표시는 버린다 (요청 48)
        if u["state"] == "superseded":
            r["superseded_by"] = u["superseded_by"]
    for n in change.get("new", []):
        out.append(dict(n, id=f"R{len(out) + 1}", from_turn=t.index, by_turn=t.index))
    return out


def _fallback(flow, t) -> dict:
    """근거 확인에 두 번 실패한 턴: 요청 원문 앞부분을 사실로 적고 주제 이동은 판단하지 않는다."""
    head = _one(t.request, FALLBACK_CUT)
    step = {"index": t.index, "label": "", "summary": head, "quote": head, "agent_summary": "", "agent_quote": "",
            "fp": fingerprint(t), "grounded": False, "shift": False}
    result = {"step": step}
    if not (flow or {}).get("steps"):
        result["first_goal"] = {"text": head, "turn": t.index, "quote": head}
        result["current_goal"] = {"text": head, "turn": t.index, "quote": head}
    return result


def empty() -> dict:
    return {"version": VERSION, "first_goal": {}, "current_goal": {}, "steps": [], "requests": [], "asks": [], "until": 0}


def migrate(flow, turns: list):
    """옛 형식 흐름을 지금 형식으로 옮겨 담는다 (요구 이력 44·45): 단계는 그대로 두고, 새로 생긴 기록만 다음 턴부터 쌓는다.
    호출 없이 끝난다. 옮겨 담기 전 턴의 요청·묻는 것은 기록에 없다는 것을 requests_from·asks_from으로 남긴다."""
    if not isinstance(flow, dict) or flow.get("version") not in (1, 2):
        return flow
    start = (flow.get("until") or 0) + 1
    moved = dict(flow, version=VERSION)
    if flow.get("version") == 1:
        moved.update(requests=[], requests_from=start)
    moved.update(asks=[], asks_from=start)
    return moved if valid_for(moved, turns) else flow


def open_asks(flow) -> list:
    """아직 답이 다 오지 않은 묻는 것 (최근에 물은 것부터)."""
    left = [a for a in (flow or {}).get("asks", []) if a.get("state") != "answered"]
    return sorted(left, key=lambda a: -(a.get("last_turn") or a.get("turn") or 0))


def valid_for(flow, turns: list) -> bool:
    """저장된 흐름을 이 기록에 이어 적을 수 있는지. 형식이 다르거나 기록이 바뀌었으면 처음부터 다시."""
    if not isinstance(flow, dict) or flow.get("version") != VERSION:
        return False
    until = flow.get("until") or 0
    if until == 0:
        return True
    by_index = {x.index: x for x in turns}
    last = by_index.get(until)
    steps = flow.get("steps") or []
    return last is not None and bool(steps) and steps[-1].get("index") == until and steps[-1].get("fp") == fingerprint(last)


def advance(flow, turns: list, t, runner, tries: int = 2) -> dict:
    """흐름에 턴 t를 이어 적은 새 흐름을 돌려준다. 앞 단계는 그대로 복사한다."""
    base = flow if flow and flow.get("steps") else empty()
    prompt = build_prompt(base, turns, t)
    got = None
    for _ in range(tries):
        try:
            got = parse_step(runner(prompt), base, turns, t)
            break
        except FlowError:
            continue
    if got is None:
        got = _fallback(base, t)
    new = {"version": VERSION, "first_goal": dict(base.get("first_goal") or {}),
           "current_goal": dict(base.get("current_goal") or {}),
           "steps": [dict(s) for s in base.get("steps", [])] + [got["step"]],
           "requests": apply_requests(base.get("requests", []), got.get("requests") or {}, t),
           "asks": apply_asks(base.get("asks", []), got.get("asks") or {}, t), "until": t.index}
    if got.get("requests") is None:
        new["steps"][-1]["requests_checked"] = False   # 이 턴 요청은 확인하지 못함 (원문 대조 실패)
    for key in ("requests_from", "asks_from"):   # 옮겨 담은 흐름이면 기록이 어디서 시작했는지 그대로 (요구 이력 44·45)
        if base.get(key):
            new[key] = base[key]
    if got.get("first_goal"):
        new["first_goal"] = got["first_goal"]
    if got.get("current_goal"):
        new["current_goal"] = got["current_goal"]
    return new


def remaining(flow) -> list:
    """남은 것: 아직 다루지 않음, 못 했거나 미룸 (요청 41)."""
    return [r for r in (flow or {}).get("requests", []) if r.get("state") in ("open", "deferred")]


def shifts(flow) -> list:
    return [s for s in (flow or {}).get("steps", []) if s.get("shift")]
