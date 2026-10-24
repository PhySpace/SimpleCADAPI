// Structured sketch_solve failures: port of simplecadapi/sketch_diagnostics.py.
//
// Both functions always throw scad::Error (operation "sketch_solve") carrying
// measurements, a per-constraint inventory and repair lines.  The Python
// version also renders a matplotlib schematic as evidence; this port omits the
// image (there is no 2-D drawing dependency) and keeps every fact in the text,
// which is where the tests and the language-model readers look.
#pragma once

#include "scad/sketch/types.hpp"

namespace scad {

class Sketch;

// A conflicting / failed solve: names the failing constraints and their partners.
[[noreturn]] void raise_sketch_solve_failure(const Sketch& sketch, const SketchSolveResult& result);

// A solve that left degrees of freedom when a fully constrained one was required.
[[noreturn]] void raise_sketch_underconstrained(const Sketch& sketch, const SketchSolveResult& result);

}  // namespace scad
