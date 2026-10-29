#include "scad/reactive/geo_selection.hpp"

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <GeomAbs_CurveType.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <TopoDS.hxx>

#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>

#include <map>

#include "scad/core/error.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"
#include "scad/reactive/lineage.hpp"
#include "scad/reactive/session.hpp"

namespace scad::reactive {

namespace {

Value vec_list(const Vec3& v) {
  return Value(Value::Array{Value(v.x), Value(v.y), Value(v.z)});
}

Value bbox_payload(const Shape& shape) {
  const kernel::BoundingBox box = shape.bounding_box();
  Value out = Value::object();
  out.set("min", vec_list({box.xmin, box.ymin, box.zmin}));
  out.set("max", vec_list({box.xmax, box.ymax, box.zmax}));
  return out;
}

std::string curve_type(GeomAbs_CurveType type) {
  switch (type) {
    case GeomAbs_Line:
      return "LINE";
    case GeomAbs_Circle:
      return "CIRCLE";
    case GeomAbs_BSplineCurve:
      return "BSPLINE";
    case GeomAbs_BezierCurve:
      return "BEZIER";
    case GeomAbs_Ellipse:
      return "ELLIPSE";
    case GeomAbs_Hyperbola:
      return "HYPERBOLA";
    case GeomAbs_Parabola:
      return "PARABOLA";
    case GeomAbs_OffsetCurve:
      return "OFFSETCURVE";
    case GeomAbs_OtherCurve:
      return "OTHERCURVE";
  }
  return "OTHERCURVE";
}

std::string surface_type(GeomAbs_SurfaceType type) {
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
    case GeomAbs_BSplineSurface:
      return "BSPLINE";
    case GeomAbs_BezierSurface:
      return "BEZIER";
    case GeomAbs_SurfaceOfRevolution:
      return "SURFACEOFREVOLUTION";
    case GeomAbs_SurfaceOfExtrusion:
      return "SURFACEOFEXTRUSION";
    case GeomAbs_OffsetSurface:
      return "OFFSETSURFACE";
    case GeomAbs_OtherSurface:
      return "OTHERSURFACE";
  }
  return "OTHERSURFACE";
}

// The position of `edge` in the wire the SDK last built for it: its wrappers are made face by face
// (outer wire first, then the inner wires), each numbering the edges of its wire, and the last one
// to number a shared edge wins.  nullopt when `source` has no face or wire that holds it.
std::optional<std::int64_t> wrapper_edge_index(const Shape& source, const Shape& edge) {
  std::optional<std::int64_t> found;
  const auto scan_wire = [&](const TopoDS_Shape& wire) {
    std::int64_t i = 0;
    for (const TopoDS_Edge& candidate : kernel::edges_of(wire)) {
      if (candidate.IsSame(edge.wrapped()))
        found = i;
      ++i;
    }
  };
  if (source.kind() == Kind::Wire) {
    scan_wire(source.wrapped());
    return found;
  }
  TopTools_IndexedMapOfShape faces;
  TopExp::MapShapes(source.wrapped(), TopAbs_FACE, faces);
  for (int f = 1; f <= faces.Extent(); ++f) {
    const TopoDS_Face face = TopoDS::Face(faces(f));
    const TopoDS_Wire outer = kernel::outer_wire_of(face);
    if (!outer.IsNull())
      scan_wire(outer);
    for (const TopoDS_Wire& wire : kernel::inner_wires_of(face))
      scan_wire(wire);
  }
  return found;
}

}  // namespace

std::string shape_kind_token(const Shape& shape) {
  return std::string(kind_name(shape.kind()));
}

std::optional<std::string> shape_geom_type(const Shape& shape) {
  try {
    if (shape.kind() == Kind::Edge)
      return curve_type(BRepAdaptor_Curve(TopoDS::Edge(shape.wrapped())).GetType());
    if (shape.kind() == Kind::Face)
      return surface_type(BRepAdaptor_Surface(TopoDS::Face(shape.wrapped())).GetType());
  } catch (const std::exception&) {
  }
  return std::nullopt;
}

Value make_selector_hint(const Shape& shape) {
  Value hint = Value::object();
  hint.set("kind", shape_kind_token(shape));
  Value tags = Value::array();
  for (const std::string& tag : shape.list_tags())
    tags.push_back(tag);
  hint.set("tags", std::move(tags));
  switch (shape.kind()) {
    case Kind::Edge: {
      const Edge edge = shape.as<Edge>();
      hint.set("length", edge.length());
      try {
        const Vec3 start = edge.start_vertex().coordinates();
        const Vec3 end = edge.end_vertex().coordinates();
        hint.set("start", vec_list(start));
        hint.set("end", vec_list(end));
      } catch (const std::exception&) {
        hint.set("center", vec_list(shape.center()));
      }
      break;
    }
    case Kind::Face: {
      const Face face = shape.as<Face>();
      hint.set("area", face.area());
      hint.set("center", vec_list(face.center()));
      hint.set("normal", vec_list(face.normal_at()));
      break;
    }
    case Kind::Wire: {
      const Wire wire = shape.as<Wire>();
      hint.set("edge_count", static_cast<std::int64_t>(wire.edges().size()));
      hint.set("closed", wire.is_closed());
      break;
    }
    case Kind::Vertex:
      hint.set("coordinates", vec_list(shape.as<Vertex>().coordinates()));
      break;
    case Kind::Shell:
      hint.set("face_count", static_cast<std::int64_t>(shape.as<Shell>().faces().size()));
      hint.set("bbox", bbox_payload(shape));
      break;
    case Kind::Solid:
      hint.set("volume", shape.as<Solid>().volume());
      hint.set("bbox", bbox_payload(shape));
      break;
    case Kind::Compound:
      hint.set("volume", shape.as<Compound>().volume());
      hint.set("solid_count", static_cast<std::int64_t>(shape.as<Compound>().solids().size()));
      hint.set("bbox", bbox_payload(shape));
      break;
  }
  return hint;
}

