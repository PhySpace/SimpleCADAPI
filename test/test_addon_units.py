"""Unit tests for the addon manager: descriptor, versions, platforms, tarball
safety, runtime probes, and source parsing."""

from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

import pytest

from simplecadapi.addon import AddonError
from simplecadapi.addon.descriptor import load_descriptor
from simplecadapi.addon.install import (
    GitHubSource,
    LocalSource,
    _safe_extract_tarball,
    parse_source,
    run_check_cmd,
)
from simplecadapi.addon.platforms import detect_platform
from simplecadapi.addon.versions import VersionRange, VersionSpecError, compare_versions


# ---------------------------------------------------------------- versions


def test_range_boundaries_match_padding_semantics():
    parsed = VersionRange.parse(">=2.1,<3")
    assert parsed.matches("2.1")
    assert parsed.matches("2.1.0")
    assert parsed.matches("2.9.9")
    assert not parsed.matches("2.0.9")
    assert not parsed.matches("3")
    assert not parsed.matches("3.0.0")


def test_bare_version_clause_means_exact_match():
    parsed = VersionRange.parse("2.1.2")
    assert parsed.matches("2.1.2")
    assert parsed.matches("2.1.2.0")
    assert not parsed.matches("2.1")
    assert not parsed.matches("2.1.3")


def test_prerelease_suffix_sorts_before_release():
    assert compare_versions("2.0.4b2", "2.0.4") == -1
    assert compare_versions("2.0.4", "2.0.4b2") == 1
    assert compare_versions("2.1.2", "2.1.2") == 0


def test_post_release_sorts_after_its_release_and_before_the_next():
    # the SDK itself is released as 2.2.6.post1 (PEP 440): compat ranges are
    # checked against that version
    assert compare_versions("2.2.6.post1", "2.2.6") == 1
    assert compare_versions("2.2.6", "2.2.6.post1") == -1
    assert compare_versions("2.2.6.post2", "2.2.6.post1") == 1
    assert compare_versions("2.2.6.post10", "2.2.6.post2") == 1
    assert compare_versions("2.2.7", "2.2.6.post9") == 1
    assert compare_versions("2.2.6.post1", "2.2.6.post1") == 0
    assert compare_versions("2.2.6b2", "2.2.6.post1") == -1


def test_ranges_hold_for_a_post_release():
    assert VersionRange.parse(">=2.2.6,<2.2.7").matches("2.2.6.post1")
    assert VersionRange.parse("==2.2.6.post1").matches("2.2.6.post1")
    assert not VersionRange.parse("<=2.2.6").matches("2.2.6.post1")
    assert not VersionRange.parse(">=2.2.7").matches("2.2.6.post1")


@pytest.mark.parametrize(
    "spec", ["", "  ", "*", "2.*", ">=2.1,,3", ">=", "==x.y", "v2.1", "2.2.post", "2.2.postx"]
)
def test_invalid_specs_are_rejected_with_named_error(spec):
    with pytest.raises(VersionSpecError):
        VersionRange.parse(spec)


@pytest.mark.parametrize(
    "spec", [">=2.1,<2.0", ">2.0,<2.0", "==2.1,==2.2", "==2.1,>=2.2"]
)
def test_conflicting_clauses_are_rejected(spec):
    with pytest.raises(VersionSpecError):
        VersionRange.parse(spec)


def test_nonconflicting_adjacent_bounds_are_accepted():
    assert VersionRange.parse(">=2.0,<=2.0").matches("2.0")
    assert VersionRange.parse(">2.0,<2.1").matches("2.0.5")


# --------------------------------------------------------------- platforms


@pytest.mark.parametrize(
    "system,machine,expected",
    [
        ("Darwin", "arm64", "macos-arm64"),
        ("Darwin", "x86_64", "macos-x86_64"),
        ("Linux", "x86_64", "linux-x86_64"),
        ("Linux", "aarch64", "linux-aarch64"),
        ("Windows", "AMD64", "windows-x86_64"),
    ],
)
def test_detect_platform_maps_aliases(system, machine, expected):
    assert detect_platform(system=system, machine=machine) == expected


def test_detect_platform_unknown_names_both_raw_values():
    with pytest.raises(AddonError) as err:
        detect_platform(system="FreeBSD", machine="riscv64")
    message = str(err.value)
    assert "freebsd" in message
    assert "riscv64" in message


# --------------------------------------------------------------- descriptor


def _write_descriptor(root: Path, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "sca-addon.toml").write_text(body, encoding="utf-8")
    return root


DESCRIPTOR_NONE = """\
[addon]
name = "demo-addon"
version = "0.1.0"
license = "MIT"
skill_path = "skill"

[compat]
sca = ">=2.0,<99"

[runtime]
kind = "none"
"""

DESCRIPTOR_BINARY = """\
[addon]
name = "ccx-fem"
version = "0.3.1"
license = "Apache-2.0"
skill_path = "skill"

[compat]
sca = ">=2.1,<3"

[runtime]
kind = "binary"
platforms = ["macos-arm64", "linux-x86_64"]
check_cmd = "ccx -v"

[runtime.check_overrides]
"linux-x86_64" = "ccx --version"
"""


