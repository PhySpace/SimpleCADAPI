// How sketch operators finish: the single place that talks to the recorder (and,
// once it lands, the semantic finalize pipeline).  Internal to the sketch library.
#pragma once

#include <string>
#include <utility>
#include <vector>

#include "scad/core/scalar.hpp"
#include "scad/core/value.hpp"
#include "scad/sketch/sketch.hpp"
#include "scad/topo/recorder.hpp"
#include "scad/topo/shape.hpp"

namespace scad::sketch_detail {

using SymbolicArgs = std::vector<std::pair<std::string, Scalar>>;

// _finalize_runtime_object for Sketch outputs: the operation is reported with its
// parameters (symbolic ones kept) and no shape output.
// The result sketch takes the lineage of the node recorded; `input` (the sketch it was made from) links to it.
// `values`: the lineages of other value inputs (the workplane a sketch is made on).
void finalize_sketch_object(const std::string& op, Value params, SymbolicArgs symbolic, const Sketch& output,
                            const Sketch* input = nullptr, std::vector<ValueLineage> values = {});

// _finalize_derived_shape for a promoted Wire / Face.  Returns the handle the
// operator must hand back (the finalize pipeline may return a detached view).
Shape finalize_sketch_promotion(Shape shape, const std::string& op, Value params, const Sketch& sketch);

}  // namespace scad::sketch_detail
