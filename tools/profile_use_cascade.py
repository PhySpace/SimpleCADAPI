"""Profile what one edit makes the notebook runtime rebuild, in a nested-assembly project.

The project: a top assembly ``use``s assemblies A, B, C; each of those ``use``s
three parts (A also a "giant" part, whose one big cell builds two independent
things).  Every part has parameters ``p`` and ``q``.  Ideally changing ``p``
of one part rebuilds that part's cells, the ``use`` of it, and what reads it
in the assembly above, and nothing else.

    uv run python tools/profile_use_cascade.py [--holes N] [--keep DIR]

Each scenario edits the project, runs the top notebook headlessly, and prints
the tree of notebook runs: wall seconds (inclusive of children) and how many
of the notebook's cells ran / were restored.  Every run uses the cache.
"""

from __future__ import annotations

import argparse
import re
import tempfile
import textwrap
import threading
import time
from pathlib import Path

HEADER = '# /// script\n# [tool.simplecadapi]\n# id = "{id}"\n# ///\nimport marimo\n\napp = marimo.App()\n\nwith app.setup:\n    import simplecadapi as scad\n\n\n'
FOOTER = '\nif __name__ == "__main__":\n    app.run()\n'


def heavy(var: str, size: str, holes: int) -> str:
    return textwrap.dedent(
        f"""\
        _s = scad.make_box_rsolid({size}, 20.0, 20.0)
        for _i in range({holes}):
            _c = scad.make_cylinder_rsolid(1.5, 30.0)
            _s = scad.cut_rsolid(_s, scad.translate_shape(_c, (_i % 6 * 3 + 1, _i // 6 * 3 + 1, -5.0)))
        {var} = _s
        """
    )


def cell(reads: str, body: str, returns: str) -> str:
    code = textwrap.indent(textwrap.dedent(body).strip(), "    ")
    return f"@app.cell\ndef _({reads}):\n{code}\n    return ({returns},)\n\n\n"


def part(name: str, holes: int) -> str:
    return (
        HEADER.format(id=name)
        + cell("", "# ---- params ----\np = 40.0\nq = 3.0", "p, q")
        + cell("p", heavy("body", "p", holes), "body")
        + cell("q, body", "rim = scad.cut_rsolid(body, scad.make_cylinder_rsolid(q, 50.0))", "rim")
        + cell("rim", f"part = scad.Part(part_id='{name}', body=rim)", "part")
        + FOOTER
    )


def giant(name: str, holes: int) -> str:
    """One big cell that reads both p and q and builds two independent things."""

    body = heavy("a", "p", holes) + "\n" + heavy("b", "q * 10.0", holes) + "\nbody = scad.union_rsolid(a, scad.translate_shape(b, (0.0, 20.0, 0.0)))\n"
    return (
        HEADER.format(id=name)
        + cell("", "# ---- params ----\np = 40.0\nq = 3.0", "p, q")
        + cell("p, q", body, "body")
        + cell("body", f"part = scad.Part(part_id='{name}', body=body)", "part")
        + FOOTER
    )


def assembly(name: str, children: list[tuple[str, str]]) -> str:
    """*children*: (variable, relative path)."""

    uses = "".join(cell("", f'{var} = scad.use("{path}")', var) for var, path in children)
    lines = [
        "_identity = scad.identity_placement_rplacement()",
        f'_assembly = scad.make_assembly_rassembly(assembly_id="{name}", name="{name}")',
    ]
    for var, _ in children:
        lines.append(
            f'_assembly = scad.add_component_rassembly(assembly=_assembly, item={var}, component_id="{var}", placement=_identity)'
        )
    lines.append(f"{name} = _assembly")
    return (
        HEADER.format(id=name)
        + uses
        + cell(", ".join(var for var, _ in children), "\n".join(lines), name)
        + FOOTER
    )


def build_project(root: Path, holes: int) -> Path:
    parts = root / "parts"
    asm = root / "asm"
    parts.mkdir(parents=True)
    asm.mkdir()
    layout = {"a": ["a1", "a2", "a3", "giant"], "b": ["b1", "b2", "b3"], "c": ["c1", "c2", "c3"]}
    for names in layout.values():
        for name in names:
            text = giant(name, holes) if name == "giant" else part(name, holes)
            (parts / f"{name}.py").write_text(text, encoding="utf-8")
    for key, names in layout.items():
        (asm / f"asm_{key}.py").write_text(
            assembly(f"asm_{key}", [(name, f"../parts/{name}.py") for name in names]), encoding="utf-8"
        )
    top = root / "top.py"
    top.write_text(assembly("top", [(f"asm_{k}", f"asm/asm_{k}.py") for k in layout]), encoding="utf-8")
    return top


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

_depth = 0
_lock = threading.Lock()
_rows: list[tuple[int, str, float, int, int]] = []


def install_probe() -> None:
    from simplecadapi.runtime import runner

    original = runner.run_notebook

    def probed(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        global _depth
        with _lock:
            depth = _depth
            _depth += 1
            slot = len(_rows)
            _rows.append((depth, Path(path).name, 0.0, 0, 0))
        start = time.perf_counter()
        try:
            run = original(path, *args, **kwargs)
        finally:
            with _lock:
                _depth -= 1
        ran = sum(1 for c in run.cells if c.status == "ran" and c.name != "setup")
        cached = sum(1 for c in run.cells if c.status == "cached")
        with _lock:
            _rows[slot] = (depth, Path(path).name, time.perf_counter() - start, ran, cached)
        return run

    runner.run_notebook = probed


def scenario(title: str, top: Path) -> float:
    from simplecadapi.runtime import runner

    _rows.clear()
    start = time.perf_counter()
    runner.run_notebook(top)
    total = time.perf_counter() - start
    print(f"\n== {title}: {total:.2f}s")
    for depth, name, seconds, ran, cached in _rows:
        mark = "" if ran == 0 else f"  <- {ran} cell(s) ran"
        print(f"  {'  ' * depth}{name:<14} {seconds:6.2f}s  ran {ran:>2}  cached {cached:>2}{mark}")
    return total


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, (path, old)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--holes", type=int, default=30, help="cuts per heavy build (cost knob)")
    parser.add_argument("--keep", type=Path, help="build the project here and keep it")
    args = parser.parse_args()

    temporary = None
    if args.keep:
        root = args.keep.resolve()
    else:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name).resolve() / "project"
    top = build_project(root, args.holes)
    print(f"project: {root}")
    install_probe()

    parts = root / "parts"
    scenario("cold", top)
    scenario("warm (nothing changed)", top)
    edit(parts / "a1.py", "p = 40.0", "p = 41.0")
    scenario("edit p of a1 (a leaf under asm_a)", top)
    edit(parts / "a1.py", "p = 41.0", "p = 41.0  # a comment")
    scenario("comment only in a1", top)
    edit(parts / "giant.py", "q = 3.0", "q = 4.0")
    scenario("edit q of giant (one big cell, two independent builds)", top)
    edit(parts / "b2.py", "q = 3.0", "q = 3.5")
    scenario("edit q of b2 (a leaf under asm_b)", top)
    edit(parts / "a1.py", "p = 41.0  # a comment", "p = 40.0")
    scenario("revert p of a1", top)

    if temporary is not None:
        temporary.cleanup()


if __name__ == "__main__":
    main()
