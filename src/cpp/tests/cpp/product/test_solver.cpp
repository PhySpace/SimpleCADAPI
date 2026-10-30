// The constraint solver: propagation, limits, couplings, nesting, and its structured failures.
#include <cmath>

#include "support.hpp"

using namespace scad::product_test;

namespace {

double z_angle_degrees(const Placement& placement) {
  return std::atan2(placement.x_axis().y, placement.x_axis().x) * 180.0 / kPi;
}

// base grounded at the origin plus one more component, joined by `joint`.
AssemblyPtr pair_with(const PartPtr& part, const std::string& other) {
  AssemblyPtr assembly = make_assembly_rassembly("pair");
  assembly = with_component(assembly, part, "base");
  assembly = with_component(assembly, part, other);
  return ground_component_rassembly(*assembly, "base");
}

}  // namespace

TEST_CASE("a fixed constraint moves the follower onto the base connector") {
  const PartPtr part = part_with_axis("p");
  AssemblyPtr assembly = make_assembly_rassembly("fixed_asm");
  assembly = with_component(assembly, part, "base", at(1, 2, 3));
  assembly = with_component(assembly, part, "follower");
  assembly = ground_component_rassembly(*assembly, "base");
  assembly = add_fixed_constraint_rassembly(*assembly, "fixed", ref("base"), ref("follower"));

  const AssemblyPtr solved = solve_assembly_constraints_rassembly(assembly);
  CHECK(solved->get_component("follower").placement.origin() == Vec3{1, 2, 3});
  CHECK(measure_constraint_residual_rconstraintresidual(*solved, "fixed").within_tolerance);
  const Value report = solved->get_runtime("constraint_report");
  CHECK(report.find("solved")->as_bool());
  // The authored placements ride along.
  CHECK(solved->get_runtime("assembly.authored_component_placements").find("follower") != nullptr);
}

TEST_CASE("a revolute drive angle turns the arm about the connector z") {
  AssemblyPtr assembly = pair_with(part_with_axis("p"), "arm");
  assembly = add_revolute_constraint_rassembly(*assembly, "hinge", ref("base"), ref("arm"), 90.0);
  const AssemblyPtr solved = solve_assembly_constraints_rassembly(assembly);
  const Placement arm = solved->get_component("arm").placement;
  check_vec(arm.origin(), {0, 0, 0});
  check_vec(arm.x_axis(), {0, 1, 0});
}

TEST_CASE("a prismatic drive distance slides the follower along z") {
  AssemblyPtr assembly = pair_with(part_with_axis("p"), "slider");
  assembly = add_prismatic_constraint_rassembly(*assembly, "slide", ref("base"), ref("slider"), 5.0);
  const AssemblyPtr solved = solve_assembly_constraints_rassembly(assembly);
  CHECK(solved->get_component("slider").placement.origin() == Vec3{0, 0, 5});
  CHECK(inspect_assembly_constraints_rconstraintreport(*solved).solved);
}

TEST_CASE("limits clamp a drive scalar into the closed range") {
  AssemblyPtr assembly = pair_with(part_with_axis("p"), "slider");
  assembly = add_prismatic_constraint_rassembly(*assembly, "slide", ref("base"), ref("slider"), 100.0,
                                                make_scalar_limit_rscalarlimit(0.0, 5.0));
  CHECK(solve_assembly_constraints_rassembly(assembly)->get_component("slider").placement.origin() == Vec3{0, 0, 5});

  AssemblyPtr inside = pair_with(part_with_axis("p2"), "slider");
  inside = add_prismatic_constraint_rassembly(*inside, "slide", ref("base"), ref("slider"), 3.0,
                                              make_scalar_limit_rscalarlimit(0.0, 10.0));
  CHECK(solve_assembly_constraints_rassembly(inside)->get_component("slider").placement.origin() == Vec3{0, 0, 3});

  AssemblyPtr revolute = pair_with(part_with_axis("p3"), "arm");
  revolute = add_revolute_constraint_rassembly(*revolute, "hinge", ref("base"), ref("arm"), 999.0,
                                               make_scalar_limit_rscalarlimit(0.0, 45.0));
  const Placement arm = solve_assembly_constraints_rassembly(revolute)->get_component("arm").placement;
  CHECK(z_angle_degrees(arm) == doctest::Approx(45.0).epsilon(1e-9));
}

