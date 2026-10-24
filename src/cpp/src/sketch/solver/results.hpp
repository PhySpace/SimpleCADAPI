// Turning a solved parameter vector back into the document-shaped answer:
// solved points, scalars and per-entity dictionaries (the layout of the Python
// py-slvs adapter), plus the reference (non-driving) measurements.
#pragma once

#include <vector>

#include "model.hpp"
#include "scad/sketch/types.hpp"

namespace scad::sketch_solver {

struct SolvedGeometry {
  OrderedMap<SketchPoint2> points;
  OrderedMap<double> scalars;
  OrderedMap<Value> entities;
};

// The solution at `x` (the unknown vector); constants come from the model.
SolvedGeometry assemble_solution(const Model& model, const std::vector<double>& x);

// Adds "constraint:<id>:value" scalars for every driving=False constraint.
// ValueError for kinds that cannot be measured.
void add_measurements(const Model& model, SolvedGeometry& solved);

}  // namespace scad::sketch_solver
