#include "probes.hpp"

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepClass3d_SolidClassifier.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepLProp_SLProps.hxx>
#include <BRep_Tool.hxx>
#include <GeomAbs_CurveType.hxx>
#include <ShapeAnalysis_Surface.hxx>
#include <Standard_Failure.hxx>
#include <TopAbs_Orientation.hxx>
#include <TopExp.hxx>
#include <TopoDS.hxx>
#include <gp_Pnt2d.hxx>

#include <algorithm>
#include <array>
#include <cmath>

#include "scad/core/tolerance.hpp"
#include "scad/kernel/convert.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/ops/features/support.hpp"

// Every probe is best effort: it reports "unknown" for any failure, so a diagnosis never
// replaces the error it was asked to explain.
namespace scad::features_detail {

namespace {

constexpr double kDegrees = 180.0 / kPi;

Vec3 vec_of(const gp_Pnt& p) {
  return {p.X(), p.Y(), p.Z()};
}

gp_Pnt midpoint_of(const TopoDS_Edge& edge) {
  const BRepAdaptor_Curve curve(edge);
  return curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2.0);
}

// The normal of `face` at the point nearest `near`, flipped to point out of the solid.
std::optional<Vec3> outward_normal_at(const TopoDS_Face& face, const gp_Pnt& target) {
  ShapeAnalysis_Surface projector(BRep_Tool::Surface(face));
  const gp_Pnt2d uv = projector.ValueOfUV(target, 1e-6);
  BRepLProp_SLProps props(BRepAdaptor_Surface(face), uv.X(), uv.Y(), 1, 1e-6);
  if (!props.IsNormalDefined())
    return std::nullopt;
  const gp_Dir normal = props.Normal();
  const Vec3 out{normal.X(), normal.Y(), normal.Z()};
  return face.Orientation() == TopAbs_REVERSED ? -out : out;
}

bool inside(const TopoDS_Solid& solid, const gp_Pnt& point) {
  BRepClass3d_SolidClassifier classifier(solid);
  classifier.Perform(point, 1e-7);
  return classifier.State() == TopAbs_IN;
}

gp_Pnt offset_point(const gp_Pnt& from, const Vec3& direction, double length) {
  return gp_Pnt(from.X() + length * direction.x, from.Y() + length * direction.y, from.Z() + length * direction.z);
}

// One end of an edge's parametrisation and the unit tangent leading into the edge from there.
struct EdgeEnd {
  gp_Pnt point;
  std::optional<Vec3> inward;
};

EdgeEnd edge_end(const BRepAdaptor_Curve& curve, bool at_start) {
  const double first = curve.FirstParameter(), last = curve.LastParameter();
  const double parameter = at_start ? first : last;
  EdgeEnd end{curve.Value(parameter), std::nullopt};
  const double step = std::max(1e-6, (last - first) * 1e-4);
  const double toward = at_start ? std::min(parameter + step, last) : std::max(parameter - step, first);
  if (toward == parameter)
    return end;
  const Vec3 along = vec_of(curve.Value(toward)) - vec_of(end.point);
  if (along.norm() >= tol::kDegenerateNorm)
    end.inward = along.normalized();
  return end;
}

}  // namespace

std::string vector_display(const Vec3& v) {
  return "(" + general_format(v.x, 4) + ", " + general_format(v.y, 4) + ", " + general_format(v.z, 4) + ")";
}

std::optional<ClosestApproach> closest_approach(const TopoDS_Shape& a, const TopoDS_Shape& b) {
  try {
    BRepExtrema_DistShapeShape tool;
    tool.LoadS1(a);
    tool.LoadS2(b);
    tool.Perform();
    if (!tool.IsDone() || tool.NbSolution() < 1)
      return std::nullopt;
    return ClosestApproach{tool.Value(), vec_of(tool.PointOnShape1(1)), vec_of(tool.PointOnShape2(1))};
  } catch (const std::exception&) {
    return std::nullopt;
  } catch (const Standard_Failure&) {
    return std::nullopt;
  }
}

std::optional<std::pair<Vec3, Vec3>> edge_endpoints(const TopoDS_Shape& edge) {
  try {
    std::vector<Vec3> points;
    for (const TopoDS_Shape& vertex : kernel::explore(edge, TopAbs_VERTEX)) {
      points.push_back(kernel::vertex_point(TopoDS::Vertex(vertex)));
      if (points.size() == 2)
        break;
    }
    if (points.size() != 2)
      return std::nullopt;
    return std::make_pair(points[0], points[1]);
  } catch (const std::exception&) {
    return std::nullopt;
  } catch (const Standard_Failure&) {
    return std::nullopt;
  }
}

std::vector<Vec3> sample_edge_polyline(const TopoDS_Edge& edge, int samples) {
  try {
    const BRepAdaptor_Curve curve(edge);
    const double first = curve.FirstParameter(), last = curve.LastParameter();
    const int count = curve.GetType() == GeomAbs_Line ? 2 : std::max(samples, 3);
    std::vector<Vec3> points;
    points.reserve(static_cast<std::size_t>(count));
    for (int i = 0; i < count; ++i)
      points.push_back(vec_of(curve.Value(first + (last - first) * i / (count - 1))));
    return points;
  } catch (const std::exception&) {
    return {};
  } catch (const Standard_Failure&) {
    return {};
  }
}

EdgeFaceAdjacency::EdgeFaceAdjacency(const TopoDS_Shape& solid) {
  TopExp::MapShapesAndAncestors(solid, TopAbs_EDGE, TopAbs_FACE, map_);
  faces_.resize(static_cast<std::size_t>(map_.Extent()));
  for (int i = 1; i <= map_.Extent(); ++i) {
    for (const TopoDS_Shape& face : map_.FindFromIndex(i))
      faces_[static_cast<std::size_t>(i - 1)].push_back(TopoDS::Face(face));
  }
}

