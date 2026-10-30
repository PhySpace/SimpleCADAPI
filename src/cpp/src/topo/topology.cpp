// Typed handles: construction checks and lazy topology enumeration.
//
// Orderings follow the Python SDK (core.py), because users pick sub-shapes by
// index: faces in TopExp_Explorer order, a face's outer wire before its inner
// wires, a solid's unique edges in face order.
#include <BRepAdaptor_Surface.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <ShapeAnalysis_FreeBounds.hxx>
#include <TopExp.hxx>
#include <TopTools_ListIteratorOfListOfShape.hxx>
#include <TopoDS.hxx>

#include <algorithm>
#include <cmath>
#include <unordered_set>

#include "internal.hpp"
#include "scad/core/error.hpp"
#include "scad/kernel/properties.hpp"
#include "scad/kernel/topology.hpp"

namespace scad {

namespace {

Shape require_kind(const Shape& shape, Kind expected) {
  if (shape.kind() != expected) {
    throw TypeError(std::string("expected a ") + std::string(kind_name(expected)) + ", got a " +
                    std::string(kind_name(shape.kind())));
  }
  return shape;
}

// First enumeration of a wire inside a face / edge inside a wire applies the
// tags Python applies at construction time.
void tag_if_absent(Shape& shape, std::string_view tag) {
  if (!shape.has_stored_tag(tag))
    shape.apply_tag(tag, false);
}

// geo[key] = index.  The common case (no geo yet) is written packed: nobody reads it on the
// hot path, and it expands in place when the metadata is read.
void set_index(Shape& shape, std::string_view key, int index) {
  if (!shape.has_metadata_key("geo")) {
    shape.set_metadata_deferred("geo", Value(Value::Object{{std::string(key), Value(index)}}));
    return;
  }
  Value geo = shape.get_metadata("geo", Value::object());
  if (!geo.is_object())
    geo = Value::object();
  geo.set(std::string(key), index);
  shape.set_metadata("geo", std::move(geo));
}

template <class T>
std::vector<T> unique_by_id(const std::vector<T>& items) {
  std::vector<T> out;
  out.reserve(items.size());
  std::unordered_set<const Entity*> seen;
  seen.reserve(items.size());
  for (const T& item : items)
    if (seen.insert(&SemanticAccess::entity(item)).second)
      out.push_back(item);
  return out;
}

}  // namespace

Vertex::Vertex(const Shape& shape) : Shape(require_kind(shape, kKind)) {}
Edge::Edge(const Shape& shape) : Shape(require_kind(shape, kKind)) {}
Wire::Wire(const Shape& shape) : Shape(require_kind(shape, kKind)) {}
Face::Face(const Shape& shape) : Shape(require_kind(shape, kKind)) {}
Shell::Shell(const Shape& shape) : Shape(require_kind(shape, kKind)) {}
Solid::Solid(const Shape& shape) : Shape(require_kind(shape, kKind)) {}
Compound::Compound(const Shape& shape) : Shape(require_kind(shape, kKind)) {}

// ---- Vertex ---------------------------------------------------------------
Vec3 Vertex::coordinates() const {
  return kernel::vertex_point(TopoDS::Vertex(wrapped()));
}

std::vector<Edge> Vertex::incident_edges() const {
  std::vector<Edge> out;
  const auto& map = registry().ancestors(Kind::Vertex, Kind::Edge);
  const int index = map.FindIndex(wrapped());
  if (index == 0)
    return out;
  for (TopTools_ListIteratorOfListOfShape it(map.FindFromIndex(index)); it.More(); it.Next())
    out.emplace_back(ancestor(it.Value(), Kind::Edge));
  return out;
}

// ---- Edge -----------------------------------------------------------------
double Edge::length() const {
  return kernel::linear_length(wrapped());
}

std::vector<Vertex> Edge::vertices() const {
  std::vector<Vertex> out;
  for (const auto& v : kernel::vertices_of(wrapped()))
    out.emplace_back(child(v, Kind::Vertex));
  return out;
}

Vertex Edge::start_vertex() const {
  auto v = vertices();
  if (v.empty())
    throw ValueError("failed to get the start vertex: the edge has no vertices");
  return v.front();
}

Vertex Edge::end_vertex() const {
  auto v = vertices();
  if (v.size() < 2)
    throw ValueError("failed to get the end vertex: the edge has fewer than two vertices");
  return v.back();
}

std::vector<Face> Edge::incident_faces() const {
  std::vector<Face> out;
  const auto& map = registry().ancestors(Kind::Edge, Kind::Face);
  const int index = map.FindIndex(wrapped());
  if (index == 0)
    return out;
  for (TopTools_ListIteratorOfListOfShape it(map.FindFromIndex(index)); it.More(); it.Next())
    out.emplace_back(ancestor(it.Value(), Kind::Face));
  return out;
}

// ---- Wire -----------------------------------------------------------------
std::vector<Edge> Wire::edges() const {
  std::vector<Edge> out;
  int i = 0;
  for (const auto& e : kernel::edges_of(wrapped())) {
    Edge edge(child(e, Kind::Edge));
    if (!edge.has_stored_tag("edge.boundary")) {
      edge.apply_tag("edge.boundary", false);
      set_index(edge, "edge_index", i);
    }
    out.push_back(std::move(edge));
    ++i;
  }
  return out;
}

bool Wire::is_closed() const {
  Entity& e = entity();
  if (e.closed < 0)
    e.closed = kernel::is_wire_closed(TopoDS::Wire(wrapped())) ? 1 : 0;
  return e.closed == 1;
}

// ---- Face -----------------------------------------------------------------
double Face::area() const {
  return kernel::surface_area(wrapped());
}

Vec3 Face::normal_at(double u, double v) const {
  return kernel::face_normal_at(TopoDS::Face(wrapped()), u, v);
}

namespace {

// The wires of a face in explorer order and the position of the outer one (cached on the entity).
struct FaceWires {
  std::vector<TopoDS_Wire> all;
  int outer = -1;
};

}  // namespace

static FaceWires wires_of_face(const Shape& shape, Entity& entity) {
  const TopoDS_Face face = TopoDS::Face(shape.wrapped());
  FaceWires out;
  out.all = kernel::wires_of(face);
  if (entity.outer_index == -2) {
    const TopoDS_Wire outer = kernel::outer_wire_of(face);
    entity.outer_index = -1;
    if (!outer.IsNull())
      for (std::size_t i = 0; i < out.all.size(); ++i)
        if (out.all[i].IsSame(outer)) {
          entity.outer_index = static_cast<std::int16_t>(i);
          break;
        }
  }
  out.outer = entity.outer_index;
  return out;
}

Wire Face::outer_wire() const {
  const FaceWires found = wires_of_face(*this, entity());
  if (found.outer < 0)
    throw ValueError("failed to get the outer wire: the face has none");
  Wire wire(child(found.all[static_cast<std::size_t>(found.outer)], Kind::Wire));
  if (!wire.is_closed())
    throw ValueError("failed to get the outer wire: the face's outer wire is not closed");
  tag_if_absent(wire, "wire.outer");
  return wire;
}

std::vector<Wire> Face::inner_wires() const {
  const FaceWires found = wires_of_face(*this, entity());
  std::vector<Wire> out;
  int i = 0;
  for (std::size_t k = 0; k < found.all.size(); ++k) {
    if (static_cast<int>(k) == found.outer)
      continue;
    Wire wire(child(found.all[k], Kind::Wire));
    if (!wire.is_closed())
      continue;
    if (!wire.has_stored_tag("wire.inner")) {
      wire.apply_tag("wire.inner", false);
      set_index(wire, "inner_wire_index", i);
    }
    out.push_back(std::move(wire));
    ++i;
  }
  return out;
}

std::vector<Wire> Face::wires() const {
  std::vector<Wire> out;
  out.push_back(outer_wire());
  for (auto& w : inner_wires())
    out.push_back(std::move(w));
  return out;
}

std::vector<Edge> Face::edges() const {
  std::vector<Edge> out;
  for (const Wire& wire : wires())
    for (Edge& edge : wire.edges())
      out.push_back(std::move(edge));
  return out;
}

std::vector<Face> Face::adjacent_faces() const {
  std::vector<Face> out;
  std::unordered_set<std::string> seen;
  for (const Edge& edge : edges()) {
    for (Face& face : edge.incident_faces()) {
      if (face.topo_id() == topo_id())
        continue;
      if (seen.insert(face.topo_id()).second)
        out.push_back(std::move(face));
    }
  }
  return out;
}

// ---- Shell ----------------------------------------------------------------
double Shell::area() const {
  return kernel::surface_area(wrapped());
}
bool Shell::is_closed() const {
  return kernel::shell_is_closed(wrapped());
}

std::vector<Face> Shell::faces() const {
  std::vector<Face> out;
  for (const auto& f : kernel::faces_of(wrapped()))
    out.emplace_back(child(f, Kind::Face));
  return out;
}

std::vector<Wire> Shell::wires() const {
  Entity& shell = entity();
  if (shell.free_wires == nullptr) {
    const ShapeAnalysis_FreeBounds analysis(wrapped(), 1e-7, false, true);
    std::vector<TopoDS_Wire> found;
    for (const TopoDS_Shape& group : {analysis.GetClosedWires(), analysis.GetOpenWires()})
      for (const auto& w : kernel::wires_of(group)) {
        bool dup = false;
        for (const auto& existing : found)
          dup = dup || w.IsSame(existing);
        if (!dup)
          found.push_back(w);
      }
    shell.free_wires = std::make_unique<std::vector<TopoDS_Wire>>(std::move(found));
  }
  std::vector<Wire> out;
  for (const auto& w : *shell.free_wires)
    out.emplace_back(child(w, Kind::Wire));
  return out;
}

std::vector<Edge> Shell::edges() const {
  std::vector<Edge> all;
  for (const Face& face : faces())
    for (Edge& edge : face.edges())
      all.push_back(std::move(edge));
  return unique_by_id(all);
}

// ---- Solid ----------------------------------------------------------------
double Solid::volume() const {
  return kernel::volume(wrapped());
}

std::vector<Face> Solid::faces() const {
  std::vector<Face> out;
  for (const auto& f : kernel::faces_of(wrapped()))
    out.emplace_back(child(f, Kind::Face));
  return out;
}

std::vector<Edge> Solid::edge_occurrences() const {
  std::vector<Edge> out;
  for (const Face& face : faces())
    for (Edge& edge : face.edges())
      out.push_back(std::move(edge));
  return out;
}

std::vector<Edge> Solid::edges() const {
  return unique_by_id(edge_occurrences());
}

void Solid::auto_tag_faces(std::string_view geometry_type) {
  auto tag_face = [](Face& face, const std::string& tag) {
    face.apply_tag("face." + tag, false);
    // Face::wires() tags each wire (wire.outer / wire.inner) and edge (edge.boundary).
    (void)face.wires();
  };
  auto faces = this->faces();
  if (geometry_type == "box" && faces.size() == 6) {
    for (std::size_t i = 0; i < faces.size(); ++i) {
      const Vec3 n = faces[i].normal_at();
      std::string tag;
      if (std::abs(n.z) > 0.9)
        tag = n.z > 0 ? "top" : "bottom";
      else if (std::abs(n.y) > 0.9)
        tag = n.y > 0 ? "front" : "back";
      else if (std::abs(n.x) > 0.9)
        tag = n.x > 0 ? "right" : "left";
      else
        tag = "face_" + std::to_string(i);
      tag_face(faces[i], tag);
    }
  } else if (geometry_type == "cylinder" && faces.size() == 3) {
    std::vector<Face> planes, sides;
    for (const Face& f : faces) {
      (BRepAdaptor_Surface(TopoDS::Face(f.wrapped())).GetType() == GeomAbs_Plane ? planes : sides).push_back(f);
    }
    if (planes.size() != 2)
      return;  // Python warns and leaves the faces untagged
    const Vec3 c0 = planes[0].center(), c1 = planes[1].center();
    const double spans[3] = {std::abs(c1.x - c0.x), std::abs(c1.y - c0.y), std::abs(c1.z - c0.z)};
    const int axis = static_cast<int>(std::max_element(spans, spans + 3) - spans);
    auto coord = [axis](const Face& f) {
      const Vec3 c = f.center();
      return axis == 0 ? c.x : axis == 1 ? c.y : c.z;
    };
    if (coord(planes[1]) < coord(planes[0]))
      std::swap(planes[0], planes[1]);
    tag_face(planes[0], "bottom");
    tag_face(planes[1], "top");
    for (Face& f : sides)
      tag_face(f, "side");
  } else if (geometry_type == "sphere" && faces.size() == 1) {
    tag_face(faces[0], "surface");
  } else {
    for (std::size_t i = 0; i < faces.size(); ++i)
      tag_face(faces[i], "face_" + std::to_string(i));
  }
}

// ---- Compound -------------------------------------------------------------
std::vector<Solid> Compound::solids() const {
  std::vector<Solid> out;
  for (const auto& s : kernel::solids_of(wrapped()))
    out.emplace_back(child(s, Kind::Solid));
  return out;
}

std::vector<Face> Compound::faces() const {
  std::vector<Face> out;
  for (const Solid& solid : solids())
    for (Face& face : solid.faces())
      out.push_back(std::move(face));
  return out;
}

std::vector<Edge> Compound::edges() const {
  std::vector<Edge> all;
  for (const Face& face : faces())
    for (Edge& edge : face.edges())
      all.push_back(std::move(edge));
  return unique_by_id(all);
}

double Compound::volume() const {
  double total = 0.0;
  for (const Solid& solid : solids())
    total += solid.volume();
  return total;
}

}  // namespace scad
