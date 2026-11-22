"""Addon runtime-state contract: runtime dir, placeholders, check verb.

Pins the design decided for SDK 2.1.3b4:

* ``{runtime_dir}`` resolves to a per-addon directory BESIDE the addon
  home, created at install, untouched by update, removed with the addon;
* updates replace the addon payload wholesale but preserve a legacy
  in-payload ``.venv`` provisioned by pre-``{runtime_dir}`` addons;
* ``sca addon check`` re-probes the installed runtime NOW and refreshes
  the registry record (the install-time probe is a cache, not truth);
* ``sca addon use`` resolves both placeholders and exports
  ``SCA_RUNTIME_DIR``;
* removal never interprets a missing runtime_dir as ``Path("")`` (the
  CWD) — records from before the layout carry no path at all.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from simplecadapi.addon import AddonError
from simplecadapi.addon import home as home_mod
from simplecadapi.addon.home import resolve_paths, runtimes_home, runtime_dir_for
from simplecadapi.addon.install import (
    check_addon,
    effective_command,
    install_addon,
    list_addons,
    parse_source,
    remove_addon,
    update_addon,
)
from simplecadapi.addon.registry import (
    empty_registry,
    get_record,
    load_registry,
    save_registry,
)
from simplecadapi.addon.use import use_addon

ADDON_NAME = "sca-demo-addon"
MARKER_PROBE = f'"{sys.executable}" -c "import os,sys; sys.exit(not os.path.isfile(sys.argv[1]))" "{{runtime_dir}}/marker"'
VENV_PROBE = f'"{sys.executable}" -c "import os,sys; sys.exit(not os.path.isdir(sys.argv[1]))" "{{addon_dir}}/.venv"'
OK_PROBE = f'"{sys.executable}" -V'


def _venv_prefix(placeholder: str) -> str:
    if sys.platform == "win32":
        return f'set "PATH={placeholder}\\.venv\\Scripts;%PATH%" &&'
    return f'PATH="{placeholder}/.venv/bin:$PATH"'


def _write_addon_source(root: Path, *, check_cmd: str | None, prefix: str | None,
                        version: str = "0.1.0") -> Path:
    source = root / ADDON_NAME
    (source / "skill").mkdir(parents=True, exist_ok=True)
    lines = [
        "[addon]",
        f'name = "{ADDON_NAME}"',
        f'version = "{version}"',
        'license = "Apache-2.0"',
        'skill_path = "skill"',
        "",
        "[compat]",
        'sca = ">=2"',
        "",
        "[runtime]",
        'kind = "python-env"',
    ]
    platforms = (
        "macos-arm64", "macos-x86_64", "linux-x86_64", "linux-aarch64",
        "windows-x86_64", "windows-arm64",
    )
    platforms_str = ", ".join('"%s"' % p for p in platforms)
    lines.append(f"platforms = [{platforms_str}]")
    if check_cmd is not None:
        lines.append(f"check_cmd = {json.dumps(check_cmd, ensure_ascii=False)}")
    if prefix is not None:
        lines.append(f"command_prefix = {json.dumps(prefix, ensure_ascii=False)}")
    (source / "sca-addon.toml").write_text("\n".join(lines) + "\n")
    (source / "skill" / "SKILL.md").write_text(
        "---\n"
        f"name: {ADDON_NAME}\n"
        "description: demo addon for runtime-state contract tests\n"
        "---\n"
        "\n# demo\n",
        encoding="utf-8",
    )
    return source


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated addon home + skills dir + config, as if `sca init` ran."""
    home = tmp_path / "state" / "addons"
    skills = tmp_path / "skills"
    home.mkdir(parents=True)
    skills.mkdir()
    save_registry(home, empty_registry())
    monkeypatch.setattr(home_mod, "config_path", lambda: tmp_path / "config.toml")
    resolved = resolve_paths(home=home, skills_dir=skills)
    home_mod.write_config(resolved)
    return resolved


def test_effective_command_resolves_both_placeholders(tmp_path):
    line = effective_command(
        'PATH="{runtime_dir}/.venv/bin:$PATH" cd {addon_dir}',
        tmp_path / "payload", tmp_path / "runtime", "run-it",
    )
    assert 'PATH="%s/.venv/bin:$PATH"' % (tmp_path / "runtime") in line
    assert "cd %s" % (tmp_path / "payload") in line
    assert line.endswith("run-it")


def test_install_creates_runtime_dir_and_records_it(env, tmp_path):
    source = _write_addon_source(
        tmp_path, check_cmd=MARKER_PROBE, prefix=None
    )
    report = install_addon(env, parse_source(str(source)))
    runtime_dir = Path(report["runtime_dir"])
    assert runtime_dir == runtimes_home(env) / ADDON_NAME
    assert runtime_dir.is_dir()
    record = get_record(load_registry(env.home), ADDON_NAME)
    assert record is not None
    assert record["runtime_dir"] == str(runtime_dir)
    # the probe references the runtime dir and must have failed: the marker
    # does not exist yet (state as of install time)
    assert record["runtime_check"] is not None
    assert record["runtime_check"]["passed"] is False


