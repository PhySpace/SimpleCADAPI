# The sketch solver

Decision record and reference for `scad_sketch` (include/scad/sketch/, src/sketch/).

## Decision

The Python SDK solves sketches with **py-slvs**, a binding of SolveSpace's `libslvs`
(GPL-3.0).  This repository is Apache-2.0, so the C++ port does **not** link it.

* **Default backend: `scad-native`**, a solver written for this repository.  No third-party
  numerical dependency, deterministic, single threaded, same result on every platform.
* The **`SketchSolverBackend` abstraction is kept exactly as in Python**: a backend has a
  `name`, a `version` and `solve(sketch, options) -> SketchSolveResult`; `register_*`,
  `get_*`, `set_default_*` and the scoped `sketch_solver_backend(...)` exist under the same names
  (Python bindings accept a duck-typed Python object, so the test double from
  `test_sketch_api.py` keeps working).  A backend never calls another one.
* A second backend wrapping libslvs behind a CMake option `SCAD_WITH_SLVS` (default OFF, so a
  default build never carries GPL code) is **not implemented**.  The seam for it is
  `register_sketch_solver_backend`; it needs no change to the document, the operators or the tests.

### Deliberate differences from py-slvs

| Aspect | py-slvs (Python) | scad-native (here) |
|---|---|---|
| backend name / version | `py-slvs` / `1.0.6` | `scad-native` / `1.0.0` |
| status codes | libslvs codes 0, 1, 2, 5 | the same four numbers, same meaning (see below) |
| naming failing constraints | libslvs's own search | order based (see below) |
| underconstrained geometry | libslvs's path | minimum-norm Newton path; fully constrained results are identical, free parts may rest elsewhere |
| DOF of a redundant system | **0 whenever the result is code 5**, even with free DOF (two equal distances on two free points: py-slvs says solved / 0, the truth is 3) | the real `unknowns - rank(J)` (`underconstrained` with the warning); a latent defect of the reference adapter that the port deliberately does not copy, because it lets `require_fully_constrained=True` accept loose sketches |
| conflict evidence image | matplotlib PNG | none; every fact is in the error text (inventory, repair, measurements) |
| iterations / residual | `0` / `0.0` | the real count / the real final L2 residual |

`tolerance` and `max_iterations` of `SketchSolverOptions` are honoured (py-slvs ignores them).

## Method

1. **Lowering** (`src/sketch/solver/model.cpp`, `lower_*.cpp`).  The document is walked once.
   Unknowns are the x/y of every sketch point that is not fixed, circle radii, B-spline poles
   of a cubic Bezier chain, and the contact points of tangencies.  `fix` removes parameters
   from the unknowns (it adds no equation).  Every driving constraint becomes residual
   equations; reference (`driving=False`) constraints are measured after the solve.
2. **Jacobians** are exact: each equation is a closure over a small forward-mode `Dual`
   (`dual.hpp`) with 20 local slots; the sparse support of every equation is discovered once.
3. **Iteration** (`newton.cpp`): from the document's coordinates, a Gauss-Newton step is the
   minimum-norm least-squares solution computed from a one-sided Jacobi SVD (`dense.cpp`).
   If a plain step does not reduce the residual, Levenberg-Marquardt damping is added and
   raised geometrically.  Convergence is `max |r| <= tolerance`, followed by three polishing
   steps so the result lands on the exact root (the tests compare to 1e-7 and better).
4. **DOF and redundancy**: after the solve, `DOF = unknowns - rank(J)`, with `J` the
   row-normalised Jacobian (so constraints of different units weigh the same) and a singular
   value counting as non-zero above `1e-6 * s_max`.  Redundant constraints sit near 1e-15 and
   independent ones above 1e-3, so the cut-off has a wide margin (SolveSpace uses 1e-4 on
   Gaussian pivots).

### Status mapping

Same decision table as the py-slvs adapter, with libslvs's numeric codes:

| solve | rank(J) vs equations | `status` | code |
|---|---|---|---|
| converged | full | `solved` or `underconstrained` (dof > 0) | 0 |
| converged | deficient | same, plus warning `redundant_constraints` | 5 |
| not converged | deficient | `conflicting` (diagnostic code `residual_too_large`) | 1 |
| not converged | full | `failed` (diagnostic code `did_not_converge`) | 2 |

An `underconstrained` result also carries the warning `Sketch has N remaining DOF.`  On a
failed solve the returned points are the document's *initial* coordinates, `dof` is 0 and
`residual_norm` is infinite, exactly like the Python adapter.

### Naming the failing constraints

* rank-deficient failure: constraints are added one at a time in document order, each time
  starting from the accepted solution; a constraint is blamed when the accepted set plus it no
  longer converges.  So the *later* of two conflicting constraints is named (`c_near`, not
  `c_far`), which is what the py-slvs probes show (A=5, B=20, C=7 names B and C).
