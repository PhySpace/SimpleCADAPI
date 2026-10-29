// make_box_rsolid, make_cylinder_rsolid, make_cone_rsolid, make_sphere_rsolid.
#include "support.hpp"

#include <algorithm>

#include "scad/reactive/expr.hpp"

using namespace scad;
using namespace scad::geometry_test;

TEST_CASE("make_box_rsolid places the box on its bottom face centre") {
  const Solid box = make_box_rsolid(10, 20, 30);
  CHECK(box.volume() == doctest::Approx(6000.0));
  CHECK(box.faces().size() == 6);
  CHECK(box.edges().size() == 12);
  check_box(box, {-5, -10, 0}, {5, 10, 30});
  CHECK(has_tag(box, "geom.primitive.box"));
  CHECK(has_tag(box, "box"));
  CHECK(box.get_metadata("track").find("op")->as_string() == "make_box_rsolid");
  CHECK(box.get_metadata("geo").find("type")->as_string() == "box");

  const Solid moved = make_box_rsolid(2, 3, 4, scalar3(5, -1, 2));
  check_box(moved, {4, -2.5, 2}, {6, 0.5, 6});
}

TEST_CASE("make_box_rsolid follows the current coordinate system") {
  const Workplane plane({1, 2, 3}, {0, 1, 0}, {1, 0, 0});
  CoordinateSystemScope scope(plane.cs());
  const Solid box = make_box_rsolid(2, 3, 4);
  // normal +Y: the box rises along the workplane's z, which is the world's +Y.
  const auto b = box.bounding_box();
  CHECK(b.ylen() == doctest::Approx(4.0));
  CHECK(b.xlen() == doctest::Approx(2.0));
}

TEST_CASE("make_box_rsolid names faces by role, prefix and result tag") {
  const Solid box = make_box_rsolid(2, 3, 4, scalar3(0, 0, 0),
                                    {.tag_prefix = "housing",
                                     .result_tag = "part.housing",
                                     .bottom_face_tag = "anchor.base",
                                     .right_face_tag = "role.mounting_surface"});
  const std::vector<Face> faces = box.faces();
  CHECK(count_with_tag(faces, "housing.face.top") == 1);
  CHECK(count_with_tag(faces, "housing.face.front") == 1);
  CHECK(count_with_tag(faces, "anchor.base") == 1);
  CHECK(count_with_tag(faces, "role.mounting_surface") == 1);
  CHECK(has_tag(box, "housing.solid"));
  CHECK(has_tag(box, "part.housing"));
}

TEST_CASE("make_box_rsolid fails as the operator, with the Python guidance") {
  const auto bad_size = failure_of([] { make_box_rsolid(0, 1, 1); });
  REQUIRE(bad_size);
  CHECK(bad_size->operation() == "make_box_rsolid");
  CHECK(bad_size->guidance().what_happened == "Failed to create a box solid.");
  CHECK(bad_size->guidance().possible_causes.size() == 3);
  CHECK(bad_size->guidance().technical_details == "ValueError: width, height, and depth must be greater than zero.");

  const auto bad_tag = failure_of([] { make_box_rsolid(1, 1, 1, scalar3(0, 0, 0), {.bottom_face_tag = "BAD TAG"}); });
  REQUIRE(bad_tag);
  CHECK(bad_tag->guidance().technical_details == "ValueError: tag 'BAD TAG' is not normalized");

  CHECK(failure_of([] { make_box_rsolid(Scalar(std::nan("")), 1, 1); }));
}