const std::vector<TopoDS_Face>* EdgeFaceAdjacency::faces_of(const TopoDS_Shape& edge) const {
  const int index = map_.FindIndex(edge);
  return index == 0 ? nullptr : &faces_[static_cast<std::size_t>(index - 1)];
}

std::optional<double> face_extent_from_edge(const TopoDS_Shape& face, const TopoDS_Shape& edge) {
  try {
    const std::vector<TopoDS_Shape> edge_vertices = kernel::explore(edge, TopAbs_VERTEX);
    const auto touches_edge = [&](const TopoDS_Shape& other) {
      for (const TopoDS_Shape& vertex : kernel::explore(other, TopAbs_VERTEX)) {
        for (const TopoDS_Shape& mine : edge_vertices) {
          if (mine.IsSame(vertex))
            return true;
        }
      }
      return false;
    };
    std::optional<double> best;
    for (const TopoDS_Shape& other : kernel::explore(face, TopAbs_EDGE)) {
      if (other.IsSame(edge) || touches_edge(other))
        continue;  // connected to the culprit: not an obstacle
      const std::optional<ClosestApproach> gap = closest_approach(edge, other);
      if (gap && (!best || gap->gap < *best))
        best = gap->gap;
    }
    return best;
  } catch (const std::exception&) {
    return std::nullopt;
  } catch (const Standard_Failure&) {
    return std::nullopt;
  }
}

std::optional<double> dihedral_angle_along_edge(const TopoDS_Face& a, const TopoDS_Face& b, const TopoDS_Edge& edge) {
  try {
    const gp_Pnt middle = midpoint_of(edge);
    const std::optional<Vec3> na = outward_normal_at(a, middle), nb = outward_normal_at(b, middle);
    if (!na || !nb)
      return std::nullopt;
    const double dot = std::clamp(na->dot(*nb), -1.0, 1.0);
    return 180.0 - std::acos(dot) * kDegrees;
  } catch (const std::exception&) {
    return std::nullopt;
  } catch (const Standard_Failure&) {
    return std::nullopt;
  }
}

std::optional<bool> edge_is_concave(const TopoDS_Solid& solid, const TopoDS_Face& a, const TopoDS_Face& b,
                                    const TopoDS_Edge& edge) {
  try {
    const gp_Pnt middle = midpoint_of(edge);
    const std::optional<Vec3> na = outward_normal_at(a, middle), nb = outward_normal_at(b, middle);
    if (!na || !nb)
      return std::nullopt;
    const Vec3 bisector = *na + *nb;
    const double length = bisector.norm();
    if (length < tol::kNegligibleLength)
      return std::nullopt;
    return inside(solid, offset_point(middle, bisector, 1e-3 / length));
  } catch (const std::exception&) {
    return std::nullopt;
  } catch (const Standard_Failure&) {
    return std::nullopt;
  }
}

std::optional<bool> edge_is_concave_side_probe(const TopoDS_Solid& solid, const TopoDS_Face& a, const TopoDS_Face& b,
                                               const TopoDS_Edge& edge) {
  try {
    const gp_Pnt middle = midpoint_of(edge);
    const std::optional<Vec3> normal_a = outward_normal_at(a, middle);
    const std::optional<Vec3> normal_b = outward_normal_at(b, middle);
    if (!normal_a || !normal_b)
      return std::nullopt;
    const std::array<Vec3, 2> normals{*normal_a, *normal_b};
    for (const auto& [first, second] : {std::pair{0, 1}, std::pair{1, 0}}) {
      const Vec3 delta = normals[static_cast<std::size_t>(first)] - normals[static_cast<std::size_t>(second)];
      const double length = delta.norm();
      // Equal normals: tangent faces, left to the tangent-adjacency probe.
      if (length < tol::kNegligibleLength)
        continue;
      if (inside(solid, offset_point(middle, delta, 1e-3 / length)))
        return true;
    }
    return false;
  } catch (const std::exception&) {
    return std::nullopt;
  } catch (const Standard_Failure&) {
    return std::nullopt;
  }
}

bool edges_tangent_at_shared_vertex(const TopoDS_Edge& a, const TopoDS_Edge& b) {
  try {
    const BRepAdaptor_Curve curve_a(a), curve_b(b);
    // The shared vertex is the closest pair of ends.
    struct Pairing {
      bool a_at_start, b_at_start;
    };
    constexpr std::array<Pairing, 4> candidates{{{true, false}, {false, true}, {true, true}, {false, false}}};
    const Pairing* closest = nullptr;
    double closest_distance = 0.0;
    for (const Pairing& pairing : candidates) {
      const double distance =
          edge_end(curve_a, pairing.a_at_start).point.Distance(edge_end(curve_b, pairing.b_at_start).point);
      if (closest == nullptr || distance < closest_distance) {
        closest = &pairing;
        closest_distance = distance;
      }
    }
    if (closest_distance > 1e-6)
      return false;  // the edges do not actually share a vertex
    const EdgeEnd end_a = edge_end(curve_a, closest->a_at_start), end_b = edge_end(curve_b, closest->b_at_start);
    if (!end_a.inward || !end_b.inward)
      return false;
    const double dot = std::clamp(end_a.inward->dot(*end_b.inward), -1.0, 1.0);
    const double angle = std::acos(dot) * kDegrees;
    // Aligned or anti-aligned (a reversed chain): one smooth curve through the shared vertex.
    return angle <= 1.0 || angle >= 179.0;
  } catch (const std::exception&) {
    return false;
  } catch (const Standard_Failure&) {
    return false;
  }
}

}  // namespace scad::features_detail
