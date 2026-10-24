// union, cut, intersect, the set boolean and the 2D booleans.
#include "fixtures.hpp"
#include "scad/semantic/tracking.hpp"

using namespace scad;
using namespace scad::feature_test;
using doctest::Approx;

TEST_CASE("union of overlapping boxes keeps the operands' tags") {
  const Solid a = box(2, 2, 2), b = box(1, 1, 3, scalar3(0.5, 0.5, 0));
  a.faces().front().apply_tag("role.a_face");
  const Solid merged = union_rsolid({a, b});
  CHECK(merged.volume() == Approx(9.0));
  CHECK(union_rsolid({a, b}, {.tracking_policy = "graph"}).volume() == Approx(9.0));
  CHECK(union_rsolid({a}).volume() == Approx(8.0));
  CHECK(union_rsolid({a}, {.clean = false}).same_entity(a));
}

TEST_CASE("union of face-touching boxes is cleaned to one box") {
  const Solid touching = union_rsolid({box(1, 1, 1), box(1, 1, 1, scalar3(1, 0, 0))});
  CHECK(touching.volume() == Approx(2.0));
  CHECK(touching.faces().size() == 6);
}

TEST_CASE("union across a small gap needs a tolerance") {
  const Solid left = box(1, 1, 1), right = box(1, 1, 1, scalar3(1.0001, 0, 0));
  const Error error = failure_of([&] { (void)union_rsolid({left, right}); });
  CHECK(error.guidance().what_happened.find("nearest detected gap") != std::string::npos);
  CHECK(union_rsolid({left, right}, {.tol = 0.0001}).volume() == Approx(2.0001).epsilon(1e-6));
  CHECK_THROWS_AS((void)union_rsolid({left, right}, {.tol = -1.0}), Error);
}

TEST_CASE("union failures carry measurements and repair") {
  const Solid base = box(10, 4, 4), distant = box(2, 4, 4, scalar3(20, 0, 0));
  const Error disjoint = failure_of([&] { (void)union_rsolid({base, distant}); });
  CHECK(disjoint.operation() == "union_rsolid");
  CHECK(measurement(disjoint, "min_gap") == Approx(14.0));
  const std::string text = disjoint.what();
  CHECK(text.find("- min_gap: 14 mm") != std::string::npos);
  CHECK(text.find("closure_vector_a_to_b: (14, 0, 0) mm") != std::string::npos);

  const Error edge = failure_of([&] { (void)union_rsolid({box(2, 2, 2), box(2, 2, 2, scalar3(2, 2, 0))}); });
  CHECK(edge.guidance().what_happened.find("edge, vertex, or tangent") != std::string::npos);

  const Solid b = box(10, 4, 4, scalar3(3, 0, 0));
  const Error cluster = failure_of([&] { (void)union_rsolid({base, b, distant}); });
  CHECK(cluster.guidance().what_happened.find("operand 2 and operand 3") != std::string::npos);
  CHECK(measurement(cluster, "min_gap") == Approx(11.0));

  CHECK_THROWS_AS((void)union_rsolid({}), Error);
  CHECK(failure_of([&] { reject_boolean_operand("union_rsolid"); }).operation() == "union_rsolid");
}

TEST_CASE("cut and intersect") {
  const Solid cube = box(10, 20, 30), hole = make_cylinder_rsolid(4, 40);
  const double through = kPi * 16 * 30;
  const Solid cut = cut_rsolid({cube, hole});
  CHECK(cut.volume() == Approx(6000.0 - through));
  CHECK(has_tag(cut, "solid.boolean.cut"));
  CHECK(intersect_rsolid({cube, hole}).volume() == Approx(through));
  CHECK(has_tag(intersect_rsolid({cube, hole}), "solid.boolean.intersect"));
  CHECK(cut_rsolid({cube, hole}, {.tracking_policy = "graph"}).volume() == Approx(6000.0 - through));

  const Solid distant = box(2, 4, 4, scalar3(50, 0, 0));
  CHECK(cut_rsolid({cube, distant}).volume() == Approx(6000.0));
  const Error strict = failure_of([&] { (void)cut_rsolid({cube, distant}, {.skip_non_intersecting = false}); });
  CHECK(strict.operation() == "cut_rsolid");
  CHECK(!strict.guidance().repair.empty());
  CHECK(failure_of([&] { (void)intersect_rsolid({cube, distant}); }).operation() == "intersect_rsolid");
}

TEST_CASE("the set boolean keeps every piece") {
  const Solid base = box(10, 2, 2), tool = box(2, 4, 4, scalar3(0, 0, -1));
  const std::vector<Solid> pieces = boolean_rsolidlist({base}, {tool}, "cut");
  REQUIRE(pieces.size() == 2);
  CHECK(pieces[0].volume() == Approx(16.0));
  CHECK(pieces[1].volume() == Approx(16.0));
  CHECK(boolean_rsolidlist({base}, {base}, "cut").empty());
  CHECK(boolean_rsolidlist({base}, {tool}, "union").size() == 1);
  CHECK(boolean_rsolidlist({base}, {tool}, "intersect").size() == 1);
  CHECK_THROWS_AS((void)boolean_rsolidlist({base}, {tool}, "xor"), ValueError);
}

TEST_CASE("2D booleans") {
  const Face a = make_rectangle_rface(4, 4), b = make_rectangle_rface(2, 2, scalar3(1, 1, 0));
  CHECK(make_2d_cut_rface(a, b).area() == Approx(12.0));
  CHECK(make_2d_union_rface(a, b).area() == Approx(16.0 + 4.0 - 1.0 - 0.0 - 3.0).epsilon(1e-6) );
  CHECK(make_2d_intersect_rface(a, b).area() == Approx(4.0));
  CHECK(make_2d_cut_rface(a, make_rectangle_rface(1, 1)).inner_wires().size() == 1);
  CHECK(failure_of([&] { (void)make_2d_cut_rface(a, box(1, 1, 1)); }).operation() == "make_2d_cut_rface");
}

TEST_CASE("a graph-policy boolean asks the kernel for no topology history") {
  const Solid body = box(6, 6, 6), cutter = box(2, 2, 12, scalar3(2, 2, -3)), rib = box(2, 2, 2, scalar3(3, 0, 0));
  const std::size_t before = tracking::history_query_count();
  CHECK(cut_rsolid({body, cutter}, {.tracking_policy = "graph"}).volume() < body.volume());
  CHECK(union_rsolid({body, rib}, {.glue = false, .tracking_policy = "graph"}).volume() > body.volume());
  CHECK(tracking::history_query_count() == before);
  (void)cut_rsolid({body, cutter});  // the default policy does ask
  CHECK(tracking::history_query_count() > before);
}
