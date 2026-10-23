// Faces from numbers and edges: Bezier, cylindrical, fitted, ruled, Gordon and patch surfaces.
#include "doctest.h"

#include <cmath>
#include <functional>

#include <BRepAdaptor_Surface.hxx>
#include <BRep_Tool.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <Geom_BSplineSurface.hxx>
#include <TopoDS.hxx>

#include "scad/core/coordinate_system.hpp"
#include "scad/core/error.hpp"
#include "scad/surface/fitter.hpp"
#include "scad/surface/hooks.hpp"
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

GeomAbs_SurfaceType surface_type(const Face& face) { return BRepAdaptor_Surface(TopoDS::Face(face.wrapped())).GetType(); }

}  // namespace

TEST_CASE("make_bezier_surface_rface builds a face, tags it and honours the workplane") {
  const Face flat = make_bezier_surface_rface(unit_square_grid());
  CHECK(flat.area() == doctest::Approx(1.0).epsilon(1e-9));
  CHECK(surface_type(flat) == GeomAbs_BezierSurface);

  const Face tagged = make_bezier_surface_rface(unit_square_grid(1.0), std::nullopt, "skin");
  CHECK(tagged.has_tag("skin.face", TagScope::Local));
  CHECK(tagged.area() == doctest::Approx(1.2807892752737977).epsilon(1e-9));  // reference: tests/golden

  Workplane plane({10, 20, 30}, {0, 1, 0}, {1, 0, 0});
  plane.enter();
  const Face placed = make_bezier_surface_rface(unit_square_grid(1.0));
  plane.exit();
  CHECK(placed.center().x == doctest::Approx(10.525156).epsilon(1e-5));
  CHECK(placed.area() == doctest::Approx(tagged.area()).epsilon(1e-9));
}

TEST_CASE("make_bezier_surface_rface rejects bad grids and weights with the public error contract") {
  CHECK_THROWS_AS((void)make_bezier_surface_rface({{{0, 0, 0}}}), Error);
  CHECK(message_has([] { (void)make_bezier_surface_rface({{{0, 0, 0}}}); }, "rectangular finite grid"));
  CHECK(message_has([] { (void)make_bezier_surface_rface(unit_square_grid(), WeightGrid{{1, 1}}); },
                    "Bezier weights must match the control-point grid"));
  CHECK(message_has([] { (void)make_bezier_surface_rface(unit_square_grid(), WeightGrid{{1, -1}, {1, 1}}); },
                    "positive finite values"));
  const Face rational = make_bezier_surface_rface(unit_square_grid(1.0), WeightGrid{{1, 1}, {1, 2}});
  CHECK(rational.area() > 0.0);
}

TEST_CASE("make_cylindrical_surface_rface: area, validity limits and unit-aware scalars") {
  const Face carrier = make_cylindrical_surface_rface(2.0, {0.0, 2 * kPi}, {0.0, 2.0});
  CHECK(carrier.area() == doctest::Approx(8 * kPi).epsilon(1e-9));
  CHECK(surface_type(carrier) == GeomAbs_Cylinder);

  CHECK(message_has([] { (void)make_cylindrical_surface_rface(2.0, {0.0, 1.0001e-12}, {0.0, 2.0}); }, "u_range"));
  CHECK(message_has([] { (void)make_cylindrical_surface_rface(2.0, {0.0, 1.0}, {0.0, 1.0e-8}); }, "v_range"));
  CHECK(message_has([] { (void)make_cylindrical_surface_rface(-1.0, {0.0, 1.0}, {0.0, 1.0}); }, "radius must be a positive finite value"));
  CHECK(message_has([] { (void)make_cylindrical_surface_rface(1.0, {0.0, 7.0}, {0.0, 1.0}); }, "at most one revolution"));
  CHECK(message_has(
      [] { (void)make_cylindrical_surface_rface(1.0, {0.0, 1.0}, {0.0, 1.0}, {.axis = {1, 0, 0}, .x_direction = ScalarVec3{2, 0, 0}}); },
      "must not be parallel"));
}

