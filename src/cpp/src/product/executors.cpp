#include "scad/product/executors.hpp"

#include <vector>

namespace scad::product {

void register_product_executors(reactive::ExecutorRegistry& registry) {
  static constexpr const char* kValueOperations[] = {
      "make_material_rmaterial",
      "make_placement_rplacement",
      "make_identity_placement_rplacement",
      "make_part_rpart",
      "make_assign_material_rpart",
      "make_assembly_rassembly",
      "make_add_component_rassembly",
      "make_place_component_rassembly",
      "make_face_connector_rconnector",
      "make_edge_connector_rconnector",
      "make_vertex_connector_rconnector",
      "make_placement_connector_rconnector",
      "make_add_connector_rpart",
      "make_set_public_connector_rassembly",
      "make_connector_ref_rconnectorref",
      "make_scalar_limit_rscalarlimit",
      "make_ground_component_rassembly",
      "make_unground_component_rassembly",
      "make_fixed_constraint_rassembly",
      "make_revolute_constraint_rassembly",
      "make_prismatic_constraint_rassembly",
      "make_gear_constraint_rassembly",
      "make_belt_constraint_rassembly",
      "make_rack_pinion_constraint_rassembly",
      "make_solve_assembly_constraints_rassembly",
  };
  for (const char* operation : kValueOperations) {
    registry.add(operation, [](const Value&, const std::vector<OpInput>&, const reactive::ScalarValues&) {
      return std::vector<Shape>{};
    });
  }
}

}  // namespace scad::product
