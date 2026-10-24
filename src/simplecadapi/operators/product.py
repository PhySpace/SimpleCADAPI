"""Operators of the ``product`` group.

Forwarding module: nothing is defined here.  The names below are implemented in C++ and re-exported under the
import path the SDK has always had.

Where to read the source (``src/cpp/bindings/python/<file>.cpp`` declares the Python name, the implementation
is behind it):
  * ``bind_product.cpp`` -> ``src/cpp/src/product``
"""

from __future__ import annotations

from simplecadapi._cpp import (
    # bind_product.cpp
    add_belt_constraint_rassembly,
    add_component_rassembly,
    add_connector_rpart,
    add_fixed_constraint_rassembly,
    add_gear_constraint_rassembly,
    add_prismatic_constraint_rassembly,
    add_rack_pinion_constraint_rassembly,
    add_revolute_constraint_rassembly,
    assign_material_rpart,
    ground_component_rassembly,
    identity_placement_rplacement,
    inspect_assembly_constraints_rconstraintreport,
    make_assembly_rassembly,
    make_compound_from_assembly_rcompound,
    make_connector_ref_rconnectorref,
    make_edge_connector_rconnector,
    make_face_connector_rconnector,
    make_material_rmaterial,
    make_part_rpart,
    make_placement_connector_rconnector,
    make_placement_rplacement,
    make_scalar_limit_rscalarlimit,
    make_vertex_connector_rconnector,
    measure_constraint_residual_rconstraintresidual,
    place_component_rassembly,
    set_public_connector_rassembly,
    solve_assembly_constraints_rassembly,
    unground_component_rassembly,
)

__all__ = [
    "add_belt_constraint_rassembly",
    "add_component_rassembly",
    "add_connector_rpart",
    "add_fixed_constraint_rassembly",
    "add_gear_constraint_rassembly",
    "add_prismatic_constraint_rassembly",
    "add_rack_pinion_constraint_rassembly",
    "add_revolute_constraint_rassembly",
    "assign_material_rpart",
    "ground_component_rassembly",
    "identity_placement_rplacement",
    "inspect_assembly_constraints_rconstraintreport",
    "make_assembly_rassembly",
    "make_compound_from_assembly_rcompound",
    "make_connector_ref_rconnectorref",
    "make_edge_connector_rconnector",
    "make_face_connector_rconnector",
    "make_material_rmaterial",
    "make_part_rpart",
    "make_placement_connector_rconnector",
    "make_placement_rplacement",
    "make_scalar_limit_rscalarlimit",
    "make_vertex_connector_rconnector",
    "measure_constraint_residual_rconstraintresidual",
    "place_component_rassembly",
    "set_public_connector_rassembly",
    "solve_assembly_constraints_rassembly",
    "unground_component_rassembly",
]
