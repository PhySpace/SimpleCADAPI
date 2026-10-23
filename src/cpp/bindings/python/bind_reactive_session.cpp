// GraphSession (the recording session), the reactive engine's Python face, the
// executor registry, and the recording context managers.
#include "bind_reactive_common.hpp"
#include "py_lifetime.hpp"

#include <mutex>
#include <optional>
#include <unordered_map>
#include <unordered_set>

#include "scad/core/error.hpp"
#include "scad/reactive/node_registry.hpp"
#include "scad/reactive/registry.hpp"
#include "scad/reactive/session.hpp"

namespace scad::pybind::reactive {

namespace sr = scad::reactive;
using sr::NodePtr;
using sr::Session;

namespace {

// ---- Python callables as executors -----------------------------------------

// A py::function that is released with the GIL held, whichever thread drops the last copy.
struct GilSafeFunction {
  py::function fn;
  ~GilSafeFunction() { scad::pybind::drop_python_reference(fn); }
};

sr::Executor wrap_python_executor(py::function fn) {
  auto holder = std::make_shared<GilSafeFunction>(GilSafeFunction{std::move(fn)});
  return [holder](const Value& params, const std::vector<OpInput>& inputs, const sr::ScalarValues& scalars) {
    const py::gil_scoped_acquire gil;
    py::list in;
    for (const OpInput& input : inputs) in.append(py::make_tuple(shape_to_python(input.shape), input.role));
    py::dict values;
    for (const auto& [name, value] : scalars) values[py::str(name)] = value;
    const py::object result = holder->fn(value_to_python(params), in, values);
    std::vector<Shape> out;
    if (result.is_none()) return out;
    if (py::isinstance<Shape>(result)) {
      out.push_back(py::cast<Shape>(result));
    } else {
      for (const auto& item : result) out.push_back(py::cast<Shape>(item));
    }
    return out;
  };
}

// ---- Python parameter structures -> Value + symbolic paths -------------------

Value split_value(const py::handle& value, const std::string& path, sr::SymbolicParams& symbolic) {
  if (py::isinstance<sr::ScalarNode>(value)) {
    const sr::ScalarPtr node = py::cast<sr::ScalarPtr>(value);
    symbolic.emplace_back(path, scad::Scalar(scad::ExprPtr(node)));
    return Value(scad::Scalar(scad::ExprPtr(node)).value());  // honours the session's edits
  }
  if (py::isinstance<py::tuple>(value) || py::isinstance<py::list>(value)) {
    Value out = Value::array();
    std::size_t index = 0;
    for (const auto& item : value) out.push_back(split_value(item, path + "[" + std::to_string(index++) + "]", symbolic));
    return out;
  }
  if (py::isinstance<py::dict>(value)) {
    Value out = Value::object();
    for (const auto& item : py::cast<py::dict>(value)) {
      const std::string key = py::cast<std::string>(py::str(item.first));
      out.set(key, split_value(item.second, path + "." + key, symbolic));
    }
    return out;
  }
  return value_from_python(value);
}

// ---- Shapes inside a captured value -----------------------------------------

void collect_shapes(const py::handle& value, std::vector<Shape>& out, std::unordered_set<PyObject*>& seen) {
  if (value.is_none() || PyUnicode_Check(value.ptr()) || PyBytes_Check(value.ptr()) || PyFloat_Check(value.ptr()) ||
      PyLong_Check(value.ptr())) {
    return;
  }
  if (!seen.insert(value.ptr()).second) return;
  if (py::isinstance<Shape>(value)) {
    out.push_back(py::cast<Shape>(value));
    return;
  }
  if (py::isinstance<py::dict>(value)) {
    for (const auto& item : py::cast<py::dict>(value)) {
      collect_shapes(item.first, out, seen);
      collect_shapes(item.second, out, seen);
    }
  } else if (py::isinstance<py::list>(value) || py::isinstance<py::tuple>(value) || py::isinstance<py::set>(value) ||
             py::isinstance<py::frozenset>(value)) {
    for (const auto& item : value) collect_shapes(item, out, seen);
  } else {
    const py::module_ dataclasses = py::module_::import("dataclasses");
    if (py::cast<bool>(dataclasses.attr("is_dataclass")(value)) && !PyType_Check(value.ptr())) {
      for (const auto& field : dataclasses.attr("fields")(value)) {
        const std::string name = py::cast<std::string>(field.attr("name"));
        if (name.rfind('_', 0) == 0) continue;
        collect_shapes(py::getattr(value, name.c_str()), out, seen);
      }
    }
  }
}

std::vector<Shape> shapes_in(const py::handle& value) {
  std::vector<Shape> shapes;
  std::unordered_set<PyObject*> seen;
  collect_shapes(value, shapes, seen);
  return shapes;
}

// ---- The session ------------------------------------------------------------

struct PySession;

std::mutex g_sessions_mutex;
std::unordered_map<const Session*, PySession*>& sessions() {
  static std::unordered_map<const Session*, PySession*> table;
  return table;
}

// The session and the Python values captured with it; findable from the Session pointer
// (get_active_session returns the very Python object).
struct PySession {
  Session session;
  std::vector<py::object> captured_values;

