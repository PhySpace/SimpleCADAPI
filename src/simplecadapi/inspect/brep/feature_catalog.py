"""Normalized per-instance computational-geometry feature catalog."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

from .manufacturing import ModelInput, _model, inspect_manufacturing_hints_rdescriptor
from .reconstruction_contract import build_reconstruction_contract


CATALOG_SCHEMA_VERSION = "4.1"
FEATURE_CATEGORIES = (
    "hole",
    "extrusion",
    "revolution",
    "loft",
    "sweep",
    "fillet",
    "chamfer",
    "sheet_metal",
)
FEATURE_FIELDS = (
    "feature_id",
    "category",
    "subtype",
    "display_name",
    "claim",
    "body_id",
    "entity_ids",
    "highlight_entity_ids",
    "support_entity_ids",
    "location",
    "dimensions",
    "profile",
    "relationships",
    "evidence",
    "confidence",
    "visuals",
    "limitations",
    "reconstruction",
    "target_sha256",
)

_CATEGORY_ORDER = {value: index for index, value in enumerate(FEATURE_CATEGORIES)}
_DISPLAY_NAMES = {
    "whole_body_prism": "整实体棱柱拉伸式几何",
    "local_boss": "局部凸台",
    "rib_or_web": "筋板或腹板",
    "blind_pocket": "盲凹槽",
    "open_slot_or_notch": "开放槽或缺口",
    "through_cut_region": "贯穿切除区域",
    "whole_body_full_revolution": "整实体完整旋转式几何",
    "whole_body_partial_revolution": "整实体部分旋转式几何",
    "local_full_revolved_boss": "局部整周旋转凸台",
    "local_partial_revolved_boss": "局部部分旋转凸台",
    "local_full_revolved_groove": "局部整周旋转凹槽",
    "local_partial_revolved_cut": "局部部分旋转切除",
    "whole_body_profile_loft": "整实体轮廓放样",
    "whole_body_point_loft": "整实体点终端放样",
    "local_lofted_boss": "局部放样凸台",
    "local_lofted_cut": "局部放样切除",
    "whole_body_path_sweep": "整实体路径扫掠",
    "local_swept_boss": "局部扫掠凸台",
    "local_swept_cut": "局部扫掠切除",
    "twisted_sweep": "扭转扫掠",
    "helical_sweep": "螺旋扫掠",
    "circular_through": "圆形贯穿孔",
    "circular_blind": "圆形盲孔",
    "counterbore": "沉孔",
    "countersink": "沉头孔",
    "circular_stepped": "多级台阶圆孔",
    "tapered_hole": "锥孔",
    "obround_through": "长圆贯穿孔",
    "obround_blind": "长圆盲孔",
    "rectangular": "矩形或圆角矩形孔",
    "polygonal": "多边形孔",
    "d_or_keyhole": "D 形或钥匙孔",
    "freeform_profile": "自由轮廓孔",
    "profile_stepped": "异形台阶孔",
    "cylindrical_constant": "圆柱等半径圆角",
    "toroidal_constant": "圆环等半径圆角",
    "spherical_corner": "球面角部圆角",
    "planar_bevel": "平面边倒角",
    "conical_bevel": "圆锥边倒角",
    "flat_sheet_body": "平板体",
    "formed_sheet_body": "成形钣金体",
    "cylindrical_bend": "圆柱折弯",
}


def _entity_index(entity_id: str) -> int:
    return int(entity_id.split(":", 1)[1])


def _stable_ids(values: Sequence[str]) -> list[str]:
    return sorted(
        dict.fromkeys(values),
        key=lambda value: (
            {"body": 0, "face": 1, "edge": 2, "vertex": 3}.get(
                value.split(":", 1)[0], 4
            ),
            _entity_index(value),
        ),
    )


def _target_hash(model, original: ModelInput) -> str:
    candidate = Path(original) if isinstance(original, (str, Path)) else None
    if candidate is None and model.source:
        candidate = Path(model.source)
    if candidate is not None and candidate.is_file():
        digest = hashlib.sha256()
        with candidate.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    entities = []
    for kind, collection in (
        ("body", model.bodies),
        ("face", model.faces),
        ("edge", model.edges),
        ("vertex", model.vertices),
    ):
        entities.extend(
            model.describe_entity(f"{kind}:{index}") for index in range(len(collection))
        )
    payload = json.dumps(
        entities,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _dimension(value: Any, unit: str, reason: str) -> dict[str, Any]:
    if value is None:
        return {"value": None, "unit": unit, "unavailable_reason": reason}
    number = float(value)
    if not math.isfinite(number):
        return {"value": None, "unit": unit, "unavailable_reason": reason}
    return {"value": number, "unit": unit}


def _profile_dimensions(profile: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    profile = profile or {}
    reason = "轮廓中未提供该测量值"
    return {
        "profile_width": _dimension(profile.get("width"), "mm", reason),
        "profile_height": _dimension(profile.get("height"), "mm", reason),
        "profile_area": _dimension(profile.get("area"), "mm^2", reason),
        "profile_perimeter": _dimension(profile.get("perimeter"), "mm", reason),
        "maximum_caliper": _dimension(profile.get("maximum_caliper"), "mm", reason),
        "minimum_caliper": _dimension(profile.get("minimum_caliper"), "mm", reason),
    }


def _category_subtype(hint: dict[str, Any]) -> tuple[str, str]:
    kind = hint["kind"]
    geometry = hint["geometry"]
    if kind == "extrusion_region_candidate":
        return "extrusion", geometry["form"]
    if kind == "revolution_region_candidate":
        return "revolution", geometry["form"]
    if kind == "loft_region_candidate":
        return "loft", geometry["form"]
    if kind == "sweep_region_candidate":
        return "sweep", geometry["form"]
    if kind == "hole_region_candidate":
        aliases = {
            "through_hole": "circular_through",
            "blind_hole": "circular_blind",
            "stepped_hole": "circular_stepped",
        }
        return "hole", aliases.get(geometry["form"], geometry["form"])
    if kind == "fillet_region_candidate":
        return (
            "fillet",
            {
                "CYLINDER": "cylindrical_constant",
                "TORUS": "toroidal_constant",
                "SPHERE": "spherical_corner",
            }[geometry["carrier_type"]],
        )
    if kind == "chamfer_region_candidate":
        return "chamfer", geometry["form"]
    if kind == "sheet_metal_body_candidate":
        subtype = "formed_sheet_body" if geometry["formed"] else "flat_sheet_body"
        return "sheet_metal", subtype
    if kind == "sheet_metal_bend_candidate":
        return "sheet_metal", "cylindrical_bend"
    raise ValueError(f"Unsupported manufacturing hint kind: {kind}")


def _profile(hint: dict[str, Any], category: str) -> dict[str, Any]:
    geometry = hint["geometry"]
    if category in {"extrusion", "loft", "sweep"}:
        return dict(geometry.get("profile") or {})
    if category == "revolution":
        return dict(geometry.get("profile") or {})
    if category != "hole":
        return {}
    profiles = geometry.get("profiles") or []
    if profiles:
        return dict(profiles[0])
    segments = geometry.get("segments") or []
    return {
        "family": geometry.get("profile_family", "circular"),
        "kind": "circular",
        "role": "inner",
        "segment_count": len(segments),
        "curve_types": sorted(
            {
                "CIRCLE" if item.get("carrier") == "cylinder" else "CONE"
                for item in segments
            }
        ),
        "diameters": list(geometry.get("diameters") or []),
    }


def _location(hint: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    geometry = hint["geometry"]
    axis = geometry.get("axis") or (geometry.get("helix_fit") or {}).get("axis") or {}
    return {
        "center": geometry.get("entry_center")
        or profile.get("centroid")
        or axis.get("point"),
        "local_origin": profile.get("centroid") or axis.get("point"),
        "direction": geometry.get("direction") or axis.get("direction"),
        "local_x_direction": geometry.get("local_x_direction")
        or profile.get("local_x_direction"),
        "local_y_direction": geometry.get("local_y_direction")
        or profile.get("local_y_direction"),
        "axis": dict(axis) if axis else None,
    }


def _dimensions(
    hint: dict[str, Any], category: str, subtype: str, profile: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    geometry = hint["geometry"]
    result: dict[str, dict[str, Any]] = {}
    if category in {"hole", "extrusion", "loft", "sweep"}:
        result.update(_profile_dimensions(profile))
    if category == "hole":
        diameters = geometry.get("diameters") or profile.get("diameters") or []
        result.update(
            {
                "depth": _dimension(
                    geometry.get("total_depth"), "mm", "孔深无法从终端面确定"
                ),
                "entry_diameter": _dimension(
                    diameters[0] if diameters else None,
                    "mm",
                    "非圆轮廓不适用圆孔直径",
                ),
                "terminal_diameter": _dimension(
                    diameters[-1] if diameters else None,
                    "mm",
                    "非圆轮廓不适用圆孔直径",
                ),
                "segment_count": _dimension(
                    len(geometry.get("segments") or []), "count", "孔段不可用"
                ),
            }
        )
        cone = next(
            (
                item
                for item in geometry.get("segments") or []
                if item.get("carrier") == "cone"
            ),
            {},
        )
        result["cone_angle"] = _dimension(
            cone.get("included_angle_degrees") or cone.get("semi_angle_degrees"),
            "degree",
            "该孔没有可测圆锥段",
        )
    elif category == "extrusion":
        result["length"] = _dimension(
            geometry.get("length"), "mm", "拉伸起止截面距离不可用"
        )
    elif category == "revolution":
        result = {
            "sweep_angle": _dimension(
                geometry.get("sweep_angle_degrees"),
                "degree",
                "旋转角域不可用",
            ),
            "minimum_radius": _dimension(
                geometry.get("minimum_radius"), "mm", "最小半径不可用"
            ),
            "maximum_radius": _dimension(
                geometry.get("maximum_radius"), "mm", "最大半径不可用"
            ),
            "axial_span": _dimension(
                geometry.get("axial_span"), "mm", "轴向范围不可用"
            ),
        }
    elif category == "loft":
        alignment = geometry.get("endpoint_alignment") or {}
        stations = (geometry.get("section_family") or {}).get("stations") or []
        endpoint_areas = [
            float(contour.get("area"))
            for station in stations[:: max(len(stations) - 1, 1)]
            for contour in station.get("contours", [])[:1]
            if contour.get("area") is not None
        ]
        result.update(
            {
                "length": _dimension(geometry.get("length"), "mm", "端点距离不可用"),
                "start_area": _dimension(
                    endpoint_areas[0] if endpoint_areas else profile.get("area"),
                    "mm^2",
                    "起始截面面积不可用",
                ),
                "end_area": _dimension(
                    endpoint_areas[-1] if endpoint_areas else None,
                    "mm^2",
                    "终止截面为点或面积不可用",
                ),
                "endpoint_scale": _dimension(
                    alignment.get("scale"), "ratio", "点终端或轮廓配准不可用"
                ),
                "rigid_fit_error": _dimension(
                    alignment.get("rigid_maximum_error"),
                    "mm",
                    "点终端或轮廓配准不可用",
                ),
            }
        )
    elif category == "sweep":
        helix = geometry.get("helix_fit") or {}
        result.update(
            {
                "path_chord_length": _dimension(
                    geometry.get("path_chord_length"), "mm", "路径弦长不可用"
                ),
                "twist_angle": _dimension(
                    geometry.get("twist_angle_degrees"),
                    "degree",
                    "非扭转扫掠不适用扭转角",
                ),
                "helix_radius": _dimension(
                    helix.get("radius"), "mm", "非螺旋扫掠不适用螺旋半径"
                ),
                "helix_pitch": _dimension(
                    helix.get("pitch"), "mm", "非螺旋扫掠不适用螺距"
                ),
                "helix_turn_count": _dimension(
                    helix.get("turn_count"), "turn", "非螺旋扫掠不适用圈数"
                ),
            }
        )
    elif category == "fillet":
        result = {
            "radius": _dimension(geometry.get("radius"), "mm", "解析载体未提供半径"),
            "effective_length": _dimension(
                geometry.get("effective_length"), "mm", "尚未稳定测得有效长度"
            ),
            "sweep_angle": _dimension(
                geometry.get("sweep_angle_degrees"),
                "degree",
                "尚未稳定测得扫角",
            ),
            "surface_area": _dimension(
                geometry.get("surface_area"), "mm^2", "圆角面积不可用"
            ),
            "major_radius": _dimension(
                geometry.get("major_radius"), "mm", "仅圆环载体适用大半径"
            ),
        }
    elif category == "chamfer":
        setbacks = geometry.get("support_setbacks") or [None, None]
        result = {
            "area": _dimension(geometry.get("area"), "mm^2", "倒角面积不可用"),
            "support_angle": _dimension(
                geometry.get("support_angle_degrees"),
                "degree",
                "圆锥倒角不使用平面支撑夹角",
            ),
            "semi_angle": _dimension(
                geometry.get("semi_angle_degrees"),
                "degree",
                "平面倒角不使用圆锥半角",
            ),
            "face_width": _dimension(
                geometry.get("face_width"), "mm", "尚未稳定测得斜面宽度"
            ),
            "length": _dimension(geometry.get("length"), "mm", "倒角边界长度不可用"),
            "first_setback": _dimension(
                setbacks[0], "mm", "最终 BRep 未稳定确定第一支撑面退距"
            ),
            "second_setback": _dimension(
                setbacks[-1], "mm", "最终 BRep 未稳定确定第二支撑面退距"
            ),
            "reference_radius": _dimension(
                geometry.get("reference_radius"), "mm", "平面倒角不适用参考半径"
            ),
        }
    elif subtype == "cylindrical_bend":
        result = {
            "inside_radius": _dimension(
                geometry.get("inside_radius"), "mm", "内半径不可用"
            ),
            "outside_radius": _dimension(
                geometry.get("outside_radius"), "mm", "外半径不可用"
            ),
            "neutral_radius": _dimension(
                geometry.get("mid_radius"), "mm", "中性半径不可用"
            ),
            "thickness": _dimension(geometry.get("thickness"), "mm", "厚度不可用"),
            "sweep_angle": _dimension(
                geometry.get("geometric_sweep_angle_degrees"), "degree", "扫角不可用"
            ),
            "bend_length": _dimension(
                geometry.get("bend_length"), "mm", "折弯长度不可用"
            ),
        }
    else:
        thickness_range = geometry.get("thickness_range") or [None, None]
        result = {
            "thickness": _dimension(geometry.get("thickness"), "mm", "厚度不可用"),
            "minimum_thickness": _dimension(thickness_range[0], "mm", "厚度范围不可用"),
            "maximum_thickness": _dimension(
                thickness_range[-1], "mm", "厚度范围不可用"
            ),
            "midsurface_area": _dimension(
                geometry.get("midsurface_area"), "mm^2", "中性面估算面积不可用"
            ),
            "bend_count": _dimension(
                geometry.get("bend_count"), "count", "折弯数不可用"
            ),
            "extent_x": _dimension(
                (geometry.get("bounding_box_size") or [None, None, None])[0],
                "mm",
                "外包尺寸不可用",
            ),
            "extent_y": _dimension(
                (geometry.get("bounding_box_size") or [None, None, None])[1],
                "mm",
                "外包尺寸不可用",
            ),
            "extent_z": _dimension(
                (geometry.get("bounding_box_size") or [None, None, None])[2],
                "mm",
                "外包尺寸不可用",
            ),
        }
    return result


def _deduplicate(hints: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse alternate whole-body extrusion directions into one instance."""

    result = []
    seen_whole: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for hint in hints:
        if (
            hint["kind"] != "extrusion_region_candidate"
            or hint["geometry"].get("form") != "whole_body_prism"
        ):
            result.append(hint)
            continue
        key = (hint["body_id"], tuple(_stable_ids(hint["entity_ids"])))
        existing = seen_whole.get(key)
        if existing is None:
            copied = {**hint, "geometry": dict(hint["geometry"])}
            copied["geometry"]["alternative_directions"] = []
            seen_whole[key] = copied
            result.append(copied)
        else:
            existing["geometry"]["alternative_directions"].append(
                list(hint["geometry"].get("direction") or [])
            )
    return result


