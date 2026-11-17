"""파이썬 엔진 단위 시험이 부른 흐름·번호 풀이 함수의 입력과 결과를 모은다 (요구 이력 68, BUILD_PLAN §4.13).

    NUNCHI_RECORD=1 .venv/bin/python -m pytest -q -p tests.record_engine_cases \\
        tests/test_flow_chain.py tests/test_flow_grown.py tests/test_in_progress.py tests/test_glossary.py

결과는 crates/engine/tests/golden/{flow,glossary}_cases.jsonl. `cargo test`가 러스트 엔진으로 같은 입력을 다시 돌려
같은 결과가 나오는지 본다. 파이썬 엔진을 지운 뒤에도 그 시험들이 확인하던 동작이 남는다.
시험의 합성 입력만 담긴다(실제 대화 기록은 담지 않는다).
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "crates" / "engine" / "tests" / "golden"
_cases = {"flow": {}, "glossary": {}}


def _turn(t):
    return {k: getattr(t, k, "" if k != "index" else 0) or ("" if k != "index" else 0)
            for k in ("index", "request", "response", "final_response")}


def _turns(turns):
    return [_turn(t) for t in turns or []]


def _plain(v):
    return json.loads(json.dumps(v, ensure_ascii=False, default=str))


def _add(kind, case):
    key = json.dumps(case, ensure_ascii=False, sort_keys=True)
    _cases[kind].setdefault(key, case)


def pytest_configure(config):
    if os.environ.get("NUNCHI_RECORD") != "1":
        return
    from control_tui import flow as F, glossary as G

    def wrap(name, record):
        orig = getattr(F, name)

        def inner(*a, **kw):
            try:
                result = orig(*a, **kw)
            except F.FlowError:
                record(a, kw, {"flow_error": True})
                raise
            record(a, kw, result)
            return result
        setattr(F, name, inner)

    def simple(name, argnames):
        def record(a, kw, result):
            args = dict(zip(argnames, a), **kw)
            case = {"fn": name, "result": _plain(result)}
            for k, v in args.items():
                case[k] = _turns(v) if k == "turns" else _turn(v) if k == "t" else _plain(v)
            _add("flow", case)
        wrap(name, record)

    simple("build_prompt", ["flow", "turns", "t"])
    simple("parse_step", ["text", "flow", "turns", "t"])
    simple("grown", ["flow", "turns"])
    simple("valid_for", ["flow", "turns"])
    simple("migrate", ["flow", "turns"])
    simple("retrieve", ["flow", "turns", "t"])

    orig_advance = F.advance

    def advance(flow, turns, t, runner, tries=2):
        outputs, raised = [], []

        def rec_runner(prompt):
            try:
                out = runner(prompt)
            except Exception:
                raised.append(True)
                raise
            outputs.append(out)
            return out
        case = {"fn": "advance", "flow": _plain(flow), "turns": _turns(turns), "t": _turn(t), "tries": tries}
        try:
            result = orig_advance(flow, turns, t, rec_runner, tries)
        except Exception:
            _add("flow", dict(case, outputs=outputs, raises=True, result=None))
            raise
        _add("flow", dict(case, outputs=outputs, raises=False, result=_plain(result)))
        return result
    F.advance = advance

    orig_explain = G.explain

    def explain(text, cwd, limit=G.LIMIT):
        docs = {}
        for f in sorted(Path(cwd or ".").glob(G.DOC_GLOB)):
            if f.is_file():
                docs[f.name] = f.read_text(encoding="utf-8")
        result = orig_explain(text, cwd, limit)
        if limit == G.LIMIT:
            _add("glossary", {"text": text, "docs": docs, "result": _plain(result),
                              "find": _plain(G.find(text, with_hints=True))})
        return result
    G.explain = explain


def pytest_unconfigure(config):
    if os.environ.get("NUNCHI_RECORD") != "1":
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for kind, cases in _cases.items():
        keys = sorted(cases)   # 정렬해 두면 다시 모아도 차이가 줄어든다. 각 사례는 키 순서를 그대로 둔다
        (OUT / f"{kind}_cases.jsonl").write_text("".join(json.dumps(cases[k], ensure_ascii=False) + "\n" for k in keys),
                                                 encoding="utf-8")
        print(f"\n{kind}: {len(cases)} cases")
