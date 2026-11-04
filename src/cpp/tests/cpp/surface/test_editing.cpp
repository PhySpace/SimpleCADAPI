// Editing existing curves and surfaces: inspect, poles, weights, knots, degree, conversion, rebuild, sampling, and
// the recorded delta (the face and its edges continue, so tags and references follow).
#include "doctest.h"

#include <cmath>
#include <functional>
#include <optional>

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepTools.hxx>
#include <BRep_Tool.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <gp_Trsf.hxx>

#include "scad/core/error.hpp"
#include "scad/surface/editing.hpp"
#include "scad/surface/operators.hpp"
#include "scad/topo/recorder.hpp"
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

class Capture final : public Recorder {
 public:
  std::vector<OpRecord> records;
  void record(const OpRecord& record, const std::vector<Shape>&) override { records.push_back(record); }
};

// A 3 x 3 quadratic Bezier patch on [0, 2] x [0, 2], flat but for the middle pole at height `bump`.
Face patch(double bump = 1.0) {
  PointGrid grid;
  for (int x = 0; x < 3; ++x) {
    grid.emplace_back();
    for (int y = 0; y < 3; ++y)
      grid.back().push_back({double(x), double(y), x == 1 && y == 1 ? bump : 0.0});
  }
  return make_bezier_surface_rface(grid);
}

Edge spline(const std::vector<Vec3>& points) {
  Handle(TColgp_HArray1OfPnt) array = new TColgp_HArray1OfPnt(1, static_cast<int>(points.size()));
  for (std::size_t i = 0; i < points.size(); ++i)
    array->SetValue(static_cast<int>(i) + 1, gp_Pnt(points[i].x, points[i].y, points[i].z));
  GeomAPI_Interpolate interpolation(array, false, 1e-7);
  interpolation.Perform();
  return Edge(BRepBuilderAPI_MakeEdge(interpolation.Curve()).Edge());
}

Vec3 vec(const Value& point) {
  const auto& a = point.as_array();
  return {a[0].as_double(), a[1].as_double(), a[2].as_double()};
}

gp_Pnt surface_point(const Face& face, double u, double v) {
  return BRepAdaptor_Surface(TopoDS::Face(face.wrapped())).Value(u, v);
}

gp_Pnt curve_point(const Edge& edge, double t) {
  return BRepAdaptor_Curve(TopoDS::Edge(edge.wrapped())).Value(t);
}

bool valid(const Shape& shape) {
  return BRepCheck_Analyzer(shape.wrapped()).IsValid();
}

}  // namespace

TEST_CASE("inspect_surface_rsurfacedata reads a Bezier face as its B-spline, and an analytic face as its conversion") {
  const Value data = inspect_surface_rsurfacedata(patch());
  CHECK(data.find("type")->as_string() == "bezier");
  CHECK(data.find("editable")->as_bool());
  CHECK(data.find("conversion")->is_null());
  CHECK(data.find("u_degree")->as_int() == 2);
  CHECK(data.find("poles")->as_array().size() == 3);
  CHECK(vec(data.find("poles")->as_array()[1].as_array()[1]).z == doctest::Approx(1.0));
  CHECK_FALSE(data.find("trimmed")->as_bool());

  const Face plane = trim_surface_rface(patch(0.0), rectangle(1.0, 1.0, 1.0, 1.0));
  CHECK(inspect_surface_rsurfacedata(plane).find("trimmed")->as_bool());

  const Solid cube = box(2, 2, 2);
  const Value analytic = inspect_surface_rsurfacedata(cube.faces().front());
  CHECK(analytic.find("type")->as_string() == "plane");
  CHECK_FALSE(analytic.find("editable")->as_bool());
  CHECK(analytic.find("conversion")->as_string() == "convert_to_bspline_rface");
  CHECK(analytic.find("u_degree")->as_int() == 1);
}

