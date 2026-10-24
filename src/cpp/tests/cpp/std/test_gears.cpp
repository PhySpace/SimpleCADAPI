// Gears, ring gears, racks, cycloidal discs.  The numbers are the Python SDK's.
#include <cmath>

#include "fixtures.hpp"
#include "scad/std/gear_profiles.hpp"
#include "scad/std/involute.hpp"

using namespace scad;
using namespace scad::std_test;
using doctest::Approx;

TEST_CASE("spur gear: volume, topology and tip radius match the reference") {
  const Solid gear = make_spur_gear_rsolid(10, 2.0, 20.0, 5.0);
  CHECK(gear.volume() == Approx(1452.1134653103873).epsilon(1e-6));
  CHECK(gear.faces().size() == 62);
  CHECK(gear.edges().size() == 180);
  const double expected_tip = 2.0 * 10 / 2.0 + 2.0;
  CHECK(radial_extent(gear) < expected_tip * 1.05);
  CHECK(radial_extent(gear) > expected_tip * 0.95);
}

TEST_CASE("spur gear: tuning changes the tooth") {
  const Solid gear = make_spur_gear_rsolid(12, 2.0, 20.0, 4.0, ToothTuning{0.9, 0.3, 0.1});
  CHECK(gear.volume() == Approx(1679.7798158481353).epsilon(1e-6));
  CHECK(gear.faces().size() == 74);
}

TEST_CASE("spur gear: height scales the volume") {
  const double short_volume = make_spur_gear_rsolid(12, 2.0, 20.0, 4.0).volume();
  const double tall_volume = make_spur_gear_rsolid(12, 2.0, 20.0, 8.0).volume();
  CHECK(tall_volume == Approx(2.0 * short_volume).epsilon(1e-6));
}

TEST_CASE("spur gear: invalid arguments are ValueErrors with the Python text") {
  CHECK(failure_message([] { (void)make_spur_gear_rsolid(2, 2.0); }) == "n_teeth must be at least 3");
  CHECK(failure_message([] { (void)make_spur_gear_rsolid(10, -1.0); }) == "module must be positive");
  CHECK(failure_message([] { (void)make_spur_gear_rsolid(10, 2.0, 20.0, 0.0); }) == "gear_height must be positive");
  CHECK(failure_message([] { (void)make_spur_gear_rsolid(10, 2.0, 0.0); }) ==
        "pressure_angle must be greater than 0 and less than 90 degrees");
  CHECK(failure_message([] { (void)make_spur_gear_rsolid(10, 2.0, 20.0, 6.0, ToothTuning{1.0, 0.25, -0.1}); }) ==
        "backlash must be non-negative");
  CHECK(failure_message([] { (void)make_spur_gear_rsolid(10, 2.0, 20.0, 6.0, ToothTuning{0.0, 0.25, 0.0}); }) ==
        "addendum_factor must be positive");
  CHECK(failure_message([] { (void)make_spur_gear_rsolid(10, 2.0, 20.0, 6.0, ToothTuning{1.0, 0.25, 100.0}); }) ==
        "backlash must be smaller than the circular tooth thickness");
}

TEST_CASE("tooth geometry: backlash narrows the tooth by exactly backlash / pitch radius") {
  const double pa = stdlib::radians(20.0);
  stdlib::ToothOptions plain, loose;
  loose.tuning.backlash = 0.12;
  const auto a = stdlib::compute_tooth_geometry(18, 1.5, pa, plain);
  const auto b = stdlib::compute_tooth_geometry(18, 1.5, pa, loose);
  CHECK((a.right_start - a.left_start) - (b.right_start - b.left_start) == Approx(0.12 / a.pitch_radius).epsilon(1e-9));

  stdlib::ToothOptions factors;
  factors.tuning.addendum_factor = 0.8;
  factors.tuning.clearance_factor = 0.1;
  const auto c = stdlib::compute_tooth_geometry(18, 1.5, pa, factors);
  CHECK(c.tip_radius == Approx(13.5 + 0.8 * 1.5));
  CHECK(c.root_radius == Approx(13.5 - 0.9 * 1.5));
}

