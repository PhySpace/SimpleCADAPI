#pragma once
// The Y-junction case family: a concave and a convex fillet edge meeting, tangentially or
// nearly so, on a common face, with their other supports tangent or nearly tangent.
#include "fixtures.hxx"
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepAlgoAPI_Common.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <cmath>
#include <vector>

struct Case
{
  std::string                       name;
  TopoDS_Shape                      shape;
  std::vector<std::pair<gp_Pnt, double>> picks; // a point on each selected edge, radius
  bool                              expect_refusal = false; // outside the domain: Perform must say no
};

inline TopoDS_Edge edge_at(const TopoDS_Shape& s, const gp_Pnt& p)
{
  TopTools_IndexedMapOfShape m;
  TopExp::MapShapes(s, TopAbs_EDGE, m);
  TopoDS_Vertex v = BRepBuilderAPI_MakeVertex(p);
  double best = 1e100;
  TopoDS_Edge out;
  for (int i = 1; i <= m.Extent(); ++i)
  {
    BRepExtrema_DistShapeShape d(v, m(i));
    if (d.IsDone() && d.Value() < best)
    {
      best = d.Value();
      out  = TopoDS::Edge(m(i));
    }
  }
  if (best > 1e-6)
    std::printf("  warning: no edge at (%g %g %g), nearest %g\n", p.X(), p.Y(), p.Z(), best);
  return out;
}

inline TopoDS_Shape prism_xy(const std::vector<gp_Pnt2d>& poly, double z0, double z1)
{
  BRepBuilderAPI_MakePolygon mp;
  for (auto& p : poly)
    mp.Add(gp_Pnt(p.X(), p.Y(), z0));
  mp.Close();
  auto f = BRepBuilderAPI_MakeFace(mp.Wire(), true).Face();
  return BRepPrimAPI_MakePrism(f, gp_Vec(0, 0, z1 - z0)).Shape();
}

inline TopoDS_Shape post(double R, double H)
{
  return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(), gp_Dir(0, 0, 1), gp_Dir(-1, 0, 0)), R, H).Shape();
}

inline TopoDS_Shape moved(const TopoDS_Shape& s, const gp_Trsf& t)
{
  return BRepBuilderAPI_Transform(s, t, true).Shape();
}

// r1, r2.5, r12: a radius in a case name
inline std::string radiusTag(double r)
{
  char buf[32];
  std::snprintf(buf, sizeof buf, "r%g", r);
  return buf;
}

