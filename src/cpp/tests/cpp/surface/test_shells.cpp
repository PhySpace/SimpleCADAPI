// Shell operators: loft, sew, solid from shell, free boundaries, hole filling, and the
// Gordon cube that closes only when shared edges are exact.
#include "doctest.h"

#include <cmath>
#include <functional>
#include <map>

#include <BRepBuilderAPI_MakeEdge.hxx>
#include <GC_MakeSegment.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <TColgp_HArray1OfPnt.hxx>

#include "scad/core/error.hpp"
#include "scad/surface/fitter.hpp"
#include "scad/surface/hooks.hpp"
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

Shell box_shell(const Solid& box) { return sew_faces_rshell(box.faces()); }

class Capture final : public Recorder {
 public:
  struct Entry {
    OpRecord record;
    std::size_t outputs;
  };
  std::vector<Entry> entries;
  void record(const OpRecord& record, const std::vector<Shape>& outputs) override { entries.push_back({record, outputs.size()}); }
};

}  // namespace

TEST_CASE("loft_rshell: open shell, endpoint wires, side faces and tags") {
  const Wire lower = circle(2.0, 0.0), upper = circle(1.0, 2.0);
  const Shell loft = loft_rshell({lower, upper}, false,
                                 {.tag_prefix = "skin",
                                  .result_tag = "part.skin",
                                  .start_wire_tag = "anchor.inlet",
                                  .end_wire_tag = "anchor.outlet",
                                  .side_faces_tag = "group.side"});
  CHECK_FALSE(loft.is_closed());
  CHECK(loft.faces().size() == 1);
  const auto wires = loft.wires();
  REQUIRE(wires.size() == 2);
  int inlet = 0, outlet = 0;
  for (const Wire& w : wires) {
    inlet += w.has_tag("anchor.inlet", TagScope::Local);
    outlet += w.has_tag("anchor.outlet", TagScope::Local);
  }
  CHECK(inlet == 1);
  CHECK(outlet == 1);
  CHECK(loft.faces()[0].has_tag("group.side", TagScope::Local));
  CHECK(loft.has_tag("part.skin", TagScope::Local));
  CHECK(loft.has_tag("skin.shell", TagScope::Local));
  CHECK(loft.faces()[0].has_tag("skin.face.side", TagScope::Local));
}

TEST_CASE("loft_rshell with a point end, and its section rules") {
  const Wire upper = circle(1.0, 2.0);
  const Shell cone = loft_rshell({upper, point(0, 0, 4)}, false, {.start_wire_tag = "anchor.base"});
  CHECK(cone.wires().size() == 1);
  CHECK(cone.wires()[0].has_tag("anchor.base", TagScope::Local));

  const Wire lower = circle(2.0, 0.0);
  CHECK(message_has([&] { (void)loft_rshell({lower, point(0, 0, 2), circle(1.0, 4.0)}); }, "only at the start or end"));
  CHECK(message_has([&] { (void)loft_rshell({lower, point(0, 0, 2)}, false, {.end_wire_tag = "anchor.end"}); },
                    "end_wire_tag requires"));
  CHECK(message_has([&] { (void)loft_rshell({lower}); }, "requires at least two sections"));
  CHECK(message_has([&] { (void)loft_rshell({point(0, 0, 0), point(0, 0, 1)}); }, "at least one Wire section"));
}

TEST_CASE("loft_rshell asks the installed diagnoser when the kernel fails") {
  static bool asked = false;
  asked = false;
  set_loft_failure_diagnoser(+[](const std::vector<LoftSection>&, std::string_view operation) {
    asked = true;
    throw Error(std::string(operation), ErrorGuidance{"diagnosed", {"x"}, {"y"}, {}, {}, {}, {}, {}, {}, {}});
  });
  // a closed circle and an open polyline cannot be lofted
  const Wire open = polygon({{0, 0, 3}, {1, 0, 3}, {1, 1, 3}}, false);
  CHECK(message_has([&] { (void)loft_rshell({circle(1.0, 0.0), open}); }, "diagnosed"));
  CHECK(asked);
  set_loft_failure_diagnoser(nullptr);
}

TEST_CASE("sew_faces_rshell, free_boundaries_rwirelist and make_solid_from_shell_rsolid on a box") {
  const Solid box_solid = box(1, 2, 3);
  const Shell shell = box_shell(box_solid);
  CHECK(shell.is_closed());
  CHECK(shell.faces().size() == 6);
  CHECK(free_boundaries_rwirelist(shell).empty());

  Shell tagged = shell;
  tagged.faces()[0].apply_tag("role.preserved_face");
  const Solid solid = make_solid_from_shell_rsolid(tagged, "body");
  CHECK(solid.volume() == doctest::Approx(6.0).epsilon(1e-9));
  CHECK(solid.has_tag("body.solid", TagScope::Local));
  int preserved = 0;
  for (const Face& f : solid.faces()) preserved += f.has_tag("role.preserved_face", TagScope::Local);
  CHECK(preserved == 1);
}

