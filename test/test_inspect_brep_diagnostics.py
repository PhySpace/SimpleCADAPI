from __future__ import annotations

import pytest
from simplecadapi._cpp.occt.BRep import BRep_Builder
from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_Transform
from simplecadapi._cpp.occt.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeSphere
from simplecadapi._cpp.occt.TopoDS import TopoDS_Compound
from simplecadapi._cpp.occt.gp import gp_Trsf, gp_Vec

from simplecadapi.inspect.brep.diagnostics import (
    inspect_difference_regions_rdescriptor,
    compare_boundary_distance_rdescriptor,
    compare_entities_rdescriptor,
    compare_global_properties_rdescriptor,
    compare_sections_rdescriptor,
    compare_material_rdescriptor,
    evaluate_reconstruction_rdescriptor,
    inspect_nearby_entities_rdescriptor,
)
from simplecadapi.inspect.brep.model import BRepEntityError, index_shape_rbrepmodel
import simplecadapi.inspect.brep.diagnostics as diagnostics


def _box(x: float = 10.0, y: float = 20.0, z: float = 30.0):
    return BRepPrimAPI_MakeBox(x, y, z).Shape()


def _translated(shape, x: float, y: float, z: float):
    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(x, y, z))
    operation = BRepBuilderAPI_Transform(shape, transform, True)
    operation.Build()
    assert operation.IsDone()
    return operation.Shape()


def test_global_boundary_and_material_diagnostics():
    target = index_shape_rbrepmodel(_box())
    current = index_shape_rbrepmodel(_box(9.0, 20.0, 30.0))

    global_properties = compare_global_properties_rdescriptor(target, current)
    boundary = compare_boundary_distance_rdescriptor(
        target,
        current,
        linear_deflection=3.0,
        max_samples=64,
    )
    material = compare_material_rdescriptor(target, current)

    assert global_properties["volume"]["absolute_delta"] == pytest.approx(-600.0)
    assert boundary["symmetric"]["hausdorff_approximation"] == pytest.approx(1.0)
    assert material["missing_material"]["volume"] == pytest.approx(600.0)
    assert material["excess_material"]["volume"] == pytest.approx(0.0)
    assert material["method"] == "bidirectional_cut"
    assert isinstance(material["missing_material"]["components"], list)
    assert material["boolean_result_valid"] is True


def test_material_volume_mode_uses_intersection_without_components():
    target = index_shape_rbrepmodel(_box())
    current = index_shape_rbrepmodel(_box(9.0, 20.0, 30.0))

    material = compare_material_rdescriptor(target, current, include_components=False)

    assert material["method"] == "common_volume"
    assert material["missing_material"]["volume"] == pytest.approx(600.0)
    assert material["excess_material"]["volume"] == pytest.approx(0.0)
    assert material["missing_material"]["component_count"] is None
    assert material["missing_material"]["components"] is None
    assert material["boolean_result_valid"] is True


@pytest.mark.parametrize(
    ("operation_name", "helper_name"),
    [
        ("BRepAlgoAPI_Cut", "_cut_shape"),
        ("BRepAlgoAPI_Common", "_common_shape"),
    ],
)
def test_material_booleans_are_configured_before_one_build(
    monkeypatch,
    operation_name,
    helper_name,
):
    instances = []

    class RecordingBoolean:
        def __init__(self, *args):
            self.constructor_args = args
            self.events = []
            self.result = None
            instances.append(self)

        def SetArguments(self, shapes):
            self.result = list(shapes)[0]
            self.events.append("arguments")

        def SetTools(self, shapes):
            assert len(list(shapes)) == 1
            self.events.append("tools")

        def SetRunParallel(self, value):
            assert value is True
            self.events.append("parallel")

        def SetUseOBB(self, value):
            assert value is True
            self.events.append("obb")

        def SetToFillHistory(self, value):
            assert value is False
            self.events.append("history")

        def SetNonDestructive(self, value):
            assert value is True
            self.events.append("non_destructive")

        def SetFuzzyValue(self, value):
            assert value == pytest.approx(1.0e-7)
            self.events.append("fuzzy")

        def Build(self):
            self.events.append("build")

        def IsDone(self):
            return True

        def Shape(self):
            return self.result

    monkeypatch.setattr(diagnostics, operation_name, RecordingBoolean)
    first = _box()
    second = _box(9.0, 20.0, 30.0)

    result = getattr(diagnostics, helper_name)(first, second, 1.0e-7)

    assert result.IsSame(first)
    assert instances[0].constructor_args == ()
    assert instances[0].events == [
        "arguments",
        "tools",
        "parallel",
        "obb",
        "history",
        "non_destructive",
        "fuzzy",
        "build",
    ]


