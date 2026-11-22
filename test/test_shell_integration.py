"""Unit tests for the ``sca init`` shell integration (shim + PATH wiring)."""

import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from simplecadapi.addon.shell import (
    BLOCK_BEGIN,
    _ensure_path_entry,
    console_script_target,
    integrate_shell,
    render_cmd_shim,
    render_posix_shim,
)
from simplecadapi.addon import shell


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _fake_install(root: Path, name: str = "venv") -> Path:
    """A fake venv whose bin/ holds the sca console script; returns python."""
    venv_bin = root / name / "bin"
    venv_bin.mkdir(parents=True)
    script = venv_bin / "sca"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    return venv_bin / "python3"


def _patch_interpreter(monkeypatch, python: Path) -> None:
    monkeypatch.setattr(shell, "sys", SimpleNamespace(platform="linux", executable=str(python)))


def test_integrate_writes_shim_and_zshenv_for_zsh(tmp_path, monkeypatch):
    _patch_interpreter(monkeypatch, _fake_install(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/zsh")
    chmod = Path.chmod
    calls = Mock(side_effect=chmod)
    monkeypatch.setattr(Path, "chmod", lambda path, mode: calls(path, mode))

    report = integrate_shell()
    shim = Path(report["shim"])
    assert shim == tmp_path / ".sca" / "bin" / "sca"
    calls.assert_called_once_with(shim, 0o755)
    if sys.platform != "win32":  # NTFS does not expose a POSIX execute bit
        assert shim.stat().st_mode & stat.S_IXUSR
    assert shim.read_text(encoding="utf-8").startswith("#!/bin/sh")
    assert str(tmp_path / "venv" / "bin" / "sca") in shim.read_text(encoding="utf-8")

    zshenv = (tmp_path / ".zshenv").read_text(encoding="utf-8")
    assert BLOCK_BEGIN in zshenv
    assert 'export PATH="$HOME/.sca/bin:$PATH"' in zshenv
    assert report["shell_blocks"][str(tmp_path / ".zshenv")] == "written"


def test_integrate_is_idempotent_and_refreshes_stale_shim(tmp_path, monkeypatch):
    _patch_interpreter(monkeypatch, _fake_install(tmp_path, "venv-a"))
    monkeypatch.setenv("SHELL", "/bin/zsh")
    first = integrate_shell()
    second = integrate_shell()
    assert second["shell_blocks"][str(tmp_path / ".zshenv")] == "present"
    zshenv = (tmp_path / ".zshenv").read_text(encoding="utf-8")
    assert zshenv.count(BLOCK_BEGIN) == 1

    _patch_interpreter(monkeypatch, _fake_install(tmp_path, "venv-b"))
    integrate_shell()
    shim = Path(first["shim"]).read_text(encoding="utf-8")
    assert str(tmp_path / "venv-b/bin/sca") in shim and "venv-a" not in shim


def test_bash_users_get_bashrc_and_no_zshenv(tmp_path, monkeypatch):
    _patch_interpreter(monkeypatch, _fake_install(tmp_path))
    monkeypatch.setenv("SHELL", "/bin/bash")
    (tmp_path / ".bashrc").write_text("# my rc\n", encoding="utf-8")

    report = integrate_shell()
    bashrc = (tmp_path / ".bashrc").read_text(encoding="utf-8")
    assert 'export PATH="$HOME/.sca/bin:$PATH"' in bashrc
    assert bashrc.startswith("# my rc\n")
    assert not (tmp_path / ".zshenv").exists()
    assert set(report["shell_blocks"]) == {str(tmp_path / ".bashrc")}


def test_fish_conf_d_file_when_fish_is_in_use(tmp_path, monkeypatch):
    _patch_interpreter(monkeypatch, _fake_install(tmp_path))
    monkeypatch.setenv("SHELL", "/usr/bin/fish")

    integrate_shell()
    fish_file = tmp_path / ".config" / "fish" / "conf.d" / "sca-path.fish"
    assert 'set -gx PATH "$HOME/.sca/bin" $PATH' in fish_file.read_text(encoding="utf-8")


def test_unknown_shell_writes_no_rc_files(tmp_path, monkeypatch):
    _patch_interpreter(monkeypatch, _fake_install(tmp_path))
    monkeypatch.setenv("SHELL", "")

    report = integrate_shell()
    assert report["shim"] is not None
    assert report["shell_blocks"] == {}


def test_missing_console_script_skips_with_a_note(tmp_path, monkeypatch):
    interpreter = tmp_path / "bare" / "python3"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("", encoding="utf-8")
    _patch_interpreter(monkeypatch, interpreter)
    monkeypatch.setenv("SHELL", "/bin/zsh")

    report = integrate_shell()
    assert report["shim"] is None
    assert report["notes"] and "shell integration" in report["notes"][0]
    assert not (tmp_path / ".zshenv").exists()


def test_posix_shim_fails_loudly_when_target_is_gone(tmp_path):
    shim_text = render_posix_shim(tmp_path / "gone" / "sca")
    assert "exit 127" in shim_text


def test_cmd_shim_references_target_and_passes_args(tmp_path):
    text = render_cmd_shim(tmp_path / "venv" / "Scripts" / "sca.exe")
    assert str(tmp_path / "venv" / "Scripts" / "sca.exe") in text
    assert "%*" in text


def test_windows_integration_installs_cmd_shim(tmp_path, monkeypatch):
    scripts = tmp_path / "venv/Scripts"
    scripts.mkdir(parents=True)
    target = scripts / "sca.exe"
    target.touch()
    monkeypatch.setattr(shell, "sys", SimpleNamespace(platform="win32", executable=str(scripts / "python.exe")))
    user_path = Mock(return_value={"windows_path": "appended"})
    monkeypatch.setattr(shell, "_windows_user_path", user_path)
    report = integrate_shell()
    shim = tmp_path / ".sca/bin/sca.cmd"
    assert report["shim"] == str(shim)
    assert shim.read_bytes() == render_cmd_shim(target).encode("utf-8")
    user_path.assert_called_once_with(shim.parent)
    assert report["windows_path"] == "appended"
    assert report["shell_blocks"] == {}


def test_ensure_path_entry_is_idempotent_and_case_insensitive():
    entries, changed = _ensure_path_entry(["C:\\Tools"], "C:\\Users\\x\\.sca\\bin")
    assert changed and entries == ["C:\\Users\\x\\.sca\\bin", "C:\\Tools"]

    entries, changed = _ensure_path_entry(["c:\\users\\x\\.sca\\bin"], "C:\\Users\\X\\.sca\\bin")
    assert not changed


def test_console_script_target_stays_inside_the_venv(tmp_path, monkeypatch):
    # venv interpreters are symlinks into a toolchain; the target must
    # stay next to the invoked path, not the resolved one
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    _patch_interpreter(monkeypatch, venv_bin / "python3")
    target = console_script_target(venv_bin / "python3")
    assert target == venv_bin / "sca"