TEST_CASE("an open shell has free boundaries and cannot become a solid") {
  const Shell shell = sew_faces_rshell({make_bezier_surface_rface(unit_square_grid())});
  CHECK_FALSE(shell.is_closed());
  CHECK(free_boundaries_rwirelist(shell).size() == 1);
  CHECK(message_has([&] { (void)make_solid_from_shell_rsolid(shell); }, "closed shell"));
  CHECK(message_has([&] { (void)free_boundaries_rwirelist(shell, 0.0); }, "tolerance must be a positive finite value"));
}

TEST_CASE("sew_faces_rshell does not copy tags whose lineage policy is none, and keeps the rest") {
  const Solid solid = box(1, 2, 3);
  Face source = solid.faces()[0];
  source.apply_tag("role.kept");
  const Shell sewn = sew_faces_rshell({source});
  CHECK(sewn.faces().size() == 1);
  CHECK(message_has([] { (void)sew_faces_rshell({}); }, "non-empty Face sequence"));
  CHECK(message_has([&] { (void)sew_faces_rshell({source}, -1.0); }, "tolerance must be a positive finite value"));
}

TEST_CASE("fill_holes_rshell closes a lofted tube") {
  const Shell tube = loft_rshell({circle(1.0, 0.0), circle(1.0, 2.0)});
  CHECK(free_boundaries_rwirelist(tube).size() == 2);
  const Shell closed = fill_holes_rshell(tube);
  CHECK(closed.is_closed());
  CHECK(closed.faces().size() == 3);
  CHECK(free_boundaries_rwirelist(closed).empty());

  const Shell one = fill_holes_rshell(tube, {.hole_indices = std::vector<int>{0}});
  CHECK(free_boundaries_rwirelist(one).size() == 1);
  CHECK(message_has([&] { (void)fill_holes_rshell(tube, {.hole_indices = std::vector<int>{7}}); }, "list index out of range"));
  const Shell open_tube = sew_faces_rshell({make_bezier_surface_rface(unit_square_grid())});
  CHECK(message_has([&] { (void)fill_holes_rshell(open_tube, {.hole_indices = std::vector<int>{0}}); }, "is open") == false);
}

TEST_CASE("every operator records itself; free_boundaries records zero outputs for a closed shell") {
  Capture capture;
  RecorderScope scope(&capture);
  const Shell shell = box_shell(box(1, 1, 1));
  (void)free_boundaries_rwirelist(shell);
  (void)make_solid_from_shell_rsolid(shell);
  REQUIRE(capture.entries.size() == 3);
  CHECK(capture.entries[0].record.op == "sew_faces_rshell");
  CHECK(capture.entries[0].record.inputs.size() == 6);
  CHECK(capture.entries[1].record.op == "free_boundaries_rwirelist");
  CHECK(capture.entries[1].outputs == 0);
  CHECK(capture.entries[2].record.op == "make_solid_from_shell_rsolid");
  const auto& labels = capture.entries[2].record.labels;
  CHECK(std::find(labels.begin(), labels.end(), "solid") != labels.end());
}

TEST_CASE("the cylindrical op records its symbolic scalars by name") {
  struct ExprStub final : ExprNode {
    double eval(const Bindings*) const override { return 0.001; }
    std::string repr() const override { return "surface_tol"; }
  };
  Capture capture;
  RecorderScope scope(&capture);
  const Scalar tolerance{ExprPtr(std::make_shared<ExprStub>())};
  (void)make_cylindrical_surface_rface(2.0, {0.0, kPi}, {0.0, 2.0}, {.tolerance = tolerance});
  REQUIRE(capture.entries.size() == 1);
  REQUIRE(capture.entries[0].record.symbolic.size() == 1);
  CHECK(capture.entries[0].record.symbolic[0].first == "tolerance");
}

