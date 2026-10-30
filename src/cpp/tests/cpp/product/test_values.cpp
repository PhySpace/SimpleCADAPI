// Placement, Material, ScalarLimit, Constraint and Part validation.
#include "support.hpp"

using namespace scad::product_test;

TEST_CASE("a placement is a canonical right-handed frame") {
  const Placement placement(Vec3{10, 20, 30}, Vec3{0, 1, 0}, Vec3{-1, 0, 0});
  CHECK(placement.origin() == Vec3{10, 20, 30});
  check_vec(placement.z_axis(), {0, 0, 1});
  check_vec(placement.transform_point({1, 2, 3}), {8, 21, 33});

  CHECK_THROWS_WITH_AS(Placement(Vec3{0, 0, 0}, Vec3{1, 0, 0}, Vec3{1, 0, 0}), "x_axis and y_axis must be orthogonal",
                       ValueError);
  CHECK_THROWS_WITH_AS(Placement(Vec3{0, 0, 0}, Vec3{0, 0, 0}), "x_axis must be a non-zero vector", ValueError);
  CHECK_THROWS_WITH_AS(Placement(Vec3{0, 0, 0}, Vec3{1, 0, 0}, Vec3{0, std::nan(""), 0}), "y_axis[1] must be finite",
                       ValueError);
}

TEST_CASE("placements compose, invert and measure relative to each other") {
  const Placement quarter = rotate_z_placement(90);
  const Placement parent(Vec3{1, 2, 3}, quarter.x_axis(), quarter.y_axis());
  const Placement child = at(1, 0, 0);
  check_vec(parent.compose(child).origin(), {1, 3, 3});

  const Placement round_trip = inverse_placement(parent).compose(parent);
  check_vec(round_trip.origin(), {0, 0, 0});
  check_vec(round_trip.x_axis(), {1, 0, 0});

  const Placement relative = relative_placement(parent, parent.compose(child));
  check_vec(relative.origin(), {1, 0, 0});
  CHECK(translate_z_placement(4).origin() == Vec3{0, 0, 4});
}

TEST_CASE("an exact frame is kept verbatim and checked") {
  const Placement exact = Placement::from_exact_frame({1, 2, 3}, {1, 0, 0}, {0, 1, 0}, {0, 0, 1});
  CHECK(exact == Placement(Vec3{1, 2, 3}));
  CHECK_THROWS_AS(Placement::from_exact_frame({0, 0, 0}, {2, 0, 0}, {0, 1, 0}, {0, 0, 1}), ValueError);
  CHECK_THROWS_AS(Placement::from_exact_frame({0, 0, 0}, {1, 0, 0}, {0, 1, 0}, {0, 0, -1}), ValueError);
}

TEST_CASE("identifiers follow the Python rule") {
  CHECK(validate_identifier("  base_1.a:b-c ", "part_id") == "base_1.a:b-c");
  CHECK_THROWS_WITH_AS(validate_identifier("", "part_id"), "part_id must not be empty", ValueError);
  CHECK_THROWS_AS(validate_identifier("1abc", "part_id"), ValueError);
  CHECK_THROWS_AS(validate_identifier("a b", "part_id"), ValueError);
}

TEST_CASE("python_repr renders a string like repr()") {
  CHECK(python_repr("abc") == "'abc'");
  CHECK(python_repr("it's") == "\"it's\"");
  CHECK(python_repr("a\"b'c") == "'a\"b\\'c'");
  CHECK(python_repr("a\\b\n") == "'a\\\\b\\n'");
}

TEST_CASE("a material validates density, unit and colour") {
  const Material steel("steel_8_8", "  Steel ", 7.85e-6, "kg/mm^3 ", Vec3{0.5, 0.5, 0.6});
  CHECK(*steel.name() == "Steel");
  CHECK(*steel.density_unit() == "kg/mm^3");
  const Value dict = steel.to_dict();
  CHECK(dict.find("material_id")->as_string() == "steel_8_8");
  CHECK(dict.find("density")->as_double() == 7.85e-6);
  CHECK(dict.find("color")->as_array().size() == 3);
  CHECK(Material("bare").to_dict().find("color")->is_null());

  CHECK_THROWS_WITH_AS(Material("m", {}, 1.0), "density_unit must be explicit when density is provided", ValueError);
  CHECK_THROWS_WITH_AS(Material("m", {}, {}, "kg"), "density_unit requires density", ValueError);
  CHECK_THROWS_WITH_AS(Material("m", {}, -1.0, "kg"), "density must be positive when provided", ValueError);
  CHECK_THROWS_WITH_AS(Material("m", {}, {}, {}, Vec3{1.2, 0, 0}), "color components must be in [0.0, 1.0]",
                       ValueError);
  CHECK(Material("a") == Material("a"));
  CHECK_FALSE(Material("a") == Material("b"));
}