TEST_CASE("the external profile sketch fixes only the centre and uses B-spline root transitions") {
  const Sketch sketch = stdlib::build_gear_profile_sketch(18, 1.5, stdlib::radians(20.0));
  CHECK(sketch.entities().find("line_up_0") == nullptr);
  CHECK(sketch.entities().find("fillet_left_0")->kind == "bspline");
  CHECK(sketch.entities().find("fillet_right_0")->kind == "bspline");
  int fixes = 0;
  for (const SketchConstraint& constraint : sketch.constraints()) fixes += constraint.kind == "fix" ? 1 : 0;
  CHECK(fixes == 1);

  // The flank starts and ends on the analytic points of the tooth.
  const SketchEntity& left = *sketch.entities().find("bspline_left_0");
  const Value& poles = *left.data.find("control_points");
  const Value& start = sketch.entities().find("t0_bs")->data;
  const Value& tip = sketch.entities().find("t0_ts")->data;
  CHECK(poles.as_array().front().as_array()[0].as_double() == Approx(start.find("x")->as_double()).epsilon(1e-8));
  CHECK(poles.as_array().back().as_array()[1].as_double() == Approx(tip.find("y")->as_double()).epsilon(1e-8));
}

TEST_CASE("helical and herringbone gears: zero helix is the spur gear") {
  const double spur = make_spur_gear_rsolid(12, 2.0, 20.0, 6.0).volume();
  CHECK(make_helical_gear_rsolid(12, 2.0, 20.0, 0.0, 6.0).volume() == Approx(spur));
  CHECK(make_herringbone_gear_rsolid(12, 2.0, 20.0, 0.0, 6.0).volume() == Approx(spur));
}

TEST_CASE("helical gear: one continuous twisted sweep") {
  const Solid gear = make_helical_gear_rsolid(12, 2.0, 20.0, 25.0, 8.0);
  CHECK(gear.volume() == Approx(3397.1259373001008).epsilon(1e-6));
  CHECK(gear.faces().size() == 74);
  CHECK(gear.edges().size() == 216);
}

TEST_CASE("herringbone gear: two halves fused") {
  const Solid gear = make_herringbone_gear_rsolid(12, 2.0, 20.0, 25.0, 10.0);
  CHECK(gear.volume() == Approx(4246.407415685476).epsilon(1e-6));
  CHECK(gear.faces().size() == 146);
}

TEST_CASE("straight bevel gear: ruled loft and metadata") {
  const Solid gear = make_straight_bevel_gear_rsolid(18, 4.0, 45.0, 20.0, 18.0);
  CHECK(gear.volume() == Approx(34402.364464437356).epsilon(1e-6));
  CHECK(gear.faces().size() == 110);
  const Value meta = gear.get_metadata("std.gear.straight_bevel");
  CHECK(meta.find("n_teeth")->as_int() == 18);
  CHECK(number(meta, "outer_pitch_radius") == Approx(36.0));
  CHECK(number(meta, "outer_cone_distance") == Approx(36.0 / std::sin(stdlib::radians(45.0))));
  CHECK(failure_message([] { (void)make_straight_bevel_gear_rsolid(18, 4.0, 45.0, 20.0, 60.0); }) ==
        "face_width must be smaller than the pitch-cone distance");
  CHECK(failure_message([] { (void)make_straight_bevel_gear_rsolid(18, 4.0, 90.0); }) ==
        "pitch_angle must be greater than 0 and less than 90 degrees");
}

TEST_CASE("ring gear: internal tooth radii and volume") {
  const Solid ring = make_spur_ring_gear_rsolid(20, 2.0, 20.0, 5.0, 4.0);
  CHECK(ring.volume() == Approx(4732.90736848749).epsilon(1e-6));
  CHECK(ring.faces().size() == 123);

  const auto radii = stdlib::internal_ring_radii(66, 1.5, 4.0, 0.8, 0.1);
  CHECK(radii.tip == Approx(radii.pitch - 0.8 * 1.5));
  CHECK(radii.root == Approx(radii.pitch + 0.9 * 1.5));
  CHECK(radii.outer == Approx(radii.root + 4.0));
}

TEST_CASE("ring gear: the profile reaches the internal tip and root radii") {
  const Face face = stdlib::build_ring_gear_face(66, 1.5, stdlib::radians(20.0), 4.0);
  double rmin = 1e9, rmax = 0;
  for (const Edge& edge : face.inner_wires().front().edges()) {
    for (const Vertex& vertex : edge.vertices()) {
      const Vec3 p = vertex.coordinates();
      rmin = std::min(rmin, std::hypot(p.x, p.y));
      rmax = std::max(rmax, std::hypot(p.x, p.y));
    }
  }
  CHECK(rmin == Approx(49.5 - 1.5).epsilon(1e-5));
  CHECK(rmax == Approx(49.5 + 1.25 * 1.5).epsilon(1e-5));
}

