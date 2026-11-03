// The product operators (simplecadapi/operators/product.py): parts, materials, assemblies,
// connectors, constraints, solving, and the flattened Compound projection.
//
// Same names, arguments and defaults as the Python operators.  Operators that take a number the
// Python code reads with float() take a Scalar: a Var / Expr argument is evaluated, as float(Var)
// does.  A failure is a scad::Error carrying the Python operation name and guidance, except where
// Python does not wrap it either (building the Constraint of an add_*_constraint operator,
// measure / inspect): those raise the plain ValueError / TypeError.
//
// Each operator records itself when a recorder is installed.  The recorded operations produce
// product values rather than shapes (only make_compound_from_assembly_rcompound has a shape output),
// so their executors (executors.hpp) have nothing to rebuild.
#pragma once

#include <map>
#include <optional>
#include <string>

#include "scad/core/scalar.hpp"
#include "scad/ops/geometry/types.hpp"
#include "scad/product/assembly.hpp"
#include "scad/product/connector.hpp"
#include "scad/product/constraint.hpp"
#include "scad/product/material.hpp"
#include "scad/product/part.hpp"
#include "scad/product/placement.hpp"
#include "scad/topo/shape.hpp"

namespace scad::product {

// ---- materials, placements, parts -----------------------------------------------------------------
Material make_material_rmaterial(const std::string& material_id, const OptionalString& name = {},
                                 const std::optional<Scalar>& density = {}, const OptionalString& density_unit = {},
                                 const std::optional<Vec3>& color = {});

// A placement in the active workplane (the arguments are given in its coordinates).
Placement make_placement_rplacement(const Scalar3& origin, const Scalar3& x_axis = scalar3(1, 0, 0),
                                    const Scalar3& y_axis = scalar3(0, 1, 0));
Placement identity_placement_rplacement();

PartPtr make_part_rpart(const std::string& part_id, const Solid& body, const OptionalString& name = {});
// A Part of several named bodies, kept apart (no boolean between them), in this order.
PartPtr make_part_rpart(const std::string& part_id, const std::vector<Body>& bodies, const OptionalString& name = {});
PartPtr assign_material_rpart(const Part& part, const Material& material);

// ---- connectors -------------------------------------------------------------------------------------
// Z follows the face normal, the origin is the face center; `flip` negates Z.
Connector make_face_connector_rconnector(const std::string& connector_id, const Face& face,
                                         const OptionalString& name = {}, bool flip = false);
// Z follows the edge direction (start to end), the origin is the edge midpoint.
Connector make_edge_connector_rconnector(const std::string& connector_id, const Edge& edge,
                                         const OptionalString& name = {}, bool flip = false);
// The origin is the vertex; the axes are the identity (`flip` has no effect).
Connector make_vertex_connector_rconnector(const std::string& connector_id, const Vertex& vertex,
                                           const OptionalString& name = {}, bool flip = false);
Connector make_placement_connector_rconnector(const std::string& connector_id, const Placement& placement,
                                              const OptionalString& name = {});
PartPtr add_connector_rpart(const Part& part, const Connector& connector);

ConnectorRef make_connector_ref_rconnectorref(const std::string& component_id, const std::string& connector_id);
ScalarLimit make_scalar_limit_rscalarlimit(const Scalar& lower_value, const Scalar& upper_value);

// ---- assemblies ---------------------------------------------------------------------------------------
AssemblyPtr make_assembly_rassembly(const std::string& assembly_id, const OptionalString& name = {});
AssemblyPtr add_component_rassembly(const Assembly& assembly, const Item& item, const std::string& component_id,
                                    const Placement& placement, const OptionalString& name = {});
AssemblyPtr place_component_rassembly(const Assembly& assembly, const std::string& component_id,
                                      const Placement& placement);
// An exploded view: a new assembly whose component placements are pushed apart, as a pure function of `assembly`
// (parts, constraints, grounding and public connectors are untouched).  Each component moves by
//   factor * weight * direction * size
// where `size` is the diagonal of the box that holds every component's bodies, `weight` is weights[id] (default 1; a
// component listed with 0 stays) and `direction` is, in this order: directions[id] (normalised); else `axis`, signed by
// the side of the centre the component is on (a component on the centre plane has no direction and stays); else the
// vector from the centre to the component's own centre.  The centre is `center`, else the centre of the box of all the
// components; a component's centre is the centre of the box of its bodies (its origin when it holds none).  A component
// with no direction stays and is listed in metadata "explode".  factor 0 gives the same placements.  The result is for
// display, rendering and export: its component frames (and so its connector frames) move together, but the constraints
// are not re-solved and solving the result moves everything back.  Metadata "explode" holds factor, size, centre, the
// displacement of every component and the ones that stayed.
AssemblyPtr explode_rassembly(const Assembly& assembly, const Scalar& factor, const std::optional<Vec3>& center = {},
                              const std::optional<Vec3>& axis = {}, const std::map<std::string, Vec3>& directions = {},
                              const std::map<std::string, double>& weights = {});
AssemblyPtr set_public_connector_rassembly(const Assembly& assembly, const std::string& public_connector_id,
                                           const std::string& source_component_id,
                                           const std::string& source_connector_id, const OptionalString& name = {});
AssemblyPtr ground_component_rassembly(const Assembly& assembly, const std::string& component_id);
AssemblyPtr unground_component_rassembly(const Assembly& assembly, const std::string& component_id);

// ---- constraints --------------------------------------------------------------------------------------
using OptionalScalar = std::optional<Scalar>;
using OptionalLimit = std::optional<ScalarLimit>;

AssemblyPtr add_fixed_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                           const ConnectorRef& connector_a, const ConnectorRef& connector_b,
                                           const OptionalString& name = {});