TEST_CASE("a scalar limit is a closed range") {
  const ScalarLimit limit(0.0, 5.0);
  CHECK(limit.contains(0.0));
  CHECK(limit.contains(5.0));
  CHECK_FALSE(limit.contains(5.1));
  CHECK_THROWS_WITH_AS(ScalarLimit(2.0, 1.0), "lower_value must be less than or equal to upper_value", ValueError);
}

TEST_CASE("a constraint accepts only what its kind allows") {
  const ConnectorRef a("a", "axis");
  const ConnectorRef b("b", "axis");
  CHECK_NOTHROW(Constraint("c", "revolute", a, b, {.drive_angle_degrees = 30.0, .angle_limit = ScalarLimit(0, 90)}));
  CHECK_THROWS_WITH_AS(Constraint("c", "fixed", a, b, {.drive_distance = 1.0}),
                       "fixed constraints do not accept drive scalars", ValueError);
  CHECK_THROWS_WITH_AS(Constraint("c", "revolute", a, b, {.drive_distance = 1.0}),
                       "revolute constraints only accept angle scalars", ValueError);
  CHECK_THROWS_WITH_AS(Constraint("c", "prismatic", a, b, {.drive_angle_degrees = 1.0}),
                       "prismatic constraints only accept distance scalars", ValueError);
  CHECK_THROWS_WITH_AS(Constraint("c", "prismatic", a, b, {.pitch_radius = 1.0}),
                       "prismatic constraints do not accept coupling radii or phase_offset", ValueError);
  CHECK_THROWS_WITH_AS(Constraint("c", "gear", a, b, {.pitch_radius_a = 0.0, .pitch_radius_b = 1.0}),
                       "pitch_radius_a must be positive", ValueError);
  CHECK_THROWS_WITH_AS(Constraint("c", "gear", a, b, {.pitch_radius_a = 1.0}),
                       "gear constraints require pitch_radius_a and pitch_radius_b", ValueError);
  CHECK_THROWS_WITH_AS(
      Constraint("c", "belt", a, b, {.pulley_radius_a = 1.0, .pulley_radius_b = 1.0, .pitch_radius = 1.0}),
      "belt constraints only accept pulley_radius_a and pulley_radius_b", ValueError);
  CHECK_THROWS_WITH_AS(Constraint("c", "rack_pinion", a, b), "rack_pinion constraints require pitch_radius",
                       ValueError);
  CHECK_THROWS_WITH_AS(Constraint("c", "weld", a, b),
                       "constraint_kind must be fixed, revolute, prismatic, gear, belt, or rack_pinion", ValueError);
  CHECK_THROWS_WITH_AS(Constraint("c", "fixed", a, a), "constraint cannot connect the same connector ref twice",
                       ValueError);

  const Constraint gear("g", " GEAR ", a, b, {.pitch_radius_a = 1.0, .pitch_radius_b = 2.0});
  CHECK(gear.constraint_kind() == "gear");
  CHECK(*gear.phase_offset() == 0.0);
  CHECK(gear.is_coupling());
}

TEST_CASE("a part holds one body, its material and unique connectors") {
  const Solid body = make_box_rsolid(1.0, 1.0, 1.0);
  const Part part("p", body, "Plate");
  CHECK(*part.name() == "Plate");
  CHECK_FALSE(part.material());

  const Connector axis("axis", std::nullopt, std::nullopt, ConnectorAnchor(at(1, 2, 3)));
  const Part with_axis = part.with_connector(axis);
  CHECK(part.connectors().empty());
  CHECK(with_axis.connector_ids() == std::vector<std::string>{"axis"});
  check_vec(with_axis.get_connector("axis").placement().origin(), {1, 2, 3});
  CHECK_THROWS_WITH_AS(with_axis.with_connector(axis), "duplicate connector_id in part: axis", ValueError);
  CHECK_THROWS_AS(with_axis.get_connector("missing"), reactive::KeyError);
  CHECK_THROWS_AS(Part("p", body, std::nullopt, std::nullopt, {axis, axis}), ValueError);

  const Part material = part.with_material(Material("steel"));
  CHECK(material.material()->material_id() == "steel");
  CHECK_FALSE(part.material());
}

TEST_CASE("a connector needs an anchor and keeps geometry and placement apart") {
  CHECK_THROWS_WITH_AS(Connector("c"), "geometry_ref must be a GeometryRef when anchor is omitted", TypeError);
  const GeometryRef ref("face", std::nullopt, Value::object());
  CHECK_THROWS_WITH_AS(Connector("c", ref, std::nullopt, ConnectorAnchor(at(0, 0, 0))),
                       "geometry_ref is only valid for geometry connectors", ValueError);
  CHECK_THROWS_WITH_AS(GeometryRef("shell", std::nullopt, Value::object()),
                       "kind must be one of: vertex, edge, wire, face, solid", ValueError);
  CHECK_THROWS_WITH_AS(ConnectorAnchor("placement", ref, std::nullopt), "placement anchors require placement",
                       TypeError);
  CHECK_THROWS_WITH_AS(ConnectorAnchor("geometry", std::nullopt, at(0, 0, 0)), "geometry anchors require geometry_ref",
                       TypeError);
}