  explicit PySession(Session::Options options) : session(std::move(options)) {
    const std::lock_guard lock(g_sessions_mutex);
    sessions()[&session] = this;
  }
  ~PySession() {
    const std::lock_guard lock(g_sessions_mutex);
    sessions().erase(&session);
  }
  PySession(const PySession&) = delete;
  PySession& operator=(const PySession&) = delete;
};

PySession* python_session_of(const Session* session) {
  const std::lock_guard lock(g_sessions_mutex);
  const auto found = sessions().find(session);
  return found == sessions().end() ? nullptr : found->second;
}

struct PyFailure {
  std::string node_id, op, message;
};

struct PyReport {
  std::vector<std::string> executed, memoized, unchanged, blocked, changed;
  std::vector<PyFailure> failed;
  bool ok = true;
};

PyReport to_report(const sr::RecomputeReport& report) {
  PyReport out;
  out.executed = report.executed;
  out.memoized = report.memoized;
  out.unchanged = report.unchanged;
  out.blocked = report.blocked;
  out.changed = report.changed;
  for (const sr::NodeFailure& f : report.failed) out.failed.push_back(PyFailure{f.node_id, f.op, f.message});
  out.ok = report.ok();
  return out;
}

struct PySuspend {
  std::optional<RecorderSuspend> inner;
};

struct PyIsolated {
  std::optional<sr::IsolatedRecording> inner;
};

}  // namespace

void bind_reactive_session(py::module_& m) {
  py::class_<PyFailure>(m, "NodeFailure")
      .def_readonly("node_id", &PyFailure::node_id)
      .def_readonly("op", &PyFailure::op)
      .def_readonly("message", &PyFailure::message)
      .def("__repr__", [](const PyFailure& f) { return "NodeFailure(node_id='" + f.node_id + "', op='" + f.op + "')"; });
  py::class_<PyReport>(m, "RecomputeReport")
      .def_readonly("executed", &PyReport::executed)
      .def_readonly("memoized", &PyReport::memoized)
      .def_readonly("unchanged", &PyReport::unchanged)
      .def_readonly("blocked", &PyReport::blocked)
      .def_readonly("changed", &PyReport::changed)
      .def_readonly("failed", &PyReport::failed)
      .def_readonly("ok", &PyReport::ok)
      .def("__repr__", [](const PyReport& r) {
        return "RecomputeReport(executed=" + std::to_string(r.executed.size()) + ", memoized=" +
               std::to_string(r.memoized.size()) + ", unchanged=" + std::to_string(r.unchanged.size()) + ", blocked=" +
               std::to_string(r.blocked.size()) + ", failed=" + std::to_string(r.failed.size()) + ")";
      });

  py::class_<sr::ExecutorRegistry>(m, "ExecutorRegistry")
      .def(py::init<bool>(), py::arg("builtins") = true)
      .def("add", [](sr::ExecutorRegistry& r, const std::string& op, const py::function& fn) {
        r.add(op, wrap_python_executor(fn));
      }, py::arg("op"), py::arg("executor"),
           "Register fn(params, inputs, scalars) -> outputs for an operation name.")
      .def("replace", [](sr::ExecutorRegistry& r, const std::string& op, const py::function& fn) {
        r.replace(op, wrap_python_executor(fn));
      }, py::arg("op"), py::arg("executor"))
      .def("remove", &sr::ExecutorRegistry::remove, py::arg("op"))
      .def("contains", &sr::ExecutorRegistry::contains, py::arg("op"))
      .def("operations", &sr::ExecutorRegistry::operations);
  m.def("global_executor_registry", []() -> sr::ExecutorRegistry& { return sr::ExecutorRegistry::global(); },
        py::return_value_policy::reference);
  m.def("register_executor", [](const std::string& op, const py::function& fn) {
    sr::register_executor(op, wrap_python_executor(fn));
  }, py::arg("op"), py::arg("executor"));

  py::class_<PySession>(m, "GraphSession", py::dynamic_attr())
      .def(py::init([](const py::object& graph_id, bool allow_external_definitions, const py::object& ns, bool shared_lineage,
                       bool attach_topology_refs, std::size_t memo_capacity, sr::ExecutorRegistry* registry,
                       const py::object& source_provider) {
             // allow_external_definitions is a policy of the Python layer that records Part / Assembly
             // values (simplecadapi._glue.session); the engine has nothing to do for it.
             static_cast<void>(allow_external_definitions);
             Session::Options options;
             options.shared_lineage = shared_lineage;
             if (!source_provider.is_none()) {
               auto holder = std::make_shared<GilSafeFunction>(GilSafeFunction{py::reinterpret_borrow<py::function>(source_provider)});
               options.source_provider = [holder]() -> std::optional<Value> {
                 const py::gil_scoped_acquire gil;
                 const py::object found = holder->fn();
                 if (found.is_none()) return std::nullopt;
                 return value_from_python(found);
               };
             }
             if (!graph_id.is_none()) options.graph_id = py::cast<std::string>(graph_id);
             if (!ns.is_none()) options.ns = py::cast<std::string>(ns);
             options.attach_topology_refs = attach_topology_refs;
             options.memo_capacity = memo_capacity;
             options.registry = registry;
             return std::make_unique<PySession>(std::move(options));
           }),
           py::arg("graph_id") = py::none(), py::kw_only(), py::arg("allow_external_definitions") = false,
           py::arg("namespace") = py::none(), py::arg("shared_lineage") = false, py::arg("attach_topology_refs") = false,
           py::arg("memo_capacity") = 128, py::arg("registry") = nullptr, py::arg("source_provider") = py::none(),
           py::keep_alive<1, 8>())
      // ---- GraphSession ----
      .def_property_readonly("graph", [](PySession& s) -> const sr::OperationGraph& { return s.session.graph(); },
                             py::return_value_policy::reference_internal)
      .def_property_readonly("expression_graph", [](PySession& s) -> sr::ExpressionGraph& { return s.session.expression_graph(); },
                             py::return_value_policy::reference_internal)
      .def_property_readonly("frame_graph", [](PySession& s) -> sr::FrameGraph& { return s.session.frame_graph(); },
                             py::return_value_policy::reference_internal)
      .def_property_readonly("registry", [](PySession& s) -> sr::ExecutorRegistry& { return s.session.registry(); },
                             py::return_value_policy::reference_internal)
      .def("start", [](PySession& s) { s.session.start(); })
      .def("stop", [](PySession& s) { s.session.stop(); })
      .def("__enter__", [](py::object self) {
        py::cast<PySession&>(self).session.start();
        return self;
      })
      .def("__exit__", [](PySession& s, const py::object&, const py::object&, const py::object&) { s.session.stop(); })
      .def("allocate_object_id", [](PySession& s, const std::string& prefix) { return s.session.allocate_object_id(prefix); },
           py::arg("prefix"))
      .def_property_readonly("result_node_ids", [](const PySession& s) { return py::tuple(py::cast(s.session.result_node_ids())); })
      .def_property_readonly("has_explicit_results", [](const PySession& s) { return s.session.has_explicit_results(); })
      .def_property_readonly("captured_values", [](const PySession& s) { return py::tuple(py::cast(s.captured_values)); })
      .def("capture_result", [](PySession& s, const py::object& value) {
        s.session.capture_result(shapes_in(value));
        s.captured_values.push_back(value);
        return value;
      }, py::kw_only(), py::arg("value"))
      .def("clear_results", [](PySession& s) {
        s.session.clear_results();
        s.captured_values.clear();
      })
      .def_property_readonly("last_node", [](const PySession& s) -> py::object {
        return s.session.last_node() ? py::cast(s.session.last_node()) : py::object(py::none());
      })
      .def_property_readonly("shared_lineage", [](const PySession& s) { return s.session.shared_lineage(); })
      .def("_expect_value_op", [](PySession& s, const py::object& inputs, bool value_output) {
        std::vector<NodePtr> nodes;
        if (!inputs.is_none()) {
          for (const auto& item : inputs) nodes.push_back(py::cast<NodePtr>(item));
        }
        s.session.expect_value_op(std::move(nodes), value_output);
      }, py::arg("inputs") = py::none(), py::arg("value_output") = true,
           "The next recorded operation also takes these nodes as inputs and (value_output) has one output.")
      .def("_clear_value_op", [](PySession& s) { s.session.clear_value_op(); })
      .def("validate_graph_ownership", [](const PySession& s, const py::object& value) {
        for (const Shape& shape : shapes_in(value)) s.session.validate_graph_ownership(shape);
      }, py::arg("value"))
      // ---- recording from Python ----
      .def("record", [](PySession& s, const std::string& op, const py::object& params, const py::object& inputs,
                        const py::object& outputs) -> NodePtr {
             OpRecord record;
             record.op = op;
             record.params = Value::object();
             if (!params.is_none()) {
               for (const auto& item : py::cast<py::dict>(params)) {
                 const std::string key = py::cast<std::string>(py::str(item.first));
                 record.params.set(key, split_value(item.second, key, record.symbolic));
               }
             }
             if (!inputs.is_none()) {
               for (const auto& item : inputs) {
                 if (py::isinstance<py::tuple>(item) && py::len(item) == 2) {
                   record.inputs.push_back(OpInput{py::cast<Shape>(item.cast<py::tuple>()[0]), py::cast<std::string>(item.cast<py::tuple>()[1])});
                 } else {
                   record.inputs.push_back(OpInput{py::cast<Shape>(item), "input"});
                 }
               }
             }
             std::vector<Shape> shapes;
             if (!outputs.is_none()) {
               if (py::isinstance<Shape>(outputs)) {
                 shapes.push_back(py::cast<Shape>(outputs));
               } else {
                 for (const auto& item : outputs) shapes.push_back(py::cast<Shape>(item));
               }
             }
             return s.session.record_node(record, shapes);
           },
           py::arg("op"), py::arg("params") = py::none(), py::kw_only(), py::arg("inputs") = py::none(),
           py::arg("outputs") = py::none(),
           "Record an operation: params may hold Var / Expr values (the symbolic ones make the node reactive); "
           "inputs are shapes or (shape, role); outputs are the shapes it produced.")
      // ---- variables ----
      .def_property_readonly("vars", [](const PySession& s) {
        py::tuple out(s.session.vars().size());
        for (std::size_t i = 0; i < s.session.vars().size(); ++i) out[i] = py::cast(s.session.vars()[i]);
        return out;
      })
      .def("declare_var", [](PySession& s, const py::object& var) {
        if (!py::isinstance<sr::Var>(var)) throw scad::TypeError("declare_var needs a Var");
        s.session.declare_var(py::cast<std::shared_ptr<const sr::Var>>(var));
      }, py::arg("var"))
      .def("has_var", [](const PySession& s, const std::string& name) { return s.session.has_var(name); }, py::arg("name"))
      .def("parameters", [](const PySession& s) {
        py::list out;
        for (const sr::ParamSpec& spec : s.session.parameters()) out.append(value_to_python(spec.to_value()));
        return out;
      })
      .def("var_value", [](const PySession& s, const std::string& name) { return s.session.var_value(name); }, py::arg("name"))
      .def_property_readonly("bindings", [](const PySession& s) {
        py::dict out;
        for (const auto& [name, value] : s.session.bindings()) out[py::str(name)] = value;
        return out;
      })
      .def("set_var", [](PySession& s, const std::string& name, const py::object& value) {
        s.session.set_var(name, finite_real(value, "Binding '" + name + "'"));
      }, py::arg("name"), py::arg("value"))
      .def("set_vars", [](PySession& s, const py::dict& values) {
        std::vector<std::pair<std::string, double>> list;
        for (const auto& item : values) {
          const std::string name = py::cast<std::string>(item.first);
          list.emplace_back(name, finite_real(item.second, "Binding '" + name + "'"));
        }
        s.session.set_vars(list);
      }, py::arg("values"))
      .def("reset_var", [](PySession& s, const std::string& name) { s.session.reset_var(name); }, py::arg("name"))
      .def("reset_vars", [](PySession& s) { s.session.reset_vars(); })
      // ---- impact ----
      .def("nodes_using", [](const PySession& s, const std::string& name) { return s.session.nodes_using(name); }, py::arg("var_name"))
      .def("affected_nodes", [](const PySession& s, const py::object& names) {
        if (py::isinstance<py::str>(names)) return s.session.affected_nodes(py::cast<std::string>(names));
        return s.session.affected_nodes(py::cast<std::vector<std::string>>(names));
      }, py::arg("var_names"))
      .def("vars_affecting", [](const PySession& s, const std::string& id) { return s.session.vars_affecting(id); }, py::arg("node_id"))
      // ---- recomputation ----
      .def("status", [](const PySession& s, const std::string& id) { return std::string(sr::to_string(s.session.status(id))); }, py::arg("node_id"))
      .def("dirty_nodes", [](const PySession& s) { return s.session.dirty_nodes(); })
      .def("failure", [](const PySession& s, const std::string& id) -> py::object {
        const std::exception_ptr error = s.session.failure(id);
        if (!error) return py::none();
        try {
          std::rethrow_exception(error);
        } catch (const std::exception& e) {
          return py::str(e.what());
        }
      }, py::arg("node_id"))
      .def("recompute", [](PySession& s, bool throw_on_error) {
        return to_report(s.session.recompute(sr::RecomputeOptions{throw_on_error}));
      }, py::kw_only(), py::arg("throw_on_error") = false)
      .def("outputs", [](const PySession& s, const std::string& id) {
        py::list out;
        for (const Shape& shape : s.session.outputs(id)) out.append(shape_to_python(shape));
        return out;
      }, py::arg("node_id"))
      .def("output", [](const PySession& s, const std::string& id, int slot) { return shape_to_python(s.session.output(id, slot)); },
           py::arg("node_id"), py::arg("slot") = 0)
      .def("current", [](const PySession& s, const py::object& shape) { return shape_to_python(s.session.current(py::cast<Shape>(shape))); },
           py::arg("shape"))
      .def("captured_shapes", [](const PySession& s) {
        py::list out;
        for (const Shape& shape : s.session.captured_shapes()) out.append(shape_to_python(shape));
        return out;
      })
      .def_property_readonly("memo_size", [](const PySession& s) { return s.session.memo_size(); });

  m.def("find_registered_node", [](const std::string& graph_id, const std::string& node_id) -> py::object {
    const NodePtr node = sr::find_registered_node(graph_id, node_id);
    return node ? py::cast(node) : py::object(py::none());
  }, py::arg("graph_id"), py::arg("node_id"),
        "The node a shared-lineage session recorded (or that register_graph_nodes added), by graph and node id.");
  m.def("register_graph_nodes", [](const sr::OperationGraph& graph) {
    for (const NodePtr& node : graph.nodes()) sr::register_node(node);
  }, py::arg("graph"), "Make the nodes of a restored graph findable by shared-lineage sessions.");
  m.def("recording_active", []() {
    Session* active = Session::active_session();
    return active != nullptr && current_recorder() == active;
  }, "Whether a session is active and not suspended (an operation would be recorded).");
  m.def("register_node", [](const NodePtr& node) { sr::register_node(node); }, py::arg("node"),
        "Make one node findable by shared-lineage sessions.");
  m.def("forget_graph_nodes", [](const std::string& graph_id) { sr::forget_graph_nodes(graph_id); }, py::arg("graph_id"));

  m.def("get_active_session", []() -> py::object {
    PySession* owner = python_session_of(Session::active_session());
    return owner != nullptr ? py::cast(owner, py::return_value_policy::reference) : py::none().cast<py::object>();
  });

  py::class_<PySuspend>(m, "_SuspendGraphRecording")
      .def("__enter__", [](py::object self) {
        py::cast<PySuspend&>(self).inner.emplace();
        return self;
      })
      .def("__exit__", [](PySuspend& s, const py::object&, const py::object&, const py::object&) { s.inner.reset(); });
  m.def("suspend_graph_recording", []() { return std::make_unique<PySuspend>(); },
        "Temporarily suspend automatic graph recording for internal API composition.");

  py::class_<PyIsolated>(m, "_IsolatedRecording")
      .def("__enter__", [](py::object self) {
        py::cast<PyIsolated&>(self).inner.emplace();
        return self;
      })
      .def("__exit__", [](PyIsolated& s, const py::object&, const py::object&, const py::object&) { s.inner.reset(); });
  m.def("isolated_recording", []() { return std::make_unique<PyIsolated>(); },
        "Run a nested definition build as if it were called at top level.");

  m.def("record_operation_if_active", [](const std::string& op, const py::object& params, const py::object& outputs,
                                         const py::object& input_shapes) -> py::object {
    Session* session = Session::active_session();
    if (session == nullptr || current_recorder() != session) return py::none();
    PySession* owner = python_session_of(session);
    if (owner == nullptr) return py::none();
    const py::object self = py::cast(owner, py::return_value_policy::reference);
    return self.attr("record")(op, params, py::arg("inputs") = input_shapes, py::arg("outputs") = outputs);
  }, py::arg("op"), py::arg("params") = py::none(), py::arg("outputs") = py::none(), py::arg("input_shapes") = py::none(),
        "Record an operation only when a session is active; returns the node or None.");
}

}  // namespace scad::pybind::reactive
