// make_workplane_*_rworkplane: workplanes from the model (see scad/ops/geometry/workplanes.hpp).
#include "scad/ops/geometry/workplanes.hpp"

#include <algorithm>
#include <cmath>
#include <string>
#include <utility>
#include <vector>

#include <BRepAdaptor_CompCurve.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <TopoDS.hxx>
#include <gp_Circ.hxx>
#include <gp_Lin.hxx>
#include <gp_Pln.hxx>

#include "internal.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/ops/geometry/plane.hpp"
#include "scad/topo/value_lineage.hpp"

namespace scad {

using namespace geometry_detail;

namespace {

constexpr double kSquareTolerance = 1e-9;  // |cross| below this: parallel; |projection| below this: degenerate
constexpr double kParallelFaces = 1e-6;    // |n_a x n_b| above this: the faces are not parallel

// Round-off of a centroid or a rotation (|v| < 1e-12): a frame of exact zeros reads better in a cell and a report.
Vec3 clean(const Vec3& v) {
  const auto snap = [](double c) { return std::abs(c) < 1e-12 ? 0.0 : c; };
  return {snap(v.x), snap(v.y), snap(v.z)};
}

// The workplane on (origin, normal, x): x is projected onto the plane first.
Workplane frame(const Vec3& origin_in, const Vec3& normal_in, const Vec3& x_in, const char* x_what) {
  const Vec3 origin = clean(origin_in);
  const Vec3 normal = clean(normal_in);
  const Vec3 x = clean(x_in);
  const double n_norm = normal.norm();
  if (!(n_norm > kSquareTolerance))
    throw ValueError("The workplane normal is a zero vector");
  const Vec3 n = normal / n_norm;
  Vec3 in_plane = x - n * x.dot(n);
  const double x_norm = in_plane.norm();
  if (!(x_norm > kSquareTolerance))
    throw ValueError(std::string("The ") + x_what + " is normal to the workplane: it gives no direction in the plane");
  in_plane = in_plane / x_norm;
  return Workplane::from_frame(CoordinateSystem(origin, in_plane, n.cross(in_plane)));
}

// A planar face: its outward normal, the x direction of its plane, its centre.
struct PlanarFace {
  Vec3 normal;
  Vec3 x_axis;
  Vec3 center;
};

PlanarFace planar_face(const Face& face, const char* what) {
  const TopoDS_Face& f = TopoDS::Face(face.wrapped());
  const BRepAdaptor_Surface surface(f, false);
  if (surface.GetType() != GeomAbs_Plane)
    throw ValueError(std::string(what) + " must be a planar face; a workplane lies on a plane");
  return occt_guard([&] {
    const gp_Pln plane = surface.Plane();
    gp_Dir normal = plane.Axis().Direction();
    if (f.Orientation() == TopAbs_REVERSED)
      normal.Reverse();
    return PlanarFace{kernel::from_dir(normal), kernel::from_dir(plane.XAxis().Direction()), kernel::center_of_mass(f)};
  });
}

// An edge's direction of travel at its start (its orientation counts).
Vec3 edge_start_direction(const Edge& edge) {
  return occt_guard([&] {
    const TopoDS_Edge& e = TopoDS::Edge(edge.wrapped());
    const BRepAdaptor_Curve curve(e);
    const bool reversed = e.Orientation() == TopAbs_REVERSED;
    gp_Pnt point;
    gp_Vec tangent;
    curve.D1(reversed ? curve.LastParameter() : curve.FirstParameter(), point, tangent);
    if (reversed)
      tangent.Reverse();
    return kernel::from_vec(tangent);
  });
}

// A line through `origin` along `direction`: a straight edge or the axis of a circular one.
struct Axis {
  Vec3 origin;
  Vec3 direction;
};

Axis edge_axis(const Edge& edge) {
  const TopoDS_Edge& e = TopoDS::Edge(edge.wrapped());
  const BRepAdaptor_Curve curve(e);
  const bool reversed = e.Orientation() == TopAbs_REVERSED;
  if (curve.GetType() == GeomAbs_Line) {
    return occt_guard([&] {
      const gp_Pnt start = curve.Value(reversed ? curve.LastParameter() : curve.FirstParameter());
      gp_Dir direction = curve.Line().Direction();
      if (reversed)
        direction.Reverse();
      return Axis{kernel::from_pnt(start), kernel::from_dir(direction)};
    });
  }
  if (curve.GetType() == GeomAbs_Circle) {
    return occt_guard([&] {
      const gp_Circ circle = curve.Circle();
      return Axis{kernel::from_pnt(circle.Location()), kernel::from_dir(circle.Axis().Direction())};
    });
  }
  throw ValueError("The axis must be a straight edge or a circular edge (its centre line)");
}

// `v` turned by `radians` about the unit axis `k` (right-handed).
Vec3 rotate_about(const Vec3& v, const Vec3& k, double radians) {
  const double c = std::cos(radians);
  const double s = std::sin(radians);
  return v * c + k.cross(v) * s + k * (k.dot(v) * (1.0 - c));
}

Vec3 point_of(const PointOrVertex& point, const char* label) {
  if (const auto* numbers = std::get_if<Scalar3>(&point))
    return place_point(*numbers, label);
  return std::get<Vertex>(point).coordinates();
}

// The wire a curve argument walks along.
TopoDS_Wire curve_wire(const EdgeOrWire& curve) {
  if (const auto* wire = std::get_if<Wire>(&curve))
    return TopoDS::Wire(wire->wrapped());
  return occt_guard([&] { return BRepBuilderAPI_MakeWire(TopoDS::Edge(std::get<Edge>(curve).wrapped())).Wire(); });
}

const Shape& curve_shape(const EdgeOrWire& curve) {
  if (const auto* wire = std::get_if<Wire>(&curve))
    return *wire;
  return std::get<Edge>(curve);
}

// Hands the operation to the recorder: the inputs as ordered input_refs (a replay rebuilds the frame from
// them), the frame made as `frame`, and the workplane takes the lineage of the node.
// Call it only when current_recorder() is set.
void record_workplane(const Workplane& workplane, OpRecord record) {
  Recorder* recorder = current_recorder();
  if (recorder == nullptr)
    return;
  record.params.set("frame", workplane.plane_value());
  if (!record.inputs.empty()) {
    std::vector<Shape> shapes;
    for (const OpInput& input : record.inputs)
      shapes.push_back(input.shape);
    if (std::optional<Value> refs = recorder->input_refs(shapes);
        refs && refs->is_array() && refs->as_array().size() == shapes.size())
      record.params.set("input_refs", std::move(*refs));
  }
  if (const auto lineage = recorder->record_value_op(record, {}))
    attach_value_lineage(workplane, *lineage, record.op);
}

std::vector<std::string> workplane_labels() {
  return {"datum", "workplane"};
}

// {"input": index}: a parameter given as the input at `index` of input_refs.
Value input_param(int index) {
  Value out = Value::object();
  out.set("input", static_cast<std::int64_t>(index));
  return out;
}

}  // namespace

Workplane make_workplane_rworkplane(const Scalar3& origin, const Scalar3& normal, const Scalar3& x_dir) {
  static constexpr const char* kOp = "make_workplane_rworkplane";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a workplane.",
      {"The origin, normal, or x direction is not a finite 3D vector.", "The normal is a zero vector."},
      {"Pass origin, normal, and x_dir as 3-element numeric tuples or expressions.",
       "Use a non-zero normal; an x_dir along the normal is replaced by a perpendicular."}};
  return guarded(kSpec, [&] {
    Workplane workplane(evaluate_point(origin, "origin"), evaluate_point(normal, "normal"),
                        evaluate_point(x_dir, "x_dir"));
    if (current_recorder() != nullptr)
      record_workplane(workplane, OpParams(kOp, workplane_labels())
                                      .point("origin", origin)
                                      .point("normal", normal)
                                      .point("x_dir", x_dir)
                                      .take());
    return workplane;
  });
}

