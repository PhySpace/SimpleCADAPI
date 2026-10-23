#include "scad/kernel/curves.hpp"

#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepLib.hxx>
#include <GCE2d_MakeSegment.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <GC_MakeCircle.hxx>
#include <GC_MakeEllipse.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <Geom2d_Line.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Circ.hxx>
#include <gp_Dir2d.hxx>
#include <gp_Pnt2d.hxx>

#include <cmath>

#include "scad/core/error.hpp"
#include "scad/kernel/convert.hpp"

namespace scad::kernel {

namespace {

gp_Ax2 plane_axes(const Vec3& center, const Vec3& normal, const std::optional<Vec3>& x_direction) {
  const gp_Pnt origin = to_pnt(center);
  const gp_Dir main = to_dir(normal, "normal");
  return x_direction ? gp_Ax2(origin, main, to_dir(*x_direction, "x direction")) : gp_Ax2(origin, main);
}

gp_Ax3 frame_axes(const Vec3& center, const Vec3& direction, const std::optional<Vec3>& x_direction) {
  const gp_Pnt origin = to_pnt(center);
  const gp_Dir main = to_dir(direction, "direction");
  return x_direction ? gp_Ax3(origin, main, to_dir(*x_direction, "x direction")) : gp_Ax3(origin, main);
}

}  // namespace

TopoDS_Edge make_line_edge(const Vec3& start, const Vec3& end) {
  return occt_guard([&] { return BRepBuilderAPI_MakeEdge(to_pnt(start), to_pnt(end)).Edge(); });
}

TopoDS_Edge make_circle_edge(const Vec3& center, double radius, const Vec3& normal,
                             const std::optional<Vec3>& x_direction) {
  return occt_guard([&] {
    const GC_MakeCircle circle(plane_axes(center, normal, x_direction), radius);
    return BRepBuilderAPI_MakeEdge(circle.Value()).Edge();
  });
}

TopoDS_Edge make_ellipse_edge(const Vec3& center, double major_radius, double minor_radius,
                              const Vec3& normal, const std::optional<Vec3>& major_direction) {
  if (major_radius <= 0.0 || minor_radius <= 0.0) throw ValueError("Ellipse radii must be positive");
  if (minor_radius > major_radius) throw ValueError("Ellipse minor radius must not exceed the major radius");
  return occt_guard([&] {
    const GC_MakeEllipse ellipse(plane_axes(center, normal, major_direction), major_radius, minor_radius);
    return BRepBuilderAPI_MakeEdge(ellipse.Value()).Edge();
  });
}

TopoDS_Edge make_arc_three_point_edge(const Vec3& start, const Vec3& middle, const Vec3& end) {
  return occt_guard([&] {
    const GC_MakeArcOfCircle arc(to_pnt(start), to_pnt(middle), to_pnt(end));
    return BRepBuilderAPI_MakeEdge(arc.Value()).Edge();
  });
}

TopoDS_Edge make_arc_angle_edge(const Vec3& center, double radius, double start_angle, double end_angle,
                                const Vec3& normal, const std::optional<Vec3>& x_direction) {
  return occt_guard([&] {
    const gp_Circ circle(plane_axes(center, normal, x_direction), radius);
    const GC_MakeArcOfCircle arc(circle, start_angle, end_angle, true);
    return BRepBuilderAPI_MakeEdge(arc.Value()).Edge();
  });
}

TopoDS_Edge make_bspline_edge(const BSplineSpec& spec) {
  return occt_guard([&] {
    const auto poles_n = static_cast<int>(spec.control_points.size());
    const auto knots_n = static_cast<int>(spec.knots.size());
    const auto mults_n = static_cast<int>(spec.multiplicities.size());

    TColgp_Array1OfPnt poles(1, poles_n);
    for (int i = 0; i < poles_n; ++i) poles.SetValue(i + 1, to_pnt(spec.control_points[static_cast<std::size_t>(i)]));
    TColStd_Array1OfReal knots(1, knots_n);
    for (int i = 0; i < knots_n; ++i) knots.SetValue(i + 1, spec.knots[static_cast<std::size_t>(i)]);
    TColStd_Array1OfInteger mults(1, mults_n);
    for (int i = 0; i < mults_n; ++i) mults.SetValue(i + 1, spec.multiplicities[static_cast<std::size_t>(i)]);

    opencascade::handle<Geom_BSplineCurve> curve;
    if (spec.weights.empty()) {
      curve = new Geom_BSplineCurve(poles, knots, mults, spec.degree, spec.periodic);
    } else {
      const auto weights_n = static_cast<int>(spec.weights.size());
      TColStd_Array1OfReal weights(1, weights_n);
      for (int i = 0; i < weights_n; ++i) weights.SetValue(i + 1, spec.weights[static_cast<std::size_t>(i)]);
      curve = new Geom_BSplineCurve(poles, weights, knots, mults, spec.degree, spec.periodic);
    }
    return BRepBuilderAPI_MakeEdge(curve).Edge();
  });
}

TopoDS_Edge make_interpolated_bspline_edge(const std::vector<Vec3>& points, bool periodic, double tolerance) {
  return occt_guard([&] {
    const auto n = static_cast<int>(points.size());
    opencascade::handle<TColgp_HArray1OfPnt> through = new TColgp_HArray1OfPnt(1, n);
    for (int i = 0; i < n; ++i) through->SetValue(i + 1, to_pnt(points[static_cast<std::size_t>(i)]));

    GeomAPI_Interpolate interpolator(through, periodic, tolerance);
    interpolator.Perform();
    if (!interpolator.IsDone()) throw ValueError("OCP B-spline interpolation failed");

    BRepBuilderAPI_MakeEdge builder(interpolator.Curve());
    if (!builder.IsDone()) throw ValueError("OCP interpolated B-spline edge builder failed");
    return builder.Edge();
  });
}

TopoDS_Wire make_wire_from_edges(const std::vector<TopoDS_Edge>& edges) {
  return occt_guard([&] {
    BRepBuilderAPI_MakeWire builder;
    for (const TopoDS_Edge& edge : edges) builder.Add(edge);
    return builder.Wire();
  });
}

TopoDS_Wire make_polyline_wire(const std::vector<Vec3>& points, bool closed) {
  std::vector<TopoDS_Edge> edges;
  edges.reserve(points.size());
  for (std::size_t i = 0; i + 1 < points.size(); ++i) edges.push_back(make_line_edge(points[i], points[i + 1]));
  if (closed && points.size() > 2) edges.push_back(make_line_edge(points.back(), points.front()));
  return make_wire_from_edges(edges);
}

TopoDS_Wire make_helix_wire(double pitch, double height, double radius, const Vec3& center,
                            const Vec3& direction, const std::optional<Vec3>& x_direction,
                            std::string_view handedness) {
  if (handedness != "Right" && handedness != "Left") throw ValueError("handedness must be 'Right' or 'Left'");
  if (pitch == 0.0) throw ValueError("helix pitch must be non-zero");
  return occt_guard([&] {
    const opencascade::handle<Geom_Surface> surface =
        new Geom_CylindricalSurface(frame_axes(center, direction, x_direction), radius);

    // A right-handed helix advances counter-clockwise (positive u) as it climbs;
    // negating the u component mirrors the winding without changing the ascent.
    const double u_step = handedness == "Right" ? 2.0 * kPi : -2.0 * kPi;
    const opencascade::handle<Geom2d_Line> line = new Geom2d_Line(gp_Pnt2d(0.0, 0.0), gp_Dir2d(u_step, pitch));
    const double turns = height / pitch;
    const gp_Pnt2d start = line->Value(0.0);
    const gp_Pnt2d stop = line->Value(turns * std::sqrt((2.0 * kPi) * (2.0 * kPi) + pitch * pitch));

    const GCE2d_MakeSegment segment(start, stop);
    const TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(segment.Value(), surface).Edge();
    const TopoDS_Wire wire = BRepBuilderAPI_MakeWire(edge).Wire();
    // The helix exists only as a pcurve on the cylinder until a 3D curve is built.
    BRepLib::BuildCurves3d(wire, 1e-6, GeomAbs_C1, 14, 2000);
    return wire;
  });
}

}  // namespace scad::kernel
