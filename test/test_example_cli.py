"""``sca example``: a bundled example workspace copied out for the editor."""
from pathlib import Path

import pytest

from simplecadapi.cli import main, run
from simplecadapi.runtime.workspace import scan_workspace


def test_without_a_name_the_examples_are_listed():
    report, code, printer = run(["example"])
    assert code == 0 and "u_link" in report["examples"]
    printer(report)


def test_copy_makes_a_workspace_the_editor_can_open(tmp_path, capsys):
    target = tmp_path / "demo"
    report, code, printer = run(["example", "u_link", str(target)])
    assert code == 0 and Path(report["path"]) == target
    assert report["edit"].startswith("sca edit ") and str(target) in report["edit"]
    entries = {entry.path: entry for entry in scan_workspace(target)}
    assert set(entries) == {"shell.py", "u_link.py", "u_link_motor_mount.py"}
    assert entries["u_link_motor_mount.py"].kind == "assembly"
    assert set(entries["u_link_motor_mount.py"].uses) == {"u_link.py", "shell.py"}
    printer(report)
    assert "open it:" in capsys.readouterr().out


def test_an_existing_directory_is_never_overwritten(tmp_path, capsys):
    target = tmp_path / "mine"
    target.mkdir()
    (target / "notes.txt").write_text("keep me")
    assert main(["example", "u_link", str(target)]) == 2
    assert "already exists" in capsys.readouterr().err
    assert [path.name for path in target.iterdir()] == ["notes.txt"]


def test_the_default_directory_is_the_examples_own_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report, _, _ = run(["example", "u_link"])
    assert Path(report["path"]) == tmp_path / "u_link_motor_mount"


def test_an_unknown_example_is_refused():
    with pytest.raises(SystemExit):
        run(["example", "nope"])
