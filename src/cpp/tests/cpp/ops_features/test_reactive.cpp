// The operators in a reactive Session: an edited parameter reruns only what depends on it.
#include <algorithm>

#include "fixtures.hpp"
#include "scad/ops/geometry/executors.hpp"
#include "scad/reactive/lineage.hpp"
#include "scad/reactive/session.hpp"

using namespace scad;
using namespace scad::feature_test;
using doctest::Approx;

namespace {

bool ran(const reactive::RecomputeReport& report, const Shape& shape) {
  const std::string id = reactive::lineage_of(shape)->node_id;
  return std::find(report.executed.begin(), report.executed.end(), id) != report.executed.end();
}

// Volume of the same model built directly, without a session.
double direct_volume(double radius) {
  const Solid cube = box(10, 20, 30);
  const Solid rounded = fillet_rsolid(cube, edges_at_z(cube, 30.0), radius);
  return cut_rsolid({rounded, make_cylinder_rsolid(2, 50, scalar3(0, 0, -5))}).volume();
}

}  // namespace

TEST_CASE("changing the fillet radius reruns the fillet and the cut, not the box") {
  reactive::ExecutorRegistry registry;
  register_geometry_executors(registry);
  register_features_executors(registry);
  reactive::Session::Options options;
  options.registry = &registry;
  reactive::Session session(options);

  const reactive::Sym radius = reactive::make_var("radius", 1.0);
  session.start();
  const Solid cube = box(10, 20, 30);
  const Solid rounded = fillet_rsolid(cube, edges_at_z(cube, 30.0), radius.scalar());
  const Solid hole = make_cylinder_rsolid(2, 50, scalar3(0, 0, -5));
  const Solid cut = cut_rsolid({rounded, hole});
  session.stop();
  CHECK(cut.volume() == Approx(direct_volume(1.0)));

  session.set_var("radius", 3.0);
  const reactive::RecomputeReport report = session.recompute();
  REQUIRE(report.ok());
  CHECK(ran(report, rounded));
  CHECK(ran(report, cut));
  CHECK_FALSE(ran(report, cube));
  CHECK_FALSE(ran(report, hole));
  CHECK(Solid(session.current(cut)).volume() == Approx(direct_volume(3.0)));
}

TEST_CASE("a recorded extrude, boolean and transform chain replays from its parameters") {
  reactive::ExecutorRegistry registry;
  register_geometry_executors(registry);
  register_features_executors(registry);
  reactive::Session::Options options;
  options.registry = &registry;
  reactive::Session session(options);

  const reactive::Sym height = reactive::make_var("height", 2.0);
  session.start();
  const Solid prism = extrude_rsolid(make_rectangle_rface(2, 2), scalar3(0, 0, 1), height.scalar());
  const Solid pad = union_rsolid({prism, box(2, 2, 1, scalar3(1, 0, 0))});
  const Solid scaled = scale_rsolid(pad, scalar3(1, 1, 2));
  const Shape moved = translate_shape(scaled, scalar3(0, 0, 1));
  session.stop();

  session.set_var("height", 4.0);
  REQUIRE(session.recompute().ok());
  const Solid after(session.current(moved));
  CHECK(after.volume() == Approx(2.0 * (2 * 2 * 4 + 2 * 2 * 1 - 1 * 2 * 1)));
}