TEST_CASE("the units probe makes make_cylindrical_surface_rface reject mis-dimensioned scalars") {
  struct ExprStub final : ExprNode {
    double eval(const Bindings*) const override { return 1.0; }
    std::string repr() const override { return "stub"; }
  };
  const Scalar symbolic{ExprPtr(std::make_shared<ExprStub>())};
  set_scalar_units_probe(+[](const Scalar&) { return ScalarUnits{true, UnitDimension::Other}; });
  CHECK(message_has([&] { (void)make_cylindrical_surface_rface(symbolic, {0.0, 1.0}, {0.0, 1.0}); }, "radius must use model length units"));
  CHECK(message_has([&] { (void)make_cylindrical_surface_rface(1.0, {0.0, symbolic}, {0.0, 1.0}); }, "unitless raw radians"));
  CHECK(message_has([&] { (void)make_cylindrical_surface_rface(1.0, {0.0, 1.0}, {0.0, 1.0}, {.tolerance = symbolic}); },
                    "tolerance must use model length units"));
  set_scalar_units_probe(+[](const Scalar&) { return ScalarUnits{true, UnitDimension::Length}; });
  CHECK(make_cylindrical_surface_rface(symbolic, {0.0, kPi}, {0.0, 2.0}).area() == doctest::Approx(2 * kPi).epsilon(1e-9));
  set_scalar_units_probe(nullptr);
}

TEST_CASE("fit_point_grid_rface fits a planar grid and validates its controls") {
  const Face fitted = fit_point_grid_rface(unit_square_grid(), {.degree_min = 1, .degree_max = 3});
  CHECK(fitted.area() == doctest::Approx(1.0).epsilon(1e-6));
  CHECK(message_has([] { (void)fit_point_grid_rface(unit_square_grid(), {.tolerance = 0.0}); }, "positive tolerance"));
  CHECK(message_has([] { (void)fit_point_grid_rface(unit_square_grid(), {.degree_min = 4, .degree_max = 3}); },
                    "degree_max must be greater than or equal to degree_min"));
  CHECK(message_has([] { (void)fit_point_grid_rface(unit_square_grid(), {.smoothing = std::array<double, 3>{1, -1, 1}}); },
                    "three finite non-negative weights"));
}

TEST_CASE("make_ruled_surface_rface spans two edges") {
  const Face ruled = make_ruled_surface_rface(line({0, 0, 0}, {1, 0, 0}), line({0, 0, 1}, {1, 0, 1}), "ruled");
  CHECK(ruled.area() == doctest::Approx(1.0).epsilon(1e-9));
  CHECK(ruled.has_tag("ruled.face", TagScope::Local));
}

TEST_CASE("make_gordon_surface_rface interpolates a planar network exactly") {
  if (!surface::gordon_available()) return;
  const Face gordon = make_gordon_surface_rface({line({0, 0, 0}, {1, 0, 0}), line({0, 1, 0}, {1, 1, 0})},
                                                {line({0, 0, 0}, {0, 1, 0}), line({1, 0, 0}, {1, 1, 0})});
  CHECK(gordon.area() == doctest::Approx(1.0).epsilon(1e-9));
  // Straight edges are not refitted: the reference gives a bilinear 2 x 2 patch.
  const auto surface = Handle(Geom_BSplineSurface)::DownCast(BRep_Tool::Surface(TopoDS::Face(gordon.wrapped())));
  REQUIRE_FALSE(surface.IsNull());
  CHECK(surface->UDegree() == 1);
  CHECK(surface->VDegree() == 1);
  CHECK(surface->NbUPoles() == 2);
  CHECK(surface->NbVPoles() == 2);
}

