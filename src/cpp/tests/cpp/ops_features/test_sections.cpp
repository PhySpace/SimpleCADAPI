// loft, sweep, twisted sweep, helical sweep, multi-section sweep.
#include "fixtures.hpp"

using namespace scad;
using namespace scad::feature_test;
using doctest::Approx;

TEST_CASE("loft between two rectangles") {
  const Wire r1 = make_rectangle_rwire(4, 4), r2 = make_rectangle_rwire(2, 2, scalar3(0, 0, 3));
  LoftOptions options;
  options.tags.start_face_tag = "role.s";
  options.tags.side_faces_tag = "role.sides";
  options.tags.tag_prefix = "body";
  const Solid frustum = loft_rsolid({r1, r2}, false, options);
  CHECK(frustum.volume() == Approx(28.0));
  CHECK(count_tagged(frustum.faces(), "role.s") == 1);
  CHECK(count_tagged(frustum.faces(), "role.sides") == 4);

  LoftOptions graph;
  graph.tracking_policy = "graph";
  CHECK(loft_rsolid({r1, r2}, false, graph).volume() == Approx(28.0));
  graph.tags.tag_prefix = "x";
  CHECK(failure_of([&] { (void)loft_rsolid({r1, r2}, false, graph); }).operation() == "loft_rsolid");

  const Vertex tip = make_point_rvertex(0, 0, 6);
  CHECK(loft_rsolid({r1, tip}).volume() == Approx(16.0 * 6 / 3));
}

TEST_CASE("a failing loft says which stations are the problem") {
  const Wire rect = make_rectangle_rwire(4, 4);
  const Error coincident = failure_of([&] { (void)loft_rsolid({rect, make_rectangle_rwire(4, 4)}); });
  CHECK(coincident.guidance().what_happened.find("S2 coincides with S1") != std::string::npos);
  std::vector<std::string> implicated;
  for (const InventoryEntry& entry : coincident.guidance().inventory) {
    if (entry.status == "implicated")
      implicated.push_back(entry.symbol);
  }
  CHECK(implicated == std::vector<std::string>{"S1", "S2"});

  const Wire open = make_wire_from_edges_rwire(
      {make_line_redge(scalar3(0, 0, 0), scalar3(10, 0, 0)), make_line_redge(scalar3(10, 0, 0), scalar3(10, 6, 0))});
  const Error not_closed = failure_of([&] { (void)loft_rsolid({rect, open}); });
  CHECK(not_closed.guidance().inventory.at(1).status == "implicated");
  CHECK(failure_of([&] { (void)loft_rsolid({rect}); }).operation() == "loft_rsolid");
}

TEST_CASE("sweep along a path and the twisted sweep") {
  const Face profile = make_circle_rface(scalar3(0, 0, 0), 1.0);
  const Wire straight = make_segment_rwire(scalar3(0, 0, 0), scalar3(0, 0, 5));
  SweepTags tags;
  tags.start_face_tag = "role.s";
  const Solid pipe = sweep_rsolid(profile, straight, false, tags);
  CHECK(pipe.volume() == Approx(5 * kPi));
  CHECK(count_tagged(pipe.faces(), "role.s") == 1);

  const Face square = make_rectangle_rface(2, 1);
  const Solid twisted = twisted_sweep_rsolid(square, 4.0, 90.0);
  CHECK(twisted.volume() == Approx(8.0).epsilon(1e-3));
  CHECK(twisted.get_metadata("twisted_sweep.kernel").is_object());
  CHECK_THROWS_AS((void)twisted_sweep_rsolid(square, 0.0, 10.0), Error);
  CHECK_THROWS_AS((void)twisted_sweep_rsolid(profile.outer_wire(), 1.0, 10.0), Error);
}

TEST_CASE("helical sweep") {
  const Wire profile = make_wire_from_edges_rwire({make_circle_redge(scalar3(3.4, 0, 0), 0.3)});
  const Solid spring = helical_sweep_rsolid(profile, 2.0, 6.0, 3.0);
  CHECK(spring.volume() > 1.0);
  CHECK(has_tag(spring, "solid.feature.helical_sweep"));
  CHECK_THROWS_AS((void)helical_sweep_rsolid(profile, 0.0, 6.0, 3.0), Error);
}

TEST_CASE("multi-section sweep") {
  const Wire path = make_segment_rwire(scalar3(0, 0, 0), scalar3(0, 0, 6));
  const std::vector<Shape> sections{make_rectangle_rwire(4, 4), make_rectangle_rwire(2, 2, scalar3(0, 0, 6))};
  CHECK(sweep_multisection_rsolid(sections, path).volume() == Approx(56.0).epsilon(1e-3));
  CHECK(sweep_multisection_rsolid(sections, path, false, Binormal(scalar3(1, 0, 0))).volume() > 0);
  CHECK_THROWS_AS((void)sweep_multisection_rsolid({sections[0]}, path), ValueError);
}
