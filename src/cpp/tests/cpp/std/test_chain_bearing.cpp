// Roller-chain sprockets and ball bearings.  The numbers are the Python SDK's.
#include <cmath>

#include "fixtures.hpp"
#include "scad/product/operators.hpp"

using namespace scad;
using namespace scad::std_test;
using doctest::Approx;

TEST_CASE("sprocket: ISO 606 12B candidate") {
  const Solid sprocket = make_roller_chain_sprocket_rsolid(18, 19.05, 12.07, 11.1, 10.2);
  CHECK(sprocket.volume() == Approx(98201.67369173263).epsilon(1e-6));
  CHECK(sprocket.faces().size() == 54);
  const Value meta = sprocket.get_metadata("std.chain.roller_sprocket");
  CHECK(meta.find("n_teeth")->as_int() == 18);
  CHECK(number(meta, "pitch_radius") == Approx(19.05 / (2.0 * std::sin(kPi / 18))));
  CHECK(number(meta, "root_radius") < number(meta, "pitch_radius"));
  CHECK(number(meta, "outside_radius") > number(meta, "pitch_radius"));
}

TEST_CASE("sprocket: invalid arguments are ValueErrors with the Python text") {
  const auto message = [](int n, double pitch, double roller, double thickness, double bore = 0.0) {
    return failure_message([&] { (void)make_roller_chain_sprocket_rsolid(n, pitch, roller, thickness, bore); });
  };
  CHECK(message(5, 19.05, 12.07, 11.1) == "n_teeth must be an integer of at least 6");
  CHECK(message(18, 0.0, 12.07, 11.1) == "chain_pitch must be positive and finite");
  CHECK(message(18, 19.05, 19.05, 11.1) == "roller_diameter must be smaller than chain_pitch");
  CHECK(message(18, 19.05, 12.07, 0.0) == "sprocket_thickness must be positive and finite");
  CHECK(message(18, 19.05, 12.07, 11.1, 60.0) == "bore_radius must be smaller than the sprocket root radius");
}

TEST_CASE("ball bearing: components, constraint, connectors, metadata") {
  BallBearingOptions options;
  options.ball_count = 7;
  options.raceway_clearance = 0.05;
  options.edge_chamfer = 0.05;
  options.assembly_id = "bearing_basic_test";
  options.drive_angle_degrees = 30.0;
  const auto bearing = make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5, options);

  const std::vector<std::string> expected{"outer_ring", "inner_ring", "ball_00", "ball_01", "ball_02",
                                          "ball_03",    "ball_04",    "ball_05", "ball_06"};
  CHECK(bearing->component_ids() == expected);
  CHECK(bearing->constraint_ids() == std::vector<std::string>{"inner_outer_revolute"});
  CHECK(bearing->public_connector_ids() == std::vector<std::string>{"outer_axis", "inner_axis"});
  CHECK(bearing->grounded_component_ids().empty());

  const product::Constraint& constraint = bearing->get_constraint("inner_outer_revolute");
  CHECK(constraint.constraint_kind() == "revolute");
  CHECK(constraint.connector_a().component_id() == "outer_ring");
  CHECK(constraint.connector_b().connector_id() == "axis");

  const auto& outer = *std::get<product::PartPtr>(bearing->get_component("outer_ring").item);
  const auto& inner = *std::get<product::PartPtr>(bearing->get_component("inner_ring").item);
  const auto& ball = *std::get<product::PartPtr>(bearing->get_component("ball_00").item);
  CHECK(outer.body().volume() == Approx(905.9721898060147).epsilon(1e-6));
  CHECK(inner.body().volume() == Approx(458.792729236588).epsilon(1e-6));
  CHECK(ball.body().volume() == Approx(22.449297503777025).epsilon(1e-6));
  CHECK(outer.connector_ids() == std::vector<std::string>{"axis"});
  CHECK(ball.connector_ids().empty());
  CHECK(has_tag(ball.body(), "role.rolling_element"));
  CHECK(has_tag(ball.body(), "group.ball_bearing"));

  const Value ring = outer.body().get_metadata("std.bearing.ring");
  CHECK(number(ring, "inner_radius") == Approx(7.5 + 1.75 * 0.75));
  CHECK(number(ring, "raceway_mouth_z") < number(ring, "groove_radius"));
  const Value meta = bearing->get_metadata("std.bearing.ball_bearing");
  CHECK(meta.find("ball_count")->as_int() == 7);
  CHECK(meta.find("ball_component_ids")->size() == 7);
  CHECK(number(*meta.find("ball_angles_degrees"), "ball_02") == Approx(360.0 * 2 / 7));
  CHECK(meta.find("rolling_element_fuse_overlap")->is_null());
  CHECK(meta.find("rolling_element_fuse_mode")->as_string() == "components");
}

