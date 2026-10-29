// OperationNode, OperationGraph, FrameNode/FrameGraph, upstream_closure.
#include "bind_reactive_common.hpp"

#include <algorithm>
#include <memory>
#include <mutex>
#include <unordered_map>

#include <pybind11/eval.h>

#include "scad/core/error.hpp"
#include "scad/reactive/errors.hpp"
#include "scad/reactive/frame.hpp"
#include "scad/reactive/graph.hpp"

namespace scad::pybind::reactive {

namespace sr = scad::reactive;
using sr::FrameGraph;
using sr::FrameNode;
using sr::NodePtr;
using sr::OperationGraph;
using sr::OperationNode;

namespace {

// Nodes restored from pickles, by (graph_id, node_id): marimo pickles every cell variable separately; two
// variables that shared a node before pickling share one node after loading.  Weak, so a node nobody holds goes.
NodePtr share_restored(const NodePtr& node) {
  static std::mutex mutex;
  static std::unordered_map<std::string, std::weak_ptr<const OperationNode>> restored;
  const std::string key = node->graph_id + '\x1f' + node->node_id;
  const std::lock_guard<std::mutex> lock(mutex);
  if (restored.size() > 4096) {  // drop what has gone
    for (auto it = restored.begin(); it != restored.end();)
      it = it->second.expired() ? restored.erase(it) : std::next(it);
  }
  if (const auto found = restored.find(key); found != restored.end()) {
    if (const NodePtr existing = found->second.lock()) {
      // A twin must hold the very same input objects: an input that was replaced by a newer version makes
      // every node downstream of it a new version too.
      const bool same_inputs = existing->inputs.size() == node->inputs.size() &&
                               std::equal(existing->inputs.begin(), existing->inputs.end(), node->inputs.begin());
      if (same_inputs && sr::same_node_content(*existing, *node))
        return existing;
    }
  }
  restored[key] = node;
  return node;
}

const char* kStaleSource = R"PY(
class StaleLineageError(ValueError):
    """Two different operations carry the same node id."""

    def __init__(self, node_id):
        super().__init__(
            f"node '{node_id}' exists in two different versions (stale lineage); "
            "re-run the cells that produced these values"
        )
        self.node_id = node_id
)PY";

py::tuple vec_tuple(const scad::Vec3& v) {
  return py::make_tuple(v.x, v.y, v.z);
}

NodePtr node_from(const py::handle& value) {
  if (!py::isinstance<OperationNode>(value))
    throw scad::TypeError("expected an OperationNode");
  return py::cast<NodePtr>(value);
}

std::vector<NodePtr> nodes_from(const py::object& items) {
  std::vector<NodePtr> out;
  if (items.is_none())
    return out;
  for (const auto& item : items)
    out.push_back(node_from(item));
  return out;
}

Value value_or_empty(const py::object& obj) {
  return obj.is_none() ? Value::object() : value_from_python(obj);
}

sr::FrameNode frame_from(const py::object& obj) {
  return py::cast<FrameNode>(obj);
}

}  // namespace

