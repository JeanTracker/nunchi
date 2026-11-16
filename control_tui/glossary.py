"""번호 풀이 (요구 이력 51, REQUIREMENTS R1·R17, SCREEN §2 ② 마지막 대화·§11).

에이전트 응답에 나온 기획 번호(R17, §4.5, Phase 4c, 요구 이력 41 등)를 세션 폴더의 프로젝트 문서에서 찾아
문서 원문 그대로 풀어 준다. LLM은 쓰지 않는다. 문서에서 못 찾은 번호는 '문서에 없음'.

사전 출처 (이 프로젝트 문서 형식, 다른 프로젝트는 같은 꼴이 있을 때만 풀린다):
- 표의 첫 칸이 R 번호인 줄: `| R17 | 뜻 | …`
- 표의 첫 칸이 숫자(또는 1~3 같은 범위)인 줄: 요구 이력 `| 41 | 요청 핵심 | …`
- 표의 첫 칸이 `4b.` 같은 단계: `| 4b. 이름 | …` → Phase 4b
- 제목 줄 `## 4.5 제목`, `### 4.5 제목` → §4.5 (문서 이름을 앞에 붙인다)
"""

import re
from pathlib import Path

DOC_GLOB = "docs/*.md"
LIMIT = 5
MEAN_CUT = 90
ID_RE = re.compile(r"(?<![A-Za-z0-9])(R\d{1,2})(?:~(R?\d{1,2}))?(?![0-9A-Za-z])|§\s?(\d+(?:\.\d+)*)|Phase\s?(\d+[a-z]?)(?![0-9A-Za-z])|(?:요구 이력|요청) (\d+)(?![0-9])")
# 한글 조사가 바로 붙는 경우('R4도', 'R17까지')도 잡도록 낱말 경계 대신 영문·숫자 앞뒤만 막는다

_cache: dict = {}   # 프로젝트 폴더 -> (문서 수정 시각들, 사전)


def _one(text: str, cut: int = MEAN_CUT) -> str:
    t = " ".join(str(text or "").replace("**", "").replace("~~", "").split())
    return t if len(t) <= cut else t[:cut - 1] + "…"


def _doc_label(path: Path, text: str) -> str:
    m = re.search(r"^# (.+)$", text, re.M)
    title = m.group(1).split(":")[0].strip() if m else path.stem
    return title


def build(cwd) -> dict:
    """프로젝트 폴더의 문서로 '번호 → 뜻 목록' 사전을 만든다. 문서가 바뀌지 않았으면 다시 읽지 않는다."""
    root = Path(cwd or ".")
    files = sorted(root.glob(DOC_GLOB))
    stamp = tuple((str(f), f.stat().st_mtime) for f in files if f.is_file())
    hit = _cache.get(str(root))
    if hit and hit[0] == stamp:
        return hit[1]
    terms: dict = {}

    def add(key: str, mean: str) -> None:
        mean = _one(mean)
        if mean and mean not in terms.setdefault(key, []):
            terms[key].append(mean)

    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        label = _doc_label(f, text)
        for m in re.finditer(r"^\| (R\d+) \| ([^|]+)\|", text, re.M):
            add(m.group(1), m.group(2))
        for m in re.finditer(r"^\| (\d+)(?:~(\d+))? \| ([^|]+)\|", text, re.M):
            a, b = int(m.group(1)), int(m.group(2) or m.group(1))
            if b - a <= 20:
                for n in range(a, b + 1):
                    add(f"요구 이력 {n}", m.group(3))
        for m in re.finditer(r"^\| (\d+[a-z]?)\. ([^|]+)\|", text, re.M):
            add(f"Phase {m.group(1)}", m.group(2))
        for m in re.finditer(r"^#{2,3} (\d+(?:\.\d+)*)\.? (.+)$", text, re.M):
            add(f"§{m.group(1)}", f"{label}: {m.group(2)}")
    _cache[str(root)] = (stamp, terms)
    return terms


DOC_HINTS = (("화면", "화면구성"), ("SCREEN", "화면구성"), ("구현", "구현 계획"), ("BUILD_PLAN", "구현 계획"),
             ("요구사항", "요구사항"), ("REQUIREMENTS", "요구사항"))


def _hint(text: str, start: int) -> str:
    """번호 바로 앞(20자)에 문서 이름이 있으면 그 문서 ('화면 문서 §8' → 화면구성)."""
    before = text[max(0, start - 20):start]
    for word, label in DOC_HINTS:
        if word in before:
            return label
    return ""


def find(text: str, with_hints: bool = False) -> list:
    """응답에 나온 번호를 처음 나온 순서로 (같은 번호는 한 번). 범위(R1~R16)는 한 덩어리로."""
    out, hints = [], {}
    for m in ID_RE.finditer(text or ""):
        r, r_to, sec, phase, hist = m.groups()
        if r and r_to:
            key = f"{r}~R{r_to.lstrip('R')}"
        elif r:
            key = r
        elif sec:
            key = f"§{sec}"
        elif phase:
            key = f"Phase {phase}"
        else:
            key = f"요구 이력 {hist}"
        if key not in out:
            out.append(key)
            hints[key] = _hint(text, m.start())
    return [(k, hints[k]) for k in out] if with_hints else out


def explain(text: str, cwd, limit: int = LIMIT) -> dict:
    """{'items': [{'id', 'means': [...]}], 'total': n}. 뜻이 없으면 means는 빈 목록('문서에 없음')."""
    ids = find(text, with_hints=True)
    if not ids:
        return {"items": [], "total": 0}
    terms = build(cwd)
    if not terms:
        return {"items": [], "total": 0}   # 사전 문서가 없는 프로젝트: 풀이 블록을 두지 않는다
    items = []
    for key, hint in ids[:limit]:
        if "~" in key and key.startswith("R"):
            a, b = key.split("~")
            means = [f"요구사항 {a}부터 {b}까지 전체"]
        else:
            means = list(terms.get(key, []))
            picked = [x for x in means if hint and x.startswith(hint + ":")]
            means = picked or means   # 앞에 문서 이름이 있으면 그 문서 것만
        items.append({"id": key, "means": means})
    return {"items": items, "total": len(ids)}