TEST_CASE("without a drive the current relative scalar is projected into the limit") {
  const PartPtr part = part_with_axis("p");
  AssemblyPtr assembly = make_assembly_rassembly("loop");
  assembly = with_component(assembly, part, "link1", at(0, 0, 2));
  assembly = with_component(assembly, part, "movable");
  assembly = ground_component_rassembly(*assembly, "link1");
  assembly = add_prismatic_constraint_rassembly(*assembly, "slide", ref("link1"), ref("movable"), std::nullopt,
                                                make_scalar_limit_rscalarlimit(-5.0, 5.0));
  const AssemblyPtr solved = solve_assembly_constraints_rassembly(assembly, false);
  CHECK(measure_constraint_residual_rconstraintresidual(*solved, "slide").within_tolerance);
}

TEST_CASE("gear and belt couplings set the free joint from the driven one") {
  const PartPtr part = part_with_axis("rotor");
  const auto build = [&](bool belt) {
    AssemblyPtr assembly = make_assembly_rassembly(belt ? "belt_asm" : "gear_asm");
    for (const char* id : {"base", "gear_a", "gear_b"})
      assembly = with_component(assembly, part, id);
    assembly = ground_component_rassembly(*assembly, "base");
    assembly = add_revolute_constraint_rassembly(*assembly, "drive_a", ref("base"), ref("gear_a"), 90.0);
    assembly = add_revolute_constraint_rassembly(*assembly, "free_b", ref("base"), ref("gear_b"));
    assembly = belt ? add_belt_constraint_rassembly(*assembly, "mesh", ref("gear_a"), ref("gear_b"), 1.0, 2.0)
                    : add_gear_constraint_rassembly(*assembly, "mesh", ref("gear_a"), ref("gear_b"), 1.0, 2.0);
    return solve_assembly_constraints_rassembly(assembly);
  };
  const AssemblyPtr gear = build(false);
  CHECK(z_angle_degrees(gear->get_component("gear_b").placement) == doctest::Approx(-45.0).epsilon(1e-9));
  CHECK(measure_constraint_residual_rconstraintresidual(*gear, "mesh").within_tolerance);
  const AssemblyPtr belt = build(true);
  CHECK(z_angle_degrees(belt->get_component("gear_b").placement) == doctest::Approx(45.0).epsilon(1e-9));
  CHECK(measure_constraint_residual_rconstraintresidual(*belt, "mesh").within_tolerance);
}

TEST_CASE("a rack-pinion coupling turns the pinion angle into rack travel") {
  const PartPtr part = part_with_axis("rp");
  AssemblyPtr assembly = make_assembly_rassembly("rack_pinion_asm");
  for (const char* id : {"base", "rack", "pinion"})
    assembly = with_component(assembly, part, id);
  assembly = ground_component_rassembly(*assembly, "base");
  assembly = add_prismatic_constraint_rassembly(*assembly, "rack_slide", ref("base"), ref("rack"));
  assembly = add_revolute_constraint_rassembly(*assembly, "pinion_axis", ref("base"), ref("pinion"), 90.0);
  assembly = add_rack_pinion_constraint_rassembly(*assembly, "rack_mesh", ref("rack"), ref("pinion"), 2.0);
  const AssemblyPtr solved = solve_assembly_constraints_rassembly(assembly);
  CHECK(solved->get_component("rack").placement.origin().z == doctest::Approx(-kPi).epsilon(1e-9));
  CHECK(measure_constraint_residual_rconstraintresidual(*solved, "rack_mesh").within_tolerance);
}

TEST_CASE("a coupling's omitted phase offset is the current relative phase") {
  const PartPtr part = part_with_axis("rotor");
  AssemblyPtr assembly = make_assembly_rassembly("phase");
  for (const char* id : {"base", "a", "b"})
    assembly = with_component(assembly, part, id);
  assembly = ground_component_rassembly(*assembly, "base");
  assembly = add_revolute_constraint_rassembly(*assembly, "ja", ref("base"), ref("a"), 30.0);
  assembly = add_revolute_constraint_rassembly(*assembly, "jb", ref("base"), ref("b"));
  const AssemblyPtr solved = solve_assembly_constraints_rassembly(assembly);
  const AssemblyPtr coupled = add_gear_constraint_rassembly(*solved, "mesh", ref("a"), ref("b"), 1.0, 1.0);
  const double expected =
      1.0 * 30.0 * kPi / 180.0 + 1.0 * z_angle_degrees(solved->get_component("b").placement) * kPi / 180.0;
  CHECK(*coupled->get_constraint("mesh").phase_offset() == doctest::Approx(expected).epsilon(1e-9));
  CHECK(coupling_phase_offset(*solved, coupled->get_constraint("mesh")) == doctest::Approx(expected).epsilon(1e-9));
  CHECK_THROWS_AS(coupling_phase_offset(*solved, solved->get_constraint("ja")), ValueError);
}

