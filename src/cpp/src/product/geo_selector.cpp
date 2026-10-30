// The exact-geometry selector a connector stores for the sub-shape it is anchored to
// (simplecadapi/operators/_support.py `_make_geo_selector`).  Only its center / normal /
// start / end / coordinates are read back to build a frame; the rest identifies the
// shape for a later re-resolution.
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <GeomAbs_CurveType.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <TopoDS.hxx>

#include <optional>
#include <utility>

#include "scad/core/error.hpp"
#include "scad/product/connector.hpp"
#include "scad/product/validation.hpp"

namespace scad::product {

namespace {

Value bbox_value(const Shape& shape) {
  const kernel::BoundingBox box = shape.bounding_box();
  Value out = Value::object();
  out.set("min", to_array({box.xmin, box.ymin, box.zmin}));
  out.set("max", to_array({box.xmax, box.ymax, box.zmax}));
  return out;
}

std::string curve_type_name(GeomAbs_CurveType type) {
  switch (type) {
    case GeomAbs_Line:
      return "LINE";
    case GeomAbs_Circle:
      return "CIRCLE";
    case GeomAbs_Ellipse:
      return "ELLIPSE";
    case GeomAbs_Hyperbola:
      return "HYPERBOLA";
    case GeomAbs_Parabola:
      return "PARABOLA";
    case GeomAbs_BezierCurve:
      return "BEZIER";
    case GeomAbs_BSplineCurve:
      return "BSPLINE";
    case GeomAbs_OffsetCurve:
      return "OFFSETCURVE";
    default:
      return "OTHERCURVE";
  }
}

std::string surface_type_name(GeomAbs_SurfaceType type) {
  switch (type) {
    case GeomAbs_Plane:
      return "PLANE";
    case GeomAbs_Cylinder:
      return "CYLINDER";
    case GeomAbs_Cone:
      return "CONE";
    case GeomAbs_Sphere:
      return "SPHERE";
    case GeomAbs_Torus:
      return "TORUS";
    case GeomAbs_BezierSurface:
      return "BEZIER";
    case GeomAbs_BSplineSurface:
      return "BSPLINE";
    case GeomAbs_SurfaceOfRevolution:
      return "SURFACEOFREVOLUTION";
    case GeomAbs_SurfaceOfExtrusion:
      return "SURFACEOFEXTRUSION";
    case GeomAbs_OffsetSurface:
      return "OFFSETSURFACE";
    default:
      return "OTHERSURFACE";
  }
}

// Absent (a null Value) for kinds that have no geometric type.
Value geom_type(const Shape& shape) {
  try {
    if (shape.kind() == Kind::Edge)
      return curve_type_name(BRepAdaptor_Curve(TopoDS::Edge(shape.wrapped())).GetType());
    if (shape.kind() == Kind::Face)
      return surface_type_name(BRepAdaptor_Surface(TopoDS::Face(shape.wrapped())).GetType());
  } catch (const Standard_Failure&) {
    return {};
  }
  return {};
}

}  // namespace

std::string shape_kind_token(const Shape& shape) {
  return std::string(kind_name(shape.kind()));
}

Value make_geo_selector(const Shape& shape) {
  Value selector = Value::object();
  selector.set("mode", "geo_exact");
  selector.set("kind", shape_kind_token(shape));
  selector.set("metadata_geo", shape.get_metadata("geo", Value::object()));

  const Value provenance = shape.get_metadata("provenance");
  if (shape.kind() == Kind::Face && provenance.is_object()) {
    const Value* artifact = provenance.find("artifact_sha256");
    const Value* source_face = provenance.find("source_face_id");
    if (artifact != nullptr && artifact->is_string() && source_face != nullptr && source_face->is_string()) {
      Value ref = Value::object();
      ref.set("artifact_sha256", *artifact);
      ref.set("source_face_id", *source_face);
      selector.set("brep_region_ref", std::move(ref));
    }
  }

  selector.set("bbox", bbox_value(shape));
  if (const Value type = geom_type(shape); !type.is_null())
    selector.set("geom_type", type);

  switch (shape.kind()) {
    case Kind::Vertex:
      selector.set("coordinates", to_array(Vertex(shape).coordinates()));
      break;
    case Kind::Edge: {
      const Edge edge(shape);
      selector.set("length", edge.length());
      selector.set("center", to_array(shape.center()));
      std::optional<std::pair<Vec3, Vec3>> end_points;
      try {
        const Vec3 start = edge.start_vertex().coordinates();
        const Vec3 end = edge.end_vertex().coordinates();
        end_points = std::pair<Vec3, Vec3>(start, end);
      } catch (const Exception&) {
        // start_vertex/end_vertex throw ValueError for an edge without vertices: the selector then
        // keeps no end points (nothing reports it; the selector is still valid).
        end_points = std::nullopt;
      }
      if (end_points) {
        selector.set("start", to_array(end_points->first));
        selector.set("end", to_array(end_points->second));
      }
      break;
    }
    case Kind::Wire:
      selector.set("edge_count", static_cast<std::int64_t>(Wire(shape).edges().size()));
      selector.set("closed", Wire(shape).is_closed());
      break;
    case Kind::Face: {
      const Face face(shape);
      selector.set("area", face.area());
      selector.set("center", to_array(shape.center()));
      selector.set("normal", to_array(face.normal_at()));
      selector.set("edge_count", static_cast<std::int64_t>(face.edges().size()));
      selector.set("inner_wire_count", static_cast<std::int64_t>(face.inner_wires().size()));
      break;
    }
    case Kind::Shell:
      selector.set("face_count", static_cast<std::int64_t>(Shell(shape).faces().size()));
      break;
    case Kind::Solid:
      selector.set("volume", Solid(shape).volume());
      selector.set("center", to_array(shape.center()));
      break;
    case Kind::Compound:
      selector.set("volume", Compound(shape).volume());
      selector.set("solid_count", static_cast<std::int64_t>(Compound(shape).solids().size()));
      break;
  }
  return selector;
}

}  // namespace scad::product
