"""Translate SimpleCAD model/graph payloads into FreeCAD Python API scripts.

This module intentionally targets FreeCAD's Python API, not raw `.FCStd`
internals. Generated scripts can be executed inside FreeCAD/FreeCADCmd and then
saved as `.FCStd` by FreeCAD itself.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from simplecadapi._cpp import OperationGraph, OperationNode
from ..base import BaseTranslator
from ..types import BackendCapabilities, TranslationArtifact
from .analysis import (
    can_fold_transform_into_input,
    can_lower_circle_extrusion_to_cylinder,
    find_cylinder_profile_nodes,
    should_materialize_transform_for_loft_section,
    transform_feeds_only_loft,
)
from .capabilities import CAPABILITIES
from .codegen import (
    _OP_EXPRESSION_BINDINGS,
    _OP_EXPRESSION_LIMITATIONS,
    _canonical_variable_default,
    _compile_time_nested_expr_ref,
    _expression_physical_metadata,
    _json_ascii,
    _py_literal,
    _safe_name,
    _sanitize_expr_alias,
    _spreadsheet_expr_aliases,
)
from .context import FreeCADCompileContext
from .emitters import (
    BooleanEmitterMixin,
    FeatureEmitterMixin,
    GeometryEmitterMixin,
    PrimitiveEmitterMixin,
    ProductEmitterMixin,
    SelectionEmitterMixin,
    SketchEmitterMixin,
    SurfaceEmitterMixin,
    TransformEmitterMixin,
    emit_native_node,
)
from .runtime import assemble_runtime_source
from .semantic import build_freecad_semantic_plan


def _curve_params_with_kernel_axes(params: Dict[str, Any]) -> Dict[str, Any]:
    """Add the source OCC periodic basis without mutating graph parameters."""

    from simplecadapi._cpp.occt.gp import gp_Ax2, gp_Dir, gp_Pnt

    enriched = dict(params)
    normal = enriched.get("normal", (0.0, 0.0, 1.0))
    axis = gp_Ax2(
        gp_Pnt(0.0, 0.0, 0.0),
        gp_Dir(float(normal[0]), float(normal[1]), float(normal[2])),
    )
    x_axis = axis.XDirection()
    y_axis = axis.YDirection()
    enriched["_kernel_x_axis"] = [x_axis.X(), x_axis.Y(), x_axis.Z()]
    enriched["_kernel_y_axis"] = [y_axis.X(), y_axis.Y(), y_axis.Z()]
    return enriched


def _interpolated_curve_params(
    params: Dict[str, Any], context: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Freeze the source OCC interpolation result for exact FreeCAD reconstruction."""

    from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve

    from simplecadapi._cpp import _native as native

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
    edge = native._interpolated_bspline_edge(
        [tuple(float(v) for v in p) for p in global_points],
        periodic=bool(params.get("periodic", False)),
        tolerance=float(params.get("tolerance", 1.0e-6)),
    )
    curve = BRepAdaptor_Curve(getattr(edge, "wrapped", edge)).BSpline()
    enriched = dict(params)
    enriched["_freecad_exact_bspline"] = {
        "control_points": [
            [
                float(curve.Pole(index).X()),
                float(curve.Pole(index).Y()),
                float(curve.Pole(index).Z()),
            ]
            for index in range(1, curve.NbPoles() + 1)
        ],
        "degree": int(curve.Degree()),
        "knots": [float(curve.Knot(index)) for index in range(1, curve.NbKnots() + 1)],
        "multiplicities": [
            int(curve.Multiplicity(index)) for index in range(1, curve.NbKnots() + 1)
        ],
        "weights": (
            [float(curve.Weight(index)) for index in range(1, curve.NbPoles() + 1)]
            if curve.IsRational()
            else None
        ),
        "periodic": bool(curve.IsPeriodic()),
    }
    return enriched


