from pathlib import Path

from simplecadapi.exporter import cli


class _Package:
    root_kind = "part"
    root_id = "part-bracket"


def test_check_defaults_to_step_stl_and_obj(monkeypatch, tmp_path: Path):
    input_path = tmp_path / "bracket.scadpkg"
    monkeypatch.setattr(cli, "read_product_package", lambda value: _Package())

    report, exit_code = cli.run(["export", str(input_path), "--check", "--output-dir", str(tmp_path / "out")])

    assert exit_code == 0
    assert report["check_only"] is True
    assert set(report["formats"]) == {"step", "stl", "obj"}
    assert report["formats"]["step"]["output"].endswith("bracket.step")
    assert report["formats"]["stl"]["output"].endswith("bracket.stl")
    assert report["formats"]["obj"]["output"].endswith("bracket.obj")


def test_check_mjcf_requires_assembly(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli, "read_product_package", lambda value: _Package())

    report, exit_code = cli.run(["export", str(tmp_path / "part.scadpkg"), "--format", "mjcf", "--check"])

    assert exit_code == 1
    assert report["formats"]["mjcf"]["ok"] is False


def test_check_rejects_unknown_package_extension(tmp_path: Path):
    try:
        cli.run(["export", str(tmp_path / "part.json"), "--check"])
    except ValueError as exc:
        assert ".scadpkg" in str(exc)
    else:
        raise AssertionError("expected .scadpkg validation error")


def test_output_override_requires_selected_optional_format(tmp_path: Path):
    try:
        cli.run(["export", str(tmp_path / "part.scadpkg"), "--check", "--output", "mjcf=part.xml"])
    except ValueError as exc:
        assert "--format" in str(exc)
    else:
        raise AssertionError("expected unselected format validation error")
