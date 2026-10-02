"""Tests for the unified ``sca`` entry point (:mod:`simplecadapi.cli`)."""

from importlib.metadata import entry_points
from pathlib import Path

import pytest

from simplecadapi.cli import run


@pytest.fixture(autouse=True)
def fake_user_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("SCA_ADDON_HOME", raising=False)
    monkeypatch.delenv("SCA_SKILLS_DIR", raising=False)
    return tmp_path


def test_init_group_runs_with_shell_integration(tmp_path, monkeypatch):
    # Pin the shell: the integration targets zsh only when SHELL says so
    # (or ~/.zshenv already exists); CI runners run bash.
    monkeypatch.setenv("SHELL", "/bin/zsh")
    report, code, printer = run(["init"])
    assert code == 0
    assert Path(report["home"]) == tmp_path / ".sca" / "addons"
    assert report["shell"]["shim"]
    assert (tmp_path / ".zshenv").is_file()
    assert callable(printer)


def test_init_no_shell_writes_no_shim(tmp_path):
    report, code, _ = run(["init", "--no-shell"])
    assert code == 0
    assert report["shell"] == {"skipped": True}
    assert not (tmp_path / ".sca" / "bin").exists()


def test_addon_group_dispatches(tmp_path):
    run(["init"])
    report, code, _ = run(["addon", "list"])
    assert code == 0
    assert report["addons"] == []


def test_cache_group_is_gone():
    # The part cache was removed; code is the only source of truth.
    with pytest.raises(SystemExit) as excinfo:
        run(["cache", "status"])
    assert excinfo.value.code == 2


def test_export_group_dispatches(tmp_path, monkeypatch):
    from simplecadapi.exporter import cli as export_cli

    package = type("P", (), {"root_kind": "part", "root_id": "part-bracket"})
    monkeypatch.setattr(export_cli, "read_product_package", lambda value: package)
    pkg = tmp_path / "bracket.scadpkg"
    pkg.write_bytes(b"stub")

    report, code, _ = run(
        ["export", str(pkg), "--check", "--output-dir", str(tmp_path / "out")]
    )
    assert code == 0
    assert report["ok"] is True
    assert set(report["formats"]) == {"step", "stl", "obj"}


def test_version_reports_the_sdk_version(capsys):
    from simplecadapi.addon.install import sca_version

    with pytest.raises(SystemExit) as excinfo:
        run(["--version"])
    assert excinfo.value.code == 0
    assert sca_version() in capsys.readouterr().out


def test_legacy_entry_points_are_gone():
    scripts = {ep.name for ep in entry_points(group="console_scripts")}
    assert "sca" in scripts
    assert "simplecad-cache" not in scripts
    assert "simplecad-export" not in scripts
