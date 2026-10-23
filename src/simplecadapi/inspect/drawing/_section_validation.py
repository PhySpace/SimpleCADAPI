"""Basic solid validity and independent section/material/display point checks."""

import math
from collections.abc import Mapping

import numpy as np
from simplecadapi._cpp.occt.BRep import BRep_Tool
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer
from simplecadapi._cpp.occt.BRepClass import BRepClass_FaceClassifier
from simplecadapi._cpp.occt.BRepClass3d import BRepClass3d_SolidClassifier
from simplecadapi._cpp.occt.TopAbs import TopAbs_SOLID, TopAbs_SHELL, TopAbs_IN, TopAbs_OUT, TopAbs_ON
from simplecadapi._cpp.occt.TopExp import TopExp_Explorer
from simplecadapi._cpp.occt.TopoDS import TopoDS
from simplecadapi._cpp.occt.gp import gp_Pnt

from ..brep.queries import _point_in_polygon
from ._provenance import digest


def shapes(source, kind):
    explorer = TopExp_Explorer(source, kind)
    found = []
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def _state(states):
    if TopAbs_IN in states:
        return "material"
    if TopAbs_ON in states:
        return "boundary"
    return "void" if states and all(s == TopAbs_OUT for s in states) else "unknown"


def _display_state(point, contours, tolerance):
    inside = 0
    for contour in contours:
        if not contour["closed"]:
            return "unknown"
        polygon = contour["samples_2d"]
        for a, b in zip(polygon, polygon[1:]):
            a, b = np.asarray(a), np.asarray(b)
            vector = b - a
            scale = float(np.dot(vector, vector))
            t = min(1, max(0, float(np.dot(point - a, vector)) / scale)) if scale else 0
            if np.linalg.norm(point - (a + t * vector)) <= tolerance:
                return "boundary"
        inside += int(_point_in_polygon(point, polygon))
    return "material" if inside % 2 else "void"


