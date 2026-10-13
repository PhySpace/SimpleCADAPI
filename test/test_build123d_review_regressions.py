"""Review reproductions cross the two isolated kernel environments end to end."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/research/build123dftc"))
from b3ftc.replay import replay_trace_to_ftc
from b3ftc.validation import compare_metrics
from b3ftc._validate_worker import run


def capture(source):
    python = ROOT.parent / ".venv/bin/python"
    if not python.is_file():
        pytest.skip("isolated build123d environment is unavailable")
    worker = "import json,sys; sys.path.insert(0,'tools/research/build123dftc'); from b3ftc.tracer import trace_source; print(json.dumps(trace_source(sys.stdin.read())))"
    process = subprocess.run([str(python), "-c", worker], input="from build123d import *\n" + source,
                             text=True, capture_output=True, cwd=ROOT, timeout=30, check=True)
    trace = json.loads(process.stdout)
    assert trace["b3d_status"] == "ok", trace
    return trace


@pytest.mark.parametrize("source", [
    "result=Solid.make_torus(5,1,major_angle=120)",
    "a=Solid.make_box(10,2,2)\nb=Solid.make_box(2,4,4).moved(Location((4,-1,-1)))\nresult=a.cut(b)",
    "a=Solid.make_box(10,2,2)\nb=Solid.make_box(2,4,4).moved(Location((4,-1,-1)))\nresult=a.cut(b).solids()[1].moved(Location((0,5,0)))",
    "a=Solid.make_box(10,2,2)\nb=Solid.make_box(2,4,4)\nc=Solid.make_box(2,4,4).moved(Location((8,0,0)))\nresult=a.intersect(Compound([b,c]))",
    "a=Solid.make_box(2,2,2)\nb=Solid.make_box(2,2,2).moved(Location((4,0,0)))\nc=Compound([a,b])\nresult=c.fillet(.2, c.edges().filter_by(Axis.Z))",
    "a=Solid.make_box(2,2,2)\nb=Solid.make_box(2,2,2).moved(Location((4,0,0)))\nc=Compound([a,b])\nresult=c.fillet(.2, a.edges().filter_by(Axis.Z))",
    "a=Solid.make_box(2,2,2)\nresult=a.split(Plane.XY.offset(10), keep=Keep.BOTH)",
])
def test_review_geometry_reconciles_with_actual_return(tmp_path, source):
    trace = capture(source)
    generated, meta = replay_trace_to_ftc(trace, stem="review")
    assert meta["status"] == "ok", meta
    ftc = tmp_path / "review.ftc.py"
    ftc.write_text(generated)
    stage = tmp_path / "staged"
    stage.mkdir()
    metrics = run(ftc, stage)
    comparison = compare_metrics(trace, metrics, meta)
    assert comparison["quality"] == "accepted", comparison


@pytest.mark.parametrize("angles", ["start_angle=-30", "end_angle=80", "start_angle=-30,end_angle=80,major_angle=140"])
def test_partial_torus_tube_is_explicitly_unsupported(angles):
    trace = capture(f"result=Solid.make_torus(5,1,{angles})")
    generated, meta = replay_trace_to_ftc(trace)
    assert meta["status"] == "partial"
    assert any("partial torus tube" in str(note) for note in meta["unsupported"])
    assert "feature tree produced no solid" in generated


def test_solid_ordering_uses_bounds_when_centroids_differ_between_kernels(tmp_path):
    trace = capture("a=Solid.make_box(2,2,2)\nb=a.moved(Location((4,0,0)))\nresult=Compound([a,b])")
    for step in trace["steps"]:
        for component in step.get("result_components", []):
            component["center"] = [1234, 5678, 9000]
    generated, meta = replay_trace_to_ftc(trace, stem="bounds")
    assert meta["status"] == "ok"
    ftc = tmp_path / "bounds.ftc.py"
    ftc.write_text(generated)
    stage = tmp_path / "stage"
    stage.mkdir()
    assert compare_metrics(trace, run(ftc, stage), meta)["quality"] == "accepted"


@pytest.mark.parametrize("source", [
    "b=Box(1,2,3)+Cylinder(.75,2.5)\nwith BuildPart() as bp:\n insert(b)\n Cylinder(.4,6,mode=Mode.SUBTRACT)\nresult=bp.part",
    "a=Box(4,4,4)\nb=Box(4,4,4).moved(Location((2,0,0)))\nresult=Part([a]) & b",
    "section=RegularPolygon(1,6).face()\nresult=Solid.extrude_linear_with_rotation(section,(0,0),(0,0,5),72)",
    "face=Face(Wire.make_circle(2),[Wire.make_circle(1)])\nresult=Solid.sweep(face,Wire([Edge.make_three_point_arc((0,0,0),(3,0,2),(5,0,5))]))",
    "v=[(1,1,1),(1,-1,-1),(-1,1,-1),(-1,-1,1)]\nf=[[0,1,2],[0,3,1],[0,2,3],[1,3,2]]\nresult=Solid(Shell([Face(Wire.make_polygon([v[i] for i in face])) for face in f])).clean()",
    "result=ConvexPolyhedron([(0,0,0),(1,0,0),(0,1,0),(0,0,1)])",
])
def test_additional_fix_candidates_reconcile(tmp_path, source):
    trace = capture(source)
    generated, meta = replay_trace_to_ftc(trace, stem="candidate")
    assert meta["status"] == "ok", meta
    ftc = tmp_path / "candidate.ftc.py"
    ftc.write_text(generated)
    stage = tmp_path / "stage"
    stage.mkdir()
    comparison = compare_metrics(trace, run(ftc, stage), meta)
    assert comparison["quality"] == "accepted", comparison
