// insert_spline_anchor_rsketch, remove_spline_anchor_rsketch and convert_spline_to_anchors_rsketch: the curve stays
// where it was, the anchors and handles keep their ids, the refusals name the ids.
#include "doctest.h"

#include <cmath>
#include <functional>
#include <string>
#include <vector>

#include <Geom2d_BSplineCurve.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColgp_Array1OfPnt2d.hxx>

#include "scad/core/error.hpp"
#include "scad/sketch/operators.hpp"

using namespace scad;

namespace {

// One anchor-form span from a0 to a1 with the handles h0 and h1.
Sketch one_span() {
  Sketch s = make_sketch_rsketch("anchors");
  s = add_point_rsketch(s, "a0", 0, 0);
  s = add_point_rsketch(s, "h0", 10, 10);
  s = add_point_rsketch(s, "h1", 20, 10);
  s = add_point_rsketch(s, "a1", 30, 0);
  return add_bspline_rsketch(s, "s1", "a0", "a1", {"a0", "h0", "h1", "a1"}, 3);
}

std::vector<std::string> pole_ids(const Sketch& s) {
  std::vector<std::string> out;
  for (const SketchPole& pole : s.entities().at("s1").bspline().poles)
    out.push_back(pole.point_id);
  return out;
}

// Points along the spline s1 of the sketch (its own seeds, which an edit leaves solved).
std::vector<gp_Pnt2d> samples(const Sketch& s, int count = 40) {
  const SketchBSpline spline = s.entities().at("s1").bspline();
  TColgp_Array1OfPnt2d poles(1, static_cast<int>(spline.poles.size()));
  for (std::size_t i = 0; i < spline.poles.size(); ++i) {
    const SketchEntity& point = s.entities().at(spline.poles[i].point_id);
    poles.SetValue(static_cast<int>(i) + 1, gp_Pnt2d(point.number("x"), point.number("y")));
  }
  TColStd_Array1OfReal knots(1, static_cast<int>(spline.knots.size()));
  TColStd_Array1OfInteger mults(1, static_cast<int>(spline.knots.size()));
  for (std::size_t i = 0; i < spline.knots.size(); ++i) {
    knots.SetValue(static_cast<int>(i) + 1, spline.knots[i]);
    mults.SetValue(static_cast<int>(i) + 1, spline.multiplicities[i]);
  }
  const opencascade::handle<Geom2d_BSplineCurve> curve = new Geom2d_BSplineCurve(poles, knots, mults, spline.degree);
  std::vector<gp_Pnt2d> out;
  for (int i = 0; i <= count; ++i)
    out.push_back(
        curve->Value(curve->FirstParameter() + (curve->LastParameter() - curve->FirstParameter()) * i / count));
  return out;
}

double gap(const std::vector<gp_Pnt2d>& a, const std::vector<gp_Pnt2d>& b) {
  double worst = 0.0;
  for (std::size_t i = 0; i < a.size(); ++i)
    worst = std::max(worst, a[i].Distance(b[i]));
  return worst;
}

std::string failure_text(const std::function<void()>& call) {
  try {
    call();
  } catch (const Error& e) {
    return e.guidance().technical_details;
  }
  return {};
}

}  // namespace

TEST_CASE("insert anchor: the curve does not change, the span's handles keep their ids, three new points") {
  const Sketch before = one_span();
  const Sketch after = insert_spline_anchor_rsketch(before, "s1", SketchPosition(12.0, 8.0));
  CHECK(pole_ids(after) == std::vector<std::string>{"a0", "h0", "p1", "p2", "p3", "h1", "a1"});
  const SketchBSpline spline = after.entities().at("s1").bspline();
  CHECK(spline.multiplicities == std::vector<int>{4, 3, 4});
  CHECK(gap(samples(before), samples(after)) < 1e-9);
  // the new anchor is on the curve and its handles are on one line with it (the curve is smooth there)
  const auto xy = [&](const char* id) {
    return gp_Pnt2d(after.entities().at(id).number("x"), after.entities().at(id).number("y"));
  };
  const gp_Vec2d in(xy("p2"), xy("p1"));
  const gp_Vec2d out(xy("p2"), xy("p3"));
  CHECK(std::abs(in.Crossed(out)) < 1e-9 * in.Magnitude() * out.Magnitude());
}

