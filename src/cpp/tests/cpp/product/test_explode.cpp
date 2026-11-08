// explode_rassembly: displacement rules, refusals, recording.
#include "support.hpp"

using namespace scad::product_test;

namespace {

// Four 2 x 2 x 2 boxes (centred on x and y, standing on z = 0): one at the origin and three 10 away along the axes.
AssemblyPtr cross() {
  const PartPtr part = make_part_rpart("cube", make_box_rsolid(2.0, 2.0, 2.0));
  AssemblyPtr assembly = make_assembly_rassembly("cross");
  assembly = with_component(assembly, part, "c0", at(0, 0, 0));
  assembly = with_component(assembly, part, "cx", at(10, 0, 0));
  assembly = with_component(assembly, part, "cy", at(0, 10, 0));
  assembly = with_component(assembly, part, "cz", at(0, 0, 10));
  return assembly;
}

Vec3 origin_of(const AssemblyPtr& assembly, const std::string& id) {
  return assembly->get_component(id).placement.origin();
}

}  // namespace

TEST_CASE("explode: each component moves away from the centre by factor * size along its own direction") {
  const AssemblyPtr assembly = cross();
  const AssemblyPtr exploded = explode_rassembly(*assembly, Scalar(1.0));
  // the box is centred on x and y and stands on z = 0: the bodies span [-1, 11] x [-1, 11] x [0, 12]
  const Value info = exploded->get_metadata("explode");
  const double size = info.find("size")->as_double();
  CHECK(size == doctest::Approx(std::sqrt(12.0 * 12.0 * 3.0)));
  const Vec3 middle{5.0, 5.0, 6.0};
  for (const char* id : {"c0", "cx", "cy", "cz"}) {
    const Vec3 start = origin_of(assembly, id);
    const Vec3 centre = start + Vec3{0, 0, 1};
    const Vec3 direction = (centre - middle).normalized();
    check_vec(origin_of(exploded, id), start + direction * size, 1e-9);
  }
  // nothing else changed: parts, constraints, grounding and the input
  CHECK(exploded->component_ids() == assembly->component_ids());
  check_vec(origin_of(assembly, "cx"), {10, 0, 0});
}

TEST_CASE("explode: factor 0 keeps the placements; weights, directions, axis and center are honoured") {
  const AssemblyPtr assembly = cross();
  const AssemblyPtr same = explode_rassembly(*assembly, Scalar(0.0));
  for (const std::string& id : assembly->component_ids())
    check_vec(origin_of(same, id), origin_of(assembly, id), 1e-12);

  const AssemblyPtr held = explode_rassembly(*assembly, Scalar(1.0), {}, {}, {}, {{"cx", 0.0}});
  check_vec(origin_of(held, "cx"), {10, 0, 0}, 1e-12);  // listed with weight 0: stays
  CHECK(origin_of(held, "cy").y > 10.0);

  const AssemblyPtr along = explode_rassembly(*assembly, Scalar(0.5), {}, {}, {{"cx", Vec3{0, 0, 2}}});
  const double size = along->get_metadata("explode").find("size")->as_double();
  check_vec(origin_of(along, "cx"), {10, 0, 0.5 * size}, 1e-9);

  const AssemblyPtr axial = explode_rassembly(*assembly, Scalar(1.0), {}, Vec3{0, 0, 3});
  CHECK(origin_of(axial, "cz").z == doctest::Approx(10.0 + size));  // above the centre: up
  CHECK(origin_of(axial, "cx").z == doctest::Approx(0.0 - size));   // below it: down
  check_vec(origin_of(axial, "cx"), {10, 0, -size}, 1e-9);

  const AssemblyPtr moved_centre =
      explode_rassembly(*assembly, Scalar(1.0), Vec3{10, 0, 1});    // the middle of cx itself
  CHECK(origin_of(moved_centre, "cx").x == doctest::Approx(10.0));  // c at the centre has no direction: stays
  const Value info = moved_centre->get_metadata("explode");
  REQUIRE(info.find("stationary")->as_array().size() == 1);
  CHECK(info.find("stationary")->as_array()[0].as_string() == "cx");
}

TEST_CASE("explode: refusals name the argument and the component") {
  const AssemblyPtr assembly = cross();
  const auto text = [](const std::unique_ptr<Error>& error) {
    return error ? error->guidance().technical_details : std::string();
  };
  CHECK(text(failure_of([&] { explode_rassembly(*assembly, Scalar(std::nan(""))); })).find("factor") !=
        std::string::npos);
  CHECK(text(failure_of([&] { explode_rassembly(*assembly, Scalar(1.0), {}, Vec3{0, 0, 0}); })).find("axis") !=
        std::string::npos);
  CHECK(text(failure_of([&] {
          explode_rassembly(*assembly, Scalar(1.0), {}, {}, {{"ghost", Vec3{1, 0, 0}}});
        })).find("'ghost'") != std::string::npos);
  CHECK(text(failure_of([&] {
          explode_rassembly(*assembly, Scalar(1.0), {}, {}, {}, {{"ghost", 1.0}});
        })).find("components: c0, cx, cy, cz") != std::string::npos);
  CHECK(text(failure_of([&] {
          explode_rassembly(*assembly, Scalar(1.0), {}, {}, {{"c0", Vec3{0, 0, 0}}});
        })).find("'c0'") != std::string::npos);
  const auto empty = explode_rassembly(*make_assembly_rassembly("none"), Scalar(1.0));
  CHECK(empty->components().empty());
}

TEST_CASE("explode: nested assemblies move as one component; grounding and constraints are untouched") {
  const PartPtr part = part_with_axis("p");
  AssemblyPtr inner = with_component(make_assembly_rassembly("inner"), part, "a", at(0, 0, 0));
  inner = with_component(inner, part, "b", at(2, 0, 0));
  AssemblyPtr outer = with_component(make_assembly_rassembly("outer"), part, "base", at(0, 0, 0));
  outer = add_component_rassembly(*outer, Item{inner}, "group", at(20, 0, 0));
  outer = ground_component_rassembly(*outer, "base");
  const AssemblyPtr exploded = explode_rassembly(*outer, Scalar(1.0));
  CHECK(exploded->grounded_component_ids() == std::vector<std::string>{"base"});
  CHECK(origin_of(exploded, "group").x > 20.0);
  const Item item = exploded->get_component("group").item;
  CHECK(std::get<AssemblyPtr>(item) == inner);  // the sub-assembly itself is shared, not rebuilt
}

TEST_CASE("explode: is recorded with its parameters") {
  Recording recording;
  const AssemblyPtr assembly = cross();
  explode_rassembly(*assembly, Scalar(0.5), Vec3{1, 2, 3}, {}, {{"cx", Vec3{1, 0, 0}}}, {{"cy", 0.25}});
  const auto ops = recording.ops();
  REQUIRE(!ops.empty());
  CHECK(ops.back() == "explode_rassembly");
  const auto& node = recording.session.graph().nodes().back();
  CHECK(node->params.find("factor")->as_double() == doctest::Approx(0.5));
  CHECK(node->params.find("center")->as_array().size() == 3);
  CHECK(node->params.find("directions")->find("cx") != nullptr);
  CHECK(node->params.find("weights")->find("cy")->as_double() == doctest::Approx(0.25));
}
