"""플러그인 환경에서 훅·분석기가 도는지 (요구 이력 63, BUILD_PLAN §4.12).

플러그인 캐시에는 .venv가 없다. 훅은 PATH의 python3로 돌고, 분석기도 그 파이썬으로 뜬다.
그래서 분석기가 읽는 코드는 textual 없이, 맥 기본 파이썬(3.9)에서도 읽혀야 한다.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 지금 파이썬과, 있으면 맥 기본 파이썬
PYTHONS = [sys.executable] + [p for p in ("/usr/bin/python3",) if Path(p).exists()]

# textual을 못 읽게 막고 시작한다 (설치돼 있어도 ImportError가 난다)
BLOCK = "import sys; sys.modules['textual'] = None\n"


def run_py(python, code, env=None):
    return subprocess.run([python, "-I", "-c", BLOCK + code], cwd=str(ROOT), capture_output=True,
                          text=True, timeout=30, env={**os.environ, **(env or {})})


@pytest.mark.parametrize("python", PYTHONS)
def test_analyzer_code_loads_without_textual(python, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"theme": "dusk", "analyze_workers": 2}))
    code = (f"sys.path.insert(0, {str(ROOT)!r})\n"
            "import control_tui.worker, control_tui.flow, control_tui.glossary, control_tui.transcript\n"
            "from control_tui import settings\n"
            f"st = settings.load({str(tmp_path)!r})\n"
            "print(st.theme, st.analyze_workers)\n")
    out = run_py(python, code)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["dusk", "2"]


@pytest.mark.parametrize("python", PYTHONS)
def test_stop_hook_queues_analysis_without_textual(python, tmp_path):
    home = tmp_path / "control"
    (home / "sessions" / "s1").mkdir(parents=True)
    (home / "sessions" / "s1" / "want").write_text(json.dumps({"on": True}))
    payload = json.dumps({"session_id": "s1", "hook_event_name": "Stop", "cwd": "/work/a",
                          "transcript_path": "/none.jsonl"})
    code = (f"sys.stdin = __import__('io').StringIO({payload!r})\n"
            f"sys.argv = [{str(ROOT / 'hooks' / 'emit.py')!r}]\n"
            "import runpy\n"
            "try:\n"
            f"    runpy.run_path({str(ROOT / 'hooks' / 'emit.py')!r}, run_name='__main__')\n"
            "except SystemExit as e:\n"
            "    sys.exit(e.code)\n")
    out = run_py(python, code, env={"CONTROL_TUI_HOME": str(home), "CONTROL_TUI_ANALYZE": "1",
                                    "CONTROL_TUI_WORKER": "0"})
    assert out.returncode == 0, out.stderr
    assert not (home / "errors.log").exists(), (home / "errors.log").read_text()
    assert (home / "queue" / "s1.json").exists()


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
