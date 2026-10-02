"""Paths inside the ``.simplecad/`` working directory.

``.simplecad/`` holds files the SDK writes as a side effect of running
code (failure evidence today). It is local scratch, never project input:
deleting it loses nothing that the code cannot regenerate.
"""

from __future__ import annotations

from pathlib import Path

WORKSPACE_DIRNAME = ".simplecad"


def diagnostics_dir() -> Path:
    """Directory for failure-evidence images: ``<cwd>/.simplecad/diagnostics``.

    Resolved on every call so a process that changes directory writes next
    to the code it is currently running.
    """

    return Path.cwd() / WORKSPACE_DIRNAME / "diagnostics"


__all__ = ["WORKSPACE_DIRNAME", "diagnostics_dir"]
