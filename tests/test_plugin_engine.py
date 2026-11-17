"""플러그인 구성 (요구 이력 63·69, BUILD_PLAN §4.12·§4.13).

훅은 모두 hooks/emit.sh를 거쳐 함께 실린 엔진으로 간다. 마켓플레이스는 엔진이 실린 배포용 브랜치를 가리킨다.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------- 플러그인 구성 ----------

def test_plugin_hooks_cover_every_event_once_and_point_at_files_that_exist():
    sys.path.insert(0, str(ROOT / "scripts"))
    import install_hooks
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert (ROOT / plugin["types"]).is_file()
    assert [(ROOT / "hooks" / m).resolve().is_file() for m in hooks["modules"]] == [True]
    assert sorted(hooks["hooks"]) == sorted(install_hooks.EVENTS)
    for groups in hooks["hooks"].values():
        assert [h["command"] for g in groups for h in g["hooks"]] == ['sh "${CLAUDE_PLUGIN_ROOT}/hooks/emit.sh"']
    # 플러그인은 배포용 브랜치에서 받는다: 엔진 실행 파일이 함께 실린 곳 (요구 이력 69)
    assert [(p["name"], p["source"]) for p in market["plugins"]] == [
        (plugin["name"], {"source": "github", "repo": "JeanTracker/nunchi", "ref": "dist"})]
