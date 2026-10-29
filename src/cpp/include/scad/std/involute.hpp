// Involute maths and the B-spline data of gear profiles (the helpers at the top of gear.py).
#pragma once

#include <cstddef>
#include <utility>
#include <vector>

namespace scad::stdlib {

// How many times the root-fillet and involute-fit helpers ran in this process: what the SDK's tests learn by
// patching the Python helper and counting its calls (a gear profile builds two canonical root fillets, not one per
// tooth).
std::size_t root_fillet_call_count() noexcept;
std::size_t involute_fit_call_count() noexcept;

struct Point2 {
  double x = 0.0;
  double y = 0.0;
};

// The point of the involute of a circle of `base_radius` at parameter `t`.
Point2 involute_point(double base_radius, double t);

// The involute parameter of the point at distance `target_radius` from the centre (0 inside the base circle).
double involute_t_for_radius(double base_radius, double target_radius);

// `p` rotated about the origin by `angle` radians.
Point2 rotate_xy(Point2 p, double angle);

// A clamped B-spline as a sketch takes it: poles, degree, distinct knots, multiplicities.
struct BSplineData {
  std::vector<Point2> control_points;
  int degree = 3;
  std::vector<double> knots;
  std::vector<int> multiplicities;
};

// One analytic involute flank from `start_radius` to `tip_radius`, fitted with the shared cubic
// B-spline fit (tolerance 1e-4) from 8 * n_segments + 1 samples, rotated by `start_angle`.
// `mirror` flips y first (the right flank); `reverse` runs the curve backwards.
BSplineData involute_bspline_control_points(double base_radius, double tip_radius, double start_radius,
                                            double start_angle, bool mirror, bool reverse = false, int n_segments = 6);

// A cubic Bezier from `start` to `end` leaving along `start_tangent_angle` and arriving along
// `end_tangent_angle`; handles are 0.45 of the chord.  The transition from the root circle to a flank.
BSplineData root_fillet_control_points(Point2 start, Point2 end, double start_tangent_angle, double end_tangent_angle);

// Tooth symmetry applied to an already fitted canonical flank: optional mirror about the x axis,
// rotation by `angle`, optional reversal of the pole order.
std::vector<Point2> transform_bspline_control_points(const std::vector<Point2>& control_points, double angle,
                                                     bool mirror = false, bool reverse = false);

// The knots and multiplicities of a curve run backwards.
std::pair<std::vector<double>, std::vector<int>> reverse_bspline_parameters(const std::vector<double>& unique_knots,
                                                                            const std::vector<int>& multiplicities);

}  // namespace scad::stdlib
