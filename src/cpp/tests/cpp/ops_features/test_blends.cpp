// fillet, chamfer, shell, offset, draft and the failure diagnoses of the blends.
#include "fixtures.hpp"

using namespace scad;
using namespace scad::feature_test;
using doctest::Approx;

TEST_CASE("fillet one edge: volume, patch tag, result tag, tags carried over") {
  const Solid cube = box(10, 10, 10);
  const std::vector<Edge> top = edges_at_z(cube, 10.0);
  REQUIRE(top.size() == 4);
  faces_facing(cube, 2).front().apply_tag("role.top");

  BlendTags tags;
  tags.result_tag = "role.rounded";
  tags.generated_faces_tag = "role.patch";
  const Solid out = fillet_rsolid(cube, std::vector<Edge>{top.front()}, 1.0, tags);
  CHECK(out.volume() == Approx(1000.0 - (1.0 - kPi / 4) * 10.0));
  CHECK(has_tag(out, "role.rounded"));
  CHECK(count_tagged(out.faces(), "role.patch") == 1);
  CHECK(out.faces().size() == 7);
}

TEST_CASE("fillet by selector") {
  const Solid cube = box(10, 10, 10);
  const Solid out = fillet_rsolid(cube, ql::edges().where(ql::prop("geom.center.z", ">", Value(9.9))), 2.0);
  CHECK(out.volume() < 1000.0);
  CHECK(out.faces().size() == 10);
}

TEST_CASE("chamfer: symmetric and angled") {
  const Solid cube = box(10, 10, 10);
  const Edge edge = [&] {
    for (const Edge& e : edges_at_z(cube, 10.0)) {
      if (e.center().y < -4.999)
        return e;
    }
    throw 0;
  }();
  ChamferOptions plain;
  plain.tags.generated_faces_tag = "role.bevel";
  const Solid symmetric = chamfer_rsolid(cube, std::vector<Edge>{edge}, 1.0, plain);
  CHECK(symmetric.volume() == Approx(1000.0 - 0.5 * 10.0));
  CHECK(count_tagged(symmetric.faces(), "role.bevel") == 1);

  for (const double angle : {15.0, 30.0, 75.0}) {
    ChamferOptions angled;
    angled.angle = angle;
    angled.reference_direction = Vec3{0, 0, 1};
    const Solid out = chamfer_rsolid(cube, std::vector<Edge>{edge}, 1.0, angled);
    CHECK(1000.0 - out.volume() == Approx(0.5 * std::tan(angle * kPi / 180.0) * 10.0));
  }
  ChamferOptions missing_reference;
  missing_reference.angle = 30.0;
  CHECK(failure_of([&] { (void)chamfer_rsolid(cube, std::vector<Edge>{edge}, 1.0, missing_reference); }).operation() ==
        "chamfer_rsolid");
  ChamferOptions out_of_range;
  out_of_range.angle = 90.0;
  out_of_range.reference_direction = Vec3{0, 0, 1};
  CHECK_THROWS_AS((void)chamfer_rsolid(cube, std::vector<Edge>{edge}, 1.0, out_of_range), Error);
}

TEST_CASE("blend failures are explained with measurements") {
  const Solid cube = box(10, 10, 10);
  const std::vector<Edge> edges = cube.edges();

  Error room = failure_of([&] { (void)fillet_rsolid(cube, std::vector<Edge>{edges[0]}, 12.0); });
  CHECK(room.operation() == "fillet_rsolid");
  CHECK(room.guidance().what_happened.find("radius 12 mm meets or exceeds the 10 mm") != std::string::npos);
  CHECK(measurement(room, "available_face_room") == Approx(10.0));

  const Error bevel = failure_of([&] { (void)chamfer_rsolid(cube, std::vector<Edge>{edges[0]}, 12.0); });
  CHECK(bevel.guidance().what_happened.find("distance 12 mm meets or exceeds the 10 mm") != std::string::npos);

  const Error critical = failure_of([&] { (void)fillet_rsolid(cube, edges, 5.0); });
  CHECK(critical.guidance().what_happened.find("meet tangentially") != std::string::npos);
  CHECK(measurement(critical, "combined_blend_width") == Approx(10.0));

  // The kernel "succeeds" with garbage; the exit check names it.
  const Error garbage = failure_of([&] { (void)fillet_rsolid(cube, edges, 6.0); });
  CHECK(garbage.guidance().what_happened.find("probes indicate") != std::string::npos);
  CHECK(garbage.guidance().technical_details.find("BlendVolumeViolation") == 0);

  CHECK_THROWS_AS((void)fillet_rsolid(cube, std::vector<Edge>{}, 1.0), Error);
  CHECK_THROWS_AS((void)fillet_rsolid(cube, std::vector<Edge>{edges[0]}, -1.0), Error);
}

TEST_CASE("shell removes faces and keeps a wall") {
  const Solid cube = box(10, 10, 10);
  ShellTags tags;
  tags.closing_faces_tag = "role.rim";
  tags.offset_faces_tag = "role.inner";
  const Solid cup = shell_rsolid(cube, std::vector<Face>{faces_facing(cube, 2).front()}, 1.0, tags);
  CHECK(cup.volume() == Approx(1000.0 - 8 * 8 * 9));
  CHECK(count_tagged(cup.faces(), "role.inner") == 5);
  CHECK(count_tagged(cup.faces(), "role.rim") == 1);
  CHECK_THROWS_AS((void)shell_rsolid(cube, std::vector<Face>{}, 1.0), Error);
}

TEST_CASE("offset and draft") {
  const Solid body = box(10, 12, 14);
  CHECK(offset_rsolid(body, 1.0).volume() > body.volume());
  const Solid open = offset_rsolid(body, -1.0, std::vector<Face>{faces_facing(body, 2).front()});
  CHECK(open.volume() > 0);
  CHECK(open.volume() < body.volume());
  CHECK_THROWS_AS((void)offset_rsolid(body, 0.0), ValueError);
  CHECK_THROWS_AS((void)offset_rsolid(body, 1.0, {}, {1e-4, "X"}), ValueError);

  const Solid cube = box(10, 10, 10);
  const std::vector<Face> right{faces_facing(cube, 0).front()};
  for (const double angle : {10.0, -10.0, 0.0}) {
    CHECK(draft_rsolid(cube, right, angle).volume() == Approx(1000.0 - 500.0 * std::tan(angle * kPi / 180.0)));
  }
  CHECK_THROWS_AS((void)draft_rsolid(cube, right, 90.0), ValueError);
  CHECK_THROWS_AS((void)draft_rsolid(cube, std::vector<Face>{}, 5.0), ValueError);
  CHECK_THROWS_AS((void)draft_rsolid(cube, right, 5.0, scalar3(0, 0, 0), scalar3(0, 0, 0)), ValueError);
  const Solid other = box(1, 1, 1, scalar3(20, 0, 0));
  CHECK_THROWS_AS((void)draft_rsolid(cube, std::vector<Face>{faces_facing(other, 0).front()}, 5.0), ValueError);
}