// ---- the Gordon cube ---------------------------------------------------------------------------
namespace {

constexpr double kSide = 40.0, kAmplitude = 10.0;
constexpr int kSamples = 9;

double wave(double u, double v) {
  const double envelope = std::pow(std::sin(kPi * u), 2) * std::pow(std::sin(kPi * v), 2);
  return kAmplitude * envelope * std::sin(4 * kPi * u) * std::sin(6 * kPi * v);
}

Vec3 corner(const std::string& label) {
  return {(label[0] == '+' ? 1 : -1) * kSide, (label[1] == '+' ? 1 : -1) * kSide, (label[2] == '+' ? 1 : -1) * kSide};
}

Vec3 point_on(const std::string& face, double u, double v) {
  const double a = (u - 0.5) * 2 * kSide, b = (v - 0.5) * 2 * kSide, o = wave(u, v);
  if (face == "+z") return {a, b, kSide + o};
  if (face == "-z") return {a, b, -kSide - o};
  if (face == "+x") return {kSide + o, a, b};
  if (face == "-x") return {-kSide - o, a, b};
  if (face == "+y") return {a, kSide + o, b};
  return {a, -kSide - o, b};
}

Edge spline(const std::vector<Vec3>& points) {
  Handle(TColgp_HArray1OfPnt) array = new TColgp_HArray1OfPnt(1, static_cast<int>(points.size()));
  for (std::size_t i = 0; i < points.size(); ++i) array->SetValue(static_cast<int>(i) + 1, gp_Pnt(points[i].x, points[i].y, points[i].z));
  GeomAPI_Interpolate interpolation(array, false, 1e-5);
  interpolation.Perform();
  return Edge(BRepBuilderAPI_MakeEdge(interpolation.Curve()).Edge());
}

}  // namespace

TEST_CASE("six Gordon patches on shared edges sew into a closed solid of the exact volume") {
  if (!surface::gordon_available()) return;
  const std::map<std::string, std::array<std::string, 4>> loops = {
      {"+z", {"--+", "+-+", "+++", "-++"}}, {"-z", {"---", "+--", "++-", "-+-"}}, {"+x", {"+--", "++-", "+++", "+-+"}},
      {"-x", {"---", "-+-", "-++", "--+"}}, {"+y", {"-+-", "++-", "+++", "-++"}}, {"-y", {"---", "+--", "+-+", "--+"}}};
  std::map<std::pair<std::string, std::string>, Edge> shared;
  const auto key = [](const std::string& a, const std::string& b) { return a < b ? std::pair{a, b} : std::pair{b, a}; };
  for (const auto& [face, c] : loops)
    for (std::size_t i = 0; i < 4; ++i) {
      const auto k = key(c[i], c[(i + 1) % 4]);
      if (!shared.count(k)) shared.emplace(k, line(corner(k.first), corner(k.second)));
    }
  CHECK(shared.size() == 12);

  std::vector<Face> faces;
  for (const auto& [face, c] : loops) {
    std::vector<Edge> profiles, guides;
    for (int row = 0; row < kSamples; ++row) {
      const double v = row / double(kSamples - 1);
      if (row == 0) profiles.push_back(shared.at(key(c[0], c[1])));
      else if (row == kSamples - 1) profiles.push_back(shared.at(key(c[3], c[2])));
      else {
        std::vector<Vec3> pts;
        for (int k = 0; k < kSamples; ++k) pts.push_back(point_on(face, k / double(kSamples - 1), v));
        profiles.push_back(spline(pts));
      }
    }
    for (int col = 0; col < kSamples; ++col) {
      const double u = col / double(kSamples - 1);
      if (col == 0) guides.push_back(shared.at(key(c[0], c[3])));
      else if (col == kSamples - 1) guides.push_back(shared.at(key(c[1], c[2])));
      else {
        std::vector<Vec3> pts;
        for (int k = 0; k < kSamples; ++k) pts.push_back(point_on(face, u, k / double(kSamples - 1)));
        guides.push_back(spline(pts));
      }
    }
    faces.push_back(make_gordon_surface_rface(profiles, guides, 1e-4));
    CHECK(faces.back().area() == doctest::Approx(6882.5098716924).epsilon(1e-4));  // reference face area
  }
  const Shell shell = sew_faces_rshell(faces, 1e-5);
  CHECK(shell.is_closed());
  CHECK(shell.faces().size() == 6);
  const Solid solid = make_solid_from_shell_rsolid(shell);
  CHECK(solid.volume() == doctest::Approx(80.0 * 80.0 * 80.0).epsilon(1e-6));
}

TEST_CASE("loft_rshell through polygons names both boundaries") {
  const Shell loft = loft_rshell({rectangle(2, 2, 0, 0, 0), rectangle(1, 1, 0, 0, 3)}, false,
                                 {.start_wire_tag = "anchor.start", .end_wire_tag = "anchor.end"});
  CHECK(loft.faces().size() == 4);
  CHECK(loft.area() == doctest::Approx(18.24828759089466).epsilon(1e-9));
  const auto wires = loft.wires();
  REQUIRE(wires.size() == 2);
  int start = 0, end = 0;
  for (const Wire& w : wires) {
    start += w.has_tag("anchor.start", TagScope::Local);
    end += w.has_tag("anchor.end", TagScope::Local);
  }
  CHECK(start == 1);
  CHECK(end == 1);
}
