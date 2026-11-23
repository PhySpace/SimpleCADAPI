// graphpatch: BRepOffsetAPI_GraphPatch on planar and curved supports. For each loop it prints
// the boundary gap to the supports (mm), the normal angle to the supports (rad, orders >= 1),
// the cross-boundary normal curvature difference (1/mm, order 2) and the deviation of the patch
// from the surface the loop was cut from (mm, sampled on a mesh of the patch); a refused or
// out-of-tolerance case makes the exit status non-zero.
#include "fixtures.hxx"
#include <BRepOffsetAPI_GraphPatch.hxx>
#include <BRepAdaptor_Curve2d.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepGProp.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepOffsetAPI_MakeFilling.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <GeomAPI_PointsToBSplineSurface.hxx>
#include <Geom_BSplineSurface.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <GeomAdaptor_Surface.hxx>
#include <Poly_Triangulation.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <algorithm>
#include <cmath>

namespace
{
struct Loop
{
  std::vector<TopoDS_Edge> edges;
  std::vector<TopoDS_Face> supports;
};

struct Metrics
{
  double gap = 0, angle = 0, curvature = 0, deviation = 0, area = 0;
};

double area(const TopoDS_Shape& s)
{
  GProp_GProps g;
  BRepGProp::SurfaceProperties(s, g);
  return g.Mass();
}

TopoDS_Face largest(const TopoDS_Shape& s, std::function<bool(const TopoDS_Face&)> keep)
{
  TopoDS_Face best;
  double      a = 0;
  for (TopExp_Explorer ex(s, TopAbs_FACE); ex.More(); ex.Next())
  {
    auto f = TopoDS::Face(ex.Current());
    if (keep(f) && area(f) > a)
    {
      a    = area(f);
      best = f;
    }
  }
  return best;
}

// The edges of one support passing `pick`, ordered by angle around their centroid in the plane
// spanned by (a, b): the ordered loop the graph patch takes.
Loop loop_on(const TopoDS_Face&                       support,
             std::function<bool(const gp_Pnt&)>        pick,
             const gp_Vec&                             a,
             const gp_Vec&                             b)
{
  Loop l;
  l.edges = edges_where(support, [&](const TopoDS_Edge& e) { return pick(mid(e)); });
  gp_XYZ c;
  for (auto& e : l.edges)
    c += mid(e).XYZ() / double(l.edges.size());
  auto angle = [&](const TopoDS_Edge& e) {
    gp_Vec d(mid(e).XYZ() - c);
    return std::atan2(d.Dot(b), d.Dot(a));
  };
  std::sort(l.edges.begin(), l.edges.end(), [&](auto& x, auto& y) { return angle(x) < angle(y); });
  l.supports.assign(l.edges.size(), support);
  return l;
}

TopoDS_Shape prism(const std::vector<gp_Pnt>& polygon, const gp_Vec& along)
{
  BRepBuilderAPI_MakePolygon p;
  for (auto& q : polygon)
    p.Add(q);
  p.Close();
  return BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(p.Wire()).Face(), along).Shape();
}

std::vector<gp_Pnt> regular(int sides, double r, double z)
{
  std::vector<gp_Pnt> v;
  for (int i = 0; i < sides; ++i)
    v.emplace_back(r * cos(2 * M_PI * i / sides + .3), r * sin(2 * M_PI * i / sides + .3), z);
  return v;
}

TopoDS_Shape tube_minus(const TopoDS_Shape& tool)
{
  auto tube = BRepAlgoAPI_Cut(BRepPrimAPI_MakeCylinder(30, 60).Shape(),
                              BRepPrimAPI_MakeCylinder(26, 60).Shape())
                .Shape();
  return BRepAlgoAPI_Cut(tube, tool).Shape();
}

TopoDS_Face outer_cylinder(const TopoDS_Shape& s)
{
  return largest(s, [](const TopoDS_Face& f) {
    BRepAdaptor_Surface a(f);
    return a.GetType() == GeomAbs_Cylinder && a.Cylinder().Radius() > 29;
  });
}

