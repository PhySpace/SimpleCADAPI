#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRepPrimAPI_MakeTorus.hxx>
#include <GC_MakeEllipse.hxx>
#include <Geom_BezierSurface.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <gp_Elips.hxx>

#include "doctest.h"
#include "fixtures.hpp"
#include "scad/core/error.hpp"
#include "scad/ql/ql.hpp"

using namespace scad;

namespace {

bool starts_with(const std::string& s, std::string_view prefix) {
  return s.rfind(prefix, 0) == 0;
}

Face lateral_face(const Solid& solid, std::string_view type) {
  for (const Face& f : solid.faces())
    if (ql::geom_type(f) == type)
      return f;
  FAIL("no face of that type");
  return solid.faces().front();
}

// Installs an evidence provider for one test and removes it again.
class ProviderGuard {
 public:
  explicit ProviderGuard(ql::EvidenceProvider provider) { ql::set_evidence_provider(std::move(provider)); }
  ~ProviderGuard() { ql::set_evidence_provider({}); }
  ProviderGuard(const ProviderGuard&) = delete;
  ProviderGuard& operator=(const ProviderGuard&) = delete;
};

}  // namespace

TEST_CASE("inventory lines: planes, cylinders, cones, spheres, tori, freeform surfaces") {
  const Solid cyl = ql_test::cylinder(2, 5);
  CHECK(ql::entity_geometry_summary(lateral_face(cyl, "CYLINDER")) ==
        "cylinder r=2, axis (0,0,1) @ (0,0,0), spans z=[0, 5]");
  CHECK(starts_with(ql::entity_geometry_summary(lateral_face(cyl, "PLANE")), "plane, normal ("));
  CHECK(ql::entity_geometry_summary(lateral_face(cyl, "PLANE")).find(", spans ") != std::string::npos);

  const Solid cone(BRepPrimAPI_MakeCone(2, 1, 3).Solid());
  CHECK(ql::entity_geometry_summary(lateral_face(cone, "CONE")) ==
        "cone half-angle -18.4 deg, r_ref=2, spans z=[0, 3]");

  const Solid sphere(BRepPrimAPI_MakeSphere(5).Solid());
  CHECK(ql::entity_geometry_summary(sphere.faces().front()) == "sphere r=5, spans x=[-5, 5]");

  const Solid torus(BRepPrimAPI_MakeTorus(10, 2).Solid());
  CHECK(ql::entity_geometry_summary(torus.faces().front()) == "torus R=10, r=2, spans x=[-12, 12]");

  TColgp_Array2OfPnt poles(1, 2, 1, 2);
  poles.SetValue(1, 1, gp_Pnt(0, 0, 0));
  poles.SetValue(1, 2, gp_Pnt(0, 4, 1));
  poles.SetValue(2, 1, gp_Pnt(6, 0, 1));
  poles.SetValue(2, 2, gp_Pnt(6, 4, 0));
  const Face patch(BRepBuilderAPI_MakeFace(new Geom_BezierSurface(poles), 1e-6).Face());
  CHECK(starts_with(ql::entity_geometry_summary(patch), "freeform surface, spans x=["));
}

TEST_CASE("inventory lines: lines, arcs, other curves, vertices, other kinds") {
  const Solid cyl = ql_test::cylinder(2, 5);
  Edge circle = cyl.edges().front();
  for (const Edge& e : cyl.edges())
    if (ql::geom_type(e) == "CIRCLE")
      circle = e;
  CHECK(ql::entity_geometry_summary(circle) == "circular arc r=2, length 12.57 mm");
  for (const Edge& e : cyl.edges())
    if (ql::geom_type(e) == "LINE")
      CHECK(ql::entity_geometry_summary(e) == "line, length 5 mm");

  const gp_Elips ellipse = GC_MakeEllipse(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 4, 2).Value()->Elips();
  const Edge ellipse_edge(BRepBuilderAPI_MakeEdge(ellipse).Edge());
  CHECK(starts_with(ql::entity_geometry_summary(ellipse_edge), "curve, length 19."));

  const Solid box = ql_test::box(1, 2, 3, {1, 2, 3});
  const Vertex v = box.edges().front().start_vertex();
  const std::string text = ql::entity_geometry_summary(v);
  CHECK(text.front() == '(');
  CHECK(text.back() == ')');

  CHECK(ql::entity_geometry_summary(box) == "solid");
  CHECK(ql::entity_geometry_summary(box.faces().front().outer_wire()) == "wire");
}

TEST_CASE("faces on one underlying surface form a logical group, adjacent or not") {
  const Solid part = ql_test::split_band_solid();
  std::vector<Shape> cylinders;
  for (const Face& f : part.faces())
    if (ql::geom_type(f) == "CYLINDER")
      cylinders.push_back(f);
  REQUIRE(cylinders.size() == 3);
  const auto groups = ql::face_logical_groups(cylinders);
  REQUIRE(groups.size() == 1);  // the two r=10 bands; the r=9 groove is another surface
  CHECK(groups[0].size() == 2);

  // two boxes side by side: their top faces lie in one plane
  const Compound row = ql_test::compound_of({ql_test::box(1, 1, 1), ql_test::box(1, 1, 1, {4, 0, 0})});
  std::vector<Shape> ups;
  for (const Face& f : row.faces())
    if (f.normal_at().z > 0.9)
      ups.push_back(f);
  REQUIRE(ups.size() == 2);
  CHECK(ql::face_logical_groups(ups).size() == 1);
  CHECK(ql::face_logical_groups({ups[0]}).empty());

  // a raised copy is a different plane; rotated cylinders are different surfaces
  const Compound stack = ql_test::compound_of({ql_test::box(1, 1, 1), ql_test::box(1, 1, 1, {0, 0, 3})});
  std::vector<Shape> stacked;
  for (const Face& f : stack.faces())
    if (f.normal_at().z > 0.9)
      stacked.push_back(f);
  CHECK(ql::face_logical_groups(stacked).empty());
  const Compound cyls = ql_test::compound_of({ql_test::cylinder(1, 2), ql_test::cylinder(1, 2, {5, 0, 0})});
  std::vector<Shape> sides;
  for (const Face& f : cyls.faces())
    if (ql::geom_type(f) == "CYLINDER")
      sides.push_back(f);
  CHECK(ql::face_logical_groups(sides).empty());
}