TEST_CASE("surface edits return a new face; the input is untouched") {
  const Face face = patch();
  const Face moved = move_surface_poles_rface(face, {{{1, 1}, {1, 1, 3}}});
  CHECK(surface_point(face, 0.5, 0.5).Z() == doctest::Approx(0.25));
  CHECK(surface_point(moved, 0.5, 0.5).Z() == doctest::Approx(0.75));
  CHECK(valid(moved));

  PointGrid all;
  const Value read = inspect_surface_rsurfacedata(face);
  for (const Value& row : read.find("poles")->as_array()) {
    all.emplace_back();
    for (const Value& p : row.as_array())
      all.back().push_back(vec(p));
  }
  all[0][0].z = -1.0;
  const Face set = set_surface_poles_rface(face, all);
  CHECK(surface_point(set, 0, 0).Z() == doctest::Approx(-1.0));

  const Face knotted = insert_surface_knot_rface(moved, "U", 0.3, 1);
  CHECK(inspect_surface_rsurfacedata(knotted).find("poles")->as_array().size() == 4);
  const Face elevated = elevate_surface_degree_rface(knotted, 3, std::nullopt);
  CHECK(inspect_surface_rsurfacedata(elevated).find("u_degree")->as_int() == 3);
  for (const auto& [u, v] : {std::pair{0.2, 0.7}, std::pair{0.5, 0.5}, std::pair{0.9, 0.1}}) {
    CHECK(surface_point(knotted, u, v).Distance(surface_point(moved, u, v)) < 1e-9);
    CHECK(surface_point(elevated, u, v).Distance(surface_point(moved, u, v)) < 1e-9);
  }

  WeightGrid weights(3, std::vector<double>(3, 1.0));
  weights[1][1] = 4.0;
  const Face weighted = set_surface_weights_rface(moved, weights);
  CHECK(inspect_surface_rsurfacedata(weighted).find("rational")->as_bool());
  CHECK(surface_point(weighted, 0.5, 0.5).Z() > surface_point(moved, 0.5, 0.5).Z());
}

TEST_CASE("a trimmed face keeps its trimming loops in (u, v) through an edit") {
  const Face carrier = patch(0.0);
  const Face holed =
      trim_surface_rface(carrier, rectangle(1.2, 1.2, 1.0, 1.0),
                         {.holes = {polygon({{0.9, 0.9, 0}, {1.1, 0.9, 0}, {1.1, 1.1, 0}, {0.9, 1.1, 0}})}});
  double u1 = 0, u2 = 0, v1 = 0, v2 = 0;
  BRepTools::UVBounds(TopoDS::Face(holed.wrapped()), u1, u2, v1, v2);
  const Face lifted = move_surface_poles_rface(holed, {{{1, 1}, {1, 1, 2}}});
  CHECK(valid(lifted));
  int wires = 0;
  for (TopExp_Explorer it(lifted.wrapped(), TopAbs_WIRE); it.More(); it.Next())
    ++wires;
  CHECK(wires == 2);
  double a1 = 0, a2 = 0, b1 = 0, b2 = 0;
  BRepTools::UVBounds(TopoDS::Face(lifted.wrapped()), a1, a2, b1, b2);
  CHECK(a1 == doctest::Approx(u1));
  CHECK(a2 == doctest::Approx(u2));
  CHECK(b1 == doctest::Approx(v1));
  CHECK(b2 == doctest::Approx(v2));
  // The boundary edges lie on the new surface: every vertex is the surface's point at its (u, v).
  for (TopExp_Explorer it(lifted.wrapped(), TopAbs_VERTEX); it.More(); it.Next()) {
    const TopoDS_Vertex vertex = TopoDS::Vertex(it.Current());
    const gp_Pnt2d uv = BRep_Tool::Parameters(vertex, TopoDS::Face(lifted.wrapped()));
    CHECK(BRep_Tool::Pnt(vertex).Distance(surface_point(lifted, uv.X(), uv.Y())) < 1e-6);
  }
  CHECK(surface_point(lifted, 0.5, 0.5).Z() == doctest::Approx(0.5));  // 2 * 0.25 (was 0)
}

TEST_CASE("poles of a located face are read and written in the current coordinate system") {
  gp_Trsf shift;
  shift.SetTranslation(gp_Vec(10, 0, 0));
  const Face moved_face(patch().wrapped().Moved(TopLoc_Location(shift)));
  const Value data = inspect_surface_rsurfacedata(moved_face);
  CHECK(vec(data.find("poles")->as_array()[0].as_array()[0]).x == doctest::Approx(10.0));
  const Face edited = move_surface_poles_rface(moved_face, {{{0, 0}, {10, 0, -2}}});
  CHECK(surface_point(edited, 0, 0).X() == doctest::Approx(10.0));
  CHECK(surface_point(edited, 0, 0).Z() == doctest::Approx(-2.0));
}