TEST_CASE("coupling constructor errors are not wrapped, like Python") {
  const PartPtr part = part_with_axis("p");
  AssemblyPtr assembly = with_component(with_component(make_assembly_rassembly("a"), part, "a"), part, "b");
  CHECK_THROWS_WITH_AS(add_gear_constraint_rassembly(*assembly, "g", ref("a"), ref("b"), 0.0, 1.0),
                       "pitch_radius_a must be positive", ValueError);
  CHECK_THROWS_WITH_AS(add_belt_constraint_rassembly(*assembly, "b", ref("a"), ref("b"), 1.0, -1.0),
                       "pulley_radius_b must be positive", ValueError);
  CHECK_THROWS_WITH_AS(add_rack_pinion_constraint_rassembly(*assembly, "r", ref("a"), ref("b"), 0.0),
                       "pitch_radius must be positive", ValueError);
}

TEST_CASE("a constraint on a missing connector is rejected with the operator's guidance") {
  const PartPtr part = part_with_axis("p");
  AssemblyPtr assembly = with_component(with_component(make_assembly_rassembly("a"), part, "base"), part, "slider");
  const auto error =
      failure_of([&] { add_fixed_constraint_rassembly(*assembly, "m", ref("base"), ref("slider", "missing_axis")); });
  REQUIRE(error);
  CHECK(error->operation() == "add_fixed_constraint_rassembly");
  CHECK(error->guidance().technical_details == "KeyError: \"part has no connector_id 'missing_axis'\"");
}

TEST_CASE("solving without a grounded component fails") {
  const PartPtr part = part_with_axis("p");
  AssemblyPtr assembly = with_component(with_component(make_assembly_rassembly("u"), part, "base"), part, "slider");
  assembly = add_prismatic_constraint_rassembly(*assembly, "slide", ref("base"), ref("slider"), 1.0);
  const auto error = failure_of([&] { solve_assembly_constraints_rassembly(assembly); });
  REQUIRE(error);
  CHECK(error->operation() == "solve_assembly_constraints_rassembly");
  CHECK(error->guidance().technical_details ==
        "ValueError: assembly constraints require at least one grounded component");
}

TEST_CASE("an assembly without constraints is returned as it is") {
  const AssemblyPtr assembly = with_component(make_assembly_rassembly("plain"), part_with_axis("p"), "only");
  CHECK(solve_assembly_constraints_rassembly(assembly) == assembly);
}

TEST_CASE("a residual failure carries the measured error and a worst-first repair") {
  const PartPtr base_part = [] {
    PartPtr part = part_with_axis("base_part");
    return add_connector_rpart(*part, make_placement_connector_rconnector("far", Placement(Vec3{15, 0, 0})));
  }();
  const PartPtr moving = part_with_axis("moving_part", {5, 0, 0});
  AssemblyPtr assembly = make_assembly_rassembly("residual_fixture");
  assembly = with_component(assembly, base_part, "base");
  assembly = with_component(assembly, moving, "moving");
  assembly = ground_component_rassembly(*assembly, "base");
  assembly = add_fixed_constraint_rassembly(*assembly, "hold", ref("base", "axis"), ref("moving", "axis"));
  assembly = add_fixed_constraint_rassembly(*assembly, "hold2", ref("base", "far"), ref("moving", "axis"));

  const auto error = failure_of([&] { solve_assembly_constraints_rassembly(assembly); });
  REQUIRE(error);
  const ErrorGuidance& guidance = error->guidance();
  CHECK(error->operation() == "solve_assembly_constraints");
  bool found = false;
  for (const ErrorMeasurement& m : guidance.measurements) {
    if (m.name == "hold2 translation error") {
      CHECK(std::get<double>(m.value) == doctest::Approx(15.0));
      found = true;
    }
  }
  CHECK(found);
  bool exceeded = false;
  for (const InventoryEntry& entry : guidance.inventory)
    exceeded = exceeded || (entry.symbol == "hold2" && entry.status == "exceeded");
  CHECK(exceeded);
  CHECK(guidance.repair.front().find("hold2") != std::string::npos);
  CHECK(std::string(error->what()).find("hold2 translation error: 15") != std::string::npos);

  // Not strict: the best effort comes back instead.
  CHECK_NOTHROW(solve_assembly_constraints_rassembly(assembly, false));
}

