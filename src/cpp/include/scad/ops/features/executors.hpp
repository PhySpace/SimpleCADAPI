// How the reactive engine re-runs a feature operation: one executor per recorded operation name
// (extrude, fillet, cut, translate, patterns, ...).  Call it explicitly, from the Python binding
// or before the first recompute; a static initializer would be dropped from a static library.
#pragma once

#include "scad/reactive/registry.hpp"

namespace scad {

void register_features_executors(reactive::ExecutorRegistry& registry);

}  // namespace scad
