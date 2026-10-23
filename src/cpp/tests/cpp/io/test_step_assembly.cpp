// STEP assemblies: product structure, placements, colours, materials, metadata.
#include "doctest.h"

#include <cmath>

#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>

#include "scad/core/error.hpp"
#include "scad/io/exchange.hpp"
#include "scad/io/step_assembly.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"

using namespace scad;
using namespace scad::io;

namespace {

StepDefinition part(const std::string& id, const TopoDS_Shape& shape) {
  StepDefinition d;
  d.id = id;
  d.kind = "single_solid";
  d.name = "Part \xC3\xA9 " + id;
  d.shape = shape;
  d.metadata.set("record_kind", "definition");
  d.metadata.set("definition_id", id);
  d.metadata.set("revision", 3);
  return d;
}

StepComponent place(const std::string& id, const std::string& definition, Vec3 at) {
  StepComponent c;
  c.id = id;
  c.name = "inst-" + id;
  c.definition_id = definition;
  c.placement.origin = at;
  c.metadata.set("record_kind", "occurrence");
  c.metadata.set("component_id", id);
  return c;
}

std::vector<StepDefinition> sample() {
  StepDefinition block = part("block", BRepPrimAPI_MakeBox(10, 20, 30).Solid());
  block.color = std::array<double, 3>{1.0, 0.0, 0.0};
  StepMaterial steel;
  steel.id = "steel";
  steel.name = "Steel";
  steel.density = 7850.0;
  steel.density_unit = "kg/m^3";
  steel.description.set("grade", "S235");
  block.material = steel;
  StepDefinition pin = part("pin", BRepPrimAPI_MakeCylinder(2.0, 10.0).Solid());
  pin.material = steel;

  StepDefinition top;
  top.id = "top";
  top.kind = "assembly";
  top.name = "Top assembly";
  top.metadata.set("record_kind", "definition");
  top.components = {place("a", "block", {0, 0, 0}), place("b", "block", {100, 0, 0}), place("c", "pin", {0, 50, 0})};
  // Rotate the pin 90 degrees about X: y -> z.
  top.components[2].placement.y_axis = {0, 0, 1};
  top.components[2].placement.z_axis = {0, -1, 0};
  return {block, pin, top};
}

}  // namespace

TEST_CASE("an assembly exports as AP242 with shared definitions and metadata properties") {
  StepAssemblyReport report;
  const Bytes bytes = step_assembly_bytes(sample(), "top", {}, &report);
  CHECK(bytes.find("AP242") != std::string::npos);
  CHECK(bytes.find("SimpleCAD metadata") != std::string::npos);
  CHECK(bytes.find("SimpleCAD:definition:single_solid:block") != std::string::npos);
  CHECK(bytes.find("SimpleCAD:occurrence:top:b") != std::string::npos);
  CHECK(bytes.find("\"revision\": 3") != std::string::npos);  // json.dumps spelling, sorted keys
  CHECK(report.schema == "AP242DIS");
  CHECK(report.occurrence_count == 3);
  CHECK(report.definition_ids == std::vector<std::string>{"top", "block", "pin"});
  CHECK(report.material_ids == std::vector<std::string>{"steel"});
  CHECK(report.metadata_item_count == 3 /*definitions*/ + 3 /*occurrences*/);

  // A plain reader sees the placed solids: two blocks and a pin.
  const StepReadResult flat = read_step_bytes(bytes);
  CHECK(kernel::solids_of(flat.shape).size() == 3);
  CHECK(kernel::volume(flat.shape) == doctest::Approx(2 * 6000.0 + kPi * 4 * 10).epsilon(1e-6));
}

TEST_CASE("the assembly reader returns names, placements, colours and bodies") {
  const Bytes bytes = step_assembly_bytes(sample(), "top");
  const std::vector<StepNode> tree = read_step_assembly_bytes(bytes);
  REQUIRE(tree.size() == 1);
  const StepNode& top = tree[0];
  CHECK(top.name == "Top assembly");
  CHECK(top.shape.IsNull());
  REQUIRE(top.children.size() == 3);
  CHECK(top.children[0].name == "inst-a");
  CHECK(top.children[1].name == "inst-b");
  CHECK(top.children[1].placement.origin.x == doctest::Approx(100.0));
  CHECK(top.children[0].shape.IsNull() == false);
  CHECK(kernel::volume(top.children[0].shape) == doctest::Approx(6000.0));
  REQUIRE(top.children[0].color.has_value());
  CHECK((*top.children[0].color)[0] == doctest::Approx(1.0));
  CHECK((*top.children[0].color)[1] == doctest::Approx(0.0));
  CHECK_FALSE(top.children[2].color.has_value());
  const StepPlacement& rotated = top.children[2].placement;
  CHECK(rotated.origin.y == doctest::Approx(50.0));
  CHECK(rotated.y_axis.z == doctest::Approx(1.0));
  CHECK(rotated.z_axis.y == doctest::Approx(-1.0));
}

TEST_CASE("assembly export validates its input") {
  auto defs = sample();
  CHECK_THROWS_AS((void)step_assembly_bytes(defs, "nope"), Error);
  defs[2].components.push_back(place("d", "missing", {}));
  CHECK_THROWS_AS((void)step_assembly_bytes(defs, "top"), Error);
  defs = sample();
  defs[2].components.push_back(place("loop", "top", {}));
  CHECK_THROWS_AS((void)step_assembly_bytes(defs, "top"), Error);
  defs = sample();
  defs[2].components[0].placement.x_axis = {2, 0, 0};  // not a rotation
  CHECK_THROWS_AS((void)step_assembly_bytes(defs, "top"), Error);
  defs = sample();
  StepAssemblyOptions bad;
  bad.schema = "NOT-A-SCHEMA";
  CHECK_THROWS_AS((void)step_assembly_bytes(defs, "top", bad), Error);
  defs.push_back(defs[0]);  // duplicate id
  CHECK_THROWS_AS((void)step_assembly_bytes(defs, "top"), Error);

  // A failed export must not leave the process-wide schema changed.
  const Bytes after = step_assembly_bytes(sample(), "top");
  CHECK(after.find("AP242") != std::string::npos);
  CHECK(step_bytes({BRepPrimAPI_MakeBox(1, 1, 1).Solid()}).find("AP242") == std::string::npos);
}

TEST_CASE("metadata properties can be left out, a single part exports without components") {
  StepAssemblyOptions options;
  options.metadata_properties = false;
  const Bytes bytes = step_assembly_bytes({part("solo", BRepPrimAPI_MakeBox(1, 2, 3).Solid())}, "solo", options);
  CHECK(bytes.find("SimpleCAD metadata") == std::string::npos);
  const std::vector<StepNode> tree = read_step_assembly_bytes(bytes);
  REQUIRE(tree.size() == 1);
  CHECK(kernel::volume(tree[0].shape) == doctest::Approx(6.0));
}