class _FreeCADCompiler(
    PrimitiveEmitterMixin,
    ProductEmitterMixin,
    SelectionEmitterMixin,
    SketchEmitterMixin,
    GeometryEmitterMixin,
    SurfaceEmitterMixin,
    FeatureEmitterMixin,
    BooleanEmitterMixin,
    TransformEmitterMixin,
):
    """Compile a SimpleCAD model payload into a FreeCAD Python script.

    Current design goals:

    - Translate only from the canonical low-level `graph` IR
    - Preserve node metadata and graph lineage as FreeCAD custom properties
    - Preserve `expression_graph` as explicit translator metadata
    - Preserve dimension tolerances and tolerance-chain requirements as metadata
    - Preserve exported assembly constraints as document metadata objects
    - Prefer native FreeCAD Boolean features so translated history remains editable
      and recomputable; accept OCCT-version drift until a concrete operation fails
    - Present geometry as variable-named semantic design history instead of a
      flat node-id tree, while retaining the original graph objects internally
    - Keep assembly metadata from the full model payload alongside the IR-driven
      geometry translation
    """

    def __init__(
        self,
        document_name: str = "SimpleCADModel",
        *,
        expression_sheet_name: str = "SimpleCADExpressions",
        definition_token: str = "",
        definition_id: str = "",
        definition_kind: str = "",
        definition_revision: str = "",
        definition_content_hash: str = "",
    ) -> None:
        self._context = FreeCADCompileContext(
            document_name=document_name,
            expression_sheet_name=expression_sheet_name,
            definition_token=definition_token,
            definition_id=definition_id,
            definition_kind=definition_kind,
            definition_revision=definition_revision,
            definition_content_hash=definition_content_hash,
        )

    @property
    def document_name(self) -> str:
        return self._context.document_name

    @property
    def _source_graph(self) -> Optional[OperationGraph]:
        return self._context.source_graph

    @property
    def _expr_alias_by_id(self) -> Dict[str, str]:
        return self._context.expression_aliases

    @_expr_alias_by_id.setter
    def _expr_alias_by_id(self, value: Dict[str, str]) -> None:
        self._context.expression_aliases = value

    @property
    def _result_node_ids(self) -> Set[str]:
        return self._context.result_node_ids

    @property
    def _result_node_id_list(self) -> List[str]:
        return self._context.result_node_id_list

    @_result_node_id_list.setter
    def _result_node_id_list(self, value: List[str]) -> None:
        self._context.result_node_id_list = value

    @property
    def _suppressed_profile_node_ids(self) -> Set[str]:
        return self._context.suppressed_profile_node_ids

    @_suppressed_profile_node_ids.setter
    def _suppressed_profile_node_ids(self, value: Set[str]) -> None:
        self._context.suppressed_profile_node_ids = value

    def _compile_time_expr_formula(self, expr_ref: Any) -> Optional[str]:
        if not isinstance(expr_ref, dict):
            return None
        expr_id = str(expr_ref.get("expr_id") or "")
        if not expr_id:
            return None
        alias = self._expr_alias_by_id.get(expr_id)
        if not alias:
            alias = _sanitize_expr_alias(expr_id, prefix="expr")
        return f"<<{self._context.expression_sheet_name}>>.{alias}"

    def _angle_arc_span_formula(self, param_exprs: Dict[str, Any]) -> Optional[str]:
        start_expr = self._compile_time_expr_formula(
            _compile_time_nested_expr_ref(param_exprs, "start_angle")
        )
        end_expr = self._compile_time_expr_formula(
            _compile_time_nested_expr_ref(param_exprs, "end_angle")
        )
        if start_expr is None and end_expr is None:
            return None
        if start_expr is None:
            return end_expr
        if end_expr is None:
            return f"0 - ({start_expr})"
        return f"({end_expr}) - ({start_expr})"

    def _line_delta_formula(
        self, param_exprs: Dict[str, Any], axis: int
    ) -> Optional[str]:
        start_expr = self._compile_time_expr_formula(
            _compile_time_nested_expr_ref(param_exprs, "start", axis)
        )
        end_expr = self._compile_time_expr_formula(
            _compile_time_nested_expr_ref(param_exprs, "end", axis)
        )
        if start_expr is None and end_expr is None:
            return None
        if start_expr is None:
            return end_expr
        if end_expr is None:
            return f"0 - ({start_expr})"
        return f"({end_expr}) - ({start_expr})"


    def translate_model_json_to_script(self, json_str: str) -> str:
        from ...recording.serializer import import_model_json

        payload = import_model_json(json_str)
        graph = payload.get("graph")
        if not isinstance(graph, OperationGraph):
            raise ValueError(
                "FreeCAD translation requires model JSON with a canonical low-level graph"
            )
        if graph.node_count == 0:
            raise ValueError(
                "FreeCAD translation requires model JSON with a non-empty canonical low-level graph"
            )
        return self.translate_model_payload_to_script(payload, graph=graph)

    def translate_model_payload_to_script(
        self,
        payload: Dict[str, Any],
        *,
        graph: Optional[OperationGraph] = None,
        include_preamble: bool = True,
        include_runtime: bool = True,
        finalize: bool = True,
        register_definition: Optional[Dict[str, str]] = None,
    ) -> str:
        source_graph = graph or payload.get("graph")
        if not isinstance(source_graph, OperationGraph):
            raise ValueError(
                "FreeCAD translation requires payload to contain a canonical low-level graph"
            )
        if source_graph.node_count == 0:
            raise ValueError(
                "FreeCAD translation requires payload to contain a non-empty canonical low-level graph"
            )
        self._context.source_graph = source_graph
        leaf_ids = payload.get("leaf_ids")
        if isinstance(leaf_ids, list) and leaf_ids:
            self._result_node_id_list = [str(value) for value in leaf_ids]
        else:
            self._result_node_id_list = [
                leaf.node_id for leaf in source_graph.leaf_nodes()
            ]
        self._context.result_node_ids = set(self._result_node_id_list)
        self._suppressed_profile_node_ids = self._find_cylinder_profile_nodes(
            source_graph
        )
        semantic_plan = build_freecad_semantic_plan(
            source_graph,
            self._result_node_id_list,
            document_name=self.document_name,
        )
        lines: List[str] = []
        emit = lines.append
        if include_preamble:
            emit("import json")
            emit("import math")
            emit("import FreeCAD as App")
            emit("import Part")
            emit("try:")
            emit("    import Sketcher")
            emit("except Exception:")
            emit("    Sketcher = None")
            emit("try:")
            emit("    import Assembly")
            emit("except Exception:")
            emit("    Assembly = None")
            emit("try:")
            emit("    import JointObject")
            emit("except Exception:")
            emit("    JointObject = None")
            emit("try:")
            emit("    import Spreadsheet")
            emit("except Exception:")
            emit("    Spreadsheet = None")
            emit("import os")
            emit("import zipfile")
            emit("")
            emit(f"DOC_NAME = {_json_ascii(self.document_name)}")
            emit(
                "doc = App.getDocument(DOC_NAME) if DOC_NAME in App.listDocuments() else App.newDocument(DOC_NAME)"
            )
            emit("DEFINITION_REGISTRY = {}")
        if include_runtime:
            emit("# FreeCAD runtime")
            emit(assemble_runtime_source())
        emit("GRAPH_NODES = {}")
        emit("GRAPH_OUTPUTS = {}")
        emit("GRAPH_METADATA = {}")
        emit("GRAPH_SELECTIONS = {}")
        emit("GRAPH_SPINE_OBJECTS = {}")
        emit("GRAPH_LIMITATIONS = {}")
        emit("GRAPH_TRANSLATION_LIMITATIONS = {}")
        emit("PRODUCT_VALUES = {}")
        emit("ASSEMBLY_PROJECTION_INPUTS = {}")
        emit("GUI_VISIBILITY_BY_NAME = {}")
        emit("GUI_SHOW_IN_TREE_BY_NAME = {}")
        emit("GUI_EXPANDED_BY_NAME = {}")
        emit("GUI_SHAPE_COLOR_BY_NAME = {}")
        emit("GUI_MATERIAL_OVERRIDE_BY_NAME = {}")
        emit("MATERIAL_OBJECTS_BY_ID = {}")
        emit("SIMPLECAD_JOINT_OBJECTS = {}")
        emit("SKETCH_REGISTRY = []")
        emit(f"SEMANTIC_PLAN = {_py_literal(semantic_plan)}")
        expression_graph_payload = payload.get("expression_graph", {})
        if hasattr(expression_graph_payload, "to_dict"):
            expression_graph_payload = expression_graph_payload.to_dict()
        self._expr_alias_by_id = {}
        nodes = (
            expression_graph_payload.get("nodes", [])
            if isinstance(expression_graph_payload, dict)
            else []
        )
        if isinstance(nodes, list):
            self._expr_alias_by_id = _spreadsheet_expr_aliases(nodes)
        emit(f"EXPRESSION_GRAPH = {_py_literal(expression_graph_payload)}")
        emit(
            f"SIMPLECAD_EXPRESSION_SHEET = {_json_ascii(self._context.expression_sheet_name)}"
        )
        emit("EXPR_CELL_BY_ID = {}")
        emit("EXPR_ALIAS_BY_ID = {}")
        emit("expr_sheet = None")
        tolerance_graph_payload = payload.get("tolerance_graph", {})
        if hasattr(tolerance_graph_payload, "to_dict"):
            tolerance_graph_payload = tolerance_graph_payload.to_dict()
        emit(f"TOLERANCE_GRAPH = {_py_literal(tolerance_graph_payload)}")
        emit(f"OP_EXPRESSION_BINDINGS = {_py_literal(_OP_EXPRESSION_BINDINGS)}")
        emit(f"OP_EXPRESSION_LIMITATIONS = {_py_literal(_OP_EXPRESSION_LIMITATIONS)}")
        emit("")
        for line in self._emit_expression_graph(expression_graph_payload):
            emit(line)
        emit("")
        emit("EXPRESSION_GRAPH_META = EXPRESSION_GRAPH")
        emit("TOLERANCE_GRAPH_META = TOLERANCE_GRAPH")
        emit("if TOLERANCE_GRAPH.get('requirements'):")
        emit(
            "    _make_metadata_note('simplecad_tolerance_graph', 'SimpleCAD Tolerance Graph', TOLERANCE_GRAPH)"
        )
        emit("")
        for node in source_graph.topological_order():
            emit(f"# Step {node.node_id}: {node.op}")
            node_lines = self._emit_node(node)
            for line in node_lines:
                emit(line)
            emit("")
        emit("if GRAPH_LIMITATIONS:")
        emit(
            "    _make_metadata_note('simplecad_expression_limitations', 'SimpleCAD Expression Limitations', GRAPH_LIMITATIONS)"
        )
        emit("if GRAPH_TRANSLATION_LIMITATIONS:")
        emit(
            "    _make_metadata_note('simplecad_translation_limitations', 'SimpleCAD Translation Limitations', GRAPH_TRANSLATION_LIMITATIONS)"
        )
        emit("doc.recompute()")
        if register_definition is not None:
            required = {"definition_kind", "definition_id", "revision", "content_hash"}
            if set(register_definition) != required:
                raise ValueError("register_definition identity fields are incomplete")
            result_node_id = self._result_node_id_list[-1]
            emit(
                f"DEFINITION_REGISTRY[{_json_ascii(register_definition['definition_id'])}] = {{"
                f"'definition_kind': {_json_ascii(register_definition['definition_kind'])}, "
                f"'revision': {_json_ascii(register_definition['revision'])}, "
                f"'content_hash': {_json_ascii(register_definition['content_hash'])}, "
                f"'product': PRODUCT_VALUES.get({_json_ascii(result_node_id)})}}"
            )
        if finalize:
            emit("")
            emit("RESULT_NODE_IDS = " + _py_literal(self._result_node_id_list))
            emit(
                "RESULT_OBJECTS = [obj for node_id in RESULT_NODE_IDS for obj in GRAPH_OUTPUTS.get(node_id, [])]"
            )
            emit("_apply_result_visibility(RESULT_NODE_IDS)")
            emit("_set_active_result_object(RESULT_NODE_IDS)")
            emit("_apply_occurrence_tree(SEMANTIC_PLAN)")
            emit("_restore_occurrence_tree_visibility()")
            emit("doc.TransientDir = getattr(doc, 'TransientDir', '')")
        return "\n".join(lines).rstrip() + "\n"

    def _find_cylinder_profile_nodes(self, graph: OperationGraph) -> Set[str]:
        return find_cylinder_profile_nodes(graph, self._result_node_ids)

    def _can_lower_circle_extrusion_to_cylinder(
        self, circle_node: OperationNode, extrusion_node: OperationNode
    ) -> bool:
        return can_lower_circle_extrusion_to_cylinder(circle_node, extrusion_node)

    def _emit_expression_graph(self, expression_graph_payload: Any) -> List[str]:
        if not isinstance(expression_graph_payload, dict):
            return []
        nodes = expression_graph_payload.get("nodes", [])
        if not isinstance(nodes, list) or not nodes:
            return []

        lines: List[str] = ["# Expression graph -> Spreadsheet"]
        lines.append("EXPR_CELL_BY_ID = {}")
        lines.append("EXPR_ALIAS_BY_ID = {}")
        lines.append("if Spreadsheet is not None:")
        lines.append(
            f"    expr_sheet = doc.addObject('Spreadsheet::Sheet', {_json_ascii(self._context.expression_sheet_name)})"
        )
        alias_by_id = _spreadsheet_expr_aliases(nodes)
        dimension_by_id, unit_aware_by_id = _expression_physical_metadata(nodes)
        row = 1
        for node in nodes:
            if not isinstance(node, dict):
                continue
            expr_id = str(node.get("expr_id", f"expr_{row}"))
            alias = alias_by_id[expr_id]
            cell = f"B{row}"
            lines.append(
                f"    EXPR_CELL_BY_ID[{_json_ascii(expr_id)}] = {_json_ascii(cell)}"
            )
            lines.append(
                f"    EXPR_ALIAS_BY_ID[{_json_ascii(expr_id)}] = {_json_ascii(alias)}"
            )
            lines.append(f"    expr_sheet.set('A{row}', {_json_ascii(alias)})")
            lines.append(f"    expr_sheet.set('C{row}', {_json_ascii(expr_id)})")
            comment = (
                str(node.get("comment", "") or "")
                if str(node.get("kind", "")) == "var"
                else ""
            )
            lines.append(f"    expr_sheet.set('D{row}', {_json_ascii(comment)})")
            tolerance = node.get("tolerance")
            if isinstance(tolerance, dict):
                lower_deviation = str(tolerance.get("lower_deviation", ""))
                upper_deviation = str(tolerance.get("upper_deviation", ""))
            else:
                lower_deviation = ""
                upper_deviation = ""
            lines.append(
                f"    expr_sheet.set('E{row}', {_json_ascii(lower_deviation)})"
            )
            lines.append(
                f"    expr_sheet.set('F{row}', {_json_ascii(upper_deviation)})"
            )
            nominal_unit = node.get("unit", "")
            if isinstance(nominal_unit, dict):
                nominal_unit = nominal_unit.get("symbol", "")
            tolerance_unit = node.get("tolerance_unit", "")
            if isinstance(tolerance_unit, dict):
                tolerance_unit = tolerance_unit.get("symbol", "")
            lines.append(
                f"    expr_sheet.set('G{row}', {_json_ascii(str(nominal_unit))})"
            )
            lines.append(
                f"    expr_sheet.set('H{row}', {_json_ascii(str(tolerance_unit))})"
            )
            lines.append(
                f"    expr_sheet.set('I{row}', {_json_ascii(dimension_by_id.get(expr_id, ''))})"
            )
            formula = self._freecad_expr_formula(
                node,
                alias_by_id,
                unit_aware=unit_aware_by_id.get(expr_id, False),
            )
            if formula is None:
                lines.append(
                    f"    expr_sheet.set({_json_ascii(cell)}, {_json_ascii('')})"
                )
            else:
                lines.append(
                    f"    expr_sheet.set({_json_ascii(cell)}, {_json_ascii(formula)})"
                )
            lines.append(
                f"    expr_sheet.setAlias({_json_ascii(cell)}, {_json_ascii(alias)})"
            )
            row += 1
        lines.append("else:")
        lines.append("    expr_sheet = None")
        return lines

    def _freecad_expr_formula(
        self,
        node: Dict[str, Any],
        alias_by_id: Dict[str, str],
        *,
        unit_aware: bool = False,
    ) -> Optional[str]:
        kind = str(node.get("kind", ""))
        if kind == "const":
            return str(float(node.get("value", 0.0)))
        if kind == "var":
            return str(_canonical_variable_default(node))
        if kind != "expr":
            return None

        op = str(node.get("op", ""))
        args: List[str] = []
        for arg in node.get("args", []):
            alias = alias_by_id.get(str(arg))
            if not alias:
                return None
            args.append(f"<<{self._context.expression_sheet_name}>>.{alias}")
        if op == "add" and len(args) == 2:
            return f"={args[0]} + {args[1]}"
        if op == "sub" and len(args) == 2:
            return f"={args[0]} - {args[1]}"
        if op == "mul" and len(args) == 2:
            return f"={args[0]} * {args[1]}"
        if op == "div" and len(args) == 2:
            return f"={args[0]} / {args[1]}"
        if op == "pow" and len(args) == 2:
            return f"=pow({args[0]}, {args[1]})"
        if op == "neg" and len(args) == 1:
            return f"=-({args[0]})"
        if op == "abs" and len(args) == 1:
            return f"=abs({args[0]})"
        if op == "sin" and len(args) == 1:
            return f"=sin({args[0]})" if unit_aware else f"=sin(({args[0]}) * 180 / pi)"
        if op == "cos" and len(args) == 1:
            return f"=cos({args[0]})" if unit_aware else f"=cos(({args[0]}) * 180 / pi)"
        if op == "tan" and len(args) == 1:
            return f"=tan({args[0]})" if unit_aware else f"=tan(({args[0]}) * 180 / pi)"
        if op == "sqrt" and len(args) == 1:
            return f"=sqrt({args[0]})"
        if op == "acos" and len(args) == 1:
            return f"=acos({args[0]})" if unit_aware else f"=acos({args[0]}) * pi / 180"
        if op == "asin" and len(args) == 1:
            return f"=asin({args[0]})" if unit_aware else f"=asin({args[0]}) * pi / 180"
        if op == "atan" and len(args) == 1:
            return f"=atan({args[0]})" if unit_aware else f"=atan({args[0]}) * pi / 180"
        if op == "atan2" and len(args) == 2:
            if unit_aware:
                return f"=atan2({args[0]}; {args[1]})"
            return f"=atan2({args[0]}; {args[1]}) * pi / 180"
        return None

    def _can_fold_transform_into_input(self, node: OperationNode) -> bool:
        graph = self._source_graph
        return graph is not None and can_fold_transform_into_input(
            node, graph, self._result_node_ids
        )

    def _should_materialize_transform_for_loft_section(
        self, node: OperationNode
    ) -> bool:
        graph = self._source_graph
        return graph is not None and should_materialize_transform_for_loft_section(
            node, graph
        )

    def _transform_feeds_only_loft(self, node_id: str, seen: Set[str]) -> bool:
        graph = self._source_graph
        return graph is not None and transform_feeds_only_loft(graph, node_id, seen)

    def _emit_node(self, node: OperationNode) -> List[str]:
        params = dict(node.params)
        if node.op == "make_set_public_connector_rassembly":
            required = {
                "public_connector_id",
                "source_component_id",
                "source_connector_id",
            }
            allowed = {*required, "assembly_id", "name"}
            missing = sorted(required - set(params))
            unexpected = sorted(set(params) - allowed)
            if missing:
                raise ValueError(
                    f"Graph node {node.node_id!r} ({node.op}) is missing required parameter(s): "
                    + ", ".join(missing)
                )
            if unexpected:
                raise ValueError(
                    f"Graph node {node.node_id!r} ({node.op}) contains unsupported parameter(s): "
                    + ", ".join(unexpected)
                )
        if node.op in {"make_angle_arc_redge", "make_circle_redge"}:
            params = _curve_params_with_kernel_axes(params)
        if node.op == "make_interpolated_spline_redge":
            params = _interpolated_curve_params(params, node.context)
        params_literal = _py_literal(params)
        inputs_literal = _py_literal([inp.node_id for inp in node.inputs])
        tags_literal = _py_literal(sorted(node.tags))
        context_literal = _py_literal(node.context or {})
        param_exprs_literal = _py_literal(dict(node.param_exprs))
        semantic_delta_literal = _py_literal(
            self._node_optional_payload(node, "semantic_delta")
        )
        topo_delta_literal = _py_literal(
            self._node_optional_payload(node, "topo_delta")
        )

        var_name = _safe_name(node.node_id)
        object_token = (
            f"{self._context.definition_token}_"
            if self._context.definition_token
            else ""
        )
        object_name = _safe_name(
            f"{object_token}{node.op}_{node.node_id}", prefix="step"
        )
        assignment_targets = (
            list(node.source.get("assignment_targets") or [])
            if isinstance(node.source, dict)
            else []
        )
        lines = [
            f"{var_name}_params = {params_literal}",
            f"{var_name}_inputs = {inputs_literal}",
            f"{var_name}_param_exprs = {param_exprs_literal}",
        ]

        native_lines = self._emit_native_node(
            node,
            var_name=var_name,
            object_name=object_name,
            tags_literal=tags_literal,
            context_literal=context_literal,
            param_exprs_literal=param_exprs_literal,
            semantic_delta_literal=semantic_delta_literal,
            topo_delta_literal=topo_delta_literal,
        )
        if native_lines is not None:
            lines.extend(native_lines)
            if assignment_targets:
                lines.append(
                    f"_apply_graph_assignment_name(GRAPH_OUTPUTS.get({_json_ascii(node.node_id)}, []), node_id={_json_ascii(node.node_id)}, assignment_targets={_py_literal(assignment_targets)}, op={_json_ascii(node.op)})"
                )
            return lines
        raise ValueError(f"Unsupported FreeCAD native graph translation op: {node.op} (inputs={list(getattr(node, 'inputs', []))!r})")

    def _emit_native_node(
        self,
        node: OperationNode,
        *,
        var_name: str,
        object_name: str,
        tags_literal: str,
        context_literal: str,
        param_exprs_literal: str,
        semantic_delta_literal: str,
        topo_delta_literal: str,
    ) -> Optional[List[str]]:
        native_expr = self._compile_native_feature_expr(
            node,
            var_name=var_name,
            object_name=object_name,
            tags_literal=tags_literal,
            context_literal=context_literal,
            param_exprs_literal=param_exprs_literal,
            semantic_delta_literal=semantic_delta_literal,
            topo_delta_literal=topo_delta_literal,
        )
        if native_expr is None:
            return None
        return native_expr

    def _compile_native_feature_expr(
        self,
        node: OperationNode,
        *,
        var_name: str,
        object_name: str,
        tags_literal: str,
        context_literal: str,
        param_exprs_literal: str,
        semantic_delta_literal: str,
        topo_delta_literal: str,
    ) -> Optional[List[str]]:
        return emit_native_node(
            self,
            node,
            var_name=var_name,
            object_name=object_name,
            tags_literal=tags_literal,
            context_literal=context_literal,
            param_exprs_literal=param_exprs_literal,
            semantic_delta_literal=semantic_delta_literal,
            topo_delta_literal=topo_delta_literal,
        )

    def _node_optional_payload(self, node: OperationNode, attr: str) -> Dict[str, Any]:
        value = getattr(node, attr)
        if value is None:
            return {}
        if hasattr(value, "created"):
            return {
                "created": [self._dataclass_ref_dict(ref) for ref in value.created],
                "modified": [self._dataclass_ref_dict(ref) for ref in value.modified],
                "deleted": [self._dataclass_ref_dict(ref) for ref in value.deleted],
                "metadata": dict(value.metadata),
            }
        return {
            "preserved": [self._dataclass_ref_dict(ref) for ref in value.preserved],
            "modified": [self._dataclass_ref_dict(ref) for ref in value.modified],
            "generated": [self._dataclass_ref_dict(ref) for ref in value.generated],
            "deleted": [self._dataclass_ref_dict(ref) for ref in value.deleted],
            "section_edges": [
                self._dataclass_ref_dict(ref) for ref in value.section_edges
            ],
            "entries": [
                {
                    "ref": self._dataclass_ref_dict(entry.ref),
                    "event": getattr(entry.event, "name", str(entry.event)),
                    "origin_role": entry.origin_role,
                    "parent_refs": [
                        self._dataclass_ref_dict(ref) for ref in entry.parent_refs
                    ],
                    "metadata": dict(entry.metadata),
                }
                for entry in value.entries
            ],
            "raw_event": dict(value.raw_event),
        }

    def _dataclass_ref_dict(self, ref: Any) -> Dict[str, Any]:
        if hasattr(ref, "__dict__"):
            payload = dict(ref.__dict__)
        else:  # a value of the native backend: its public fields
            payload = {
                name: getattr(ref, name)
                for name in dir(ref)
                if not name.startswith("_") and not callable(getattr(ref, name))
            }
        if "kind" in payload and hasattr(payload["kind"], "name"):
            payload["kind"] = payload["kind"].name
        return payload


