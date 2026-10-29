// Python bindings for the "sketch" area: the Sketch document, its data classes,
// the solver backend registry (duck-typed Python backends included) and the 42
// operators, under the names and signatures of simplecadapi.
#include "bindings.hpp"
#include "py_lifetime.hpp"

#include <mutex>

#include "scad/core/error.hpp"
#include "scad/sketch/native_solver.hpp"
#include "scad/sketch/operators.hpp"

namespace pybind11::detail {

// SketchTarget <- SketchRef | str
template <>
struct type_caster<scad::SketchTarget> {
  PYBIND11_TYPE_CASTER(scad::SketchTarget, const_name("SketchRef | str"));

  bool load(handle src, bool) {
    if (isinstance<scad::SketchRef>(src)) {
      value = scad::SketchTarget(src.cast<scad::SketchRef>());
      return true;
    }
    if (isinstance<str>(src)) {
      value = scad::SketchTarget(src.cast<std::string>());
      return true;
    }
    return false;
  }
  static handle cast(const scad::SketchTarget& target, return_value_policy, handle) {
    return target.is_ref() ? pybind11::cast(target.ref()).release() : pybind11::cast(target.path()).release();
  }
};

// SketchControlPoint <- SketchRef | str | {"point_id": ...} | (x, y)
template <>
struct type_caster<scad::SketchControlPoint> {
 public:
  PYBIND11_TYPE_CASTER(scad::SketchControlPoint, const_name("SketchRef | str | tuple[float, float]"));

  bool load(handle src, bool) {
    if (isinstance<scad::SketchRef>(src)) {
      value = scad::SketchControlPoint(scad::SketchTarget(src.cast<scad::SketchRef>()));
      return true;
    }
    if (isinstance<str>(src)) {
      value = scad::SketchControlPoint(src.cast<std::string>());
      return true;
    }
    if (isinstance<dict>(src)) {
      const dict mapping = reinterpret_borrow<dict>(src);
      object point = mapping.contains("point_id") ? mapping["point_id"]
                                                  : (mapping.contains("point") ? mapping["point"] : object());
      if (!point)
        throw scad::ValueError("bspline control point mapping requires point_id");
      value = scad::SketchControlPoint(str(point).cast<std::string>());
      return true;
    }
    if (isinstance<sequence>(src)) {
      const sequence seq = reinterpret_borrow<sequence>(src);
      if (seq.size() != 2) {
        throw scad::ValueError("bspline control point must contain exactly two coordinates");
      }
      value = scad::SketchControlPoint(seq[0].cast<double>(), seq[1].cast<double>());
      return true;
    }
    return false;
  }
};

// SketchProfileId <- int | str
template <>
struct type_caster<scad::SketchProfileId> {
  PYBIND11_TYPE_CASTER(scad::SketchProfileId, const_name("int | str"));

  bool load(handle src, bool) {
    if (isinstance<str>(src)) {
      value = scad::SketchProfileId(src.cast<std::string>());
      return true;
    }
    if (PyLong_Check(src.ptr()) && !PyBool_Check(src.ptr())) {
      value = scad::SketchProfileId(src.cast<int>());
      return true;
    }
    return false;
  }
  static handle cast(const scad::SketchProfileId& id, return_value_policy, handle) {
    return id.is_index() ? pybind11::cast(id.index()).release() : pybind11::cast(id.id()).release();
  }
};

}  // namespace pybind11::detail

namespace {

using namespace scad;
using pybind::value_from_python;
using pybind::value_to_python;

// A Python object that implements the SketchSolverBackend protocol.
class PythonBackend final : public SketchSolverBackend {
 public:
  explicit PythonBackend(py::object object) : object_(std::move(object)) {}
  ~PythonBackend() override { scad::pybind::drop_python_reference(object_); }
  std::string name() const override {
    const py::gil_scoped_acquire gil;
    return py::str(object_.attr("name")).cast<std::string>();
  }
  std::string version() const override {
    const py::gil_scoped_acquire gil;
    return py::str(object_.attr("version")).cast<std::string>();
  }
  SketchSolveResult solve(const Sketch& sketch, const SketchSolverOptions& options) const override {
    const py::gil_scoped_acquire gil;
    py::object result = object_.attr("solve")(py::cast(sketch), py::arg("options") = py::cast(options));
    return result.cast<SketchSolveResult>();
  }

