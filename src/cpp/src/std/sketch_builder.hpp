// Builds a constraint sketch the way the gear factories do.
//
// The functional sketch operators copy the whole document on every call, which is quadratic in
// the number of entities and a gear sketch has hundreds.  The Python factories avoid it with a
// private "linear edit" mode that updates one sketch in place.  This builder does the same
// when nothing records (the entities and constraints are the same ones the operators would
// add); when a recorder is installed it goes through the operators so that every step is a
// graph node, as it is in Python.
#pragma once

#include <string>
#include <vector>

#include "scad/core/vec.hpp"
#include "scad/sketch/operators.hpp"
#include "scad/std/involute.hpp"
#include "scad/topo/recorder.hpp"

namespace scad::stdlib {

class SketchBuilder {
 public:
  explicit SketchBuilder(const std::string& name)
      : functional_(current_recorder() != nullptr), sketch_(make_sketch_rsketch(name, Value("XY"))) {}

  void point(const std::string& id, double x, double y) {
    if (functional_) {
      sketch_ = add_point_rsketch(sketch_, id, x, y);
    } else {
      sketch_.add_point(id, Scalar(x), Scalar(y));
    }
  }

  void line(const std::string& id, const std::string& start, const std::string& end) {
    if (functional_) {
      sketch_ = add_line_rsketch(sketch_, id, start, end);
    } else {
      sketch_.add_line(id, point_ref(start), point_ref(end));
    }
  }

  void circle(const std::string& id, const std::string& center, double radius, bool construction) {
    if (functional_) {
      sketch_ = add_circle_rsketch(sketch_, id, center, radius, construction);
    } else {
      sketch_.add_circle(id, point_ref(center), Scalar(radius), construction);
    }
  }

  void arc(const std::string& id, const std::string& start, const std::string& end, const std::string& center) {
    if (functional_) {
      sketch_ = add_arc_rsketch(sketch_, id, start, end, center);
    } else {
      sketch_.add_arc(id, point_ref(start), point_ref(end), point_ref(center));
    }
  }

  void bspline(const std::string& id, const std::string& start, const std::string& end, const BSplineData& data) {
    std::vector<SketchControlPoint> poles;
    poles.reserve(data.control_points.size());
    for (const Point2& pole : data.control_points) poles.emplace_back(pole.x, pole.y);
    std::vector<Scalar> knots(data.knots.begin(), data.knots.end());
    if (functional_) {
      sketch_ = add_bspline_rsketch(sketch_, id, start, end, poles, data.degree, knots, data.multiplicities);
    } else {
      sketch_.add_bspline(id, point_ref(start), point_ref(end), poles, data.degree, knots, data.multiplicities);
    }
  }

  void fix(const std::string& id) {
    if (functional_) {
      sketch_ = constrain_fix_rsketch(sketch_, id);
    } else {
      sketch_.add_constraint("fix", {sketch_.resolve_target(id)});
    }
  }

  void radius(const std::string& circle_id, double value) {
    if (functional_) {
      sketch_ = constrain_radius_rsketch(sketch_, circle_id, value);
    } else {
      sketch_.add_constraint("radius", {sketch_.resolve_target(circle_id, {"circle", "arc"})}, Scalar(value));
    }
  }

  void concentric(const std::string& a, const std::string& b) {
    if (functional_) {
      sketch_ = constrain_concentric_rsketch(sketch_, a, b);
    } else {
      const std::vector<std::string> kinds{"circle", "arc", "ellipse"};
      sketch_.add_constraint("concentric", {sketch_.resolve_target(a, kinds), sketch_.resolve_target(b, kinds)});
    }
  }

  const Sketch& sketch() const noexcept { return sketch_; }
  Sketch take() { return std::move(sketch_); }

 private:
  SketchRef point_ref(const std::string& id) const { return sketch_.resolve_target(id, {"point"}); }

  bool functional_;
  Sketch sketch_;
};

}  // namespace scad::stdlib