def test_check_reprobes_and_refreshes_registry(env, tmp_path):
    source = _write_addon_source(
        tmp_path, check_cmd=MARKER_PROBE, prefix=None
    )
    install_addon(env, parse_source(str(source)))
    runtime_dir = runtime_dir_for(env, ADDON_NAME)
    (runtime_dir / "marker").write_text("", encoding="utf-8")

    report = check_addon(env, ADDON_NAME)
    assert report["runtime_check"] is not None
    assert report["runtime_check"]["passed"] is True
    assert report["runtime_check"]["checked_at"]
    record = get_record(load_registry(env.home), ADDON_NAME)
    assert record is not None
    assert record["runtime_check"] is not None
    assert record["runtime_check"]["passed"] is True

    listing = list_addons(env)
    state = listing["addons"][0]["runtime_state"]
    assert state.startswith("ok (cached ")


def test_update_replaces_payload_but_keeps_runtime_state(env, tmp_path):
    source = _write_addon_source(
        tmp_path, check_cmd=MARKER_PROBE, prefix=None,
        version="0.1.0",
    )
    install_addon(env, parse_source(str(source)))
    addon_dir = env.home / ADDON_NAME
    runtime_dir = runtime_dir_for(env, ADDON_NAME)
    (runtime_dir / "marker").write_text("precious", encoding="utf-8")
    (addon_dir / "payload-file.txt").write_text("old", encoding="utf-8")

    _write_addon_source(
        tmp_path, check_cmd=MARKER_PROBE, prefix=None,
        version="0.2.0",
    )
    report = update_addon(env, ADDON_NAME)

    assert report["version"] == "0.2.0"
    assert not (addon_dir / "payload-file.txt").exists()  # payload replaced
    assert (runtime_dir / "marker").read_text() == "precious"  # state kept
    # and the freshly provisioned runtime now passes the install-time probe
    assert report["runtime_check"] is not None
    assert report["runtime_check"]["passed"] is True


def test_update_preserves_legacy_payload_venv(env, tmp_path):
    source = _write_addon_source(
        tmp_path, check_cmd=VENV_PROBE,
        prefix=_venv_prefix("{addon_dir}"), version="0.1.0",
    )
    install_addon(env, parse_source(str(source)))
    addon_dir = env.home / ADDON_NAME
    legacy = addon_dir / ".venv" / "bin"
    legacy.mkdir(parents=True)
    (legacy / "python").write_text("", encoding="utf-8")

    _write_addon_source(
        tmp_path, check_cmd=VENV_PROBE,
        prefix=_venv_prefix("{addon_dir}"), version="0.2.0",
    )
    update_addon(env, ADDON_NAME)

    assert (addon_dir / ".venv" / "bin" / "python").is_file()


def test_use_exports_runtime_dir_and_resolves_prefix(env, tmp_path):
    source = _write_addon_source(
        tmp_path, check_cmd=OK_PROBE,
        prefix=_venv_prefix("{runtime_dir}"),
    )
    install_addon(env, parse_source(str(source)))
    report = use_addon(env, ADDON_NAME, [sys.executable, "-c", "import os; print(os.environ['SCA_RUNTIME_DIR'])"],
                       capture_output=True)
    assert report["exit_code"] == 0
    assert report["output"].strip() == str(runtime_dir_for(env, ADDON_NAME))


def test_remove_deletes_payload_skill_and_runtime(env, tmp_path):
    source = _write_addon_source(tmp_path, check_cmd=OK_PROBE, prefix=None)
    install_addon(env, parse_source(str(source)))
    runtime_dir = runtime_dir_for(env, ADDON_NAME)
    (runtime_dir / "state.txt").write_text("", encoding="utf-8")

    report = remove_addon(env, ADDON_NAME)

    removed = {Path(p) for p in report["removed"]}
    assert removed == {env.home / ADDON_NAME, runtime_dir,
                       env.skills_dir / ADDON_NAME}
    assert not runtime_dir.exists()
    assert get_record(load_registry(env.home), ADDON_NAME) is None


def test_remove_with_legacy_record_never_touches_cwd(env, tmp_path, monkeypatch):
    """A pre-runtime-dir record has no runtime_dir; removal must not
    interpret the missing field as Path('') == the CWD."""
    source = _write_addon_source(tmp_path, check_cmd=OK_PROBE, prefix=None)
    install_addon(env, parse_source(str(source)))
    registry = load_registry(env.home)
    record = registry["addons"][ADDON_NAME]
    del record["runtime_dir"]
    save_registry(env.home, registry)

    # run the removal from a scratch cwd full of canary files
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "canary.txt").write_text("alive", encoding="utf-8")
    monkeypatch.chdir(scratch)

    report = remove_addon(env, ADDON_NAME)

    assert (scratch / "canary.txt").read_text() == "alive"
    assert str(env.home / ADDON_NAME) in report["removed"]
    assert not any(p == str(scratch) for p in report["removed"])


def test_check_unknown_addon_names_installed(env):
    with pytest.raises(AddonError, match="not installed"):
        check_addon(env, "sca-nope")
