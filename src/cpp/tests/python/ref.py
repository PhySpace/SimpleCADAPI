"""Parity helper: ask the reference Python SDK, cache the answer as golden JSON.

    from ref import golden
    expected = golden("box_basic", '''
        box = scad.make_box_rsolid(10, 20, 30)
        result = {"volume": box.get_volume(), "faces": len(ql.faces().resolve(box))}
    ''')

The snippet runs in the *reference* interpreter (the Python SDK on OCP) with
`scad` = simplecadapi and `result` JSON-serialisable.  The first run on a machine
that has the reference stores tests/golden/<name>.json; every other machine (the
Linux VM, CI) reads that file.  Re-record with SCAD_REGOLDEN=1.

Golden files are committed: they are the contract the C++ port is held to.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
REF_PYTHON = os.environ.get(
    "SCAD_REF_PYTHON", "/Users/lildino/Project/ocws/SimpleCADAPI/.venv/bin/python"
)

_PRELUDE = """
import json, sys
import simplecadapi as scad
result = None
"""
_EPILOGUE = """
json.dump(result, sys.stdout, default=float)
"""


def reference_available() -> bool:
    return Path(REF_PYTHON).exists()


def ref_eval(snippet: str, timeout: float = 120.0) -> Any:
    """Run `snippet` in the reference interpreter and return its `result`."""
    if not reference_available():
        raise RuntimeError(f"reference interpreter not found at {REF_PYTHON}")
    code = _PRELUDE + textwrap.dedent(snippet) + _EPILOGUE
    proc = subprocess.run([REF_PYTHON, "-c", code], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"reference snippet failed:\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


def golden(name: str, snippet: str) -> Any:
    """Golden value for `name`: from tests/golden/<name>.json, recorded on demand."""
    path = GOLDEN_DIR / f"{name}.json"
    if path.exists() and not os.environ.get("SCAD_REGOLDEN"):
        return json.loads(path.read_text())
    if not reference_available():
        pytest.skip(f"no golden file {path.name} and no reference interpreter to record it")
    value = ref_eval(snippet)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return value


# The reference SDK wrote some of its messages in Chinese; its error report replaced those by this sentence, so the
# goldens hold it.  The port writes every message in English: a recorded generic sentence matches any English
# message of the same exception type ("ValueError: ...").
_GENERIC_DETAIL = "The underlying validation failed; use the structured guidance above to repair the operation."


def close(a: Any, b: Any, rel: float = 1e-6, abs_: float = 1e-9) -> bool:
    """Recursive approximate equality for golden comparisons."""
    if isinstance(b, str) and isinstance(a, str) and b.endswith(_GENERIC_DETAIL) and a != b:
        return a.split(": ", 1)[0] == b.split(": ", 1)[0] and a.isascii()
    if isinstance(a, dict) and isinstance(b, dict):
        # An error report of the reference with no guidance at all (a message-first family before its guidance was
        # designed): the port's report carries guidance, which the reference lacked.  Everything else must match.
        skip = set()
        if (b.get("possible_causes") == [] and b.get("how_to_fix") == [] and "what_happened" in b
                and a.keys() == b.keys()):
            skip = {"possible_causes", "how_to_fix"}
        return a.keys() == b.keys() and all(close(a[k], b[k], rel, abs_) for k in a if k not in skip)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(close(x, y, rel, abs_) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))
    return a == b