Workplane make_workplane_from_face_rworkplane(const Face& face, const std::optional<Scalar3>& origin,
                                              const std::optional<Edge>& x_edge, const std::optional<Scalar3>& x_dir,
                                              const Scalar& offset, bool flip) {
  static constexpr const char* kOp = "make_workplane_from_face_rworkplane";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a workplane on the face.",
      {"The face is not planar.", "Both x_edge and x_dir were given.",
       "The x edge or x direction is normal to the face, so it gives no direction in the plane.",
       "The origin, x direction, or offset is not finite."},
      {"Pick a planar face (a cylinder or a B-spline face has no single plane).",
       "Give the x direction once: an edge of the face (x_edge) or a vector (x_dir).",
       "Use an edge that lies in the face or a direction along the face."}};
  return guarded(kSpec, [&] {
    if (x_edge && x_dir)
      throw ValueError("Give x_edge or x_dir, not both");
    const PlanarFace plane = planar_face(face, "face");
    const Vec3 normal = flip ? plane.normal * -1.0 : plane.normal;
    Vec3 at = plane.center;
    if (origin) {
      const Vec3 given = place_point(*origin, "origin");
      at = given - plane.normal * (given - plane.center).dot(plane.normal);
    }
    at = at + normal * evaluate_scalar(offset, "offset");
    Vec3 x = plane.x_axis;
    const char* x_what = "face's x direction";
    if (x_edge) {
      x = edge_start_direction(*x_edge);
      x_what = "x edge";
    } else if (x_dir) {
      x = place_vector(*x_dir, "x_dir");
      x_what = "x direction";
    }
    Workplane workplane = frame(at, normal, x, x_what);
    if (current_recorder() != nullptr) {
      OpParams params(kOp, workplane_labels());
      params.optional_point("origin", origin).optional_point("x_dir", x_dir).scalar("offset", offset);
      params.boolean("flip", flip).input(face, "face");
      if (x_edge)
        params.input(*x_edge, "x_edge");
      OpRecord record = params.take();
      record.params.set("x_edge", x_edge ? input_param(1) : Value());
      record_workplane(workplane, std::move(record));
    }
    return workplane;
  });
}

