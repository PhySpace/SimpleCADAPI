// Exceptions of the reactive area that the Python SDK gives their own type.
#pragma once

#include <string>

#include "scad/core/error.hpp"

namespace scad::reactive {

// simplecadapi.params.units.UnitValidationError: units or expression
// dimensions are physically inconsistent.  A message-first Error whose
// operation is "units".
class UnitValidationError : public MessageError {
 public:
  explicit UnitValidationError(const std::string& message) : MessageError("units", message) {}
};

// builtins.KeyError (the foundation has no class for it).
class KeyError : public Exception {
 public:
  explicit KeyError(const std::string& message) : Exception(PyKind::KeyError, message) {}
};

// topology.model.StaleLineageError: two different operations carry one node
// id.  In a notebook that means values of an older run met values of a newer
// run of the same cell; here it means the same for nodes adopted from another
// graph.
class StaleLineageError : public ValueError {
 public:
  explicit StaleLineageError(std::string node_id)
      : ValueError("node '" + node_id +
                   "' exists in two different versions (stale lineage); "
                   "re-run the cells that produced these values"),
        node_id_(std::move(node_id)) {}
  const std::string& node_id() const noexcept { return node_id_; }

 private:
  std::string node_id_;
};

}  // namespace scad::reactive
