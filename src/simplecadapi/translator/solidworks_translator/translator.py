"""Translate SimpleCAD model/graph payloads into SolidWorks COM automation scripts.

This module intentionally targets the SolidWorks COM automation API through a
per-node emitted runtime, mirroring the FreeCAD backend's architecture:
the generated script contains one ``runtime.emit_node(...)`` call per canonical
graph node, preceded by its sanitized parameter and input literals.
"""

from __future__ import annotations

import base64
import json
import os
import zlib
from typing import Any, Dict, List, Optional, Sequence, Set


from ...recording.serializer import import_model_json
from ...errors import ErrorGuidance
from simplecadapi._cpp import OperationGraph, OperationNode
from ..base import BaseTranslator
from ..errors import TranslationRequestError
from ..types import (
    BackendCapabilities,
    SupportLevel,
    TranslationArtifact,
)
from .analysis import (
    _assembly_state_result_node_ids,
    _recorded_detail_edge_catalog,
    _preferred_result_node_ids,
    _result_dependency_node_ids,
)
from .capabilities import CAPABILITIES
from .codegen import _emit_node_lines, _json_ascii, _py_literal
from .context import SolidWorksCompileContext
from .emitters import (
    BooleanEmitterMixin,
    FeatureEmitterMixin,
    GeometryEmitterMixin,
    PrimitiveEmitterMixin,
    ProductEmitterMixin,
    SelectionEmitterMixin,
    TransformEmitterMixin,
    emit_native_node,
)
from .runtime import assemble_runtime_source
from .emitters.products import evaluated_assembly_params
from .versions import normalize_solidworks_version


def _dependency_node_ids(
    graph: OperationGraph, result_node_ids: Sequence[str]
) -> Set[str]:
    needed: Set[str] = set()
    pending = [str(node_id) for node_id in result_node_ids]
    while pending:
        node_id = pending.pop()
        if node_id in needed:
            continue
        node = graph.get_node(node_id)
        if node is None:
            raise ValueError(f"Result node {node_id!r} is not present in the graph")
        needed.add(node_id)
        pending.extend(input_ref.node_id for input_ref in node.inputs)
        for key in ("selected_edge_node_ids", "selected_face_node_ids"):
            pending.extend(str(value) for value in node.params.get(key, []) or [])
    return needed


def _supported_ops() -> Set[str]:
    supported: Set[str] = set()
    for op, capability in CAPABILITIES.operations.items():
        if capability.level is not SupportLevel.UNSUPPORTED:
            supported.add(str(op))
    return supported


def _curve_params_with_kernel_axes(params: Dict[str, Any]) -> Dict[str, Any]:
    """Add the source OCC periodic basis without mutating graph parameters."""

    enriched = dict(params)
    normal = enriched.get("normal", (0.0, 0.0, 1.0))
    x_axis, y_axis = _occ_default_axes(normal)
    enriched["_kernel_x_axis"] = list(x_axis)
    enriched["_kernel_y_axis"] = list(y_axis)
    return enriched


def _occ_default_axes(normal: Any) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """The X and Y directions OpenCASCADE's ``gp_Ax2(origin, Dir(normal))`` picks.

    Same selection as ``gp_Ax2::gp_Ax2(P, V)``: the axis least aligned with the normal decides the
    perpendicular direction; Y is Z x X.
    """

    import math

    nx, ny, nz = (float(normal[0]), float(normal[1]), float(normal[2]))
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1e-300:
        raise ValueError("normal must not be the zero vector")
    zx, zy, zz = nx / length, ny / length, nz / length
    a, b, c = abs(zx), abs(zy), abs(zz)
    if b <= a and b <= c:
        x = (-zz, 0.0, zx) if a > c else (zz, 0.0, -zx)
    elif a <= b and a <= c:
        x = (0.0, -zz, zy) if b > c else (0.0, zz, -zy)
    else:
        x = (-zy, zx, 0.0) if a > b else (zy, -zx, 0.0)
    xl = math.sqrt(x[0] ** 2 + x[1] ** 2 + x[2] ** 2)
    x = (x[0] / xl, x[1] / xl, x[2] / xl)
    y = (zy * x[2] - zz * x[1], zz * x[0] - zx * x[2], zx * x[1] - zy * x[0])
    return x, y


def make_interpolated_bspline_edge(points: Any, *, periodic: bool = False, tolerance: float = 1.0e-6) -> Any:
    """An interpolating B-spline edge on the active backend."""

    from simplecadapi._cpp import _native as native

    return native._interpolated_bspline_edge(
        [tuple(float(v) for v in p) for p in points],
        periodic=periodic,
        tolerance=tolerance,
    )


