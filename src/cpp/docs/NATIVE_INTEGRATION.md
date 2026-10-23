# Running the SDK on the native backend

Goal (owner, 2026-10-21): `sca editor` runs `sandbox-envs/desktop_arm_sources` (the 6-DOF arm,
`arm6.py`) completely on the C++ backend; the top-level API and the behaviour of every API are
identical to the Python SDK; unimportant details the Python SDK should have optimised anyway (some
ids, ...) are optimised in C++.

## Where the work happens

- SDK worktree: `/Users/lildino/Project/ocws/SimpleCADAPI-native`, branch `feat/native-backend`, cut
  from `dev` (29cbcc3). The owner's main checkout `/Users/lildino/Project/ocws/SimpleCADAPI` is NOT
  touched. No commits unless asked; never push.
- Python 3.12 env: `SimpleCADAPI-native/.venv` (the SDK installed editable from the worktree, OCP,
  marimo, editor extras). The native module is used from a build tree: put
  `<repo>/cpp/build/<yours>/python` on `PYTHONPATH`.
- The sandbox is copied into `SimpleCADAPI-native/sandbox-envs/desktop_arm_sources` and is
  git-ignored (keep it untracked). `tools/profile_arm6.py` finds it there.
- The C++ project lives in this repo under `cpp/` (see src/cpp/ARCHITECTURE.md, src/cpp/AGENTS.md). One folder, one branch.

## Design

`SCA_BACKEND=native|ocp` selects the implementation of the lower layers; `ocp` stays the default until
the acceptance criteria below pass, then the default flips.

| Layer | Backend native | Notes |
|---|---|---|
| core (shapes, tags, CoordinateSystem), kernel, topology, operators, sketch, sketch_solver, ql, std, surface, product, params (expr, units, frame), math, recording.graph | native module | re-exported under the same module paths |
| runtime, editor, build, cli, addon | unchanged Python | they never touch `.wrapped` or OCP (checked: 0 uses) |
| inspect (146 OCP imports), artifacts, exporter, scene, translator, dxf_engine, `_internal` | unchanged Python | reach shapes through `.wrapped` |

Mechanism: `simplecadapi/__init__.py` (and `_backend.py`) installs shim modules into `sys.modules` for
the replaced module paths *before* the kept layers import them, so `from ..core import Solid` in kept
code resolves to the native class. The shims re-export from `simplecadapi._cpp` and add what kept code
imports (private helpers included).

