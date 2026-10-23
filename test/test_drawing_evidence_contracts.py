"""Independent regressions for semantic, visual-artifact and display bindings."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest
from simplecadapi._cpp.occt.BRepPrimAPI import BRepPrimAPI_MakeBox

from simplecadapi.inspect import drawing
from simplecadapi.inspect.drawing._provenance import file_hash

# The pytest console entry point need not put the repository root on sys.path.
# Load the standalone verifier by its actual file, as the other tool tests do.
_VERIFIER_PATH = (
    Path(__file__).resolve().parents[1] / "tools/verify_drawing_evidence.py"
)
_VERIFIER_SPEC = importlib.util.spec_from_file_location(
    "drawing_evidence_verifier", _VERIFIER_PATH
)
assert _VERIFIER_SPEC is not None and _VERIFIER_SPEC.loader is not None
_VERIFIER = importlib.util.module_from_spec(_VERIFIER_SPEC)
sys.modules[_VERIFIER_SPEC.name] = _VERIFIER
_VERIFIER_SPEC.loader.exec_module(_VERIFIER)
verify = _VERIFIER.verify

PLANE = {"origin": [0, 0, 1], "normal": [0, 0, 1]}


def contract(kind, direction, definition="axis_aligned_extent", point=None):
    return {
        "kind": kind,
        "direction": direction,
        "definition": definition,
        "point": point,
        "units": "mm",
        "coordinate_space": "section_local",
    }


def fixture(width=20, height=10):
    # Local x = global -Y, local y = global X.
    model = BRepPrimAPI_MakeBox(height, width, 2).Shape()
    result = drawing.measure_model_section_rdimensions(
        model, PLANE, section_checks=box_checks(width, height)
    )
    return model, {m["kind"]: m for m in result.measurements}


def box_checks(width=20, height=10):
    return {
        "expected_origin": [0, 0, 1],
        "expected_normal": [0, 0, 1],
        "expected_x_direction": [0, -1, 0],
        "expected_y_direction": [1, 0, 0],
        "expected_solid_count": 1,
        "expected_face_count": 1,
        "expected_hole_count": 0,
        "material_points": [{"id": "material", "point": [-width / 2, height / 2]}],
        "void_points": [],
        "point_tolerance_mm": 1e-7,
        "tolerance_basis": "fixture point classification precision",
        "evidence": "box drawing fixture",
    }


def ledger_for(record, expected_contract, nominal):
    return {
        "dim_id": "DIM-W",
        "feature_id": "outline",
        "view": "section",
        "source_id": "fixture-source",
        "raw_word_ids": [1],
        "association_evidence": ["independent dimension line review"],
        "datum": "local axes",
        "tolerance_basis": "explicit fixture band",
        "tolerance_min": nominal - 0.01,
        "tolerance_max": nominal + 0.01,
        "nominal": nominal,
        "coordinate_status": "verified",
        "value_status": "verified",
        "association_status": "verified",
        "target_geometry": deepcopy(record["target_geometry"]),
        "section_checks": deepcopy(record["configuration"]["section_checks"]),
        "measurement_contract": deepcopy(expected_contract),
    }


def uncertainty(record):
    return {
        "measurement_id": record["measurement_id"],
        "bound_mm": 1e-6,
        "basis": "independently assessed fixture",
        "evidence": "fixture proof",
    }


def annotate(record, ledger):
    return drawing.build_section_annotation_rrecord(
        record, ledger, error_assessment=uncertainty(record), anchor=[0, 0]
    )


def reviewed_evidence(model, ledger, annotation, tmp_path):
    png = drawing.render_model_section_rpath(
        model,
        PLANE,
        dimensions=[annotation],
        validation_ledger=[ledger],
        out_dir=tmp_path,
        dpi=72,
    )
    sidecar = png.with_suffix(".json")
    review = {
        "dim_id": ledger["dim_id"],
        "layout_status": "reviewed",
        "association_status": "verified",
        "evidence": "independent reviewer",
        **{k: annotation[k] for k in ("measurement_id", "model_hash", "section_id")},
        "render_artifact": {
            "image_path": str(png.resolve()),
            "image_sha256": file_hash(png),
            "sidecar_path": str(sidecar.resolve()),
            "sidecar_sha256": file_hash(sidecar),
        },
    }
    return {
        "plane": PLANE,
        "ledger": [ledger],
        "annotations": [annotation],
        "output_reviews": {ledger["dim_id"]: review},
    }


def test_wrong_axis_rejected_by_assessor_and_builder():
    _, records = fixture()
    height = records["extent_height"]
    row = ledger_for(height, contract("extent_width", [1, 0]), 10)
    verdict = drawing.assess_dimension_rverdict(
        row, height, error_assessment=uncertainty(height)
    )
    assert verdict["model_measurement"]["status"] != "passed"
    with pytest.raises(ValueError, match="contract"):
        annotate(height, row)


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("kind", "extent_height"),
        ("direction", [0, 1]),
        ("definition", "minimum_boundary_gap"),
        ("point", [1, 0]),
    ],
)
def test_independent_ledger_contract_cannot_be_changed(field, wrong, tmp_path):
    model, records = fixture()
    width = records["extent_width"]
    row = ledger_for(width, contract("extent_width", [1, 0]), 20)
    ann = annotate(width, row)
    evidence = reviewed_evidence(model, row, ann, tmp_path)
    assert verify(model, evidence)["status"] == "passed"
    row["measurement_contract"][field] = wrong
    assert verify(model, evidence)["status"] != "passed"


def test_height_cannot_satisfy_width_in_complete_verify(tmp_path):
    model, records = fixture()
    height = records["extent_height"]
    row = ledger_for(height, contract("extent_height", [0, 1]), 10)
    ann = annotate(height, row)
    evidence = reviewed_evidence(model, row, ann, tmp_path)
    assert verify(model, evidence)["status"] == "passed"
    row["measurement_contract"] = contract("extent_width", [1, 0])
    assert verify(model, evidence)["status"] != "passed"


@pytest.mark.parametrize(
    "fields",
    [
        ["measurement_id"],
        ["model_hash"],
        ["section_id"],
        ["measurement_id", "model_hash", "section_id"],
    ],
)
def test_old_visual_review_ids_are_preserved_and_rejected(fields, tmp_path):
    model, records = fixture()
    row = ledger_for(records["extent_width"], contract("extent_width", [1, 0]), 20)
    ann = annotate(records["extent_width"], row)
    evidence = reviewed_evidence(model, row, ann, tmp_path)
    review = evidence["output_reviews"]["DIM-W"]
    for field in fields:
        review[field] = "OLD"
    snapshot = deepcopy(evidence)
    report = verify(model, evidence)
    assert report["status"] != "passed"
    assert evidence == snapshot
    for field in fields:
        assert report["dimensions"][0]["output_expression"]["evidence"][field] == "OLD"


@pytest.mark.parametrize("decimals", [0, 1])
def test_display_precision_follows_tolerance_at_builder_and_validator(decimals):
    model, records = fixture(width=10.4)
    record = records["extent_width"]
    row = ledger_for(record, contract("extent_width", [1, 0]), 10.4)
    with pytest.raises(ValueError, match="display precision"):
        drawing.build_section_annotation_rrecord(
            record,
            row,
            error_assessment=uncertainty(record),
            anchor=[0, 0],
            display_decimals=decimals,
        )
    ann = annotate(record, row)
    ann["display_decimals"] = decimals
    assert (
        drawing.validate_section_annotations_rreport(model, PLANE, [ann], [row])[
            "status"
        ]
        == "rejected"
    )


@pytest.mark.parametrize("target", ["image_path", "sidecar_path"])
def test_modified_reviewed_artifact_is_rejected(target, tmp_path):
    from pathlib import Path

    model, records = fixture()
    row = ledger_for(records["extent_width"], contract("extent_width", [1, 0]), 20)
    ann = annotate(records["extent_width"], row)
    evidence = reviewed_evidence(model, row, ann, tmp_path)
    assert verify(model, evidence)["status"] == "passed"
    path = Path(evidence["output_reviews"]["DIM-W"]["render_artifact"][target])
    path.write_bytes(path.read_bytes() + b" ")
    assert verify(model, evidence)["status"] != "passed"


def test_reviewed_render_must_match_current_annotation_not_just_model(tmp_path):
    model, records = fixture()
    row = ledger_for(records["extent_width"], contract("extent_width", [1, 0]), 20)
    ann = annotate(records["extent_width"], row)
    evidence = reviewed_evidence(model, row, ann, tmp_path)
    ann["anchor"] = [-20, 0]  # Also on the contour; old layout was not reviewed.
    assert (
        drawing.validate_section_annotations_rreport(model, PLANE, [ann], [row])[
            "status"
        ]
        == "verified"
    )
    assert verify(model, evidence)["status"] != "passed"


@pytest.mark.parametrize(
    "missing",
    [
        "measurement_contract",
        "kind",
        "definition",
        "direction",
        "point",
        "units",
        "coordinate_space",
    ],
)
def test_missing_semantic_contract_is_not_inferred(missing):
    _, records = fixture()
    record = records["extent_width"]
    row = ledger_for(record, contract("extent_width", [1, 0]), 20)
    if missing == "measurement_contract":
        row.pop(missing)
    else:
        row["measurement_contract"].pop(missing)
    assert (
        drawing.assess_dimension_rverdict(
            row, record, error_assessment=uncertainty(record)
        )["model_measurement"]["status"]
        != "passed"
    )


def test_directional_thickness_binds_line_point_even_when_values_match():
    model, _ = fixture()

    def probe(point):
        result = drawing.measure_model_section_rdimensions(
            model,
            PLANE,
            section_checks=box_checks(),
            directional_thickness=[
                {"id": "probe", "point": point, "direction": [1, 0]}
            ],
        )
        return next(
            m for m in result.measurements if m["kind"] == "thickness_directional"
        )

    first, second = probe([-10, 1]), probe([-10, 2])
    assert first["value"] == pytest.approx(second["value"])
    row = ledger_for(
        first,
        contract("thickness_directional", [1, 0], "material_length_on_line", [-10, 1]),
        20,
    )
    assert (
        drawing.assess_dimension_rverdict(
            row, first, error_assessment=uncertainty(first)
        )["model_measurement"]["status"]
        == "passed"
    )
    assert (
        drawing.assess_dimension_rverdict(
            row, second, error_assessment=uncertainty(second)
        )["model_measurement"]["status"]
        != "passed"
    )


def test_sufficient_display_precision_and_live_review_pass(tmp_path):
    model, records = fixture(width=10.4)
    record = records["extent_width"]
    row = ledger_for(record, contract("extent_width", [1, 0]), 10.4)
    annotation = drawing.build_section_annotation_rrecord(
        record,
        row,
        error_assessment=uncertainty(record),
        anchor=[0, 0],
        display_decimals=2,
    )
    evidence = reviewed_evidence(model, row, annotation, tmp_path)
    assert verify(model, evidence)["status"] == "passed"
    assert json.loads((tmp_path / "section.json").read_text())["dimensions"][0][
        "display_text"
    ][0].endswith("10.40")
    annotation["display_decimals"] = 0
    result = drawing.validate_section_annotations_rreport(
        model, PLANE, [annotation], [row]
    )
    assert any(
        "display precision" in error for error in result["dimensions"][0]["errors"]
    )
    assert verify(model, evidence)["status"] != "passed"
    with pytest.raises(ValueError, match="display precision"):
        drawing.render_model_section_rpath(
            model,
            PLANE,
            dimensions=[annotation],
            validation_ledger=[row],
            out_dir=tmp_path,
        )


@pytest.mark.parametrize(
    "missing", ["measurement_id", "model_hash", "section_id", "render_artifact"]
)
def test_missing_visual_identity_cannot_pass_or_count_as_reviewed(missing, tmp_path):
    model, records = fixture()
    row = ledger_for(records["extent_width"], contract("extent_width", [1, 0]), 20)
    ann = annotate(records["extent_width"], row)
    evidence = reviewed_evidence(model, row, ann, tmp_path)
    evidence["output_reviews"]["DIM-W"].pop(missing)
    report = verify(model, evidence)
    assert report["status"] != "passed"
    assert report["coverage"]["layout_reviewed"]["count"] == 0


def test_layout_review_counts_separately_when_association_is_pending(tmp_path):
    model, records = fixture()
    row = ledger_for(records["extent_width"], contract("extent_width", [1, 0]), 20)
    ann = annotate(records["extent_width"], row)
    evidence = reviewed_evidence(model, row, ann, tmp_path)
    evidence["output_reviews"]["DIM-W"]["association_status"] = "pending"
    report = verify(model, evidence)
    assert report["status"] != "passed"
    assert report["coverage"]["layout_reviewed"]["count"] == 1


@pytest.mark.parametrize(
    "value,band,decimals,expected",
    [
        (10.408, [10.389, 10.409], 2, "rejected"),
        (-10.408, [-10.409, -10.389], 2, "rejected"),
        (10, [10, 10], 0, "verified"),
        (10.123, [10.123, 10.123], 2, "rejected"),
        (10.123, [10.123, 10.123], 3, "verified"),
    ],
)
def test_display_rounding_boundary_cases(value, band, decimals, expected):
    from simplecadapi.inspect.drawing._measurement_contract import display_precision

    result = display_precision(
        value, decimals, {"tolerance_min": band[0], "tolerance_max": band[1]}
    )
    assert result["status"] == expected