def test_material_component_rejects_negative_signed_volume():
    with pytest.raises(BRepEntityError, match="negative signed volume"):
        diagnostics._component_summary(
            _box().Reversed(),
            "missing:0",
            "missing_material",
        )


def test_fuzzy_material_result_cannot_claim_strict_equality():
    target = index_shape_rbrepmodel(_box(1000.0, 1.0, 1.0))
    current = index_shape_rbrepmodel(_box(999.91, 1.0, 1.0))

    material = compare_material_rdescriptor(
        target,
        current,
        boolean_tolerance=0.1,
        include_components=True,
    )

    assert material["missing_material"]["volume"] == 0.0
    assert material["boolean_result_valid"] is False
    assert material["strict_equality_supported"] is False
    assert material["volume_balance"]["valid"] is False


def test_material_balance_allows_valid_curved_boolean_roundoff():
    target = BRepPrimAPI_MakeSphere(10.0).Shape()
    current = _translated(target, 0.1, 0.0, 0.0)

    material = compare_material_rdescriptor(target, current)

    assert material["missing_material"]["volume"] == pytest.approx(
        material["excess_material"]["volume"],
        rel=1.0e-8,
    )
    assert material["volume_balance"]["valid"] is True
    assert material["boolean_result_valid"] is True


def test_boundary_identity_and_section_comparison():
    target = index_shape_rbrepmodel(_box())

    boundary = compare_boundary_distance_rdescriptor(
        target,
        target,
        linear_deflection=3.0,
        max_samples=32,
    )
    section = compare_sections_rdescriptor(
        target,
        target,
        (0.0, 0.0, 15.0),
        (0.0, 0.0, 1.0),
        samples_per_edge=4,
    )

    assert boundary["symmetric"]["hausdorff_approximation"] < 1.0e-9
    assert section["comparison"]["hausdorff_approximation"] < 1.0e-9
    assert section["comparison"]["area_delta"] == pytest.approx(0.0)


def test_boundary_distance_can_scope_each_model_to_selected_faces():
    target = index_shape_rbrepmodel(_box())
    result = compare_boundary_distance_rdescriptor(
        target,
        target,
        linear_deflection=3.0,
        max_samples=16,
        target_face_ids=["face:0"],
        current_face_ids=["face:0"],
    )

    assert result["scope"] == {
        "target_face_ids": ["face:0"],
        "current_face_ids": ["face:0"],
    }
    assert result["target_to_current"]["sample_count"] <= 16
    assert result["symmetric"]["hausdorff_approximation"] < 1.0e-9


def test_difference_regions_and_nearby_entities():
    target = index_shape_rbrepmodel(_box())
    current = index_shape_rbrepmodel(_translated(_box(), 2.0, 0.0, 0.0))

    regions = inspect_difference_regions_rdescriptor(
        target,
        current,
        distance_threshold=0.5,
        linear_deflection=4.0,
        max_samples=48,
    )
    nearby = inspect_nearby_entities_rdescriptor(
        target,
        region=regions["regions"][0],
        radius=1.0,
        max_results=10,
    )

    assert regions["region_count"] >= 1
    assert nearby["entity_count"] >= 1
    assert nearby["entities"][0]["distance"] <= 1.0


def test_difference_regions_reuses_precomputed_results(monkeypatch):
    target = index_shape_rbrepmodel(_box())
    current = index_shape_rbrepmodel(_translated(_box(), 2.0, 0.0, 0.0))
    boundary = compare_boundary_distance_rdescriptor(
        target,
        current,
        linear_deflection=4.0,
        max_samples=32,
        include_records=True,
    )
    material = compare_material_rdescriptor(target, current, include_components=True)

    monkeypatch.setattr(
        diagnostics,
        "compare_boundary_distance_rdescriptor",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("recomputed boundary")
        ),
    )
    monkeypatch.setattr(
        diagnostics,
        "compare_material_rdescriptor",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("recomputed material")
        ),
    )
    regions = inspect_difference_regions_rdescriptor(
        target,
        current,
        distance_threshold=0.5,
        include_boundary=True,
        boundary_result=boundary,
        material_result=material,
    )

    assert regions["boundary_included"] is True
    assert regions["region_count"] >= 1


