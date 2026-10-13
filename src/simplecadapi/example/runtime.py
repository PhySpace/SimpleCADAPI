"""Find and copy the bundled example workspaces.

An example is a directory of notebooks.  The wheel carries the sources under
``resources/`` (see ``pyproject.toml``); a checkout (editable install) reads
them from ``examples/`` at the repository root.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Example:
    name: str
    directory: str
    """Name of the directory it is copied to by default."""
    open_with: str
    """What to hand ``sca edit``, relative to the copy."""
    summary: str


EXAMPLES: dict[str, Example] = {
    "u_link": Example(
        name="u_link",
        directory="u_link_motor_mount",
        open_with=".",
        summary="a motor mount: two parts and the assembly that fixes them together, "
        "driven by the shared dimensions in dimensions.py",
    ),
}

_SOURCES = {
    "u_link": (
        "u_link.py",
        "shell.py",
        "u_link_motor_mount.py",
        "dimensions.py",
        "common.py",
    ),
}


def example_names() -> list[str]:
    return sorted(EXAMPLES)


def _source_root(example: Example) -> Path:
    bundled = Path(__file__).parent / "resources" / example.directory
    if bundled.is_dir():
        return bundled
    # An editable install keeps the examples where the repository has them.
    return Path(__file__).resolve().parents[3] / "examples" / example.directory


def copy_example(name: str, destination: Path | None = None) -> Path:
    """Copy example *name* to *destination* (default: its own name in the current directory).

    Refuses to write into an existing directory, so nothing of the person's is
    overwritten.  Returns the directory made.
    """
    if name not in EXAMPLES:
        raise ValueError(f"unknown example {name!r}; choose from: {', '.join(example_names())}")
    example = EXAMPLES[name]
    target = (destination if destination is not None else Path.cwd() / example.directory).expanduser()
    target = target.absolute()
    if target.exists():
        raise ValueError(f"{target} already exists; pick another directory (nothing was changed)")
    source = _source_root(example)
    files = [source / relative for relative in _SOURCES[name]]
    missing = [file.name for file in files if not file.is_file()]
    if missing:
        raise ValueError(f"the bundled example is incomplete (missing {', '.join(missing)}); reinstall simplecadapi")
    target.mkdir(parents=True)
    try:
        for file in files:
            shutil.copy2(file, target / file.name)
    except OSError:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target