TEST_CASE("ring gear: backlash widens the tooth space") {
  const double pa = stdlib::radians(20.0);
  const auto a = stdlib::compute_internal_tooth_geometry(66, 1.5, pa);
  const auto b = stdlib::compute_internal_tooth_geometry(66, 1.5, pa, ToothTuning{1.0, 0.25, 0.12});
  const double space_a = a.tooth_angle - (a.right_root_angle - a.left_root_angle);
  const double space_b = b.tooth_angle - (b.right_root_angle - b.left_root_angle);
  CHECK(space_b - space_a == Approx(0.12 / a.pitch_radius).epsilon(1e-9));
}

TEST_CASE("helical and herringbone ring gears") {
  CHECK(make_helical_ring_gear_rsolid(20, 2.0, 20.0, 20.0, 8.0).volume() == Approx(6265.749254481292).epsilon(1e-6));
  CHECK(make_herringbone_ring_gear_rsolid(20, 2.0, 20.0, 20.0, 10.0).volume() ==
        Approx(7832.186568524259).epsilon(1e-6));
  CHECK(failure_message([] { (void)make_spur_ring_gear_rsolid(10, 2.0, 20.0, 6.0, 0.0); }) ==
        "rim_thickness must be positive");
}

TEST_CASE("cycloidal disc: fit data, holes, errors") {
  CycloidalDiscOptions options;
  options.bore_radius = 3.45;
  options.output_pin_count = 3;
  options.output_pin_pitch_radius = 6.4;
  options.output_pin_clearance_radius = 2.05;
  options.output_pin_phase = 60.0;
  const Solid disc = make_cycloidal_disc_rsolid(10, 18.0, 1.6, 0.8, 5.7, options);
  CHECK(disc.volume() == Approx(4440.720394399493).epsilon(1e-5));
  CHECK(disc.faces().size() == 16);
  const Value meta = disc.get_metadata("std.gear.cycloidal_disc");
  CHECK(meta.find("pin_count")->as_int() == 11);
  CHECK(meta.find("segment_count")->as_int() == 10);
  CHECK(number(meta, "radius_min") < number(meta, "radius_max"));
  CHECK(meta.find("control_point_counts")->size() == 10);

  CHECK(failure_message([] { (void)make_cycloidal_disc_rsolid(1, 18.0, 1.6, 0.8); }) == "n_lobes must be at least 2");
  CycloidalDiscOptions holes;
  holes.output_pin_count = 3;
  CHECK(failure_message([&] { (void)make_cycloidal_disc_rsolid(10, 18.0, 1.6, 0.8, 6.0, holes); }) ==
        "output_pin_pitch_radius must be positive when output holes are requested");
}

TEST_CASE("racks") {
  CHECK(make_spur_rack_rsolid(2.0, 8, 20.0, 5.0).volume() == Approx(815.472695385286).epsilon(1e-6));
  CHECK(make_helical_rack_rsolid(2.0, 8, 20.0, 25.0, 8.0).volume() == Approx(1304.7563133931917).epsilon(1e-6));
  CHECK(make_herringbone_rack_rsolid(2.0, 8, 20.0, 30.0, 10.0).volume() == Approx(1630.9265860771739).epsilon(1e-6));
  CHECK(failure_message([] { (void)make_spur_rack_rsolid(-1.0); }) == "module must be positive");
  CHECK(failure_message([] { (void)make_spur_rack_rsolid(2.0, 0); }) == "n_teeth must be at least 1");
}

TEST_CASE("an external gear profile builds two canonical root fillets, and its flanks go through the shared fit") {
  const std::size_t fillets = stdlib::root_fillet_call_count();
  const std::size_t fits = stdlib::involute_fit_call_count();
  (void)stdlib::build_gear_profile_face(18, 1.5, kPi / 9.0);
  CHECK(stdlib::root_fillet_call_count() - fillets == 2);
  CHECK(stdlib::involute_fit_call_count() > fits);
}
