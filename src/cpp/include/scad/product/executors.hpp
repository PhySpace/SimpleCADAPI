// The product operations in the reactive engine.
#pragma once

#include "scad/reactive/registry.hpp"

namespace scad::product {

// Registers an executor for every operation the product operators record, so a parameter edit
// upstream (a Part's body, a placement coordinate) does not stop a recompute at them.
//
// Product operations produce values (parts, assemblies, constraints), not shapes, and the
// values the caller holds are not graph outputs, so there is nothing for an executor to
// rebuild: each one accepts its recorded parameters and returns no outputs.  The exception is
// "make_compound_from_assembly_rcompound": its Compound output needs the assembly itself, which a
// record does not hold, so it has no executor and recomputing it is reported by name.
//
// Call it once per registry, explicitly (a static initializer in a static library would be
// dropped by the linker).  ValueError when a name is already registered.
void register_product_executors(reactive::ExecutorRegistry& registry);

}  // namespace scad::product
