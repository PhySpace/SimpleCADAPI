// Value -> tag records: the inverse of TagBinding::to_value / TagLineageWitness::to_value (internal).
#pragma once

#include "scad/core/value.hpp"
#include "scad/topo/tagging.hpp"

namespace scad::io::detail {

// Throw scad::ValueError (naming the bad field) on a malformed record; the
// result is validated by the caller (Shape::add_binding / add_lineage_witness).
TagBinding binding_from_value(const Value& value);
TagLineageWitness witness_from_value(const Value& value);

}  // namespace scad::io::detail
