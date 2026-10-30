// trim_surface_rface: planar and periodic carriers, holes, and the rejections.
#include "doctest.h"

#include <cmath>
#include <functional>

#include "scad/core/error.hpp"
#include "scad/surface/operators.hpp"
#include "support.hpp"

using namespace scad;
using namespace surface_test;

namespace {

bool message_has(const std::function<void()>& body, const std::string& needle) {
  try {
    body();
  } catch (const std::exception& e) {
    return std::string(e.what()).find(needle) != std::string::npos;
  }
  return false;
}

Face carrier() {
  return make_bezier_surface_rface(carrier_grid());
}

Vec3 on_cylinder(double radius, double angle, double z) {
  return {radius * std::cos(angle), radius * std::sin(angle), z};
}

Wire cylinder_patch(double radius, double from, double to) {
  return wire_of(
      {arc(on_cylinder(radius, from, 0), on_cylinder(radius, (from + to) / 2, 0), on_cylinder(radius, to, 0)),
       line(on_cylinder(radius, to, 0), on_cylinder(radius, to, 2)),
       arc(on_cylinder(radius, to, 2), on_cylinder(radius, (from + to) / 2, 2), on_cylinder(radius, from, 2)),
       line(on_cylinder(radius, from, 2), on_cylinder(radius, from, 0))});
}

}  // namespace

TEST_CASE("trim keeps the face's carrier and takes the loop's area") {
  const Face trimmed = trim_surface_rface(carrier(), rectangle(4, 4), {.tag_prefix = "trimmed"});
  CHECK(trimmed.area() == doctest::Approx(16.0).epsilon(1e-6));
  CHECK(trimmed.has_tag("trimmed.face", TagScope::Local));
  CHECK(trimmed.wires().size() == 1);
}

TEST_CASE("trim with a hole, and a second trim that keeps the carrier's own hole") {
  const Face holed = trim_surface_rface(carrier(), rectangle(4, 4), {.holes = {rectangle(1, 1)}});
  CHECK(holed.area() == doctest::Approx(15.0).epsilon(1e-6));
  CHECK(holed.wires().size() == 2);

  const Face bounded = trim_surface_rface(carrier(), rectangle(4, 4), {.holes = {rectangle(2, 2)}});
  const Face again = trim_surface_rface(bounded, rectangle(3, 3));
  CHECK(again.area() == doctest::Approx(5.0).epsilon(1e-6));
  CHECK(again.inner_wires().size() == 1);
}

TEST_CASE("trim intersects with the carrier's bounds") {
  const Face backing = trim_surface_rface(carrier(), rectangle(4, 4));
  CHECK(trim_surface_rface(backing, rectangle(2, 4, 1.5, 0)).area() == doctest::Approx(6.0).epsilon(1e-6));
}

TEST_CASE("trim reports empty and disconnected intersections like the reference") {
  const Face big = make_bezier_surface_rface({{{-4, -4, 0}, {-4, 4, 0}}, {{4, -4, 0}, {4, 4, 0}}});
  const Face bounded = trim_surface_rface(big, rectangle(6, 6), {.holes = {rectangle(2, 4)}});
  CHECK(message_has([&] { (void)trim_surface_rface(bounded, rectangle(1, 1)); },
                    "exactly one connected Face; intersection is empty"));
  CHECK(message_has([&] { (void)trim_surface_rface(bounded, rectangle(4, 2)); },
                    "exactly one connected Face; intersection produced 2 disconnected Faces"));
}

TEST_CASE("trim rejects open, self-intersecting and off-carrier wires") {
  CHECK(message_has([] { (void)trim_surface_rface(carrier(), wire_of({line({-1, 0, 0}, {1, 0, 0})})); },
                    "must be closed"));
  CHECK(message_has(
      [] { (void)trim_surface_rface(carrier(), polygon({{-2, -2, 0}, {2, 2, 0}, {-2, 2, 0}, {2, -2, 0}})); },
      "must be simple"));
  CHECK(message_has([] { (void)trim_surface_rface(carrier(), rectangle(4, 4, 0, 0, 1)); }, "trim"));
  CHECK(message_has([] { (void)trim_surface_rface(carrier(), rectangle(4, 4), {.tolerance = 0.0}); },
                    "tolerance must be a positive finite value"));
}

TEST_CASE("periodic carrier: a patch trims, holes and seam crossings are rejected") {
  const Face cylinder = make_cylindrical_surface_rface(2.0, {0.0, 2 * kPi}, {0.0, 2.0});
  const Face trimmed = trim_surface_rface(cylinder, cylinder_patch(2.0, 0.5, 2.5));
  CHECK(trimmed.area() == doctest::Approx(8.0).epsilon(1e-5));
  CHECK(message_has(
      [&] {
        (void)trim_surface_rface(cylinder, rectangle(1, 1, 2.0, 0, 1), {.holes = {rectangle(0.25, 0.25, 2.0, 0, 1)}});
      },
      "holes is not supported"));

  const Face partial = make_cylindrical_surface_rface(2.0, {0.0, 1.0}, {0.0, 2.0});
  CHECK(message_has([&] { (void)trim_surface_rface(partial, cylinder_patch(2.0, 2.0, 2.5)); }, "bounded carrier"));
}