class FreeCADTranslator(BaseTranslator):
    """Translate validated `.scadpkg` products into FreeCAD scripts."""

    def __init__(self, document_name: str = "SimpleCADProduct") -> None:
        self.document_name = str(document_name)

    @property
    def capabilities(self) -> BackendCapabilities:
        return CAPABILITIES

    def translate_model_json_to_script(self, json_str: str) -> str:
        return _FreeCADCompiler(self.document_name).translate_model_json_to_script(
            json_str
        )

    def translate_model_payload_to_script(
        self,
        payload: Dict[str, Any],
        *,
        graph: Optional[OperationGraph] = None,
    ) -> str:
        return _FreeCADCompiler(self.document_name).translate_model_payload_to_script(
            payload, graph=graph
        )

    def translate_model_json(self, json_str: str) -> TranslationArtifact:
        return TranslationArtifact(
            backend_id="freecad",
            target_id="freecad_script",
            media_type="text/x-python",
            suggested_suffix=".py",
            content=self.translate_model_json_to_script(json_str),
            metadata={"document_name": self.document_name},
        )

    def _translate_product_package_to_script(self, units: Any) -> str:
        if not units:
            raise ValueError("Product package contains no definition units")
        sections: List[str] = []
        for index, unit in enumerate(units):
            token = _safe_name(unit.definition_id, prefix="definition")
            compiler = _FreeCADCompiler(
                self.document_name,
                expression_sheet_name=f"SimpleCADExpressions_{token}",
                definition_token=token,
                definition_id=unit.definition_id,
                definition_kind=unit.definition_kind,
                definition_revision=unit.revision,
                definition_content_hash=unit.content_hash,
            )
            sections.append(
                compiler.translate_model_payload_to_script(
                    unit.model_payload(),
                    graph=unit.graph,
                    include_preamble=index == 0,
                    include_runtime=index == 0,
                    finalize=index == len(units) - 1,
                    register_definition={
                        "definition_kind": unit.definition_kind,
                        "definition_id": unit.definition_id,
                        "revision": unit.revision,
                        "content_hash": unit.content_hash,
                    },
                )
            )
        return "\n".join(section.rstrip() for section in sections) + "\n"

    def translate_product_package(
        self,
        data: Any,
        **_options: Any,
    ) -> TranslationArtifact:
        from ..package_units import read_product_package_translation_units

        package, units = read_product_package_translation_units(data)
        return TranslationArtifact(
            backend_id="freecad",
            target_id="freecad_script",
            media_type="text/x-python",
            suggested_suffix=".py",
            content=self._translate_product_package_to_script(units),
            metadata={
                "document_name": self.document_name,
                "root_definition_id": package.root_definition.definition_id,
                "root_definition_kind": package.root_definition.definition_kind,
                "definition_ids": tuple(unit.definition_id for unit in units),
                "target_runtime_validated": False,
            },
        )


__all__ = ["FreeCADTranslator"]
