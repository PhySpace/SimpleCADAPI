"""Unknown construction must remain visible instead of aliasing an old solid."""
from pathlib import Path
import sys

import pytest

pytest.importorskip("build123d")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/research/build123dftc"))
from b3ftc.replay import replay_trace_to_ftc
from b3ftc.tracer import trace_source
from b3ftc.validation import compare_metrics


@pytest.mark.parametrize("statement", [
    "result = Box(2,3,4).to_splines()",
    "from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox\nresult = Solid(BRepPrimAPI_MakeBox(2,3,4).Solid())",
])
def test_uninstrumented_api_cannot_silently_accept(statement):
    trace = trace_source("from build123d import *\n" + statement)
    assert trace["b3d_status"] == "ok", trace["error"]
    assert trace["unsupported"], trace
    assert any(step["op"] == "unsupported" for step in trace["steps"])
    _, metadata = replay_trace_to_ftc(trace)
    assert metadata["status"] == "partial", metadata
    actual = {"status": "ok", "volume": trace["b3d_volume"],
              "bbox": trace["b3d_bbox"], "solid_count": trace["solid_count"],
              "body_count": trace["solid_count"], "is_valid": True}
    assert compare_metrics(trace, actual, metadata)["quality"] == "rejected"


def test_failed_source_rejects_even_after_valid_feature_was_created():
    trace = trace_source("from build123d import *\nresult=Box(2,3,4)\nraise RuntimeError('unknown operation')")
    _, metadata = replay_trace_to_ftc(trace)
    actual = {"status": "ok", "volume": 24, "bbox": [-1,-1.5,-2,1,1.5,2],
              "solid_count": 1, "body_count": 1, "is_valid": True}
    result = compare_metrics(trace, actual, metadata)
    assert result["quality"] == "rejected"
    assert "source_failed" in result["reasons"]