// Normal curvature of s at (u, v) along the tangent direction d, the normal oriented along ref.
double normal_curvature(const Adaptor3d_Surface& s, double u, double v, const gp_Vec& d, const gp_Vec& ref)
{
  gp_Pnt p;
  gp_Vec su, sv, suu, svv, suv;
  s.D2(u, v, p, su, sv, suu, svv, suv);
  gp_Vec nn = su.Crossed(sv).Normalized();
  if (nn.Dot(ref) < 0)
    nn.Reverse();
  double E = su.Dot(su), F = su.Dot(sv), G = sv.Dot(sv), det = E * G - F * F;
  double du = (G * d.Dot(su) - F * d.Dot(sv)) / det, dv = (E * d.Dot(sv) - F * d.Dot(su)) / det;
  return (suu.Dot(nn) * du * du + 2 * suv.Dot(nn) * du * dv + svv.Dot(nn) * dv * dv)
         / (E * du * du + 2 * F * du * dv + G * dv * dv);
}

Metrics measure(const Loop&                         l,
                const std::vector<int>&             orders,
                const TopoDS_Face&                  patch,
                std::function<double(const gp_Pnt&)> deviation)
{
  Metrics            m;
  Handle(Geom_Surface) g = BRep_Tool::Surface(patch);
  GeomAdaptor_Surface  ga(g);
  for (size_t i = 0; i < l.edges.size(); ++i)
  {
    BRepAdaptor_Curve2d c(l.edges[i], l.supports[i]);
    BRepAdaptor_Surface s(l.supports[i]);
    for (int j = 0; j <= 64; ++j)
    {
      double   t  = c.FirstParameter() + (c.LastParameter() - c.FirstParameter()) * j / 64;
      gp_Pnt2d uv;
      gp_Vec2d duv;
      c.D1(t, uv, duv);
      gp_Pnt p;
      gp_Vec su, sv;
      s.D1(uv.X(), uv.Y(), p, su, sv);
      GeomAPI_ProjectPointOnSurf proj(p, g);
      if (!proj.NbPoints())
      {
        m.gap = 1e100;
        continue;
      }
      m.gap = std::max(m.gap, proj.LowerDistance());
      if (orders[i] < 1)
        continue;
      double pu, pv;
      proj.LowerDistanceParameters(pu, pv);
      gp_Pnt q;
      gp_Vec qu, qv;
      ga.D1(pu, pv, q, qu, qv);
      gp_Vec ns = su.Crossed(sv).Normalized(), np = qu.Crossed(qv).Normalized();
      m.angle   = std::max(m.angle, std::acos(std::min(1., std::abs(ns.Dot(np)))));
      if (orders[i] < 2)
        continue;
      gp_Vec tangent = su * duv.X() + sv * duv.Y(), cross = ns.Crossed(tangent).Normalized();
      m.curvature    = std::max(m.curvature,
                             std::abs(normal_curvature(s, uv.X(), uv.Y(), cross, ns)
                                      - normal_curvature(ga, pu, pv, cross, ns)));
    }
  }
  BRepMesh_IncrementalMesh(patch, 0.01, false, 0.05);
  TopLoc_Location loc;
  auto            tri = BRep_Tool::Triangulation(patch, loc);
  for (int i = 1; tri && i <= tri->NbNodes(); ++i)
    m.deviation = std::max(m.deviation, deviation(tri->Node(i).Transformed(loc.Transformation())));
  m.area = area(patch);
  return m;
}

int failures = 0;

// Runs one loop with one order everywhere; the patch must be valid and within the limits.
void run(const char*                          name,
         const Loop&                          l,
         int                                  order,
         std::function<double(const gp_Pnt&)> deviation,
         double                               maxDeviation)
{
  std::vector<int> orders(l.edges.size(), order);
  TopoDS_Face      patch;
  bool ok = !l.edges.empty()
            && BRepOffsetAPI_GraphPatch::TryBuild(int(l.edges.size()),
                                                  l.edges.data(),
                                                  l.supports.data(),
                                                  orders.data(),
                                                  patch);
  if (!ok)
  {
    std::printf("%-22s %zu sides order %d: REFUSED\n", name, l.edges.size(), order);
    ++failures;
    return;
  }
  auto m    = measure(l, orders, patch, deviation);
  // the gap is bounded like the deviation: 1e-3 on curved supports, model precision on planar ones
  bool pass = valid(patch) && m.gap <= std::min(1e-3, maxDeviation) && m.angle <= 1e-3
              && m.deviation <= maxDeviation;
  std::printf("%-22s %zu sides order %d: gap %.2e angle %.2e dcurv %.2e deviation %.2e area %.4f %s\n",
              name,
              l.edges.size(),
              order,
              m.gap,
              m.angle,
              m.curvature,
              m.deviation,
              m.area,
              pass ? "ok" : "FAIL");
  failures += !pass;
}
} // namespace

