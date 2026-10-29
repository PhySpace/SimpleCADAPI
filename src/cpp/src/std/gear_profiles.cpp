#include "scad/core/tolerance.hpp"
#include "scad/std/gear_profiles.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <string>

#include "scad/core/vec.hpp"
#include "scad/ops/features/support.hpp"
#include "scad/ops/geometry/geometry.hpp"
#include "scad/reactive/bspline_fit.hpp"
#include "scad/sketch/operators.hpp"
#include "scad/std/involute.hpp"
#include "sketch_builder.hpp"

namespace scad::stdlib {

namespace {

std::string tooth_point(int tooth, const char* key) {
  return "t" + std::to_string(tooth) + "_" + key;
}

std::string numbered(const char* stem, int index) {
  return std::string(stem) + std::to_string(index);
}

void add_point(SketchBuilder& sketch, int tooth, const char* key, Point2 p) {
  sketch.point(tooth_point(tooth, key), p.x, p.y);
}

Point2 polar(double radius, double angle) {
  return {radius * std::cos(angle), radius * std::sin(angle)};
}

// The three construction circles of a gear sketch, in the order the factories add them.
void add_construction_circles(SketchBuilder& sketch, const char* first, double first_radius, const char* second,
                              double second_radius, const char* third, double third_radius) {
  sketch.point("center", 0.0, 0.0);
  sketch.fix("center");
  sketch.circle(first, "center", first_radius, true);
  sketch.circle(second, "center", second_radius, true);
  sketch.circle(third, "center", third_radius, true);
  sketch.radius(first, first_radius);
  sketch.radius(second, second_radius);
  sketch.radius(third, third_radius);
  sketch.concentric(first, second);
  sketch.concentric(third, second);
}

}  // namespace

// ---------------------------------------------------------------------------
// External gear
// ---------------------------------------------------------------------------

Sketch build_gear_profile_sketch(int n_teeth, double module, double pressure_angle, const ToothOptions& options) {
  const ToothGeometry geo = compute_tooth_geometry(n_teeth, module, pressure_angle, options);
  const double root_radius = geo.root_radius;
  const double base_radius = geo.base_radius;
  const double tip_radius = geo.tip_radius;
  const double tooth_angle = geo.tooth_angle;
  const double flank_start_radius = std::max(base_radius, root_radius);
  const bool needs_root_connectors = root_radius < base_radius - tol::kBaseCircleClearance;
  const double t_flank_start = involute_t_for_radius(base_radius, flank_start_radius);
  const double flank_start_span = t_flank_start - std::atan(t_flank_start);
  const double left_flank_start_angle = geo.left_start + flank_start_span;
  const double right_flank_start_angle = geo.right_start - flank_start_span;
  const double root_left_angle = needs_root_connectors ? geo.left_start : left_flank_start_angle;
  const double root_right_angle = needs_root_connectors ? geo.right_start : right_flank_start_angle;
  const double prev_right_start = root_right_angle - tooth_angle;

  const BSplineData canonical =
      involute_bspline_control_points(base_radius, tip_radius, flank_start_radius, 0.0, false);
  const auto [reversed_knots, reversed_multiplicities] =
      reverse_bspline_parameters(canonical.knots, canonical.multiplicities);

  SketchBuilder sketch("gear_" + std::to_string(n_teeth) + "t_m" + python_float_repr(module));
  add_construction_circles(sketch, "root_circle", root_radius, "pitch_circle", geo.pitch_radius, "tip_circle",
                           tip_radius);

  struct ToothPoints {
    Point2 rs, re, bs, be, ts, te;
  };
  std::vector<ToothPoints> teeth;
  teeth.reserve(static_cast<std::size_t>(n_teeth));
  for (int i = 0; i < n_teeth; ++i) {
    const double offset = tooth_angle * i;
    teeth.push_back({polar(root_radius, prev_right_start + offset), polar(root_radius, root_left_angle + offset),
                     polar(flank_start_radius, left_flank_start_angle + offset),
                     polar(flank_start_radius, right_flank_start_angle + offset),
                     polar(tip_radius, geo.left_tip_angle + offset), polar(tip_radius, geo.right_tip_angle + offset)});
  }

  std::optional<BSplineData> left_fillet, right_fillet;
  if (needs_root_connectors) {
    left_fillet = root_fillet_control_points(teeth[0].re, teeth[0].bs, root_left_angle + kPi / 2.0, geo.left_start);
    right_fillet = root_fillet_control_points(teeth[0].be, teeth[static_cast<std::size_t>(1 % n_teeth)].rs,
                                              geo.right_start + kPi, root_right_angle + kPi / 2.0);
  }

  // Edges share these points instead of carrying hundreds of coincidence constraints.
  for (int i = 0; i < n_teeth; ++i) {
    const ToothPoints& t = teeth[static_cast<std::size_t>(i)];
    add_point(sketch, i, "rs", t.rs);
    add_point(sketch, i, "re", t.re);
    add_point(sketch, i, "bs", t.bs);
    add_point(sketch, i, "be", t.be);
    add_point(sketch, i, "ts", t.ts);
    add_point(sketch, i, "te", t.te);
  }

  for (int i = 0; i < n_teeth; ++i) {
    const std::string rs = tooth_point(i, "rs");
    const std::string re = tooth_point(i, "re");
    const std::string bs = needs_root_connectors ? tooth_point(i, "bs") : re;
    const std::string be = tooth_point(i, "be");
    const std::string ts = tooth_point(i, "ts");
    const std::string te = tooth_point(i, "te");
    const std::string next_rs = tooth_point((i + 1) % n_teeth, "rs");
    const std::string right_flank_end = needs_root_connectors ? be : next_rs;
    const double turn = tooth_angle * i;

    sketch.arc(numbered("arc_root_", i), rs, re, "center");
    if (needs_root_connectors) {
      BSplineData fillet = *left_fillet;
      fillet.control_points = transform_bspline_control_points(fillet.control_points, turn);
      sketch.bspline(numbered("fillet_left_", i), re, tooth_point(i, "bs"), fillet);
    }

    BSplineData left = canonical;
    left.control_points = transform_bspline_control_points(canonical.control_points, geo.left_start + turn);
    sketch.bspline(numbered("bspline_left_", i), bs, ts, left);

    sketch.arc(numbered("arc_tip_", i), ts, te, "center");

    BSplineData right = canonical;
    right.control_points = transform_bspline_control_points(canonical.control_points, geo.right_start + turn,
                                                            /*mirror=*/true, /*reverse=*/true);
    right.knots = reversed_knots;
    right.multiplicities = reversed_multiplicities;
    sketch.bspline(numbered("bspline_right_", i), te, right_flank_end, right);

    if (needs_root_connectors) {
      BSplineData fillet = *right_fillet;
      fillet.control_points = transform_bspline_control_points(fillet.control_points, turn);
      sketch.bspline(numbered("fillet_right_", i), be, next_rs, fillet);
    }
  }
  return sketch.take();
}

Face build_gear_profile_face(int n_teeth, double module, double pressure_angle, const ToothOptions& options) {
  return make_face_from_sketch_rface(build_gear_profile_sketch(n_teeth, module, pressure_angle, options), 0);
}

// ---------------------------------------------------------------------------
// Internal gear and ring gear
// ---------------------------------------------------------------------------

Sketch build_internal_gear_profile_sketch(int n_teeth, double module, double pressure_angle,
                                          const ToothTuning& tuning) {
  const InternalToothGeometry geo = compute_internal_tooth_geometry(n_teeth, module, pressure_angle, tuning);
  const double root_radius = geo.root_radius;
  const double tip_radius = geo.tip_radius;
  const double flank_tip_radius = geo.flank_tip_radius;
  const double base_radius = geo.base_radius;
  const double tooth_angle = geo.tooth_angle;
  const bool needs_tip_connectors = geo.needs_tip_connectors;

  SketchBuilder sketch("internal_gear_" + std::to_string(n_teeth) + "t_m" + python_float_repr(module));
  add_construction_circles(sketch, "tip_circle", tip_radius, "pitch_circle", geo.pitch_radius, "root_circle",
                           root_radius);

  struct ToothPoints {
    Point2 rs, re, lb, lt, rt, rb, rr;
  };
  std::vector<ToothPoints> teeth;
  teeth.reserve(static_cast<std::size_t>(n_teeth));
  for (int i = 0; i < n_teeth; ++i) {
    const double offset = tooth_angle * i;
    const double left_tip = geo.left_tip_angle + offset;
    const double right_tip = geo.right_tip_angle + offset;
    teeth.push_back({polar(root_radius, geo.right_root_angle - tooth_angle + offset),
                     polar(root_radius, geo.left_root_angle + offset), polar(flank_tip_radius, left_tip),
                     polar(tip_radius, left_tip), polar(tip_radius, right_tip), polar(flank_tip_radius, right_tip),
                     polar(root_radius, geo.right_root_angle + offset)});
  }
  for (int i = 0; i < n_teeth; ++i) {
    const ToothPoints& t = teeth[static_cast<std::size_t>(i)];
    add_point(sketch, i, "rs", t.rs);
    add_point(sketch, i, "re", t.re);
    add_point(sketch, i, "lb", t.lb);
    add_point(sketch, i, "lt", t.lt);
    add_point(sketch, i, "rt", t.rt);
    add_point(sketch, i, "rb", t.rb);
    add_point(sketch, i, "rr", t.rr);
  }

  for (int i = 0; i < n_teeth; ++i) {
    const ToothPoints& t = teeth[static_cast<std::size_t>(i)];
    const std::string rs = tooth_point(i, "rs");
    const std::string re = tooth_point(i, "re");
    const std::string lb = tooth_point(i, "lb");
    const std::string lt = tooth_point(i, "lt");
    const std::string rt = tooth_point(i, "rt");
    const std::string rb = tooth_point(i, "rb");
    const std::string next_rs = tooth_point((i + 1) % n_teeth, "rs");
    const double turn = tooth_angle * i;

    sketch.arc(numbered("arc_internal_root_", i), rs, re, "center");
    sketch.bspline(numbered("bspline_internal_left_", i), re, lb,
                   involute_bspline_control_points(base_radius, root_radius, flank_tip_radius,
                                                   geo.left_base_angle + turn, /*mirror=*/true, /*reverse=*/true));

    std::string tip_left = lb;
    std::string tip_right = rb;
    if (needs_tip_connectors) {
      const double left_angle = std::atan2(t.lt.y - t.lb.y, t.lt.x - t.lb.x);
      sketch.bspline(numbered("transition_internal_left_", i), lb, lt,
                     root_fillet_control_points(t.lb, t.lt, left_angle, left_angle));
      tip_left = lt;
      tip_right = rt;
    }
    sketch.arc(numbered("arc_internal_tip_", i), tip_left, tip_right, "center");
    if (needs_tip_connectors) {
      const double right_angle = std::atan2(t.rb.y - t.rt.y, t.rb.x - t.rt.x);
      sketch.bspline(numbered("transition_internal_right_", i), rt, rb,
                     root_fillet_control_points(t.rt, t.rb, right_angle, right_angle));
    }
    sketch.bspline(numbered("bspline_internal_right_", i), rb, next_rs,
                   involute_bspline_control_points(base_radius, root_radius, flank_tip_radius,
                                                   geo.right_base_angle + turn, /*mirror=*/false));
  }
  return sketch.take();
}

Wire build_internal_gear_profile_wire(int n_teeth, double module, double pressure_angle, const ToothTuning& tuning) {
  return make_wire_from_sketch_rwire(build_internal_gear_profile_sketch(n_teeth, module, pressure_angle, tuning), 0);
}

Face build_ring_gear_face(int n_teeth, double module, double pressure_angle, double rim_thickness,
                          const ToothTuning& tuning) {
  const InternalRingRadii radii =
      internal_ring_radii(n_teeth, module, rim_thickness, tuning.addendum_factor, tuning.clearance_factor);
  const Wire outer = make_circle_rwire(scalar3(0.0, 0.0, 0.0), radii.outer);
  const Wire inner = build_internal_gear_profile_wire(n_teeth, module, pressure_angle, tuning);
  return make_face_from_wires_rface(outer, {inner});
}

// ---------------------------------------------------------------------------
// Rack
// ---------------------------------------------------------------------------

Face build_rack_profile_face(double module, int n_teeth, double pressure_angle) {
  const std::vector<Point2> points = rack_profile_points(module, n_teeth, pressure_angle);
  SketchBuilder sketch("rack_m" + python_float_repr(module) + "_n" + std::to_string(n_teeth));
  for (std::size_t i = 0; i < points.size(); ++i)
    sketch.point("p" + std::to_string(i), points[i].x, points[i].y);
  for (std::size_t i = 0; i < points.size(); ++i) {
    sketch.line("l" + std::to_string(i), "p" + std::to_string(i), "p" + std::to_string((i + 1) % points.size()));
  }
  return make_face_from_sketch_rface(sketch.take(), 0);
}

// ---------------------------------------------------------------------------
// Cycloidal disc
// ---------------------------------------------------------------------------

Wire build_cycloidal_disc_profile_wire(const CycloidalProfile& profile, CycloidalFitData* fit_data) {
  std::vector<Edge> edges;
  edges.reserve(static_cast<std::size_t>(profile.n_lobes));
  CycloidalFitData data;
  data.radius_min = std::numeric_limits<double>::infinity();
  data.radius_max = -std::numeric_limits<double>::infinity();

  for (int segment = 0; segment < profile.n_lobes; ++segment) {
    const double start_theta = 2.0 * kPi * segment / profile.n_lobes;
    const double end_theta = 2.0 * kPi * (segment + 1) / profile.n_lobes;
    std::vector<std::vector<double>> samples;
    samples.reserve(static_cast<std::size_t>(profile.sample_count_per_lobe));
    for (int index = 0; index < profile.sample_count_per_lobe; ++index) {
      const double theta = start_theta + (end_theta - start_theta) * index / (profile.sample_count_per_lobe - 1);
      const Point2 p = cycloidal_disc_point(theta, profile.n_lobes, profile.ring_pin_pitch_radius,
                                            profile.roller_radius, profile.eccentricity);
      const double radius = std::hypot(p.x, p.y);
      data.radius_min = std::min(data.radius_min, radius);
      data.radius_max = std::max(data.radius_max, radius);
      samples.push_back({p.x, p.y, 0.0});
    }
    reactive::BSplineFitOptions options;
    options.tolerance = profile.spline_tolerance;
    options.max_control_points = profile.max_control_points;
    options.fairing = 1e-8;
    const reactive::BSplineFit fit = reactive::fit_cubic_bspline_control_points(samples, options);

    SplineSpec spec;
    for (const auto& pole : fit.control_points)
      spec.control_points.push_back({Scalar(pole[0]), Scalar(pole[1]), Scalar(pole[2])});
    spec.degree = fit.degree;
    const std::vector<double> knots = fit.unique_knots();
    spec.knots = ScalarList(knots.begin(), knots.end());
    spec.multiplicities = fit.multiplicities();
    edges.push_back(make_spline_redge(spec));
    data.control_point_counts.push_back(static_cast<int>(fit.control_points.size()));
    data.max_errors.push_back(fit.max_error);
  }

  Wire wire = make_wire_from_edges_rwire(edges);
  if (fit_data != nullptr)
    *fit_data = std::move(data);
  return wire;
}

}  // namespace scad::stdlib
