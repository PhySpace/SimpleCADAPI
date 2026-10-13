"""Complex shared fillet geometry must survive nonuniform scale without a crash."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/research/build123dftc"))
from b3ftc.replay import replay_trace_to_ftc
from b3ftc.validation import _worker


def test_nonuniform_scale_after_spherical_cut_and_fillet(tmp_path):
    trace = json.loads((ROOT / "test/build123d_traces/affine_trimmed_sphere.trace.json").read_text())
    source, meta = replay_trace_to_ftc(trace, stem="affine-shared-geometry")
    assert meta["status"] == "ok"
    path = tmp_path / "affine.ftc.py"
    path.write_text(source)
    # A native kernel regression can segfault. Keep the test runner alive and
    # report it as a failing feature, exactly like the external acceptance tool.
    metrics = _worker(path, tmp_path / "work", 30, None, sys.executable, None)
    assert metrics["status"] == "ok", metrics
    assert metrics["is_valid"] is True
    assert metrics["volume"] == pytest.approx(trace["b3d_volume"], rel=1e-6)