inline std::vector<Case> family()
{
  std::vector<Case> cs;
  const double R = 50, h = 40, L = 150;
  // 1. post flush with the plate side (the reference sample), several radii
  for (double r : {1., 2.5, 5., 8., 12.})
    cs.push_back({"flush-" + radiusTag(r), plate_post(R, h), {{gp_Pnt(R, 0, h), r}, {gp_Pnt(75, -R, h), r}}});
  // 1b. the cylinder's default seam (+X) lies on the root, which is then two quarter arcs
  //     (what make_cylinder_rsolid gives every SDK user)
  {
    auto c = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(), gp_Dir(0, 0, 1)), R, 2 * h).Shape();
    auto b = BRepPrimAPI_MakeBox(gp_Pnt(0, -R, 0), 3 * R, 2 * R, h).Shape();
    const double q = R / std::sqrt(2.);
    const TopoDS_Shape s = fuse(c, b);
    for (const double r : {1., 2.5, 5., 8., 12.})
    {
      const std::string tag = radiusTag(r);
      cs.push_back({"flush-seam-on-root-" + tag, s, {{gp_Pnt(q, -q, h), r}, {gp_Pnt(q, q, h), r}, {gp_Pnt(75, -R, h), r}}});
      cs.push_back({"flush-seam-on-root-both-sides-" + tag, s,
                    {{gp_Pnt(q, -q, h), r}, {gp_Pnt(q, q, h), r}, {gp_Pnt(75, -R, h), r}, {gp_Pnt(75, R, h), r}}});
    }
  }
  // 1c. the seam at every eighth of a turn (angle of the cylinder's X direction)
  for (int deg = 0; deg < 360; deg += 45)
  {
    const double a = deg * M_PI / 180;
    auto c = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(), gp_Dir(0, 0, 1), gp_Dir(std::cos(a), std::sin(a), 0)), R, 2 * h).Shape();
    auto b = BRepPrimAPI_MakeBox(gp_Pnt(0, -R, 0), 3 * R, 2 * R, h).Shape();
    Case sc{"seam-at-" + std::to_string(deg), fuse(c, b), {{gp_Pnt(75, -R, h), 5}}};
    for (double t : {-85., -60., -35., -10., 10., 35., 60., 85.}) // root points clear of every seam angle
      sc.picks.push_back({gp_Pnt(R * std::cos(t * M_PI / 180), R * std::sin(t * M_PI / 180), h), 5});
    cs.push_back(sc);
  }
  // 2. both plate sides flush: two junctions on one concave edge
  cs.push_back({"flush-both-sides", plate_post(R, h), {{gp_Pnt(R, 0, h), 5}, {gp_Pnt(75, -R, h), 5}, {gp_Pnt(75, R, h), 5}}});
  // 3. unequal radii
  cs.push_back({"flush-r3-r7", plate_post(R, h), {{gp_Pnt(R, 0, h), 3}, {gp_Pnt(75, -R, h), 7}}});
  cs.push_back({"flush-r7-r3", plate_post(R, h), {{gp_Pnt(R, 0, h), 7}, {gp_Pnt(75, -R, h), 3}}});
  // 4. arbitrary placement
  {
    gp_Trsf t;
    t.SetRotation(gp_Ax1(gp_Pnt(3, -7, 11), gp_Dir(1, 2, 3)), 0.7);
    gp_Trsf m;
    m.SetTranslation(gp_Vec(10, -20, 5));
    t = m * t;
    Case c{"flush-moved", moved(plate_post(R, h), t), {}};
    c.picks = {{gp_Pnt(R, 0, h).Transformed(t), 5}, {gp_Pnt(75, -R, h).Transformed(t), 5}};
    cs.push_back(c);
  }
  // 5. near tangency: the plate side turned outward by d degrees about the junction line
  for (double d : {2., 5., 10.})
  {
    const double a = d * M_PI / 180;
    auto plate = prism_xy({{0, -R}, {L, -R - L * std::tan(a)}, {L, R}, {0, R}}, 0, h);
    cs.push_back({"side-out-" + std::to_string(int(d)) + "deg", fuse(post(R, 2 * h), plate),
                  {{gp_Pnt(R, 0, h), 5}, {gp_Pnt(75, -R - 75 * std::tan(a), h), 5}}});
  }
  // 6. near tangency: the plate side turned inward (it enters the post; the junction moves to
  //    where it leaves the post).  The plate starts at x = 1 and its other side is y = R/2, so
  //    that its end face lies wholly inside the post (no sliver faces).
  for (double d : {2., 5.})
  {
    const double a     = d * M_PI / 180;
    auto         plate = prism_xy({{-R, -R - R * std::tan(a)}, {L, -R + L * std::tan(a)}, {L, R / 2}, {-R, R / 2}}, 0, h);
    auto         cut   = fuse(post(R, 2 * h),
                      BRepAlgoAPI_Common(plate, BRepPrimAPI_MakeBox(gp_Pnt(1, -2 * R, 0), L, 4 * R, h).Shape()).Shape());
    cs.push_back({"side-in-" + std::to_string(int(d)) + "deg", cut,
                  {{gp_Pnt(R * std::cos(0.2), R * std::sin(0.2), h), 5}, {gp_Pnt(120, -R + 120 * std::tan(a), h), 5}}});
  }
  // 7. planar wedge: a block whose face makes d degrees with the plate side; the Y spans about
  //    (r_in + r_out) / tan(d) along the edges, so the block is long enough for it.  The short
  //    variant ends the concave edge before the bands separate: it must be refused.
  struct Wedge
  {
    double      d, e;
    bool        refuse;
    const char* suffix;
  };
  for (const Wedge& wg : {Wedge{5., 140., false, ""}, Wedge{5., 60., true, "-short"}, Wedge{10., 60., false, ""},
                          Wedge{15., 60., false, ""}})
  {
    const double a = wg.d * M_PI / 180, w = 40, e = wg.e;
    auto plate = BRepPrimAPI_MakeBox(gp_Pnt(0, -R, 0), L, 2 * R, h).Shape();
    auto block = prism_xy({{-w, -R - w * std::tan(a)}, {e, -R + e * std::tan(a)}, {e, R}, {-w, R}}, 0, 2 * h);
    Case c{"wedge-" + std::to_string(int(wg.d)) + "deg" + wg.suffix, fuse(plate, block),
           {{gp_Pnt(e / 2, -R + e / 2 * std::tan(a), h), 4}, {gp_Pnt(e + (L - e) / 2, -R, h), 4}}};
    c.expect_refusal = wg.refuse;
    cs.push_back(c);
  }
  // 8. curved plate side: a large arc tangent to the post at the junction
  {
    // The rim (radius R2) leaves the junction, then continues tangentially as a straight side
    // that meets the square plate end: each band's far end is a standard one.
    const double R2 = 140, a0 = 0.5, top = 0.5 * R;
    auto         rp = [&](double a) { return gp_Pnt(R2 * std::sin(a), -R + R2 - R2 * std::cos(a), 0); };
    const gp_Pnt p0 = rp(0), p1 = rp(a0), p2(L, p1.Y() + (L - p1.X()) * std::tan(a0), 0);
    BRepBuilderAPI_MakeWire w;
    w.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(p0, rp(a0 / 2), p1).Value()).Edge());
    w.Add(BRepBuilderAPI_MakeEdge(p1, p2).Edge());
    w.Add(BRepBuilderAPI_MakeEdge(p2, gp_Pnt(L, top, 0)).Edge());
    w.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(L, top, 0), gp_Pnt(0, top, 0)).Edge());
    w.Add(BRepBuilderAPI_MakeEdge(gp_Pnt(0, top, 0), p0).Edge());
    auto plate = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(w.Wire(), true).Face(), gp_Vec(0, 0, h)).Shape();
    gp_Pnt rim = rp(a0 / 2).Translated(gp_Vec(0, 0, h));
    cs.push_back({"curved-side", fuse(post(R, 2 * h), plate), {{gp_Pnt(R, 0, h), 5}, {rim, 5}}});
  }
  // 9. inclined common face: the plate top rises along x
  {
    const double s = 0.15;
    BRepBuilderAPI_MakePolygon mp;
    for (auto p : {gp_Pnt(0, -R, 0), gp_Pnt(L, -R, 0), gp_Pnt(L, -R, h + s * L), gp_Pnt(0, -R, h)})
      mp.Add(p);
    mp.Close();
    auto plate = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(mp.Wire(), true).Face(), gp_Vec(0, 1.5 * R, 0)).Shape();
    const double x = R * std::cos(0.3);
    cs.push_back({"inclined-top", fuse(post(R, 3 * h), plate),
                  {{gp_Pnt(x, R * std::sin(0.3), h + s * x), 5}, {gp_Pnt(75, -R, h + s * 75), 5}}});
  }
  return cs;
}