int main()
{
  auto radial = [](double r) {
    return [r](const gp_Pnt& p) { return std::abs(std::hypot(p.X(), p.Y()) - r); };
  };
  // A window through the wall of a tube (radius 30), around +y and away from the seam.
  {
    auto holed = tube_minus(BRepPrimAPI_MakeBox(gp_Pnt(-20, 15, 18), 40, 30, 24).Shape());
    auto loop  = loop_on(outer_cylinder(holed),
                        [](const gp_Pnt& p) { return p.Y() > 20 && p.Z() > 17 && p.Z() < 43; },
                        gp_Vec(1, 0, 0),
                        gp_Vec(0, 0, 1));
    for (int order : {0, 1, 2})
      run("cylinder window", loop, order, radial(30), 1e-3);
    // the plate filling of the same loop, for reference
    BRepOffsetAPI_MakeFilling filling;
    for (auto& e : loop.edges)
      filling.Add(e, loop.supports[0], GeomAbs_G1);
    filling.Build();
    if (filling.IsDone())
    {
      auto f = largest(filling.Shape(), [](const TopoDS_Face&) { return true; });
      std::vector<int> orders(loop.edges.size(), 1);
      auto m = measure(loop, orders, f, radial(30));
      std::printf("%-22s %zu sides order 1: gap %.2e angle %.2e deviation %.2e (plate filling)\n",
                  "cylinder window",
                  loop.edges.size(),
                  m.gap,
                  m.angle,
                  m.deviation);
    }
    // the same edges out of order are no loop: refused
    Loop shuffled = loop;
    std::swap(shuffled.edges[1], shuffled.edges[2]);
    std::vector<int> orders(shuffled.edges.size(), 1);
    TopoDS_Face      patch;
    bool             refused = !BRepOffsetAPI_GraphPatch::TryBuild(int(shuffled.edges.size()),
                                                       shuffled.edges.data(),
                                                       shuffled.supports.data(),
                                                       orders.data(),
                                                       patch);
    std::printf("%-22s %zu sides order 1: out of order %s\n",
                "cylinder window",
                shuffled.edges.size(),
                refused ? "refused, ok" : "ACCEPTED");
    failures += !refused;
  }
  // A triangle through the tube wall: two of its sides are ellipse arcs.
  {
    auto holed = tube_minus(prism({{-15, 10, 20}, {15, 10, 20}, {0, 10, 44}}, gp_Vec(0, 40, 0)));
    auto loop  = loop_on(outer_cylinder(holed),
                        [](const gp_Pnt& p) { return p.Y() > 20 && p.Z() > 19 && p.Z() < 45; },
                        gp_Vec(1, 0, 0),
                        gp_Vec(0, 0, 1));
    for (int order : {1, 2})
      run("cylinder triangle", loop, order, radial(30), 1e-3);
  }
  // A window on a sphere (radius 30), centred on +y at the equator.
  {
    auto holed = BRepAlgoAPI_Cut(BRepPrimAPI_MakeSphere(30).Shape(),
                                 BRepPrimAPI_MakeBox(gp_Pnt(-10, 15, -10), 20, 30, 20).Shape())
                   .Shape();
    auto sphere = largest(holed, [](const TopoDS_Face&) { return true; });
    auto loop   = loop_on(sphere,
                        [](const gp_Pnt& p) { return p.Y() > 15; },
                        gp_Vec(1, 0, 0),
                        gp_Vec(0, 0, 1));
    auto dev    = [](const gp_Pnt& p) { return std::abs(p.Distance(gp::Origin()) - 30); };
    for (int order : {1, 2})
      run("sphere window", loop, order, dev, 1e-3);
    // a pentagonal cap around the pole: the seam crosses the hole, the pole is inside it
    auto capped = BRepAlgoAPI_Cut(BRepPrimAPI_MakeSphere(30).Shape(),
                                  prism(regular(5, 11, 15), gp_Vec(0, 0, 30)))
                    .Shape();
    auto cap    = largest(capped, [](const TopoDS_Face&) { return true; });
    auto rim    = loop_on(cap,
                       [](const gp_Pnt& p) { return p.Z() > 20; },
                       gp_Vec(1, 0, 0),
                       gp_Vec(0, 1, 0));
    for (int order : {1, 2})
      run("sphere cap", rim, order, dev, 1e-3);
  }
  // A bumpy B-spline sheet with 3-, 5- and 6-sided vertical prisms cut through it.
  {
    TColgp_Array2OfPnt grid(1, 9, 1, 9);
    for (int i = 1; i <= 9; ++i)
      for (int j = 1; j <= 9; ++j)
      {
        double x = -40 + 10 * (i - 1), y = -40 + 10 * (j - 1);
        grid(i, j) = gp_Pnt(x, y, 6 * sin(x / 25) * cos(y / 30) + 0.004 * x * y);
      }
    Handle(Geom_Surface) sheet = GeomAPI_PointsToBSplineSurface(grid).Surface();
    auto                 face  = BRepBuilderAPI_MakeFace(sheet, 1e-7).Face();
    auto                 dev   = [sheet](const gp_Pnt& p) {
      GeomAPI_ProjectPointOnSurf proj(p, sheet);
      return proj.NbPoints() ? proj.LowerDistance() : 1e100;
    };
    for (int sides : {3, 5, 6})
    {
      auto holed = BRepAlgoAPI_Cut(face, prism(regular(sides, 15, -30), gp_Vec(0, 0, 60))).Shape();
      auto sheetFace = largest(holed, [](const TopoDS_Face&) { return true; });
      auto loop =
        loop_on(sheetFace,
                [](const gp_Pnt& p) { return std::hypot(p.X(), p.Y()) < 16; },
                gp_Vec(1, 0, 0),
                gp_Vec(0, 1, 0));
      for (int order : {1, 2})
        run("b-spline polygon", loop, order, dev, 1e-3);
    }
  }
  // Holes in a plate and open prisms (the walls hold the loop): planar-representable, exact.
  // The square ones take the rectangular branch, the others the general loop.
  {
    auto plateTop = [](const TopoDS_Shape& tool) {
      auto plate = BRepAlgoAPI_Cut(BRepPrimAPI_MakeBox(gp_Pnt(-20, -20, 0), 40, 40, 5).Shape(), tool).Shape();
      auto top   = largest(plate, [](const TopoDS_Face& f) {
        BRepAdaptor_Surface a(f);
        return a.GetType() == GeomAbs_Plane && a.Plane().Location().Z() > 4.9
               && std::abs(a.Plane().Axis().Direction().Z()) > 0.99;
      });
      return loop_on(top,
                     [](const gp_Pnt& p) { return std::max(std::abs(p.X()), std::abs(p.Y())) < 8; },
                     gp_Vec(1, 0, 0),
                     gp_Vec(0, 1, 0));
    };
    auto flat = [](double z) { return [z](const gp_Pnt& p) { return std::abs(p.Z() - z); }; };
    auto square = plateTop(BRepPrimAPI_MakeBox(gp_Pnt(-5, -5, -2), 10, 10, 9).Shape());
    auto penta  = plateTop(prism(regular(5, 7, -2), gp_Vec(0, 0, 9)));
    for (int order : {1, 2})
    {
      run("plane hole", square, order, flat(5), 1e-9);
      run("plane polygon hole", penta, order, flat(5), 1e-9);
    }
    // the top edges of a prism, each with its wall, ordered around the axis
    auto walls = [](const TopoDS_Shape& solid, double z) {
      std::vector<std::pair<TopoDS_Edge, TopoDS_Face>> found;
      for (TopExp_Explorer ex(solid, TopAbs_FACE); ex.More(); ex.Next())
      {
        auto f = TopoDS::Face(ex.Current());
        if (std::abs(BRepAdaptor_Surface(f).Plane().Axis().Direction().Z()) > 1e-9)
          continue;
        for (auto& e : edges_where(f, [z](const TopoDS_Edge& e) { return std::abs(mid(e).Z() - z) < 1e-9; }))
          found.emplace_back(e, f);
      }
      gp_XYZ c;
      for (auto& w : found)
        c += mid(w.first).XYZ() / double(found.size());
      auto at = [c](const std::pair<TopoDS_Edge, TopoDS_Face>& w) {
        auto p = mid(w.first);
        return std::atan2(p.Y() - c.Y(), p.X() - c.X());
      };
      std::sort(found.begin(), found.end(), [&](auto& a, auto& b) { return at(a) < at(b); });
      Loop l;
      for (auto& w : found)
      {
        l.edges.push_back(w.first);
        l.supports.push_back(w.second);
      }
      return l;
    };
    run("open box", walls(BRepPrimAPI_MakeBox(20, 20, 10).Shape(), 10), 0, flat(10), 1e-9);
    run("open hexagonal prism", walls(prism(regular(6, 12, 0), gp_Vec(0, 0, 10)), 10), 0, flat(10), 1e-9);
  }
  std::printf("%d failure(s)\n", failures);
  return failures ? 1 : 0;
}