AssemblyPtr add_revolute_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                              const ConnectorRef& connector_a, const ConnectorRef& connector_b,
                                              const OptionalScalar& drive_angle_degrees = {},
                                              const OptionalLimit& angle_limit = {}, const OptionalString& name = {});
AssemblyPtr add_prismatic_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                               const ConnectorRef& connector_a, const ConnectorRef& connector_b,
                                               const OptionalScalar& drive_distance = {},
                                               const OptionalLimit& distance_limit = {},
                                               const OptionalString& name = {});
// Couple two revolute axes as meshing gears (inverse rotation).  Without a phase_offset the
// current relative angles define it.
AssemblyPtr add_gear_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                          const ConnectorRef& connector_a, const ConnectorRef& connector_b,
                                          const Scalar& pitch_radius_a, const Scalar& pitch_radius_b,
                                          const OptionalScalar& phase_offset = {}, const OptionalString& name = {});
// Couple two revolute axes as belt-linked pulleys (same-direction rotation).
AssemblyPtr add_belt_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                          const ConnectorRef& connector_a, const ConnectorRef& connector_b,
                                          const Scalar& pulley_radius_a, const Scalar& pulley_radius_b,
                                          const OptionalScalar& phase_offset = {}, const OptionalString& name = {});
// Couple a prismatic rack axis to a revolute pinion axis.
AssemblyPtr add_rack_pinion_constraint_rassembly(const Assembly& assembly, const std::string& constraint_id,
                                                 const ConnectorRef& rack_connector,
                                                 const ConnectorRef& pinion_connector, const Scalar& pitch_radius,
                                                 const OptionalScalar& phase_offset = {},
                                                 const OptionalString& name = {});

// ---- solving and inspecting -----------------------------------------------------------------------------
AssemblyPtr solve_assembly_constraints_rassembly(const AssemblyPtr& assembly, bool strict = true);
ConstraintResidual measure_constraint_residual_rconstraintresidual(const Assembly& assembly,
                                                                   const std::string& constraint_id);
ConstraintReport inspect_assembly_constraints_rconstraintreport(const Assembly& assembly);

// ---- projection -----------------------------------------------------------------------------------------
// Every Part body placed through its component chain, as one Compound.
Compound make_compound_from_assembly_rcompound(const Assembly& assembly);

}  // namespace scad::product