TEST_CASE("curve edits: poles, weights, knots, degree; the shape-keeping ones keep the shape") {
  const Edge edge = spline({{0, 0, 0}, {1, 1, 0}, {2, 0, 0}, {3, 1, 0}});
  const Value data = inspect_curve_rcurvedata(edge);
  CHECK(data.find("type")->as_string() == "bspline");
  const int poles = static_cast<int>(data.find("poles")->as_array().size());
  const double first = data.find("parameter_range")->as_array()[0].as_double();
  const double last = data.find("parameter_range")->as_array()[1].as_double();

  const Edge moved = move_curve_poles_redge(edge, {{1, {1, 5, 0}}});
  CHECK(vec(inspect_curve_rcurvedata(moved).find("poles")->as_array()[1]).y == doctest::Approx(5.0));
  CHECK(curve_point(moved, first).Distance(curve_point(edge, first)) < 1e-9);  // the end pole stays

  const double mid = 0.5 * (first + last);
  const Edge knotted = insert_curve_knot_redge(moved, mid, 1);
  CHECK(static_cast<int>(inspect_curve_rcurvedata(knotted).find("poles")->as_array().size()) == poles + 1);
  const Edge elevated = elevate_curve_degree_redge(knotted, 5);
  CHECK(inspect_curve_rcurvedata(elevated).find("degree")->as_int() == 5);
  for (double t : {first, 0.3 * first + 0.7 * last, mid, last}) {
    CHECK(curve_point(knotted, t).Distance(curve_point(moved, t)) < 1e-9);
    CHECK(curve_point(elevated, t).Distance(curve_point(moved, t)) < 1e-9);
  }

  std::vector<double> weights(static_cast<std::size_t>(poles), 1.0);
  weights[1] = 5.0;
  const Edge weighted = set_curve_weights_redge(edge, weights);
  CHECK(inspect_curve_rcurvedata(weighted).find("rational")->as_bool());

  std::vector<Vec3> all;
  for (const Value& p : data.find("poles")->as_array())
    all.push_back(vec(p));
  all.back() = {4, 4, 4};
  CHECK(curve_point(set_curve_poles_redge(edge, all), last).Distance(gp_Pnt(4, 4, 4)) < 1e-9);
}

TEST_CASE("analytic geometry is refused with the conversion named; the conversion is explicit") {
  const Edge segment = line({0, 0, 0}, {5, 0, 0});
  CHECK(message_has([&] { (void)move_curve_poles_redge(segment, {{0, {0, 1, 0}}}); }, "convert_to_bspline_redge"));
  const Edge converted = convert_to_bspline_redge(segment);
  CHECK(inspect_curve_rcurvedata(converted).find("editable")->as_bool());
  const Edge bent = move_curve_poles_redge(converted, {{1, {5, 2, 0}}});
  CHECK(valid(bent));

  const Face side = box(2, 2, 2).faces().front();
  CHECK(message_has([&] { (void)elevate_surface_degree_rface(side, 3, 3); }, "convert_to_bspline_rface"));
  const Face nurbs = convert_to_bspline_rface(side);
  CHECK(inspect_surface_rsurfacedata(nurbs).find("type")->as_string() == "bspline");
  CHECK(valid(elevate_surface_degree_rface(nurbs, 3, 3)));
}

TEST_CASE("a converted cylinder side is a periodic, untrimmed B-spline face that edits keep valid") {
  const Solid cylinder(BRepPrimAPI_MakeCylinder(5.0, 10.0).Solid());
  std::optional<Face> side;
  for (const Face& face : cylinder.faces())
    if (inspect_surface_rsurfacedata(face).find("type")->as_string() == "cylinder")
      side = face;
  REQUIRE(side);
  const Face nurbs = convert_to_bspline_rface(*side);
  const Value data = inspect_surface_rsurfacedata(nurbs);
  CHECK(data.find("u_periodic")->as_bool());
  CHECK_FALSE(data.find("trimmed")->as_bool());
  const Face bulged = move_surface_poles_rface(nurbs, {{{0, 1}, {20, 0, 10}}});
  CHECK(valid(bulged));
  CHECK(bulged.area() > nurbs.area());
}

TEST_CASE("bad arguments fail with the operation's error and say what fits") {
  const Face face = patch();
  CHECK(message_has([&] { (void)set_surface_poles_rface(face, {{{0, 0, 0}}}); }, "3 x 3 grid"));
  CHECK(message_has([&] { (void)move_surface_poles_rface(face, {{{3, 0}, {0, 0, 0}}}); }, "out of range"));
  CHECK(message_has([&] { (void)insert_surface_knot_rface(face, "W", 0.5); }, "'U' or 'V'"));
  CHECK(message_has([&] { (void)insert_surface_knot_rface(face, "U", 1.0); }, "strictly inside"));
  CHECK(message_has([&] { (void)insert_surface_knot_rface(face, "U", 0.5, 3); }, "multiplicity"));
  CHECK(message_has([&] { (void)elevate_surface_degree_rface(face, 1, std::nullopt); }, "cannot be lowered"));
  CHECK(message_has([&] { (void)elevate_surface_degree_rface(face, std::nullopt, std::nullopt); }, "u_degree"));
  WeightGrid weights(3, std::vector<double>(3, 1.0));
  weights[0][0] = 0.0;
  CHECK(message_has([&] { (void)set_surface_weights_rface(face, weights); }, "positive"));
  const Edge edge = spline({{0, 0, 0}, {1, 1, 0}, {2, 0, 0}});
  CHECK(message_has([&] { (void)elevate_curve_degree_redge(edge, 2); }, "higher than"));
  CHECK(message_has([&] { (void)set_curve_poles_redge(edge, {{0, 0, 0}}); }, "exactly"));
  CHECK(message_has([&] { (void)move_curve_poles_redge(edge, {}); }, "at least one"));
  CHECK_THROWS_AS((void)move_curve_poles_redge(edge, {{0, {NAN, 0, 0}}}), Error);
}