void bind_reactive_graph(py::module_& m) {
  py::dict scope;
  py::exec(kStaleSource, scope);
  m.attr("StaleLineageError") = scope["StaleLineageError"];
  py::register_exception_translator([](std::exception_ptr p) {
    try {
      if (p)
        std::rethrow_exception(p);
    } catch (const sr::StaleLineageError& e) {
      py::object cls = py::module_::import("simplecadapi._cpp._native").attr("StaleLineageError");
      PyErr_SetObject(cls.ptr(), cls(e.node_id()).ptr());
    }
  });

  py::class_<FrameNode>(m, "FrameNode")
      .def(py::init([](const std::string& frame_id, const scad::Vec3& origin, const scad::Vec3& x_axis,
                       const scad::Vec3& y_axis, const scad::Vec3& z_axis, const py::object& parent,
                       const py::object& metadata) {
             FrameNode node{frame_id, origin, x_axis, y_axis, z_axis, std::nullopt, value_or_empty(metadata)};
             if (!parent.is_none())
               node.parent_frame_id = py::cast<std::string>(parent);
             return node;
           }),
           py::arg("frame_id"), py::arg("origin"), py::arg("x_axis"), py::arg("y_axis"), py::arg("z_axis"),
           py::arg("parent_frame_id") = py::none(), py::arg("metadata") = py::none())
      .def_readonly("frame_id", &FrameNode::frame_id)
      .def_property_readonly("origin", [](const FrameNode& f) { return vec_tuple(f.origin); })
      .def_property_readonly("x_axis", [](const FrameNode& f) { return vec_tuple(f.x_axis); })
      .def_property_readonly("y_axis", [](const FrameNode& f) { return vec_tuple(f.y_axis); })
      .def_property_readonly("z_axis", [](const FrameNode& f) { return vec_tuple(f.z_axis); })
      .def_property_readonly("parent_frame_id",
                             [](const FrameNode& f) -> py::object {
                               return f.parent_frame_id ? py::object(py::str(*f.parent_frame_id)) : py::none();
                             })
      .def_property_readonly("metadata", [](const FrameNode& f) { return value_to_python(f.metadata); })
      .def("__eq__", [](const FrameNode& a, const py::object& b) {
        return py::isinstance<FrameNode>(b) && a == py::cast<FrameNode>(b);
      });

  py::class_<FrameGraph>(m, "FrameGraph")
      .def(py::init<>())
      .def_property_readonly("node_count", &FrameGraph::node_count)
      .def(
          "add",
          [](FrameGraph& g, const py::object& node) {
            g.add(frame_from(node));
            return node;  // the node that was passed, like the Python SDK
          },
          py::arg("node"))
      .def(
          "ensure_frame",
          [](FrameGraph& g, const std::string& id, const scad::Vec3& origin, const scad::Vec3& x_axis,
             const scad::Vec3& y_axis, const scad::Vec3& z_axis, const py::object& parent, const py::object& metadata) {
            return g.ensure_frame(
                id, origin, x_axis, y_axis, z_axis,
                parent.is_none() ? std::nullopt : std::optional<std::string>(py::cast<std::string>(parent)),
                value_or_empty(metadata));
          },
          py::arg("frame_id"), py::kw_only(), py::arg("origin"), py::arg("x_axis"), py::arg("y_axis"),
          py::arg("z_axis"), py::arg("parent_frame_id") = py::none(), py::arg("metadata") = py::none())
      .def("to_dict",
           [](const FrameGraph& g) {
             py::object data = value_to_python(g.to_value());
             // Each frame's vectors are tuples of floats, as the SDK's FrameNode holds them.
             if (data.contains("nodes"))
               for (const py::handle node : data["nodes"])
                 for (const char* key : {"origin", "x_axis", "y_axis", "z_axis"})
                   if (node.contains(key) && py::isinstance<py::list>(node[key]))
                     node[key] = py::tuple(node[key]);
             return data;
           })
      .def_static("from_dict", [](const py::object& data) { return FrameGraph::from_value(value_from_python(data)); });

  py::class_<OperationNode, py::smart_holder>(m, "OperationNode")
      // A node outside any graph (pickle restore, tests): the fields of the SDK's OperationNode dataclass, in its
      // order.
      .def(py::init([](const std::string& node_id, const std::string& op, const py::object& params,
                       const py::object& param_exprs, const py::object& inputs, const py::object& context,
                       int output_count, const py::object& semantic_delta, const py::object& topo_delta,
                       const py::object& tags, const py::object& graph_id, const py::object& source,
                       const py::object& expressions, const py::object& frame) {
             auto node = std::make_shared<OperationNode>();
             node->node_id = node_id;
             node->op = op;
             node->params = value_or_empty(params);
             node->param_exprs = value_or_empty(param_exprs);
             node->inputs = nodes_from(inputs);
             for (const NodePtr& input : node->inputs)
               node->bindings.push_back(sr::InputBinding{input->node_id, 0, {}});
             if (!context.is_none())
               node->context = value_from_python(context);
             node->output_count = output_count;
             if (!semantic_delta.is_none())
               node->semantic_delta = py::cast<scad::SemanticDelta>(semantic_delta);
             if (!topo_delta.is_none())
               node->topo_delta = scad::topo_delta_from_value(value_from_python(topo_delta));
             if (!tags.is_none())
               for (const auto& tag : tags)
                 node->tags.insert(py::cast<std::string>(tag));
             if (!graph_id.is_none())
               node->graph_id = py::cast<std::string>(graph_id);
             if (!source.is_none())
               node->source = value_from_python(source);
             if (!expressions.is_none())
               for (const auto& e : expressions)
                 node->expressions.push_back(lift(e));
             if (!frame.is_none())
               node->frame = frame_from(frame);
             return std::shared_ptr<const OperationNode>(std::move(node));
           }),
           py::arg("node_id"), py::arg("op"), py::arg("params") = py::none(), py::arg("param_exprs") = py::none(),
           py::arg("inputs") = py::none(), py::arg("context") = py::none(), py::arg("output_count") = 1,
           py::arg("semantic_delta") = py::none(), py::arg("topo_delta") = py::none(), py::arg("tags") = py::none(),
           py::arg("graph_id") = py::none(), py::arg("source") = py::none(), py::arg("expressions") = py::none(),
           py::arg("frame") = py::none())
      .def_property_readonly("node_id", [](const OperationNode& n) { return n.node_id; })
      .def_property_readonly("op", [](const OperationNode& n) { return n.op; })
      .def_property_readonly("params", [](const OperationNode& n) { return value_to_python(n.params); })
      .def_property_readonly("param_exprs", [](const OperationNode& n) { return value_to_python(n.param_exprs); })
      .def_property_readonly("inputs",
                             [](const OperationNode& n) {
                               py::tuple out(n.inputs.size());
                               for (std::size_t i = 0; i < n.inputs.size(); ++i)
                                 out[i] = py::cast(n.inputs[i]);
                               return out;
                             })
      .def_property_readonly(
          "input_bindings",
          [](const OperationNode& n) {
            py::list out;
            for (const sr::InputBinding& b : n.bindings)
              out.append(py::make_tuple(b.external() ? py::object(py::none()) : py::object(py::str(b.node_id)),
                                        b.output_slot, b.role));
            return out;
          })
      .def_property_readonly("context",
                             [](const OperationNode& n) -> py::object {
                               if (!n.context)
                                 return py::none();
                               py::object context = value_to_python(*n.context);
                               // The SDK's context snapshot holds each frame axis as a tuple of floats.
                               if (py::isinstance<py::dict>(context)) {
                                 for (const char* key : {"origin", "x_axis", "y_axis", "z_axis"}) {
                                   if (context.contains(key) && py::isinstance<py::list>(context[key]))
                                     context[key] = py::tuple(context[key]);
                                 }
                               }
                               return context;
                             })
      .def_property_readonly("output_count", [](const OperationNode& n) { return n.output_count; })
      .def_property_readonly("topo_delta",
                             [](const OperationNode& n) -> py::object {
                               return n.topo_delta ? value_to_python(scad::to_value(*n.topo_delta)) : py::none();
                             })
      .def_property_readonly("semantic_delta",
                             [](const OperationNode& n) -> py::object {
                               return n.semantic_delta ? py::cast(*n.semantic_delta) : py::none().cast<py::object>();
                             })
      .def_property_readonly("tags", [](const OperationNode& n) { return py::frozenset(py::cast(n.tags)); })
      .def_property_readonly("graph_id", [](const OperationNode& n) { return n.graph_id; })
      .def_property_readonly(
          "source",
          [](const OperationNode& n) { return n.source ? value_to_python(*n.source) : py::none().cast<py::object>(); })
      .def_property_readonly("expressions",
                             [](const OperationNode& n) {
                               py::tuple out(n.expressions.size());
                               for (std::size_t i = 0; i < n.expressions.size(); ++i)
                                 out[i] = py::cast(n.expressions[i]);
                               return out;
                             })
      .def_property_readonly("symbolic",
                             [](const OperationNode& n) {
                               py::dict out;
                               for (const auto& [path, scalar] : n.symbolic)
                                 out[py::str(path)] = py::cast(scalar);
                               return out;
                             })
      .def_property_readonly(
          "frame", [](const OperationNode& n) -> py::object { return n.frame ? py::cast(*n.frame) : py::none(); })
      .def("__eq__",
           [](const OperationNode& a, const py::object& b) {
             return py::isinstance<OperationNode>(b) && sr::same_node_content(a, *py::cast<NodePtr>(b));
           })
      .def_static(
          "_share_restored", [](const py::object& node) { return share_restored(node_from(node)); }, py::arg("node"),
          "The live node restored from a pickle that is the twin of `node`, or `node` itself, registered as one.")
      .def("__hash__", [](const OperationNode& n) { return std::hash<std::string>{}(n.node_id); })
      .def("__repr__",
           [](const OperationNode& n) { return "OperationNode(node_id='" + n.node_id + "', op='" + n.op + "')"; });

  py::class_<OperationGraph>(m, "OperationGraph")
      .def(py::init([](const py::object& graph_id, const py::object& ns) {
             return OperationGraph(graph_id.is_none() ? std::string{} : py::cast<std::string>(graph_id),
                                   ns.is_none() ? std::nullopt : std::optional<std::string>(py::cast<std::string>(ns)));
           }),
           py::arg("graph_id") = py::none(), py::kw_only(), py::arg("namespace") = py::none())
      .def_property_readonly("graph_id", &OperationGraph::graph_id)
      .def_property_readonly(
          "namespace",
          [](const OperationGraph& g) -> py::object { return g.ns() ? py::object(py::str(*g.ns())) : py::none(); })
      .def("namespaced", &OperationGraph::namespaced, py::arg("prefix"))
      .def("allocate_node_id", &OperationGraph::allocate_node_id, py::arg("prefix") = "node")
      .def(
          "add_node",
          [](OperationGraph& g, const std::string& op, const py::object& params, const py::object& param_exprs,
             const py::object& inputs, const py::object& node_id, int output_count, const py::object& context,
             const py::object& tags, const py::object& source, const py::object& expressions, const py::object& frame,
             const py::object& semantic_delta) {
            sr::NodeSpec spec;
            spec.op = op;
            spec.params = value_or_empty(params);
            spec.param_exprs = value_or_empty(param_exprs);
            spec.inputs = nodes_from(inputs);
            for (const NodePtr& input : spec.inputs)
              spec.bindings.push_back(sr::InputBinding{input->node_id, 0, {}});
            if (!node_id.is_none())
              spec.node_id = py::cast<std::string>(node_id);
            spec.output_count = output_count;
            if (!context.is_none())
              spec.context = value_from_python(context);
            if (!tags.is_none()) {
              for (const auto& tag : tags)
                spec.tags.insert(py::cast<std::string>(tag));
            }
            if (!source.is_none())
              spec.source = value_from_python(source);
            if (!expressions.is_none()) {
              for (const auto& e : expressions)
                spec.expressions.push_back(lift(e));
            }
            if (!frame.is_none())
              spec.frame = frame_from(frame);
            if (!semantic_delta.is_none())
              spec.semantic_delta = py::cast<scad::SemanticDelta>(semantic_delta);
            return g.add_node(std::move(spec));
          },
          py::arg("op"), py::arg("params") = py::none(), py::arg("param_exprs") = py::none(),
          py::arg("inputs") = py::none(), py::arg("node_id") = py::none(), py::arg("output_count") = 1,
          py::arg("context") = py::none(), py::arg("tags") = py::none(), py::arg("source") = py::none(),
          py::arg("expressions") = py::none(), py::arg("frame") = py::none(), py::arg("semantic_delta") = py::none())
      .def(
          "adopt", [](OperationGraph& g, const py::object& node) { return g.adopt(node_from(node)); }, py::arg("node"))
      .def(
          "get_node",
          [](const OperationGraph& g, const std::string& id) -> py::object {
            const NodePtr node = g.get_node(id);
            return node ? py::cast(node) : py::none();
          },
          py::arg("node_id"))
      .def_property_readonly("nodes", [](const OperationGraph& g) { return py::cast(g.nodes()); })
      .def_property_readonly("node_count", &OperationGraph::node_count)
      .def_property_readonly("edges", [](const OperationGraph& g) { return py::set(py::cast(g.edges())); })
      .def_property_readonly("edge_count", &OperationGraph::edge_count)
      .def("upstream_nodes", &OperationGraph::upstream_nodes, py::arg("node_id"))
      .def("downstream_nodes", &OperationGraph::downstream_nodes, py::arg("node_id"))
      .def("root_nodes", &OperationGraph::root_nodes)
      .def("leaf_nodes", &OperationGraph::leaf_nodes)
      .def("is_dag", &OperationGraph::is_dag)
      .def("topological_order", &OperationGraph::topological_order)
      .def("to_dict", [](const OperationGraph& g) { return value_to_python(g.to_value()); })
      .def("to_json", &OperationGraph::to_json, py::arg("indent") = 2)
      .def_static(
          "from_dict",
          [](const py::object& data, bool strict, const py::object& expression_graph, const py::object& frame_graph) {
            const sr::ExpressionGraph* expressions =
                expression_graph.is_none() ? nullptr : &py::cast<const sr::ExpressionGraph&>(expression_graph);
            const sr::FrameGraph* frames =
                frame_graph.is_none() ? nullptr : &py::cast<const sr::FrameGraph&>(frame_graph);
            return OperationGraph::from_value(value_from_python(data), strict, expressions, frames);
          },
          py::arg("data"), py::kw_only(), py::arg("strict") = true, py::arg("expression_graph") = py::none(),
          py::arg("frame_graph") = py::none())
      .def_static(
          "from_json",
          [](const std::string& text, bool strict) {
            return OperationGraph::from_value(value_from_python(py::module_::import("json").attr("loads")(text)),
                                              strict);
          },
          py::arg("json_str"), py::kw_only(), py::arg("strict") = true);

  m.def(
      "set_producer_version", [](const std::string& version) { scad::reactive::set_producer_version(version); },
      py::arg("version"));
  m.def(
      "upstream_closure",
      [](const py::object& roots, const py::object& stop_at) {
        std::function<bool(const NodePtr&)> stop;
        if (!stop_at.is_none())
          stop = [stop_at](const NodePtr& node) { return py::cast<bool>(stop_at(py::cast(node))); };
        return sr::upstream_closure(nodes_from(roots), stop);
      },
      py::arg("roots"), py::kw_only(), py::arg("stop_at") = py::none());
  m.def(
      "same_node_content",
      [](const py::object& a, const py::object& b) { return sr::same_node_content(*node_from(a), *node_from(b)); },
      py::arg("first"), py::arg("second"));
}

}  // namespace scad::pybind::reactive