namespace {

// A face loaded from a BREP region snapshot also names its snapshot and source face id.
void add_brep_region_ref(Value& selector, const Shape& shape) {
  if (shape.kind() == Kind::Face) {
    const Value provenance = shape.get_metadata("provenance");
    if (provenance.is_object()) {
      const Value* sha = provenance.find("artifact_sha256");
      const Value* face_id = provenance.find("source_face_id");
      if (sha != nullptr && sha->is_string() && face_id != nullptr && face_id->is_string()) {
        Value ref = Value::object();
        ref.set("artifact_sha256", *sha);
        ref.set("source_face_id", *face_id);
        selector.set("brep_region_ref", std::move(ref));
      }
    }
  }
}

// The kind-specific measurements that make up the exact selector (compared by geo_selector_score).
void add_kind_measurements(Value& selector, const Shape& shape) {
  switch (shape.kind()) {
    case Kind::Vertex:
      selector.set("coordinates", vec_list(shape.as<Vertex>().coordinates()));
      break;
    case Kind::Edge: {
      const Edge edge = shape.as<Edge>();
      selector.set("length", edge.length());
      selector.set("center", vec_list(edge.center()));
      try {
        const Vec3 start = edge.start_vertex().coordinates();
        const Vec3 end = edge.end_vertex().coordinates();
        selector.set("start", vec_list(start));
        selector.set("end", vec_list(end));
      } catch (const std::exception&) {
      }
      break;
    }
    case Kind::Wire: {
      const Wire wire = shape.as<Wire>();
      selector.set("edge_count", static_cast<std::int64_t>(wire.edges().size()));
      selector.set("closed", wire.is_closed());
      break;
    }
    case Kind::Face: {
      const Face face = shape.as<Face>();
      selector.set("area", face.area());
      selector.set("center", vec_list(face.center()));
      selector.set("normal", vec_list(face.normal_at()));
      selector.set("edge_count", static_cast<std::int64_t>(face.edges().size()));
      selector.set("inner_wire_count", static_cast<std::int64_t>(face.inner_wires().size()));
      break;
    }
    case Kind::Shell:
      selector.set("face_count", static_cast<std::int64_t>(shape.as<Shell>().faces().size()));
      break;
    case Kind::Solid: {
      const Solid solid = shape.as<Solid>();
      selector.set("volume", solid.volume());
      selector.set("center", vec_list(solid.center()));
      break;
    }
    case Kind::Compound: {
      const Compound compound = shape.as<Compound>();
      selector.set("volume", compound.volume());
      selector.set("solid_count", static_cast<std::int64_t>(compound.solids().size()));
      break;
    }
  }
}

}  // namespace

Value make_geo_exact_selector(const Shape& shape, const Shape* source) {
  Value selector = Value::object();
  selector.set("mode", "geo_exact");
  selector.set("kind", shape_kind_token(shape));
  Value geo = shape.get_metadata("geo", Value::object());
  if (geo.is_null())
    geo = Value::object();
  if (shape.kind() == Kind::Edge && source != nullptr) {
    if (const auto index = wrapper_edge_index(*source, shape))
      geo.set("edge_index", *index);
  }
  selector.set("metadata_geo", std::move(geo));
  add_brep_region_ref(selector, shape);
  try {
    selector.set("bbox", bbox_payload(shape));
  } catch (const std::exception&) {
  }
  if (const auto geom = shape_geom_type(shape))
    selector.set("geom_type", *geom);

  add_kind_measurements(selector, shape);
  return selector;
}

std::optional<Value> serialize_shape_ref(const Shape& shape) {
  std::optional<Value> ref;
  if (Session* session = Session::active_session())
    ref = session->topo_ref_value(shape);
  if (!ref) {
    const Value stored = shape.get_metadata("topo_ref");
    if (stored.is_object())
      ref = stored;
  }
  if (!ref)
    return std::nullopt;
  ref->set("selector_hint", make_selector_hint(shape));
  return ref;
}

Value serialize_shape_refs(const std::vector<Shape>& shapes) {
  Value refs = Value::array();
  for (const Shape& shape : shapes) {
    if (auto ref = serialize_shape_ref(shape))
      refs.push_back(std::move(*ref));
  }
  return refs;
}

std::optional<std::string> shape_ref_topo_id(const Shape& shape) {
  const auto ref = serialize_shape_ref(shape);
  if (!ref)
    return std::nullopt;
  const Value* id = ref->find("topo_id");
  if (id == nullptr || id->is_null())
    return std::nullopt;
  return id->is_string() ? id->as_string() : id->dump();
}

Value serialize_selection_indices(const std::vector<Shape>& selected, const std::vector<Shape>& candidates) {
  std::map<std::string, std::int64_t> index_by_topo_id;
  for (std::size_t i = 0; i < candidates.size(); ++i) {
    if (const auto id = shape_ref_topo_id(candidates[i]))
      index_by_topo_id.emplace(*id, static_cast<std::int64_t>(i));
  }
  Value out = Value::array();
  for (const Shape& shape : selected) {
    const auto id = shape_ref_topo_id(shape);
    if (!id)
      continue;
    if (const auto found = index_by_topo_id.find(*id); found != index_by_topo_id.end())
      out.push_back(found->second);
  }
  return out;
}

}  // namespace scad::reactive