TEST_CASE("make_cylinder_rsolid has kernel face and edge roles") {
  const Solid cylinder =
      make_cylinder_rsolid(2.0, 5.0, scalar3(0, 0, 0), scalar3(0, 0, 1),
                           {.tag_prefix = "shaft", .start_face_tag = "role.base", .seam_edge_tag = "role.seam"});
  CHECK(cylinder.volume() == doctest::Approx(kPi * 4 * 5));
  CHECK(cylinder.faces().size() == 3);
  CHECK(count_with_tag(cylinder.faces(), "shaft.face.start") == 1);
  CHECK(count_with_tag(cylinder.faces(), "role.base") == 1);
  CHECK(count_with_tag(cylinder.edges(), "shaft.edge.seam") == 1);
  CHECK(count_with_tag(cylinder.edges(), "role.seam") == 1);

  const Solid sideways = make_cylinder_rsolid(1.5, 4.0, scalar3(1, 2, 3), scalar3(1, 0, 0));
  check_box(sideways, {1, 0.5, 1.5}, {5, 3.5, 4.5}, 1e-6);
  CHECK(failure_of([] { make_cylinder_rsolid(-1, 2); }));
}

TEST_CASE("make_cone_rsolid builds cones and frustums") {
  const Solid cone = make_cone_rsolid(2.0, 3.0);
  CHECK(cone.volume() == doctest::Approx(kPi * 4 * 3 / 3));
  CHECK(has_tag(cone, "geom.primitive.cone"));
  CHECK(cone.faces().size() == 2);

  const Solid frustum = make_cone_rsolid(3.0, 4.0, 1.0);
  CHECK(frustum.volume() == doctest::Approx(kPi * 4 * (9 + 3 + 1) / 3));
  CHECK(frustum.faces().size() == 3);

  const Solid named = make_cone_rsolid(2.0, 4.0, 1.0, scalar3(0, 0, 0), scalar3(0, 0, 1),
                                       {.tag_prefix = "adapter", .end_face_tag = "role.outlet"});
  CHECK(count_with_tag(named.faces(), "adapter.face.end") == 1);
  CHECK(count_with_tag(named.faces(), "role.outlet") == 1);
}

TEST_CASE("a pointed cone has no end face to tag") {
  const auto error = failure_of(
      [] { make_cone_rsolid(2.0, 4.0, 0.0, scalar3(0, 0, 0), scalar3(0, 0, 1), {.end_face_tag = "role.outlet"}); });
  REQUIRE(error);
  CHECK(error->operation() == "semantic_query");
  CHECK(error->guidance().what_happened.find("requires exactly one kernel-proven result, got 0") != std::string::npos);
}

TEST_CASE("make_sphere_rsolid") {
  const Solid sphere = make_sphere_rsolid(2.5, scalar3(1, 2, 3));
  CHECK(sphere.volume() == doctest::Approx(4.0 / 3 * kPi * 2.5 * 2.5 * 2.5).epsilon(1e-6));
  CHECK(has_tag(sphere, "geom.primitive.sphere"));
  CHECK(sphere.get_metadata("geo").find("radius")->as_double() == 2.5);
  CHECK(sphere.center().x == doctest::Approx(1.0));
  const auto error = failure_of([] { make_sphere_rsolid(0); });
  REQUIRE(error);
  CHECK(error->operation() == "make_sphere_rsolid");
}

TEST_CASE("primitives record their parameters and symbolic scalars") {
  Recording recording;
  const reactive::Sym w = reactive::make_var("w", 10.0);
  const Solid box = make_box_rsolid(w.scalar(), 2.0, 3.0, scalar3(0, 0, 0), {.tag_prefix = "b"});
  const Solid cone = make_cone_rsolid(2, 4, (w * 0.1).scalar());
  make_sphere_rsolid(1.5);

  const auto& nodes = recording.session.graph().nodes();
  REQUIRE(nodes.size() >= 3);
  CHECK(nodes[0]->op == "make_box_rsolid");
  CHECK(nodes[0]->params.find("width")->as_double() == 10.0);
  CHECK(nodes[0]->symbolic.size() == 1);
  CHECK(nodes[0]->symbolic[0].first == "width");
  // The prefix tags are separate recorded assignments, like Python's.
  const std::vector<std::string> ops = recording.ops();
  CHECK(ops.back() == "make_sphere_rsolid");
  CHECK(std::count(ops.begin(), ops.end(), "apply_tag_rselection") >= 1);
  (void)box;
  (void)cone;
}
