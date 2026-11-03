// Element references resolved through recorded history (scad/reactive/element_ref.hpp): a private spike API.
#include <algorithm>
#include <cctype>

#include "bind_reactive_common.hpp"
#include "scad/core/error.hpp"
#include "scad/reactive/element_ref.hpp"

namespace scad::pybind::reactive {

namespace sr = scad::reactive;

namespace {

Kind kind_from_text(std::string name) {
  std::transform(name.begin(), name.end(), name.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  for (const Kind kind : {Kind::Vertex, Kind::Edge, Kind::Wire, Kind::Face, Kind::Shell, Kind::Solid, Kind::Compound}) {
    if (kind_name(kind) == name)
      return kind;
  }
  throw ValueError("unknown topology kind '" + name + "'");
}

sr::ElementAnchor anchor_from(const py::dict& anchor) {
  sr::ElementAnchor out;
  out.node_id = py::cast<std::string>(anchor["node_id"]);
  out.output_slot = anchor.contains("output_slot") ? py::cast<int>(anchor["output_slot"]) : 0;
  out.kind = kind_from_text(py::cast<std::string>(py::str(anchor["kind"])));
  out.topo_id = py::cast<std::string>(anchor["topo_id"]);
  return out;
}

py::dict anchor_to(const sr::ElementAnchor& anchor) {
  py::dict out;
  out["node_id"] = anchor.node_id;
  out["output_slot"] = anchor.output_slot;
  out["kind"] = std::string(kind_name(anchor.kind));
  out["topo_id"] = anchor.topo_id;
  return out;
}

}  // namespace

void bind_element_ref(py::module_& m) {
  m.def(
      "_resolve_by_history",
      [](const sr::NodePtr& target, const py::dict& anchor, int target_slot, const std::string& follow) {
        if (follow != "identity" && follow != "derived")
          throw ValueError("follow must be 'identity' or 'derived'");
        const sr::FollowMode mode = follow == "derived" ? sr::FollowMode::Derived : sr::FollowMode::Identity;
        return value_to_python(sr::to_value(sr::resolve_by_history(target, anchor_from(anchor), target_slot, mode)));
      },
      py::arg("target"), py::arg("anchor"), py::arg("target_slot") = 0, py::arg("follow") = "identity",
      "Follow an element anchor {node_id, output_slot, kind, topo_id} through the recorded topology deltas "
      "to output `target_slot` of node `target`: {status: ok|split|merged|lost, targets, hops, lost_at, reason}.");
  m.def(
      "_anchors_for_role",
      [](const sr::NodePtr& node, const std::string& role) {
        py::list out;
        for (const sr::ElementAnchor& anchor : sr::anchors_for_role(node, role))
          out.append(anchor_to(anchor));
        return out;
      },
      py::arg("node"), py::arg("role"), "The anchors of the node's entities with a kernel output role.");
  m.def(
      "_subshapes_by_recorded_id",
      [](const Shape& root, const std::string& kind, const std::vector<std::string>& ids) {
        py::list out;
        for (const Shape& sub : sr::subshapes_by_recorded_id(root, kind_from_text(kind), ids))
          out.append(shape_to_python(sub));
        return out;
      },
      py::arg("root"), py::arg("kind"), py::arg("topo_ids"),
      "The sub-shapes of `root` with recorded topo ids ('face_face_5'); ValueError for one that is absent.");
}

}  // namespace scad::pybind::reactive
