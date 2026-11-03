// The guidance text of every guarded product operator: the Python operator's operation name,
// what happened, possible causes and how to fix.
#include <map>

#include "scad/product/guard.hpp"

namespace scad::product {

namespace {

using Specs = std::map<std::string, ErrorSpec, std::less<>>;

void add(Specs& specs, ErrorSpec spec) {
  const std::string name = spec.operation;
  specs.emplace(name, std::move(spec));
}

void add_structure(Specs& s) {
  add(s,
      {"make_material_rmaterial",
       "Failed to create the material definition.",
       {"The material_id is empty or uses unsupported characters.",
        "The density is non-finite, non-positive, or missing a density_unit.",
        "The color is not a 3-tuple in the [0.0, 1.0] range."},
       {"Use a stable identifier such as 'aluminum_6061'.", "Provide density and density_unit together, or omit both.",
        "Pass RGB color components as floats between 0.0 and 1.0."}});
  add(s, {"make_placement_rplacement",
          "Failed to create the placement.",
          {"The origin is not a finite 3D point.", "One of the axes is zero-length or non-finite.",
           "x_axis and y_axis are not orthogonal."},
          {"Pass origin, x_axis, and y_axis as finite 3-element tuples.",
           "Use one canonical representation; do not mix Euler, quaternion, or axis-angle payloads.",
           "Make sure x_axis and y_axis form a right-handed frame."}});
  add(s, {"identity_placement_rplacement",
          "Failed to create the identity placement.",
          {"Internal placement validation failed."},
          {"Report this as a SimpleCADAPI bug if it reproduces."}});
  add(s, {"make_part_rpart",
          "Failed to create the single-body Part.",
          {"The part_id is empty or uses unsupported characters.", "The body is not a Solid.",
           "A Part with the same part_id already exists in the active GraphSession."},
          {"Pass a stable part_id such as 'base_plate'.",
           "Union intended multiple bodies into one Solid before creating the Part.",
           "Do not pass material to make_part_rpart; use assign_material_rpart instead."}});
  add(s, {"assign_material_rpart",
          "Failed to assign the material to the Part.",
          {"The part input is not a Part.", "The material input is not a Material."},
          {"Create parts with make_part_rpart(...).", "Create materials with make_material_rmaterial(...)."}});
  add(s, {"make_assembly_rassembly",
          "Failed to create the assembly.",
          {"The assembly_id is empty or uses unsupported characters.",
           "An Assembly with the same assembly_id already exists in the active GraphSession."},
          {"Pass a stable assembly_id such as 'fixture_assembly'."}});
  add(s, {"add_component_rassembly",
          "Failed to add the component to the assembly.",
          {"The assembly input is not an Assembly.", "The item input is not a Part or Assembly.",
           "The component_id is empty, malformed, or duplicated in the assembly.",
           "The placement is invalid or missing.", "Adding this subassembly would create an assembly cycle."},
          {"Wrap solids explicitly with make_part_rpart before adding them to assemblies.",
           "Use a unique component_id within the parent assembly.",
           "Create placements with make_placement_rplacement or identity_placement_rplacement."}});
  add(s, {"place_component_rassembly",
          "Failed to place the assembly component.",
          {"The assembly input is not an Assembly.", "The component_id does not exist in the assembly.",
           "The placement is invalid or missing."},
          {"Use add_component_rassembly before placing a component.",
           "Use a component_id returned in assembly.component_ids().",
           "Create placements with make_placement_rplacement."}});
}

void add_connectors(Specs& s) {
  add(s, {"make_face_connector_rconnector",
          "Failed to create the face connector.",
          {"The connector_id is empty or malformed.", "The face is not a valid Face object."},
          {"Use a stable connector_id such as 'mount_face'.",
           "Select a face via ql.faces().where(...).resolve(solid), or an indexed pick solid.get_faces(index)."}});
  add(s, {"make_edge_connector_rconnector",
          "Failed to create the edge connector.",
          {"The connector_id is empty or malformed.", "The edge is not a valid Edge object."},
          {"Use a stable connector_id such as 'hinge_axis'.",
           "Select an edge via ql.edges().where(...).resolve(solid), or an indexed pick solid.get_edges(index)."}});
  add(s,
      {"make_vertex_connector_rconnector",
       "Failed to create the vertex connector.",
       {"The connector_id is empty or malformed.", "The vertex is not a valid Vertex object."},
       {"Use a stable connector_id such as 'pivot_point'.",
        "Select a vertex via ql.vertices().where(...).resolve(solid), or an indexed pick solid.get_vertices(index)."}});
  add(s, {"make_placement_connector_rconnector",
          "Failed to create the placement connector.",
          {"The connector_id is empty or malformed.", "The placement input is not a Placement."},
          {"Create placements with make_placement_rplacement.", "Use a stable connector_id such as 'bearing_axis'."}});
  add(s, {"add_connector_rpart",
          "Failed to add the connector to the Part.",
          {"The part input is not a Part.", "The connector input is not a Connector.",
           "The connector_id is duplicated in the Part."},
          {"Create a connector with make_face_connector_rconnector, make_edge_connector_rconnector, or "
           "make_vertex_connector_rconnector.",
           "Use unique connector ids within one Part."}});
  add(s, {"set_public_connector_rassembly",
          "Failed to expose the component connector publicly.",
          {"The assembly input is not an Assembly.", "The component is not a direct child of the Assembly.",
           "The connector does not exist on the child component.",
           "The public connector ID is already used in the Assembly."},
          {"Add the direct child component before exposing its connector.",
           "Create the connector on the child Part or expose it on the child Assembly first.",
           "Expose each public connector ID at most once per Assembly."}});
  add(s, {"make_connector_ref_rconnectorref",
          "Failed to create the connector reference.",
          {"The component_id or connector_id is empty or malformed."},
          {"Use stable ids from the owning Assembly and component item."}});
  add(s, {"make_scalar_limit_rscalarlimit",
          "Failed to create the scalar limit.",
          {"One of the limit values is non-finite.", "lower_value is greater than upper_value."},
          {"Pass finite lower and upper values in increasing order."}});
}

void add_constraints(Specs& s) {
  add(s, {"ground_component_rassembly",
          "Failed to ground the assembly component.",
          {"The assembly input is not an Assembly.", "The component_id does not exist in the Assembly."},
          {"Use a component_id already added to the Assembly."}});
  add(s, {"unground_component_rassembly",
          "Failed to unground the assembly component.",
          {"The assembly input is not an Assembly.", "The component_id does not exist in the Assembly."},
          {"Use a component_id already added to the Assembly."}});
  for (const char* name :
       {"add_fixed_constraint_rassembly", "add_revolute_constraint_rassembly", "add_prismatic_constraint_rassembly",
        "add_gear_constraint_rassembly", "add_belt_constraint_rassembly", "add_rack_pinion_constraint_rassembly"}) {
    add(s, {name,
            "Failed to add the assembly constraint.",
            {"The assembly input is not an Assembly.", "A connector ref references a missing component or connector.",
             "The constraint_id is duplicated in the Assembly.", "A drive value violates its scalar limit."},
            {"Create connector refs with make_connector_ref_rconnectorref.",
             "Add connectors to Parts or Assemblies before adding constrained components.",
             "Use unique constraint ids within one Assembly."}});
  }
  add(s, {"solve_assembly_constraints_rassembly",
          "Failed to solve the assembly constraints.",
          {"No component is grounded.", "A constraint graph references missing connectors.",
           "A connected component cannot be reached from a grounded component.",
           "A closed-loop residual exceeds tolerance."},
          {"Ground at least one component with ground_component_rassembly.",
           "Ensure every constrained component has the required connectors.",
           "Inspect constraint residuals before strict solving."}});
  add(s,
      {"make_compound_from_assembly_rcompound",
       "Failed to project the assembly into a Compound.",
       {"The input is not an Assembly.", "The assembly has no components.", "A component placement is invalid.",
        "The kernel could not transform or combine the component bodies."},
       {"Create an assembly with make_assembly_rassembly and add at least one component.",
        "Ensure every component references a valid Part or subassembly.", "Validate placements before projection."}});
}

const Specs& specs() {
  static const Specs table = [] {
    Specs s;
    add_structure(s);
    add_connectors(s);
    add_constraints(s);
    return s;
  }();
  return table;
}

}  // namespace

const ErrorSpec& operator_spec(std::string_view operation) {
  const auto found = specs().find(operation);
  if (found == specs().end())
    throw LookupError("no error guidance for operation '" + std::string(operation) + "'");
  return found->second;
}

void raise_operation_error(std::string_view operation, const std::exception& error) {
  const ErrorSpec& spec = operator_spec(operation);
  if (dynamic_cast<const reactive::KeyError*>(&error) != nullptr) {
    raise_harness_error(spec, "KeyError: " + python_repr(error.what()));
  }
  raise_harness_error(spec, error);
}

}  // namespace scad::product