def test_descriptor_happy_path_kind_none(tmp_path):
    descriptor = load_descriptor(_write_descriptor(tmp_path, DESCRIPTOR_NONE))
    assert descriptor.name == "demo-addon"
    assert descriptor.runtime_kind == "none"
    assert descriptor.platforms == ()
    assert descriptor.check_cmd is None
    assert descriptor.check_overrides == {}


def test_descriptor_happy_path_binary_with_overrides(tmp_path):
    descriptor = load_descriptor(_write_descriptor(tmp_path, DESCRIPTOR_BINARY))
    assert descriptor.platforms == ("macos-arm64", "linux-x86_64")
    assert descriptor.check_cmd == "ccx -v"
    assert descriptor.check_overrides == {"linux-x86_64": "ccx --version"}


def test_descriptor_missing_file_names_the_path(tmp_path):
    with pytest.raises(AddonError) as err:
        load_descriptor(tmp_path)
    assert "sca-addon.toml" in str(err.value)


@pytest.mark.parametrize(
    "mutation,expected_fragment",
    [
        ('name = "Demo Addon"', "name"),
        ('skill_path = "/abs/skill"', "relative"),
        ('skill_path = "../skill"', "relative"),
        ('sca = ">=2.1,<=2.0"', "conflict"),
        ('version = "x.y"', "version"),
        ('kind = "web"', "kind"),
    ],
)
def test_descriptor_field_rejections(tmp_path, mutation, expected_fragment):
    body = DESCRIPTOR_BINARY
    for old in (
        'name = "ccx-fem"',
        'skill_path = "skill"',
        'sca = ">=2.1,<3"',
        'version = "0.3.1"',
        'kind = "binary"',
    ):
        if mutation.split(" = ")[0] == old.split(" = ")[0]:
            body = body.replace(old, mutation)
            break
    with pytest.raises(AddonError) as err:
        load_descriptor(_write_descriptor(tmp_path, body))
    assert expected_fragment in str(err.value)


def test_descriptor_unknown_table_and_key_rejected(tmp_path):
    body = DESCRIPTOR_NONE + "\n[extra]\nkey = 1\n"
    with pytest.raises(AddonError) as err:
        load_descriptor(_write_descriptor(tmp_path, body))
    assert "extra" in str(err.value)

    body = DESCRIPTOR_NONE.replace('license = "MIT"', 'license = "MIT"\nbonus = "x"')
    with pytest.raises(AddonError) as err:
        load_descriptor(_write_descriptor(tmp_path, body))
    assert "bonus" in str(err.value)


def test_descriptor_platform_rules_per_kind(tmp_path):
    # binary without platforms
    body = DESCRIPTOR_BINARY.replace(
        'platforms = ["macos-arm64", "linux-x86_64"]\n', ""
    )
    with pytest.raises(AddonError) as err:
        load_descriptor(_write_descriptor(tmp_path, body))
    assert "platforms" in str(err.value)

    # binary without check_cmd
    body = DESCRIPTOR_BINARY.replace('check_cmd = "ccx -v"\n', "")
    with pytest.raises(AddonError) as err:
        load_descriptor(_write_descriptor(tmp_path, body))
    assert "check_cmd" in str(err.value)

    # none with platforms
    body = DESCRIPTOR_NONE.replace('kind = "none"', 'kind = "none"\nplatforms = ["linux-x86_64"]')
    with pytest.raises(AddonError) as err:
        load_descriptor(_write_descriptor(tmp_path, body))
    assert "platforms" in str(err.value)

    # none with check_cmd contradicts
    body = DESCRIPTOR_NONE.replace('kind = "none"', 'kind = "none"\ncheck_cmd = "x -v"')
    with pytest.raises(AddonError):
        load_descriptor(_write_descriptor(tmp_path, body))


def test_descriptor_override_must_target_declared_platform(tmp_path):
    body = DESCRIPTOR_BINARY.replace(
        '"linux-x86_64" = "ccx --version"', '"windows-x86_64" = "ccx --version"'
    )
    with pytest.raises(AddonError) as err:
        load_descriptor(_write_descriptor(tmp_path, body))
    assert "windows-x86_64" in str(err.value)


# ----------------------------------------------------------- source parsing


def test_parse_source_github_and_local(tmp_path):
    github = parse_source("owner/repo")
    assert isinstance(github, GitHubSource)
    assert (github.owner, github.repo, github.ref) == ("owner", "repo", "HEAD")

    pinned = parse_source("owner/repo@v1.2.0")
    assert isinstance(pinned, GitHubSource)
    assert pinned.ref == "v1.2.0"
    assert pinned.spec == "owner/repo@v1.2.0"

    local_dir = tmp_path / "an-addon"
    local_dir.mkdir()
    local = parse_source(str(local_dir))
    assert isinstance(local, LocalSource)
    assert local.path == local_dir.resolve()


def test_parse_source_local_wins_over_github_shape(tmp_path):
    nested = tmp_path / "owner" / "repo"
    nested.mkdir(parents=True)
    parsed = parse_source(str(nested))
    assert isinstance(parsed, LocalSource)


