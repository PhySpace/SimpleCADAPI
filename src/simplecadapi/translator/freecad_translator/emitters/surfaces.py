"""FreeCAD emitters for canonical surface and shell operations."""

from __future__ import annotations

from typing import List, Optional

from simplecadapi._cpp import OperationNode
from ..codegen import *


_FIT_POINT_GRID_EMULATION = (
    "FreeCAD approximates the point grid with its native BSplineSurface fitter; "
    "when that fitter rejects a small grid, translation falls back to exact grid interpolation."
)
_CYLINDRICAL_SURFACE_EMULATION = (
    "FreeCAD reconstructs the bounded carrier from a native partial cylinder and "
    "retains its cylindrical side face."
)
_GORDON_EMULATION = (
    "FreeCAD has no native Gordon curve-network builder. Translation interpolates a "
    "BSpline surface through the unique profile-guide intersection grid; the surface "
    "passes through the network intersections but does not reproduce every source curve exactly."
)
_SURFACE_PATCH_EMULATION = (
    "FreeCAD has no native equivalent for the full SimpleCAD constrained filling contract. "
    "Translation fills the boundary edges and preserves hole trims; support-face continuity, "
    "interior constraint points, and detailed filling settings are not parametrically mapped."
)
_TRIM_SURFACE_EMULATION = (
    "FreeCAD rebuilds the carrier trim loops and intersects them with the existing "
    "carrier bounds."
)
_FREE_BOUNDARIES_EMULATION = (
    "FreeCAD exposes no direct free-boundary operation. Translation reconstructs boundary "
    "wires from shell edges referenced by exactly one face."
)
_FILL_HOLES_EMULATION = (
    "FreeCAD fills selected closed free-boundary wires with native filled faces and sews them "
    "back to the shell; detailed SimpleCAD filling settings are not parametrically mapped."
)
_SOLID_FROM_SHELL_EMULATION = (
    "FreeCAD converts the validated closed shell to a Part solid while preserving "
    "the source faces."
)


class SurfaceEmitterMixin:
    def _emit_surfaces(
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
        if self._source_graph is None:
            return None

        rp = f"{var_name}_params"
        inputs = [inp.node_id for inp in node.inputs]
        register_args = (
            f"node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, "
            f"params={rp}, inputs={var_name}_inputs, tags={tags_literal}, "
            f"context={context_literal}, output_count={node.output_count}, "
            f"param_exprs={param_exprs_literal}, semantic_delta={semantic_delta_literal}, "
            f"topo_delta={topo_delta_literal}"
        )

        if node.op == "make_bezier_surface_rface":
            return [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _bezier_surface_shape({rp}, {context_literal}), {register_args})"
            ]
        if node.op == "make_cylindrical_surface_rface":
            return [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _cylindrical_surface_shape({rp}, {context_literal}), {register_args})",
                f"_mark_emulated_translation({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, reason={_json_ascii(_CYLINDRICAL_SURFACE_EMULATION)})",
            ]
        if node.op == "fit_point_grid_rface":
            return [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _fit_point_grid_surface_shape({rp}, {context_literal}), {register_args})",
                f"_mark_emulated_translation({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, reason={_json_ascii(_FIT_POINT_GRID_EMULATION)})",
            ]
        if node.op == "make_ruled_surface_rface":
            return [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _ruled_surface_shape({rp}, {var_name}_inputs), {register_args})"
            ]
        if node.op == "make_gordon_surface_rface":
            return [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _gordon_surface_shape({rp}, {var_name}_inputs), {register_args})",
                f"_mark_emulated_translation({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, reason={_json_ascii(_GORDON_EMULATION)})",
            ]
        if node.op == "make_surface_patch_rface":
            return [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _surface_patch_shape({rp}, {var_name}_inputs, {context_literal}), {register_args})",
                f"_mark_emulated_translation({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, reason={_json_ascii(_SURFACE_PATCH_EMULATION)})",
            ]
        if node.op == "trim_surface_rface":
            return [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _trim_surface_shape({rp}, {var_name}_inputs), {register_args})",
                f"_mark_emulated_translation({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, reason={_json_ascii(_TRIM_SURFACE_EMULATION)})",
            ]
        if node.op == "make_loft_rshell":
            return [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _loft_shell_shape({rp}, {var_name}_inputs), {register_args})"
            ]
        if node.op == "sew_faces_rshell":
            return [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _sew_faces_shell_shape({rp}, {var_name}_inputs), {register_args})"
            ]
        if node.op == "make_solid_from_shell_rsolid":
            return [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _solid_from_shell_shape({rp}, {var_name}_inputs), {register_args})",
                f"_mark_emulated_translation({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, reason={_json_ascii(_SOLID_FROM_SHELL_EMULATION)})",
            ]
        if node.op == "free_boundaries_rwirelist":
            return [
                f"{var_name} = _register_shape_list_features({_json_ascii(object_name)}, _free_boundary_shapes({rp}, {var_name}_inputs), {register_args})",
                f"_mark_graph_outputs_emulated(node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, reason={_json_ascii(_FREE_BOUNDARIES_EMULATION)})",
            ]
        if node.op == "fill_holes_rshell":
            return [
                f"{var_name} = _make_feature({_json_ascii(object_name)}, _fill_holes_shell_shape({rp}, {var_name}_inputs), {register_args})",
                f"_mark_emulated_translation({var_name}, node_id={_json_ascii(node.node_id)}, op={_json_ascii(node.op)}, reason={_json_ascii(_FILL_HOLES_EMULATION)})",
            ]
        return None


__all__ = ["SurfaceEmitterMixin"]
