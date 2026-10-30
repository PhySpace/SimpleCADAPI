// Shape classes, with the method names of the Python SDK (core.py).
//
// Where the Python SDK forbids bare enumeration (get_faces() without an index
// raises, pointing at the QL selectors) this module does too; the plural
// accessors faces()/edges()/... exist as C++-port extensions so tests and
// native callers can enumerate until QL is ported.
#include "bindings.hpp"

#include <BRep_Builder.hxx>
#include <TopoDS_Compound.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>

#include "occt/occt.hpp"
#include "scad/core/error.hpp"
#include "scad/reactive/graph.hpp"
#include "scad/reactive/lineage.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/shape.hpp"

namespace occt = scad::pybind::occt;

namespace {

using namespace scad;

[[noreturn]] void enumeration_forbidden(const char* method, const char* kind) {
  ErrorGuidance g;
  g.what_happened = std::string(method) +
                    "() without an index no longer returns a list -- bare topology enumeration is not part of "
                    "the public API.";
  g.possible_causes = {"Calling a plural topology getter (get_edges/get_faces/...) with no argument.",
                       "Porting code that enumerated topology with Python loops or len()."};
  g.how_to_fix = {
      "Enumerate or measure via QL: ql.edges().resolve(shape) / len(ql.faces().resolve(shape)).",
      "Pick intentionally with the indexed form get_edges(index) -- indexed picks are recorded as graph "
      "selection nodes.",
      "Filter with QL predicates and cardinality (take/exactly) instead of post-filtering an enumerated list."};
  g.signature = std::string(method) + "(index: int) -> " + kind;
  g.technical_details =
      "Enumeration escapes the graph: selections made by indexing a bare list carry no predicate and capture "
      "kernel artifacts (e.g. periodic-face seams).";
  throw Error(std::string(method) + " (no index)", std::move(g));
}

// get_faces(i) and the like: the pick is recorded as a graph selection node when it is made
// (_record_indexed_topology_selection; a recorder that cannot take it is ignored).
template <class T>
T indexed(const Shape& source, const std::vector<T>& items, const py::object& index, const char* method,
          const char* kind) {
  if (index.is_none())
    enumeration_forbidden(method, kind);
  T picked = pick(items, index.cast<long>(), kind);
  if (Recorder* recorder = current_recorder()) {
    try {
      recorder->record_selection(source, {picked}, kind);
    } catch (const std::exception&) {
    }
  }
  return picked;
}

// Methods every shape kind shares (TaggedMixin + TopoMixein).
template <class T, class Cls>
void bind_common(Cls& cls) {
  cls.def_property_readonly("topo_id", [](const T& s) { return s.topo_id(); })
      .def("same_topology", [](const T& a, const Shape& b) { return a.same_entity(b) || a.topo_id() == b.topo_id(); })
      .def("_add_tag", [](T& s, const std::string& tag) { s.add_tag(tag); })
      .def(
          "_apply_tag", [](T& s, const std::string& tag, bool propagate) { s.apply_tag(tag, propagate); },
          py::arg("tag"), py::arg("propagate") = false)
      .def(
          "_has_tag",
          [](const T& s, const std::string& tag, const std::string& scope) {
            return s.has_tag(tag, normalize_tag_scope(scope));
          },
          py::arg("tag"), py::arg("scope") = "effective")
      .def(
          "_list_tags", [](const T& s, const std::string& scope) { return s.list_tags(normalize_tag_scope(scope)); },
          py::arg("scope") = "effective")
      .def(
          "_explain_tag",
          [](const T& s, const std::string& tag, const std::string& scope) {
            return s.explain_tag(normalize_tag(tag, true), normalize_tag_scope(scope));
          },
          py::arg("tag"), py::arg("scope") = "effective")
      .def("set_metadata", [](T& s, const std::string& key, const Value& v) { s.set_metadata(key, v); })
      .def(
          "get_metadata",
          [](const T& s, const std::string& key, const Value& dflt) {
            Value found = s.get_metadata(key, Value());
            // The SDK stamps "topo_ref" on every entity of a recorded output; here it is derived on demand.
            if (found.is_null() && key == "topo_ref") {
              if (auto ref = scad::reactive::topo_ref_of(s)) {
                ref->topo_id = std::string(kind_name(ref->kind)) + "_" + ref->topo_id;  // the SDK's text: "face_face_5"
                return scad::to_value(*ref);
              }
            }
            return found.is_null() ? dflt : found;
          },
          py::arg("key"), py::arg("default") = Value())
      .def_property_readonly(
          "wrapped", [](const T& s) { return occt::shape_to_python(s.wrapped()); },
          "The OCCT shape (TopoDS_Solid, ...) this handle stands for: the same OpenCASCADE, no copy.")
      .def(
          "_attach_node",
          [](const T& s, const std::shared_ptr<const scad::reactive::OperationNode>& node) { s.set_graph_node(node); },
          py::arg("node"),
          "The graph node this value was made by (a value restored from a pickle brings its node back).")
      .def("_set_runtime", [](T& s, const std::string& key, const Value& v) { s.set_runtime(key, v); })
      .def(
          "_get_runtime",
          [](const T& s, const std::string& key, const Value& dflt) -> py::object {
            if (key == "graph.node") {  // the node object itself, as the SDK keeps it in the runtime
              if (const auto node = s.graph_node())
                return py::cast(std::static_pointer_cast<const scad::reactive::OperationNode>(node));
            }
            return scad::pybind::value_to_python(s.get_runtime(key, dflt));
          },
          py::arg("key"), py::arg("default") = Value())
      .def("get_center", [](const T& s) { return scad::pybind::PyVec3{s.center()}; })
      .def(
          "__eq__",
          [](const T& a, const py::object& b) {
            return py::isinstance<Shape>(b) && a.same_entity(b.cast<const Shape&>());
          },
          py::is_operator())
      .def("__hash__", [](const T& s) { return s.entity_key(); })
      .def("__repr__", [](const T& s) { return s.repr(); })
      .def("__str__", [](const T& s) { return s.to_string(0); });
}

}  // namespace

