"""Runtime compilation, installation, and destination protection."""
from pathlib import Path

import pytest

from simplecadapi.cli import main, run
from simplecadapi.skill import cli
from simplecadapi.skill.compiler import SkillBuildError, load_project


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    source = root / "source"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: demo\n---\nshared\n<!-- skill:if zcode -->\nzcode-only\n<!-- skill:endif -->\n",
        encoding="utf-8",
    )
    (source / "asset.bin").write_bytes(b"\xff\x00")
    (root / "skillproj.toml").write_text(
        '[skill]\nname="demo"\nsource="source"\n'
        '[build]\ntargets=["zcode", "codex"]\n'
        '[build.output]\nzcode="out/zcode"\ncodex="out/codex"\n',
        encoding="utf-8",
    )
    result = load_project(root)
    monkeypatch.setattr(cli, "bundled_project", lambda: result)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.delenv("SCA_SKILLS_DIR", raising=False)
    monkeypatch.delenv("SCA_ADDON_HOME", raising=False)
    return result


def install_args(*extra):
    return ["skill", "install", "--target", "zcode", *extra]


def test_targets(project):
    report, code, printer = run(["skill", "targets"])
    assert report == {"targets": ["zcode", "codex"]}
    assert code == 0 and callable(printer)
    printer(report)


@pytest.mark.parametrize("target, included", [("zcode", True), ("codex", False)])
def test_install_compiles_selected_target(project, tmp_path, target, included):
    report, code, _ = run(
        ["skill", "install", "--target", target, "--skills-dir", str(tmp_path / "skills")]
    )
    output = tmp_path / "skills" / "demo"
    text = (output / "SKILL.md").read_text()
    assert ("zcode-only" in text) == included
    assert "<!-- skill:" not in text
    assert (output / "asset.bin").read_bytes() == b"\xff\x00"
    assert Path(report["output"]) == output and code == 0


def test_install_default_location_without_init(project, tmp_path):
    report, code, _ = run(install_args())
    assert code == 0
    assert Path(report["output"]) == tmp_path / "home/.agents/skills/demo"
    assert not (tmp_path / "home/.sca").exists()


def test_install_location_precedence(project, tmp_path, monkeypatch):
    home = tmp_path / "home/.sca"
    home.mkdir(parents=True)
    (home / "config.toml").write_text(f'skills_dir="{tmp_path / "configured"}"\n')
    report, _, _ = run(install_args())
    assert Path(report["output"]) == tmp_path / "configured/demo"
    monkeypatch.setenv("SCA_SKILLS_DIR", str(tmp_path / "env"))
    report, _, _ = run(install_args())
    assert Path(report["output"]) == tmp_path / "env/demo"
    report, _, _ = run(install_args("--skills-dir", str(tmp_path / "flag")))
    assert Path(report["output"]) == tmp_path / "flag/demo"


def test_overwrite_requires_force_and_removes_stale_files(project, tmp_path):
    skills_dir = tmp_path / "skills"
    run(install_args("--skills-dir", str(skills_dir)))
    output = skills_dir / "demo"
    (output / "stale").write_text("old")
    with pytest.raises(SkillBuildError, match="--force"):
        run(install_args("--skills-dir", str(skills_dir)))
    assert (output / "stale").exists()
    run(install_args("--skills-dir", str(skills_dir), "--force"))
    assert not (output / "stale").exists()


@pytest.mark.parametrize("kind", ["directory", "file", "other-skill", "symlink"])
def test_force_rejects_foreign_destinations(project, tmp_path, kind):
    skills_dir = tmp_path / "skills"
    output = skills_dir / "demo"
    if kind == "file":
        output.parent.mkdir(parents=True)
        output.write_text("keep")
    elif kind == "symlink":
        output.parent.mkdir(parents=True)
        output.symlink_to(project.source, target_is_directory=True)
    else:
        output.mkdir(parents=True)
        if kind == "other-skill":
            (output / "SKILL.md").write_text("---\nname: other\n---\n")
    with pytest.raises(SkillBuildError, match="refusing"):
        run(install_args("--skills-dir", str(skills_dir), "--force"))
    assert output.exists()


def test_compilation_failure_preserves_destination(project, tmp_path):
    skills_dir = tmp_path / "skills"
    run(install_args("--skills-dir", str(skills_dir)))
    output = skills_dir / "demo"
    original = (output / "SKILL.md").read_bytes()
    (project.source / "SKILL.md").write_text("<!-- skill:if typo -->\nx\n<!-- skill:endif -->\n")
    with pytest.raises(SkillBuildError, match="unknown target"):
        run(install_args("--skills-dir", str(skills_dir), "--force"))
    assert (output / "SKILL.md").read_bytes() == original


def test_main_reports_unknown_target_without_traceback(project, tmp_path, capsys):
    code = main(["skill", "install", "--target", "typo", "--skills-dir", str(tmp_path / "s")])
    assert code == 2
    error = capsys.readouterr().err
    assert "unknown target" in error and "Traceback" not in error
    assert not (tmp_path / "s").exists()


def test_where_reports_the_destination_without_writing(project, tmp_path):
    report, code, printer = run(["skill", "where"])
    expected = tmp_path / "home" / ".agents" / "skills" / "demo"
    assert code == 0 and Path(report["where"]) == expected and report["exists"] is False
    assert not expected.parent.exists()  # nothing was created
    printer(report)
    run(install_args())
    assert run(["skill", "where"])[0]["exists"] is True
    elsewhere, _, _ = run(["skill", "where", "--skills-dir", str(tmp_path / "other")])
    assert Path(elsewhere["where"]) == tmp_path / "other" / "demo"


def test_where_reports_the_destination_without_writing(project, tmp_path):
    report, code, printer = run(["skill", "where"])
    expected = tmp_path / "home" / ".agents" / "skills" / "demo"
    assert code == 0 and Path(report["where"]) == expected and report["exists"] is False
    assert not expected.parent.exists()  # nothing was created
    printer(report)
    run(install_args())
    assert run(["skill", "where"])[0]["exists"] is True
    elsewhere, _, _ = run(["skill", "where", "--skills-dir", str(tmp_path / "other")])
    assert Path(elsewhere["where"]) == tmp_path / "other" / "demo"
