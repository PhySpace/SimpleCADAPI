"""simplecadapi.verify: SDK shapes to OCP and back, for verifier scripts.

Runs only where OCP is installed (``uv run --with cadquery-ocp pytest ...``); the SDK and the rest of the suite never
need it.  The verifier recipes of the skill (docs/skill/references/workflows/verifier-scripts.md) are run here too.
"""

from __future__ import annotations

import math

import pytest

import simplecadapi as scad
from simplecadapi import verify

ocp = pytest.importorskip("OCP")

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common  # noqa: E402
from OCP.BRepBndLib import BRepBndLib  # noqa: E402
from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepClass3d import BRepClass3d_SolidClassifier  # noqa: E402
from OCP.BRepExtrema import BRepExtrema_DistShapeShape  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.Bnd import Bnd_Box  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402
from OCP.TopAbs import TopAbs_IN, TopAbs_ON  # noqa: E402
from OCP.TopoDS import TopoDS  # noqa: E402
from OCP.gp import gp_Pnt  # noqa: E402


def part():
    box = scad.make_box_rsolid(10, 20, 30, bottom_face_center=(0, 0, 0))
    hole = scad.make_cylinder_rsolid(3, 40, bottom_face_center=(0, 0, -5))
    return scad.cut_rsolid(box, hole)


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_the_sdk_wrapped_shape_is_not_an_ocp_shape():
    with pytest.raises(TypeError, match="incompatible"):
        BRepGProp.VolumeProperties_s(part().wrapped, GProp_GProps())


def test_to_ocp_measures_like_the_sdk():
    solid = part()
    shape = verify.to_ocp(solid)
    assert math.isclose(volume(shape), solid.get_volume(), rel_tol=1e-12)
    assert BRepCheck_Analyzer(shape).IsValid()
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    assert [round(v, 6) for v in box.Get()] == [-5.0, -10.0, 0.0, 5.0, 10.0, 30.0]


def test_recipes_point_in_solid_distance_and_overlap():
    solid = verify.to_ocp(part())
    classify = BRepClass3d_SolidClassifier(TopoDS.Solid_s(solid), gp_Pnt(4, 5, 6), 1e-6)
    assert classify.State() == TopAbs_IN
    in_hole = BRepClass3d_SolidClassifier(TopoDS.Solid_s(solid), gp_Pnt(0, 0, 15), 1e-6)
    assert in_hole.State() != TopAbs_IN and in_hole.State() != TopAbs_ON

    other = verify.to_ocp(scad.make_box_rsolid(2, 2, 2, bottom_face_center=(20, 0, 0)))
    distance = BRepExtrema_DistShapeShape(solid, other)
    assert distance.IsDone() and math.isclose(distance.Value(), 14.0, abs_tol=1e-9)  # 20 - 1 - 5

    overlapping = verify.to_ocp(scad.make_box_rsolid(10, 10, 10, bottom_face_center=(0, 0, 25)))
    common = BRepAlgoAPI_Common(solid, overlapping)
    # the box overlaps the top 5 mm of the part; the 3 mm hole runs through that slab
    assert common.IsDone() and math.isclose(volume(common.Shape()), 10 * 10 * 5 - math.pi * 3**2 * 5, rel_tol=1e-9)


def test_from_ocp_brings_a_shape_back():
    original = part()
    back = verify.from_ocp(verify.to_ocp(original))
    assert isinstance(back, scad.Solid)
    assert math.isclose(back.get_volume(), original.get_volume(), rel_tol=1e-12)


def test_wrong_arguments_say_what_to_pass():
    with pytest.raises(TypeError, match="expects an SDK shape"):
        verify.to_ocp(verify.to_ocp(part()))
    with pytest.raises(TypeError, match="expects an OCP TopoDS_Shape"):
        verify.from_ocp(part())


def test_a_missing_ocp_names_the_extra(monkeypatch):
    import builtins

    real = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "OCP" or name.startswith("OCP."):
            raise ImportError("no OCP")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    assert verify.ocp_available() is False
    with pytest.raises(ImportError, match=r"simplecadapi\[verify\]"):
        verify.to_ocp(part())


def test_the_skill_page_code_runs(monkeypatch):
    """The recipes and the skeleton of references/discipline/verifier-scripts.md run as written."""

    import re
    import sys
    import types
    from pathlib import Path

    page = Path(__file__).resolve().parents[4] / "docs/skill/references/discipline/verifier-scripts.md"
    blocks = re.findall(r"```python\n(.*?)```", page.read_text(encoding="utf-8"), flags=re.S)
    recipes = next(b for b in blocks if "def overlap_volume" in b)
    skeleton = next(b for b in blocks if "verify_bracket.py" in b)

    bracket = types.ModuleType("bracket")
    bracket.build = part
    monkeypatch.setitem(sys.modules, "bracket", bracket)

    namespace: dict = {"__name__": "verifier"}
    exec(compile(recipes, "recipes", "exec"), namespace)
    exec(compile(skeleton.replace("sys.exit(0 if all(checks) else 1)", ""), "skeleton", "exec"), namespace)
    assert namespace["checks"] and all(namespace["checks"]), namespace["checks"]
    # every recipe answers on the part
    shape = namespace["shape"]
    assert namespace["contains"](TopoDS.Solid_s(shape), 4, 5, 6)
    assert namespace["gap"](shape, verify.to_ocp(scad.make_box_rsolid(2, 2, 2, bottom_face_center=(20, 0, 0)))) == pytest.approx(14.0)