 private:
  py::object object_;
};

std::shared_ptr<SketchSolverBackend> backend_from_python(const py::object& backend) {
  if (backend.is_none())
    return get_default_sketch_solver_backend();
  if (py::isinstance<py::str>(backend))
    return get_sketch_solver_backend(backend.cast<std::string>());
  if (py::isinstance<SketchSolverBackend>(backend))
    return backend.cast<std::shared_ptr<SketchSolverBackend>>();
  return std::make_shared<PythonBackend>(backend);
}

template <class T>
py::dict to_dict_of(const OrderedMap<T>& map, py::object (*convert)(const T&)) {
  py::dict out;
  for (const auto& [key, value] : map)
    out[py::str(key)] = convert(value);
  return out;
}

template <class T>
OrderedMap<T> from_dict_of(const py::object& mapping, T (*convert)(const py::handle&)) {
  OrderedMap<T> out;
  if (mapping.is_none())
    return out;
  for (const auto& item : mapping.cast<py::dict>())
    out.set(py::str(item.first).cast<std::string>(), convert(item.second));
  return out;
}

py::object point_to_python(const SketchPoint2& p) {
  return py::make_tuple(p.first, p.second);
}
py::object double_to_python(const double& v) {
  return py::float_(v);
}
py::object value_object(const Value& v) {
  return value_to_python(v);
}
SketchPoint2 point_from_python(const py::handle& h) {
  const py::sequence seq = py::reinterpret_borrow<py::sequence>(h);
  return {seq[0].cast<double>(), seq[1].cast<double>()};
}
double double_from_python(const py::handle& h) {
  return h.cast<double>();
}
Value value_from_handle(const py::handle& h) {
  return value_from_python(h);
}

SketchSolveRequest request_of(bool require_fully_constrained, bool strict, double tolerance, int max_iterations) {
  SketchSolveRequest request;
  request.require_fully_constrained = require_fully_constrained;
  request.strict = strict;
  request.tolerance = tolerance;
  request.max_iterations = max_iterations;
  return request;
}

void bind_data_classes(py::module_& m) {
  py::class_<SketchRef>(m, "SketchRef")
      .def(py::init([](std::string sketch_id, std::string entity_id, std::string kind, std::string subentity) {
             return SketchRef{std::move(sketch_id), std::move(entity_id), std::move(kind), std::move(subentity)};
           }),
           py::arg("sketch_id"), py::arg("entity_id"), py::kw_only(), py::arg("kind"),
           py::arg("subentity") = "geometry")
      .def_readwrite("sketch_id", &SketchRef::sketch_id)
      .def_readwrite("entity_id", &SketchRef::entity_id)
      .def_readwrite("kind", &SketchRef::kind)
      .def_readwrite("subentity", &SketchRef::subentity)
      .def("to_dict", [](const SketchRef& r) { return value_to_python(r.to_value()); })
      .def_static("from_dict", [](const py::object& data) { return SketchRef::from_value(value_from_python(data)); })
      .def("__repr__", &SketchRef::repr)
      .def("__eq__", [](const SketchRef& a, const SketchRef& b) { return a == b; })
      .def("__hash__", [](const SketchRef& r) {
        return std::hash<std::string>{}(r.sketch_id + "|" + r.entity_id + "|" + r.kind + "|" + r.subentity);
      });

  py::class_<SketchEntity>(m, "SketchEntity")
      .def_property_readonly("entity_id", [](const SketchEntity& e) { return e.id; })
      .def_readonly("kind", &SketchEntity::kind)
      .def_readonly("construction", &SketchEntity::construction)
      .def_property_readonly("data", [](const SketchEntity& e) { return value_to_python(e.data); })
      .def("to_dict", [](const SketchEntity& e) { return value_to_python(e.to_value()); });

  py::class_<SketchConstraint>(m, "SketchConstraint")
      .def_property_readonly("constraint_id", [](const SketchConstraint& c) { return c.id; })
      .def_readonly("kind", &SketchConstraint::kind)
      .def_property_readonly("targets",
                             [](const SketchConstraint& c) {
                               py::list targets;
                               for (const SketchRef& t : c.targets)
                                 targets.append(value_to_python(t.to_value()));
                               return py::tuple(targets);
                             })
      .def_property_readonly("value",
                             [](const SketchConstraint& c) -> py::object {
                               return c.value ? py::object(py::float_(c.numeric_value())) : py::none();
                             })
      .def_readonly("driving", &SketchConstraint::driving)
      .def_property_readonly("metadata", [](const SketchConstraint& c) { return value_to_python(c.metadata); })
      .def("to_dict", [](const SketchConstraint& c) { return value_to_python(c.to_value()); });

  py::class_<SketchConstraintDiagnostic>(m, "SketchConstraintDiagnostic")
      .def(py::init([](std::optional<std::string> constraint_id, std::string severity, std::string code,
                       std::string message, std::optional<double> residual) {
             return SketchConstraintDiagnostic{std::move(constraint_id), std::move(severity), std::move(code),
                                               std::move(message), residual};
           }),
           py::arg("constraint_id"), py::arg("severity"), py::arg("code"), py::arg("message"),
           py::arg("residual") = py::none())
      .def_readonly("constraint_id", &SketchConstraintDiagnostic::constraint_id)
      .def_readonly("severity", &SketchConstraintDiagnostic::severity)
      .def_readonly("code", &SketchConstraintDiagnostic::code)
      .def_readonly("message", &SketchConstraintDiagnostic::message)
      .def_readonly("residual", &SketchConstraintDiagnostic::residual);

  py::class_<SketchSolverOptions>(m, "SketchSolverOptions")
      .def(
          py::init([](double tolerance, int max_iterations) { return SketchSolverOptions{tolerance, max_iterations}; }),
          py::arg("tolerance") = 1e-7, py::arg("max_iterations") = 80)
      .def_readonly("tolerance", &SketchSolverOptions::tolerance)
      .def_readonly("max_iterations", &SketchSolverOptions::max_iterations);

  py::class_<SketchSolveResult>(m, "SketchSolveResult")
      .def(py::init([](std::string sketch_id, std::string status, int dof, double residual_norm, int iterations,
                       const py::object& solved_points, const py::object& solved_scalars,
                       const py::object& solved_entities, const py::object& diagnostics, std::string backend,
                       std::string backend_version, std::optional<int> backend_status_code) {
             SketchSolveResult r;
             r.sketch_id = std::move(sketch_id);
             r.status = std::move(status);
             r.dof = dof;
             r.residual_norm = residual_norm;
             r.iterations = iterations;
             r.solved_points = from_dict_of<SketchPoint2>(solved_points, point_from_python);
             r.solved_scalars = from_dict_of<double>(solved_scalars, double_from_python);
             r.solved_entities = from_dict_of<Value>(solved_entities, value_from_handle);
             if (!diagnostics.is_none()) {
               for (const auto& item : diagnostics)
                 r.diagnostics.push_back(item.cast<SketchConstraintDiagnostic>());
             }
             r.backend = std::move(backend);
             r.backend_version = std::move(backend_version);
             r.backend_status_code = backend_status_code;
             return r;
           }),
           py::arg("sketch_id"), py::arg("status"), py::arg("dof"), py::arg("residual_norm"), py::arg("iterations"),
           py::arg("solved_points"), py::arg("solved_scalars"), py::arg("solved_entities") = py::none(),
           py::arg("diagnostics") = py::none(), py::arg("backend") = "unknown", py::arg("backend_version") = "unknown",
           py::arg("backend_status_code") = py::none())
      .def_readwrite("sketch_id", &SketchSolveResult::sketch_id)
      .def_readwrite("status", &SketchSolveResult::status)
      .def_readwrite("dof", &SketchSolveResult::dof)
      .def_readwrite("residual_norm", &SketchSolveResult::residual_norm)
      .def_readwrite("iterations", &SketchSolveResult::iterations)
      .def_property_readonly(
          "solved_points",
          [](const SketchSolveResult& r) { return to_dict_of<SketchPoint2>(r.solved_points, point_to_python); })
      .def_property_readonly(
          "solved_scalars",
          [](const SketchSolveResult& r) { return to_dict_of<double>(r.solved_scalars, double_to_python); })
      .def_property_readonly(
          "solved_entities",
          [](const SketchSolveResult& r) { return to_dict_of<Value>(r.solved_entities, value_object); })
      .def_property_readonly("diagnostics",
                             [](const SketchSolveResult& r) { return py::tuple(py::cast(r.diagnostics)); })
      .def_readwrite("backend", &SketchSolveResult::backend)
      .def_readwrite("backend_version", &SketchSolveResult::backend_version)
      .def_readwrite("backend_status_code", &SketchSolveResult::backend_status_code)
      .def("to_dict", [](const SketchSolveResult& r) { return value_to_python(r.to_value()); });
}

void bind_backends(py::module_& m) {
  py::class_<SketchSolverBackend, std::shared_ptr<SketchSolverBackend>>(m, "SketchSolverBackend")
      .def_property_readonly("name", [](const SketchSolverBackend& b) { return b.name(); })
      .def_property_readonly("version", [](const SketchSolverBackend& b) { return b.version(); })
      .def(
          "solve",
          [](const SketchSolverBackend& b, const Sketch& sketch, const SketchSolverOptions& options) {
            return b.solve(sketch, options);
          },
          py::arg("sketch"), py::kw_only(), py::arg("options"));

  m.def(
      "register_sketch_solver_backend",
      [](const py::object& backend, bool replace) {
        register_sketch_solver_backend(py::isinstance<SketchSolverBackend>(backend)
                                           ? backend.cast<std::shared_ptr<SketchSolverBackend>>()
                                           : std::make_shared<PythonBackend>(backend),
                                       replace);
      },
      py::arg("backend"), py::kw_only(), py::arg("replace") = false);
  m.def(
      "get_sketch_solver_backend",
      [](const std::optional<std::string>& name) { return get_sketch_solver_backend(name); },
      py::arg("name") = py::none());
  m.def("get_default_sketch_solver_backend", [] { return get_default_sketch_solver_backend(); });
  m.def(
      "set_default_sketch_solver_backend",
      [](const py::object& backend) {
        if (py::isinstance<py::str>(backend)) {
          set_default_sketch_solver_backend(backend.cast<std::string>());
        } else {
          set_default_sketch_solver_backend(backend_from_python(backend));
        }
      },
      py::arg("backend"));

  // `with sketch_solver_backend(...)`: select, then restore the previous default.
  struct BackendContext {
    py::object backend;
    std::string previous;
  };
  py::class_<BackendContext>(m, "_SketchSolverBackendContext")
      .def("__enter__",
           [](BackendContext& c) {
             c.previous = get_default_sketch_solver_backend()->name();
             if (py::isinstance<py::str>(c.backend)) {
               set_default_sketch_solver_backend(c.backend.cast<std::string>());
             } else {
               set_default_sketch_solver_backend(backend_from_python(c.backend));
             }
             return get_default_sketch_solver_backend();
           })
      .def("__exit__", [](BackendContext& c, const py::args&) {
        set_default_sketch_solver_backend(c.previous);
        return false;
      });
  m.def(
      "sketch_solver_backend", [](const py::object& backend) { return BackendContext{backend, {}}; },
      py::arg("backend"));
}

void bind_sketch_class(py::module_& m) {
  py::class_<Sketch>(m, "Sketch")
      .def(py::init([](const py::object& curves, std::optional<std::string> name, const py::object& plane,
                       std::optional<std::string> sketch_id) {
             Sketch sketch(std::move(name), value_from_python(plane), std::move(sketch_id));
             if (!curves.is_none()) {
               for (const auto& curve : curves)
                 sketch.add_curve(curve.cast<Shape>());
             }
             return sketch;
           }),
           py::arg("curves") = py::none(), py::kw_only(), py::arg("name") = py::none(), py::arg("plane") = "XY",
           py::arg("sketch_id") = py::none())
      .def_property_readonly("sketch_id", [](const Sketch& s) { return s.sketch_id(); })
      .def_property_readonly("name", [](const Sketch& s) { return s.name(); })
      .def_property_readonly("plane",
                             [](const Sketch& s) {
                               py::object plane = value_to_python(s.plane());
                               // A plane mapping holds its frame vectors as tuples of floats.
                               if (py::isinstance<py::dict>(plane)) {
                                 for (const char* key : {"origin", "x_axis", "y_axis", "z_axis"})
                                   if (plane.contains(key) && py::isinstance<py::list>(plane[key]))
                                     plane[key] = py::tuple(plane[key]);
                               }
                               return plane;
                             })
      .def_property_readonly("entities",
                             [](const Sketch& s) {
                               py::dict out;
                               for (const auto& [id, entity] : s.entities())
                                 out[py::str(id)] = entity;
                               return out;
                             })
      .def_property_readonly("entity_order", [](const Sketch& s) { return s.entities().keys(); })
      .def_property_readonly("constraints", [](const Sketch& s) { return s.constraints(); })
      .def(
          "add_curve", [](Sketch& s, const Shape& curve) -> Sketch& { return s.add_curve(curve); }, py::arg("curve"),
          py::return_value_policy::reference_internal)
      .def("curves", &Sketch::curves)
      .def("closed_wires", &Sketch::closed_wires)
      .def("to_faces", [](const Sketch& s) { return sketch_to_faces(s); })
      .def(
          "to_face",
          [](const Sketch& s, const SketchProfileId& profile, const std::vector<SketchProfileId>& inner) {
            return make_face_from_sketch_rface(s, profile, inner);
          },
          py::arg("profile") = 0, py::kw_only(), py::arg("inner_profiles") = std::vector<SketchProfileId>{})
      .def(
          "clone", [](const Sketch& s, bool include_solve) { return s.clone(include_solve); }, py::kw_only(),
          py::arg("include_solve") = true)
      .def("to_dict", [](const Sketch& s) { return value_to_python(s.to_value()); })
      .def_static("from_dict", [](const py::object& data) { return Sketch::from_value(value_from_python(data)); })
      .def(
          "ref",
          [](const Sketch& s, const std::string& entity_id, std::optional<std::string> kind, const std::string& sub) {
            return s.ref(entity_id, kind, sub);
          },
          py::arg("entity_id"), py::kw_only(), py::arg("kind") = py::none(), py::arg("subentity") = "geometry")
      .def("point_ref", &Sketch::point_ref, py::arg("path"))
      .def(
          "resolve_target",
          [](const Sketch& s, const SketchTarget& target, const py::object& expected) {
            std::vector<std::string> kinds;
            if (py::isinstance<py::str>(expected)) {
              kinds.push_back(expected.cast<std::string>());
            } else if (!expected.is_none()) {
              for (const auto& item : expected)
                kinds.push_back(py::str(item).cast<std::string>());
            }
            return s.resolve_target(target, kinds);
          },
          py::arg("target"), py::kw_only(), py::arg("expected") = py::none())
      .def("validate_ref", &Sketch::validate_ref, py::arg("ref"))
      .def("resolve_point_id", &Sketch::resolve_point_id, py::arg("ref"))
      .def("add_point", &Sketch::add_point, py::arg("point_id"), py::arg("x"), py::arg("y"))
      .def(
          "add_line",
          [](Sketch& s, const std::string& id, const SketchRef& a, const SketchRef& b, bool construction) -> Sketch& {
            return s.add_line(id, a, b, construction);
          },
          py::arg("entity_id"), py::arg("start"), py::arg("end"), py::kw_only(), py::arg("construction") = false,
          py::return_value_policy::reference_internal)
      .def(
          "add_circle",
          [](Sketch& s, const std::string& id, const SketchRef& c, const Scalar& r, bool construction) -> Sketch& {
            return s.add_circle(id, c, r, construction);
          },
          py::arg("entity_id"), py::arg("center"), py::arg("radius"), py::kw_only(), py::arg("construction") = false,
          py::return_value_policy::reference_internal)
      .def(
          "add_arc",
          [](Sketch& s, const std::string& id, const SketchRef& a, const SketchRef& b, const SketchRef& c,
             bool construction) -> Sketch& { return s.add_arc(id, a, b, c, construction); },
          py::arg("entity_id"), py::arg("start"), py::arg("end"), py::arg("center"), py::kw_only(),
          py::arg("construction") = false, py::return_value_policy::reference_internal)
      .def(
          "add_ellipse",
          [](Sketch& s, const std::string& id, const SketchRef& c, const SketchRef& a, const SketchRef& b,
             bool construction) -> Sketch& { return s.add_ellipse(id, c, a, b, construction); },
          py::arg("entity_id"), py::arg("center"), py::arg("major_point"), py::arg("minor_point"), py::kw_only(),
          py::arg("construction") = false, py::return_value_policy::reference_internal)
      .def(
          "add_bspline",
          [](Sketch& s, const std::string& id, const SketchRef& start, const SketchRef& end,
             const std::vector<SketchControlPoint>& control_points, int degree,
             const std::optional<std::vector<Scalar>>& knots, const std::optional<std::vector<int>>& multiplicities,
             const std::optional<std::vector<Scalar>>& weights, bool periodic, bool construction) -> Sketch& {
            return s.add_bspline(id, start, end, control_points, degree, knots, multiplicities, weights, periodic,
                                 construction);
          },
          py::arg("entity_id"), py::arg("start"), py::arg("end"), py::arg("control_points"), py::arg("degree") = 3,
          py::arg("knots") = py::none(), py::arg("multiplicities") = py::none(), py::arg("weights") = py::none(),
          py::arg("periodic") = false, py::kw_only(), py::arg("construction") = false,
          py::return_value_policy::reference_internal)
      .def(
          "add_constraint",
          [](Sketch& s, const std::string& kind, const std::vector<SketchRef>& targets, const py::object& value,
             std::optional<std::string> constraint_id, bool driving, const py::object& metadata) -> Sketch& {
            std::optional<Scalar> scalar;
            if (!value.is_none())
              scalar = value.cast<Scalar>();
            return s.add_constraint(kind, targets, scalar, constraint_id, driving,
                                    metadata.is_none() ? Value::object() : value_from_python(metadata));
          },
          py::arg("kind"), py::arg("targets"), py::kw_only(), py::arg("value") = py::none(),
          py::arg("constraint_id") = py::none(), py::arg("driving") = true, py::arg("metadata") = py::none(),
          py::return_value_policy::reference_internal)
      .def(
          "solve",
          [](Sketch& s, bool require_fully_constrained, bool strict, double tolerance, int max_iterations,
             const py::object& backend) {
            SketchSolveRequest request = request_of(require_fully_constrained, strict, tolerance, max_iterations);
            request.backend = backend_from_python(backend);
            return s.solve(request);
          },
          py::kw_only(), py::arg("require_fully_constrained") = false, py::arg("strict") = true,
          py::arg("tolerance") = 1e-7, py::arg("max_iterations") = 80, py::arg("backend") = py::none())
      .def("solved_result", [](Sketch& s) { return s.solved_result(); })
      .def(
          "make_wire",
          [](const Sketch& s, const SketchProfileId& profile) { return make_wire_from_sketch_rwire(s, profile); },
          py::arg("profile") = 0)
      .def(
          "make_face",
          [](const Sketch& s, const SketchProfileId& profile, const std::vector<SketchProfileId>& inner) {
            return make_face_from_sketch_rface(s, profile, inner);
          },
          py::arg("profile") = 0, py::kw_only(), py::arg("inner_profiles") = std::vector<SketchProfileId>{})
      .def(
          "get_metadata",
          [](const Sketch& s, const std::string& key, const Value& fallback) {
            const Value* found = s.metadata().find(key);
            return found != nullptr ? *found : fallback;
          },
          py::arg("key"), py::arg("default") = Value())
      .def("set_metadata", [](Sketch& s, const std::string& key, const Value& value) { s.metadata().set(key, value); })
      .def("_set_runtime", [](Sketch& s, const std::string& key, const Value& value) { s.runtime().set(key, value); })
      .def(
          "_get_runtime",
          [](const Sketch& s, const std::string& key, const Value& fallback) {
            const Value* found = s.runtime().find(key);
            return found != nullptr ? *found : fallback;
          },
          py::arg("key"), py::arg("default") = Value())
      .def("__repr__", [](const Sketch& s) {
        return "Sketch(sketch_id='" + s.sketch_id() + "', entities=" + std::to_string(s.entities().size()) +
               ", constraints=" + std::to_string(s.constraints().size()) + ")";
      });
}

void bind_entity_operators(py::module_& m) {
  m.def(
      "make_sketch_rsketch",
      [](const std::optional<std::string>& name, const py::object& plane, const std::optional<std::string>& sketch_id) {
        return make_sketch_rsketch(name, value_from_python(plane), sketch_id);
      },
      py::arg("name") = py::none(), py::kw_only(), py::arg("plane") = "XY", py::arg("sketch_id") = py::none());
  m.def("add_point_rsketch", &add_point_rsketch, py::arg("sketch"), py::arg("point_id"), py::arg("x"), py::arg("y"));
  m.def("get_sketch_entity_rsketchref", &get_sketch_entity_rsketchref, py::arg("sketch"), py::arg("entity_id"));
  m.def("get_sketch_point_rsketchref", &get_sketch_point_rsketchref, py::arg("sketch"), py::arg("point_path"));
  m.def("add_line_rsketch", &add_line_rsketch, py::arg("sketch"), py::arg("entity_id"), py::arg("start"),
        py::arg("end"), py::kw_only(), py::arg("construction") = false);
  m.def("add_circle_rsketch", &add_circle_rsketch, py::arg("sketch"), py::arg("entity_id"), py::arg("center"),
        py::arg("radius"), py::kw_only(), py::arg("construction") = false);
  m.def("add_ellipse_rsketch", &add_ellipse_rsketch, py::arg("sketch"), py::arg("entity_id"), py::arg("center"),
        py::arg("major_point"), py::arg("minor_point"), py::kw_only(), py::arg("construction") = false);
  m.def("add_bspline_rsketch", &add_bspline_rsketch, py::arg("sketch"), py::arg("entity_id"), py::arg("start"),
        py::arg("end"), py::arg("control_points"), py::arg("degree") = 3, py::arg("knots") = py::none(),
        py::arg("multiplicities") = py::none(), py::arg("weights") = py::none(), py::arg("periodic") = false,
        py::kw_only(), py::arg("construction") = false);
  m.def("add_arc_rsketch", &add_arc_rsketch, py::arg("sketch"), py::arg("entity_id"), py::arg("start"), py::arg("end"),
        py::arg("center"), py::kw_only(), py::arg("construction") = false);
}

// (sketch, a, b, *, constraint_id=None)
template <class F>
void def_two(py::module_& m, const char* name, F fn, const char* first = "a", const char* second = "b") {
  m.def(name, fn, py::arg("sketch"), py::arg(first), py::arg(second), py::kw_only(),
        py::arg("constraint_id") = py::none());
}
// (sketch, target, *, constraint_id=None)
template <class F>
void def_one(py::module_& m, const char* name, F fn, const char* target) {
  m.def(name, fn, py::arg("sketch"), py::arg(target), py::kw_only(), py::arg("constraint_id") = py::none());
}
// (sketch, a, b, value, *, constraint_id=None, driving=True)
template <class F>
void def_two_value(py::module_& m, const char* name, F fn) {
  m.def(name, fn, py::arg("sketch"), py::arg("a"), py::arg("b"), py::arg("value"), py::kw_only(),
        py::arg("constraint_id") = py::none(), py::arg("driving") = true);
}
// (sketch, target, value, *, constraint_id=None, driving=True)
template <class F>
void def_one_value(py::module_& m, const char* name, F fn, const char* target) {
  m.def(name, fn, py::arg("sketch"), py::arg(target), py::arg("value"), py::kw_only(),
        py::arg("constraint_id") = py::none(), py::arg("driving") = true);
}

void bind_constraint_operators(py::module_& m) {
  m.def(
      "_constrain_rsketch",
      [](const Sketch& sketch, const std::string& kind, const std::vector<SketchTarget>& targets,
         const std::optional<Scalar>& value, const SketchConstraintId& id, bool driving, const Value& metadata,
         const py::object&) { return constrain_rsketch(sketch, kind, targets, value, id, driving, metadata); },
      py::arg("sketch"), py::arg("kind"), py::arg("targets"), py::kw_only(), py::arg("value") = py::none(),
      py::arg("constraint_id") = py::none(), py::arg("driving") = true, py::arg("metadata") = py::none(),
      py::arg("expected") = py::none(),
      "Any constraint kind by name (graph replay); `expected` is accepted and not used.");
  def_two(m, "constrain_coincident_rsketch", &constrain_coincident_rsketch);
  def_two(m, "constrain_connect_rsketch", &constrain_connect_rsketch);
  def_two(m, "constrain_point_on_rsketch", &constrain_point_on_rsketch, "point", "entity");
  def_one(m, "constrain_horizontal_rsketch", &constrain_horizontal_rsketch, "line");
  def_one(m, "constrain_vertical_rsketch", &constrain_vertical_rsketch, "line");
  def_two(m, "constrain_points_horizontal_rsketch", &constrain_points_horizontal_rsketch);
  def_two(m, "constrain_points_vertical_rsketch", &constrain_points_vertical_rsketch);
  def_two_value(m, "constrain_line_distance_rsketch", &constrain_line_distance_rsketch);
  def_two(m, "constrain_normal_rsketch", &constrain_normal_rsketch);
  m.def("constrain_mirror_rsketch", &constrain_mirror_rsketch, py::arg("sketch"), py::arg("a"), py::arg("axis"),
        py::arg("b"), py::kw_only(), py::arg("constraint_id") = py::none());
  m.def("constrain_midpoint_points_rsketch", &constrain_midpoint_points_rsketch, py::arg("sketch"), py::arg("mid"),
        py::arg("a"), py::arg("b"), py::kw_only(), py::arg("constraint_id") = py::none());
  def_two(m, "constrain_parallel_rsketch", &constrain_parallel_rsketch);
  def_two(m, "constrain_perpendicular_rsketch", &constrain_perpendicular_rsketch);
  def_two(m, "constrain_collinear_rsketch", &constrain_collinear_rsketch);
  m.def("constrain_tangent_rsketch", &constrain_tangent_rsketch, py::arg("sketch"), py::arg("a"), py::arg("b"),
        py::kw_only(), py::arg("at_a") = py::none(), py::arg("at_b") = py::none(), py::arg("mode") = "external",
        py::arg("constraint_id") = py::none());
  def_two(m, "constrain_concentric_rsketch", &constrain_concentric_rsketch);
  def_two(m, "constrain_midpoint_rsketch", &constrain_midpoint_rsketch, "point", "line");
  m.def("constrain_symmetric_rsketch", &constrain_symmetric_rsketch, py::arg("sketch"), py::arg("a"), py::arg("b"),
        py::arg("axis"), py::kw_only(), py::arg("constraint_id") = py::none());
  def_two(m, "constrain_equal_length_rsketch", &constrain_equal_length_rsketch);
  def_two(m, "constrain_equal_radius_rsketch", &constrain_equal_radius_rsketch);
  def_two_value(m, "constrain_distance_rsketch", &constrain_distance_rsketch);
  def_two_value(m, "constrain_distance_x_rsketch", &constrain_distance_x_rsketch);
  def_two_value(m, "constrain_distance_y_rsketch", &constrain_distance_y_rsketch);
  def_one_value(m, "constrain_length_rsketch", &constrain_length_rsketch, "line");
  def_two_value(m, "constrain_angle_rsketch", &constrain_angle_rsketch);
  def_one_value(m, "constrain_radius_rsketch", &constrain_radius_rsketch, "circle");
  def_one_value(m, "constrain_diameter_rsketch", &constrain_diameter_rsketch, "circle");
  def_one_value(m, "constrain_major_radius_rsketch", &constrain_major_radius_rsketch, "ellipse");
  def_one_value(m, "constrain_minor_radius_rsketch", &constrain_minor_radius_rsketch, "ellipse");
  def_one(m, "constrain_fix_rsketch", &constrain_fix_rsketch, "target");
}

void bind_solve_operators(py::module_& m) {
  m.def(
      "inspect_sketch_rsketchresult",
      [](const Sketch& sketch, bool fully, bool strict, double tolerance, int max_iterations) {
        return inspect_sketch_rsketchresult(sketch, request_of(fully, strict, tolerance, max_iterations));
      },
      py::arg("sketch"), py::kw_only(), py::arg("require_fully_constrained") = false, py::arg("strict") = true,
      py::arg("tolerance") = 1e-7, py::arg("max_iterations") = 80);
  m.def(
      "make_wire_from_sketch_rwire",
      [](const Sketch& sketch, const SketchProfileId& profile, bool fully, bool strict, double tolerance,
         int max_iterations) {
        return make_wire_from_sketch_rwire(sketch, profile, request_of(fully, strict, tolerance, max_iterations));
      },
      py::arg("sketch"), py::arg("profile") = 0, py::kw_only(), py::arg("require_fully_constrained") = false,
      py::arg("strict") = true, py::arg("tolerance") = 1e-7, py::arg("max_iterations") = 80);
  m.def(
      "make_face_from_sketch_rface",
      [](const Sketch& sketch, const SketchProfileId& profile, const std::vector<SketchProfileId>& inner, bool fully,
         bool strict, double tolerance, int max_iterations) {
        return make_face_from_sketch_rface(sketch, profile, inner,
                                           request_of(fully, strict, tolerance, max_iterations));
      },
      py::arg("sketch"), py::arg("profile") = 0, py::kw_only(),
      py::arg("inner_profiles") = std::vector<SketchProfileId>{}, py::arg("require_fully_constrained") = false,
      py::arg("strict") = true, py::arg("tolerance") = 1e-7, py::arg("max_iterations") = 80);
}

}  // namespace

void bind_sketch(py::module_& m) {
  bind_data_classes(m);
  bind_backends(m);
  bind_sketch_class(m);
  bind_entity_operators(m);
  bind_constraint_operators(m);
  bind_solve_operators(m);
}