`.wrapped` bridge: two in-process OCCT copies (OCP's and ours) cannot share TopoDS objects, so a native
shape exposes `wrapped` lazily as an OCP shape rebuilt from `to_brep()` bytes (BinTools), cached on the
handle; kept layers that return OCP shapes (STEP import, ...) are wrapped back with `from_brep`. The cost
is paid only on the kept layers' paths (inspect, export, render), never in modelling.

Pickle/deepcopy/cell cache: native `serialize/deserialize` (versioned `SCADSHAP`) via `__reduce__`.

## Acceptance (all three, in this order)

1. **Old test suite** (`test/`, `tests/` of the worktree) with `SCA_BACKEND=native`: pass-rate against the
   `ocp` baseline (`/tmp/native/baseline_ocp.log`). Every failure is classified: fixed; legitimate
   (the test pokes OCP-wrapper internals that no longer exist: skip with a reason in the test, or adapt it
   to the public API); open. "Behaviour identical" is judged by this suite plus the goldens.
2. **Sandbox checks**: `check_desktop_arm.py`, `check_desktop_interfaces.py`, `check_desktop_service.py`,
   `check_short_link_lands.py`, `check_snapshot_kinematics.py`, `verification/` give the same results on
   `native` as on `ocp`.
3. **arm6 end to end**: `arm6.py` and its 11 nested `scad.use` notebooks run through the runtime
   (`tools/profile_arm6.py`; cold, warm, one-parameter edits) and through the editor kernel (`sca edit`;
   UI e2e with `ego-browser`, see memory `ego-browser-e2e`) on `native`, with outputs equal to `ocp`
   (volumes, bounding boxes, solved placements, exported artifacts), and timings recorded next to the
   2.2.6.post1 numbers (cold 34.6 s, warm 4.0 s, J1 edit 3.0 s).

## Optimising ids and other unimportant details

Principle: **compact internally, canonical at the boundary.** An id that is only compared inside a
process can be a small integer or an interned string; the Python-format string is produced lazily when
the value crosses a boundary (`to_dict`, serialization, error text, golden comparison). Then nothing
persisted or hashed changes.

An id may change representation only if all of these hold (verify by grep in the worktree, not by memory):
- it is not written to artifact / model-JSON / scene / cache files or hashed into a digest in
  `artifacts/`, `recording/serializer.py`, `runtime/` cache keys, `scene/`;
- no kept-Python code parses its text;
- no golden file or old test asserts its text.
Candidates: `TagBinding.binding_id` (44-char string, uuid5 in the port), `rule_id`/`rule_version`
strings repeated per binding, `topo_id` ("face_12"), `expr_id`, `OperationNode.node_id`, `semantic ids`.
Anything that fails the checklist keeps its Python format. Every deliberate deviation is listed in
`docs/DEVIATIONS.md` with the reason and the measured gain (memory: `tools/bench/bench_memory.py`;
speed: `tools/bench/bench_native.py`; current: 77 KB per box vs a 15 KB OCCT floor).

## Target architecture (owner, 2026-10-22)

- Python stays a thin binding layer. In C++: geometry, construction/computation, tagging, ql, the
  operation GRAPH (recording, model-JSON export/import/replay, `geo_selector`), a CAD-specific reactive
  runtime, rendering, and `.scadpkg` packaging.
- **Translators (FreeCAD, Fusion360, SolidWorks) stay in Python** (decided by the owner): they consume the
  C++ graph through the bindings, so the recorded graph and model JSON must match the original schema
  exactly (`geo_selector`, `selected_*_node_ids`, `input_refs`, `semantic_delta_log`, ...). Acceptance for
  graph work is identical translator OUTPUT on both backends, not only passing tests (measured: the
  translator tests pass on native today although the schema differs).
- The notebook cells (user code) are executed by Python; the C++ reactive runtime schedules and caches
  them as external nodes and replays the recorded graph natively for everything else.
- Order: (1) graph schema parity (docs/GRAPH_PARITY.md) -> (2) serializer/replay in C++ -> (3) C++ reactive
  runtime (project-level push graph, native replay, cache, parallel scheduling; acceptance: arm6 J1 edit) ->
  (4) `.scadpkg` in C++ -> (5) software renderer wired in (docs/render.md) -> (6) remaining OCP removal.


## Reactive granularity (owner decision, 2026-10-22; corrected same day)

Required: **variable + statement level** reactivity (marimo only gives cell level); the one that matters
most is **variable + operator level**.

Principle: **the recorded graph is a trace of one execution, not the program.** An `if` or a loop whose
condition depends on a variable makes it a snapshot. Dependencies and correctness therefore come from the
Python runtime; C++ only accelerates.

1. **Dependencies are captured dynamically (Python, authoritative).** While a statement runs, the runtime
   records the variables, `scad.use` results and globals it reads and writes. A changed variable
   re-executes the statements that read it, in Python, so control flow is always re-evaluated.
2. **Operator level = content-addressed memo in C++.** Re-executed statements call operators as usual; each
   call is keyed by (operator, params, digests of input shapes). A hit returns the cached result without
   touching OCCT. Correct under any control flow because the statement really runs.
3. **Optional later: guarded trace replay.** Variable reads return symbolic scalars; every forced
   concretisation (`__bool__`, comparison, `int()`) is recorded as a guard. If all guards still hold after
   a change, C++ replays the trace without entering Python; any guard flip falls back to 2. Built only if
   measurements show statement re-execution matters.

The graph (recording, model JSON, `geo_selector`) serves translators and export; it is not an input to
reactive correctness, so graph parity is no longer a prerequisite of the reactive runtime.

Acceptance: arm6 J1 edit == full re-run (volumes, bboxes, placements, exported artifacts) with only the
operators downstream of J1 recomputed; a one-statement edit in cell 2 re-runs that statement and its
dependents, not the 11 `scad.use`; a variable that flips an `if` branch still gives the correct result.