* full-rank failure: every constraint whose residual is still above tolerance at the last iterate.
* more than 400 constraints: nothing is named (the search is a series of solves).

## Equation catalogue

`d_a` is a line's end - start; `R` is a circle's radius parameter or an arc's |start - center|.
All equations are the SolveSpace forms py-slvs lowers to, so initial-geometry basins agree.

| constraint | equations |
|---|---|
| coincident, concentric | x1 - x2, y1 - y2 (concentric on the centers) |
| horizontal / vertical (line), points_horizontal / points_vertical | y (x) of the two points equal |
| parallel | cross(d_a, d_b) |
| perpendicular | dot(d_a, d_b) |
| collinear | cross(d_a, d_b), cross(a.start - b.start, d_b) |
| equal_length | `|d_a| - |d_b|` |
| equal_radius | R_a - R_b |
| distance | `|p - q| - v` |
| distance_x / distance_y | (b - a).axis - v (target = b - a) |
| length (lines only) | `|d| - v` |
| radius / diameter | 2R - diameter |
| major_radius / minor_radius | `|center - axis point| - v` |
| point_on (line) | cross(p - start, d) |
| point_on (circle, arc) | `|p - center| - R` |
| midpoint | p - (start + end) / 2 |
| midpoint_points | `|am| - |mb|`, cross(m - a, b - m) |
| symmetric, mirror | midpoint of the pair on the axis; pair direction perpendicular to the axis (mirror matches line/arc endpoints by nearest initial position, circles by center) |
| line_distance | signed distance of a.start to line b minus +-v, sign fixed by the initial side |
| normal | cross(curve center - start, d) |
| angle | dot(d_a, d_b) / (`|d_a||d_b|`) - cos(theta), theta = min(v mod 360, 360 - v mod 360); 0/360 is rejected with the "use constrain_parallel_rsketch" text |
| tangent line/circle | helper contact T: `|T - c| - R`, cross(T - s, d), dot(T - c, d) |
| tangent circle/circle | helper T (initial point per `mode`): `|T - c_a| - R_a`, `|T - c_b| - R_b`, cross(T - c_a, T - c_b) |
| tangent line/arc | dot(d, endpoint - center) at the selected endpoint |
| tangent line/B-spline, B-spline/arc | cross of the end tangents (arc: radius turned a quarter turn; cubic: P1-P0 or P3-P2 of the end segment) |
| (implicit) arc | `|start - center| - |end - center|`, arcs run counter-clockwise start to end |

A B-spline is a *cubic Bezier chain* for the solver when it is non-periodic, cubic, unit
weighted, clamped (multiplicity 4 at both ends) and C0 inside (multiplicity 3); its literal
poles are unknowns and the endpoint poles share the start/end points.  Any other B-spline is
`fixed_shape`: poles are constants.  Unsupported combinations raise the Python messages
(`Unsupported tangent target kinds 'line' and 'ellipse'`, ...).

## Plugging in another backend

```cpp
class MyBackend final : public scad::SketchSolverBackend { /* name, version, solve */ };
scad::register_sketch_solver_backend(std::make_shared<MyBackend>());
sketch.solve({.backend = scad::get_sketch_solver_backend("my-backend")});
```

From Python any object with `name`, `version` and `solve(sketch, *, options)` can be registered
with `register_sketch_solver_backend` and selected by name.

## Where things live

| file | role |
|---|---|
| `include/scad/sketch/{types,sketch,solver,native_solver,profile,operators,diagnostics}.hpp` | public surface |
| `src/sketch/sketch.cpp`, `types.cpp`, `bspline_params.cpp` | the document |
| `src/sketch/solver/` | lowering, autodiff, SVD, iteration, results, registry |
| `src/sketch/profile.cpp`, `convert.cpp`, `promote.cpp`, `promotion_semantics.cpp` | profiles, OCCT conversion, tags/metadata |
| `src/sketch/operators_*.cpp`, `finalize.cpp` | the 42 operators and the one seam to `scad/semantic/finalize.hpp` |

## Verification

* `tests/cpp/sketch/` (doctest): solver cases ported from the four Python sketch test modules, the
  probes that were run against py-slvs (failing-constraint names, status codes), the document,
  promotion (tags, metadata, holes, planes, open chains, branch errors), recording and the registry.
* `tests/python/test_sketch_parity.py`: 16 sketches solved by the reference SDK; the golden files
  `tests/golden/sketch_parity_*.json` hold py-slvs's status, DOF, points and scalars, and the port
  must match them (1e-6).  Underconstrained directions that py-slvs resolves by its own path are kept
  out of the comparison on purpose (see the table above).
* `tests/python/test_sketch_api.py`: the Python-facing API, including a duck-typed Python backend.
* Linux x86_64 (GCC 15, libstdc++ assertions) and AddressSanitizer/UBSan builds are clean.