def _resolve_conflicts(hints: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve equivalent whole-body explanations by geometric specificity."""

    values = list(hints)
    groups: defaultdict[tuple[str, tuple[str, ...]], list[int]] = defaultdict(list)
    for index, hint in enumerate(values):
        geometry = hint["geometry"]
        whole = geometry.get("coverage") == "whole_body" or geometry.get("form") in {
            "whole_body_prism",
            "whole_body_full_revolution",
            "whole_body_partial_revolution",
        }
        if whole:
            groups[(hint["body_id"], tuple(_stable_ids(hint["entity_ids"])))].append(
                index
            )
    rank = {
        "whole_body_full_revolution": 500,
        "whole_body_partial_revolution": 490,
        "whole_body_prism": 400,
        "helical_sweep": 330,
        "twisted_sweep": 320,
        "whole_body_path_sweep": 310,
        "whole_body_point_loft": 210,
        "whole_body_profile_loft": 200,
    }
    suppressed: set[int] = set()
    for (body_id, _entities), indices in groups.items():
        recognized = [
            index for index in indices if values[index]["geometry"].get("form") in rank
        ]
        if len(recognized) < 2:
            continue
        primary_index = min(
            recognized,
            key=lambda index: (
                -rank[values[index]["geometry"]["form"]],
                index,
            ),
        )
        primary = values[primary_index]
        primary_category, primary_subtype = _category_subtype(primary)
        alternatives = []
        for index in recognized:
            if index == primary_index:
                continue
            alternative = values[index]
            category, subtype = _category_subtype(alternative)
            if category == primary_category and subtype == primary_subtype:
                suppressed.add(index)
                continue
            suppressed.add(index)
            alternatives.append(
                {
                    "category": category,
                    "subtype": subtype,
                    "direction": list(alternative["geometry"].get("direction") or []),
                    "reason": (
                        f"same_final_brep_prefers_{primary_category}_{primary_subtype}"
                    ),
                }
            )
        if alternatives:
            copied = {**primary, "geometry": dict(primary["geometry"])}
            copied["geometry"][
                "conflict_group_id"
            ] = f"conflict-{body_id.replace(':', '-')}-generation-law"
            copied["geometry"]["alternative_interpretations"] = alternatives
            values[primary_index] = copied
    for loft_index, loft in enumerate(values):
        if loft["geometry"].get("form") != "whole_body_point_loft":
            continue
        loft_entities = set(loft["entity_ids"])
        alternatives = list(loft["geometry"].get("alternative_interpretations", []))
        for detail_index, detail in enumerate(values):
            if detail_index == loft_index or detail_index in suppressed:
                continue
            if detail["body_id"] != loft["body_id"] or detail["kind"] not in {
                "fillet_region_candidate",
                "chamfer_region_candidate",
            }:
                continue
            if not set(detail["entity_ids"]).issubset(loft_entities):
                continue
            category, subtype = _category_subtype(detail)
            suppressed.add(detail_index)
            alternatives.append(
                {
                    "category": category,
                    "subtype": subtype,
                    "direction": [],
                    "reason": "point_loft_side_face_is_not_a_local_edge_treatment",
                }
            )
        if alternatives:
            copied = {**loft, "geometry": dict(loft["geometry"])}
            copied["geometry"][
                "conflict_group_id"
            ] = f"conflict-{loft['body_id'].replace(':', '-')}-point-loft"
            copied["geometry"]["alternative_interpretations"] = alternatives
            values[loft_index] = copied
    return [value for index, value in enumerate(values) if index not in suppressed]


def _visuals(category: str, feature_id: str) -> dict[str, str | None]:
    base = f"highlights/{category}/{feature_id}"
    sectional = category in {"hole", "extrusion", "revolution", "loft", "sweep"}
    return {
        "overview": "highlights/all-features.png",
        "isometric": f"{base}/isometric.png",
        "context": f"{base}/context.png",
        "profile": f"profiles/{feature_id}.png" if sectional else None,
        "longitudinal_section": (
            f"sections/{feature_id}-longitudinal.png" if sectional else None
        ),
        "transverse_section": (
            f"sections/{feature_id}-transverse.png" if sectional else None
        ),
        "angular_sections": (
            f"sections/{feature_id}-angular.png" if category == "revolution" else None
        ),
    }


def inspect_geometric_features_rdescriptor(
    model_or_path: ModelInput,
    *,
    feature_kinds: Sequence[str] = FEATURE_CATEGORIES,
    tolerance: float | None = None,
    angular_tolerance_degrees: float = 0.5,
    max_features: int = 500,
) -> dict[str, Any]:
    """Return the normalized v4 catalog for final-BREP geometric candidates.

    ``extrusion`` means extrusion-style geometry; ``whole_body_prism`` is only
    one subtype. ``revolution`` covers whole and local, full and partial-angle
    geometry. Circular and non-circular closed negative spaces remain under the
    ``hole`` category. Values describe final geometry, not original CAD history
    or manufacturing intent.
    """

    if max_features < 1:
        raise ValueError("max_features must be at least one")
    requested = tuple(dict.fromkeys(str(value) for value in feature_kinds))
    unknown = sorted(set(requested) - set(FEATURE_CATEGORIES))
    if unknown:
        raise ValueError(
            "feature_kinds contains unsupported values: " + ", ".join(unknown)
        )
    model = _model(model_or_path)
    target_sha256 = _target_hash(model, model_or_path)
    raw = inspect_manufacturing_hints_rdescriptor(
        model,
        feature_kinds=requested,
        tolerance=tolerance,
        angular_tolerance_degrees=angular_tolerance_degrees,
        max_hints=max(500, max_features * 20),
    )
    hints = _resolve_conflicts(_deduplicate(raw["hints"]))
    sortable = []
    for hint in hints:
        category, subtype = _category_subtype(hint)
        sortable.append((hint, category, subtype))
    sortable.sort(
        key=lambda item: (
            _entity_index(item[0]["body_id"]),
            _CATEGORY_ORDER[item[1]],
            item[2],
            tuple(_entity_index(value) for value in _stable_ids(item[0]["entity_ids"])),
            tuple(float(value) for value in item[0]["geometry"].get("direction", ())),
        )
    )
    truncated = raw["truncated"] or len(sortable) > max_features
    returned = sortable[:max_features]
    counters: Counter[str] = Counter()
    feature_ids: dict[str, str] = {}
    assigned = []
    for hint, category, subtype in returned:
        counters[category] += 1
        feature_id = f"{category}-{counters[category]:04d}"
        feature_ids[hint["hint_id"]] = feature_id
        assigned.append((hint, category, subtype, feature_id))
    features = []
    for hint, category, subtype, feature_id in assigned:
        profile = _profile(hint, category)
        parent = feature_ids.get(hint.get("parent_hint_id", ""))
        alternative_directions = hint["geometry"].get("alternative_directions", [])
        conflict_alternatives = hint["geometry"].get("alternative_interpretations", [])
        relationships = {
            "parent_feature_id": parent,
            "child_feature_ids": [],
            "intersects_feature_ids": [],
            "contains_feature_ids": [],
            "conflict_group_id": hint["geometry"].get("conflict_group_id"),
            "duplicate_group_id": None,
            "alternative_interpretations": [
                {
                    "category": "extrusion",
                    "subtype": "whole_body_prism",
                    "direction": direction,
                    "reason": "whole_body_prism_direction_ambiguity",
                }
                for direction in alternative_directions
            ]
            + [dict(value) for value in conflict_alternatives],
        }
        feature = {
            "feature_id": feature_id,
            "category": category,
            "subtype": subtype,
            "display_name": _DISPLAY_NAMES[subtype],
            "claim": "geometric_candidate",
            "body_id": hint["body_id"],
            "entity_ids": _stable_ids(hint["entity_ids"]),
            "highlight_entity_ids": _stable_ids(hint["highlight_entity_ids"]),
            "support_entity_ids": _stable_ids(hint["support_entity_ids"]),
            "location": _location(hint, profile),
            "dimensions": _dimensions(hint, category, subtype, profile),
            "profile": profile,
            "relationships": relationships,
            "evidence": list(hint["evidence"]),
            "confidence": dict(hint["confidence"]),
            "visuals": _visuals(category, feature_id),
            "limitations": [
                "最终 BRep 只能支持几何候选，不能证明原始建模命令或创建顺序"
            ],
            "reconstruction": build_reconstruction_contract(
                category=category,
                geometry=hint["geometry"],
                feature_id=feature_id,
                entity_ids=_stable_ids(hint["entity_ids"]),
                confidence=dict(hint["confidence"]),
            ),
            "target_sha256": target_sha256,
        }
        if set(feature) != set(FEATURE_FIELDS):
            raise RuntimeError("internal feature catalog field contract mismatch")
        features.append(feature)
    children: defaultdict[str, list[str]] = defaultdict(list)
    for feature in features:
        parent = feature["relationships"]["parent_feature_id"]
        if parent:
            children[parent].append(feature["feature_id"])
    for feature in features:
        feature["relationships"]["child_feature_ids"] = children[feature["feature_id"]]
    for feature in features:
        if feature["category"] != "revolution" or not feature["subtype"].startswith(
            "local_"
        ):
            continue
        parent = next(
            (
                candidate
                for candidate in features
                if candidate["category"] == "revolution"
                and candidate["body_id"] == feature["body_id"]
                and candidate["subtype"].startswith("whole_body_")
                and set(feature["entity_ids"]).issubset(candidate["entity_ids"])
            ),
            None,
        )
        if parent is None:
            continue
        feature["relationships"]["parent_feature_id"] = parent["feature_id"]
        parent["relationships"]["contains_feature_ids"].append(feature["feature_id"])
        parent["relationships"]["child_feature_ids"].append(feature["feature_id"])
    subtype_counts = Counter(feature["subtype"] for feature in features)
    omitted = max(len(sortable) - max_features, 0) + int(raw["omitted_hint_count"])
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "units": dict(raw["units"]),
        "target_sha256": target_sha256,
        "feature_kinds": list(requested),
        "tolerances": dict(raw["tolerances"]),
        "raw_feature_hints": list(raw["hints"]),
        "features": features,
        "summary": {
            "analyzed_body_count": raw["summary"]["analyzed_body_count"],
            "analyzed_face_count": raw["summary"]["analyzed_face_count"],
            "feature_count": len(features),
            "category_counts": dict(sorted(counters.items())),
            "subtype_counts": dict(sorted(subtype_counts.items())),
        },
        "diagnostics": list(raw["diagnostics"]),
        "truncated": bool(truncated),
        "complete": not truncated,
        "omitted_feature_count": omitted,
    }


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "FEATURE_CATEGORIES",
    "FEATURE_FIELDS",
    "inspect_geometric_features_rdescriptor",
]