TEST_CASE("a structural failure lists the connectivity verdict") {
  const PartPtr part = part_with_axis("p");
  AssemblyPtr assembly = make_assembly_rassembly("structural");
  for (const char* id : {"base", "floating", "island"})
    assembly = with_component(assembly, part, id);
  assembly = ground_component_rassembly(*assembly, "base");
  assembly = add_revolute_constraint_rassembly(*assembly, "link", ref("base"), ref("floating"));

  const auto error = failure_of([&] { solve_assembly_constraints_rassembly(assembly); });
  REQUIRE(error);
  CHECK(error->operation() == "solve_assembly_constraints");
  CHECK(error->guidance().what_happened.find("island") != std::string::npos);
  std::map<std::string, std::string> statuses;
  for (const InventoryEntry& entry : error->guidance().inventory)
    statuses[entry.symbol] = entry.status;
  CHECK(statuses["base"] == "grounded");
  CHECK(statuses["floating"] == "reachable");
  CHECK(statuses["island"] == "unsolved");
  CHECK(error->guidance().technical_details == "assembly_id=structural, kind=unsolved_components");
}

TEST_CASE("public connectors close a nested revolute between fixed interfaces") {
  const PartPtr ring = part_with_axis("nested_bearing_ring");
  AssemblyPtr bearing = make_assembly_rassembly("nested_bearing");
  bearing = with_component(bearing, ring, "outer_ring");
  bearing = with_component(bearing, ring, "inner_ring");
  bearing = ground_component_rassembly(*bearing, "outer_ring");
  bearing = add_revolute_constraint_rassembly(*bearing, "inner_outer_revolute", ref("outer_ring"), ref("inner_ring"));
  bearing = set_public_connector_rassembly(*bearing, "outer_axis", "outer_ring", "axis");
  bearing = set_public_connector_rassembly(*bearing, "inner_axis", "inner_ring", "axis");

  const Placement quarter_turn(Vec3{0, 0, 0}, Vec3{0, 1, 0}, Vec3{-1, 0, 0});
  AssemblyPtr root = make_assembly_rassembly("nested_bearing_fixture");
  root = with_component(root, ring, "housing");
  root = with_component(root, ring, "shaft", quarter_turn);
  root = add_component_rassembly(*root, Item{bearing}, "bearing", identity_placement());
  root = ground_component_rassembly(*root, "housing");
  root = ground_component_rassembly(*root, "shaft");
  root = add_fixed_constraint_rassembly(*root, "outer_ring_to_housing", ref("housing"), ref("bearing", "outer_axis"));
  root = add_fixed_constraint_rassembly(*root, "inner_ring_to_shaft", ref("shaft"), ref("bearing", "inner_axis"));

  const AssemblyPtr solved = solve_assembly_constraints_rassembly(root);
  const Value report = solved->get_runtime("constraint_report");
  CHECK(report.find("solved")->as_bool());
  const auto& nested = *std::get<AssemblyPtr>(solved->get_component("bearing").item);
  check_vec(nested.get_component("inner_ring").placement.x_axis(), solved->get_component("shaft").placement.x_axis());
  check_vec(nested.get_component("outer_ring").placement.x_axis(), solved->get_component("housing").placement.x_axis());
}

TEST_CASE("a public connector solves at the parent level") {
  const PartPtr inner_part = part_with_axis("public_inner_part", {2, 0, 0});
  const PartPtr base_part = part_with_axis("public_base_part");
  AssemblyPtr child = with_component(make_assembly_rassembly("public_child"), inner_part, "inner", at(5, 0, 0));
  child = set_public_connector_rassembly(*child, "public_axis", "inner", "axis");
  AssemblyPtr root = with_component(make_assembly_rassembly("public_root"), base_part, "base", at(10, 0, 0));
  root = add_component_rassembly(*root, Item{child}, "child", identity_placement());
  root = ground_component_rassembly(*root, "base");
  root = add_fixed_constraint_rassembly(*root, "bind_public_axis", ref("base"), ref("child", "public_axis"));
  const AssemblyPtr solved = solve_assembly_constraints_rassembly(root);
  CHECK(solved->get_component("child").placement.origin() == Vec3{3, 0, 0});
  CHECK(measure_constraint_residual_rconstraintresidual(*solved, "bind_public_axis").within_tolerance);
}

TEST_CASE("constraint reports compare by verdict and tolerance") {
  AssemblyPtr assembly = pair_with(part_with_axis("p"), "slider");
  assembly = add_prismatic_constraint_rassembly(*assembly, "slide", ref("base"), ref("slider"), 5.0);
  const AssemblyPtr solved = solve_assembly_constraints_rassembly(assembly);
  const Value report = inspect_assembly_constraints_rconstraintreport(*solved).to_dict();
  CHECK(constraint_reports_match(report, report));
  const AssemblyPtr with_island = with_component(assembly, part_with_axis("island_part"), "island");
  const Value island = inspect_assembly_constraints_rconstraintreport(*with_island).to_dict();
  CHECK_FALSE(constraint_reports_match(report, island));
}
