"""Shared test configuration."""

from __future__ import annotations

import os

# Failure-path evidence rendering stays off for the suite at large: it is
# slow (one render per failure) and exercises nothing those tests assert.
# Dedicated evidence tests opt back in via monkeypatch.delenv. Their
# per-render budget scales with the slowest runner (cold CI workers), not
# with the agent-facing default.
os.environ.setdefault("SCA_NO_DIAGNOSTIC_RENDER", "1")
os.environ.setdefault("SCA_DIAGNOSTIC_RENDER_BUDGET", "60")

# Worker processes for the notebooks a cell uses are for the tests that are
# about them (they set SCA_JOBS themselves): starting several interpreters per
# run would only slow the rest of the suite down.
os.environ.setdefault("SCA_JOBS", "1")


# ---------------------------------------------------------------------------
# The C++ backend: failures that are known and classified.
#
# ``internal``: the test reads a private helper or an internal of the Python wrappers (the
#   ``_TopoEntity`` cache, ``OperationNode`` dataclass pickling, ...) that the C++ port does not have;
#   skipped.  ``open``: a real parity difference of the native operators / recorder (most are the
#   graph-replay contract of ``replay_model_json``: selection nodes, detail features, sketches); expected
#   to fail, not strict, so a fix shows up as XPASS.  src/cpp/docs/NATIVE_PROGRESS.md has the causes.
# ---------------------------------------------------------------------------

import json as _json
from pathlib import Path as _Path

import pytest as _pytest

_KNOWN = _json.loads((_Path(__file__).with_name("native_known_failures.json")).read_text(encoding="utf-8"))


def pytest_collection_modifyitems(config, items):  # noqa: D103
    for item in items:
        entry = _KNOWN.get(item.nodeid)
        if entry is None:
            continue
        kind, reason = entry
        if kind == "internal":
            item.add_marker(_pytest.mark.skip(reason="native backend: " + reason))
        else:
            item.add_marker(_pytest.mark.xfail(reason="native backend: " + reason, strict=False))
