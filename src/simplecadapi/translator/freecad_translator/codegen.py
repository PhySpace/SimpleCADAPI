"""Pure code-generation helpers shared by the FreeCAD compiler and emitters."""

from __future__ import annotations

import hashlib
import json
import pprint
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from simplecadapi._cpp import (
    expression_uses_units,
    ExpressionGraph,
    infer_dimension,
    OperationNode,
    unit_from_payload,
)


def _json_ascii(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _py_literal(value: Any) -> str:
    return pprint.pformat(value, compact=True, sort_dicts=True, width=120)


def _expression_physical_metadata(
    nodes: Sequence[Any],
) -> Tuple[Dict[str, str], Dict[str, bool]]:
    graph = ExpressionGraph.from_dict({"nodes": list(nodes)})
    dimensions: Dict[str, str] = {}
    unit_aware: Dict[str, bool] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        expr_id = str(node.get("expr_id", ""))
        expr = graph.get(expr_id)
        if expr is None:
            continue
        dimension = infer_dimension(expr)
        dimensions[expr_id] = "Legacy" if dimension is None else dimension.name
        unit_aware[expr_id] = expression_uses_units(expr)
    return dimensions, unit_aware


def _canonical_variable_default(node: Dict[str, Any]) -> float:
    value = float(node.get("default", 0.0))
    unit_payload = node.get("unit")
    if unit_payload is None:
        return value
    return unit_from_payload(unit_payload).to_canonical(value)


def _safe_name(raw: str, *, prefix: str = "obj") -> str:
    token = "".join(ch if ch.isalnum() else "_" for ch in raw)
    token = token.strip("_")
    if not token:
        token = prefix
    if token[0].isdigit():
        token = f"{prefix}_{token}"
    return token


_OP_EXPRESSION_BINDINGS: Dict[str, Tuple[Tuple[str, Tuple[Any, ...]], ...]] = {
    "make_line_redge": (),
    "make_circle_redge": (),
    "make_angle_arc_redge": (),
    "make_three_point_arc_redge": (),
    "make_spline_redge": (),
    "make_wire_from_edges_rwire": (),
    "make_helix_redge": (
        ("Pitch", ("pitch",)),
        ("Height", ("height",)),
        ("Radius", ("radius",)),
        ("Placement.Base.x", ("center", 0)),
        ("Placement.Base.y", ("center", 1)),
        ("Placement.Base.z", ("center", 2)),
    ),
    "make_face_from_wire_rface": (),
    "make_face_from_wires_rface": (),
    "make_box_rsolid": (
        ("Length", ("width",)),
        ("Width", ("height",)),
        ("Height", ("depth",)),
    ),
    "make_cylinder_rsolid": (
        ("Radius", ("radius",)),
        ("Height", ("height",)),
        ("Placement.Base.x", ("bottom_face_center", 0)),
        ("Placement.Base.y", ("bottom_face_center", 1)),
        ("Placement.Base.z", ("bottom_face_center", 2)),
    ),
    "make_cone_rsolid": (
        ("Radius1", ("bottom_radius",)),
        ("Radius2", ("top_radius",)),
        ("Height", ("height",)),
        ("Placement.Base.x", ("bottom_face_center", 0)),
        ("Placement.Base.y", ("bottom_face_center", 1)),
        ("Placement.Base.z", ("bottom_face_center", 2)),
    ),
    "make_sphere_rsolid": (
        ("Radius", ("radius",)),
        ("Placement.Base.x", ("center", 0)),
        ("Placement.Base.y", ("center", 1)),
        ("Placement.Base.z", ("center", 2)),
    ),
    "make_extrude_rsolid": (
        ("LengthFwd", ("distance",)),
        ("Dir.x", ("direction", 0)),
        ("Dir.y", ("direction", 1)),
        ("Dir.z", ("direction", 2)),
    ),
    "make_revolve_rsolid": (
        ("Angle", ("angle",)),
        ("Axis.x", ("axis", 0)),
        ("Axis.y", ("axis", 1)),
        ("Axis.z", ("axis", 2)),
        ("Base.x", ("origin", 0)),
        ("Base.y", ("origin", 1)),
        ("Base.z", ("origin", 2)),
    ),
    "make_loft_rsolid": (("Ruled", ("ruled",)),),
    "make_sweep_rsolid": (("Frenet", ("is_frenet",)),),
    "make_cut_rsolid": (),
    "make_union_rsolid": (),
    "make_intersect_rsolid": (),
    "make_fillet_rsolid": (),
    "make_chamfer_rsolid": (),
    "make_shell_rsolid": (("Value", ("thickness",)),),
    "make_mirror_rshape": (
        ("Base.x", ("plane_origin", 0)),
        ("Base.y", ("plane_origin", 1)),
        ("Base.z", ("plane_origin", 2)),
        ("Normal.x", ("plane_normal", 0)),
        ("Normal.y", ("plane_normal", 1)),
        ("Normal.z", ("plane_normal", 2)),
    ),
    "make_translate_rshape": (
        ("Placement.Base.x", ("vector", 0)),
        ("Placement.Base.y", ("vector", 1)),
        ("Placement.Base.z", ("vector", 2)),
    ),
    "make_rotate_rshape": (
        ("Placement.Base.x", ("origin", 0)),
        ("Placement.Base.y", ("origin", 1)),
        ("Placement.Base.z", ("origin", 2)),
        ("Placement.Rotation.Axis.x", ("axis", 0)),
        ("Placement.Rotation.Axis.y", ("axis", 1)),
        ("Placement.Rotation.Axis.z", ("axis", 2)),
        ("Placement.Rotation.Angle", ("angle",)),
    ),
}


_OP_EXPRESSION_LIMITATIONS: Dict[str, str] = {
    "make_spline_redge": (
        "Exact B-spline pole/weight expressions have no stable equivalent native "
        "FreeCAD Sketcher BSpline parameter host. The translator exports exact "
        "B-spline geometry, but does not map make_spline_redge param_exprs into "
        "FreeCAD ExpressionEngine."
    ),
}


def _contains_expr_refs(value: Any) -> bool:
    if isinstance(value, dict):
        if isinstance(value.get("expr_id"), str) and value["expr_id"]:
            return True
        return any(_contains_expr_refs(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_expr_refs(v) for v in value)
    return False


def _expression_limitation_payload(
    op: str, param_exprs: Any
) -> Optional[Dict[str, str]]:
    if not _contains_expr_refs(param_exprs or {}):
        return None
    reason = _OP_EXPRESSION_LIMITATIONS.get(str(op))
    if not reason:
        return None
    return {"op": str(op), "reason": str(reason)}


def _node_expression_limitation(
    node: Optional[OperationNode],
) -> Optional[Dict[str, str]]:
    if node is None:
        return None
    payload = _expression_limitation_payload(str(node.op), dict(node.param_exprs))
    if payload is None:
        return None
    return {"node_id": str(node.node_id), **payload}


def _sanitize_expr_alias(alias: str, *, prefix: str = "expr") -> str:
    token = "".join(
        ch if ch.isascii() and ch.isalnum() else "_" for ch in str(alias)
    ).strip("_")
    if not token:
        token = prefix
    if token[0].isdigit():
        token = f"{prefix}_{token}"
    return token[:64]


def _expr_short_suffix(expr_id: str) -> str:
    raw = str(expr_id).rsplit("_", 1)[-1]
    token = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in raw).strip(
        "_"
    )
    return token[:8] if token else "id"


def _const_value_alias_token(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "value"
    text = f"{number:.6g}".replace("-", "neg_").replace(".", "_")
    token = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in text).strip(
        "_"
    )
    return token or "value"


def _spreadsheet_expr_alias(expr_node: Dict[str, Any], row: int) -> str:
    expr_id = str(expr_node.get("expr_id", f"expr_{row}"))
    kind = str(expr_node.get("kind", "expr"))
    if kind == "var":
        name = str(expr_node.get("name", "")).strip()
        if name:
            return _sanitize_expr_alias(f"var_{name}", prefix="var")
    if kind == "const":
        return _sanitize_expr_alias(
            f"const_{_const_value_alias_token(expr_node.get('value'))}_{_expr_short_suffix(expr_id)}",
            prefix="const",
        )
    op = str(expr_node.get("op", "expr")).strip() or "expr"
    return _sanitize_expr_alias(
        f"expr_{op}_{_expr_short_suffix(expr_id)}", prefix="expr"
    )


def _spreadsheet_expr_aliases(nodes: Sequence[Any]) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    used: Set[str] = set()
    row = 1
    for node in nodes:
        if not isinstance(node, dict):
            continue
        expr_id = str(node.get("expr_id", f"expr_{row}"))
        alias = _spreadsheet_expr_alias(node, row)
        if alias in used:
            suffix = hashlib.sha256(expr_id.encode("utf-8")).hexdigest()[:8]
            prefix = alias[: 63 - len(suffix)]
            alias = f"{prefix}_{suffix}"
            collision = 2
            while alias in used:
                collision_suffix = f"{suffix}_{collision}"
                prefix = alias[: 63 - len(collision_suffix)]
                alias = f"{prefix}_{collision_suffix}"
                collision += 1
        aliases[expr_id] = alias
        used.add(alias)
        row += 1
    return aliases


def _coincident_constraint_pairs(
    input_nodes: Sequence[Optional[OperationNode]],
) -> List[Tuple[int, int, int, int]]:
    pairs: List[Tuple[int, int, int, int]] = []
    if len(input_nodes) < 2:
        return pairs
    for idx in range(len(input_nodes) - 1):
        left = input_nodes[idx]
        right = input_nodes[idx + 1]
        if left is None or right is None:
            continue
        if left.op == "make_circle_redge" or right.op == "make_circle_redge":
            continue
        pairs.append((idx, 2, idx + 1, 1))
    first = input_nodes[0]
    last = input_nodes[-1]
    if (
        first is not None
        and last is not None
        and first.op != "make_circle_redge"
        and last.op != "make_circle_redge"
    ):
        try:
            first_start = first.params.get("start")
            last_end = last.params.get("end")
            if isinstance(first_start, (list, tuple)) and isinstance(
                last_end, (list, tuple)
            ):
                if all(
                    abs(float(a) - float(b)) <= 1e-7
                    for a, b in zip(first_start, last_end)
                ):
                    pairs.append((len(input_nodes) - 1, 2, 0, 1))
        except Exception:
            pass
    return pairs


def _compile_time_nested_expr_ref(expr_meta: Any, *path: Any) -> Any:
    value = expr_meta
    for key in path:
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and isinstance(key, int) and 0 <= key < len(value):
            value = value[key]
        else:
            return None
    return value


__all__ = [
    "_OP_EXPRESSION_BINDINGS",
    "_OP_EXPRESSION_LIMITATIONS",
    "_coincident_constraint_pairs",
    "_compile_time_nested_expr_ref",
    "_contains_expr_refs",
    "_canonical_variable_default",
    "_expression_physical_metadata",
    "_node_expression_limitation",
    "_json_ascii",
    "_py_literal",
    "_safe_name",
    "_sanitize_expr_alias",
    "_spreadsheet_expr_alias",
    "_spreadsheet_expr_aliases",
]