void bind_topo(py::module_& m) {
  py::class_<Shape>(m, "AnyShape")
      .def_property_readonly("topo_id", &Shape::topo_id)
      // How many writes to semantic state the root of this shape has had: equal before and after means unchanged.
      .def("_semantic_revision", &Shape::semantic_revision);

  auto vertex = py::class_<Vertex, Shape>(m, "Vertex");
  vertex.def("get_coordinates", &Vertex::coordinates).def("get_incident_edges", &Vertex::incident_edges);
  bind_common<Vertex>(vertex);

  auto edge = py::class_<Edge, Shape>(m, "Edge");
  edge.def("get_length", &Edge::length)
      .def("get_start_vertex", &Edge::start_vertex)
      .def("get_end_vertex", &Edge::end_vertex)
      .def("get_incident_faces", &Edge::incident_faces)
      .def(
          "get_vertices",
          [](const Edge& e, const py::object& i) { return indexed(e, e.vertices(), i, "get_vertices", "vertex"); },
          py::arg("index") = py::none())
      .def("vertices", &Edge::vertices);
  bind_common<Edge>(edge);

  auto wire = py::class_<Wire, Shape>(m, "Wire");
  wire.def(
          "get_edges", [](const Wire& w, const py::object& i) { return indexed(w, w.edges(), i, "get_edges", "edge"); },
          py::arg("index") = py::none())
      .def("is_closed", &Wire::is_closed)
      .def("edges", &Wire::edges);
  bind_common<Wire>(wire);

  auto face = py::class_<Face, Shape>(m, "Face");
  face.def("get_area", &Face::area)
      .def(
          "get_normal_at", [](const Face& f, double u, double v) { return scad::pybind::PyVec3{f.normal_at(u, v)}; },
          py::arg("u") = 0.5, py::arg("v") = 0.5)
      .def("get_outer_wire", &Face::outer_wire)
      .def(
          "get_wires", [](const Face& f, const py::object& i) { return indexed(f, f.wires(), i, "get_wires", "wire"); },
          py::arg("index") = py::none())
      .def(
          "get_inner_wires",
          [](const Face& f, const py::object& i) { return indexed(f, f.inner_wires(), i, "get_inner_wires", "wire"); },
          py::arg("index") = py::none())
      .def(
          "get_edges", [](const Face& f, const py::object& i) { return indexed(f, f.edges(), i, "get_edges", "edge"); },
          py::arg("index") = py::none())
      .def("get_adjacent_faces", &Face::adjacent_faces)
      .def("wires", &Face::wires)
      .def("edges", &Face::edges);
  bind_common<Face>(face);

  auto shell = py::class_<Shell, Shape>(m, "Shell");
  shell.def("get_area", &Shell::area)
      .def("is_closed", &Shell::is_closed)
      .def(
          "get_faces",
          [](const Shell& s, const py::object& i) { return indexed(s, s.faces(), i, "get_faces", "face"); },
          py::arg("index") = py::none())
      .def(
          "get_wires",
          [](const Shell& s, const py::object& i) { return indexed(s, s.wires(), i, "get_wires", "wire"); },
          py::arg("index") = py::none())
      .def(
          "get_edges",
          [](const Shell& s, const py::object& i) { return indexed(s, s.edges(), i, "get_edges", "edge"); },
          py::arg("index") = py::none())
      .def("faces", &Shell::faces)
      .def("edges", &Shell::edges);
  bind_common<Shell>(shell);

  auto solid = py::class_<Solid, Shape>(m, "Solid");
  solid.def("get_volume", &Solid::volume)
      .def(
          "get_faces",
          [](const Solid& s, const py::object& i) { return indexed(s, s.faces(), i, "get_faces", "face"); },
          py::arg("index") = py::none())
      .def(
          "get_edges",
          [](const Solid& s, const py::object& i) { return indexed(s, s.edges(), i, "get_edges", "edge"); },
          py::arg("index") = py::none())
      .def(
          "get_edge_occurrences",
          [](const Solid& s, const py::object& i) {
            return indexed(s, s.edge_occurrences(), i, "get_edge_occurrences", "edge");
          },
          py::arg("index") = py::none())
      .def("auto_tag_faces", &Solid::auto_tag_faces, py::arg("geometry_type") = "unknown")
      .def("faces", &Solid::faces)
      .def("edges", &Solid::edges);
  bind_common<Solid>(solid);

  auto compound = py::class_<Compound, Shape>(m, "Compound");
  // A compound of shapes (duplicates and all): the shapes themselves are not copied.
  compound.def(py::init([](const py::sequence& shapes) {
                 BRep_Builder builder;
                 TopoDS_Compound made;
                 builder.MakeCompound(made);
                 for (const py::handle item : shapes)
                   builder.Add(made, item.cast<const Shape&>().wrapped());
                 return Compound(made);
               }),
               py::arg("shapes"));
  compound.def("get_volume", &Compound::volume)
      .def(
          "get_solids",
          [](const Compound& c, const py::object& i) { return indexed(c, c.solids(), i, "get_solids", "solid"); },
          py::arg("index") = py::none())
      .def(
          "get_faces",
          [](const Compound& c, const py::object& i) { return indexed(c, c.faces(), i, "get_faces", "face"); },
          py::arg("index") = py::none())
      .def(
          "get_edges",
          [](const Compound& c, const py::object& i) { return indexed(c, c.edges(), i, "get_edges", "edge"); },
          py::arg("index") = py::none())
      .def("solids", &Compound::solids)
      .def("faces", &Compound::faces)
      .def("edges", &Compound::edges);
  bind_common<Compound>(compound);

  // The Python SDK's private enumerators (`_iter_*`): its own tests and std parts use them.
  // The wrapper tree the SDK builds: vertex < edge < wire < face < solid | shell < compound.
  edge.def("get_children", [](const Edge& e) { return py::cast(e.vertices()); });
  wire.def("get_children", [](const Wire& w) { return py::cast(w.edges()); });
  face.def("get_children", [](const Face& f) { return py::cast(f.wires()); });
  shell.def("get_children", [](const Shell& s) {
    py::list out = py::cast(s.faces());
    for (const py::handle wire : py::cast(s.wires()))
      out.append(wire);  // its free boundaries
    return out;
  });
  solid.def("get_children", [](const Solid& s) { return py::cast(s.faces()); });
  compound.def("get_children", [](const Compound& c) { return py::cast(c.solids()); });
  vertex.def("get_children", [](const Vertex&) { return py::list(); });
  edge.def("_iter_vertices", &Edge::vertices);
  wire.def("_iter_edges", &Wire::edges);
  face.def("_iter_wires", &Face::wires).def("_iter_inner_wires", &Face::inner_wires).def("_iter_edges", &Face::edges);
  shell.def("_iter_faces", &Shell::faces).def("_iter_wires", &Shell::wires).def("_iter_edges", &Shell::edges);
  solid.def("_iter_faces", &Solid::faces)
      .def("_iter_edges", &Solid::edges)
      .def("_iter_edge_occurrences", &Solid::edge_occurrences);
  compound.def("_iter_solids", &Compound::solids)
      .def("_iter_faces", &Compound::faces)
      .def("_iter_edges", &Compound::edges);

  // Raw OCCT primitives for tests: operators are the real way to build shapes.
  auto testing = m.def_submodule("_testing", "helpers for the test suite");
  testing.def("box", [](double x, double y, double z) { return Solid(BRepPrimAPI_MakeBox(x, y, z).Solid()); });
  testing.def("cylinder", [](double r, double h) { return Solid(BRepPrimAPI_MakeCylinder(r, h).Solid()); });
}
