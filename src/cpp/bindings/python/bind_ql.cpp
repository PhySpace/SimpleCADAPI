// Python bindings for the "ql" area: the module `simplecadapi.ql`, here `simplecadapi._cpp.ql`.
//
// Same names, signatures and error messages as the Python SDK:
//
//     from simplecadapi._cpp import ql
//     ql.faces().where(ql.prop("geom.normal.z", ">", 0.9)).exactly(1).resolve(solid)
//
// The submodule is registered under both `simplecadapi._cpp._native.ql` and
// `simplecadapi._cpp.ql`, so `import simplecadapi._cpp.ql as Q` works.
#include "bindings.hpp"

#include <BRepAlgoAPI_Cut.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRep_Builder.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <gp_Ax2.hxx>

#include <algorithm>
#include <string_view>

#include "scad/core/error.hpp"
#include "scad/ql/ql.hpp"

namespace {

using namespace scad;
using scad::pybind::value_from_python;
using scad::pybind::value_to_python;

// ---- conversions ----------------------------------------------------------------------------------------------
py::object shape_to_py(const Shape& s) {
  switch (s.kind()) {
    case Kind::Vertex: return py::cast(Vertex(s));
    case Kind::Edge: return py::cast(Edge(s));
    case Kind::Wire: return py::cast(Wire(s));
    case Kind::Face: return py::cast(Face(s));
    case Kind::Shell: return py::cast(Shell(s));
    case Kind::Solid: return py::cast(Solid(s));
    case Kind::Compound: return py::cast(Compound(s));
  }
  return py::none();
}

py::list shapes_to_py(const std::vector<Shape>& shapes) {
  py::list out;
  for (const Shape& s : shapes) out.append(shape_to_py(s));
  return out;
}

bool is_text(const py::handle& h) { return py::isinstance<py::str>(h) || py::isinstance<py::bytes>(h); }

// A shape, or any iterable of shapes (ShapeSelector.resolve(scope)).
ql::Scope scope_from_py(const py::object& scope, const std::string& target_kind) {
  if (py::isinstance<Shape>(scope)) return ql::Scope(scope.cast<const Shape&>());
  if (!is_text(scope) && !py::isinstance<py::dict>(scope) && py::hasattr(scope, "__iter__")) {
    std::vector<Shape> items;
    for (const py::handle item : scope) {
      if (!py::isinstance<Shape>(item)) throw TypeError("QL selector scope items must be shapes");
      items.push_back(item.cast<const Shape&>());
    }
    return ql::Scope(std::move(items));
  }
  throw TypeError("cannot resolve QL selector scope for target_kind=" + target_kind);
}

py::object scope_to_py(const ql::Scope& scope) {
  return scope.is_list() ? py::object(shapes_to_py(scope.items())) : shape_to_py(scope.shape());
}

py::dict dict_of(const Value& v) { return py::cast<py::dict>(value_to_python(v)); }

std::string scope_name(const py::object& scope) {
  if (py::isinstance<py::str>(scope)) return scope.cast<std::string>();
  if (py::hasattr(scope, "value")) return py::str(scope.attr("value")).cast<std::string>();
  throw TypeError("scope must be a string or a TagScope");
}

std::string text_of(const py::object& v, const char* message) {
  if (!py::isinstance<py::str>(v)) throw ValueError(message);
  return v.cast<std::string>();
}

// A Python callable the C++ side keeps: it never touches the interpreter once the interpreter has gone.
class PyCallable {
 public:
  explicit PyCallable(py::object fn) : fn_(std::move(fn)) {}
  PyCallable(const PyCallable&) = delete;
  PyCallable& operator=(const PyCallable&) = delete;
  ~PyCallable() {
    if (Py_IsInitialized() == 0) {
      fn_.release();
    } else {
      const py::gil_scoped_acquire gil;
      fn_ = py::object();
    }
  }
  [[nodiscard]] const py::object& get() const { return fn_; }

