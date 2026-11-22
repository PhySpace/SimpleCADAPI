"""``sca addon use``: run a command inside an installed addon's environment.

The addon's ``[runtime].command_prefix`` (a shell prelude, with
``{addon_dir}`` resolving to the installed addon payload and
``{runtime_dir}`` to the addon's private runtime-state directory beside the
addon home) is joined in front of the requested command and handed to the
shell, so ``sca addon use conn-tools python train.py`` executes with
exactly the environment the addon declares — its own venv, tool paths, or
variables — without the caller having to provision anything. The installed
addon directory is also exported as ``SCA_ADDON_DIR`` and its runtime
directory as ``SCA_RUNTIME_DIR``, so provisioning scripts can self-locate.

Calling without a command reports the effective prefix and directories
instead of executing anything.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from . import AddonError
from .descriptor import load_descriptor
from .home import ResolvedPaths, require_initialized, runtime_dir_for
from .install import _shell_invocation, effective_command
from .registry import get_record, load_registry


def _windows_dispatch(cmd: Sequence[str], env: dict[str, str]) -> str:
    # Expand argv only *after* cmd has parsed operators, quotes, %VAR% and
    # newlines. A child cmd enables delayed expansion just for this final
    # dispatch; the descriptor prelude keeps ordinary cmd /c semantics.
    env["_SCA_USE_PROGRAM"] = cmd[0]
    env["_SCA_USE_ARGS"] = subprocess.list2cmdline(cmd[1:])
    program = "!_SCA_USE_PROGRAM!"
    if any(c.isspace() for c in cmd[0]):
        program = f'"{program}"'
    return f'"%ComSpec%" /d /v:on /s /c "{program} !_SCA_USE_ARGS!"'


def use_addon(
    resolved: ResolvedPaths,
    name: str,
    cmd: Sequence[str],
    *,
    capture_output: bool = False,
) -> dict[str, Any]:
    """Dispatch ``cmd`` through the addon's command prefix.

    With ``capture_output`` the command's stdout/stderr come back in the
    report (for tests and tooling); otherwise they stream straight to the
    caller's terminal and only the exit code is reported.
    """
    require_initialized(resolved)
    registry = load_registry(resolved.home)
    record = get_record(registry, name)
    if record is None:
        installed = sorted(registry.get("addons", {}))
        listing = ", ".join(installed) if installed else "(none installed)"
        raise AddonError(f"addon {name!r} is not installed; installed: {listing}")
    addon_dir = resolved.home / str(record.get("addon_relpath", name))
    if not addon_dir.is_dir():
        raise AddonError(
            f"addon directory {addon_dir} is missing from the addon home — "
            f"reinstall with `sca addon update {name}` or `sca addon add`"
        )
    runtime_dir = Path(str(record.get("runtime_dir") or runtime_dir_for(resolved, name)))
    # The installed descriptor is the source of truth for the prefix: a
    # user may provision or edit it after install without re-adding.
    descriptor = load_descriptor(addon_dir)
    prefix = descriptor.command_prefix

    if not cmd:
        return {
            "action": "use",
            "name": name,
            "addon_dir": str(addon_dir),
            "runtime_dir": str(runtime_dir),
            "command_prefix": prefix,
        }

    # Shell-quote each argv element so the joined line re-parses to exactly
    # the requested argv, even for arguments with spaces or shell metachars.
    env = dict(os.environ)
    env["SCA_ADDON_DIR"] = str(addon_dir)
    env["SCA_RUNTIME_DIR"] = str(runtime_dir)
    windows = sys.platform == "win32"
    command = subprocess.list2cmdline(cmd) if windows else shlex.join(cmd)
    effective = effective_command(prefix, addon_dir, runtime_dir, command)
    dispatch = (
        effective_command(prefix, addon_dir, runtime_dir, _windows_dispatch(cmd, env))
        if windows else effective
    )
    try:
        completed = subprocess.run(
            _shell_invocation(dispatch), env=env, capture_output=capture_output,
            text=capture_output, errors="replace" if capture_output else None,
        )
    except FileNotFoundError as exc:
        raise AddonError(f"cannot launch the shell for {effective!r}: {exc}") from exc
    report: dict[str, Any] = {
        "action": "use",
        "name": name,
        "addon_dir": str(addon_dir),
        "runtime_dir": str(runtime_dir),
        "command": effective,
        "exit_code": completed.returncode,
    }
    if capture_output:
        report["output"] = completed.stdout
        if completed.stderr:
            report["stderr"] = completed.stderr
    return report
