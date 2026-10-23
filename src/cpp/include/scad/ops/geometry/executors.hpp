// Re-running the geometry operators from what the recorder stored.
#pragma once

#include "scad/reactive/registry.hpp"

namespace scad {

// Registers one executor per operation the geometry operators record ("make_box_rsolid",
// "make_line_redge", "make_wire_from_edges_rwire", ...), so a parameter edit can rebuild
// them.  Call it once per registry, explicitly: a static initializer in a static library
// would be dropped by the linker.  ValueError when a name is already registered.
void register_geometry_executors(reactive::ExecutorRegistry& registry);

}  // namespace scad