Workplane make_workplane_from_points_rworkplane(const PointOrVertex& a, const PointOrVertex& b,
                                                const PointOrVertex& c) {
  static constexpr const char* kOp = "make_workplane_from_points_rworkplane";
  static const ErrorSpec kSpec{kOp,
                               "Failed to create a workplane through three points.",
                               {"Two of the points coincide or the three points lie on one line.",
                                "A point is not a finite 3D point or a vertex."},
                               {"Pick three points that span a plane (not on one line).",
                                "Pass each point as a Vertex of the model or a 3-element tuple."}};
  return guarded(kSpec, [&] {
    const Vec3 pa = point_of(a, "a");
    const Vec3 pb = point_of(b, "b");
    const Vec3 pc = point_of(c, "c");
    const Vec3 x = pb - pa;
    const Vec3 normal = x.cross(pc - pa);
    const double scale = std::max({x.norm(), (pc - pa).norm(), 1.0});
    if (!(normal.norm() > kSquareTolerance * scale * scale))
      throw ValueError("The three points lie on one line (or two coincide): they do not span a plane");
    Workplane workplane = frame(pa, normal, x, "direction from a to b");
    if (current_recorder() != nullptr) {
      OpParams params(kOp, workplane_labels());
      std::vector<std::pair<const char*, Value>> by_input;
      int index = 0;
      for (const auto& [name, point] : {std::pair<const char*, const PointOrVertex*>{"a", &a}, {"b", &b}, {"c", &c}}) {
        if (const auto* numbers = std::get_if<Scalar3>(point)) {
          params.point(name, *numbers);
        } else {
          params.input(std::get<Vertex>(*point), name);
          by_input.emplace_back(name, input_param(index++));
        }
      }
      OpRecord record = params.take();
      for (auto& [name, value] : by_input)
        record.params.set(name, std::move(value));
      record_workplane(workplane, std::move(record));
    }
    return workplane;
  });
}