TEST_CASE("an edit records its op, its params and a delta in which the face and its edges continue") {
  const Face face = patch();
  Capture capture;
  RecorderScope scope(&capture);
  const Face moved = move_surface_poles_rface(face, {{{1, 1}, {1, 1, 3}}}, "skin");
  REQUIRE(capture.records.size() == 1);
  const OpRecord& record = capture.records.front();
  CHECK(record.op == "move_surface_poles_rface");
  CHECK(record.inputs.size() == 1);
  CHECK(record.params.find("moves")->as_array().size() == 1);
  CHECK(record.params.find("tag_prefix")->as_string() == "skin");
  REQUIRE(record.delta.has_value());
  int faces = 0, edges = 0;
  for (const TopoEntry& entry : record.delta->entries) {
    CHECK(entry.event == TopoEvent::Modified);
    faces += entry.ref.kind == Kind::Face;
    edges += entry.ref.kind == Kind::Edge;
  }
  CHECK(faces == 1);
  CHECK(edges == 4);
  CHECK(moved.has_tag("skin.face"));
}

TEST_CASE("rebuild refits in the shape's own parameters; sampling gives curvature and clipped isocurves") {
  const Edge edge = spline({{0, 0, 0}, {1, 2, 0}, {2, 0, 0}, {3, 2, 0}, {4, 0, 0}});
  const Edge rebuilt = rebuild_curve_redge(edge, {.degree = 3, .tolerance = 1e-4});
  const Value r = inspect_curve_rcurvedata(rebuilt);
  CHECK(r.find("degree")->as_int() == 3);
  const double first = r.find("parameter_range")->as_array()[0].as_double();
  const double last = r.find("parameter_range")->as_array()[1].as_double();
  for (int i = 0; i <= 10; ++i) {
    const double t = first + (last - first) * i / 10;
    CHECK(curve_point(rebuilt, t).Distance(curve_point(edge, t)) < 1e-4);
  }
  const Edge coarse = rebuild_curve_redge(edge, {.degree = 2, .pole_count = 4});
  CHECK(inspect_curve_rcurvedata(coarse).find("poles")->as_array().size() == 4);
  CHECK(valid(rebuild_curve_redge(line({0, 0, 0}, {1, 0, 0}), {.degree = 3, .pole_count = 4})));

  const Face holed =
      move_surface_poles_rface(trim_surface_rface(patch(0.0), rectangle(1.2, 1.2, 1.0, 1.0)), {{{1, 1}, {1, 1, 1}}});
  const Face refit = rebuild_surface_rface(holed, {.u_degree = 3, .v_degree = 3, .u_pole_count = 5, .v_pole_count = 5});
  CHECK(valid(refit));
  CHECK(inspect_surface_rsurfacedata(refit).find("u_degree")->as_int() == 3);
  CHECK(std::abs(refit.area() - holed.area()) < 1e-3 * holed.area());
  CHECK(message_has([&] { (void)rebuild_surface_rface(holed, {.u_pole_count = 5}); }, "both"));

  const Value comb = sample_curve_rcurvature(edge, 9);
  CHECK(comb.find("points")->as_array().size() == 9);
  CHECK(comb.find("max_curvature")->as_double() > 0.0);
  const Value straight = sample_curve_rcurvature(line({0, 0, 0}, {1, 0, 0}), 3);
  CHECK(straight.find("max_curvature")->as_double() == doctest::Approx(0.0));

  const Value iso = sample_surface_risocurves(holed, 3, 2, 20);
  CHECK(iso.find("u")->as_array().size() == 3);
  CHECK(iso.find("v")->as_array().size() == 2);
  for (const Value& line_value : iso.find("u")->as_array())
    for (const Value& segment : line_value.find("segments")->as_array())
      for (const Value& p : segment.as_array()) {
        CHECK(vec(p).x >= 0.4 - 1e-6);
        CHECK(vec(p).x <= 1.6 + 1e-6);
      }
}