def test_parse_source_rejections(tmp_path):
    with pytest.raises(AddonError):
        parse_source("")
    with pytest.raises(AddonError):
        parse_source("owner/repo@")
    with pytest.raises(AddonError):
        parse_source("definitely not a spec")
    local_dir = tmp_path / "x"
    local_dir.mkdir()
    with pytest.raises(AddonError):
        parse_source(f"{local_dir}@v1")


# ----------------------------------------------------------- tarball safety


def _tarball_bytes(members: list[tuple[str, str]], *, top: str = "repo-main") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, payload in members:
            data = payload.encode("utf-8")
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_safe_extract_strips_top_level_directory(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    _safe_extract_tarball(
        _tarball_bytes([("sca-addon.toml", "[addon]\n"), ("skill/SKILL.md", "# x\n")]),
        dest,
    )
    assert (dest / "sca-addon.toml").read_text(encoding="utf-8").startswith("[addon]")
    assert (dest / "skill" / "SKILL.md").exists()


def _raw_tarball_bytes(builder) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        builder(archive)
    return buffer.getvalue()


def test_safe_extract_refuses_escaping_member(tmp_path):
    def build(archive: tarfile.TarFile) -> None:
        data = b"evil"
        info = tarfile.TarInfo("repo-main/../escaped.txt")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))

    with pytest.raises(AddonError) as err:
        _safe_extract_tarball(_raw_tarball_bytes(build), tmp_path / "out")
    assert "escapes" in str(err.value)


def test_safe_extract_refuses_symlink_member(tmp_path):
    def build(archive: tarfile.TarFile) -> None:
        info = tarfile.TarInfo("repo-main/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)

    with pytest.raises(AddonError) as err:
        _safe_extract_tarball(_raw_tarball_bytes(build), tmp_path / "out")
    assert "links" in str(err.value)


def test_safe_extract_refuses_multiple_tops(tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for top in ("repo-a", "repo-b"):
            data = b"x"
            info = tarfile.TarInfo(f"{top}/file.txt")
            info.size = 1
            archive.addfile(info, io.BytesIO(data))
    with pytest.raises(AddonError) as err:
        _safe_extract_tarball(buffer.getvalue(), tmp_path / "out")
    assert "top-level" in str(err.value)


# ------------------------------------------------------------ runtime probe


def test_run_check_cmd_pass_and_fail():
    passing = f'"{sys.executable}" -c "print(42)"'
    report = run_check_cmd(passing)
    assert report["passed"] is True
    assert report["exit_code"] == 0

    failing = f'"{sys.executable}" -c "raise SystemExit(3)"'
    report = run_check_cmd(failing)
    assert report["passed"] is False
    assert report["exit_code"] == 3

    missing = run_check_cmd("definitely-not-a-command-xyz-123")
    assert missing["passed"] is False


# ---------------------------------------------------- command_prefix (v2 std)


def test_command_prefix_defaults_to_empty(tmp_path):
    descriptor = load_descriptor(_write_descriptor(tmp_path, DESCRIPTOR_NONE))
    assert descriptor.command_prefix == ""


def test_command_prefix_roundtrip_with_addon_dir_placeholder(tmp_path):
    body = DESCRIPTOR_NONE.replace(
        'kind = "none"',
        'kind = "none"\ncommand_prefix = \'PATH="{addon_dir}/.venv/bin:$PATH\"\'',
    )
    descriptor = load_descriptor(_write_descriptor(tmp_path, body))
    assert descriptor.command_prefix == 'PATH="{addon_dir}/.venv/bin:$PATH"'


def test_command_prefix_rejects_non_string(tmp_path):
    body = DESCRIPTOR_NONE.replace('kind = "none"', 'kind = "none"\ncommand_prefix = 7')
    with pytest.raises(AddonError) as err:
        load_descriptor(_write_descriptor(tmp_path, body))
    assert "command_prefix" in str(err.value)


def test_command_prefix_rejects_unknown_placeholder(tmp_path):
    body = DESCRIPTOR_NONE.replace(
        'kind = "none"',
        'kind = "none"\ncommand_prefix = "PATH={venv_dir}/bin:$PATH"',
    )
    with pytest.raises(AddonError) as err:
        load_descriptor(_write_descriptor(tmp_path, body))
    assert "{venv_dir}" in str(err.value)
    assert "{addon_dir}" in str(err.value)


def test_effective_command_joins_prefix_and_substitutes_both_dirs():
    from simplecadapi.addon.install import effective_command

    prefix = 'PATH="{addon_dir}/.venv/bin:$PATH" SCA_RUNTIME_DIR="{runtime_dir}"'
    effective = effective_command(
        prefix, Path("/addons/demo"), Path("/sca/runtimes/demo"), "python -V"
    )
    assert effective == (
        'PATH="/addons/demo/.venv/bin:$PATH" '
        'SCA_RUNTIME_DIR="/sca/runtimes/demo" python -V'
    )
    assert (
        effective_command("", Path("/addons/demo"), Path("/sca/runtimes/demo"), "python -V")
        == "python -V"
    )
