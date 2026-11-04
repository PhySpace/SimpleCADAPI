// The workplane constructors: frames from faces, points, axes, two faces and curves; what they record.
#include "support.hpp"

#include "scad/kernel/properties.hpp"
#include "scad/ops/geometry/executors.hpp"
#include "scad/ops/geometry/workplanes.hpp"
#include "scad/reactive/registry.hpp"

using namespace scad;
using namespace scad::geometry_test;

namespace {

void check_vec(const Vec3& actual, const Vec3& expected) {
  CHECK(actual.x == doctest::Approx(expected.x).epsilon(1e-9));
  CHECK(actual.y == doctest::Approx(expected.y).epsilon(1e-9));
  CHECK(actual.z == doctest::Approx(expected.z).epsilon(1e-9));
}

Face face_with_normal(const Solid& solid, const Vec3& normal) {
  for (const Face& face : solid.faces())
    if (face.normal_at().dot(normal) > 0.999)
      return face;
  FAIL("no face with that normal");
  return solid.faces().front();
}

}  // namespace

TEST_CASE("a workplane on a planar face: its centre, its outward normal, an offset, an x edge") {
  const Solid box = make_box_rsolid(10.0, 20.0, 5.0);
  const Face top = face_with_normal(box, {0, 0, 1});
  const Workplane on_top = make_workplane_from_face_rworkplane(top);
  check_vec(on_top.origin(), {0, 0, 5});
  check_vec(on_top.normal(), {0, 0, 1});

  const Workplane lifted = make_workplane_from_face_rworkplane(top, scalar3(3, 4, 99), std::nullopt, std::nullopt, 2.0);
  check_vec(lifted.origin(), {3, 4, 7});  // the given origin, projected onto the face, then moved along the normal

  const Face bottom = face_with_normal(box, {0, 0, -1});
  check_vec(make_workplane_from_face_rworkplane(bottom).normal(), {0, 0, -1});
  check_vec(make_workplane_from_face_rworkplane(bottom, std::nullopt, std::nullopt, std::nullopt, 0.0, true).normal(),
            {0, 0, 1});

  const Edge along_y = make_line_redge(scalar3(0, 0, 5), scalar3(0, 1, 5));
  const Workplane turned = make_workplane_from_face_rworkplane(top, std::nullopt, along_y);
  check_vec(turned.x_dir(), {0, 1, 0});
  check_vec(turned.y_dir(), {-1, 0, 0});
  CHECK_THROWS_AS(make_workplane_from_face_rworkplane(top, std::nullopt, along_y, scalar3(1, 0, 0)), Error);

  const Solid cylinder = make_cylinder_rsolid(2.0, 4.0);
  for (const Face& face : cylinder.faces()) {
    if (std::abs(face.normal_at().z) < 0.5) {
      CHECK_THROWS_AS(make_workplane_from_face_rworkplane(face), Error);  // not planar
    }
  }
}

TEST_CASE("three points, an axis turned by an angle, a midplane, a curve's normal plane") {
  const Workplane through = make_workplane_from_points_rworkplane(scalar3(1, 1, 1), scalar3(2, 1, 1), scalar3(1, 1, 3));
  check_vec(through.origin(), {1, 1, 1});
  check_vec(through.x_dir(), {1, 0, 0});
  check_vec(through.normal(), {0, -1, 0});
  CHECK_THROWS_AS(make_workplane_from_points_rworkplane(scalar3(0, 0, 0), scalar3(1, 0, 0), scalar3(2, 0, 0)), Error);
  const Vertex v(make_point_rvertex(0.0, 0.0, 7.0));
  check_vec(make_workplane_from_points_rworkplane(v, scalar3(1, 0, 7), scalar3(0, 1, 7)).origin(), {0, 0, 7});

  const Edge x_axis = make_line_redge(scalar3(0, 0, 0), scalar3(10, 0, 0));
  const Workplane flat = make_workplane_from_axis_rworkplane(x_axis);
  check_vec(flat.normal(), {0, 0, 1});  // global Z made square to the axis
  const Workplane tilted = make_workplane_from_axis_rworkplane(x_axis, 90.0);
  check_vec(tilted.normal(), {0, -1, 0});  // Z turned 90 degrees about +X
  check_vec(tilted.x_dir(), {1, 0, 0});
  const Edge ring = make_circle_redge(scalar3(0, 0, 3), 2.0, scalar3(0, 0, 1));
  const Workplane through_axis = make_workplane_from_axis_rworkplane(ring);
  check_vec(through_axis.origin(), {0, 0, 3});
  check_vec(through_axis.x_dir(), {0, 0, 1});

  const Solid box = make_box_rsolid(10.0, 20.0, 5.0);
  const Workplane middle =
      make_workplane_midplane_rworkplane(face_with_normal(box, {1, 0, 0}), face_with_normal(box, {-1, 0, 0}));
  check_vec(middle.origin(), {0, 0, 2.5});
  check_vec(middle.normal(), {1, 0, 0});
  CHECK_THROWS_AS(
      make_workplane_midplane_rworkplane(face_with_normal(box, {1, 0, 0}), face_with_normal(box, {0, 0, 1})), Error);

  const Workplane halfway = make_workplane_normal_to_curve_rworkplane(x_axis, 0.25);
  check_vec(halfway.origin(), {2.5, 0, 0});
  check_vec(halfway.normal(), {1, 0, 0});
  check_vec(make_workplane_normal_to_curve_rworkplane(x_axis, 1.0).origin(), {10, 0, 0});
  CHECK_THROWS_AS(make_workplane_normal_to_curve_rworkplane(x_axis, 1.5), Error);
}

TEST_CASE("a workplane is recorded with its inputs; an operation inside it names its node") {
  Recording recording;
  const Face face = make_rectangle_rface(4.0, 2.0, scalar3(0, 0, 3));
  const Workplane wp = make_workplane_from_face_rworkplane(face);
  const auto& nodes = recording.session.graph().nodes();
  const auto& made = *nodes.back();
  CHECK(made.op == "make_workplane_from_face_rworkplane");
  CHECK(made.params.find("input_refs")->size() == 1);
  CHECK(made.params.find("frame")->find("origin")->dump() == "[0,0,3]");
  CHECK(wp.get_runtime("graph.node_id").as_string() == made.node_id);

  Workplane entered(wp);
  entered.enter();
  make_box_rsolid(1.0, 1.0, 1.0);
  entered.exit();
  const auto& inside = *recording.session.graph().nodes().back();
  REQUIRE(inside.context);
  CHECK(inside.context->find("workplane")->find("node_id")->as_string() == made.node_id);
  CHECK(inside.context->find("origin")->dump() == "[0,0,3]");
}

TEST_CASE("the workplane constructors have (value) executors") {
  reactive::ExecutorRegistry registry(false);
  register_geometry_executors(registry);
  for (const char* op : {"make_workplane_rworkplane", "make_workplane_from_face_rworkplane",
                         "make_workplane_from_points_rworkplane", "make_workplane_from_axis_rworkplane",
                         "make_workplane_midplane_rworkplane", "make_workplane_normal_to_curve_rworkplane"}) {
    CHECK_MESSAGE(registry.contains(op), op);
  }
}
