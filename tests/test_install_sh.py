"""install.sh 테스트: 네트워크 없이 도는 부분 (링크, PATH 블록, 훅 등록·제거, 삭제).

전체 설치(내려받기, pip)는 네트워크가 필요해 여기서 돌리지 않는다.
실제 HOME은 건드리지 않도록 HOME과 NUNCHI_* 환경변수를 모두 임시 폴더로 돌린다.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sandbox(tmp_path):
    """저장소 사본(직접 받아 둔 저장소 역할)과 가짜 HOME."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("install.sh", "pyproject.toml"):
        shutil.copy2(ROOT / name, repo / name)
    for d in ("bin", "control_tui", "hooks", "scripts"):
        shutil.copytree(ROOT / d, repo / d, ignore=shutil.ignore_patterns("__pycache__"))
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    rc = home / ".zshrc"
    rc.write_text("export FOO=1\n", encoding="utf-8")
    settings = home / ".claude" / "settings.json"
    settings.write_text('{"model": "x"}', encoding="utf-8")
    env = {
        "HOME": str(home), "PATH": "/usr/bin:/bin:" + os.path.dirname(shutil.which("python3")),
        "SHELL": "/bin/zsh", "NUNCHI_BIN": str(home / "bin"), "NUNCHI_RC": str(rc),
        "NUNCHI_CLAUDE_SETTINGS": str(settings),
        "CONTROL_TUI_HOME": str(home / ".claude-control"),
    }
    return {"repo": repo, "home": home, "rc": rc, "settings": settings, "env": env}


def sh(sb, *args):
    return subprocess.run(["sh", str(sb["repo"] / "install.sh"), *args], capture_output=True,
                          text=True, env=sb["env"], cwd=sb["home"], timeout=60,
                          start_new_session=True)  # 제어 터미널을 떼어 /dev/tty 질문이 뜨지 않게 한다


def test_help_lists_options(sandbox):
    res = sh(sandbox, "--help")
    assert res.returncode == 0
    for opt in ("--uninstall", "--link", "--path", "--hooks", "--yes"):
        assert opt in res.stdout


def test_unknown_option_fails(sandbox):
    assert sh(sandbox, "--nope").returncode != 0


def test_path_writes_one_marked_block(sandbox):
    sh(sandbox, "--path")
    sh(sandbox, "--path")
    text = sandbox["rc"].read_text(encoding="utf-8")
    assert text.count("# >>> nunchi >>>") == 1
    assert str(sandbox["home"] / "bin") in text
    assert text.startswith("export FOO=1\n")


def test_link_points_to_checkout_launcher(sandbox):
    res = sh(sandbox, "--link")
    assert res.returncode == 0, res.stderr
    link = sandbox["home"] / "bin" / "nunchi"
    assert link.is_symlink()
    assert Path(os.readlink(link)) == sandbox["repo"] / "bin" / "nunchi"
    where = subprocess.run([str(link), "--where"], capture_output=True, text=True)
    assert where.stdout.strip() == str(sandbox["repo"])


def test_link_refuses_to_replace_regular_file(sandbox):
    (sandbox["home"] / "bin").mkdir()
    (sandbox["home"] / "bin" / "nunchi").write_text("mine", encoding="utf-8")
    res = sh(sandbox, "--link")
    assert res.returncode != 0
    assert (sandbox["home"] / "bin" / "nunchi").read_text(encoding="utf-8") == "mine"


def test_hooks_without_tty_or_yes_changes_nothing(sandbox):
    res = sh(sandbox, "--hooks")
    assert res.returncode == 0
    assert sandbox["settings"].read_text(encoding="utf-8") == '{"model": "x"}'
    assert "바꾸지 않았습니다" in res.stdout


def test_uninstall_reverts_everything_and_keeps_checkout(sandbox):
    sh(sandbox, "--link")
    sh(sandbox, "--path")
    res = sh(sandbox, "--hooks", "--yes")
    assert res.returncode == 0, res.stderr
    assert "hooks/emit.sh" in sandbox["settings"].read_text(encoding="utf-8")

    res = sh(sandbox, "--uninstall", "--yes")
    assert res.returncode == 0, res.stderr
    assert json.loads(sandbox["settings"].read_text(encoding="utf-8")) == {"model": "x"}
    assert not (sandbox["home"] / "bin" / "nunchi").exists()
    assert sandbox["rc"].read_text(encoding="utf-8") == "export FOO=1\n"
    assert (sandbox["repo"] / "install.sh").exists()   # 직접 받아 둔 저장소는 남긴다


def test_uninstall_stops_when_hook_removal_declined(sandbox):
    sh(sandbox, "--link")
    sh(sandbox, "--hooks", "--yes")
    res = sh(sandbox, "--uninstall")          # tty도 --yes도 없음 → 묻지 못함
    assert res.returncode != 0
    assert (sandbox["home"] / "bin" / "nunchi").is_symlink()
    assert "hooks/emit.sh" in sandbox["settings"].read_text(encoding="utf-8")


def test_uninstall_stops_before_deleting_when_statusline_was_rewrapped(sandbox):
    sh(sandbox, "--link")
    sh(sandbox, "--hooks", "--yes")
    data = json.loads(sandbox["settings"].read_text(encoding="utf-8"))
    data["statusLine"]["command"] = "other-tool --wrap " + data["statusLine"]["command"]
    sandbox["settings"].write_text(json.dumps(data), encoding="utf-8")
    res = sh(sandbox, "--uninstall", "--yes")
    assert res.returncode != 0
    assert "statusLine" in res.stderr
    assert (sandbox["home"] / "bin" / "nunchi").is_symlink()   # 멈췄으니 링크도 그대로


def test_settings_moves_old_hooks_to_the_plugin_and_keeps_statusline(sandbox):
    """예전 설치가 넣은 훅은 빼고 상태 표시줄 감싸기만 둔다. 플러그인이 없으면 설치 명령을 보여 준다 (요구 이력 63)."""
    sh(sandbox, "--hooks", "--yes")
    res = sh(sandbox, "--settings", "--yes")
    assert res.returncode == 0, res.stderr
    data = json.loads(sandbox["settings"].read_text(encoding="utf-8"))
    assert "hooks" not in data
    assert "statusline.py" in data["statusLine"]["command"]
    assert "/plugin install nunchi --marketplace JeanTracker/nunchi" in res.stdout


def test_settings_without_tty_or_yes_changes_nothing(sandbox):
    sh(sandbox, "--hooks", "--yes")
    before = sandbox["settings"].read_text(encoding="utf-8")
    res = sh(sandbox, "--settings")
    assert res.returncode == 0
    assert sandbox["settings"].read_text(encoding="utf-8") == before
    assert "install.sh --settings" in res.stdout


def test_settings_reports_installed_plugin(sandbox):
    plugins = sandbox["home"] / ".claude" / "plugins"
    plugins.mkdir()
    (plugins / "installed_plugins.json").write_text('{"plugins": {"nunchi@nunchi": []}}', encoding="utf-8")
    res = sh(sandbox, "--settings", "--yes")
    assert res.returncode == 0, res.stderr
    assert "nunchi@nunchi: 설치됨" in res.stdout
