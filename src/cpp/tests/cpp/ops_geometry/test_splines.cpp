// B-spline makers and the argument normalisers they share.
#include "support.hpp"

#include "scad/ops/geometry/bspline_args.hpp"

using namespace scad;
using namespace scad::geometry_test;

namespace {

std::vector<ScalarPoint> poles() {
  return {{0.0, 0.0, 0.0}, {0.6, 1.0, 0.0}, {1.4, 1.0, 0.0}, {2.0, 0.0, 0.0}};
}

std::string what(const std::unique_ptr<Error>& error) {
  return error ? error->guidance().technical_details : std::string("(no error)");
}

}  // namespace

TEST_CASE("make_spline_redge builds a clamped cubic by default") {
  const Edge spline = make_spline_redge({.control_points = poles()});
  CHECK(spline.length() > 2.0);
  check_box(spline, {0, 0, 0}, {2, 0.75, 0}, 1e-6);
  const Value& geo = spline.get_metadata("geo");
  CHECK(geo.find("type")->as_string() == "bspline");
  CHECK(geo.find("degree")->as_int() == 3);
  CHECK(geo.find("multiplicities")->dump() == "[4,4]");
  CHECK(geo.find("weights")->is_null());
  CHECK(make_spline_rwire({.control_points = poles()}).edges().size() == 1);

  const Edge rational = make_spline_redge({.control_points = poles(), .weights = ScalarList{1.0, 2.0, 2.0, 1.0}});
  CHECK(rational.get_metadata("geo").find("weights")->dump() == "[1,2,2,1]");
  const Edge planar = make_spline_redge({.control_points = {{0.0, 0.0}, {1.0, 2.0}, {2.0, 0.0}}, .degree = 2});
  check_box(planar, {0, 0, 0}, {2, 1, 0}, 1e-6);
}

TEST_CASE("spline definitions are validated with the Python messages") {
  const auto fails = [](SplineSpec spec) { return failure_of([&] { make_spline_redge(spec); }); };
  CHECK(what(fails({.control_points = poles(), .degree = 2.5})) == "ValueError: degree must be an integer");
  CHECK(what(fails({.control_points = poles(), .degree = std::nan("")})) == "ValueError: degree must be an integer");
  CHECK(what(fails({.control_points = poles(), .degree = 0})) == "ValueError: degree must be at least 1");
  CHECK(what(fails({.control_points = poles(), .degree = 30})) == "ValueError: degree must be 25 or lower");
  CHECK(what(fails({.control_points = {}})) == "ValueError: control_points must contain at least one point");
  CHECK(what(fails({.control_points = {{0.0}, {1.0}, {2.0}, {3.0}}})) ==
        "ValueError: control point 0 must be 2D or 3D");
  CHECK(what(fails({.control_points = {{0.0, 0.0}, {1.0, 1.0}, {2.0, 0.0}}})) ==
        "ValueError: control point count must be at least degree + 1");
  CHECK(what(fails({.control_points = poles(), .multiplicities = std::vector<int>{4, 4}})) ==
        "ValueError: multiplicities require explicit knots");
  CHECK(what(fails({.control_points = poles(), .weights = ScalarList{1.0, 0.0, 1.0, 1.0}})) ==
        "ValueError: weights must be finite positive values");
  CHECK(fails({.control_points = {}})->operation() == "make_spline_redge");
  CHECK(failure_of([] { make_spline_rwire({.control_points = {}}); })->operation() == "make_spline_redge");
}

TEST_CASE("knot normalisation") {
  const auto collapsed = bspline::collapse_knot_vector({0.0, 0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0, 1.0});
  CHECK(collapsed.unique == std::vector<double>{0.0, 0.5, 1.0});
  CHECK(collapsed.multiplicities == std::vector<int>{4, 1, 4});
  CHECK(bspline::default_knots(5, 3, false).multiplicities == std::vector<int>{4, 1, 4});
  CHECK(bspline::default_knots(4, 3, true).unique.size() == 5);
  CHECK(bspline::default_knots(4, 3, false).multiplicities == std::vector<int>{4, 4});
  CHECK_THROWS_WITH_AS(bspline::default_knots(3, 3, false), "control point count must be at least degree + 1",
                       ValueError);
  CHECK_THROWS_WITH_AS(bspline::normalize_knots(4, 3, false, ScalarList{0.0, 1.0}, std::vector<int>{3, 4}),
                       "sum(multiplicities) must equal 8 for this non-periodic B-spline", ValueError);
  CHECK_THROWS_WITH_AS(bspline::normalize_knots(4, 3, true, ScalarList{0.0, 0.5, 1.0}, std::vector<int>{1, 1, 1}),
                       "sum(multiplicities) must equal 5 for this periodic B-spline", ValueError);
  CHECK_THROWS_WITH_AS(bspline::collapse_knot_vector({0.0, 1.0, 0.5}),
                       "knots must be non-decreasing when passed as a full knot vector", ValueError);
  CHECK(bspline::normalize_weights(std::nullopt, 4) == std::nullopt);
}

TEST_CASE("interpolated splines") {
  const std::vector<ScalarPoint> points{{0.0, 0.0, 0.0}, {1.0, 2.0, 0.0}, {2.0, 0.0, 1.0}, {3.0, 2.0, 0.0}};
  const Edge open = make_interpolated_spline_redge({.points = points});
  CHECK(open.length() > 3.0);
  CHECK(open.get_metadata("geo").find("construction")->as_string() == "interpolated");
  CHECK(open.vertices().front().coordinates().x == doctest::Approx(0.0));
  CHECK(open.vertices().back().coordinates().x == doctest::Approx(3.0));

  const std::vector<ScalarPoint> loop{{0.0, 0.0, 0.0}, {2.0, 0.0, 0.0}, {2.0, 2.0, 0.0}, {0.0, 2.0, 0.0}};
  CHECK(make_periodic_spline_rwire(loop).is_closed());
  // A repeated closing point is accepted and dropped.
  std::vector<ScalarPoint> repeated = loop;
  repeated.push_back(loop.front());
  CHECK(make_interpolated_spline_rwire({.points = repeated, .periodic = true}).is_closed());

  CHECK(what(failure_of([] { make_interpolated_spline_redge({.points = {{0.0, 0.0, 0.0}}}); })) ==
        "ValueError: interpolation requires at least 2 points");
  CHECK(what(failure_of([] {
          make_interpolated_spline_redge({.points = {{0.0, 0.0, 0.0}, {1.0, 0.0, 0.0}}, .periodic = true});
        })) == "ValueError: interpolation requires at least 3 distinct points");
  CHECK(what(failure_of([] {
          make_interpolated_spline_redge({.points = {{0.0, 0.0, 0.0}, {0.0, 0.0, 0.0}, {1.0, 0.0, 0.0}}});
        })) == "ValueError: interpolation points 0 and 1 are within the interpolation tolerance");
  CHECK(what(failure_of([] {
          make_interpolated_spline_redge({.points = {{0.0, 0.0, 0.0}, {1.0, 0.0, 0.0}}, .tolerance = Scalar(0.0)});
        })) == "ValueError: tolerance must be a finite positive value");
}
