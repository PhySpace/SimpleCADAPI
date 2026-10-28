"""``shape.wrapped`` is an OCP shape when OCP is installed, so the OCCT code an agent knows runs as written."""

from __future__ import annotations

import pytest

pytest.importorskip("OCP")

import simplecadapi as scad
from simplecadapi import ql
from simplecadapi._glue import bridge


@pytest.fixture(autouse=True)
def ocp_view(monkeypatch):
    monkeypatch.delenv("SCA_WRAPPED", raising=False)  # (the suite's default is the native view)


def box():
    return scad.make_box_rsolid(2.0, 3.0, 4.0)


def test_wrapped_is_the_ocp_class_of_the_kind_of_shape() -> None:
    from OCP.TopoDS import TopoDS_Edge, TopoDS_Face, TopoDS_Solid

    solid = box()
    edge = ql.select(ql.edges().resolve(solid)).all()[0]
    face = ql.select(ql.faces().resolve(solid)).all()[0]
    assert type(solid.wrapped) is TopoDS_Solid
    assert type(edge.wrapped) is TopoDS_Edge
    assert type(face.wrapped) is TopoDS_Face
    assert type(solid.wrapped).__module__.startswith("OCP")


def test_the_code_an_agent_writes_for_cadquery_runs_as_written() -> None:
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.GProp import GProp_GProps

    solid = box()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid.wrapped, props)
    assert props.Mass() == pytest.approx(solid.get_volume(), rel=1e-9)
    bounds = Bnd_Box()
    BRepBndLib.Add_s(solid.wrapped, bounds)
    xmin, ymin, zmin, xmax, ymax, zmax = bounds.Get()
    assert (xmax - xmin, ymax - ymin, zmax - zmin) == pytest.approx((2.0, 3.0, 4.0), abs=1e-6)
    assert BRepCheck_Analyzer(solid.wrapped).IsValid()
    edge = ql.select(ql.edges().resolve(solid)).all()[0]
    face = ql.select(ql.faces().resolve(solid)).all()[0]
    assert "Line" in str(BRepAdaptor_Curve(edge.wrapped).GetType())
    assert "Plane" in str(BRepAdaptor_Surface(face.wrapped).GetType())


def test_each_access_is_a_copy_of_the_same_geometry() -> None:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    solid = box()
    first, second = solid.wrapped, solid.wrapped
    assert first is not second
    for shape in (first, second):
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        assert props.Mass() == pytest.approx(24.0)


def test_the_choice_can_be_made_either_way(monkeypatch) -> None:
    monkeypatch.setenv("SCA_WRAPPED", "native")
    assert type(box().wrapped).__module__.endswith("_occt")
    monkeypatch.setenv("SCA_WRAPPED", "ocp")
    assert type(box().wrapped).__module__.startswith("OCP")
    assert box()._native_wrapped is not None  # the SDK's own view does not depend on it
    assert type(box()._native_wrapped).__module__.endswith("_occt")


def test_without_ocp_the_view_is_the_native_one(monkeypatch) -> None:
    monkeypatch.setattr(bridge, "_ocp_present", False)
    assert bridge.wrapped_mode() == "native"
    assert type(box().wrapped).__module__.endswith("_occt")


def test_the_inspect_queries_take_an_ocp_shape_and_a_native_one(monkeypatch) -> None:
    from simplecadapi.inspect import brep

    solid = box()
    from_ocp = brep.index_shape_rbrepmodel(solid.wrapped).summary()
    monkeypatch.setenv("SCA_WRAPPED", "native")
    from_native = brep.index_shape_rbrepmodel(solid.wrapped).summary()
    assert from_ocp == from_native


def test_the_helpers_and_the_step_export_take_an_ocp_shape(tmp_path) -> None:
    from simplecadapi.kernel.ocp_export import export_step_shapes
    from simplecadapi.kernel.ocp_properties import bounding_box

    solid = box()
    bounds = bounding_box(solid.wrapped)
    assert (bounds.xmax - bounds.xmin, bounds.zmax - bounds.zmin) == pytest.approx((2.0, 4.0), abs=1e-6)
    target = tmp_path / "box.step"
    export_step_shapes([solid.wrapped], str(target))
    assert target.stat().st_size > 0


def test_the_way_back_from_an_ocp_shape_keeps_the_geometry() -> None:
    back = bridge.from_occt(box().wrapped)
    assert back.get_volume() == pytest.approx(24.0)


def test_something_that_is_not_a_shape_is_refused_with_a_reason() -> None:
    with pytest.raises(TypeError, match="SDK shape"):
        bridge.native_to_ocp(5)
