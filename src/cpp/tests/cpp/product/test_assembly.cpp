// Assembly structure: components, public connectors, grounding, nesting and projection.
#include "support.hpp"

using namespace scad::product_test;

TEST_CASE("components are added immutably and placed by id") {
  const PartPtr bolt = make_part_rpart("bolt", make_cylinder_rsolid(1.0, 2.0));
  AssemblyPtr assembly = make_assembly_rassembly("fixture");
  const AssemblyPtr empty = assembly;
  assembly = with_component(assembly, bolt, "bolt_left", at(-5, 0, 0));
  assembly = with_component(assembly, bolt, "bolt_right", at(5, 0, 0));

  CHECK(empty->components().empty());
  CHECK(assembly->component_ids() == std::vector<std::string>{"bolt_left", "bolt_right"});
  CHECK(std::get<PartPtr>(assembly->get_component("bolt_left").item) == bolt);

  const AssemblyPtr moved = place_component_rassembly(*assembly, "bolt_left", at(-9, 0, 0));
  check_vec(moved->get_component("bolt_left").placement.origin(), {-9, 0, 0});
  check_vec(assembly->get_component("bolt_left").placement.origin(), {-5, 0, 0});

  CHECK_THROWS_AS(assembly->get_component("nope"), reactive::KeyError);
  CHECK_THROWS_AS(place_component_rassembly(*assembly, "nope", at(0, 0, 0)), Error);
}

TEST_CASE("duplicate components and assembly cycles are rejected") {
  const PartPtr part = make_part_rpart("box_part", make_box_rsolid(1.0, 1.0, 1.0));
  AssemblyPtr assembly = make_assembly_rassembly("root");
  assembly = with_component(assembly, part, "box");

  const auto duplicate = failure_of([&] { with_component(assembly, part, "box"); });
  REQUIRE(duplicate);
  CHECK(duplicate->operation() == "add_component_rassembly");
  CHECK(duplicate->guidance().technical_details == "ValueError: duplicate component_id in assembly: box");

  AssemblyPtr child = make_assembly_rassembly("child");
  child = add_component_rassembly(*child, Item{assembly}, "parent_instance", identity_placement());
  const auto cycle =
      failure_of([&] { add_component_rassembly(*assembly, Item{child}, "child_instance", identity_placement()); });
  REQUIRE(cycle);
  CHECK(cycle->guidance().technical_details == "ValueError: assembly cycle detected for 'root'");
}

TEST_CASE("a missing key is described as Python's str(KeyError)") {
  AssemblyPtr assembly = make_assembly_rassembly("a");
  const auto error = failure_of([&] { ground_component_rassembly(*assembly, "ghost"); });
  REQUIRE(error);
  CHECK(error->operation() == "ground_component_rassembly");
  CHECK(error->guidance().technical_details == "KeyError: \"assembly has no component_id 'ghost'\"");
}

TEST_CASE("grounding is idempotent and can be undone") {
  const PartPtr part = part_with_axis("p");
  AssemblyPtr assembly = with_component(make_assembly_rassembly("g"), part, "base");
  assembly = ground_component_rassembly(*assembly, "base");
  CHECK(assembly->grounded_component_ids() == std::vector<std::string>{"base"});
  assembly = ground_component_rassembly(*assembly, "base");
  CHECK(assembly->grounded_component_ids().size() == 1);
  assembly = unground_component_rassembly(*assembly, "base");
  CHECK(assembly->grounded_component_ids().empty());
}

TEST_CASE("public connectors expose a child's connector") {
  const PartPtr part = part_with_axis("p", {2, 0, 0});
  AssemblyPtr child = with_component(make_assembly_rassembly("child"), part, "inner", at(5, 0, 0));
  child = set_public_connector_rassembly(*child, "public_axis", "inner", "axis");
  CHECK(child->public_connector_ids() == std::vector<std::string>{"public_axis"});
  const PublicConnectorRef& pub = child->get_public_connector("public_axis");
  CHECK(pub.component_id == "inner");
  CHECK(pub.connector_id == "axis");

  const auto missing = failure_of([&] { set_public_connector_rassembly(*child, "other", "ghost", "axis"); });
  REQUIRE(missing);
  CHECK(missing->guidance().technical_details.find("missing component or connector for public connector") !=
        std::string::npos);

  const auto duplicate = failure_of([&] { set_public_connector_rassembly(*child, "public_axis", "inner", "axis"); });
  REQUIRE(duplicate);
  CHECK(duplicate->guidance().technical_details ==
        "ValueError: duplicate public_connector_id in assembly: public_axis");

  check_vec(resolve_item_connector_placement(Item{child}, "public_axis").origin(), {7, 0, 0});
}

TEST_CASE("an assembly projects to a compound of placed solids") {
  const Solid body = make_cylinder_rsolid(1.0, 2.0);
  const PartPtr bolt = make_part_rpart("bolt", body);
  AssemblyPtr assembly = make_assembly_rassembly("fixture");
  assembly = with_component(assembly, bolt, "left", at(-5, 0, 0));
  assembly = with_component(assembly, bolt, "right", at(5, 0, 0));

  const Compound compound = make_compound_from_assembly_rcompound(*assembly);
  CHECK(compound.solids().size() == 2);
  CHECK(compound.volume() == doctest::Approx(2.0 * body.volume()).epsilon(1e-7));
  const kernel::BoundingBox box = compound.bounding_box();
  CHECK(box.xmin == doctest::Approx(-6.0));
  CHECK(box.xmax == doctest::Approx(6.0));
  const Value projection = compound.get_metadata("assembly_projection");
  CHECK(projection.dump() == R"({"assembly_id":"fixture","component_count":2,"solid_count":2})");

  const auto empty = failure_of([&] { make_compound_from_assembly_rcompound(*make_assembly_rassembly("empty")); });
  REQUIRE(empty);
  CHECK(empty->operation() == "make_compound_from_assembly_rcompound");
  CHECK(empty->guidance().technical_details == "ValueError: assembly must contain at least one component to project");
}

TEST_CASE("nested assembly projection composes component placements") {
  const PartPtr part = make_part_rpart("cube_part", make_box_rsolid(1.0, 1.0, 1.0));
  const AssemblyPtr child = with_component(make_assembly_rassembly("child_assembly"), part, "cube", at(2, 0, 0));
  AssemblyPtr root = make_assembly_rassembly("root_assembly");
  root = add_component_rassembly(*root, Item{child}, "child", at(10, 0, 0));
  const Compound compound = make_compound_from_assembly_rcompound(*root);
  CHECK(compound.solids().size() == 1);
  const kernel::BoundingBox box = compound.bounding_box();
  CHECK(box.xmin == doctest::Approx(11.5));
  CHECK(box.xmax == doctest::Approx(12.5));
}