 private:
  py::object fn_;
};

// The sentinel resolvers return for "not mine" (simplecadapi.ql.MISSING).
struct MissingType {};


// The resolvers registered from Python, in order, for objects that are not shapes: a custom resolver is how
// QL is extended to any Python object (resolver(target, path) -> value | MISSING).
struct PyResolverEntry {
  std::string prefix;
  std::shared_ptr<PyCallable> resolve;
};
std::vector<PyResolverEntry>& py_resolvers() {
  static std::vector<PyResolverEntry>* entries = new std::vector<PyResolverEntry>();  // outlives the interpreter
  return *entries;
}

// A property path of an arbitrary object: the first registered resolver answering for the path wins.
std::optional<Value> object_property(const py::object& target, const std::string& path) {
  for (const PyResolverEntry& entry : py_resolvers()) {
    if (path.rfind(entry.prefix, 0) != 0) continue;
    const py::object answer = entry.resolve->get()(target, path);
    if (py::isinstance<MissingType>(answer)) continue;
    return value_from_python(answer);
  }
  return std::nullopt;
}

// A predicate evaluated on an object that is not a shape: logic, and property comparisons that a registered
// resolver answers.  Anything else needs a shape.
bool matches_object(const ql::Predicate& predicate, const py::object& target) {
  const std::string kind = predicate.kind();
  if (kind == "and" || kind == "or") {
    const bool all = kind == "and";
    for (const ql::Predicate& child : predicate.children())
      if (matches_object(child, target) != all) return !all;
    return all;
  }
  if (kind == "not") return !matches_object(predicate.children().front(), target);
  if (kind == "property_compare") {
    const Value& data = predicate.data();
    const std::string path = data.find("path")->as_string();
    const std::string op = data.find("op")->as_string();
    const std::optional<Value> actual = object_property(target, path);
    return ql::compare(actual ? *actual : Value(), ql::parse_compare_op(op), op, *data.find("value"));
  }
  throw TypeError("predicate '" + kind + "' needs a shape: expected AnyShape, got " +
                  std::string(py::str(py::type::of(target).attr("__name__"))));
}

// ---- predicate / key factories ------------------------------------------------------------------------------------
ql::Predicate comparison(const py::object& op, ql::Predicate (*make)(std::string_view, std::string_view, Value),
                         const std::string& path, const Value& expected) {
  if (!py::isinstance<py::str>(op)) throw TypeError("op must be a string");
  return make(path, op.cast<std::string>(), expected);
}

// and_/or_ of serializable predicates is itself one; anything else becomes a plain Python callable.
py::object combine(const py::args& args, bool all) {
  const bool serializable =
      std::all_of(args.begin(), args.end(), [](const py::handle h) { return py::isinstance<ql::Predicate>(h); });
  if (serializable) {
    std::vector<ql::Predicate> children;
    for (const py::handle h : args) children.push_back(h.cast<ql::Predicate>());
    return py::cast(all ? ql::and_(std::move(children)) : ql::or_(std::move(children)));
  }
  const py::tuple predicates = args;
  return py::cpp_function([predicates, all](const py::object& obj) {
    for (const py::handle predicate : predicates)
      if (py::bool_(predicate(obj)) != all) return !all;
    return all;
  });
}

// ---- Query over arbitrary Python objects ---------------------------------------------------------------------------
// select() takes any iterable and any callable, like the Python Query; the typed ql::Query is for native callers.
struct PyQuery {
  py::list items;
};

PyQuery query_where(const PyQuery& self, const py::object& predicate) {
  py::list kept;
  for (const py::handle item : self.items)
    if (py::bool_(predicate(item))) kept.append(item);
  return PyQuery{kept};
}

PyQuery query_order_by(const PyQuery& self, const py::object& sort_key, bool desc) {
  const py::cpp_function safe_key([sort_key](const py::object& obj) {
    const py::object value = sort_key(obj);
    return py::make_tuple(value.is_none(), value);
  });
  const py::object ordered =
      py::module_::import("builtins").attr("sorted")(self.items, py::arg("key") = safe_key, py::arg("reverse") = desc);
  return PyQuery{py::list(ordered)};
}

PyQuery query_limit(const PyQuery& self, std::int64_t count) {
  if (count <= 0) return PyQuery{py::list()};
  return PyQuery{py::list(self.items[py::slice(0, count, 1)])};
}

// ---- evidence -------------------------------------------------------------------------------------------------------
py::object field_of(const py::object& item, const char* name) {
  if (py::isinstance<py::dict>(item)) return item.attr("get")(name, py::none());
  return py::getattr(item, name, py::none());
}

ErrorEvidence evidence_from_py(const py::object& item) {
  ErrorEvidence out;
  const auto text = [&](const char* name) {
    const py::object v = field_of(item, name);
    return v.is_none() ? std::string() : py::str(v).cast<std::string>();
  };
  out.kind = text("kind");
  out.path = text("path");
  out.view = text("view");
  out.caption = text("caption");
  const py::object symbols = field_of(item, "symbols");
  if (!symbols.is_none()) {
    const py::object pairs = py::isinstance<py::dict>(symbols) ? py::object(symbols.attr("items")()) : symbols;
    for (const py::handle pair : pairs) {
      const py::sequence entry = py::reinterpret_borrow<py::sequence>(pair);
      out.symbols.emplace_back(py::str(entry[0]).cast<std::string>(), py::str(entry[1]).cast<std::string>());
    }
  }
  return out;
}

// ---- raw shapes for the tests ------------------------------------------------------------------------------------------
// Stand-ins for the operators (which live in other areas) so QL tests can place and cut shapes.
Solid box_at(const Vec3& origin, double dx, double dy, double dz) {
  return Solid(BRepPrimAPI_MakeBox(gp_Pnt(origin.x, origin.y, origin.z), dx, dy, dz).Solid());
}

Solid cylinder_at(const Vec3& base, double radius, double height) {
  const gp_Ax2 axis(gp_Pnt(base.x, base.y, base.z), gp_Dir(0, 0, 1));
  return Solid(BRepPrimAPI_MakeCylinder(axis, radius, height).Solid());
}

Solid cut_solids(const Solid& body, const Solid& tool) {
  BRepAlgoAPI_Cut op(body.wrapped(), tool.wrapped());
  const TopExp_Explorer solids(op.Shape(), TopAbs_SOLID);
  if (!solids.More()) throw ValueError("the cut left no solid");
  return Solid(TopoDS::Solid(solids.Current()));
}

Compound compound_of(const std::vector<Solid>& solids) {
  BRep_Builder builder;
  TopoDS_Compound compound;
  builder.MakeCompound(compound);
  for (const Solid& s : solids) builder.Add(compound, s.wrapped());
  return Compound(compound);
}

// ---- the classes ----------------------------------------------------------------------------------------------------------
void bind_predicate(py::module_& q) {
  py::class_<ql::Predicate>(q, "SerializablePredicate",
                            "A serializable QL predicate: (kind, data, children), also callable on a shape.")
      .def(py::init([](const std::string& kind, const py::object& data, const py::object& children) {
             std::vector<ql::Predicate> kids;
             if (!children.is_none())
               for (const py::handle child : children) kids.push_back(child.cast<ql::Predicate>());
             return ql::Predicate(kind, data.is_none() ? Value::object() : value_from_python(data), std::move(kids));
           }),
           py::arg("kind"), py::arg("data") = py::none(), py::arg("children") = py::tuple())
      .def_property_readonly("kind", &ql::Predicate::kind)
      .def_property_readonly("data", [](const ql::Predicate& p) { return dict_of(p.data()); })
      .def_property_readonly("children",
                             [](const ql::Predicate& p) {
                               py::list kids;
                               for (const ql::Predicate& child : p.children()) kids.append(py::cast(child));
                               return py::tuple(kids);
                             })
      .def("__call__", [](const ql::Predicate& p, const py::object& obj) {
             if (py::isinstance<Shape>(obj)) return p.matches(obj.cast<const Shape&>());
             return matches_object(p, obj);
           }, py::arg("obj"))
      .def("to_dict", [](const ql::Predicate& p) { return dict_of(p.to_value()); })
      .def_static("from_dict", [](const Value& payload) { return ql::Predicate::from_value(payload); }, py::arg("data"))
      .def("__eq__", [](const ql::Predicate& a, const ql::Predicate& b) { return a == b; }, py::is_operator())
      .def("__repr__", [](const ql::Predicate& p) {
        py::list kids;
        for (const ql::Predicate& child : p.children()) kids.append(py::cast(child));
        return "SerializablePredicate(kind=" + std::string(py::repr(py::str(p.kind()))) +
               ", data=" + std::string(py::repr(dict_of(p.data()))) +
               ", children=" + std::string(py::repr(py::tuple(kids))) + ")";
      });

  py::class_<ql::Key>(q, "SerializableKey", "A serializable QL sort key: (kind, data), callable on a shape.")
      .def(py::init([](const std::string& kind, const py::object& data) {
             return ql::Key(kind, data.is_none() ? Value::object() : value_from_python(data));
           }),
           py::arg("kind"), py::arg("data") = py::none())
      .def_property_readonly("kind", &ql::Key::kind)
      .def_property_readonly("data", [](const ql::Key& k) { return dict_of(k.data()); })
      .def("__call__", [](const ql::Key& k, const py::object& obj) -> py::object {
             if (py::isinstance<Shape>(obj)) return py::cast(k.evaluate(obj.cast<const Shape&>()));
             if (k.kind() == "property") {
               const Value fallback = k.data().find("default") != nullptr ? *k.data().find("default") : Value();
               const auto found = object_property(obj, k.data().find("path")->as_string());
               return value_to_python(found ? *found : fallback);
             }
             throw TypeError("key '" + k.kind() + "' needs a shape");
           }, py::arg("obj"))
      .def("to_dict", [](const ql::Key& k) { return dict_of(k.to_value()); })
      .def_static("from_dict", [](const Value& payload) { return ql::Key::from_value(payload); }, py::arg("data"))
      .def("__eq__", [](const ql::Key& a, const ql::Key& b) { return a == b; }, py::is_operator())
      .def("__repr__", [](const ql::Key& k) {
        return "SerializableKey(kind=" + std::string(py::repr(py::str(k.kind()))) +
               ", data=" + std::string(py::repr(dict_of(k.data()))) + ")";
      });

  py::class_<ql::TraversalSpec>(q, "TraversalSpec")
      .def(py::init([](const std::string& relation) { return ql::TraversalSpec{relation}; }), py::arg("relation"))
      .def_readonly("relation", &ql::TraversalSpec::relation)
      .def("to_dict", [](const ql::TraversalSpec& t) { return dict_of(t.to_value()); })
      .def_static("from_dict", [](const Value& payload) { return ql::TraversalSpec::from_value(payload); },
                  py::arg("data"))
      .def("__eq__", [](const ql::TraversalSpec& a, const ql::TraversalSpec& b) { return a == b; }, py::is_operator());
}

void bind_factories(py::module_& q) {
  q.def(
      "tag",
      [](const py::object& pattern, const py::object& scope) {
        if (!py::isinstance<py::str>(pattern)) throw TypeError("pattern must be a string");
        return ql::tag(pattern.cast<std::string>(), scope_name(scope));
      },
      py::arg("pattern"), py::arg("scope") = "effective",
      "Build a tag predicate: an exact tag, or a prefix when the pattern ends in '*'.\n\n"
      "scope is one of local, inherited, effective or lineage.");
  q.def(
      "meta",
      [](const std::string& path, const py::object& op, const Value& value_) {
        return comparison(op, &ql::meta, path, value_);
      },
      py::arg("path"), py::arg("op"), py::arg("value_"),
      "Build a metadata comparison predicate; op is one of ==, !=, >, >=, <, <=.");
  q.def(
      "prop",
      [](const std::string& path, const py::object& op, const Value& value_) {
        return comparison(op, &ql::prop, path, value_);
      },
      py::arg("path"), py::arg("op"), py::arg("value_"),
      "Build a property comparison predicate over metadata or measured geometry (geom.*, topo.*).");
  q.def("value", [](const std::string& path, const Value& fallback) { return ql::value(path, fallback); },
        py::arg("path"), py::arg("default") = Value(), "Build a value key (metadata first, then geo.area/length/volume).");
  q.def("key", [](const std::string& path, const Value& fallback) { return ql::key(path, fallback); },
        py::arg("path"), py::arg("default") = Value(), "Build a property key.");
  q.def("geo", [](const std::string& field, const Value& fallback) { return ql::geo(field, fallback); },
        py::arg("field"), py::arg("default") = Value(), "Shortcut for value('geo.<field>').");
  q.def("center_axis", [](const std::string& axis) { return ql::center_axis(axis); }, py::arg("axis"));
  q.def("curve_type", [](const std::string& kind) { return ql::curve_type(kind); }, py::arg("kind"));
  q.def("surface_type", [](const std::string& kind) { return ql::surface_type(kind); }, py::arg("kind"));

  q.def("and_", [](const py::args& predicates) { return combine(predicates, true); },
        "Combine predicates so all of them must match.");
  q.def("or_", [](const py::args& predicates) { return combine(predicates, false); },
        "Combine predicates so at least one of them must match.");
  q.def(
      "not_",
      [](const py::object& predicate) -> py::object {
        if (py::isinstance<ql::Predicate>(predicate)) return py::cast(ql::not_(predicate.cast<ql::Predicate>()));
        return py::cpp_function([predicate](const py::object& obj) { return !py::bool_(predicate(obj)); });
      },
      py::arg("predicate"), "Negate a QL predicate.");

  const auto operation_event = [](const py::object& op_name, const py::object& event) {
    return ql::operation_event(text_of(op_name, "op_name must be a non-empty string"),
                               text_of(event, "event must be a non-empty string"));
  };
  q.def("operation_event", operation_event, py::arg("op_name"), py::arg("event") = "*",
        "Match typed operation and topology-event metadata under track.");
  q.def("op", operation_event, py::arg("op_name"), py::arg("event") = "*");

  const auto origin_role = [](const py::object& role_name) {
    return ql::origin_role(text_of(role_name, "role_name must be a non-empty string"));
  };
  q.def("origin_role", origin_role, py::arg("role_name"), "Match a typed source role under track metadata.");
  q.def("origin", origin_role, py::arg("role_name"));
  q.def(
      "output_role",
      [](const py::object& role_name) { return ql::output_role(text_of(role_name, "role_name must be a non-empty string")); },
      py::arg("role_name"), "Match a kernel-proven operation output role under track metadata.");
  q.def(
      "source_binding",
      [](const py::object& binding_id) { return ql::source_binding(text_of(binding_id, "binding_id must be a non-empty string")); },
      py::arg("binding_id"), "Match a projected local binding by its exact source binding identity.");
  q.def(
      "source_topology",
      [](const py::object& topo_id) { return ql::source_topology(text_of(topo_id, "topo_id must be a non-empty string")); },
      py::arg("topo_id"), "Match a projected local binding by its exact source topology identity.");
  q.def("role", [](const std::string& role_name) { return ql::role(role_name); }, py::arg("role_name"));

  q.def(
      "register_property_resolver",
      [](const py::object& prefix, const py::object& resolver) {
        if (!py::isinstance<py::str>(prefix) || prefix.cast<std::string>().empty())
          throw ValueError("prefix must be a non-empty string");
        const auto callable = std::make_shared<PyCallable>(resolver);
        const std::string name = prefix.cast<std::string>();
        auto& entries = py_resolvers();
        const auto found = std::find_if(entries.begin(), entries.end(), [&](const PyResolverEntry& e) { return e.prefix == name; });
        if (found != entries.end()) found->resolve = callable;
        else entries.push_back({name, callable});
        ql::register_property_resolver(
            name, [callable](const Shape& shape, std::string_view path) -> std::optional<Value> {
              const py::object answer = callable->get()(shape_to_py(shape), std::string(path));
              if (py::isinstance<MissingType>(answer)) return std::nullopt;
              return value_from_python(answer);
            });
      },
      py::arg("prefix"), py::arg("resolver"),
      "Answer property paths that start with `prefix`: resolver(shape, path) returns a value or ql.MISSING.");
  q.def("unregister_property_resolver", [](const std::string& prefix) {
          auto& entries = py_resolvers();
          entries.erase(std::remove_if(entries.begin(), entries.end(), [&](const PyResolverEntry& e) { return e.prefix == prefix; }),
                        entries.end());
          ql::unregister_property_resolver(prefix);
        },
        py::arg("prefix"));
}

void bind_selector(py::module_& q) {
  py::class_<ql::ShapeSelector>(q, "ShapeSelector", "A fluent, serializable query over the topology of a shape.")
      .def(py::init<std::string>(), py::arg("target_kind"))
      .def_property_readonly("target_kind", &ql::ShapeSelector::target_kind)
      .def_property_readonly("source_selector",
                             [](const ql::ShapeSelector& s) -> py::object {
                               const ql::ShapeSelector* source = s.source_selector();
                               return source != nullptr ? py::cast(*source) : py::none();
                             })
      .def_property_readonly("traversal",
                             [](const ql::ShapeSelector& s) -> py::object {
                               return s.traversal() ? py::cast(*s.traversal()) : py::none();
                             })
      .def_property_readonly("predicate",
                             [](const ql::ShapeSelector& s) -> py::object {
                               return s.predicate() ? py::cast(*s.predicate()) : py::none();
                             })
      .def_property_readonly("order_key",
                             [](const ql::ShapeSelector& s) -> py::object {
                               return s.order_key() ? py::cast(*s.order_key()) : py::none();
                             })
      .def_property_readonly("order_keys",
                             [](const ql::ShapeSelector& s) {
                               py::list out;
                               for (const auto& [sort_key, desc] : s.order_keys())
                                 out.append(py::make_tuple(py::cast(sort_key), desc));
                               return py::tuple(out);
                             })
      .def_property_readonly("order_desc", &ql::ShapeSelector::order_desc)
      .def_property_readonly("limit_count",
                             [](const ql::ShapeSelector& s) -> py::object {
                               return s.limit_count() ? py::object(py::int_(*s.limit_count())) : py::none();
                             })
      .def_property_readonly("cardinality",
                             [](const ql::ShapeSelector& s) {
                               py::dict out;
                               for (const auto& [mode, count] : s.cardinality()) out[py::str(mode)] = count;
                               return out;
                             })
      .def_property_readonly("source_node_id",
                             [](const ql::ShapeSelector& s) -> py::object {
                               return s.source_node_id() ? py::object(py::str(*s.source_node_id())) : py::none();
                             })
      .def_property_readonly("source_output_slot",
                             [](const ql::ShapeSelector& s) -> py::object {
                               return s.source_output_slot() ? py::object(py::int_(*s.source_output_slot())) : py::none();
                             })
      .def_property_readonly("set_operation",
                             [](const ql::ShapeSelector& s) -> py::object {
                               return s.set_operation() ? py::object(py::str(*s.set_operation())) : py::none();
                             })
      .def_property_readonly("operands",
                             [](const ql::ShapeSelector& s) {
                               py::list out;
                               for (const auto& operand : s.operands()) out.append(py::cast(operand));
                               return py::tuple(out);
                             })
      .def_property_readonly("incident_face_selectors",
                             [](const ql::ShapeSelector& s) {
                               py::list out;
                               for (const auto& selector : s.incident_face_selectors()) out.append(py::cast(selector));
                               return py::tuple(out);
                             })
      .def_property_readonly("incident_faces_distinct", &ql::ShapeSelector::incident_faces_distinct)
      .def_property_readonly("incident_face_cardinality",
                             [](const ql::ShapeSelector& s) {
                               py::dict out;
                               if (s.incident_face_cardinality()) out["exactly"] = *s.incident_face_cardinality();
                               return out;
                             })
      .def(
          "where",
          [](const ql::ShapeSelector& s, const py::object& predicate) {
            if (!py::isinstance<ql::Predicate>(predicate))
              throw TypeError("ShapeSelector.where only supports serializable QL predicates");
            return s.where(predicate.cast<ql::Predicate>());
          },
          py::arg("predicate"))
      .def(
          "order_by",
          [](const ql::ShapeSelector& s, const py::object& sort_key, bool desc) {
            if (!py::isinstance<ql::Key>(sort_key))
              throw TypeError("ShapeSelector.order_by only supports serializable QL keys");
            return s.order_by(sort_key.cast<ql::Key>(), desc);
          },
          py::arg("key"), py::arg("desc") = false)
      .def("from_source",
           [](const ql::ShapeSelector& s, const std::string& node_id, int slot) { return s.from_source(node_id, slot); },
           py::arg("node_id"), py::arg("output_slot") = 0)
      .def("take", [](const ql::ShapeSelector& s, std::int64_t count) { return s.take(count); }, py::arg("count"))
      .def("exactly", [](const ql::ShapeSelector& s, std::int64_t count) { return s.exactly(count); }, py::arg("count"))
      .def("at_least", [](const ql::ShapeSelector& s, std::int64_t count) { return s.at_least(count); }, py::arg("count"))
      .def("at_most", [](const ql::ShapeSelector& s, std::int64_t count) { return s.at_most(count); }, py::arg("count"))
      .def("traverse",
           [](const ql::ShapeSelector& s, const std::string& relation, const std::string& to_kind) {
             return s.traverse(relation, to_kind);
           },
           py::arg("relation"), py::arg("to_kind"))
      .def("boundary", [](const ql::ShapeSelector& s, const std::string& to_kind) { return s.boundary(to_kind); },
           py::arg("to_kind"))
      .def(
          "intersection",
          [](const ql::ShapeSelector& s, const py::object& other) {
            if (!py::isinstance<ql::ShapeSelector>(other)) throw TypeError("intersection requires another ShapeSelector");
            return s.intersection(other.cast<ql::ShapeSelector>());
          },
          py::arg("other"), "Return entities present in both selector result sets.")
      .def(
          "shared_boundary",
          [](const ql::ShapeSelector& s, const py::object& other, const std::string& to_kind) {
            if (!py::isinstance<ql::ShapeSelector>(other)) throw TypeError("intersection requires another ShapeSelector");
            return s.shared_boundary(other.cast<ql::ShapeSelector>(), to_kind);
          },
          py::arg("other"), py::arg("to_kind") = "edge",
          "Select current-topology boundary entities shared by both operands.")
      .def(
          "incident_to",
          [](const ql::ShapeSelector& s, const py::args& face_selectors, bool distinct) {
            if (s.target_kind() != "edge") throw ValueError("incident_to is only valid on an Edge selector");
            std::vector<ql::ShapeSelector> selectors;
            for (const py::handle h : face_selectors) {
              if (!py::isinstance<ql::ShapeSelector>(h)) throw TypeError("incident_to requires one or more Face selectors");
              selectors.push_back(h.cast<ql::ShapeSelector>());
            }
            return s.incident_to(std::move(selectors), distinct);
          },
          py::kw_only(), py::arg("distinct") = false, "Restrict Edges by their distinct incident Face witnesses.")
      .def("incident_face_count",
           [](const ql::ShapeSelector& s, std::int64_t exactly) { return s.incident_face_count(exactly); },
           py::kw_only(), py::arg("exactly"))
      .def(
          "resolve",
          [](const ql::ShapeSelector& s, const py::object& scope) {
            return shapes_to_py(s.resolve(scope_from_py(scope, s.target_kind())));
          },
          py::arg("scope"), "The shapes this query picks inside `scope` (a shape or a list of shapes).")
      .def("to_dict", [](const ql::ShapeSelector& s) { return dict_of(s.to_value()); })
      .def_static("from_dict", [](const Value& payload) { return ql::ShapeSelector::from_value(payload); },
                  py::arg("data"))
      .def("__eq__", [](const ql::ShapeSelector& a, const ql::ShapeSelector& b) { return a == b; }, py::is_operator())
      .def("__repr__", [](const ql::ShapeSelector& s) {
        return "ShapeSelector(" + std::string(py::repr(dict_of(s.to_value()))) + ")";
      });

  q.def("edges", [] { return ql::edges(); });
  q.def("faces", [] { return ql::faces(); });
  q.def("wires", [] { return ql::wires(); });
  q.def("vertices", [] { return ql::vertices(); });
  q.def("solids", [] { return ql::solids(); });
  q.def("shells", [] { return ql::shells(); }, "Select Shell entities from a Shell or compatible topology scope.");
  q.def("selector_from_dict", [](const Value& payload) { return ql::selector_from_value(payload); }, py::arg("data"));
}

void bind_query(py::module_& q) {
  py::class_<PyQuery>(q, "Query")
      .def(py::init([](const py::iterable& items) { return PyQuery{py::list(items)}; }), py::arg("items"))
      .def("where", &query_where, py::arg("predicate"))
      .def("order_by", &query_order_by, py::arg("key"), py::arg("desc") = false)
      .def("limit", &query_limit, py::arg("count"))
      .def("first", [](const PyQuery& self) -> py::object { return self.items.empty() ? py::none() : py::object(self.items[0]); })
      .def("all", [](const PyQuery& self) { return py::list(self.items); });
  q.def("select", [](const py::iterable& items) { return PyQuery{py::list(items)}; }, py::arg("items"),
        "Start a QL query over a shape collection or selector scope.");
}

void bind_hooks_and_testing(py::module_& q) {
  q.def(
      "_set_evidence_provider",
      [](const py::object& provider) {
        if (provider.is_none()) {
          ql::set_evidence_provider({});
          return;
        }
        const auto callable = std::make_shared<PyCallable>(provider);
        ql::set_evidence_provider([callable](const ql::EvidenceRequest& request) {
          const py::tuple dedup =
              py::make_tuple("ql", request.target_kind, request.mode, request.expected, request.matched.size());
          const py::object rendered =
              callable->get()(scope_to_py(request.scope), shapes_to_py(request.matched), request.target_kind, dedup,
                              shapes_to_py(request.near_misses));
          std::vector<ErrorEvidence> out;
          if (!rendered.is_none())
            for (const py::handle item : rendered) out.push_back(evidence_from_py(py::reinterpret_borrow<py::object>(item)));
          return out;
        });
      },
      py::arg("provider"),
      "Install provider(scope, matched, target_kind, dedup_key, near_misses) -> list of evidence dicts; it "
      "attaches rendered views to cardinality errors.  None removes it.");

  py::module_ testing = q.def_submodule("_testing", "raw-OCCT shapes for the QL tests (the operators live elsewhere)");
  testing.def("box_at", &box_at, py::arg("origin"), py::arg("dx"), py::arg("dy"), py::arg("dz"));
  testing.def("cylinder_at", &cylinder_at, py::arg("base"), py::arg("radius"), py::arg("height"));
  testing.def("cut", &cut_solids, py::arg("body"), py::arg("tool"));
  testing.def("compound", &compound_of, py::arg("solids"));
}

}  // namespace

void bind_ql(py::module_& m) {
  py::module_ q = m.def_submodule("ql", "The selector query language: ql.faces().where(...).exactly(1).resolve(shape)");
  py::module_::import("sys").attr("modules")[py::str(error_module_name() + ".ql")] = q;

  py::class_<MissingType>(q, "_Missing").def("__repr__", [](const MissingType&) { return "MISSING"; });
  q.attr("MISSING") = py::cast(MissingType{});

  bind_predicate(q);
  bind_factories(q);
  bind_selector(q);
  bind_query(q);
  bind_hooks_and_testing(q);
}