Workplane make_workplane_from_axis_rworkplane(const Edge& axis, const Scalar& angle, const std::optional<Face>& face) {
  static constexpr const char* kOp = "make_workplane_from_axis_rworkplane";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a workplane through the axis.",
      {"The edge is neither straight nor circular.", "The reference face is not planar.",
       "The reference face's normal is along the axis, so the axis does not lie in its plane."},
      {"Use a straight edge, or a circular edge for its centre line.",
       "Give a planar face that contains the axis direction (a face the edge bounds), or no face."}};
  return guarded(kSpec, [&] {
    const Axis line = edge_axis(axis);
    const Vec3 k = line.direction / line.direction.norm();
    Vec3 start_normal = orthonormal_plane_axes(k).x_axis;
    if (face) {
      const Vec3 n = planar_face(*face, "face").normal;
      start_normal = n - k * n.dot(k);
      if (!(start_normal.norm() > kSquareTolerance))
        throw ValueError("The face's normal is along the axis: the axis does not lie in the face's plane");
      start_normal = start_normal / start_normal.norm();
    }
    const double radians = evaluate_scalar(angle, "angle") * kPi / 180.0;
    Workplane workplane = frame(line.origin, rotate_about(start_normal, k, radians), k, "axis");
    if (current_recorder() != nullptr) {
      OpParams params(kOp, workplane_labels());
      params.scalar("angle", angle).input(axis, "axis");
      if (face)
        params.input(*face, "face");
      OpRecord record = params.take();
      record.params.set("face", face ? input_param(1) : Value());
      record_workplane(workplane, std::move(record));
    }
    return workplane;
  });
}

Workplane make_workplane_midplane_rworkplane(const Face& face_a, const Face& face_b) {
  static constexpr const char* kOp = "make_workplane_midplane_rworkplane";
  static const ErrorSpec kSpec{kOp,
                               "Failed to create the workplane halfway between two faces.",
                               {"A face is not planar.", "The two faces are not parallel."},
                               {"Pick two parallel planar faces (the two sides of a plate, a slot's walls)."}};
  return guarded(kSpec, [&] {
    const PlanarFace a = planar_face(face_a, "face_a");
    const PlanarFace b = planar_face(face_b, "face_b");
    if (a.normal.cross(b.normal).norm() > kParallelFaces)
      throw ValueError("The two faces are not parallel: a midplane needs parallel planar faces");
    const Vec3 on_b = a.center - b.normal * (a.center - b.center).dot(b.normal);
    Workplane workplane = frame((a.center + on_b) * 0.5, a.normal, a.x_axis, "face's x direction");
    if (current_recorder() != nullptr) {
      OpParams params(kOp, workplane_labels());
      params.input(face_a, "face_a").input(face_b, "face_b");
      record_workplane(workplane, params.take());
    }
    return workplane;
  });
}