TEST_CASE("remove anchor: undoes an insert; the outer handles keep their ids and directions") {
  const Sketch before = one_span();
  const Sketch split = insert_spline_anchor_rsketch(before, "s1", SketchPosition(20.0, 7.0));
  const Sketch merged = remove_spline_anchor_rsketch(split, "s1", "p2");
  CHECK(pole_ids(merged) == std::vector<std::string>{"a0", "h0", "h1", "a1"});
  CHECK(gap(samples(before), samples(merged)) < 1e-7);
  CHECK_FALSE(merged.entities().contains("p1"));
  CHECK_FALSE(merged.entities().contains("p2"));
  CHECK_FALSE(merged.entities().contains("p3"));
}

TEST_CASE("remove anchor: an anchor another entity uses stays as a point; constraints on removed points go") {
  Sketch s = insert_spline_anchor_rsketch(one_span(), "s1", SketchPosition(15.0, 8.0));
  s = add_point_rsketch(s, "far", 15, 30);
  s = add_line_rsketch(s, "l0", "p2", "far");
  s = constrain_fix_rsketch(s, "p3");
  const Sketch after = remove_spline_anchor_rsketch(s, "s1", "p2");
  CHECK(after.entities().contains("p2"));
  CHECK_FALSE(after.entities().contains("p3"));
  CHECK(after.constraints().empty());
}

TEST_CASE("anchors: refusals name the ids") {
  const Sketch split = insert_spline_anchor_rsketch(one_span(), "s1", SketchPosition(15.0, 8.0));
  CHECK(failure_text([&] { remove_spline_anchor_rsketch(split, "s1", "a0"); }).find("is an end of 's1'") !=
        std::string::npos);
  CHECK(failure_text([&] { remove_spline_anchor_rsketch(split, "s1", "p1"); }).find("is a handle of 's1'") !=
        std::string::npos);
  CHECK(failure_text([&] { remove_spline_anchor_rsketch(one_span(), "s1", "zz"); }).find("only its two end anchors") !=
        std::string::npos);
  CHECK(failure_text([&] { insert_spline_anchor_rsketch(split, "s1", "p2"); }).find("already has an anchor there") !=
        std::string::npos);
  Sketch control = make_sketch_rsketch("control");
  for (int i = 0; i < 5; ++i)
    control = add_point_rsketch(control, "q" + std::to_string(i), 5.0 * i, i % 2 == 0 ? 0.0 : 8.0);
  control = add_bspline_rsketch(control, "s1", "q0", "q4", {"q0", "q1", "q2", "q3", "q4"}, 3);
  CHECK(failure_text([&] {
          insert_spline_anchor_rsketch(control, "s1", SketchPosition(10.0, 4.0));
        }).find("convert_spline_to_anchors_rsketch") != std::string::npos);
}

TEST_CASE("convert: a control-point B-spline keeps its curve and becomes Bezier spans") {
  Sketch control = make_sketch_rsketch("control");
  for (int i = 0; i < 5; ++i)
    control = add_point_rsketch(control, "q" + std::to_string(i), 5.0 * i, i % 2 == 0 ? 0.0 : 8.0);
  control = add_bspline_rsketch(control, "s1", "q0", "q4", {"q0", "q1", "q2", "q3", "q4"}, 3);
  const Sketch after = convert_spline_to_anchors_rsketch(control, "s1");
  const SketchBSpline spline = after.entities().at("s1").bspline();
  CHECK(spline.multiplicities == std::vector<int>{4, 3, 4});
  CHECK(pole_ids(after).front() == "q0");
  CHECK(pole_ids(after).back() == "q4");
  CHECK(gap(samples(control), samples(after)) < 1e-9);
  // already in anchor form: nothing changes
  CHECK(pole_ids(convert_spline_to_anchors_rsketch(after, "s1")) == pole_ids(after));
}

TEST_CASE("trim keeps the anchor form: the cut piece is still Bezier spans") {
  Sketch s = insert_spline_anchor_rsketch(one_span(), "s1", SketchPosition(15.0, 8.0));
  s = add_point_rsketch(s, "t0", 25, -5);
  s = add_point_rsketch(s, "t1", 25, 20);
  s = add_line_rsketch(s, "cut", "t0", "t1");
  const Sketch after = trim_rsketch(s, "s1", SketchPosition(29.0, 1.0));
  const SketchEntity* piece = nullptr;
  for (const auto& [id, entity] : after.entities())
    if (entity.kind == "bspline")
      piece = &entity;
  REQUIRE(piece != nullptr);
  const SketchBSpline spline = piece->bspline();
  CHECK(spline.degree == 3);
  CHECK(spline.multiplicities == std::vector<int>{4, 3, 4});
}
