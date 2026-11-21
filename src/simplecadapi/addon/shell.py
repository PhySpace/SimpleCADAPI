"""``sca init`` shell integration: make ``sca`` resolve in any new shell.

One ``sca init`` wires the command everywhere without the user touching
PATH by hand:

1. a shim directory ``~/.sca/bin`` holding a wrapper that execs the real
   console script living next to the interpreter that ran ``sca init``;
   the venv's own ``bin`` is never put on PATH (it would shadow ``python``
   and friends globally — the shim is surgical);
2. that directory on PATH: a marked, removable block in ``~/.zshenv``
   (zsh reads it in non-interactive shells too, so agents and scripts see
   the command; ``~/.zshrc`` would only serve interactive terminals),
   ``~/.bashrc`` (bash), ``~/.config/fish/conf.d/sca-path.fish`` (fish);
   on Windows, the user-scope ``PATH`` registry value (HKCU\\Environment)
   plus a broadcast so newly opened shells pick it up.

Only the marked block, the shim directory, and (Windows) the single PATH
entry are ever written. An rc file is created only for the user's login
shell or when it already exists — ``sca init`` never plants dotfiles for
shells that are not in use. ``--no-shell`` skips the step; re-running
``sca init`` after the install environment moves refreshes the shim.
Removal is manual by construction: delete the marked block(s) and
``~/.sca/bin`` (Windows: drop the ``.sca\\bin`` PATH entry).
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import Any

BLOCK_BEGIN = "# >>> sca shell integration >>>"
BLOCK_END = "# <<< sca shell integration <<<"

_SHIM_DIR_PARTS = (".sca", "bin")


def shim_dir(home: Path | None = None) -> Path:
    """Directory holding the ``sca`` wrapper (default ``~/.sca/bin``)."""
    base = home if home is not None else Path.home()
    return base.joinpath(*_SHIM_DIR_PARTS)


def console_script_target(executable: Path | None = None) -> Path:
    """The real ``sca`` console script next to the running interpreter.

    Deliberately no symlink resolution: venv interpreters are usually
    symlinks into a toolchain directory, and following them would leave
    the venv whose ``bin/`` holds the console script.
    """
    interpreter = Path(executable or sys.executable)
    if not interpreter.is_absolute():
        interpreter = Path.cwd() / interpreter
    return interpreter.parent / ("sca.exe" if sys.platform == "win32" else "sca")


def render_posix_shim(target: Path) -> str:
    quoted = shlex.quote(str(target))
    return (
        "#!/bin/sh\n"
        "# Written by `sca init`; re-run `sca init` after the install moves.\n"
        f"SCA_TARGET={quoted}\n"
        'if [ ! -x "$SCA_TARGET" ]; then\n'
        '    echo "sca: console script $SCA_TARGET is missing;" '
        '"re-run \'sca init\' from the environment that provides simplecadapi" >&2\n'
        "    exit 127\n"
        "fi\n"
        'exec "$SCA_TARGET" "$@"\n'
    )


def render_cmd_shim(target: Path) -> str:
    return (
        "@echo off\r\n"
        "rem Written by `sca init`; re-run `sca init` after the install moves.\r\n"
        f'if not exist "{target}" (\r\n'
        "  echo sca: console script is missing; "
        "re-run sca init from the environment that provides simplecadapi 1>&2\r\n"
        "  exit /b 127\r\n"
        ")\r\n"
        f'@"{target}" %*\r\n'
    )


def _path_block() -> str:
    return f"{BLOCK_BEGIN}\n" 'export PATH="$HOME/.sca/bin:$PATH"\n' f"{BLOCK_END}\n"


def _fish_block() -> str:
    return f"{BLOCK_BEGIN}\n" 'set -gx PATH "$HOME/.sca/bin" $PATH\n' f"{BLOCK_END}\n"


def _upsert_block(path: Path, block: str) -> str:
    """Append the marked block once; return "written" or "present"."""
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if BLOCK_BEGIN in text:
        return "present"
    if text and not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + block, encoding="utf-8")
    return "written"


def _login_shell() -> str:
    return Path(os.environ.get("SHELL", "")).name.lower()


def _posix_rc_targets(home: Path) -> dict[Path, str]:
    """rc file -> block kind, for shells actually in use on this machine."""
    targets: dict[Path, str] = {}
    shell = _login_shell()
    zshenv = home / ".zshenv"
    bashrc = home / ".bashrc"
    fish_file = home / ".config" / "fish" / "conf.d" / "sca-path.fish"
    if zshenv.is_file() or shell == "zsh":
        targets[zshenv] = "posix"
    if bashrc.is_file() or shell == "bash":
        targets[bashrc] = "posix"
    if (home / ".config" / "fish").is_dir() or shell == "fish":
        targets[fish_file] = "fish"
    return targets


def _ensure_path_entry(entries: list[str], entry: str) -> tuple[list[str], bool]:
    """Insert ``entry`` at the front of a PATH entry list if absent."""
    wanted = entry.rstrip("\\/").lower()
    if any(item.rstrip("\\/").lower() == wanted for item in entries):
        return entries, False
    return [entry, *entries], True


def _windows_user_path(shim: Path) -> dict[str, Any]:
    """Prepend the shim dir to the user-scope PATH (HKCU\\Environment); no admin."""
    import winreg

    entry = str(shim)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:  # ty: ignore[unresolved-attribute]
        try:
            value, value_type = winreg.QueryValueEx(key, "Path")  # ty: ignore[unresolved-attribute]
        except FileNotFoundError:
            value, value_type = "", winreg.REG_EXPAND_SZ  # ty: ignore[unresolved-attribute]
    entries, changed = _ensure_path_entry(str(value).split(";"), entry)
    report: dict[str, Any] = {"windows_path": "present" if not changed else "appended"}
    if changed:
        with winreg.OpenKey(  # ty: ignore[unresolved-attribute]
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE  # ty: ignore[unresolved-attribute]
        ) as key:
            winreg.SetValueEx(key, "Path", 0, value_type, ";".join(entries))  # ty: ignore[unresolved-attribute]
        _broadcast_environment_change()
        report["notes"] = ["PATH updated; already-open terminals must be reopened"]
    return report


def _broadcast_environment_change() -> None:
    import ctypes

    HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(  # ty: ignore[unresolved-attribute]
        HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
        SMTO_ABORTIFHUNG, 5000, ctypes.byref(result),
    )


def integrate_shell(home: Path | None = None) -> dict[str, Any]:
    """Write the shim and PATH wiring; return a report for the init output."""
    base = home if home is not None else Path.home()
    target = console_script_target()
    report: dict[str, Any] = {"shim": None, "shell_blocks": {}, "notes": []}
    if not target.is_file():
        report["notes"].append(
            f"no console script next to {sys.executable!r}; shell integration "
            "skipped — run `sca init` from the environment that provides simplecadapi"
        )
        return report

    directory = shim_dir(base)
    directory.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        shim = directory / "sca.cmd"
        shim.write_bytes(render_cmd_shim(target).encode("utf-8"))
        report.update(_windows_user_path(directory))
    else:
        shim = directory / "sca"
        shim.write_text(render_posix_shim(target), encoding="utf-8")
        shim.chmod(0o755)
        for rc_path, kind in _posix_rc_targets(base).items():
            block = _fish_block() if kind == "fish" else _path_block()
            report["shell_blocks"][str(rc_path)] = _upsert_block(rc_path, block)
    report["shim"] = str(shim)
    return report