Workplane make_workplane_normal_to_curve_rworkplane(const EdgeOrWire& curve, const Scalar& at,
                                                    const std::optional<Scalar3>& x_dir) {
  static constexpr const char* kOp = "make_workplane_normal_to_curve_rworkplane";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to create a workplane normal to the curve.",
      {"`at` is outside [0, 1].", "The curve has no length.", "The x direction is along the curve's tangent there."},
      {"Pass at as a fraction of the curve's length: 0 = start, 1 = end.",
       "Use an x_dir that is not along the curve at that point."}};
  return guarded(kSpec, [&] {
    const double fraction = evaluate_scalar(at, "at");
    if (fraction < 0.0 || fraction > 1.0)
      throw ValueError("at must be a fraction of the curve's length in [0, 1]");
    const TopoDS_Wire wire = curve_wire(curve);
    const auto [point, tangent] = occt_guard([&] {
      const BRepAdaptor_CompCurve adaptor(wire);
      const double first = adaptor.FirstParameter();
      const double last = adaptor.LastParameter();
      double parameter = first;
      if (fraction >= 1.0) {
        parameter = last;
      } else if (fraction > 0.0) {
        const double length = GCPnts_AbscissaPoint::Length(adaptor);
        if (!(length > 0.0))
          throw ValueError("The curve has no length");
        const GCPnts_AbscissaPoint abscissa(adaptor, fraction * length, first);
        if (!abscissa.IsDone())
          throw ValueError("Could not find the point at that fraction of the curve's length");
        parameter = abscissa.Parameter();
      }
      gp_Pnt p;
      gp_Vec d;
      adaptor.D1(parameter, p, d);
      return std::pair<Vec3, Vec3>{kernel::from_pnt(p), kernel::from_vec(d)};
    });
    if (!(tangent.norm() > kSquareTolerance))
      throw ValueError("The curve has no direction at that point");
    const Vec3 x = x_dir ? place_vector(*x_dir, "x_dir") : orthonormal_plane_axes(tangent).x_axis;
    Workplane workplane = frame(point, tangent, x, "x direction");
    if (current_recorder() != nullptr) {
      OpParams params(kOp, workplane_labels());
      params.scalar("at", at).optional_point("x_dir", x_dir).input(curve_shape(curve), "curve");
      record_workplane(workplane, params.take());
    }
    return workplane;
  });
}

Workplane make_workplane_offset_rworkplane(const Workplane& base, const Scalar3& offset, const Scalar& rx,
                                           const Scalar& ry, const Scalar& rz,
                                           const std::optional<std::string>& base_plane) {
  static constexpr const char* kOp = "make_workplane_offset_rworkplane";
  static const ErrorSpec kSpec{
      kOp,
      "Failed to place a workplane relative to its base.",
      {"The offset or an angle is not a finite number."},
      {"Pass offset as (dx, dy, dz) along the base's x, y and normal, and the angles in degrees."}};
  return guarded(kSpec, [&] {
    const CoordinateSystem& frame_in = base.cs();
    const Vec3 bx = frame_in.x_axis();
    const Vec3 by = frame_in.y_axis();
    const Vec3 bz = frame_in.z_axis();
    const Vec3 d = evaluate_point(offset, "offset");
    const Vec3 origin = frame_in.origin() + bx * d.x + by * d.y + bz * d.z;
    // intrinsic turns about the base's axes: x first, then the y it left, then the z
    Vec3 x = bx, y = by, z = bz;
    const auto turn = [&](const Vec3& about, double degrees) {
      const double radians = degrees * kPi / 180.0;
      const Vec3 k = about / about.norm();
      x = rotate_about(x, k, radians);
      y = rotate_about(y, k, radians);
      z = rotate_about(z, k, radians);
    };
    turn(x, evaluate_scalar(rx, "rx"));
    turn(y, evaluate_scalar(ry, "ry"));
    turn(z, evaluate_scalar(rz, "rz"));
    Workplane workplane = frame(origin, z, x, "x direction");
    if (Recorder* recorder = current_recorder()) {
      OpParams params(kOp, workplane_labels());
      params.point("offset", offset).scalar("rx", rx).scalar("ry", ry).scalar("rz", rz);
      OpRecord record = params.take();
      record.params.set("base_plane", base_plane ? Value(*base_plane) : Value());
      record.params.set("base", base.plane_value());
      record.params.set("frame", workplane.plane_value());
      std::vector<ValueLineage> inputs;
      if (!base_plane) {
        if (auto lineage = value_lineage_of(base))
          inputs.push_back(std::move(*lineage));
      }
      if (const auto lineage = recorder->record_value_op(record, inputs))
        attach_value_lineage(workplane, *lineage, record.op);
    }
    return workplane;
  });
}

}  // namespace scad
