// extrude, revolve, taper, extrude until.
#include "fixtures.hpp"

using namespace scad;
using namespace scad::feature_test;
using doctest::Approx;

TEST_CASE("extrude a face: volume, role tags and prefix") {
  const Face rect = make_rectangle_rface(2, 1);
  SweepTags tags;
  tags.tag_prefix = "part";
  tags.result_tag = "role.body";
  tags.start_face_tag = "role.start";
  tags.side_faces_tag = "role.sides";
  const Solid prism = extrude_rsolid(rect, scalar3(0, 0, 1), 3.0, tags);

  CHECK(prism.volume() == Approx(6.0));
  CHECK(has_tag(prism, "solid.extrusion"));
  CHECK(has_tag(prism, "part.solid"));
  CHECK(has_tag(prism, "role.body"));
  const auto faces = prism.faces();
  CHECK(faces.size() == 6);
  CHECK(count_tagged(faces, "role.start") == 1);
  CHECK(count_tagged(faces, "role.sides") == 4);
  CHECK(count_tagged(faces, "face.extrusion.end") == 1);
}

TEST_CASE("extrude a wire, and a wire that is not closed") {
  CHECK(extrude_rsolid(make_rectangle_rwire(4, 2), scalar3(0, 0, 1), 5.0).volume() == Approx(40.0));

  const Wire open = make_wire_from_edges_rwire(
      {make_line_redge(scalar3(0, 0, 0), scalar3(10, 0, 0)), make_line_redge(scalar3(10, 0, 0), scalar3(10, 6, 0)),
       make_line_redge(scalar3(10, 6, 0), scalar3(0, 6, 0)), make_line_redge(scalar3(0, 6, 0), scalar3(0, 0.8, 0))});
  const Error error = failure_of([&] { (void)extrude_rsolid(open, scalar3(0, 0, 1), 2.0); });
  CHECK(error.operation() == "extrude_rsolid");
  CHECK(measurement(error, "gap") == Approx(0.8));
}

TEST_CASE("extrude failures name the operation") {
  const Face rect = make_rectangle_rface(2, 1);
  CHECK(failure_of([&] { (void)extrude_rsolid(rect, scalar3(0, 0, 1), 0.0); }).operation() == "extrude_rsolid");
  CHECK(failure_of([&] { (void)extrude_rsolid(rect, scalar3(0, 0, 0), 1.0); }).operation() == "extrude_rsolid");
  CHECK(failure_of([&] { (void)extrude_rsolid(box(1, 1, 1), scalar3(0, 0, 1), 1.0); }).operation() == "extrude_rsolid");
  SweepTags bad;
  bad.result_tag = "Not A Tag";
  const Error error = failure_of([&] { (void)extrude_rsolid(rect, scalar3(0, 0, 1), 1.0, bad); });
  CHECK(error.guidance().technical_details == "ValueError: tag 'Not A Tag' is not normalized");
}

TEST_CASE("extrude follows the current workplane") {
  Workplane plane(Vec3{1, 2, 3}, Vec3{1, 0, 0});
  plane.enter();
  const Solid prism = extrude_rsolid(make_rectangle_rwire(4, 2), scalar3(0, 0, 1), 5.0);
  plane.exit();
  CHECK(prism.volume() == Approx(40.0));
  const auto box_of = prism.bounding_box();
  CHECK(box_of.xmin == Approx(1.0));
  CHECK(box_of.xmax == Approx(6.0));
}

TEST_CASE("revolve: a ring, partial turns and caps") {
  const Face rect = make_rectangle_rface(1, 2, scalar3(2, 0, 0));
  const double ring = 8 * kPi;  // pi (2.5^2 - 1.5^2) * 2
  CHECK(revolve_rsolid(rect, scalar3(0, 1, 0), 360.0).volume() == Approx(ring));
  SweepTags tags;
  tags.start_face_tag = "role.s";
  const Solid half = revolve_rsolid(rect, scalar3(0, 1, 0), 180.0, scalar3(0, 0, 0), tags);
  CHECK(half.volume() == Approx(ring / 2));
  CHECK(count_tagged(half.faces(), "role.s") == 1);
  CHECK(failure_of([&] { (void)revolve_rsolid(rect, scalar3(0, 1, 0), -5.0); }).operation() == "revolve_rsolid");
}

TEST_CASE("tapered extrusion") {
  const Face square = make_rectangle_rface(4, 4);
  CHECK(extrude_taper_rsolid(square, scalar3(0, 0, 3), 0.0).volume() == Approx(48.0));
  const double inward = extrude_taper_rsolid(square, scalar3(0, 0, 3), 10.0).volume();
  const double outward = extrude_taper_rsolid(square, scalar3(0, 0, 3), -10.0).volume();
  CHECK(inward < 48.0);
  CHECK(outward > 48.0);
  CHECK_THROWS_AS((void)extrude_taper_rsolid(square, scalar3(0, 0, 0), 5.0), ValueError);
  CHECK_THROWS_AS((void)extrude_taper_rsolid(square, scalar3(0, 0, 1), 90.0), ValueError);
}

TEST_CASE("extrude until a target") {
  const Face profile = make_rectangle_rface(2, 2);
  const Solid ceiling = box(10, 10, 2, scalar3(0, 0, 5));
  CHECK(extrude_until_rsolid(profile, {ceiling}, scalar3(0, 0, 1), "NEXT").volume() == Approx(20.0));
  CHECK(extrude_until_rsolid(profile, {ceiling}, scalar3(0, 0, 1), "LAST").volume() == Approx(28.0));
  const Face high = make_rectangle_rface(2, 2, scalar3(0, 0, 10));
  CHECK(extrude_until_rsolid(high, {box(10, 10, 2)}, scalar3(0, 0, 1), "PREVIOUS").volume() == Approx(32.0));
  CHECK_THROWS_AS((void)extrude_until_rsolid(profile, {}), ValueError);
  CHECK_THROWS_AS((void)extrude_until_rsolid(profile, {ceiling}, scalar3(0, 0, 1), "UNKNOWN"), ValueError);
  CHECK_THROWS_AS((void)extrude_until_rsolid(profile, {box(2, 2, 2, scalar3(20, 0, 5))}), ValueError);
}
