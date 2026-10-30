#include "finalize.hpp"

#include "scad/semantic/finalize.hpp"
#include "scad/topo/value_lineage.hpp"

namespace scad::sketch_detail {

// The only place the sketch library hands an operation to the semantic pipeline.

void finalize_sketch_object(const std::string& op, Value params, SymbolicArgs symbolic, const Sketch& output,
                            const Sketch* input) {
  OpRecord record;
  record.op = op;
  record.params = std::move(params);
  record.symbolic = std::move(symbolic);
  std::vector<ValueLineage> inputs;
  if (input != nullptr)
    if (auto lineage = value_lineage_of(*input))
      inputs.push_back(std::move(*lineage));
  if (const auto lineage = finalize_runtime_object(std::move(record), "Sketch", inputs))
    attach_value_lineage(output, *lineage, op);
}

// The symbolic scalars a sketch holds, by their path in params["sketch"] (the structure of Sketch.to_dict()): a
// promotion's parameter expressions are the sketch's, so a variable edit reaches the profile it made.
static SymbolicArgs sketch_symbolic(const Sketch& sketch) {
  SymbolicArgs out;
  std::size_t index = 0;
  for (const auto& [id, entity] : sketch.entities()) {
    for (const auto& [key, scalar] : entity.scalars)
      if (scalar.symbolic())
        out.emplace_back("sketch.entities[" + std::to_string(index) + "]." + key, scalar);
    ++index;
  }
  index = 0;
  for (const SketchConstraint& constraint : sketch.constraints()) {
    if (constraint.value && constraint.value->symbolic())
      out.emplace_back("sketch.constraints[" + std::to_string(index) + "].value", *constraint.value);
    ++index;
  }
  return out;
}

Shape finalize_sketch_promotion(Shape shape, const std::string& op, Value params, const Sketch& sketch) {
  FinalizeSpec spec;
  spec.record.op = op;
  spec.record.params = std::move(params);
  spec.record.symbolic = sketch_symbolic(sketch);
  if (auto lineage = value_lineage_of(sketch))
    spec.record.value_inputs.push_back(std::move(*lineage));
  return finalize_derived_shape(std::move(shape), std::move(spec));
}

}  // namespace scad::sketch_detail
