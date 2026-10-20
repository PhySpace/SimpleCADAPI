"""Shared test configuration."""

from __future__ import annotations

import os

# Failure-path evidence rendering stays off for the suite at large: it is
# slow (VTK worker per render) and exercises nothing those tests assert.
# Dedicated evidence tests opt back in via monkeypatch.delenv. Their
# per-render budget scales with the slowest runner (cold CI workers), not
# with the agent-facing default.
os.environ.setdefault("SCA_NO_DIAGNOSTIC_RENDER", "1")
os.environ.setdefault("SCA_DIAGNOSTIC_RENDER_BUDGET", "60")

# Worker processes for the notebooks a cell uses are for the tests that are
# about them (they set SCA_JOBS themselves): starting several interpreters per
# run would only slow the rest of the suite down.
os.environ.setdefault("SCA_JOBS", "1")