def _interpolated_curve_params(
    params: Dict[str, Any], context: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Freeze the source OCC interpolation result for exact reconstruction."""

    context = dict(context or {})
    origin = context.get("origin", (0.0, 0.0, 0.0))
    x_axis = context.get("x_axis", (1.0, 0.0, 0.0))
    y_axis = context.get("y_axis", (0.0, 1.0, 0.0))
    z_axis = context.get("z_axis", (0.0, 0.0, 1.0))

    def world_point(point: Any) -> List[float]:
        values = [float(value) for value in point]
        if len(values) == 2:
            values.append(0.0)
        return [
            float(origin[index])
            + values[0] * float(x_axis[index])
            + values[1] * float(y_axis[index])
            + values[2] * float(z_axis[index])
            for index in range(3)
        ]

    global_points = [world_point(point) for point in params.get("points", ())]
    if len(global_points) < 2:
        return dict(params)
    try:
        edge = make_interpolated_bspline_edge(
            global_points,
            periodic=bool(params.get("periodic", False)),
            tolerance=float(params.get("tolerance", 1.0e-6)),
        )
        exact = _exact_bspline_data(edge)
    except Exception:
        return dict(params)
    enriched = dict(params)
    enriched["_exact_bspline"] = exact
    return enriched


def _exact_bspline_data(edge: Any) -> Dict[str, Any]:
    """Poles, degree, knots, multiplicities and weights of an edge's B-spline curve."""

    from simplecadapi._cpp import _native as native

    data = native._bspline_curve_of(edge)
    return {
        "control_points": [[float(v) for v in point] for point in data["control_points"]],
        "degree": int(data["degree"]),
        "knots": [float(v) for v in data["knots"]],
        "multiplicities": [int(v) for v in data["multiplicities"]],
        "weights": [float(v) for v in data["weights"]] if data["rational"] else [],
    }


def _clamped_spline_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Clamp an unclamped B-spline so SolidWorks accepts its knot data.

    SW's ISplineParamData/CreateSplinesByEqnParams2 only accepts clamped
    splines (end knot multiplicity == degree + 1). OCC allows unclamped
    forms; trimming the curve to its own parameter range (Segment) yields
    the mathematically identical curve in clamped form.
    """

    control_points = params.get("control_points") or params.get("controls")
    knots = params.get("knots")
    mults = params.get("multiplicities")
    if not control_points or not knots or not mults:
        return params
    degree = int(params.get("degree") or 3)
    if int(mults[0]) >= degree + 1 and int(mults[-1]) >= degree + 1:
        return params
    try:
        from simplecadapi._cpp.occt.TColgp import TColgp_Array1OfPnt
        from simplecadapi._cpp.occt.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
        from simplecadapi._cpp.occt.Geom import Geom_BSplineCurve
        from simplecadapi._cpp.occt.gp import gp_Pnt

        poles = TColgp_Array1OfPnt(1, len(control_points))
        for index, point in enumerate(control_points, 1):
            poles.SetValue(index, gp_Pnt(*[float(v) for v in point[:3]]))
        knot_array = TColStd_Array1OfReal(1, len(knots))
        mult_array = TColStd_Array1OfInteger(1, len(mults))
        for index, (knot, mult) in enumerate(zip(knots, mults), 1):
            knot_array.SetValue(index, float(knot))
            mult_array.SetValue(index, int(mult))
        weights = params.get("weights") or [1.0] * len(control_points)
        weight_array = TColStd_Array1OfReal(1, len(control_points))
        for index, weight in enumerate(weights, 1):
            weight_array.SetValue(index, float(weight))
        curve = Geom_BSplineCurve(
            poles, weight_array, knot_array, mult_array, degree,
            bool(params.get("periodic", False)),
        )
        curve.Segment(curve.FirstParameter(), curve.LastParameter())
        enriched = dict(params)
        enriched["control_points"] = [
            [curve.Pole(i).X(), curve.Pole(i).Y(), curve.Pole(i).Z()]
            for i in range(1, curve.NbPoles() + 1)
        ]
        enriched["knots"] = [curve.Knot(i) for i in range(1, curve.NbKnots() + 1)]
        enriched["multiplicities"] = [
            curve.Multiplicity(i) for i in range(1, curve.NbKnots() + 1)
        ]
        enriched["weights"] = [
            curve.Weight(i) for i in range(1, curve.NbPoles() + 1)
        ]
        enriched["periodic"] = bool(curve.IsPeriodic())
        return enriched
    except Exception:
        return params


def _sanitize_solidworks_params(value: Any) -> Any:
    """Drop recorded topology indices so the runtime must match by geometry."""

    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, child in value.items():
            if key in {
                "selected_edge_indices",
                "selected_face_indices",
                "edge_index_param",
                "face_index_param",
                "topo_id",
            }:
                continue
            if key == "metadata_geo":
                child_cleaned = _sanitize_solidworks_params(child)
                if isinstance(child_cleaned, dict):
                    child_cleaned = {
                        k: v
                        for k, v in child_cleaned.items()
                        if k not in {"edge_index", "face_index"}
                    }
                if child_cleaned:
                    cleaned[key] = child_cleaned
                continue
            cleaned[key] = _sanitize_solidworks_params(child)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_sanitize_solidworks_params(item) for item in value]
    return value


class _SolidWorksCompiler(
    PrimitiveEmitterMixin,
    GeometryEmitterMixin,
    SelectionEmitterMixin,
    FeatureEmitterMixin,
    BooleanEmitterMixin,
    TransformEmitterMixin,
    ProductEmitterMixin,
):
    """Compile one canonical payload into a per-node SolidWorks script."""

    def __init__(
        self,
        document_name: str = "SimpleCADModel",
        *,
        visible: bool = False,
        solidworks_version: str = "2025",
    ) -> None:
        self._context = SolidWorksCompileContext(
            document_name=document_name,
            visible=visible,
            solidworks_version=solidworks_version,
        )

    @property
    def document_name(self) -> str:
        return self._context.document_name

    @property
    def _source_graph(self) -> Optional[OperationGraph]:
        return self._context.source_graph

    def _node_inputs(self, node: OperationNode) -> List[Dict[str, str]]:
        return [{"node_id": str(input_ref.node_id)} for input_ref in node.inputs]

    def _solidworks_params(self, node: OperationNode) -> Dict[str, Any]:
        params = _sanitize_solidworks_params(dict(node.params))
        op = str(node.op)
        if op in {"make_angle_arc_redge", "make_circle_redge"}:
            params = _curve_params_with_kernel_axes(params)
        elif op == "make_interpolated_spline_redge":
            params = _interpolated_curve_params(
                params, getattr(node, "context", None)
            )
        elif op == "make_spline_redge":
            params = _clamped_spline_params(params)
        elif op == "evaluate_assembly_definition":
            params = evaluated_assembly_params(params)
        return params

    def translate_model_json_to_script(
        self,
        json_str: str,
        *,
        output_path: Optional[str] = None,
    ) -> str:
        payload = import_model_json(json_str)
        graph = payload.get("graph")
        if not isinstance(graph, OperationGraph):
            raise ValueError(
                "SolidWorks translation requires model JSON with a canonical low-level graph"
            )
        if graph.node_count == 0:
            raise ValueError(
                "SolidWorks translation requires model JSON with a non-empty canonical low-level graph"
            )
        return self.translate_model_payload_to_script(
            payload, graph=graph, output_path=output_path
        )

    def translate_model_payload_to_script(
        self,
        payload: Dict[str, Any],
        *,
        graph: OperationGraph,
        output_path: Optional[str] = None,
    ) -> str:
        leaf_ids = payload.get("leaf_ids")
        if isinstance(leaf_ids, list) and leaf_ids:
            self._context.declared_result_node_id_list = [
                str(value) for value in leaf_ids
            ]
        else:
            self._context.declared_result_node_id_list = [
                leaf.node_id for leaf in graph.leaf_nodes()
            ]
        self._context.source_graph = graph
        self._context.result_state_node_ids = _assembly_state_result_node_ids(
            graph, self._context.declared_result_node_id_list
        )
        self._context.result_node_id_list = _preferred_result_node_ids(
            graph, self._context.declared_result_node_id_list
        )
        self._context.active_result_state = next(
            (
                state
                for state, node_ids in self._context.result_state_node_ids.items()
                if node_ids == self._context.result_node_id_list
            ),
            None,
        )
        self._context.result_node_ids = set(self._context.result_node_id_list)

        closure_ids = _result_dependency_node_ids(
            graph, self._context.result_node_id_list
        )
        nodes_in_closure = [
            node
            for node in graph.topological_order()
            if str(node.node_id) in closure_ids
        ]
        payload_dict = self._payload_to_jsonable(payload, graph, nodes_in_closure)
        if os.environ.get("SIMPLECAD_SW_PERSIST_TOPOLOGY", "1") != "0":
            detail_edge_catalog = _recorded_detail_edge_catalog(
                graph, self._context.result_node_id_list
            )
            if detail_edge_catalog:
                catalog_json = json.dumps(
                    detail_edge_catalog,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("ascii")
                payload_dict["solidworks_detail_edge_catalog_z"] = (
                    base64.b64encode(zlib.compress(catalog_json, level=9)).decode(
                        "ascii"
                    )
                )

        node_lines: List[str] = []
        for node in nodes_in_closure:
            emitted = emit_native_node(self, node)
            if emitted is None:
                raise TranslationRequestError(
                    "solidworks",
                    "translate_model_payload",
                    ErrorGuidance(
                        what_happened=(
                            "The SolidWorks runtime has no emitter for op "
                            f"{node.op!r}."
                        ),
                        possible_causes=(
                            "The graph contains an operation outside the "
                            "SolidWorks emitter registry.",
                        ),
                        how_to_fix=(
                            "Extend EMITTER_METHOD_BY_OP in "
                            "solidworks_translator.emitters.registry.",
                        ),
                    ),
                )
            node_lines.extend(emitted)

        return self._assemble_script(payload_dict, node_lines, output_path)

    def _payload_to_jsonable(
        self,
        payload: Dict[str, Any],
        source_graph: OperationGraph,
        nodes_in_closure: List[OperationNode],
    ) -> Dict[str, Any]:
        nodes = [
            {
                "node_id": str(node.node_id),
                "op": str(node.op),
                "params": self._solidworks_params(node),
                "inputs": self._node_inputs(node),
            }
            for node in nodes_in_closure
        ]
        return {
            "schema_version": str(payload.get("schema_version", "2.0")),
            "graph": {
                "graph_id": str(getattr(source_graph, "graph_id", "graph")),
                "nodes": nodes,
            },
            "leaf_ids": [str(v) for v in payload.get("leaf_ids", [])],
        }

    def _assemble_script(
        self,
        payload_dict: Dict[str, Any],
        node_lines: List[str],
        output_path: Optional[str],
    ) -> str:
        return (
            "from __future__ import annotations\n"
            "\n"
            "import base64\n"
            "import glob\n"
            "import hashlib\n"
            "import json\n"
            "import math\n"
            "import os\n"
            "import shutil\n"
            "import time\n"
            "import traceback\n"
            "import zlib\n"
            "\n"
            "import pythoncom\n"
            "import win32com.client\n"
            "\n"
            f"DOC_NAME = {_json_ascii(self.document_name)}\n"
            f"VISIBLE = {_py_literal(bool(self._context.visible))}\n"
            f"SOLIDWORKS_VERSION = {_json_ascii(str(self._context.solidworks_version))}\n"
            f"MODEL_PAYLOAD = {_py_literal(payload_dict)}\n"
            f"DECLARED_RESULT_NODE_IDS = {_py_literal(self._context.declared_result_node_id_list)}\n"
            f"RESULT_STATE_NODE_IDS = {_py_literal(self._context.result_state_node_ids)}\n"
            f"ACTIVE_RESULT_STATE = {_py_literal(self._context.active_result_state)}\n"
            f"RESULT_NODE_IDS = {_py_literal(self._context.result_node_id_list)}\n"
            f"OUTPUT_PATH = {_json_ascii(os.path.abspath(output_path)) if output_path else 'None'}\n"
            "\n"
            "# SolidWorks runtime\n"
            + assemble_runtime_source()
            + "\n"
            "def main():\n"
            "    pythoncom.CoInitialize()\n"
            "    runtime = None\n"
            "    try:\n"
            "        runtime = SimpleCADSolidWorksRuntime(MODEL_PAYLOAD, DOC_NAME, RESULT_NODE_IDS, visible=VISIBLE, solidworks_version=SOLIDWORKS_VERSION)\n"
            + "\n".join(node_lines)
            + "\n        runtime.finalize(output_path=OUTPUT_PATH)\n"
            "        print(json.dumps({'document_name': DOC_NAME, 'output_path': OUTPUT_PATH, 'strategy': 'operation_graph_native'}))\n"
            "    finally:\n"
            "        if runtime is not None:\n"
            "            runtime.finish()\n"
            "        else:\n"
            "            pythoncom.CoUninitialize()\n"
            "\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    try:\n"
            "        main()\n"
            "    except Exception:\n"
            "        traceback.print_exc()\n"
            "        raise\n"
        )


class SolidWorksTranslator(BaseTranslator):
    """Public, stateless facade for SolidWorks script translation."""

    def __init__(
        self,
        document_name: str = "SimpleCADModel",
        *,
        output_path: Optional[str] = None,
        visible: bool = False,
        solidworks_version: str = "2025",
    ) -> None:
        self.document_name = str(document_name)
        self.output_path = output_path
        self.visible = bool(visible)
        self.solidworks_version = normalize_solidworks_version(solidworks_version)

    @property
    def capabilities(self) -> BackendCapabilities:
        return CAPABILITIES

    def _preflight(self, graph: OperationGraph, result_node_id: str) -> None:
        needed = _dependency_node_ids(graph, [result_node_id])
        supported = _supported_ops()
        unsupported = sorted(
            {
                node.op
                for node in graph.nodes
                if str(node.node_id) in needed and str(node.op) not in supported
            }
        )
        if unsupported:
            joined = ", ".join(unsupported)
            raise TranslationRequestError(
                "solidworks",
                "translate_model_payload",
                ErrorGuidance(
                    what_happened=(
                        "The result graph uses unsupported SolidWorks "
                        f"operations: {joined}."
                    ),
                    possible_causes=(
                        "The model uses canonical operations not implemented "
                        "by the contributed SolidWorks runtime.",
                    ),
                    how_to_fix=(
                        "Lower the model to operations declared by "
                        "solidworks_translator.CAPABILITIES.",
                        "Use another translator backend for this model.",
                    ),
                ),
            )

    def _compiler(self) -> _SolidWorksCompiler:
        return _SolidWorksCompiler(
            self.document_name,
            visible=self.visible,
            solidworks_version=self.solidworks_version,
        )

    def translate_model_json_to_script(
        self, json_str: str, *, output_path: Optional[str] = None
    ) -> str:
        return self._compiler().translate_model_json_to_script(
            json_str, output_path=self.output_path if output_path is None else output_path
        )

    def translate_model_payload_to_script(
        self,
        payload: Dict[str, Any],
        *,
        graph: Optional[OperationGraph] = None,
    ) -> str:
        source_graph = graph or payload.get("graph")
        if not isinstance(source_graph, OperationGraph) or source_graph.node_count == 0:
            raise ValueError(
                "SolidWorks translation requires a non-empty canonical graph"
            )
        return self._compiler().translate_model_payload_to_script(
            payload, graph=source_graph, output_path=self.output_path
        )

    def translate_model_json(self, json_str: str) -> TranslationArtifact:
        return TranslationArtifact(
            backend_id="solidworks",
            target_id="solidworks_script",
            media_type="text/x-python",
            suggested_suffix=".py",
            content=self.translate_model_json_to_script(json_str),
            metadata={
                "document_name": self.document_name,
                "solidworks_version": self.solidworks_version,
            },
        )

    def translate_model_payload(
        self,
        payload: Dict[str, Any],
        *,
        graph: Optional[OperationGraph] = None,
    ) -> TranslationArtifact:
        return TranslationArtifact(
            backend_id="solidworks",
            target_id="solidworks_script",
            media_type="text/x-python",
            suggested_suffix=".py",
            content=self.translate_model_payload_to_script(payload, graph=graph),
            metadata={
                "document_name": self.document_name,
                "solidworks_version": self.solidworks_version,
            },
        )

    def translate_product_package(
        self,
        data: Any,
        **_options: Any,
    ) -> TranslationArtifact:
        from ..package_units import ProductPackageInput  # noqa: F401
        from ..product_graph import build_product_graph_view

        view = build_product_graph_view(data)
        self._preflight(view.graph, view.root_result_node_id)
        script = self._compiler().translate_model_payload_to_script(
            view.model_payload(), graph=view.graph, output_path=self.output_path
        )
        return TranslationArtifact(
            backend_id="solidworks",
            target_id="solidworks_script",
            media_type="text/x-python",
            suggested_suffix=".py",
            content=script,
            metadata={
                "document_name": self.document_name,
                "solidworks_version": self.solidworks_version,
                "root_definition_id": view.root_definition_id,
                "root_definition_kind": view.root_definition_kind,
                "definition_ids": view.definition_ids,
                "target_runtime_validated": False,
            },
        )


__all__ = ["SolidWorksTranslator"]