TEST_CASE("the logical group is named in the repair line, symbols follow candidate order") {
  const Solid part = ql_test::split_band_solid();
  try {
    (void)ql::faces().where(ql::surface_type("CYLINDER")).exactly(1).resolve(part);
    FAIL("expected an Error");
  } catch (const Error& e) {
    const ErrorGuidance& g = e.guidance();
    CHECK(g.what_happened ==
          "QL selector expected exactly 1 face(s), got 3; the matched faces include 1 logical surface group(s) split "
          "by seams");
    REQUIRE(g.repair.size() == 2);
    CHECK(g.repair[0].find("lie on one logical surface") != std::string::npos);
    CHECK(g.repair[0].find("F1+F6") != std::string::npos);
    CHECK(g.repair[0].find(" \xE2\x80\x94 select the whole group") != std::string::npos);
    int hits = 0;
    std::vector<std::string> radial;
    for (const auto& entry : g.inventory) {
      hits += entry.status == "hit";
      if (entry.status == "hit" && entry.description.find("r=10") != std::string::npos)
        radial.push_back(entry.description);
    }
    CHECK(hits == 3);
    REQUIRE(radial.size() == 2);
    CHECK(radial[0] != radial[1]);  // the two bands differ by their axial span
    CHECK(radial[0].find("z=[") != std::string::npos);
  }
}

TEST_CASE("symbols use one letter per kind") {
  const Solid box = ql_test::box(1, 1, 1);
  const auto first_symbol = [](const std::function<void()>& body) {
    try {
      body();
    } catch (const Error& e) {
      return e.guidance().inventory.front().symbol;
    }
    return std::string("none");
  };
  CHECK(first_symbol([&] { (void)ql::faces().exactly(0).resolve(box); }) == "F1");
  CHECK(first_symbol([&] { (void)ql::edges().exactly(0).resolve(box); }) == "E1");
  CHECK(first_symbol([&] { (void)ql::vertices().exactly(0).resolve(box); }) == "V1");
  CHECK(first_symbol([&] { (void)ql::solids().exactly(2).resolve(box); }) == "S1");
  CHECK(first_symbol([&] {
          (void)ql::faces().exactly(0).resolve(box.faces()[0].outer_wire().edges()[0].incident_faces()[0]);
        }) == "F1");
}

TEST_CASE("an evidence provider is asked once per failure and its views reach the message") {
  const Solid part = ql_test::split_band_solid();
  int calls = 0;
  std::string seen_key, seen_kind, seen_mode;
  std::size_t matched = 0, near = 0;
  const ProviderGuard guard([&](const ql::EvidenceRequest& request) {
    ++calls;
    seen_key = request.dedup_key;
    seen_kind = request.target_kind;
    seen_mode = request.mode;
    matched = request.matched.size();
    near = request.near_misses.size();
    ErrorEvidence evidence;
    evidence.kind = "render";
    evidence.path = "/tmp/ql_face_resolve.png";
    evidence.view = "iso";
    evidence.caption = "orange = matched, purple = near miss; see inventory for identities";
    return std::vector<ErrorEvidence>{evidence};
  });
  try {
    (void)ql::faces().where(ql::surface_type("CYLINDER")).exactly(1).resolve(part);
    FAIL("expected an Error");
  } catch (const Error& e) {
    REQUIRE(e.guidance().evidence.size() == 1);
    CHECK(std::string(e.what()).find("Evidence:\n- render view 'iso': /tmp/ql_face_resolve.png (orange = matched") !=
          std::string::npos);
  }
  CHECK(calls == 1);
  CHECK(seen_key == "ql|face|exactly|1|3");
  CHECK(seen_kind == "face");
  CHECK(seen_mode == "exactly");
  CHECK(matched == 3);
  CHECK(near == 3);  // capped at three
}

TEST_CASE("a throwing evidence provider never masks the failure") {
  const Solid box = ql_test::box(1, 1, 1);
  const ProviderGuard guard(
      [](const ql::EvidenceRequest&) -> std::vector<ErrorEvidence> { throw RuntimeError("renderer is down"); });
  try {
    (void)ql::faces().exactly(0).resolve(box);
    FAIL("expected an Error");
  } catch (const Error& e) {
    CHECK(e.guidance().evidence.empty());
    CHECK(e.guidance().what_happened == "QL selector expected exactly 0 face(s), got 6");
  }
}

TEST_CASE("without a provider the message carries no evidence section") {
  const Solid box = ql_test::box(1, 1, 1);
  try {
    (void)ql::faces().exactly(0).resolve(box);
    FAIL("expected an Error");
  } catch (const Error& e) {
    CHECK(std::string(e.what()).find("Evidence:") == std::string::npos);
  }
}