TEST_CASE("make_gordon_surface_rface rejects small or disjoint networks") {
  if (!surface::gordon_available()) return;
  CHECK(message_has([] { (void)make_gordon_surface_rface({line({0, 0, 0}, {1, 0, 0})}, {line({0, 0, 0}, {0, 1, 0})}); },
                    "at least two profiles and two guides"));
  CHECK(message_has(
      [] {
        (void)make_gordon_surface_rface({line({0, 0, 0}, {1, 0, 0}), line({0, 1, 0}, {1, 1, 0})},
                                        {line({5, 0, 0}, {5, 1, 0}), line({6, 0, 0}, {6, 1, 0})});
      },
      "Failed to create the Gordon surface face"));
  CHECK(message_has([] { (void)make_gordon_surface_rface({}, {}, 0.0); }, "Gordon"));
}

TEST_CASE("make_surface_patch_rface fills a square boundary, with and without a hole") {
  std::vector<Vec3> corners{{0, 0, 1}, {2, 0, 1}, {2, 2, 1}, {0, 2, 1}};
  std::vector<SurfaceBoundary> boundaries;
  for (std::size_t i = 0; i < 4; ++i) boundaries.emplace_back(line(corners[i], corners[(i + 1) % 4]));
  const Face patch = make_surface_patch_rface(boundaries, {.tag_prefix = "patch"});
  CHECK(patch.area() == doctest::Approx(4.0).epsilon(1e-6));
  CHECK(patch.has_tag("patch.face", TagScope::Local));
  CHECK(patch.outer_wire().edges().size() == 4);

  const Face holed = make_surface_patch_rface(boundaries, {.holes = {rectangle(0.5, 0.5, 1.0, 1.0, 1.0)}});
  // The reference adds the hole wire as given: it comes out with two wires (and, for this
  // orientation, a degenerate area -- reproduced, not fixed).
  CHECK(holed.wires().size() == 2);

  CHECK(message_has([] { (void)make_surface_patch_rface({}); }, "non-empty SurfaceBoundary"));
  CHECK_THROWS_AS(SurfaceBoundary(line({0, 0, 0}, {1, 0, 0}), "C3"), ValueError);
  CHECK(SurfaceBoundary(line({0, 0, 0}, {1, 0, 0}), "g1").continuity == "G1");
}

TEST_CASE("SurfaceFillingSettings validates like its Python dataclass") {
  CHECK_NOTHROW(SurfaceFillingSettings{}.validate());
  CHECK_THROWS_AS((SurfaceFillingSettings{.degree = 0}).validate(), ValueError);
  CHECK_THROWS_AS((SurfaceFillingSettings{.degree = 4, .max_degree = 3}).validate(), ValueError);
  CHECK_THROWS_AS((SurfaceFillingSettings{.tolerance_3d = -1}).validate(), ValueError);
  CHECK(SurfaceFillingSettings{}.as_dict().size() == 10);
}

TEST_CASE("a replaced SurfaceFitter is the one the operators use") {
  struct Counting final : surface::SurfaceFitter {
    mutable int grid_fits = 0;
    Handle(Geom_BSplineSurface) fit_point_grid(const PointGrid& g, const surface::GridFit& o) const override {
      ++grid_fits;
      return surface::occt_surface_fitter()->fit_point_grid(g, o);
    }
    TopoDS_Face fill(const surface::FillingProblem& p) const override { return surface::occt_surface_fitter()->fill(p); }
    Handle(Geom_BSplineSurface) gordon(const std::vector<Handle(Geom_Curve)>& a, const std::vector<Handle(Geom_Curve)>& b,
                                       double t) const override {
      return surface::occt_surface_fitter()->gordon(a, b, t);
    }
  };
  auto counting = std::make_shared<Counting>();
  surface::set_surface_fitter(counting);
  (void)fit_point_grid_rface(unit_square_grid());
  surface::set_surface_fitter(nullptr);
  (void)fit_point_grid_rface(unit_square_grid());
  CHECK(counting->grid_fits == 1);
}