TEST_CASE("ball bearing: an inferred ball count, fused rolling elements") {
  const auto inferred = make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5);
  CHECK(inferred->get_metadata("std.bearing.ball_bearing").find("ball_count")->as_int() == 8);

  BallBearingOptions options;
  options.ball_count = 7;
  options.raceway_clearance = 0.05;
  options.assembly_id = "fz";
  options.fuse_rolling_elements = true;
  const auto fused = make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5, options);
  CHECK(fused->component_ids() == std::vector<std::string>{"outer_ring", "inner_ring"});
  const auto& outer = *std::get<product::PartPtr>(fused->get_component("outer_ring").item);
  CHECK(outer.body().volume() == Approx(1000.511251295269).epsilon(1e-6));
  CHECK(has_tag(outer.body(), "role.rolling_elements_fused_into_outer_ring"));
}

TEST_CASE("ball bearing: a material goes to every part") {
  BallBearingOptions options;
  options.ball_count = 7;
  options.raceway_clearance = 0.05;
  options.material = product::Material("steel", std::string("Steel"), 7.85, std::string("g/cm3"));
  const auto bearing = make_ball_bearing_rassembly(8.0, 22.0, 7.0, 3.5, options);
  for (const char* id : {"outer_ring", "inner_ring", "ball_03"}) {
    const auto& part = *std::get<product::PartPtr>(bearing->get_component(id).item);
    REQUIRE(part.material().has_value());
    CHECK(part.material()->material_id() == "steel");
  }
}

TEST_CASE("ball bearing: invalid arguments are ValueErrors with the Python text") {
  const auto message = [](double bore, double outer, double width, double ball, BallBearingOptions o = {}) {
    return failure_message([&] { (void)make_ball_bearing_rassembly(bore, outer, width, ball, o); });
  };
  CHECK(message(22.0, 8.0, 7.0, 3.5) == "outer_diameter must be greater than bore_diameter");
  CHECK(message(8.0, 22.0, 3.0, 3.5) == "bearing_width must be greater than ball_diameter plus raceway_clearance");
  CHECK(message(8.0, 22.0, 7.0, 8.0) == "ball_diameter plus raceway_clearance leaves no radial wall thickness");
  BallBearingOptions crowded;
  crowded.ball_count = 100;
  CHECK(message(8.0, 22.0, 7.0, 3.5, crowded) == "ball_count is too high for ball_diameter on the bearing pitch circle");
  BallBearingOptions few;
  few.ball_count = 2;
  CHECK(message(8.0, 22.0, 7.0, 3.5, few) == "ball_count must be at least 3");
  BallBearingOptions thick;
  thick.ball_count = 7;
  thick.raceway_clearance = 0.05;
  thick.edge_chamfer = 2.0;
  CHECK(message(8.0, 22.0, 7.0, 3.5, thick) == "edge_chamfer must be smaller than the thinnest bearing feature");
  BallBearingOptions fuse;
  fuse.fuse_rolling_elements = true;
  fuse.rolling_element_fuse_overlap = 0.0;
  CHECK(message(8.0, 22.0, 7.0, 3.5, fuse) == "rolling_element_fuse_overlap must be finite and positive");
}