def validate_section(source, section, material, faces, holes, checks):
    solids = [TopoDS.Solid_s(s) for s in shapes(source, TopAbs_SOLID)]
    shells = shapes(source, TopAbs_SHELL)
    basic = {
        "solid_count": len(solids),
        "model_valid": BRepCheck_Analyzer(source).IsValid(),
        "model_closed": bool(shells) and all(BRep_Tool.IsClosed_s(s) for s in shells),
        "section_closed": bool(section["contours"])
        and section["open_contour_count"] == 0,
        "material_faces_valid": bool(faces)
        and all(BRepCheck_Analyzer(f).IsValid() for f in faces),
        "face_count": len(faces),
        "hole_count": len(holes),
    }
    failures, missing, observations = [], [], []

    def fail(owner, message):
        failures.append({"owner": owner, "reason": message})

    if not basic["model_valid"] or (solids and not basic["model_closed"]):
        fail("model_validity", "source geometry is invalid or not closed")
    if not basic["section_closed"]:
        fail("section_intersection", "section is empty or has open contours")
    if material:
        for error in material.get("material_topology", {}).get("errors", []):
            fail("section_intersection", error)
        if not basic["material_faces_valid"]:
            fail("section_intersection", "material faces are absent or invalid")
        if len(section["contours"]) != len(material["contours"]):
            fail(
                "section_intersection",
                "section contour count differs from material-face rings",
            )
        if sum(c.get("role") == "hole" for c in section["contours"]) != len(holes):
            fail(
                "section_intersection",
                "section inner/outer ring classification differs from BREP topology",
            )
    else:
        missing.append("material-face reference unavailable")
    if not isinstance(checks, Mapping):
        missing.append("independent section_checks contract missing")
    else:
        required = [
            "expected_origin",
            "expected_normal",
            "expected_x_direction",
            "expected_y_direction",
            "expected_solid_count",
            "expected_face_count",
            "expected_hole_count",
            "material_points",
            "void_points",
            "point_tolerance_mm",
            "tolerance_basis",
            "evidence",
        ]
        missing.extend(
            f"section_checks.{key} missing" for key in required if key not in checks
        )
        try:
            tolerance = float(checks["point_tolerance_mm"])
            if not math.isfinite(tolerance) or tolerance <= 0:
                raise ValueError("point_tolerance_mm must be finite and positive")
            if not checks.get("tolerance_basis") or not checks.get("evidence"):
                raise ValueError(
                    "section check thresholds and expectations need evidence"
                )
            if section.get("topological_endpoint_snap_max_mm", 0.0) > tolerance:
                missing.append(
                    "curve endpoint snapping exceeds the declared point tolerance"
                )
            for field in ("origin", "normal", "x_direction", "y_direction"):
                expected = np.array(checks["expected_" + field], dtype=float, copy=True)
                if expected.shape != (3,) or not np.isfinite(expected).all():
                    raise ValueError(f"invalid expected_{field}")
                if field != "origin":
                    magnitude = np.linalg.norm(expected)
                    if magnitude == 0:
                        raise ValueError(f"zero expected_{field}")
                    expected /= magnitude
                threshold = tolerance if field == "origin" else 1e-10
                if not np.allclose(
                    expected, section["plane"][field], atol=threshold, rtol=0
                ):
                    fail(
                        "section_definition",
                        f"section {field} differs from drawing contract",
                    )
            for field in ("solid_count", "face_count", "hole_count"):
                expected = checks["expected_" + field]
                if type(expected) is not int or expected < 0:
                    raise ValueError(f"expected_{field} must be a nonnegative integer")
                if basic[field] != expected:
                    fail(
                        (
                            "model_validity"
                            if field == "solid_count"
                            else "section_intersection"
                        ),
                        f"unexpected {field}",
                    )
            if not solids:
                fail(
                    "model_validity", "formal section evidence requires a closed solid"
                )
            covered_faces, covered_holes, ids = set(), set(), set()
            for kind in ("material", "void"):
                points = checks[kind + "_points"]
                if not isinstance(points, list):
                    raise ValueError(f"{kind}_points must be a list")
                for probe in points:
                    point = np.asarray(probe["point"], float)
                    if (
                        not probe["id"]
                        or probe["id"] in ids
                        or point.shape != (2,)
                        or not np.isfinite(point).all()
                    ):
                        raise ValueError(
                            "probes need unique IDs and finite section-local points"
                        )
                    ids.add(probe["id"])
                    world = np.asarray(section["plane"]["origin"]) + point @ np.asarray(
                        [
                            section["plane"]["x_direction"],
                            section["plane"]["y_direction"],
                        ]
                    )
                    location = gp_Pnt(*world)
                    model_state = _state(
                        [
                            BRepClass3d_SolidClassifier(s, location, tolerance).State()
                            for s in solids
                        ]
                    )
                    face_states = [
                        BRepClass_FaceClassifier(f, location, tolerance).State()
                        for f in faces
                    ]
                    material_state = _state(face_states)
                    display_state = _display_state(
                        point, section["contours"], tolerance
                    )
                    observations.append(
                        {
                            "id": probe["id"],
                            "point": point.tolist(),
                            "world_point": world.tolist(),
                            "expected": kind,
                            "model": model_state,
                            "section": material_state,
                            "display": display_state,
                        }
                    )
                    if (
                        model_state in ("boundary", "unknown")
                        or material_state in ("boundary", "unknown")
                        or display_state in ("boundary", "unknown")
                    ):
                        missing.append(
                            f"probe {probe['id']} lies on a boundary or is indeterminate"
                        )
                    if model_state in ("material", "void") and model_state != kind:
                        fail(
                            "model_geometry_or_requirement",
                            f"probe {probe['id']} contradicts the independent solid classification",
                        )
                    if (
                        material_state in ("material", "void")
                        and model_state in ("material", "void")
                        and material_state != model_state
                    ):
                        fail(
                            "section_intersection",
                            f"probe {probe['id']} differs between solid and material face",
                        )
                    if (
                        display_state in ("material", "void")
                        and model_state in ("material", "void")
                        and display_state != model_state
                    ):
                        fail(
                            "section_display",
                            f"probe {probe['id']} differs between solid and rendered polygons",
                        )
                    if (
                        kind == "material"
                        and model_state == material_state == display_state == kind
                    ):
                        covered_faces.update(
                            i
                            for i, state in enumerate(face_states)
                            if state == TopAbs_IN
                        )
                    if (
                        kind == "void"
                        and model_state == material_state == display_state == kind
                    ):
                        covered_holes.update(
                            i
                            for i, hole in enumerate(holes)
                            if BRepClass_FaceClassifier(
                                hole, location, tolerance
                            ).State()
                            == TopAbs_IN
                        )
            if covered_faces != set(range(len(faces))) or not covered_faces:
                missing.append(
                    "representative material points do not cover every material face"
                )
            if covered_holes != set(range(len(holes))):
                missing.append("representative void points do not cover every hole")
        except (KeyError, TypeError, ValueError) as exc:
            missing.append(f"invalid section_checks contract: {exc}")
    return {
        "status": "failed" if failures else "pending" if missing else "passed",
        "basic": basic,
        "probes": observations,
        "failures": failures,
        "missing": missing,
        "contract_id": digest(checks) if checks is not None else None,
        "direction_tolerance": 1e-10,
        "direction_tolerance_basis": "normalized frame comparison only; not a dimensional error bound",
    }