def test_difference_regions_default_skips_boundary_sampling(monkeypatch):
    target = index_shape_rbrepmodel(_box())
    current = index_shape_rbrepmodel(_translated(_box(), 2.0, 0.0, 0.0))
    monkeypatch.setattr(
        diagnostics,
        "compare_boundary_distance_rdescriptor",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("boundary sampled")
        ),
    )

    regions = inspect_difference_regions_rdescriptor(target, current)

    assert regions["boundary_included"] is False
    assert regions["boundary_summary"] is None
    assert regions["region_count"] >= 1
    assert regions["material_summary"]["method"] == "bidirectional_cut"


def test_entity_comparison_and_evaluation_gates():
    target = index_shape_rbrepmodel(_box())
    identical = index_shape_rbrepmodel(_box())
    different = index_shape_rbrepmodel(_box(9.0, 20.0, 30.0))

    entity = compare_entities_rdescriptor(target, "face:0", identical, "face:0")
    passed = evaluate_reconstruction_rdescriptor(
        target,
        identical,
        replay_succeeded=True,
        linear_deflection=3.0,
        max_samples=32,
        require_strict_brep=True,
    )
    failed = evaluate_reconstruction_rdescriptor(
        target,
        different,
        replay_succeeded=True,
        linear_deflection=3.0,
        max_samples=32,
    )

    assert entity["kind_match"] is True
    assert entity["geometry_type_match"] is True
    assert entity["distance"]["distance"] == pytest.approx(0.0)
    assert passed["passed"] is True
    assert passed["strict_brep_executed"] is True
    assert passed["metrics"]["material_difference"]["method"] == "bidirectional_cut"
    assert failed["passed"] is False
    assert failed["strict_brep_executed"] is False
    assert failed["metrics"]["strict_brep"] is None


def test_evaluation_rejects_fuzzy_material_false_positive():
    target = _box(10.0, 1.0, 1.0)
    result = evaluate_reconstruction_rdescriptor(
        index_shape_rbrepmodel(target),
        index_shape_rbrepmodel(_translated(target, 0.09, 0.0, 0.0)),
        replay_succeeded=True,
        boundary_tolerance=0.2,
        bounding_box_tolerance=0.2,
        relative_volume_tolerance=1.0,
        relative_area_tolerance=1.0,
        relative_material_tolerance=1.0,
        linear_deflection=100.0,
        max_samples=16,
        boolean_tolerance=0.1,
    )

    assert result["passed"] is False
    assert "material_strict_equality_supported" in result["failed_checks"]
    assert result["metrics"]["material_difference"]["boolean_result_valid"] is True


def test_evaluation_does_not_run_strict_comparison_unless_requested(monkeypatch):
    def unexpected_strict_comparison(*args, **kwargs):
        raise AssertionError("strict comparison must not execute")

    monkeypatch.setattr(diagnostics, "compare_shapes_rbrepcomparison", unexpected_strict_comparison)
    result = evaluate_reconstruction_rdescriptor(
        index_shape_rbrepmodel(_box()),
        index_shape_rbrepmodel(_box()),
        replay_succeeded=True,
        linear_deflection=3.0,
        max_samples=32,
        require_strict_brep=False,
    )

    assert result["passed"] is True
    assert result["strict_brep_executed"] is False
    assert result["metrics"]["strict_brep"] is None


def test_boundary_sample_budget_limits_face_tessellation(monkeypatch):
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for index in range(4):
        builder.Add(compound, _translated(_box(), index * 20.0, 0.0, 0.0))
    model = index_shape_rbrepmodel(compound)
    sampled = []

    def fake_face_samples(face, linear_deflection):
        del linear_deflection
        sampled.append(face)
        return diagnostics.measure_shape_mass_rtuple(face, "area")[1][None, :]

    monkeypatch.setattr(diagnostics, "_face_samples", fake_face_samples)

    points = diagnostics._surface_samples(
        model,
        linear_deflection=1.0,
        max_samples=16,
    )

    assert len(sampled) <= 16
    assert len(points) <= 16
