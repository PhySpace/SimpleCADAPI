"""Compile validated product graphs into Autodesk Fusion 360 scripts.

Generated scripts run inside Fusion 360's Python environment and select
detail-feature geometry by signatures instead of topology indices.
"""

from __future__ import annotations

import base64
import copy
import json
import os
import pprint
import re
import tempfile
import zlib
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ...product.placement import placement_frame_mm
from ...recording.serializer import _execute_graph
from simplecadapi._cpp import OperationGraph, OperationNode


def _json_ascii(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _py_literal(value: Any) -> str:
    return pprint.pformat(value, compact=True, sort_dicts=True, width=120)


def _deterministic_step_bytes(data: bytes) -> bytes:
    text = data.decode("latin-1")
    text = re.sub(
        r"(FILE_NAME\('[^']*',)'[^']*'",
        r"\1'1970-01-01T00:00:00'",
        text,
        count=1,
    )
    text = re.sub(
        r"(Open CASCADE STEP translator [^']* )\d+(')",
        r"\g<1>1\2",
        text,
    )
    return text.encode("latin-1")


def _safe_name(raw: str, *, prefix: str = "obj") -> str:
    token = "".join(ch if ch.isalnum() else "_" for ch in raw)
    token = token.strip("_")
    if not token:
        token = prefix
    if token[0].isdigit():
        token = f"{prefix}_{token}"
    return token


def _normalized_spline_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Convert legacy fit-point splines to the OCC-equivalent NURBS payload."""

    result = dict(params)
    if result.get("control_points") or not result.get("points"):
        return result
    try:
        from simplecadapi._cpp.occt.GeomAPI import GeomAPI_Interpolate
        from simplecadapi._cpp.occt.TColgp import TColgp_HArray1OfPnt
        from simplecadapi._cpp.occt.gp import gp_Pnt

        points = [tuple(float(value) for value in point) for point in result["points"]]
        point_array = TColgp_HArray1OfPnt(1, len(points))
        for index, point in enumerate(points, 1):
            xyz = point + (0.0,) * (3 - len(point))
            point_array.SetValue(index, gp_Pnt(*xyz[:3]))
        interpolation = GeomAPI_Interpolate(point_array, False, 1.0e-9)
        interpolation.Perform()
        if not interpolation.IsDone():
            return result
        curve = interpolation.Curve()
        result["control_points"] = [
            [curve.Pole(index).X(), curve.Pole(index).Y(), curve.Pole(index).Z()]
            for index in range(1, curve.NbPoles() + 1)
        ]
        result["degree"] = int(curve.Degree())
        result["knots"] = [
            float(curve.Knot(index)) for index in range(1, curve.NbKnots() + 1)
        ]
        result["multiplicities"] = [
            int(curve.Multiplicity(index)) for index in range(1, curve.NbKnots() + 1)
        ]
        result["fusion_knots"] = [
            knot
            for knot, multiplicity in zip(result["knots"], result["multiplicities"])
            for _ in range(multiplicity)
        ]
        result["periodic"] = bool(curve.IsPeriodic())
        if curve.IsRational():
            result["weights"] = [
                float(curve.Weight(index)) for index in range(1, curve.NbPoles() + 1)
            ]
    except Exception:
        return result
    return result


def _curve_params_with_kernel_axes(
    params: Dict[str, Any], axis_key: str
) -> Dict[str, Any]:
    """Add the canonical OCC periodic frame without mutating graph parameters."""

    from simplecadapi._cpp.occt.gp import gp_Ax2, gp_Dir, gp_Pnt

    result = dict(params)
    axis_value = result.get(axis_key, (0.0, 0.0, 1.0))
    axis = gp_Ax2(
        gp_Pnt(0.0, 0.0, 0.0),
        gp_Dir(*(float(value) for value in axis_value)),
    )
    x_axis = axis.XDirection()
    y_axis = axis.YDirection()
    result["_kernel_x_axis"] = [x_axis.X(), x_axis.Y(), x_axis.Z()]
    result["_kernel_y_axis"] = [y_axis.X(), y_axis.Y(), y_axis.Z()]
    return result


_ASSEMBLY_ACTIVE_STATE_PRIORITY = (
    "operating",
    "locked",
    "nominal",
    "default",
    "middle",
    "middle_adjustment",
)


def _assembly_state_result_node_ids(
    graph: OperationGraph, result_node_ids: Sequence[str]
) -> Dict[str, List[str]]:
    """Group sibling assembly compound leaves by their state suffix."""

    node_ids = [str(node_id) for node_id in result_node_ids]
    if len(node_ids) < 2:
        return {}
    snapshots: List[Tuple[str, str, int]] = []
    for node_id in node_ids:
        node = graph.get_node(node_id)
        if node is None or node.op != "make_compound_from_assembly_rcompound":
            return {}
        assembly_id = str(node.params.get("assembly_id") or "")
        if not assembly_id:
            return {}
        snapshots.append(
            (node_id, assembly_id, int(node.params.get("component_count") or 0))
        )
    if len({count for _, _, count in snapshots}) != 1:
        return {}
    common_prefix = os.path.commonprefix(
        [assembly_id for _, assembly_id, _ in snapshots]
    )
    separator_index = common_prefix.rfind("_")
    if separator_index <= 0:
        return {}
    state_prefix = common_prefix[: separator_index + 1]
    grouped: Dict[str, List[str]] = {}
    for node_id, assembly_id, _ in snapshots:
        if not assembly_id.startswith(state_prefix):
            return {}
        state = assembly_id[len(state_prefix) :].strip("_")
        if not state or state in grouped:
            return {}
        grouped[state] = [node_id]
    return grouped


def _preferred_result_node_ids(
    graph: OperationGraph, result_node_ids: Sequence[str]
) -> Tuple[List[str], Optional[str], Dict[str, List[str]]]:
    state_node_ids = _assembly_state_result_node_ids(graph, result_node_ids)
    for state in _ASSEMBLY_ACTIVE_STATE_PRIORITY:
        selected = state_node_ids.get(state)
        if selected is not None:
            return list(selected), state, state_node_ids
    # Assembly compounds are terminal result sets.  Graph exporters can also
    # expose the rotated component snapshots used to build the compound as
    # leaves; emitting both duplicates every component in the STEP result.
    node_by_id = {str(node.node_id): node for node in graph.nodes}
    assembly_results = [
        node_id
        for node_id in result_node_ids
        if getattr(node_by_id.get(str(node_id)), "op", None)
        == "make_compound_from_assembly_rcompound"
    ]
    if assembly_results:
        return assembly_results, None, state_node_ids
    dominant_result = _dominant_result_node_id(graph, result_node_ids)
    if dominant_result is not None:
        return [dominant_result], None, state_node_ids
    return [str(node_id) for node_id in result_node_ids], None, state_node_ids


def _dominant_result_node_id(
    graph: OperationGraph, result_node_ids: Sequence[str]
) -> Optional[str]:
    """Resolve redundant terminal leaves only when source geometry proves dominance."""

    node_by_id = {str(node.node_id): node for node in graph.nodes}
    node_ids = [str(node_id) for node_id in result_node_ids]
    nodes = [node_by_id.get(node_id) for node_id in node_ids]
    ops = [getattr(node, "op", None) for node in nodes]
    detail_ops = {"make_fillet_rsolid", "make_chamfer_rsolid", "make_shell_rsolid"}
    detail_indices = [index for index, op in enumerate(ops) if op in detail_ops]
    all_union_results = len(node_ids) > 1 and all(
        op == "make_union_rsolid" for op in ops
    )
    if len(detail_indices) != 1 and not all_union_results:
        return None

    try:
        from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Fuse
        from simplecadapi._cpp.occt.BRepGProp import BRepGProp
        from simplecadapi._cpp.occt.GProp import GProp_GProps

        replay_graph = copy.deepcopy(graph)
        for node in replay_graph.nodes:
            if node.op == "make_spline_redge":
                normalized = _normalized_spline_params(dict(node.params))
                normalized.pop("fusion_knots", None)
                node.params.clear()
                node.params.update(normalized)
        results = _execute_graph(replay_graph, node_ids, strict=True)

        def shape_volume(shape: Any) -> float:
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(shape, props)
            return max(0.0, float(props.Mass()))

        shapes = [getattr(result, "wrapped", None) for result in results]
        volumes = [
            shape_volume(shape) if shape is not None else 0.0 for shape in shapes
        ]
    except Exception:
        return None

    if len(detail_indices) == 1:
        detail_index = detail_indices[0]
        total_volume = sum(volumes)
        if total_volume > 0.0 and volumes[detail_index] / total_volume >= 0.99:
            return node_ids[detail_index]

    if all_union_results and shapes:
        try:
            fused_shape = shapes[0]
            for shape in shapes[1:]:
                fuse = BRepAlgoAPI_Fuse(fused_shape, shape)
                fuse.Build()
                if not fuse.IsDone():
                    return None
                fused_shape = fuse.Shape()
            fused_volume = shape_volume(fused_shape)
            largest_index = max(range(len(volumes)), key=volumes.__getitem__)
            tolerance = max(1.0e-12, fused_volume * 1.0e-8)
            if (
                fused_volume > 0.0
                and abs(volumes[largest_index] - fused_volume) <= tolerance
            ):
                return node_ids[largest_index]
        except Exception:
            return None
    return None


def _source_kernel_fallback_node_ids(graph: OperationGraph) -> List[str]:
    fallback_ops = {
        "make_loft_rsolid",
        "make_revolve_rsolid",
        "make_sweep_rsolid",
        "make_fillet_rsolid",
        "make_chamfer_rsolid",
        "make_shell_rsolid",
    }
    return [str(node.node_id) for node in graph.nodes if node.op in fallback_ops]


def _dependency_node_ids(
    graph: OperationGraph, result_node_ids: Sequence[str]
) -> Set[str]:
    pending = [str(node_id) for node_id in result_node_ids]
    needed: Set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in needed:
            continue
        node = graph.get_node(node_id)
        if node is None:
            raise ValueError(f"Result node {node_id!r} is not present in the graph")
        needed.add(node_id)
        pending.extend(str(input_ref.node_id) for input_ref in node.inputs)
    return needed


def _dependency_subgraph(
    graph: OperationGraph, result_node_ids: Sequence[str]
) -> OperationGraph:
    needed = _dependency_node_ids(graph, result_node_ids)
    omitted_selector_ids = {
        str(node.node_id)
        for node in graph.nodes
        if node.op in {"make_select_redge", "make_select_rface"} and not node.inputs
    }
    result = OperationGraph(graph_id=graph.graph_id)
    for node in graph.topological_order():
        if str(node.node_id) not in needed or str(node.node_id) in omitted_selector_ids:
            continue
        inputs = [
            result.get_node(str(input_ref.node_id))
            for input_ref in node.inputs
            if str(input_ref.node_id) not in omitted_selector_ids
        ]
        if any(input_node is None for input_node in inputs):
            raise ValueError(
                f"Dependency subgraph is missing an input for node {node.node_id!r}"
            )
        params = copy.deepcopy(node.params)
        for key in ("selected_edge_node_ids", "selected_face_node_ids"):
            if key in params:
                params[key] = [
                    str(value)
                    for value in params.get(key, []) or []
                    if str(value) not in omitted_selector_ids
                ]
        result.add_node(
            node.op,
            params=params,
            param_exprs=copy.deepcopy(node.param_exprs),
            inputs=[input_node for input_node in inputs if input_node is not None],
            node_id=str(node.node_id),
            output_count=node.output_count,
            semantic_delta=copy.deepcopy(node.semantic_delta),
            topo_delta=copy.deepcopy(node.topo_delta),
            context=copy.deepcopy(node.context),
            tags=set(node.tags),
            source=copy.deepcopy(node.source),
        )
    return result


def _seam_split_circle_node_ids(graph: OperationGraph) -> List[str]:
    """Find circular profiles whose downstream selectors target axial seam edges.

    Fusion does not expose the seam of a full analytic cylinder as a selectable
    BRep edge.  Splitting only circles that feed a line-edge selection preserves
    the exact profile while making the corresponding longitudinal boundary
    explicit in the native feature chain.
    """
    node_by_id = {str(node.node_id): node for node in graph.nodes}
    selected_sources: List[Tuple[OperationNode, Dict[str, Any]]] = []
    # Selection nodes are often leaf records without graph inputs.  The
    # consuming detail node still records their semantic ownership in
    # selected_edge_node_ids, so recover the source body through that edge.
    owner_source_by_selection: Dict[str, OperationNode] = {}
    for owner in graph.nodes:
        if owner.op not in {"make_fillet_rsolid", "make_chamfer_rsolid"}:
            continue
        if not owner.inputs:
            continue
        source = node_by_id.get(str(owner.inputs[0].node_id))
        if source is None:
            continue
        for selection_id in owner.params.get("selected_edge_node_ids") or []:
            owner_source_by_selection[str(selection_id)] = source
    for node in graph.nodes:
        if node.op != "make_select_redge":
            continue
        selector = node.params.get("geo_selector")
        if (
            not isinstance(selector, dict)
            or str(selector.get("geom_type", "")).upper() != "LINE"
        ):
            continue
        source = (
            node_by_id.get(str(node.inputs[0].node_id))
            if node.inputs
            else owner_source_by_selection.get(str(node.node_id))
        )
        if source is not None:
            selected_sources.append((source, selector))

    result: Set[str] = set()
    for source, selector in selected_sources:
        if source is None:
            continue
        queue = [str(source.node_id)]
        visited: Set[str] = set()
        while queue:
            node_id = queue.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            node = node_by_id.get(node_id)
            if node is None:
                continue
            if node.op == "make_circle_redge":
                params = node.params
                center = params.get("center")
                normal = params.get("normal") or (0.0, 0.0, 1.0)
                radius = params.get("radius")
                start = selector.get("start")
                end = selector.get("end")
                if not (
                    isinstance(center, (list, tuple))
                    and len(center) == 3
                    and isinstance(normal, (list, tuple))
                    and len(normal) == 3
                    and isinstance(start, (list, tuple))
                    and len(start) == 3
                    and isinstance(end, (list, tuple))
                    and len(end) == 3
                ):
                    continue
                try:
                    center_v = tuple(float(value) for value in center)
                    normal_v = tuple(float(value) for value in normal)
                    start_v = tuple(float(value) for value in start)
                    end_v = tuple(float(value) for value in end)
                    radius_v = float(radius)
                    normal_len = sum(value * value for value in normal_v) ** 0.5
                    if normal_len <= 1.0e-12 or radius_v <= 0.0:
                        continue
                    normal_v = tuple(value / normal_len for value in normal_v)

                    def radial_distance(point):
                        delta = tuple(
                            point[index] - center_v[index] for index in range(3)
                        )
                        axial = sum(
                            delta[index] * normal_v[index] for index in range(3)
                        )
                        radial = tuple(
                            delta[index] - axial * normal_v[index] for index in range(3)
                        )
                        return abs(axial), sum(value * value for value in radial) ** 0.5

                    _start_axial, start_radial = radial_distance(start_v)
                    _end_axial, end_radial = radial_distance(end_v)
                    edge_direction = tuple(
                        end_v[index] - start_v[index] for index in range(3)
                    )
                    edge_length = sum(value * value for value in edge_direction) ** 0.5
                    scale = max(1.0, abs(radius_v), *(abs(value) for value in center_v))
                    if (
                        edge_length > scale * 1.0e-8
                        and abs(start_radial - radius_v) <= scale * 1.0e-6
                        and abs(end_radial - radius_v) <= scale * 1.0e-6
                        and abs(
                            sum(
                                edge_direction[index] * normal_v[index]
                                for index in range(3)
                            )
                        )
                        / edge_length
                        >= 1.0 - 1.0e-6
                    ):
                        result.add(str(node.node_id))
                except (TypeError, ValueError):
                    pass
            queue.extend(str(input_ref.node_id) for input_ref in node.inputs)
    return sorted(result)


def _source_kernel_step_payloads(
    graph: OperationGraph, result_node_ids: Sequence[str] = ()
) -> Tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    replay_graph = (
        _dependency_subgraph(graph, result_node_ids)
        if result_node_ids
        else copy.deepcopy(graph)
    )
    node_by_id = {str(node.node_id): node for node in replay_graph.nodes}
    has_legacy_fit_spline = any(
        node.op == "make_spline_redge"
        and bool(node.params.get("points"))
        and not bool(node.params.get("control_points"))
        for node in replay_graph.nodes
    )
    result_boolean_ids = [
        str(node_id)
        for node_id in result_node_ids
        if has_legacy_fit_spline
        if getattr(node_by_id.get(str(node_id)), "op", None)
        in {"make_cut_rsolid", "make_union_rsolid", "make_intersect_rsolid"}
    ]
    detail_input_ids = [
        str(input_ref.node_id)
        for node in replay_graph.nodes
        if node.op in {"make_fillet_rsolid", "make_chamfer_rsolid"}
        for input_ref in node.inputs[:1]
    ]
    boolean_input_ids = [
        str(input_ref.node_id)
        for node in replay_graph.nodes
        if node.op in {"make_cut_rsolid", "make_union_rsolid", "make_intersect_rsolid"}
        for input_ref in node.inputs
    ]
    node_ids = list(
        dict.fromkeys(
            _source_kernel_fallback_node_ids(replay_graph)
            + result_boolean_ids
            + detail_input_ids
            + boolean_input_ids
        )
    )
    if not node_ids:
        return {}, {}
    try:
        for node in replay_graph.nodes:
            if node.op == "make_spline_redge":
                normalized = _normalized_spline_params(dict(node.params))
                normalized.pop("fusion_knots", None)
                node.params.clear()
                node.params.update(normalized)
        results = _execute_graph(replay_graph, node_ids, strict=True)
    except Exception:
        return {}, {}
    if len(results) != len(node_ids):
        return {}, {}

    payloads: Dict[str, str] = {}
    signatures: Dict[str, Dict[str, Any]] = {}
    for node_id, result in zip(node_ids, results):
        path: Optional[str] = None
        try:
            from simplecadapi._cpp.occt.Bnd import Bnd_Box
            from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib
            from simplecadapi._cpp.occt.BRepGProp import BRepGProp
            from simplecadapi._cpp.occt.GProp import GProp_GProps
            from simplecadapi._cpp.occt.IFSelect import IFSelect_RetDone
            from simplecadapi._cpp.occt.STEPControl import STEPControl_AsIs, STEPControl_Writer

            wrapped = getattr(result, "wrapped", None)
            if wrapped is None:
                continue
            handle = tempfile.NamedTemporaryFile(suffix=".step", delete=False)
            path = handle.name
            handle.close()
            writer = STEPControl_Writer()
            writer.Transfer(wrapped, STEPControl_AsIs)
            if writer.Write(path) != IFSelect_RetDone:
                continue
            with open(path, "rb") as source:
                compressed = zlib.compress(
                    _deterministic_step_bytes(source.read()), level=9
                )
                payloads[node_id] = base64.b64encode(compressed).decode("ascii")
            bounds = Bnd_Box()
            BRepBndLib.Add_s(wrapped, bounds)
            xmin, ymin, zmin, xmax, ymax, zmax = bounds.Get()
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(wrapped, props)
            signatures[node_id] = {
                "bbox": {
                    "min": [float(xmin), float(ymin), float(zmin)],
                    "max": [float(xmax), float(ymax), float(zmax)],
                },
                "volume": max(0.0, float(props.Mass())) * 0.001,
            }
        except Exception:
            continue
        finally:
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    return payloads, signatures


class Fusion360ScriptTranslator:
    """Compile a SimpleCAD model payload into a Fusion 360 Python script."""

    def __init__(
        self,
        document_name: str = "SimpleCADModel",
        result_node_ids: Optional[Sequence[str]] = None,
        selection_mode: str = "gsm",
        source_kernel_fallback: bool = False,
    ) -> None:
        if selection_mode not in {"gsm", "index", "sample"}:
            raise ValueError(
                f"Unsupported Fusion topology selection mode: {selection_mode}"
            )
        self.document_name = document_name
        self.selection_mode = selection_mode
        self.source_kernel_fallback = bool(source_kernel_fallback)
        self._explicit_result_node_ids = (
            [str(node_id) for node_id in result_node_ids]
            if result_node_ids is not None
            else None
        )
        self._source_graph: Optional[OperationGraph] = None
        self._result_node_ids: Set[str] = set()
        self._result_node_id_list: List[str] = []
        self._declared_result_node_id_list: List[str] = []
        self._result_state_node_ids: Dict[str, List[str]] = {}
        self._active_result_state: Optional[str] = None
        self._source_kernel_steps: Dict[str, str] = {}
        self._source_kernel_signatures: Dict[str, Dict[str, Any]] = {}
        self._seam_split_circle_node_ids: List[str] = []

    def translate_model_payload_to_script(
        self,
        payload: Dict[str, Any],
        *,
        graph: Optional[OperationGraph] = None,
    ) -> str:
        source_graph = graph or payload.get("graph")
        if not isinstance(source_graph, OperationGraph):
            raise ValueError(
                "Fusion 360 translation requires payload to contain a canonical low-level graph"
            )
        if source_graph.node_count == 0:
            raise ValueError(
                "Fusion 360 translation requires payload to contain a non-empty canonical low-level graph"
            )
        self._source_graph = source_graph
        self._seam_split_circle_node_ids = _seam_split_circle_node_ids(source_graph)
        leaf_ids = payload.get("leaf_ids")
        if isinstance(leaf_ids, list) and leaf_ids:
            self._declared_result_node_id_list = [str(v) for v in leaf_ids]
        else:
            self._declared_result_node_id_list = [
                leaf.node_id for leaf in source_graph.leaf_nodes()
            ]
        if self._explicit_result_node_ids is not None:
            self._result_state_node_ids = {}
            self._active_result_state = None
            self._result_node_id_list = list(self._explicit_result_node_ids)
        else:
            (
                self._result_node_id_list,
                self._active_result_state,
                self._result_state_node_ids,
            ) = _preferred_result_node_ids(
                source_graph, self._declared_result_node_id_list
            )
        missing_result_ids = [
            node_id
            for node_id in self._result_node_id_list
            if source_graph.get_node(node_id) is None
        ]
        if missing_result_ids:
            raise ValueError(
                "Fusion 360 result node IDs are not present in the graph: "
                + ", ".join(missing_result_ids)
            )
        self._result_node_ids = set(self._result_node_id_list)
        if self.source_kernel_fallback:
            (
                self._source_kernel_steps,
                self._source_kernel_signatures,
            ) = _source_kernel_step_payloads(source_graph, self._result_node_id_list)
        else:
            self._source_kernel_steps = {}
            self._source_kernel_signatures = {}

        payload_dict = self._payload_to_jsonable(payload, source_graph)
        lines: List[str] = []
        emit = lines.append
        emit("import base64")
        emit("import json")
        emit("import math")
        emit("import os")
        emit("import tempfile")
        emit("import traceback")
        emit("import zlib")
        emit("import adsk.core")
        emit("import adsk.fusion")
        emit("")
        emit(f"DOC_NAME = {_json_ascii(self.document_name)}")
        emit(f"SELECTION_MODE = {_json_ascii(self.selection_mode)}")
        emit(f"MODEL_PAYLOAD = {_py_literal(payload_dict)}")
        emit(
            f"DECLARED_RESULT_NODE_IDS = {_py_literal(self._declared_result_node_id_list)}"
        )
        emit(f"RESULT_STATE_NODE_IDS = {_py_literal(self._result_state_node_ids)}")
        emit(f"ACTIVE_RESULT_STATE = {_py_literal(self._active_result_state)}")
        emit(f"RESULT_NODE_IDS = {_py_literal(self._result_node_id_list)}")
        emit(f"SOURCE_KERNEL_STEPS = {_py_literal(self._source_kernel_steps)}")
        emit(
            f"SOURCE_KERNEL_SIGNATURES = {_py_literal(self._source_kernel_signatures)}"
        )
        emit(
            f"SEAM_SPLIT_CIRCLE_NODE_IDS = {_py_literal(self._seam_split_circle_node_ids)}"
        )
        emit("")
        emit(self._script_helpers())
        emit("")
        emit("def run(context):")
        emit("    app = adsk.core.Application.get()")
        emit("    try:")
        emit(
            "        translator = SimpleCADFusionRuntime(MODEL_PAYLOAD, DOC_NAME, RESULT_NODE_IDS, SOURCE_KERNEL_STEPS, SOURCE_KERNEL_SIGNATURES, SEAM_SPLIT_CIRCLE_NODE_IDS)"
        )
        emit("        return translator.run()")
        emit("    except Exception:")
        emit("        message = traceback.format_exc()")
        emit("        print(message)")
        emit("        raise")
        emit("")
        emit("if __name__ == '__main__':")
        emit("    run(None)")
        return "\n".join(lines).rstrip() + "\n"

    def _payload_to_jsonable(
        self, payload: Dict[str, Any], source_graph: OperationGraph
    ) -> Dict[str, Any]:
        # Fusion scripts do not need the full model payload. Keeping only the
        # executable graph surface also prevents stale topology-index hints from
        # appearing in generated Fusion scripts.
        nodes: List[Dict[str, Any]] = []
        for node in source_graph.topological_order():
            params = dict(node.params)
            if str(node.op) == "make_spline_redge":
                params = _normalized_spline_params(params)
            elif str(node.op) in {"make_circle_redge", "make_angle_arc_redge"}:
                params = _curve_params_with_kernel_axes(params, "normal")
            elif str(node.op) == "make_helix_redge":
                params = _curve_params_with_kernel_axes(params, "dir")
            nodes.append(
                {
                    "node_id": str(node.node_id),
                    "op": str(node.op),
                    "params": self._sanitize_payload_for_fusion(params),
                    "inputs": [
                        {"node_id": str(input_ref.node_id)} for input_ref in node.inputs
                    ],
                }
            )
        return {
            "schema_version": str(payload.get("schema_version", "2.0")),
            "graph": {
                "graph_id": str(getattr(source_graph, "graph_id", "graph")),
                "nodes": nodes,
            },
            "leaf_ids": [str(v) for v in payload.get("leaf_ids", [])],
        }

    def _sanitize_payload_for_fusion(self, value: Any) -> Any:
        if isinstance(value, dict):
            cleaned: Dict[str, Any] = {}
            for key, child in value.items():
                if self.selection_mode == "index":
                    cleaned[key] = self._sanitize_payload_for_fusion(child)
                    continue
                if key in {
                    "selected_edge_indices",
                    "selected_face_indices",
                    "edge_index_param",
                    "face_index_param",
                    "topo_id",
                }:
                    continue
                if key == "metadata_geo":
                    child_cleaned = self._sanitize_payload_for_fusion(child)
                    if isinstance(child_cleaned, dict):
                        child_cleaned = {
                            k: v
                            for k, v in child_cleaned.items()
                            if k not in {"edge_index", "face_index"}
                        }
                    if child_cleaned:
                        cleaned[key] = child_cleaned
                    continue
                cleaned[key] = self._sanitize_payload_for_fusion(child)
            return cleaned
        if isinstance(value, (list, tuple)):
            return [self._sanitize_payload_for_fusion(item) for item in value]
        return value

    def _script_helpers(self) -> str:
        return r'''
SCALE = 0.1  # SimpleCAD model JSON is in mm; Fusion API geometry units are cm.
TOL = 1.0e-5


# Self-contained emitted-script fragment: runs inside Fusion's Python where
# simplecadapi is NOT importable; deliberately NOT unified with
# errors.SimpleCADError. Emitted runtime code catches this as RuntimeError.
class SimpleCADUnsupportedOpError(RuntimeError):
    pass


def _flatten(values):
    for value in values:
        if isinstance(value, (list, tuple)):
            yield from _flatten(value)
        else:
            yield value


def _v3(value, default=(0.0, 0.0, 0.0)):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        value = default
    return (float(value[0]), float(value[1]), float(value[2]))


def _scaled(value):
    x, y, z = _v3(value)
    return (x * SCALE, y * SCALE, z * SCALE)


def _pt(value):
    x, y, z = _scaled(value)
    return adsk.core.Point3D.create(x, y, z)


def _vec(value):
    x, y, z = _v3(value)
    return adsk.core.Vector3D.create(x, y, z)


def _vec_scaled(value):
    x, y, z = _scaled(value)
    return adsk.core.Vector3D.create(x, y, z)


def _distance(a, b):
    ax, ay, az = _v3(a)
    bx, by, bz = _v3(b)
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)


def _dot(a, b):
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1]) + float(a[2]) * float(b[2])


def _cross(a, b):
    return (
        float(a[1]) * float(b[2]) - float(a[2]) * float(b[1]),
        float(a[2]) * float(b[0]) - float(a[0]) * float(b[2]),
        float(a[0]) * float(b[1]) - float(a[1]) * float(b[0]),
    )


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a, fallback=(0.0, 0.0, 1.0)):
    length = _norm(a)
    if length <= 1.0e-12:
        return _v3(fallback)
    return (float(a[0]) / length, float(a[1]) / length, float(a[2]) / length)


def _add(a, b):
    return (float(a[0]) + float(b[0]), float(a[1]) + float(b[1]), float(a[2]) + float(b[2]))


def _sub(a, b):
    return (float(a[0]) - float(b[0]), float(a[1]) - float(b[1]), float(a[2]) - float(b[2]))


def _mul(a, scalar):
    return (float(a[0]) * scalar, float(a[1]) * scalar, float(a[2]) * scalar)


def _bbox_tuple(box):
    return {
        'min': (box.minPoint.x / SCALE, box.minPoint.y / SCALE, box.minPoint.z / SCALE),
        'max': (box.maxPoint.x / SCALE, box.maxPoint.y / SCALE, box.maxPoint.z / SCALE),
    }


def _bbox_center(bbox):
    return tuple((float(bbox['min'][i]) + float(bbox['max'][i])) * 0.5 for i in range(3))


def _bbox_score(candidate_bbox, selector_bbox):
    if not isinstance(selector_bbox, dict):
        return 0.0
    score = 0.0
    for key in ('min', 'max'):
        if key not in selector_bbox:
            continue
        target = selector_bbox[key]
        actual = candidate_bbox[key]
        score += sum((float(actual[i]) - float(target[i])) ** 2 for i in range(3))
    return score


def _object_collection(items=None):
    collection = adsk.core.ObjectCollection.create()
    for item in items or []:
        collection.add(item)
    return collection


def _iter_collection(collection):
    for item in collection:
        yield item


def _first_entity(collection, label):
    for item in _iter_collection(collection):
        return item
    raise RuntimeError(f'Expected at least one {label}')


def _value_cm(mm_value):
    return adsk.core.ValueInput.createByReal(float(mm_value) * SCALE)


def _value_deg(degrees):
    return adsk.core.ValueInput.createByReal(math.radians(float(degrees)))


def _curve_points_on_edge(edge):
    ev = edge.evaluator
    ok, start_param, end_param = ev.getParameterExtents()
    if not ok:
        return None
    ok, start_pt = ev.getPointAtParameter(start_param)
    if not ok:
        return None
    ok, end_pt = ev.getPointAtParameter(end_param)
    if not ok:
        return None
    ok, mid_pt = ev.getPointAtParameter((start_param + end_param) * 0.5)
    if not ok:
        mid_pt = start_pt
    return (
        (start_pt.x / SCALE, start_pt.y / SCALE, start_pt.z / SCALE),
        (mid_pt.x / SCALE, mid_pt.y / SCALE, mid_pt.z / SCALE),
        (end_pt.x / SCALE, end_pt.y / SCALE, end_pt.z / SCALE),
    )


def _edge_length(edge):
    try:
        ok, length = edge.evaluator.getLengthAtParameter(
            edge.evaluator.getParameterExtents()[1],
            edge.evaluator.getParameterExtents()[2],
        )
        if ok:
            return float(length) / SCALE
    except Exception:
        pass
    pts = _curve_points_on_edge(edge)
    if not pts:
        return 0.0
    return _distance(pts[0], pts[2])


def _edge_is_geometrically_linear(edge, edge_length):
    try:
        evaluator = edge.evaluator
        ok, start_parameter, end_parameter = evaluator.getParameterExtents()
        if not ok:
            return False
        samples = []
        for index in range(9):
            parameter = start_parameter + (end_parameter - start_parameter) * index / 8.0
            ok, point = evaluator.getPointAtParameter(parameter)
            if not ok:
                return False
            samples.append((point.x / SCALE, point.y / SCALE, point.z / SCALE))
    except Exception:
        return False
    start, end = samples[0], samples[-1]
    chord = _sub(end, start)
    chord_length = _norm(chord)
    scale = max(1.0, chord_length, float(edge_length))
    if chord_length <= scale * 1.0e-10:
        return False
    if abs(float(edge_length) - chord_length) > scale * 1.0e-7:
        return False
    tolerance = scale * 1.0e-7
    return all(
        _norm(_cross(_sub(point, start), chord)) / chord_length <= tolerance
        for point in samples
    )


def _edge_signature(edge):
    bbox = _bbox_tuple(edge.boundingBox)
    pts = _curve_points_on_edge(edge)
    center = _bbox_center(bbox)
    length = _edge_length(edge)
    geom_type = str(getattr(edge.geometry, 'objectType', '')).upper()
    if _canonical_geom_type(geom_type) == 'BSPLINE' and _edge_is_geometrically_linear(edge, length):
        geom_type = 'LINE'
    return {
        'bbox': bbox,
        'center': center,
        'start': pts[0] if pts else center,
        'end': pts[2] if pts else center,
        'length': length,
        'geom_type': geom_type,
    }


def _face_signature(face):
    bbox = _bbox_tuple(face.boundingBox)
    center = _bbox_center(bbox)
    geom_type = str(getattr(face.geometry, 'objectType', '')).upper()
    return {
        'bbox': bbox,
        'center': center,
        'area': float(getattr(face, 'area', 0.0)) / (SCALE * SCALE),
        'geom_type': geom_type,
        'normal': _face_normal_tuple(face),
    }


def _face_normal_tuple(face):
    try:
        geometry = face.geometry
        normal = getattr(geometry, 'normal', None)
        if normal is not None:
            return _unit((normal.x, normal.y, normal.z))
    except Exception:
        pass
    try:
        evaluator = face.evaluator
        point = face.pointOnFace
        ok, parameter = evaluator.getParameterAtPoint(point)
        if ok:
            ok, normal = evaluator.getNormalAtParameter(parameter)
            if ok:
                return _unit((normal.x, normal.y, normal.z))
    except Exception:
        pass
    return None


def _selector_geometry(selector):
    params = selector.get('params') if isinstance(selector, dict) else None
    if isinstance(params, dict):
        selector = params
    if not isinstance(selector, dict):
        return {}
    geo_selector = selector.get('geo_selector')
    if isinstance(geo_selector, dict):
        return dict(selector, **geo_selector)
    return selector


def _tuple3_or_none(value):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    return None


def _canonical_geom_type(value):
    text = str(value or '').upper().replace('_TYPE', '')
    aliases = (
        ('B-SPLINE', 'BSPLINE'), ('BSPLINE', 'BSPLINE'),
        ('NURBS', 'BSPLINE'), ('CYLINDER', 'CYLINDER'),
        ('BEZIERCURVE', 'BEZIER'), ('BEZIER', 'BEZIER'),
        ('PLANE', 'PLANE'), ('CIRCLE', 'CIRCLE'),
        ('ELLIPTICALARC', 'ELLIPSE'), ('ELLIPSE', 'ELLIPSE'),
        ('ARC', 'CIRCLE'),
        ('LINE', 'LINE'), ('CONE', 'CONE'), ('SPHERE', 'SPHERE'),
        ('TORUS', 'TORUS'),
    )
    for token, canonical in aliases:
        if token in text:
            return canonical
    return text


def _selector_geom_type(selector):
    selector = _selector_geometry(selector)
    geom_type = _canonical_geom_type(
        selector.get('geom_type') or selector.get('surface_type')
    )
    if geom_type not in {'BSPLINE', 'BEZIER'} or _selector_kind(selector, selector) != 'edge':
        return geom_type
    start = _tuple3_or_none(selector.get('start'))
    end = _tuple3_or_none(selector.get('end'))
    expected_length = selector.get('length')
    if start is None or end is None or expected_length is None:
        return geom_type
    chord_length = _distance(start, end)
    edge_length = float(expected_length)
    scale = max(1.0, chord_length, edge_length)
    if chord_length > scale * 1.0e-10 and abs(edge_length - chord_length) <= scale * 1.0e-7:
        return 'LINE'
    return geom_type


def _geom_type_mismatch(sig, selector):
    selector = _selector_geometry(selector)
    target = _selector_geom_type(selector)
    actual = _canonical_geom_type(sig.get('geom_type'))
    if target == 'CIRCLE' and actual == 'BSPLINE':
        expected_length = selector.get('length')
        actual_length = sig.get('length')
        expected_start = _tuple3_or_none(selector.get('start'))
        expected_end = _tuple3_or_none(selector.get('end'))
        actual_start = _tuple3_or_none(sig.get('start'))
        actual_end = _tuple3_or_none(sig.get('end'))
        scale = _selector_length_scale(selector)
        if (
            expected_length is not None
            and actual_length is not None
            and all(
                value is not None
                for value in (
                    expected_start,
                    expected_end,
                    actual_start,
                    actual_end,
                )
            )
            and _bbox_selector_score(sig, selector) <= 1.0e-4
            and _relative_error(actual_length, expected_length) <= 1.0e-4
        ):
            same = _distance(actual_start, expected_start) + _distance(
                actual_end, expected_end
            )
            reverse = _distance(actual_start, expected_end) + _distance(
                actual_end, expected_start
            )
            if min(same, reverse) <= scale * 2.0e-4:
                return 0
    return int(bool(target and actual and target != actual))


def _selector_length_scale(selector):
    selector = _selector_geometry(selector)
    bbox = selector.get('bbox')
    if isinstance(bbox, dict):
        minimum = _tuple3_or_none(bbox.get('min'))
        maximum = _tuple3_or_none(bbox.get('max'))
        if minimum is not None and maximum is not None:
            return max(1.0, _distance(minimum, maximum))
    return 1.0


def _relative_error(actual, expected, floor=1.0):
    return abs(float(actual) - float(expected)) / max(float(floor), abs(float(expected)))


def _bbox_selector_score(sig, selector):
    selector = _selector_geometry(selector)
    candidate_bbox = sig.get('bbox')
    expected_bbox = selector.get('bbox')
    if not isinstance(candidate_bbox, dict) or not isinstance(expected_bbox, dict):
        return 0.0
    actual_min = _tuple3_or_none(candidate_bbox.get('min'))
    actual_max = _tuple3_or_none(candidate_bbox.get('max'))
    expected_min = _tuple3_or_none(expected_bbox.get('min'))
    expected_max = _tuple3_or_none(expected_bbox.get('max'))
    if any(value is None for value in (actual_min, actual_max, expected_min, expected_max)):
        return 1.0e6
    scale = _selector_length_scale(selector)
    return (
        _distance(actual_min, expected_min) + _distance(actual_max, expected_max)
    ) / scale


def _selector_kind(selector, sig):
    selector = _selector_geometry(selector)
    kind = str(selector.get('kind') or selector.get('target_kind') or '').lower()
    if kind:
        return kind
    if 'length' in selector or 'length' in sig:
        return 'edge'
    if 'area' in selector or 'area' in sig:
        return 'face'
    return ''


def _geom_score(sig, selector):
    selector = _selector_geometry(selector)
    score = _bbox_selector_score(sig, selector) * 10.0
    if _geom_type_mismatch(sig, selector):
        score += 20.0
    scale = _selector_length_scale(selector)
    kind = _selector_kind(selector, sig)
    expected_center = _tuple3_or_none(selector.get('center'))
    actual_center = _tuple3_or_none(sig.get('center'))
    if expected_center is not None and actual_center is not None:
        score += _distance(actual_center, expected_center) / scale * 3.0
    if kind == 'edge':
        if selector.get('length') is not None and sig.get('length') is not None:
            score += _relative_error(sig['length'], selector['length']) * 3.0
        expected_start = _tuple3_or_none(selector.get('start'))
        expected_end = _tuple3_or_none(selector.get('end'))
        candidate_start = _tuple3_or_none(sig.get('start'))
        candidate_end = _tuple3_or_none(sig.get('end'))
        if all(value is not None for value in (expected_start, expected_end, candidate_start, candidate_end)):
            same = _distance(candidate_start, expected_start) + _distance(candidate_end, expected_end)
            reverse = _distance(candidate_start, expected_end) + _distance(candidate_end, expected_start)
            score += min(same, reverse) / scale
    elif kind == 'face':
        if selector.get('area') is not None and sig.get('area') is not None:
            score += _relative_error(sig['area'], selector['area']) * 3.0
        if _selector_geom_type(selector) == 'PLANE':
            expected_normal = _tuple3_or_none(selector.get('normal'))
            candidate_normal = _tuple3_or_none(sig.get('normal'))
            if expected_normal is not None and candidate_normal is not None:
                alignment = abs(_dot(_unit(expected_normal), _unit(candidate_normal)))
                score += (1.0 - min(1.0, alignment)) * 2.0
    return score


def _point_mm(point):
    return (point.x / SCALE, point.y / SCALE, point.z / SCALE)


def _candidate_sample_point(candidate, kind):
    centroid = getattr(candidate, 'centroid', None)
    if centroid is not None:
        return _point_mm(centroid)
    if kind == 'face':
        return _bbox_center(_bbox_tuple(candidate.boundingBox))
    try:
        evaluator = candidate.evaluator
        ok, start_parameter, end_parameter = evaluator.getParameterExtents()
        if not ok or not math.isfinite(start_parameter) or not math.isfinite(end_parameter):
            return _bbox_center(_bbox_tuple(candidate.boundingBox))
        points = []
        for index in range(65):
            parameter = start_parameter + (end_parameter - start_parameter) * index / 64.0
            ok, point = evaluator.getPointAtParameter(parameter)
            if not ok:
                return _bbox_center(_bbox_tuple(candidate.boundingBox))
            points.append(_point_mm(point))
    except Exception:
        return _bbox_center(_bbox_tuple(candidate.boundingBox))
    weighted = [0.0, 0.0, 0.0]
    total_weight = 0.0
    for first, second in zip(points, points[1:]):
        weight = _distance(first, second)
        if weight <= 0.0:
            continue
        for axis in range(3):
            weighted[axis] += (first[axis] + second[axis]) * 0.5 * weight
        total_weight += weight
    if total_weight <= 0.0:
        return _bbox_center(_bbox_tuple(candidate.boundingBox))
    return tuple(value / total_weight for value in weighted)


def _best_by_geometry(candidates, selector, signature_fn, label):
    if not candidates:
        raise RuntimeError(f'No {label} candidates available for geometry selection')
    selector = _selector_geometry(selector)
    if SELECTION_MODE == 'index':
        kind = _selector_kind(selector, {}) or str(label).lower()
        metadata = selector.get('metadata_geo')
        key = 'edge_index' if kind == 'edge' else 'face_index'
        if not isinstance(metadata, dict) or key not in metadata:
            raise RuntimeError(
                f'Direct {kind} index is missing for {label} selection; '
                f'selector={selector!r}'
            )
        try:
            index = int(metadata[key])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f'Invalid direct {kind} index: {metadata[key]!r}') from exc
        if index < 0 or index >= len(candidates):
            raise RuntimeError(
                f'Direct {kind} index {index} is out of range for '
                f'{len(candidates)} {label} candidates'
            )
        return candidates[index]
    if SELECTION_MODE == 'sample':
        kind = _selector_kind(selector, {}) or str(label).lower()
        sample = _tuple3_or_none(selector.get('center'))
        if sample is None:
            raise RuntimeError(
                f'Single-point {kind} selector has no canonical sample point; '
                f'selector={selector!r}'
            )
        ranked_samples = sorted(
            (
                (_distance(_candidate_sample_point(candidate, kind), sample), index, candidate)
                for index, candidate in enumerate(candidates)
            ),
            key=lambda item: (item[0], item[1]),
        )
        best_distance, _best_index, best_candidate = ranked_samples[0]
        if not math.isfinite(best_distance):
            raise RuntimeError(f'Single-point {kind} selection has no finite candidate')
        if len(ranked_samples) > 1:
            second_distance = ranked_samples[1][0]
            scale = max(1.0, abs(best_distance), abs(second_distance), *map(abs, sample))
            if second_distance - best_distance <= scale * 1.0e-9:
                raise RuntimeError(
                    f'Ambiguous single-point {kind} selection: '
                    f'best={best_distance}, second={second_distance}, sample={sample!r}'
                )
        return best_candidate
    ranked = sorted(
        [(candidate, signature_fn(candidate)) for candidate in candidates],
        key=lambda item: _geom_score(item[1], selector),
    )

    exact_spatial_matches = [
        candidate
        for candidate, signature in ranked
        if _bbox_selector_score(signature, selector) <= 1.0e-6
        and _geom_type_mismatch(signature, selector) == 0
    ]
    if len(exact_spatial_matches) == 1:
        return exact_spatial_matches[0]

    kind = _selector_kind(selector, ranked[0][1])
    expected_center = _tuple3_or_none(selector.get('center'))
    expected_measure = selector.get('length') if kind == 'edge' else selector.get('area')
    scale = _selector_length_scale(selector)

    def intrinsic_matches(center_tolerance, measure_tolerance):
        matches = []
        if expected_center is None or expected_measure is None:
            return matches
        measure_key = 'length' if kind == 'edge' else 'area'
        for candidate, signature in ranked:
            if _geom_type_mismatch(signature, selector):
                continue
            candidate_center = _tuple3_or_none(signature.get('center'))
            candidate_measure = signature.get(measure_key)
            if candidate_center is None or candidate_measure is None:
                continue
            center_error = _distance(candidate_center, expected_center) / scale
            measure_error = _relative_error(candidate_measure, expected_measure)
            if center_error <= center_tolerance and measure_error <= measure_tolerance:
                matches.append(candidate)
        return matches

    exact_intrinsic_matches = intrinsic_matches(1.0e-5, 1.0e-4)
    if len(exact_intrinsic_matches) == 1:
        return exact_intrinsic_matches[0]
    approximate_intrinsic_matches = intrinsic_matches(1.0e-3, 1.0e-3)
    if len(approximate_intrinsic_matches) == 1:
        return approximate_intrinsic_matches[0]

    best, best_signature = ranked[0]
    best_score = _geom_score(best_signature, selector)
    second_score = (
        _geom_score(ranked[1][1], selector) if len(ranked) > 1 else float('inf')
    )
    exact_match = best_score <= 1.0e-4
    acceptable_match = best_score <= 1.5 + 1.0e-9
    clearly_better = (
        second_score == float('inf')
        or second_score - best_score >= max(0.1, best_score * 0.15)
    )
    if _geom_type_mismatch(best_signature, selector) or not (
        exact_match or (acceptable_match and clearly_better)
    ):
        nearest = [
            {
                'score': _geom_score(signature, selector),
                'type_mismatch': _geom_type_mismatch(signature, selector),
                'signature': signature,
            }
            for _candidate, signature in ranked[:3]
        ]
        raise RuntimeError(
            f'Geometry selector did not match a stable {label}; '
            f'best score={best_score}; second score={second_score}; '
            f'selector={selector!r}; nearest={nearest!r}'
        )
    return best


def _matrix_translate(vector):
    matrix = adsk.core.Matrix3D.create()
    matrix.translation = _vec_scaled(vector)
    return matrix


def _placement_params(value):
    if not isinstance(value, dict):
        return {}
    if value.get('kind') == 'placement':
        return value.get('params') or {}
    return value


def _matrix_from_placement(value):
    params = _placement_params(value)
    origin = _v3(params.get('origin') or params.get('base') or (0.0, 0.0, 0.0))
    x_axis = _unit(params.get('x_axis') or (1.0, 0.0, 0.0))
    y_axis = _unit(params.get('y_axis') or (0.0, 1.0, 0.0))
    z_axis = params.get('z_axis')
    if z_axis is None:
        z_axis = (
            x_axis[1] * y_axis[2] - x_axis[2] * y_axis[1],
            x_axis[2] * y_axis[0] - x_axis[0] * y_axis[2],
            x_axis[0] * y_axis[1] - x_axis[1] * y_axis[0],
        )
    z_axis = _unit(z_axis)
    ox, oy, oz = _scaled(origin)
    matrix = adsk.core.Matrix3D.create()
    matrix.setWithArray([
        x_axis[0], y_axis[0], z_axis[0], ox,
        x_axis[1], y_axis[1], z_axis[1], oy,
        x_axis[2], y_axis[2], z_axis[2], oz,
        0.0, 0.0, 0.0, 1.0,
    ])
    return matrix


def _placement_is_identity(value):
    params = _placement_params(value)
    origin = _v3(params.get('origin') or params.get('base') or (0.0, 0.0, 0.0))
    x_axis = _v3(params.get('x_axis') or (1.0, 0.0, 0.0))
    y_axis = _v3(params.get('y_axis') or (0.0, 1.0, 0.0))
    z_axis = _v3(params.get('z_axis') or (0.0, 0.0, 1.0))
    values = origin + _sub(x_axis, (1.0, 0.0, 0.0)) + _sub(y_axis, (0.0, 1.0, 0.0)) + _sub(z_axis, (0.0, 0.0, 1.0))
    return max(abs(float(value)) for value in values) <= 1.0e-10


def _matrix_rotate(origin, axis, angle_degrees):
    matrix = adsk.core.Matrix3D.create()
    matrix.setToRotation(math.radians(float(angle_degrees)), _vec(axis), _pt(origin))
    return matrix


def _matrix_mirror(plane_origin, plane_normal):
    normal = _unit(_v3(plane_normal))
    nx, ny, nz = normal
    px, py, pz = _scaled(plane_origin)
    d = -(nx * px + ny * py + nz * pz)
    cells = [
        1 - 2 * nx * nx, -2 * nx * ny, -2 * nx * nz, -2 * d * nx,
        -2 * ny * nx, 1 - 2 * ny * ny, -2 * ny * nz, -2 * d * ny,
        -2 * nz * nx, -2 * nz * ny, 1 - 2 * nz * nz, -2 * d * nz,
        0, 0, 0, 1,
    ]
    matrix = adsk.core.Matrix3D.create()
    matrix.setWithArray(cells)
    return matrix


def _arc_basis(normal, kernel_x_axis=None, kernel_y_axis=None):
    axis = _unit(normal)
    if kernel_x_axis is not None and kernel_y_axis is not None:
        return _unit(kernel_x_axis), _unit(kernel_y_axis)
    reference = (0.0, 0.0, 1.0)
    if abs(_dot(axis, reference)) > 0.9:
        reference = (1.0, 0.0, 0.0)
    x_axis = _unit(_cross(axis, reference), fallback=(1.0, 0.0, 0.0))
    y_axis = _unit(_cross(axis, x_axis), fallback=(0.0, 1.0, 0.0))
    return x_axis, y_axis


def _arc_midpoint(
    center,
    radius,
    start_angle,
    end_angle,
    normal=(0.0, 0.0, 1.0),
    kernel_x_axis=None,
    kernel_y_axis=None,
):
    angle = (float(start_angle) + float(end_angle)) * 0.5
    x_axis, y_axis = _arc_basis(normal, kernel_x_axis, kernel_y_axis)
    offset = _add(_mul(x_axis, float(radius) * math.cos(angle)), _mul(y_axis, float(radius) * math.sin(angle)))
    return _add(_v3(center), offset)


def _arc_endpoint(
    center,
    radius,
    angle,
    normal=(0.0, 0.0, 1.0),
    kernel_x_axis=None,
    kernel_y_axis=None,
):
    x_axis, y_axis = _arc_basis(normal, kernel_x_axis, kernel_y_axis)
    offset = _add(_mul(x_axis, float(radius) * math.cos(float(angle))), _mul(y_axis, float(radius) * math.sin(float(angle))))
    return _add(_v3(center), offset)


def _three_point_circle(start, middle, end):
    ax, ay, az = _v3(start)
    bx, by, bz = _v3(middle)
    cx, cy, cz = _v3(end)
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) <= 1.0e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    center = (ux, uy, az)
    return center, _distance(center, start)


def _placement_payload_origin(payload):
    if not isinstance(payload, dict):
        return (0.0, 0.0, 0.0)
    return _v3(payload.get('origin') or payload.get('base') or (0.0, 0.0, 0.0))


def _apply_name(entity, name):
    try:
        entity.name = str(name)
    except Exception:
        pass
    return entity


def _set_simplecad_attribute(entity, name, value):
    try:
        attributes = entity.attributes
        existing = attributes.itemByName('SimpleCAD', str(name))
        if existing is not None:
            existing.deleteMe()
        attributes.add('SimpleCAD', str(name), str(value))
    except Exception:
        pass


def _set_simplecad_chunked_attribute(entity, name, value, chunk_size=12000):
    text = str(value)
    chunks = [text[index:index + chunk_size] for index in range(0, len(text), chunk_size)]
    _set_simplecad_attribute(entity, name + 'ChunkCount', len(chunks))
    for index, chunk in enumerate(chunks):
        _set_simplecad_attribute(entity, name + 'Chunk' + str(index), chunk)


def _attach_simplecad_native_metadata(entity, node_id, op, params, inputs):
    if entity is None:
        return entity
    _set_simplecad_attribute(entity, 'NodeId', node_id)
    _set_simplecad_attribute(entity, 'Op', op)
    _set_simplecad_attribute(entity, 'Params', json.dumps(params or {}, sort_keys=True))
    _set_simplecad_attribute(entity, 'Inputs', json.dumps(inputs or []))
    return entity


class SimpleCADFusionRuntime:
    def __init__(
        self,
        payload,
        document_name,
        result_node_ids,
        source_kernel_steps=None,
        source_kernel_signatures=None,
        seam_split_circle_node_ids=None,
    ):
        self.payload = payload
        self.graph = payload.get('graph') or {}
        self.nodes = self.graph.get('nodes') or []
        self.node_by_id = {str(node.get('node_id')): node for node in self.nodes}
        self.document_name = document_name
        self.result_node_ids = [str(v) for v in (result_node_ids or [])]
        self.source_kernel_steps = dict(source_kernel_steps or {})
        self.source_kernel_signatures = dict(source_kernel_signatures or {})
        self.source_kernel_body_sets = {}
        self.seam_split_circle_node_ids = {
            str(node_id) for node_id in (seam_split_circle_node_ids or [])
        }
        self.outputs = {}
        self.native_features = {}
        self.native_bodies = {}
        self.native_body_sets = {}
        self.materialized_native_node_ids = set()
        self.materialized_component_definitions = {}
        self.precreated_component_occurrences = {}
        self.product_definition_components = {}
        self.part_body_node_ids = {
            self._input_ids(node)[0]
            for node in self.nodes
            if str(node.get('op')) == 'make_part_rpart'
            and self._input_ids(node)
        }
        self.product_values = {}
        self.selection_payloads = {}
        self.tmp = adsk.fusion.TemporaryBRepManager.get()
        self.app = adsk.core.Application.get()
        self.previous_document = self.app.activeDocument
        self.document = None
        self.design = None
        self.root = None
        self.logs = []

    def run(self):
        try:
            self._prepare_document()
            active_node_ids = self._result_dependency_ids(self.result_node_ids)
            for node in self.nodes:
                if active_node_ids and str(node.get('node_id')) not in active_node_ids:
                    continue
                self._emit_node(node)
            self._materialize_results()
        except Exception:
            self._close_failed_document()
            raise
        print('SimpleCAD Fusion translation complete', self.document_name, 'nodes', len(self.nodes))
        if self.logs:
            print('\n'.join(self.logs))
        feature_ops = {
            'make_extrude_rsolid', 'make_revolve_rsolid', 'make_loft_rsolid',
            'make_sweep_rsolid', 'make_cut_rsolid', 'make_union_rsolid',
            'make_intersect_rsolid', 'make_fillet_rsolid',
            'make_chamfer_rsolid', 'make_shell_rsolid',
            'make_translate_rshape', 'make_rotate_rshape', 'make_mirror_rshape',
        }
        executed_node_ids = [
            str(node.get('node_id')) for node in self.nodes
            if self.outputs.get(str(node.get('node_id')))
        ]
        executed_feature_node_ids = [
            str(node.get('node_id')) for node in self.nodes
            if str(node.get('op')) in feature_ops
            and self.outputs.get(str(node.get('node_id')))
        ]
        return {
            'node_count': len(self.nodes),
            'executed_node_count': len(executed_node_ids),
            'feature_count': sum(str(node.get('op')) in feature_ops for node in self.nodes),
            'executed_feature_count': len(executed_feature_node_ids),
            'executed_node_ids': executed_node_ids,
            'executed_feature_node_ids': executed_feature_node_ids,
            'logs': list(self.logs),
        }

    def _result_dependency_ids(self, result_node_ids):
        needed = set()
        pending = [str(node_id) for node_id in (result_node_ids or [])]
        while pending:
            node_id = pending.pop()
            if node_id in needed:
                continue
            node = self.node_by_id.get(node_id)
            if not isinstance(node, dict):
                continue
            needed.add(node_id)
            pending.extend(self._input_ids(node))
            params = node.get('params') or {}
            for key in ('selected_edge_node_ids', 'selected_face_node_ids'):
                pending.extend(str(value) for value in (params.get(key) or []))
        return needed

    def _prepare_document(self):
        documents = self.app.documents
        doc = documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        self.document = doc
        try:
            doc.name = self.document_name
        except Exception:
            pass
        self.design = adsk.fusion.Design.cast(self.app.activeProduct)
        if self.design is None:
            raise RuntimeError('Active Fusion product is not a Design')
        try:
            self.design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        except Exception:
            pass
        self.root = self.design.rootComponent

    def _close_failed_document(self):
        try:
            if self.document is not None:
                self.document.close(False)
        except Exception:
            pass
        try:
            if self.previous_document is not None:
                self.previous_document.activate()
        except Exception:
            pass

    def _add_base_body(self, body):
        # A shared BaseFeature sits at the start of the timeline. Re-entering
        # it for every graph node forces Fusion to replay all later features
        # repeatedly and makes large models effectively quadratic. Keep each
        # imported BRep immediately before its consuming native feature.
        base_feature = self.root.features.baseFeatures.add()
        base_feature.startEdit()
        try:
            source_body = self.root.bRepBodies.add(body, base_feature)
            if source_body is None:
                raise RuntimeError('Fusion could not add body to BaseFeature')
        finally:
            base_feature.finishEdit()
        result_bodies = list(base_feature.bodies)
        if len(result_bodies) != 1:
            raise RuntimeError(
                f'expected one BaseFeature result body, found {len(result_bodies)}'
            )
        return result_bodies[0]

    def _input_ids(self, node):
        return [str(ref.get('node_id')) for ref in (node.get('inputs') or []) if isinstance(ref, dict)]

    def _has_consumers(self, node_id):
        target_id = str(node_id)
        for candidate in self.nodes:
            for reference in candidate.get('inputs') or []:
                if isinstance(reference, dict):
                    reference_id = reference.get('node_id')
                else:
                    reference_id = reference
                if str(reference_id) == target_id:
                    return True
        return False

    def _first_output(self, node_id):
        outputs = self.outputs.get(str(node_id)) or []
        if not outputs:
            raise RuntimeError(f'Missing graph output for {node_id}')
        return outputs[0]

    def _body_copy(self, body):
        return self.tmp.copy(body)

    def _delete_entity(self, entity):
        if entity is None:
            return
        try:
            if hasattr(entity, 'isValid') and not entity.isValid:
                return
        except Exception:
            pass
        try:
            entity.deleteMe()
        except Exception:
            pass

    def _register_native_feature(self, node, feature, body):
        node_id = str(node.get('node_id'))
        op = str(node.get('op'))
        params = node.get('params') or {}
        inputs = self._input_ids(node)
        _apply_name(feature, _safe_label(op, node_id))
        _apply_name(body, f'SimpleCAD_{node_id}')
        _attach_simplecad_native_metadata(feature, node_id, op, params, inputs)
        _attach_simplecad_native_metadata(body, node_id, op, params, inputs)
        if inputs:
            source_step = self.source_kernel_steps.get(str(inputs[0]))
            if source_step:
                _set_simplecad_chunked_attribute(
                    feature, 'TopologySourceSTEP', source_step
                )
        self.native_features[node_id] = feature
        self.native_bodies[node_id] = body
        return body

    def _precreate_terminal_part_component(self, node, body):
        node_id = str(node.get('node_id'))
        if (
            node_id not in self.part_body_node_ids
            or node_id in self.precreated_component_occurrences
        ):
            return body
        moved = body.createComponent()
        if moved is None:
            raise RuntimeError(
                f'Fusion could not create terminal component for {node_id}'
            )
        if not self.design.activateRootComponent():
            raise RuntimeError(
                f'Fusion could not reactivate the root component after {node_id}'
            )
        child = moved.parentComponent
        occurrences = [
            occurrence
            for occurrence in self.root.occurrences
            if occurrence.component == child
        ]
        if len(occurrences) != 1:
            raise RuntimeError(
                f'Fusion did not expose one terminal occurrence for {node_id}; '
                f'found {len(occurrences)}'
            )
        occurrence = occurrences[0]
        try:
            moved.isVisible = False
        except Exception:
            pass
        self.precreated_component_occurrences[node_id] = occurrence
        self.logs.append(f'precreated live terminal component for {node_id}')
        return moved

    def _feature_result_body(self, feature, label, expected_body=None):
        try:
            if feature.healthState in {
                adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState,
                adsk.fusion.FeatureHealthStates.SuppressedFeatureHealthState,
            }:
                raise RuntimeError(
                    f'{label} is unhealthy: {feature.errorOrWarningMessage}'
                )
        except AttributeError:
            pass
        feature_bodies = []
        try:
            feature_bodies = [body for body in feature.bodies]
        except Exception:
            feature_bodies = []
        if not feature_bodies:
            raise RuntimeError(f'Expected at least one {label}')
        if expected_body is None or len(feature_bodies) == 1:
            return feature_bodies[0]
        try:
            expected_volume = float(expected_body.volume)
            expected_bbox = _bbox_tuple(expected_body.boundingBox)

            def score(body):
                volume_scale = max(1.0e-9, abs(expected_volume), abs(float(body.volume)))
                volume_error = abs(float(body.volume) - expected_volume) / volume_scale
                bbox = _bbox_tuple(body.boundingBox)
                bbox_error = sum(
                    abs(float(left) - float(right))
                    for left, right in zip(
                        bbox['min'] + bbox['max'],
                        expected_bbox['min'] + expected_bbox['max'],
                    )
                )
                return (volume_error, bbox_error)

            return min(feature_bodies, key=score)
        except Exception:
            return feature_bodies[0]

    def _copy_first_feature_body_and_cleanup(
        self, feature, label, cleanup=None, node=None, expected_body=None
    ):
        native_body = self._feature_result_body(feature, label, expected_body)
        if node is not None:
            self._register_native_feature(node, feature, native_body)
        body = self.tmp.copy(native_body)
        for old in cleanup or []:
            try:
                old.isVisible = False
            except Exception:
                pass
        return body

    def _native_source_body(self, input_id, fallback_body):
        native = self.native_bodies.get(str(input_id))
        if native is not None:
            try:
                if native.isValid and self._native_body_close(native, fallback_body):
                    return native, False
            except Exception:
                pass
        persisted = self._add_base_body(fallback_body)
        _apply_name(persisted, f'SimpleCAD_base_{input_id}')
        _attach_simplecad_native_metadata(
            persisted, str(input_id), 'static_input_fallback', {}, []
        )
        return persisted, True

    def _native_body_matches(self, native, expected):
        try:
            native_volume = float(native.volume)
            expected_volume = float(expected.volume)
            scale = max(1.0e-9, abs(native_volume), abs(expected_volume))
            if abs(native_volume - expected_volume) > scale * 1.0e-7:
                return False
            native_bbox = _bbox_tuple(native.boundingBox)
            expected_bbox = _bbox_tuple(expected.boundingBox)
            bbox_scale = max(
                1.0,
                *(abs(float(value)) for value in native_bbox['min'] + native_bbox['max']),
                *(abs(float(value)) for value in expected_bbox['min'] + expected_bbox['max']),
            )
            return max(
                abs(float(left) - float(right))
                for left, right in zip(
                    native_bbox['min'] + native_bbox['max'],
                    expected_bbox['min'] + expected_bbox['max'],
                )
            ) <= bbox_scale * 1.0e-7
        except Exception:
            return False

    def _native_body_close(self, native, expected):
        try:
            native_volume = float(native.volume)
            expected_volume = float(expected.volume)
            scale = max(1.0e-9, abs(native_volume), abs(expected_volume))
            if abs(native_volume - expected_volume) > scale * 1.0e-2:
                return False
            native_bbox = _bbox_tuple(native.boundingBox)
            expected_bbox = _bbox_tuple(expected.boundingBox)
            bbox_scale = max(
                1.0,
                *(abs(float(value)) for value in native_bbox['min'] + native_bbox['max']),
                *(abs(float(value)) for value in expected_bbox['min'] + expected_bbox['max']),
            )
            if max(
                abs(float(left) - float(right))
                for left, right in zip(
                    native_bbox['min'] + native_bbox['max'],
                    expected_bbox['min'] + expected_bbox['max'],
                )
            ) > bbox_scale * 1.0e-2:
                return False
            return True
        except Exception:
            return False

    def _native_body_comparison(self, native, expected):
        try:
            native_bbox = _bbox_tuple(native.boundingBox)
            expected_bbox = _bbox_tuple(expected.boundingBox)
            native_center = native.physicalProperties.centerOfMass
            expected_center = expected.physicalProperties.centerOfMass
            return {
                'native_volume': float(native.volume),
                'expected_volume': float(expected.volume),
                'native_bbox': native_bbox,
                'expected_bbox': expected_bbox,
                'native_center_cm': (
                    float(native_center.x),
                    float(native_center.y),
                    float(native_center.z),
                ),
                'expected_center_cm': (
                    float(expected_center.x),
                    float(expected_center.y),
                    float(expected_center.z),
                ),
            }
        except Exception as exc:
            return {'error': f'{type(exc).__name__}: {exc}'}

    def _native_body_set_close(self, bodies, expected):
        try:
            unique = []
            seen = set()
            for body in bodies:
                try:
                    if not body.isValid:
                        continue
                except Exception:
                    pass
                try:
                    token = str(body.entityToken)
                except Exception:
                    token = str(id(body))
                token = token or str(id(body))
                if token not in seen:
                    seen.add(token)
                    unique.append(body)
            if not unique:
                return False
            expected_volume = float(expected.volume)
            actual_volume = sum(float(body.volume) for body in unique)
            volume_scale = max(1.0e-9, abs(expected_volume), abs(actual_volume))
            if abs(actual_volume - expected_volume) > volume_scale * 1.0e-2:
                return False
            boxes = [_bbox_tuple(body.boundingBox) for body in unique]
            actual_bbox = {
                'min': tuple(min(box['min'][axis] for box in boxes) for axis in range(3)),
                'max': tuple(max(box['max'][axis] for box in boxes) for axis in range(3)),
            }
            expected_bbox = _bbox_tuple(expected.boundingBox)
            bbox_scale = max(
                1.0,
                *(abs(float(value)) for value in actual_bbox['min'] + actual_bbox['max']),
                *(abs(float(value)) for value in expected_bbox['min'] + expected_bbox['max']),
            )
            return max(
                abs(float(left) - float(right))
                for left, right in zip(
                    actual_bbox['min'] + actual_bbox['max'],
                    expected_bbox['min'] + expected_bbox['max'],
                )
            ) <= bbox_scale * 1.0e-2
        except Exception:
            return False

    def _native_body_sets_close(self, bodies, expected_bodies):
        """Compare disconnected native bodies with a disconnected expected set."""
        try:
            actual = [body for body in bodies if body is not None]
            expected = [body for body in expected_bodies if body is not None]
            if not actual or not expected:
                return False
            actual_volume = sum(float(body.volume) for body in actual)
            expected_volume = sum(float(body.volume) for body in expected)
            volume_scale = max(1.0e-9, abs(actual_volume), abs(expected_volume))
            if abs(actual_volume - expected_volume) > volume_scale * 1.0e-2:
                return False
            actual_boxes = [_bbox_tuple(body.boundingBox) for body in actual]
            expected_boxes = [_bbox_tuple(body.boundingBox) for body in expected]
            actual_bbox = {
                'min': tuple(min(box['min'][axis] for box in actual_boxes) for axis in range(3)),
                'max': tuple(max(box['max'][axis] for box in actual_boxes) for axis in range(3)),
            }
            expected_bbox = {
                'min': tuple(min(box['min'][axis] for box in expected_boxes) for axis in range(3)),
                'max': tuple(max(box['max'][axis] for box in expected_boxes) for axis in range(3)),
            }
            scale = max(
                1.0,
                *(abs(float(value)) for value in actual_bbox['min'] + actual_bbox['max']),
                *(abs(float(value)) for value in expected_bbox['min'] + expected_bbox['max']),
            )
            return max(
                max(
                    abs(actual_bbox[key][axis] - expected_bbox[key][axis])
                    for key in ('min', 'max')
                    for axis in range(3)
                ),
            ) <= scale * 1.0e-2
        except Exception:
            return False

    def _native_body_sets_bbox_close(self, bodies, expected_bodies):
        """Check disconnected body correspondence without requiring equal volume."""
        try:
            actual = [body for body in bodies if body is not None]
            expected = [body for body in expected_bodies if body is not None]
            if len(actual) != len(expected) or not actual:
                return False
            actual_boxes = [_bbox_tuple(body.boundingBox) for body in actual]
            expected_boxes = [_bbox_tuple(body.boundingBox) for body in expected]
            actual_bbox = {
                'min': tuple(min(box['min'][axis] for box in actual_boxes) for axis in range(3)),
                'max': tuple(max(box['max'][axis] for box in actual_boxes) for axis in range(3)),
            }
            expected_bbox = {
                'min': tuple(min(box['min'][axis] for box in expected_boxes) for axis in range(3)),
                'max': tuple(max(box['max'][axis] for box in expected_boxes) for axis in range(3)),
            }
            scale = max(
                1.0,
                *(abs(float(value)) for value in actual_bbox['min'] + actual_bbox['max']),
                *(abs(float(value)) for value in expected_bbox['min'] + expected_bbox['max']),
            )
            return max(
                abs(actual_bbox[key][axis] - expected_bbox[key][axis])
                for key in ('min', 'max')
                for axis in range(3)
            ) <= scale * 1.0e-2
        except Exception:
            return False

    def _native_boolean_feature(self, node, operation, expected_body):
        inputs = self._input_ids(node)
        if len(inputs) < 2:
            return None
        native = []
        temporary_inputs = []
        pending_static_inputs = []
        primary_body_set_count = 0
        for input_id in inputs:
            body_set = self.native_body_sets.get(str(input_id))
            if body_set:
                if not native:
                    primary_body_set_count = len(body_set)
                native.extend(body_set)
                continue
            body = self.native_bodies.get(str(input_id))
            exact_input = self._source_kernel_step_body(input_id)
            if body is not None and exact_input is not None:
                if self._native_body_close(body, exact_input):
                    self._delete_entity(exact_input)
                else:
                    body = None
                    pending_static_inputs.append(
                        (len(native), str(input_id), exact_input, 'exact_static_input')
                    )
            elif body is None and exact_input is not None:
                pending_static_inputs.append(
                    (len(native), str(input_id), exact_input, 'exact_static_input')
                )
                body = None
            if body is None:
                if not any(index == len(native) for index, *_rest in pending_static_inputs):
                    pending_static_inputs.append(
                        (
                            len(native),
                            str(input_id),
                            self._body_copy(self._first_output(input_id)),
                            'static_input_fallback',
                        )
                    )
            native.append(body)
        if pending_static_inputs:
            base_feature = self.root.features.baseFeatures.add()
            base_feature.startEdit()
            try:
                for index, input_id, temporary_body, role in pending_static_inputs:
                    persisted = self.root.bRepBodies.add(temporary_body, base_feature)
                    persisted_name = (
                        f'SimpleCAD_boolean_{role}_{input_id}_{node.get("node_id")}'
                    )
                    _apply_name(
                        persisted,
                        persisted_name,
                    )
                    _attach_simplecad_native_metadata(
                        persisted, input_id, role, {}, []
                    )
            finally:
                base_feature.finishEdit()
            result_bodies = list(base_feature.bodies)
            if len(result_bodies) != len(pending_static_inputs):
                raise RuntimeError(
                    f'expected {len(pending_static_inputs)} persisted Boolean inputs, '
                    f'found {len(result_bodies)}'
                )
            for pending, result_body in zip(pending_static_inputs, result_bodies):
                index, input_id, _temporary_body, role = pending
                persisted_name = (
                    f'SimpleCAD_boolean_{role}_{input_id}_{node.get("node_id")}'
                )
                _apply_name(result_body, persisted_name)
                _attach_simplecad_native_metadata(
                    result_body, input_id, role, {}, []
                )
                native[index] = result_body
                temporary_inputs.append(result_body)
        unique_native = []
        seen_tokens = set()
        for body in native:
            try:
                if not body.isValid:
                    continue
            except Exception:
                pass
            try:
                token = str(body.entityToken)
            except Exception:
                token = str(id(body))
            token = token or str(id(body))
            if token not in seen_tokens:
                seen_tokens.add(token)
                unique_native.append(body)
        native = unique_native
        if (
            operation == adsk.fusion.BooleanTypes.DifferenceBooleanType
            and primary_body_set_count > 1
        ):
            return self._native_difference_body_set(
                node,
                native[:primary_body_set_count],
                native[primary_body_set_count:],
                expected_body,
            )
        if (
            operation == adsk.fusion.BooleanTypes.UnionBooleanType
            and self._native_body_set_close(native, expected_body)
        ):
            node_id = str(node.get('node_id'))
            self.native_body_sets[node_id] = list(native)
            self.logs.append(
                f'native disjoint union body set used for {node_id}: '
                f'body_count={len(native)}'
            )
            return native[0]
        try:
            feature_operation = {
                adsk.fusion.BooleanTypes.DifferenceBooleanType:
                    adsk.fusion.FeatureOperations.CutFeatureOperation,
                adsk.fusion.BooleanTypes.UnionBooleanType:
                    adsk.fusion.FeatureOperations.JoinFeatureOperation,
                adsk.fusion.BooleanTypes.IntersectionBooleanType:
                    adsk.fusion.FeatureOperations.IntersectFeatureOperation,
            }.get(operation)
            if feature_operation is None:
                raise RuntimeError(f'unsupported native boolean operation: {operation}')
            tools = _object_collection(native[1:])
            combine_input = self.root.features.combineFeatures.createInput(
                native[0], tools
            )
            combine_input.operation = feature_operation
            if hasattr(combine_input, 'isKeepToolBodies'):
                combine_input.isKeepToolBodies = True
            feature = self.root.features.combineFeatures.add(combine_input)
            bodies = list(feature.bodies)
            if not bodies:
                return None
            result_body = self._feature_result_body(
                feature, 'native boolean result body', expected_body
            )
            if not self._native_body_close(result_body, expected_body):
                self.logs.append(
                    f'native boolean geometry mismatch for {node.get("node_id")}; '
                    'using exact static result; '
                    f'comparison={self._native_body_comparison(result_body, expected_body)!r}; '
                    f'input_count={len(native)}; '
                    f'input_volumes={[float(body.volume) for body in native]!r}'
                )
                self._delete_entity(feature)
                return None
            self._register_native_feature(node, feature, result_body)
            return result_body
        except Exception as exc:
            self.logs.append(
                f'native boolean feature unavailable for {node.get("node_id")}: {exc}'
            )
            return None

    def _native_difference_body_set(self, node, targets, tools, expected_body):
        if not targets or not tools:
            return None
        features = []
        results = []
        try:
            for target_index, target in enumerate(targets):
                current = target
                for tool_index, tool in enumerate(tools):
                    combine_input = self.root.features.combineFeatures.createInput(
                        current, _object_collection([tool])
                    )
                    combine_input.operation = (
                        adsk.fusion.FeatureOperations.CutFeatureOperation
                    )
                    if hasattr(combine_input, 'isKeepToolBodies'):
                        combine_input.isKeepToolBodies = True
                    try:
                        feature = self.root.features.combineFeatures.add(combine_input)
                    except Exception as exc:
                        self.logs.append(
                            f'native body-set cut skipped target={target_index} '
                            f'tool={tool_index} for {node.get("node_id")}: {exc}'
                        )
                        continue
                    current = self._feature_result_body(
                        feature, 'native body-set cut result body'
                    )
                    features.append(feature)
                results.append(current)
            if not self._native_body_set_close(results, expected_body):
                self.logs.append(
                    f'native body-set cut geometry mismatch for {node.get("node_id")}; '
                    f'result_count={len(results)}; '
                    f'result_volumes={[float(body.volume) for body in results]!r}'
                )
                for feature in reversed(features):
                    self._delete_entity(feature)
                return None
            node_id = str(node.get('node_id'))
            op = str(node.get('op'))
            params = node.get('params') or {}
            input_ids = self._input_ids(node)
            for index, body in enumerate(results):
                _apply_name(body, f'SimpleCAD_{node_id}_{index}')
                _attach_simplecad_native_metadata(
                    body, node_id, op, params, input_ids
                )
            for index, feature in enumerate(features):
                _apply_name(feature, f'{_safe_label(op, node_id)}_{index}')
                _attach_simplecad_native_metadata(
                    feature, node_id, op, params, input_ids
                )
            self.native_body_sets[node_id] = list(results)
            self.native_bodies[node_id] = results[0]
            if features:
                self.native_features[node_id] = features[-1]
            self.logs.append(
                f'native body-set cut used for {node_id}: body_count={len(results)}'
            )
            return results[0]
        except Exception as exc:
            for feature in reversed(features):
                self._delete_entity(feature)
            self.logs.append(
                f'native body-set cut unavailable for {node.get("node_id")}: {exc}'
            )
            return None

    def _native_move_feature(self, node, matrix, expected_body=None):
        inputs = self._input_ids(node)
        if not inputs:
            return None
        input_id = inputs[0]
        source_bodies = list(self.native_body_sets.get(input_id) or [])
        if not source_bodies:
            body = self.native_bodies.get(input_id)
            if body is not None:
                source_bodies = [body]
        if not source_bodies:
            return None
        try:
            move_input = self.root.features.moveFeatures.createInput2(
                _object_collection(source_bodies)
            )
            move_input.defineAsFreeMove(matrix)
            feature = self.root.features.moveFeatures.add(move_input)
            bodies = list(feature.bodies)
            if not bodies:
                return None
            if len(source_bodies) > 1:
                if expected_body is not None and not self._native_body_set_close(
                    bodies, expected_body
                ):
                    self.logs.append(
                        f'native body-set move geometry mismatch for '
                        f'{node.get("node_id")}; body_count={len(bodies)}'
                    )
                    self._delete_entity(feature)
                    return None
                node_id = str(node.get('node_id'))
                op = str(node.get('op'))
                params = node.get('params') or {}
                input_ids = self._input_ids(node)
                _apply_name(feature, _safe_label(op, node_id))
                _attach_simplecad_native_metadata(
                    feature, node_id, op, params, input_ids
                )
                for index, result_body in enumerate(bodies):
                    _apply_name(result_body, f'SimpleCAD_{node_id}_{index}')
                    _attach_simplecad_native_metadata(
                        result_body, node_id, op, params, input_ids
                    )
                self.native_features[node_id] = feature
                self.native_bodies[node_id] = bodies[0]
                self.native_body_sets[node_id] = list(bodies)
                self.logs.append(
                    f'native body-set move used for {node_id}: '
                    f'body_count={len(bodies)}'
                )
                return bodies[0]
            result_body = self._precreate_terminal_part_component(node, bodies[0])
            self._register_native_feature(node, feature, result_body)
            return result_body
        except Exception as exc:
            self.logs.append(
                f'native move feature unavailable for {node.get("node_id")}: {exc}'
            )
            return None

    def _planar_profile_body(self, profile, label):
        if not isinstance(profile, adsk.fusion.BRepBody):
            raise RuntimeError(f'{label} profile is not a BRep body')
        if profile.faces.count > 0:
            return profile
        wire_body = profile
        if wire_body.wires.count <= 0 and wire_body.edges.count > 0:
            curves = [edge.geometry for edge in wire_body.edges]
            wire_body, _edges = self.tmp.createWireFromCurves(curves, False)
        if wire_body is None or wire_body.wires.count <= 0:
            raise RuntimeError(f'{label} profile has no usable planar wire')
        face_body = self.tmp.createFaceFromPlanarWires([wire_body])
        if face_body is None or face_body.faces.count <= 0:
            raise RuntimeError(f'{label} profile wire could not be converted to a planar face')
        return face_body

    def _source_kernel_step_body(self, node_id):
        encoded_step = self.source_kernel_steps.get(str(node_id))
        if not encoded_step:
            return None
        expected_signature = self.source_kernel_signatures.get(str(node_id)) or {}
        before_tokens = {
            str(getattr(body, 'entityToken', ''))
            for body in self.root.bRepBodies
        }
        file_descriptor, step_path = tempfile.mkstemp(suffix='.step')
        os.close(file_descriptor)
        imported_entities = []
        try:
            with open(step_path, 'wb') as output:
                compressed = base64.b64decode(encoded_step.encode('ascii'))
                output.write(zlib.decompress(compressed))
            import_manager = self.app.importManager
            options = import_manager.createSTEPImportOptions(step_path)
            imported = import_manager.importToTarget2(options, self.root)
            imported_entities = list(_iter_collection(imported)) if imported is not None else []
            adsk.doEvents()
            candidate_groups = []
            all_occurrence_local = []
            all_occurrence_transformed = []
            all_occurrence_proxy = []
            direct_bodies = [
                entity
                for entity in imported_entities
                if isinstance(entity, adsk.fusion.BRepBody)
            ]
            if direct_bodies:
                candidate_groups.append(('direct_import', direct_bodies))
            for entity in imported_entities:
                if isinstance(entity, adsk.fusion.Occurrence):
                    local_bodies = []
                    transformed_bodies = []
                    for local_body in entity.component.bRepBodies:
                        local_bodies.append(self._body_copy(local_body))
                        transformed_body = self._body_copy(local_body)
                        self.tmp.transform(transformed_body, entity.transform2)
                        transformed_bodies.append(transformed_body)
                    if local_bodies:
                        candidate_groups.append(('occurrence_local', local_bodies))
                        all_occurrence_local.extend(local_bodies)
                    if transformed_bodies:
                        candidate_groups.append(
                            ('occurrence_transformed', transformed_bodies)
                        )
                        all_occurrence_transformed.extend(transformed_bodies)
                    proxy_bodies = []
                    try:
                        proxy_bodies = [
                            self._body_copy(body) for body in entity.bRepBodies
                        ]
                    except Exception:
                        proxy_bodies = []
                    if proxy_bodies:
                        candidate_groups.append(('occurrence_proxy', proxy_bodies))
                        all_occurrence_proxy.extend(proxy_bodies)
            if len(all_occurrence_local) > 1:
                candidate_groups.append(('all_occurrence_local', all_occurrence_local))
            if len(all_occurrence_transformed) > 1:
                candidate_groups.append(
                    ('all_occurrence_transformed', all_occurrence_transformed)
                )
            if len(all_occurrence_proxy) > 1:
                candidate_groups.append(('all_occurrence_proxy', all_occurrence_proxy))
            root_bodies = [
                body for body in self.root.bRepBodies
                if str(getattr(body, 'entityToken', '')) not in before_tokens
            ]
            if root_bodies:
                candidate_groups.append(('root_new_body', root_bodies))
            if not candidate_groups:
                raise RuntimeError(f'Source-kernel STEP import produced no body for {node_id}')

            candidates = []
            for group_label, group_bodies in candidate_groups:
                for index, body in enumerate(group_bodies):
                    candidates.append((f'{group_label}[{index}]', body))
                if len(group_bodies) > 1:
                    combined = self._body_copy(group_bodies[0])
                    combined_ok = True
                    for body in group_bodies[1:]:
                        if not self.tmp.booleanOperation(
                            combined,
                            self._body_copy(body),
                            adsk.fusion.BooleanTypes.UnionBooleanType,
                        ):
                            combined_ok = False
                            break
                    if combined_ok:
                        candidates.append((group_label + '_union', combined))

            def candidate_score(candidate):
                if not expected_signature:
                    return 0.0
                try:
                    expected_bbox = expected_signature.get('bbox') or {}
                    actual_bbox = _bbox_tuple(candidate.boundingBox)
                    coordinates = (
                        list(expected_bbox.get('min') or ())
                        + list(expected_bbox.get('max') or ())
                        + list(actual_bbox['min'])
                        + list(actual_bbox['max'])
                    )
                    bbox_scale = max(
                        1.0, *(abs(float(value)) for value in coordinates)
                    )
                    bbox_error = max(
                        abs(float(left) - float(right))
                        for left, right in zip(
                            list(expected_bbox.get('min') or ())
                            + list(expected_bbox.get('max') or ()),
                            list(actual_bbox['min']) + list(actual_bbox['max']),
                        )
                    ) / bbox_scale
                    expected_volume = float(expected_signature.get('volume') or 0.0)
                    actual_volume = float(candidate.volume)
                    volume_scale = max(
                        1.0e-9, abs(expected_volume), abs(actual_volume)
                    )
                    volume_error = abs(actual_volume - expected_volume) / volume_scale
                    return volume_error * 10.0 + bbox_error
                except Exception:
                    return float('inf')

            def candidate_group_score(group):
                if len(group) == 1:
                    return candidate_score(group[0])
                try:
                    expected_bbox = expected_signature.get('bbox') or {}
                    boxes = [_bbox_tuple(body.boundingBox) for body in group]
                    actual_bbox = {
                        'min': tuple(min(box['min'][axis] for box in boxes) for axis in range(3)),
                        'max': tuple(max(box['max'][axis] for box in boxes) for axis in range(3)),
                    }
                    coordinates = (
                        list(expected_bbox.get('min') or ())
                        + list(expected_bbox.get('max') or ())
                        + list(actual_bbox['min'])
                        + list(actual_bbox['max'])
                    )
                    bbox_scale = max(1.0, *(abs(float(value)) for value in coordinates))
                    bbox_error = max(
                        abs(float(left) - float(right))
                        for left, right in zip(
                            list(expected_bbox.get('min') or ())
                            + list(expected_bbox.get('max') or ()),
                            list(actual_bbox['min']) + list(actual_bbox['max']),
                        )
                    ) / bbox_scale
                    expected_volume = float(expected_signature.get('volume') or 0.0)
                    actual_volume = sum(float(body.volume) for body in group)
                    volume_scale = max(1.0e-9, abs(expected_volume), abs(actual_volume))
                    volume_error = abs(actual_volume - expected_volume) / volume_scale
                    return volume_error * 10.0 + bbox_error
                except Exception:
                    return float('inf')

            ranked = sorted(
                (candidate_score(body), label, body) for label, body in candidates
            )
            group_ranked = sorted(
                (candidate_group_score(group), label, group)
                for label, group in candidate_groups
                if len(group) > 1
            )
            if group_ranked and (
                not ranked or group_ranked[0][0] < ranked[0][0]
            ):
                group_score, group_label, group_bodies = group_ranked[0]
                self.source_kernel_body_sets[str(node_id)] = [
                    self._body_copy(body) for body in group_bodies
                ]
                self.logs.append(
                    f'source-kernel STEP body set for {node_id}: '
                    f'label={group_label}; score={group_score}; '
                    f'body_count={len(group_bodies)}'
                )
            best_score, best_label, best_body = ranked[0]
            result = self._body_copy(best_body)
            if len(ranked) > 1 or best_score > 1.0e-7:
                self.logs.append(
                    f'source-kernel STEP candidate for {node_id}: '
                    f'label={best_label}; score={best_score}; '
                    f'alternatives={[(score, label) for score, label, _body in ranked[:4]]!r}'
                )
            for entity in imported_entities:
                self._delete_entity(entity)
            for _label, candidate in candidates:
                self._delete_entity(candidate)
            return result
        finally:
            try:
                os.unlink(step_path)
            except OSError:
                pass

    def _set_output(self, node, values):
        node_id = str(node.get('node_id'))
        if not isinstance(values, list):
            values = [values]
        self.outputs[node_id] = values
        return values

    def _native_output_values(self, node_id, fallback):
        body_set = list(self.native_body_sets.get(str(node_id)) or [])
        if body_set:
            return body_set
        body = self.native_bodies.get(str(node_id))
        return [body] if body is not None else [fallback]

    def _split_circle_curve(self, params):
        center = _v3(params.get('center'))
        normal = _unit(params.get('normal') or (0.0, 0.0, 1.0))
        radius = float(params.get('radius', 0.0))
        if radius <= 0.0:
            raise RuntimeError('circle radius must be positive')
        reference = (1.0, 0.0, 0.0)
        if abs(_dot(normal, reference)) > 0.9:
            reference = (0.0, 1.0, 0.0)
        first = _unit(_cross(reference, normal), fallback=(0.0, 1.0, 0.0))
        second = _unit(_cross(normal, first), fallback=(0.0, 0.0, 1.0))
        points = []
        for axis in (first, second, _mul(first, -1.0), _mul(second, -1.0)):
            points.append(_add(center, _mul(axis, radius)))
        curves = []
        for index in range(4):
            start = points[index]
            end = points[(index + 1) % 4]
            start_axis = _unit(_sub(start, center))
            end_axis = _unit(_sub(end, center))
            control = _add(
                center,
                _mul(_add(start_axis, end_axis), radius),
            )
            curve = adsk.core.NurbsCurve3D.createRational(
                [_pt(start), _pt(control), _pt(end)],
                2,
                [0.0, 0.0, 0.0, 1.0, 1.0, 1.0],
                [1.0, 2.0 ** -0.5, 1.0],
                False,
            )
            if curve is None:
                raise RuntimeError('failed to create rational circular arc')
            curves.append(curve)
        return curves

    def _emit_node(self, node):
        op = str(node.get('op'))
        params = node.get('params') or {}
        node_id = str(node.get('node_id'))
        inputs = self._input_ids(node)
        name = _safe_label(op, node_id)
        if op == 'make_line_redge':
            curve = adsk.core.Line3D.create(_pt(params.get('start')), _pt(params.get('end')))
            return self._set_output(node, curve)
        if op == 'make_circle_redge':
            center = _pt(params.get('center'))
            normal = _vec(params.get('normal') or (0.0, 0.0, 1.0))
            curve = adsk.core.Circle3D.createByCenter(center, normal, float(params.get('radius', 0.0)) * SCALE)
            return self._set_output(node, curve)
        if op == 'make_angle_arc_redge':
            center = params.get('center') or (0.0, 0.0, 0.0)
            radius = float(params.get('radius', 0.0))
            normal = params.get('normal') or (0, 0, 1)
            start_angle = float(params.get('start_angle', 0.0))
            end_angle = float(params.get('end_angle', 0.0))
            x_axis = params.get('_kernel_x_axis')
            y_axis = params.get('_kernel_y_axis')
            if abs(abs(end_angle - start_angle) - 2.0 * math.pi) <= 1.0e-9:
                curve = adsk.core.Circle3D.createByCenter(
                    _pt(center), _vec(normal), radius * SCALE
                )
            else:
                start = _arc_endpoint(
                    center, radius, start_angle, normal, x_axis, y_axis
                )
                middle = _arc_midpoint(
                    center, radius, start_angle, end_angle, normal, x_axis, y_axis
                )
                end = _arc_endpoint(
                    center, radius, end_angle, normal, x_axis, y_axis
                )
                curve = adsk.core.Arc3D.createByThreePoints(
                    _pt(start), _pt(middle), _pt(end)
                )
            if curve is None:
                raise RuntimeError('Fusion could not create angle arc geometry')
            return self._set_output(node, curve)
        if op == 'make_box_rsolid':
            width = float(params.get('width', 0.0)) * SCALE
            height = float(params.get('height', 0.0)) * SCALE
            depth = float(params.get('depth', 0.0)) * SCALE
            bottom = _v3(params.get('bottom_face_center') or (0.0, 0.0, 0.0))
            center = _pt(
                (
                    bottom[0],
                    bottom[1],
                    bottom[2] + float(params.get('depth', 0.0)) * 0.5,
                )
            )
            bounds = adsk.core.OrientedBoundingBox3D.create(
                center,
                adsk.core.Vector3D.create(1.0, 0.0, 0.0),
                adsk.core.Vector3D.create(0.0, 1.0, 0.0),
                width,
                height,
                depth,
            )
            body = self.tmp.createBox(bounds)
            if body is None:
                raise RuntimeError(f'Fusion box creation failed for {node_id}')
            return self._set_output(node, body)
        if op in {'make_cylinder_rsolid', 'make_cone_rsolid'}:
            bottom = _v3(params.get('bottom_face_center') or (0.0, 0.0, 0.0))
            axis = _unit(params.get('axis') or (0.0, 0.0, 1.0))
            height = float(params.get('height', 0.0))
            top = _add(bottom, _scale(axis, height))
            bottom_radius = float(
                params.get('bottom_radius', params.get('radius', 0.0))
            ) * SCALE
            top_radius = float(
                params.get('top_radius', params.get('radius', 0.0))
            ) * SCALE
            body = self.tmp.createCylinderOrCone(
                _pt(bottom), bottom_radius, _pt(top), top_radius
            )
            if body is None:
                raise RuntimeError(f'Fusion cylinder/cone creation failed for {node_id}')
            return self._set_output(node, body)
        if op == 'make_sphere_rsolid':
            body = self.tmp.createSphere(
                _pt(params.get('center') or (0.0, 0.0, 0.0)),
                float(params.get('radius', 0.0)) * SCALE,
            )
            if body is None:
                raise RuntimeError(f'Fusion sphere creation failed for {node_id}')
            return self._set_output(node, body)
        if op == 'apply_tag_rselection':
            value = self._first_output(inputs[0])
            _set_simplecad_attribute(
                value,
                'AppliedTag',
                str(params.get('tag') or params.get('normalized_tag') or ''),
            )
            return self._set_output(node, value)

        if op == 'make_three_point_arc_redge':
            curve = adsk.core.Arc3D.createByThreePoints(_pt(params.get('start')), _pt(params.get('middle')), _pt(params.get('end')))
            return self._set_output(node, curve)
        if op == 'make_spline_redge':
            points = params.get('control_points') or params.get('poles') or params.get('points') or []
            if len(points) < 2:
                raise RuntimeError('make_spline_redge requires at least two control points')
            degree = int(params.get('degree') or min(3, len(points) - 1))
            knots = params.get('fusion_knots') or params.get('knots')
            multiplicities = params.get('multiplicities')
            if (
                not params.get('fusion_knots')
                and isinstance(knots, list)
                and isinstance(multiplicities, list)
                and len(knots) == len(multiplicities)
            ):
                knots = [
                    float(knot)
                    for knot, multiplicity in zip(knots, multiplicities)
                    for _ in range(int(multiplicity))
                ]
            if not isinstance(knots, list) or len(knots) < degree + len(points) + 1:
                internal_count = max(0, len(points) - degree - 1)
                internal = [(i + 1) / (internal_count + 1) for i in range(internal_count)]
                knots = [0.0] * (degree + 1) + internal + [1.0] * (degree + 1)
            control_points = [_pt(p) for p in points]
            weights = params.get('weights')
            if isinstance(weights, list) and len(weights) == len(points):
                curve = adsk.core.NurbsCurve3D.createRational(control_points, degree, [float(k) for k in knots], [float(w) for w in weights], bool(params.get('periodic', False)))
            else:
                curve = adsk.core.NurbsCurve3D.createNonRational(control_points, degree, [float(k) for k in knots], bool(params.get('periodic', False)))
            return self._set_output(node, curve)
        if op == 'make_helix_redge':
            axis = _unit(params.get('dir') or params.get('axis') or (0.0, 0.0, 1.0))
            center = _v3(params.get('center') or (0.0, 0.0, 0.0))
            radius = float(params.get('radius', 1.0))
            height = float(params.get('height', 1.0))
            pitch = float(params.get('pitch', height))
            radial = params.get('_kernel_x_axis')
            if radial is None:
                radial, _unused = _arc_basis(axis)
            start = _add(center, _mul(_unit(radial), radius))
            turns = height / pitch if abs(pitch) > 1e-12 else 1.0
            wire = self.tmp.createHelixWire(_pt(center), _vec(axis), _pt(start), pitch * SCALE, turns, 0.0)
            return self._set_output(node, wire)
        if op == 'make_wire_from_edges_rwire':
            curves = []
            for input_id in inputs:
                item = self._first_output(input_id)
                if hasattr(item, 'edges'):
                    for edge in item.edges:
                        curves.append(edge.geometry)
                elif (
                    str(input_id) in self.seam_split_circle_node_ids
                    and str((self.node_by_id.get(str(input_id)) or {}).get('op'))
                    == 'make_circle_redge'
                ):
                    curves.extend(
                        self._split_circle_curve(
                            (self.node_by_id.get(str(input_id)) or {}).get('params') or {}
                        )
                    )
                else:
                    curves.append(item)
            wire, _edges = self.tmp.createWireFromCurves(curves, False)
            if wire is None:
                raise RuntimeError('createWireFromCurves failed')
            return self._set_output(node, wire)
        if op == 'make_face_from_wire_rface':
            wire = self._first_output(inputs[0])
            face = self.tmp.createFaceFromPlanarWires([wire])
            if face is None:
                raise RuntimeError('createFaceFromPlanarWires failed')
            return self._set_output(node, face)
        if op == 'make_face_from_wires_rface':
            wires = [self._first_output(input_id) for input_id in inputs]
            face = self.tmp.createFaceFromPlanarWires(wires)
            if face is None:
                raise RuntimeError('createFaceFromPlanarWires failed for multi-loop face')
            return self._set_output(node, face)
        if op in {'make_wire_from_sketch_rwire', 'make_face_from_sketch_rface'}:
            raise SimpleCADUnsupportedOpError(f'{op} is not yet supported by the Fusion translator')
        if op == 'make_extrude_rsolid':
            profile = self._first_output(inputs[0])
            direction = _unit(params.get('direction') or (0.0, 0.0, 1.0))
            distance = float(params.get('distance', 0.0))
            vector = _mul(direction, distance)
            body = self._extrude(profile, vector, node)
            return self._set_output(node, body)
        if op == 'make_revolve_rsolid':
            profile = self._first_output(inputs[0])
            body = self._revolve_by_sampling(profile, params, node_id)
            return self._set_output(node, body)
        if op == 'make_loft_rsolid':
            sections = [self._first_output(input_id) for input_id in inputs]
            body = self._loft_by_features(sections, bool(params.get('ruled', False)), node_id)
            return self._set_output(node, body)
        if op == 'make_sweep_rsolid':
            profile = self._first_output(inputs[0])
            path = self._first_output(inputs[1])
            body = self._sweep_by_features(profile, path, params, node_id)
            return self._set_output(node, body)
        if op == 'make_cut_rsolid':
            source_body = self._source_kernel_step_body(node_id)
            if source_body is not None:
                self.logs.append(f'cut source-kernel STEP used for {node_id}')
                native_result = self._native_boolean_feature(
                    node, adsk.fusion.BooleanTypes.DifferenceBooleanType, source_body
                )
                return self._set_output(
                    node,
                    self._native_output_values(node_id, source_body)
                    if native_result is not None
                    else source_body,
                )
            body = self._body_copy(self._first_output(inputs[0]))
            for input_id in inputs[1:]:
                tool = self._first_output(input_id)
                ok = self.tmp.booleanOperation(body, self._body_copy(tool), adsk.fusion.BooleanTypes.DifferenceBooleanType)
                if not ok:
                    raise RuntimeError(f'Fusion cut boolean failed for {node_id} tool {input_id}')
            native_result = self._native_boolean_feature(
                node, adsk.fusion.BooleanTypes.DifferenceBooleanType, body
            )
            if native_result is None:
                self.logs.append(
                    f'Fusion cut feature unavailable for {node_id}; '
                    'preserving exact static TemporaryBRep result'
                )
            return self._set_output(node, body)
        if op == 'make_union_rsolid':
            source_body = self._source_kernel_step_body(node_id)
            if source_body is not None:
                self.logs.append(f'union source-kernel STEP used for {node_id}')
                native_result = self._native_boolean_feature(
                    node, adsk.fusion.BooleanTypes.UnionBooleanType, source_body
                )
                return self._set_output(
                    node,
                    self._native_output_values(node_id, source_body)
                    if native_result is not None
                    else source_body,
                )
            body = self._body_copy(self._first_output(inputs[0]))
            for input_id in inputs[1:]:
                tool = self._first_output(input_id)
                ok = self.tmp.booleanOperation(body, self._body_copy(tool), adsk.fusion.BooleanTypes.UnionBooleanType)
                if not ok:
                    raise RuntimeError(f'Fusion union boolean failed for {node_id} tool {input_id}')
            native_result = self._native_boolean_feature(
                node, adsk.fusion.BooleanTypes.UnionBooleanType, body
            )
            if native_result is None:
                self.logs.append(
                    f'Fusion union feature unavailable for {node_id}; '
                    'preserving exact static TemporaryBRep result'
                )
            return self._set_output(node, body)
        if op == 'make_intersect_rsolid':
            source_body = self._source_kernel_step_body(node_id)
            if source_body is not None:
                self.logs.append(f'intersection source-kernel STEP used for {node_id}')
                native_result = self._native_boolean_feature(
                    node, adsk.fusion.BooleanTypes.IntersectionBooleanType, source_body
                )
                return self._set_output(
                    node,
                    self._native_output_values(node_id, source_body)
                    if native_result is not None
                    else source_body,
                )
            body = self._body_copy(self._first_output(inputs[0]))
            for input_id in inputs[1:]:
                tool = self._first_output(input_id)
                ok = self.tmp.booleanOperation(body, self._body_copy(tool), adsk.fusion.BooleanTypes.IntersectionBooleanType)
                if not ok:
                    raise RuntimeError(f'Fusion intersection boolean failed for {node_id} tool {input_id}')
            native_result = self._native_boolean_feature(
                node, adsk.fusion.BooleanTypes.IntersectionBooleanType, body
            )
            if native_result is None:
                self.logs.append(
                    f'Fusion intersection feature unavailable for {node_id}; '
                    'preserving exact static TemporaryBRep result'
                )
            return self._set_output(node, body)
        if op == 'make_select_redge':
            self.selection_payloads[node_id] = {'kind': 'edge', 'params': params, 'input': inputs[0] if inputs else None}
            return self._set_output(node, self.selection_payloads[node_id])
        if op == 'make_select_rface':
            self.selection_payloads[node_id] = {'kind': 'face', 'params': params, 'input': inputs[0] if inputs else None}
            return self._set_output(node, self.selection_payloads[node_id])
        if op == 'make_fillet_rsolid':
            body = self._feature_detail_edges(node, params, inputs, 'fillet')
            return self._set_output(node, body)
        if op == 'make_chamfer_rsolid':
            body = self._feature_detail_edges(node, params, inputs, 'chamfer')
            return self._set_output(node, body)
        if op == 'make_shell_rsolid':
            body = self._feature_shell(node, params, inputs)
            return self._set_output(node, body)
        if op == 'make_translate_rshape':
            body = self._body_copy(self._first_output(inputs[0]))
            matrix = _matrix_translate(params.get('vector') or (0.0, 0.0, 0.0))
            self.tmp.transform(body, matrix)
            self._native_move_feature(node, matrix, body)
            return self._set_output(node, body)
        if op == 'make_rotate_rshape':
            body = self._body_copy(self._first_output(inputs[0]))
            matrix = _matrix_rotate(
                params.get('origin') or (0.0, 0.0, 0.0),
                params.get('axis') or (0.0, 0.0, 1.0),
                params.get('angle', 0.0),
            )
            self.tmp.transform(body, matrix)
            self._native_move_feature(node, matrix, body)
            return self._set_output(node, body)
        if op == 'make_mirror_rshape':
            body = self._body_copy(self._first_output(inputs[0]))
            self.tmp.transform(body, _matrix_mirror(params.get('plane_origin') or (0, 0, 0), params.get('plane_normal') or (0, 0, 1)))
            return self._set_output(node, body)
        if op == 'make_material_rmaterial':
            return self._set_output(node, {'kind': 'material', 'params': params})
        if op in {'make_placement_rplacement', 'make_identity_placement_rplacement'}:
            return self._set_output(node, {'kind': 'placement', 'params': params})
        if op == 'make_part_rpart':
            value = {'kind': 'part', 'params': params, 'body_node': inputs[0], 'body': self._first_output(inputs[0])}
            self.product_values[node_id] = value
            return self._set_output(node, value)
        if op == 'make_assign_material_rpart':
            value = dict(self._first_output(inputs[0]))
            value['material'] = self._first_output(inputs[1])
            self.product_values[node_id] = value
            return self._set_output(node, value)
        if op == 'make_assembly_rassembly':
            value = {'kind': 'assembly', 'params': params, 'components': []}
            self.product_values[node_id] = value
            return self._set_output(node, value)
        if op == 'make_add_component_rassembly':
            assembly = dict(self._first_output(inputs[0]))
            components = list(assembly.get('components') or [])
            placement = self._first_output(inputs[2]) if len(inputs) > 2 else {
                'kind': 'placement',
                'params': dict(params.get('placement') or {}),
            }
            components.append({
                'item': self._first_output(inputs[1]),
                'placement': placement,
                'component_id': str(params.get('component_id') or ''),
                'node_id': node_id,
                'params': params,
            })
            assembly['components'] = components
            self.product_values[node_id] = assembly
            return self._set_output(node, assembly)
        if op == 'make_place_component_rassembly':
            assembly = dict(self._first_output(inputs[0]))
            placement = self._first_output(inputs[1]) if len(inputs) > 1 else {
                'kind': 'placement',
                'params': dict(params.get('placement') or {}),
            }
            component_id = str(params.get('component_id') or '')
            components = []
            for component in assembly.get('components') or []:
                component = dict(component)
                if str(component.get('component_id') or '') == component_id:
                    component['placement'] = placement
                components.append(component)
            assembly['components'] = components
            self.product_values[node_id] = assembly
            return self._set_output(node, assembly)
        if op == 'make_solve_assembly_constraints_rassembly':
            assembly = dict(self._first_output(inputs[0]))
            placements = {
                str(component_id): {
                    'kind': 'placement',
                    'params': placement_frame_mm(frame),
                }
                for component_id, frame in (
                    (str(key), value)
                    for key, value in dict(params.get('component_placements') or {}).items()
                )
            }
            components = []
            for component in assembly.get('components') or []:
                component = dict(component)
                component_id = str(component.get('component_id') or '')
                if component_id in placements:
                    component['placement'] = placements[component_id]
                components.append(component)
            assembly['components'] = components
            self.product_values[node_id] = assembly
            return self._set_output(node, assembly)
        if op == 'evaluate_assembly_definition':
            assembly = dict(self._first_output(inputs[0]))
            placements = {
                str(record.get('instance_id') or ''): {
                    'kind': 'placement',
                    'params': placement_frame_mm(record.get('placement') or {}),
                }
                for record in (params.get('component_placements') or [])
                if isinstance(record, dict)
            }
            components = []
            for component in assembly.get('components') or []:
                component = dict(component)
                component_id = str(component.get('component_id') or '')
                if component_id in placements:
                    component['placement'] = placements[component_id]
                components.append(component)
            assembly['components'] = components
            assembly['evaluation'] = params
            self.product_values[node_id] = assembly
            return self._set_output(node, assembly)
        if op == 'make_compound_from_assembly_rcompound':
            assembly = self._first_output(inputs[0])
            if not isinstance(assembly, dict) or not assembly.get('components'):
                raise RuntimeError('assembly compound has no bodies')
            state = dict(assembly)
            state['kind'] = 'state'
            state['state_name'] = str(params.get('assembly_id') or node_id)
            state['result_node_id'] = node_id
            return self._set_output(node, state)
        if op.startswith('make_') and op.endswith('_rconnector'):
            return self._set_output(node, {'kind': 'connector', 'params': params})
        if op in {
            'make_add_connector_rpart', 'make_set_public_connector_rassembly',
            'make_connector_ref_rconnectorref', 'make_scalar_limit_rscalarlimit',

            'make_ground_component_rassembly', 'make_unground_component_rassembly',
            'make_fixed_constraint_rassembly', 'make_revolute_constraint_rassembly',
            'make_prismatic_constraint_rassembly',
        }:
            value = self._first_output(inputs[0]) if inputs else {'kind': op, 'params': params}
            return self._set_output(node, value)
        raise SimpleCADUnsupportedOpError(f'Unsupported SimpleCAD op for Fusion 360 translation: {op}')

    def _extrude(self, profile, vector, node):
        distance = _norm(vector)
        if distance <= 1.0e-12:
            raise RuntimeError('Extrude distance is zero')
        face_body = self._planar_profile_body(profile, 'Extrude')
        persistent_face_body = self._add_base_body(face_body)
        face = _first_entity(persistent_face_body.faces, 'profile face')
        features = self.root.features.extrudeFeatures
        face_normal = _face_normal_tuple(face)
        feature = None
        if face_normal is not None:
            target = _unit(vector)
            if abs(_dot(face_normal, target)) < 1.0 - 1.0e-9:
                start = face.pointOnFace
                end = adsk.core.Point3D.create(
                    start.x + float(vector[0]) * SCALE,
                    start.y + float(vector[1]) * SCALE,
                    start.z + float(vector[2]) * SCALE,
                )
                line = adsk.core.Line3D.create(start, end)
                path_shape, _path_edges = self.tmp.createWireFromCurves(
                    [line], False
                )
                path_body = self._add_base_body(path_shape)
                path_edge = _first_entity(path_body.edges, 'oblique extrusion path')
                path = adsk.fusion.Path.create(
                    path_edge,
                    adsk.fusion.ChainedCurveOptions.openEdgesChainedCurves,
                )
                sweep_input = self.root.features.sweepFeatures.createInput(
                    face,
                    path,
                    adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
                )
                sweep_input.orientation = (
                    adsk.fusion.SweepOrientationTypes.ParallelOrientationType
                )
                feature = self.root.features.sweepFeatures.add(sweep_input)
                return self._copy_first_feature_body_and_cleanup(
                    feature,
                    'oblique extrusion result body',
                    [persistent_face_body, path_body],
                    node,
                )
            direction = adsk.fusion.ExtentDirections.PositiveExtentDirection
            if _dot(face_normal, target) < 0.0:
                direction = adsk.fusion.ExtentDirections.NegativeExtentDirection
            try:
                input_obj = features.createInput(face, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
                extent = adsk.fusion.DistanceExtentDefinition.create(_value_cm(distance))
                input_obj.setOneSideExtent(extent, direction)
                feature = features.add(input_obj)
            except Exception as exc:
                self.logs.append(f'extrude directional API fallback: {exc}')
        if feature is None:
            feature = features.addSimple(face, _value_cm(distance), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        return self._copy_first_feature_body_and_cleanup(
            feature, 'extrude result body', [persistent_face_body], node
        )

    def _revolve_by_sampling(self, profile, params, node_id):
        source_body = self._source_kernel_step_body(node_id)
        # Fusion temporary BRep has no direct revolve primitive. Use Fusion's feature
        # API so the kernel owns a live, editable result.  The source-kernel body
        # remains an accuracy oracle and is used only when native construction
        # fails or produces materially different geometry.
        persistent_face_body = None
        axis_persistent = None
        feature = None
        try:
            face_body = self._planar_profile_body(profile, 'Revolve')
            persistent_face_body = self._add_base_body(face_body)
            face = _first_entity(persistent_face_body.faces, 'revolve profile face')
            origin = params.get('origin') or (0.0, 0.0, 0.0)
            axis = _unit(params.get('axis') or (0.0, 0.0, 1.0))
            line = adsk.core.Line3D.create(_pt(origin), _pt(_add(origin, axis)))
            axis_body, _edges = self.tmp.createWireFromCurves([line], False)
            axis_persistent = self._add_base_body(axis_body)
            axis_edge = _first_entity(axis_persistent.edges, 'revolve axis edge')
            input_obj = self.root.features.revolveFeatures.createInput(
                face,
                axis_edge,
                adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
            )
            input_obj.setAngleExtent(
                False, _value_deg(params.get('angle', 360.0))
            )
            feature = self.root.features.revolveFeatures.add(input_obj)
            native_body = self._feature_result_body(
                feature, 'revolve result body', source_body
            )
            if source_body is not None and not self._native_body_close(
                native_body, source_body
            ):
                self.logs.append(
                    f'native revolve geometry mismatch for {node_id}; '
                    'using source-kernel STEP fallback'
                )
                self._delete_entity(feature)
                feature = None
                return source_body
            node = self.node_by_id.get(str(node_id)) or {}
            self._register_native_feature(node, feature, native_body)
            result = self.tmp.copy(native_body)
            if source_body is not None:
                self._delete_entity(source_body)
            self.logs.append(f'native revolve feature used for {node_id}')
            return result
        except Exception as exc:
            if feature is not None:
                self._delete_entity(feature)
            if source_body is None:
                raise
            self.logs.append(
                f'native revolve feature unavailable for {node_id}: {exc}; '
                'using source-kernel STEP fallback'
            )
            return source_body
        finally:
            for old in (persistent_face_body, axis_persistent):
                if old is None:
                    continue
                try:
                    old.isVisible = False
                except Exception:
                    pass

    def _loft_by_features(self, sections, ruled, node_id):
        source_body = self._source_kernel_step_body(node_id)
        if source_body is not None:
            self.logs.append(f'loft source-kernel STEP used for {node_id}')
            return source_body
        input_obj = self.root.features.loftFeatures.createInput(adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        persisted = []
        for section in sections:
            face_section = self._planar_profile_body(section, 'Loft section')
            body = self._add_base_body(face_section)
            persisted.append(body)
            input_obj.loftSections.add(_first_entity(body.faces, 'loft section face'))
        try:
            input_obj.isSolid = True
            input_obj.isClosed = False
            input_obj.isTangentEdgesMerged = False
            if hasattr(input_obj, 'isRuled'):
                input_obj.isRuled = bool(ruled)
        except Exception:
            pass
        feature = self.root.features.loftFeatures.add(input_obj)
        return self._copy_first_feature_body_and_cleanup(
            feature,
            'loft result body',
            persisted,
            self.node_by_id.get(str(node_id)),
        )

    def _sweep_by_features(self, profile, path, params, node_id):
        node = self.node_by_id.get(str(node_id)) or {}
        input_ids = self._input_ids(node)
        path_node = self.node_by_id.get(input_ids[1]) if len(input_ids) == 2 else None
        path_input_ids = self._input_ids(path_node) if path_node else []
        is_direct_helix = (
            path_node is not None
            and str(path_node.get('op')) == 'make_wire_from_edges_rwire'
            and len(path_input_ids) == 1
            and str((self.node_by_id.get(path_input_ids[0]) or {}).get('op')) == 'make_helix_redge'
        )
        # The canonical kernel has already resolved the profile/path frame and
        # GSM semantics.  Fusion's native sweep can silently choose a
        # different section orientation while still returning a valid body,
        # so prefer the exact source result whenever it is available.
        source_body = self._source_kernel_step_body(node_id)
        if source_body is not None:
            label = 'direct helix' if is_direct_helix else 'sweep'
            self.logs.append(f'{label} source-kernel STEP used for {node_id}')
            return source_body

        face_body = self._planar_profile_body(profile, 'Sweep')
        profile_body = self._add_base_body(face_body)
        path_body = self._add_base_body(path)
        sweep_features = self.root.features.sweepFeatures
        path_seed = _first_entity(path_body.edges, 'sweep path edge')
        path_obj = adsk.fusion.Path.create(path_seed, adsk.fusion.ChainedCurveOptions.openEdgesChainedCurves)
        if path_obj is None or path_obj.count <= 0:
            raise RuntimeError('Fusion sweep path could not be constructed from the persistent path edge')
        profile_face = _first_entity(profile_body.faces, 'sweep profile face')

        def create_input(orientation):
            result = sweep_features.createInput(
                profile_face,
                path_obj,
                adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
            )
            result.orientation = orientation
            return result

        is_frenet = bool(params.get('is_frenet', False))
        preferred_orientation = (
            adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType
            if is_frenet
            else adsk.fusion.SweepOrientationTypes.ParallelOrientationType
        )
        alternate_orientation = (
            adsk.fusion.SweepOrientationTypes.ParallelOrientationType
            if is_frenet
            else adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType
        )
        try:
            feature = sweep_features.add(create_input(preferred_orientation))
        except Exception as exc:
            self.logs.append(f'sweep alternate orientation fallback for {node_id}: {exc}')
            try:
                feature = sweep_features.add(create_input(alternate_orientation))
            except Exception as alternate_exc:
                source_body = self._source_kernel_step_body(node_id)
                if source_body is None:
                    raise alternate_exc
                self.logs.append(f'sweep source-kernel STEP fallback used for {node_id}: {alternate_exc}')
                self._delete_entity(profile_body)
                self._delete_entity(path_body)
                return source_body
        return self._copy_first_feature_body_and_cleanup(
            feature,
            'sweep result body',
            [profile_body, path_body],
            self.node_by_id.get(str(node_id)),
        )

    def _feature_detail_edges(self, node, params, inputs, kind):
        node_id = str(node.get('node_id'))
        canonical_input = self._first_output(inputs[0])
        exact_input = self._source_kernel_step_body(inputs[0])
        exact_input_set = list(self.source_kernel_body_sets.get(str(inputs[0])) or [])
        if exact_input is not None:
            canonical_input = self._body_copy(exact_input)
            self._delete_entity(exact_input)
        # Detail features are built on an exact persisted copy of the
        # canonical temporary result.  This keeps their editable radius and
        # edge references without letting an approximate native Boolean chain
        # contaminate the geometry used by later graph nodes.
        topology_source_shapes = [
            body for body in exact_input_set
            if body is not None and bool(getattr(body, 'isValid', False))
        ]
        if not topology_source_shapes or not any(
            self._native_body_close(body, canonical_input)
            for body in topology_source_shapes
        ):
            topology_source_shapes.insert(0, canonical_input)
        topology_sources = []
        for index, source_shape in enumerate(topology_source_shapes):
            topology_source = self._add_base_body(self._body_copy(source_shape))
            suffix = '' if len(topology_source_shapes) == 1 else f'_{index}'
            _apply_name(
                topology_source,
                f'SimpleCAD_topology_source_{node_id}{suffix}',
            )
            _set_simplecad_attribute(topology_source, 'TopologySourceFor', node_id)
            try:
                topology_source.isVisible = False
            except Exception:
                pass
            topology_sources.append(topology_source)
        native_sources = list(self.native_body_sets.get(str(inputs[0])) or [])
        if not native_sources:
            native_body = self.native_bodies.get(str(inputs[0]))
            if native_body is not None:
                native_sources = [native_body]
        native_chain_matches = False
        if exact_input_set:
            native_chain_matches = self._native_body_sets_close(
                native_sources, exact_input_set
            )
        elif native_sources:
            native_chain_matches = (
                (
                    len(native_sources) > 1
                    and self._native_body_set_close(native_sources, canonical_input)
                )
                or (
                    len(native_sources) == 1
                    and self._native_body_close(native_sources[0], canonical_input)
                )
            )
        if native_sources and native_chain_matches:
            source_bodies = native_sources
            source_is_fallback = False
            self.logs.append(
                f'{kind} native input chain preserved for {node_id}: '
                f'body_count={len(source_bodies)}'
            )
        else:
            source_bodies = [
                self._add_base_body(self._body_copy(body))
                for body in (exact_input_set or [canonical_input])
            ]
            source_is_fallback = True
            _apply_name(source_bodies[0], f'SimpleCAD_base_{inputs[0]}_{node_id}')
            _attach_simplecad_native_metadata(
                source_bodies[0], str(inputs[0]), 'static_input_fallback', {}, []
            )
        selectors = []
        for selector_id in params.get('selected_edge_node_ids') or []:
            payload = self.selection_payloads.get(str(selector_id))
            if payload:
                selectors.append(payload.get('params') or {})
        if not selectors:
            for item in params.get('selected_edges') or []:
                if isinstance(item, dict):
                    selectors.append(item.get('selector_hint') or item)
        if not selectors and SELECTION_MODE == 'index':
            selectors.extend(
                {
                    'kind': 'edge',
                    'metadata_geo': {'edge_index': int(index)},
                }
                for index in params.get('selected_edge_indices') or []
            )
        for topology_source in topology_sources:
            _set_simplecad_attribute(
                topology_source,
                'TopologySelectors',
                json.dumps(selectors, sort_keys=True),
            )
            _set_simplecad_attribute(
                topology_source,
                'TopologySelectionNodeIds',
                json.dumps(params.get('selected_edge_node_ids') or []),
            )

        def attach_topology_metadata(feature):
            _set_simplecad_chunked_attribute(
                feature,
                'TopologySelectors',
                json.dumps(selectors, sort_keys=True),
            )
            _set_simplecad_chunked_attribute(
                feature,
                'TopologySelectionNodeIds',
                json.dumps(params.get('selected_edge_node_ids') or []),
            )
            _set_simplecad_attribute(
                feature, 'TopologyEdgeSetLayout', 'flat_explicit_v1'
            )
            return feature

        def create_feature(feature_sources):
            selected_groups = []
            for selector in selectors:
                candidate_edges = [
                    edge
                    for feature_source in feature_sources
                    for edge in feature_source.edges
                ]
                selector_geometry = _selector_geometry(selector)
                try:
                    edge = _best_by_geometry(
                        candidate_edges, selector, _edge_signature, 'edge'
                    )
                    selected_groups.append([edge])
                    continue
                except RuntimeError as direct_match_error:
                    direct_error_text = str(direct_match_error)
                    if _selector_geom_type(selector_geometry) not in {'LINE', 'CIRCLE'}:
                        raise
                if _selector_geom_type(selector_geometry) == 'LINE':
                    expected_start = _tuple3_or_none(selector_geometry.get('start'))
                    expected_end = _tuple3_or_none(selector_geometry.get('end'))
                    expected_length = float(selector_geometry.get('length') or 0.0)
                    expected_bbox = selector_geometry.get('bbox') or {}
                    expected_min = _tuple3_or_none(expected_bbox.get('min'))
                    expected_max = _tuple3_or_none(expected_bbox.get('max'))
                    if (
                        expected_start is None
                        or expected_end is None
                        or expected_min is None
                        or expected_max is None
                        or expected_length <= 0.0
                    ):
                        raise
                    direction = _sub(expected_end, expected_start)
                    direction_length = _norm(direction)
                    if direction_length <= 1.0e-12:
                        raise
                    direction = _mul(direction, 1.0 / direction_length)
                    matches = []
                    group_debug = []
                    for feature_source in feature_sources:
                        source_matches = []
                        for candidate in feature_source.edges:
                            signature = _edge_signature(candidate)
                            # Fusion may expose an exact straight seam as a
                            # degree-one/linear BSPLINE after a native feature
                            # or STEP-backed Boolean. Treat it as a line only
                            # after the sampled points pass the collinearity
                            # test below; curved BSPLINEs remain excluded.
                            if _canonical_geom_type(signature.get('geom_type')) not in {
                                'LINE', 'BSPLINE'
                            }:
                                continue
                            points = list(_curve_points_on_edge(candidate) or ())
                            if len(points) < 2:
                                continue
                            scale = max(1.0, expected_length)
                            if any(
                                _norm(_cross(_sub(point, expected_start), direction))
                                / direction_length
                                > scale * 1.0e-5
                                for point in points
                            ):
                                continue
                            bbox = signature.get('bbox') or {}
                            bbox_min = _tuple3_or_none(bbox.get('min'))
                            bbox_max = _tuple3_or_none(bbox.get('max'))
                            if bbox_min is None or bbox_max is None:
                                continue
                            if any(
                                bbox_min[index] < expected_min[index] - scale * 1.0e-5
                                or bbox_max[index] > expected_max[index] + scale * 1.0e-5
                                for index in range(3)
                            ):
                                continue
                            source_matches.append((candidate, signature))
                        group_debug.append(
                            [
                                (
                                    signature.get('start'),
                                    signature.get('end'),
                                    signature.get('length'),
                                )
                                for _candidate, signature in source_matches
                            ]
                        )
                        matches.extend(source_matches)
                    if len(matches) < 2:
                        raise RuntimeError(
                            f'{kind} linear seam selector did not identify a unique split-edge set; '
                            f'direct_error={direct_error_text}; candidates={group_debug!r}'
                        )
                    intervals = []
                    for _candidate, signature in matches:
                        points = [signature.get('start'), signature.get('end')]
                        projections = [
                            _dot(_sub(point, expected_start), direction)
                            for point in points
                        ]
                        intervals.append((min(projections), max(projections)))
                    intervals.sort()
                    if (
                        intervals[0][0] > scale * 1.0e-5
                        or intervals[-1][1] < expected_length - scale * 1.0e-5
                        or any(
                            right < left - scale * 1.0e-5
                            for (_left, right), (left, _right) in zip(
                                intervals, intervals[1:]
                            )
                        )
                    ):
                        raise RuntimeError(
                            f'{kind} linear seam selector did not identify a unique split-edge set; '
                            f'direct_error={direct_error_text}; candidates={group_debug!r}'
                        )
                    total_length = sum(
                        float(signature.get('length') or 0.0)
                        for _candidate, signature in matches
                    )
                    if abs(total_length - expected_length) > scale * 1.0e-5:
                        raise RuntimeError(
                            f'{kind} linear seam selector did not identify a unique split-edge set; '
                            f'direct_error={direct_error_text}; candidates={group_debug!r}'
                        )
                    selected_groups.append(
                        [candidate for candidate, _signature in matches]
                    )
                    continue
                expected_center = _tuple3_or_none(selector_geometry.get('center'))
                expected_start = _tuple3_or_none(selector_geometry.get('start'))
                expected_end = _tuple3_or_none(selector_geometry.get('end'))
                expected_length = float(selector_geometry.get('length') or 0.0)
                expected_bbox = selector_geometry.get('bbox') or {}
                expected_min = _tuple3_or_none(expected_bbox.get('min'))
                expected_max = _tuple3_or_none(expected_bbox.get('max'))
                expected_radius = expected_length / (2.0 * math.pi)
                if (
                    expected_center is None
                    or expected_start is None
                    or expected_end is None
                    or expected_min is None
                    or expected_max is None
                    or expected_radius <= 0.0
                ):
                    raise
                path_scale = max(1.0, expected_length)
                endpoint_tolerance = path_scale * 1.0e-4
                if _distance(expected_start, expected_end) > endpoint_tolerance:
                    paths = []
                    for feature_source in feature_sources:
                        path_candidates = []
                        for candidate in feature_source.edges:
                            signature = _edge_signature(candidate)
                            if _canonical_geom_type(signature.get('geom_type')) not in {
                                'BSPLINE', 'CIRCLE'
                            }:
                                continue
                            start = _tuple3_or_none(signature.get('start'))
                            end = _tuple3_or_none(signature.get('end'))
                            bbox = signature.get('bbox') or {}
                            bbox_min = _tuple3_or_none(bbox.get('min'))
                            bbox_max = _tuple3_or_none(bbox.get('max'))
                            if any(
                                value is None
                                for value in (start, end, bbox_min, bbox_max)
                            ):
                                continue
                            if any(
                                bbox_min[index] < expected_min[index] - endpoint_tolerance
                                or bbox_max[index] > expected_max[index] + endpoint_tolerance
                                for index in range(3)
                            ):
                                continue
                            path_candidates.append((candidate, signature, start, end))

                        def walk(point, used, path, total_length):
                            if len(path) > 1 and _distance(point, expected_end) <= endpoint_tolerance:
                                if abs(total_length - expected_length) <= path_scale * 1.0e-4:
                                    boxes = [item[1]['bbox'] for item in path]
                                    union_min = tuple(
                                        min(box['min'][axis] for box in boxes)
                                        for axis in range(3)
                                    )
                                    union_max = tuple(
                                        max(box['max'][axis] for box in boxes)
                                        for axis in range(3)
                                    )
                                    if max(
                                        max(
                                            abs(union_min[axis] - expected_min[axis]),
                                            abs(union_max[axis] - expected_max[axis]),
                                        )
                                        for axis in range(3)
                                    ) <= endpoint_tolerance:
                                        paths.append([item[0] for item in path])
                                return
                            if len(path) >= 8 or total_length >= expected_length + endpoint_tolerance:
                                return
                            for index, item in enumerate(path_candidates):
                                if index in used:
                                    continue
                                _candidate, signature, start, end = item
                                next_point = None
                                if _distance(point, start) <= endpoint_tolerance:
                                    next_point = end
                                elif _distance(point, end) <= endpoint_tolerance:
                                    next_point = start
                                if next_point is None:
                                    continue
                                walk(
                                    next_point,
                                    used | {index},
                                    path + [item],
                                    total_length + float(signature.get('length') or 0.0),
                                )

                        walk(expected_start, set(), [], 0.0)
                    unique_paths = {
                        tuple(sorted(str(edge.entityToken) for edge in path)): path
                        for path in paths
                    }
                    if len(unique_paths) == 1:
                        selected_groups.append(next(iter(unique_paths.values())))
                        continue
                    if unique_paths:
                        raise RuntimeError(
                            f'{kind} curved fragment selector is ambiguous; '
                            f'path_count={len(unique_paths)}; direct_error={direct_error_text}'
                        )
                groups = []
                for feature_source in feature_sources:
                    matches = []
                    for candidate in feature_source.edges:
                        signature = _edge_signature(candidate)
                        if _canonical_geom_type(signature.get('geom_type')) not in {
                            'BSPLINE', 'CIRCLE'
                        }:
                            continue
                        points = list(_curve_points_on_edge(candidate) or ())
                        if any(point is None for point in points):
                            continue
                        if any(
                            abs(_distance(point, expected_center) - expected_radius)
                            > max(1.0, expected_radius) * 1.0e-4
                            for point in points
                        ):
                            continue
                        bbox = signature.get('bbox') or {}
                        bbox_min = _tuple3_or_none(bbox.get('min'))
                        bbox_max = _tuple3_or_none(bbox.get('max'))
                        if bbox_min is None or bbox_max is None:
                            continue
                        scale = max(1.0, expected_radius)
                        if any(
                            bbox_min[index] < expected_min[index] - scale * 1.0e-4
                            or bbox_max[index] > expected_max[index] + scale * 1.0e-4
                            for index in range(3)
                        ):
                            continue
                        matches.append((candidate, signature))
                    if len(matches) < 2:
                        continue
                    total_length = sum(
                        float(signature.get('length') or 0.0)
                        for _candidate, signature in matches
                    )
                    if abs(total_length - expected_length) > max(
                        1.0, expected_length
                    ) * 1.0e-4:
                        continue
                    union_min = tuple(
                        min(signature['bbox']['min'][index] for _candidate, signature in matches)
                        for index in range(3)
                    )
                    union_max = tuple(
                        max(signature['bbox']['max'][index] for _candidate, signature in matches)
                        for index in range(3)
                    )
                    if max(
                        max(abs(union_min[index] - expected_min[index]), abs(union_max[index] - expected_max[index]))
                        for index in range(3)
                    ) <= max(1.0, expected_radius) * 1.0e-4:
                        groups.append([candidate for candidate, _signature in matches])
                if len(groups) != 1:
                    raise RuntimeError(
                        f'{kind} circular selector did not identify a unique split-edge set; '
                        f'direct_error={direct_error_text}; group_count={len(groups)}'
                    )
                selected_groups.append(groups[0])
            if not selected_groups:
                raise RuntimeError(f'{kind} requires at least one geometrically selected edge')
            selected = [edge for group in selected_groups for edge in group]
            if kind == 'fillet':
                input_obj = self.root.features.filletFeatures.createInput()
                input_obj.addConstantRadiusEdgeSet(
                    _object_collection(selected),
                    _value_cm(params.get('radius', 0.0)),
                    False,
                )
                return self.root.features.filletFeatures.add(input_obj)
            else:
                input_obj = self.root.features.chamferFeatures.createInput2()
                input_obj.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
                    _object_collection(selected),
                    _value_cm(params.get('distance', params.get('radius', 0.0))),
                    False,
                )
                return self.root.features.chamferFeatures.add(input_obj)

        def complete_feature_bodies(feature, feature_sources):
            result_bodies = list(feature.bodies)
            result_tokens = {
                str(getattr(body, 'entityToken', '')) for body in result_bodies
            }
            for source_body in feature_sources:
                try:
                    token = str(getattr(source_body, 'entityToken', ''))
                    if source_body.isValid and token not in result_tokens:
                        result_bodies.append(source_body)
                        result_tokens.add(token)
                except Exception:
                    continue
            return result_bodies

        def register_multi_body_feature(feature, feature_sources):
            feature_bodies = complete_feature_bodies(feature, feature_sources)
            if not self._native_body_sets_bbox_close(feature_bodies, feature_sources):
                raise RuntimeError(
                    f'{kind} native body-set geometry mismatch for {node_id}'
                )
            for index, result_body in enumerate(feature_bodies):
                _apply_name(result_body, f'SimpleCAD_{node_id}_{index}')
                _attach_simplecad_native_metadata(
                    result_body, node_id, str(node.get('op')), params, inputs
                )
            _apply_name(feature, _safe_label(str(node.get('op')), node_id))
            _attach_simplecad_native_metadata(
                feature, node_id, str(node.get('op')), params, inputs
            )
            self.native_features[node_id] = feature
            self.native_bodies[node_id] = feature_bodies[0]
            self.native_body_sets[node_id] = list(feature_bodies)
            return [self._body_copy(body) for body in feature_bodies]

        feature = None
        first_error = None
        try:
            feature = create_feature(source_bodies)
            attach_topology_metadata(feature)
            if len(source_bodies) > 1:
                return register_multi_body_feature(feature, source_bodies)
            return self._copy_first_feature_body_and_cleanup(
                feature,
                f'{kind} result body',
                source_bodies if source_is_fallback else [],
                node,
                expected_body=source_bodies[0],
            )
        except Exception as exc:
            first_error = exc
            if feature is not None:
                self._delete_entity(feature)
            if source_is_fallback:
                for source_body in source_bodies:
                    self._delete_entity(source_body)
            else:
                fallback_shapes = exact_input_set or [canonical_input]
                fallback_sources = [
                    self._add_base_body(self._body_copy(body))
                    for body in fallback_shapes
                ]
                for index, fallback_source in enumerate(fallback_sources):
                    _apply_name(
                        fallback_source,
                        f'SimpleCAD_base_{inputs[0]}_{node_id}_{index}',
                    )
                    _attach_simplecad_native_metadata(
                        fallback_source,
                        str(inputs[0]),
                        'static_input_fallback',
                        {},
                        [],
                    )
                feature = None
                try:
                    feature = create_feature(fallback_sources)
                    attach_topology_metadata(feature)
                    self.logs.append(
                        f'{kind} canonical-input native retry used for {node_id}: '
                        f'{first_error}'
                    )
                    if len(fallback_sources) > 1:
                        return register_multi_body_feature(feature, fallback_sources)
                    return self._copy_first_feature_body_and_cleanup(
                        feature,
                        f'{kind} result body',
                        fallback_sources,
                        node,
                        expected_body=fallback_sources[0],
                    )
                except Exception as fallback_exc:
                    if feature is not None:
                        self._delete_entity(feature)
                    for fallback_source in fallback_sources:
                        self._delete_entity(fallback_source)
                    first_error = RuntimeError(
                        f'native source failed: {first_error}; '
                        f'canonical input failed: {fallback_exc}'
                    )
            source_body = self._source_kernel_step_body(node_id)
            if source_body is None:
                raise first_error
            self.logs.append(
                f'{kind} source-kernel STEP fallback used for {node_id}: '
                f'{first_error}'
            )
            return source_body

    def _feature_shell(self, node, params, inputs):
        node_id = str(node.get('node_id'))
        source, source_is_fallback = self._native_source_body(
            inputs[0], self._first_output(inputs[0])
        )
        try:
            selectors = []
            for selector_id in params.get('selected_face_node_ids') or []:
                payload = self.selection_payloads.get(str(selector_id))
                if payload:
                    selectors.append(payload.get('params') or {})
            for item in params.get('selected_faces') or []:
                if isinstance(item, dict):
                    selectors.append(item.get('selector_hint') or item)
            if not selectors and SELECTION_MODE == 'index':
                selectors.extend(
                    {
                        'kind': 'face',
                        'metadata_geo': {'face_index': int(index)},
                    }
                    for index in params.get('selected_face_indices') or []
                )
            faces = []
            for selector in selectors:
                faces.append(_best_by_geometry(list(source.faces), selector, _face_signature, 'face'))
            input_obj = self.root.features.shellFeatures.createInput(faces, False)
            input_obj.insideThickness = _value_cm(params.get('thickness', 0.0))
            feature = self.root.features.shellFeatures.add(input_obj)
            cleanup = [source] if source_is_fallback else []
            return self._copy_first_feature_body_and_cleanup(
                feature,
                'shell result body',
                cleanup,
                node,
                expected_body=source,
            )
        except Exception as exc:
            source_body = self._source_kernel_step_body(node_id)
            if source_body is None:
                raise
            self.logs.append(f'shell source-kernel STEP fallback used for {node_id}: {exc}')
            if source_is_fallback:
                self._delete_entity(source)
            return source_body

    def _bodies_from_product(self, value, placements=()):
        if not isinstance(value, dict):
            return []
        if value.get('kind') == 'part':
            body = value.get('body')
            if body is None:
                return []
            body = self._body_copy(body)
            for placement in reversed(tuple(placements)):
                self.tmp.transform(body, _matrix_from_placement(placement))
            return [body]
        if value.get('kind') in {'assembly', 'state'}:
            bodies = []
            for component in value.get('components') or []:
                component_placement = component.get('placement') or {}
                bodies.extend(
                    self._bodies_from_product(
                        component.get('item'),
                        tuple(placements) + (component_placement,),
                    )
                )
            return [body for body in bodies if body is not None]
        return []

    def _product_definition_key(self, value, node_id):
        params = value.get('params') or {}
        kind = str(value.get('kind') or '')
        if kind == 'part':
            definition_id = str(params.get('part_id') or params.get('id') or node_id)
        else:
            definition_id = str(params.get('assembly_id') or params.get('id') or node_id)
        return kind, definition_id

    def _set_occurrence_visibility(self, occurrence, visible):
        try:
            occurrence.isLightBulbOn = bool(visible)
        except Exception:
            pass

    def _ensure_product_definition(self, value, result_node_id):
        if not isinstance(value, dict) or value.get('kind') not in {'part', 'assembly', 'state'}:
            raise RuntimeError('Fusion product definition must be a part or assembly')
        key = self._product_definition_key(value, result_node_id)
        existing = self.product_definition_components.get(key)
        if existing is not None:
            return existing

        params = value.get('params') or {}
        display_name = str(
            params.get('name')
            or params.get('part_id')
            or params.get('assembly_id')
            or key[1]
        )
        identity = adsk.core.Matrix3D.create()

        if value.get('kind') == 'part':
            body = value.get('body')
            if body is None:
                raise RuntimeError(f'Fusion part definition {key[1]} has no body')
            body_node = str(value.get('body_node') or '')
            seed = self.precreated_component_occurrences.get(body_node)
            if seed is not None:
                component = seed.component
            else:
                seed = self.root.occurrences.addNewComponent(identity)
                if seed is None:
                    raise RuntimeError(
                        f'Fusion could not create part definition {key[1]}'
                    )
                component = seed.component
                base_feature = component.features.baseFeatures.add()
                base_feature.startEdit()
                try:
                    added = component.bRepBodies.add(self._body_copy(body), base_feature)
                    if added is None:
                        raise RuntimeError(
                            f'Fusion could not add body for part definition {key[1]}'
                        )
                finally:
                    base_feature.finishEdit()
            _apply_name(component, display_name)
            _apply_name(seed, f'SimpleCAD_definition_{key[1]}')
            _set_simplecad_attribute(component, 'DefinitionKind', 'single_solid')
            _set_simplecad_attribute(component, 'DefinitionId', key[1])
            _set_simplecad_attribute(component, 'BodyNodeId', body_node)
            self._set_occurrence_visibility(seed, False)
            record = {'component': component, 'seed': seed, 'solid_count': 1}
            self.product_definition_components[key] = record
            return record

        seed = self.root.occurrences.addNewComponent(identity)
        if seed is None:
            raise RuntimeError(
                f'Fusion could not create assembly definition {key[1]}'
            )
        component = seed.component
        _apply_name(component, display_name)
        _apply_name(seed, f'SimpleCAD_definition_{key[1]}')
        _set_simplecad_attribute(component, 'DefinitionKind', 'assembly')
        _set_simplecad_attribute(component, 'DefinitionId', key[1])
        _set_simplecad_chunked_attribute(
            component,
            'AssemblyEvaluation',
            json.dumps(value.get('evaluation') or {}, sort_keys=True),
        )
        record = {'component': component, 'seed': seed, 'solid_count': 0}
        self.product_definition_components[key] = record
        solid_count = 0
        for child_record in value.get('components') or []:
            item = child_record.get('item') or {}
            child_definition = self._ensure_product_definition(item, result_node_id)
            placement = child_record.get('placement') or {}
            occurrence = component.occurrences.addExistingComponent(
                child_definition['component'], _matrix_from_placement(placement)
            )
            if occurrence is None:
                raise RuntimeError(
                    f"Fusion could not instantiate component {child_record.get('component_id')!r} "
                    f"inside assembly {key[1]!r}"
                )
            component_id = str(child_record.get('component_id') or '')
            child_params = child_record.get('params') or {}
            _apply_name(
                occurrence,
                str(child_params.get('name') or component_id or child_definition['component'].name),
            )
            _set_simplecad_attribute(occurrence, 'ComponentId', component_id)
            _set_simplecad_attribute(occurrence, 'ParentDefinitionId', key[1])
            _set_simplecad_attribute(
                occurrence,
                'DefinitionId',
                self._product_definition_key(item, result_node_id)[1],
            )
            try:
                occurrence.isGroundToParent = component_id in set(
                    value.get('grounded_component_ids') or []
                )
            except Exception:
                pass
            solid_count += int(child_definition['solid_count'])
        record['solid_count'] = solid_count
        self._set_occurrence_visibility(seed, False)
        return record

    def _materialize_product_value(self, value, node_id, placements=()):
        if placements:
            raise RuntimeError('Fusion product roots cannot carry external placements')
        definition = self._ensure_product_definition(value, node_id)
        self._set_occurrence_visibility(definition['seed'], True)
        _set_simplecad_attribute(definition['component'], 'RootProduct', 'true')
        return int(definition['solid_count'])

    def _materialize_results(self):
        if not self.result_node_ids:
            self.result_node_ids = [str(node.get('node_id')) for node in self.nodes[-1:]]
        # Fusion's STEP exporter includes every visible intermediate feature
        # body.  Keep the complete parametric history but expose only the
        # selected terminal result bodies.
        for body in self.root.bRepBodies:
            try:
                body.isVisible = False
            except Exception:
                pass
        emitted = 0
        for node_id in self.result_node_ids:
            values = list(self.outputs.get(node_id, []))
            native_set = list(self.native_body_sets.get(str(node_id)) or [])
            # Detail and boolean features can legitimately produce several
            # disconnected result bodies. Their output list is one semantic
            # result, so materialize the matching native set as a unit. If
            # each body is handled independently, _materialize_value compares
            # the whole native set with one body and falls back to static
            # copies, leaving the editable native bodies hidden in the export.
            if (
                len(native_set) > 1
                and len(values) == len(native_set)
                and all(isinstance(value, adsk.fusion.BRepBody) for value in values)
                and self._native_body_list_close(native_set, values)
            ):
                for index, native_part in enumerate(native_set):
                    _apply_name(native_part, f'SimpleCAD_{node_id}_{index}')
                    try:
                        native_part.isVisible = True
                    except Exception:
                        pass
                emitted += len(native_set)
                continue
            for value in values:
                emitted += self._materialize_value(value, node_id)
        if emitted == 0:
            for node_id, outputs in self.outputs.items():
                for value in outputs:
                    emitted += self._materialize_value(value, node_id)
        if emitted == 0:
            raise RuntimeError('Fusion translator produced no materialized bodies')

    def _native_body_list_close(self, native_bodies, expected_bodies):
        """Match a multi-body native result to its serialized body list."""
        remaining = list(native_bodies)
        try:
            if len(remaining) != len(expected_bodies):
                return False
            for expected in expected_bodies:
                matches = [
                    candidate
                    for candidate in remaining
                    if self._native_body_close(candidate, expected)
                ]
                if len(matches) != 1:
                    return False
                remaining.remove(matches[0])
            return not remaining
        except Exception:
            return False

    def _materialize_value(self, value, node_id):
        count = 0
        native = self.native_bodies.get(str(node_id))
        native_set = self.native_body_sets.get(str(node_id)) or []
        node = self.node_by_id.get(str(node_id)) or {}
        if (
            native_set
            and isinstance(value, adsk.fusion.BRepBody)
            and self._native_body_set_close(native_set, value)
        ):
            for index, native_part in enumerate(native_set):
                _apply_name(native_part, f'SimpleCAD_{node_id}_{index}')
                try:
                    native_part.isVisible = True
                except Exception:
                    pass
            return len(native_set)
        if (
            native is not None
            and isinstance(value, adsk.fusion.BRepBody)
            and self._native_body_close(native, value)
        ):
            _apply_name(native, f'SimpleCAD_{node_id}')
            _attach_simplecad_native_metadata(
                native,
                str(node_id),
                str((self.node_by_id.get(str(node_id)) or {}).get('op') or ''),
                (self.node_by_id.get(str(node_id)) or {}).get('params') or {},
                self._input_ids(self.node_by_id.get(str(node_id)) or {}),
            )
            try:
                native.isVisible = True
            except Exception:
                pass
            return 1
        if native is not None:
            self.logs.append(
                f'native terminal geometry mismatch for {node_id}; '
                'materializing exact static result; '
                f'comparison={self._native_body_comparison(native, value)!r}'
            )
        if isinstance(value, adsk.fusion.BRepBody):
            body = self._add_base_body(value)
            _apply_name(body, f'SimpleCAD_{node_id}')
            _attach_simplecad_native_metadata(
                body,
                str(node_id),
                str(node.get('op') or ''),
                node.get('params') or {},
                self._input_ids(node),
            )
            return 1
        if isinstance(value, dict) and value.get('kind') in {'part', 'assembly', 'state'}:
            count += self._materialize_product_value(value, node_id)
        return count


def _safe_label(op, node_id):
    raw = f'{op}_{node_id}'
    token = ''.join(ch if ch.isalnum() else '_' for ch in raw).strip('_')
    if not token:
        token = 'simplecad'
    if token[0].isdigit():
        token = 'simplecad_' + token
    return token[:80]
'''
