# Landing plan: the native engine as a stack of reviewable pull requests

**Status: a plan.** The stacked branches described here have **not been created**, and none of the intermediate states has
been built or tested. The initial commit `8971279` ("the geometry engine is C++ on OpenCASCADE, one package, prebuilt
wheels") changed 1,268 files (140,294 insertions); this document proposes how to cut the part of it that lives in `src/cpp`
(plus the Python files that exist only to drive the compiled module) into ten pull requests, each small enough to review.
Everything below is derived from the layer rules and from a script, `tools/landing_plan.py`; nothing in it has been
confirmed by a build of a partial tree.

## How the cut was made

* **Order follows the link dependencies** in `src/CMakeLists.txt` (`scad_add_area ... DEPS`): core, kernel, topo, then
  semantic / reactive / io, then ql / render, then the operators, then product / std, then the Python module.
  `python3 src/cpp/tools/landing_plan.py --check-includes` reads every `#include "scad/..."` in each area's `include/`,
  `src/` and `tests/cpp/` and reports any that names an area outside the area's dependency closure. It reports none on the
  current tree, so each C++ PR only needs the PRs below it. (The check was run against its own negative case: with a
  deliberately wrong dependency table it reports the violations.)
* **One file, one PR.** `tools/landing_plan.py` assigns every tracked file of the universe (all of `src/cpp`, plus
  `src/simplecadapi/_cpp`, `src/simplecadapi/_glue`, `pyproject.toml`, `.github/workflows`) to a PR by the longest matching
  path prefix, and exits non-zero if a file matches no prefix or a prefix matches no file. Its rule table is the exact
  list for each PR; `--files` prints every file with its line count, `--pr N` prints the files of one PR.
* **Not in this plan:** the other files of commit `8971279` outside the universe above (the forwarding modules and the
  Python layers adapted in the rest of `src/simplecadapi`, `docs/skill`, examples, tests, `uv.lock`; 449 of the commit's
  1,268 files; the universe covers the other 819). They need their own plan; they depend on PR 9 and should land after it.
* **Build gating is not done.** `src/cpp/src/CMakeLists.txt` and `tests/cpp/CMakeLists.txt` name every area. The structure
  suggests a partial tree configures: an area directory with no sources becomes an INTERFACE library, a test directory with
  no sources is skipped, `ScadGordon.cmake` falls back when `third_party/occ_gordon` is missing. That has not been tried.
  If it does not hold, each PR needs a small gating change (an area list in CMake) which is not part of the counts below.
  Configure PRs 1 to 8 with `-DSCAD_BUILD_PYTHON=OFF`; the module needs every area.
* **Counts.** "Lines" counts code, docs and scripts (`wc -l` style newline counts of the committed blobs); "data" counts
  vendored code, recorded goldens and JSON, which a reviewer samples rather than reads. The numbers below are from
  `python3 src/cpp/tools/landing_plan.py --rev WORKTREE` at the time of writing and drift with every commit; rerun the script.

## The stack

| PR | Title | Files | Lines | Data lines | Depends on |
|---|---|---|---|---|---|
| 1 | build, CI, format, docs | 26 | 2,421 | 7,106 | - |
| 2 | core, topo, kernel | 72 | 9,523 | 0 | 1 |
| 3 | semantic | 27 | 6,459 | 677 | 2 |
| 4 | reactive | 41 | 9,103 | 0 | 2 |
| 5 | io, render, ql | 91 | 13,763 | 615 | 2, 3 |
| 6 | ops_geometry, ops_features | 87 | 9,079 | 0 | 3, 4, 5 |
| 7 | sketch, surface | 94 | 9,923 | 4,932 | 3 (can land in parallel with 4-6) |
| 8 | product, std | 77 | 8,182 | 0 | 6, 7 |
| 9 | python bindings, adapter, parity tests | 293 | 22,861 | 34,169 | 1-8 |
| 10 | OCCT shim, wheels, release, research | 23 | 5,222 | 306 | 9 |
| | total | 831 | 96,536 | 47,805 | |

PR 9 is large in files because the 182 golden JSON files (all but `io_*`) and the 54 files of `tests/python` ride with it; if that is too much, split
it into 9a (`bindings/python`, `src/simplecadapi/_cpp`, `_glue`) and 9b (`tests/python`, `tests/golden` except `io_*`).
PR 7 does not depend on 4 to 6 (it needs only `semantic` and below), so it can be reviewed in parallel.

### PR 1: build, CI, format, docs

* **Contents (exact prefixes):** `src/cpp/CMakeLists.txt`, `src/cpp/src/CMakeLists.txt`, `src/cpp/cmake/ScadCompile.cmake`,
  `ScadOcct.cmake`, `src/cpp/tests/cpp/CMakeLists.txt`, `tests/cpp/test_main.cpp`, `third_party/doctest/`, `.clang-format`,
  `.clang-tidy`, `.gitignore`, `tools/{check_format.sh,build_occt.py,check_occt_guard.py,lsan.supp,gen_stubs.sh,landing_plan.py,gen_status.py}`,
  `scripts/`, and the top-level docs: `README.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`, `PORTING_STATUS.md`,
  `docs/{READING_ORDER,LANDING_PLAN,DEVIATIONS,briefs}.md`.
* **Proves it:** no C++ yet; the `clang-format` CI job (`tools/check_format.sh`), a configure of the project with
  `-DSCAD_BUILD_PYTHON=OFF` (empty areas), `python3 tools/build_occt.py` on one platform.
* **Read first:** `CONTRIBUTING.md`, `cmake/ScadCompile.cmake`, `src/CMakeLists.txt`, then `ARCHITECTURE.md`.
* **Old tests it answers for:** none.

### PR 2: core, topo, kernel

* **Contents:** `include/scad/{core,topo,kernel}/`, `src/{core,topo,kernel}/`, `tests/cpp/{core,topo,kernel}/`,
  `docs/memory.md`, `tools/bench/`.
* **Proves it:** `test_core`, `test_topo`, `test_kernel` (ctest names `core`, `topo`, `kernel`).
* **Read first:** `include/scad/core/error.hpp`, `include/scad/topo/shape.hpp`, `include/scad/topo/recorder.hpp`, then
  `src/core/occt_guard.cpp` and `include/scad/kernel/builders.hpp`.
* **Old tests it answers for:** `test_rearchitecture_2_0_kernel_builders.py`, `test_rearchitecture_2_0_kernel_transforms.py`,
  `test_rearchitecture_2_0_contract.py`, `test_topology_getter_contract.py`, `tests/test_topology_identity.py`,
  `test_error_harness.py`, `test_math_helpers.py`.

### PR 3: semantic

* **Contents:** `include/scad/semantic/`, `src/semantic/`, `tests/cpp/semantic/` (including `tracking_golden.hpp`, a generated file).
* **Proves it:** `test_semantic` (tagging, selection, finalize, tracking behaviour, tracking golden).
* **Read first:** `include/scad/semantic/finalize.hpp`, `tracking.hpp`, then `src/semantic/tracking_core.cpp` and `finalize.cpp`.
* **Old tests it answers for:** `test_tagging_refactor.py`, `test_operation_output_roles.py`, `test_tracking_data_models.py`,
  `test_graph_lineage.py`.

### PR 4: reactive

* **Contents:** `include/scad/reactive/`, `src/reactive/`, `tests/cpp/reactive/`.
* **Proves it:** `test_reactive`.
* **Read first:** `include/scad/reactive/expr.hpp`, `session.hpp`, then `src/reactive/recompute.cpp`.
* **Old tests it answers for:** `test_expr_graph.py`, `test_graph_model_api.py`, `test_model_json.py`,
  `test_notebook_params.py`, `test_tolerance.py`.

### PR 5: io, render, ql

* **Contents:** `include/scad/{io,render,ql}/`, `src/{io,render,ql}/`, `tests/cpp/{io,render,ql}/`, `tests/golden/io_*`
  (read by `tests/cpp/io/test_brep_region.cpp`), `docs/io.md`, `docs/render.md`, `docs/render/` (pictures and metrics).
* **Proves it:** `test_io`, `test_render`, `test_ql`.
* **Read first:** `include/scad/io/serialize.hpp` and `docs/io.md`, `include/scad/ql/selector.hpp` with `src/ql/resolve.cpp`,
  `include/scad/render/render.hpp`.
* **Old tests it answers for:** `test_serialization.py`, `test_internal_mesh.py`, `test_brep_region_snapshot.py`,
  `test_native_canonical.py`, `test_product_exporter.py`, `test_ql.py`, `test_error_diagnostics_blend_ql.py`,
  `test_render_screenshot_multiview.py`, `test_failure_evidence.py`.

### PR 6: ops_geometry, ops_features

* **Contents:** `include/scad/ops/`, `src/ops/`, `tests/cpp/ops_geometry/`, `tests/cpp/ops_features/`.
* **Proves it:** `test_ops_geometry`, `test_ops_features`.
* **Read first:** `src/ops/geometry/box.cpp` (one operator end to end), `src/ops/features/blends.cpp` and
  `blend_diagnosis.cpp`, `src/ops/features/booleans.cpp`.
* **Old tests it answers for:** `test_all_features.py`, `test_original_api_integration.py`, `test_helix_handedness.py`,
  `test_rational_volume_precision.py`, `test_rearchitecture_2_0_{ops,remaining_ops,structural_remaining,todo_ops}.py`,
  `test_chamfer_angle.py`, `test_draft.py`, `test_limited_extrusion.py`, `test_section_features.py`,
  `test_deformation_features.py`, `test_shell_integration.py`, `test_error_diagnostics_{boolean,sweep_loft}.py`.

### PR 7: sketch, surface

* **Contents:** `include/scad/{sketch,surface}/`, `src/{sketch,surface}/`, `tests/cpp/{sketch,surface}/`,
  `docs/sketch-solver.md`, `cmake/ScadGordon.cmake`, `third_party/occ_gordon/` (vendored DLR `occ_gordon`, Apache-2.0; 4,932 lines
  of the data column).
* **Proves it:** `test_sketch`, `test_surface`.
* **Read first:** `docs/sketch-solver.md`, `include/scad/sketch/sketch.hpp`, `src/sketch/solver/newton.cpp`;
  `include/scad/surface/fitter.hpp`, `src/surface/trim.cpp`.
* **Old tests it answers for:** `test_sketch_api.py`, `test_sketch_closed_bspline.py`, `test_sketch_ellipse.py`,
  `test_sketch_histcad_constraints.py`, `test_error_diagnostics_sketch.py`, `test_surface_api.py`, `test_periodic_loft_api.py`.

### PR 8: product, std

* **Contents:** `include/scad/{product,std}/`, `src/{product,std}/`, `tests/cpp/{product,std}/`.
* **Proves it:** `test_product`, `test_std`.
* **Read first:** `include/scad/product/solver.hpp` with `src/product/solve.cpp`, `assembly.hpp`; for std `src/std/gear_external.cpp`
  and `involute.cpp`.
* **Old tests it answers for:** `test_product_assembly.py`, `test_part_interface.py`, `test_part_builder.py`,
  `test_assembly_builder.py`, `test_error_diagnostics_assembly.py`, `tests/test_placement_stability.py`,
  `test_stdlib_{bearing,chain,fastener,gear}.py`.

### PR 9: python bindings, adapter, parity tests

* **Contents:** `src/cpp/bindings/python/` (except `occt/`), `src/simplecadapi/_cpp/` (except `occt.py` and `_occt_layout.json`),
  `src/simplecadapi/_glue/`, `src/cpp/tests/python/`, `src/cpp/tests/golden/` (all except `io_*`), `tools/graph_parity/`,
  `docs/{NATIVE_INTEGRATION,NATIVE_PROGRESS,PERF}.md`.
* **Proves it:** `python -m pytest src/cpp/tests/python -q` (468 passed at the last recorded run), then the whole old suite on
  the native engine, `python -m pytest test tests -q` (2202 passed, 49 skipped, 1 xfailed at the last recorded run; figures
  from `docs/NATIVE_PROGRESS.md`).
* **Read first:** `bindings/python/module.cpp`, `common.cpp`, `py_lifetime.hpp`, `bind_ops_features.cpp`,
  `tests/python/ref.py`, `src/simplecadapi/_glue/names.py`.
* **Old tests it answers for:** the whole of `test/` and `tests/` (this is the PR where the old suite first runs on the
  native engine), plus `test_public_api_surface.py`, `test_native_without_ocp.py`, `test_library_is_english.py`,
  `test_operator_layout.py`. Entries in `test/native_known_failures.json` are reviewed here.

### PR 10: OCCT shim, wheels, release, research

* **Contents:** `bindings/python/occt/`, `occt_dev/`, `docs/OCCT_BINDINGS.md`, `tools/occt_usage_trace.json`,
  `src/simplecadapi/_cpp/{occt.py,_occt_layout.json}`, `pyproject.toml`, `.github/workflows/`,
  `tests/wheel_smoke.py`, `docs/research/`, `tools/research/`.
* **Proves it:** `python src/cpp/tests/wheel_smoke.py` in a clean environment with only the wheel installed (cibuildwheel runs it);
  a dry run of the release workflow (`workflow_dispatch` with `dry_run`, see `.github/workflows/release.yml`); the editable
  build through `uv sync --locked --group dev`.
* **Read first:** `docs/OCCT_BINDINGS.md`, `pyproject.toml` (`[tool.scikit-build]`, `[tool.cibuildwheel]`),
  `.github/workflows/release.yml`.
* **Old tests it answers for:** `test_wrapped_ocp.py` and the `test_inspect_brep*.py` family (the Python layers that still read OCP
  classes through the shim).
* **Note:** `src/cpp/.github/workflows/{ci,wheels}.yml` were an older pair of workflows nested in `src/cpp` that GitHub
  never ran (it reads only the repository root `.github/workflows`); they are deleted.

## Reviewing and landing

* Land in numerical order; PR 7 may go any time after PR 3. Each PR is expected to pass its own test executables
  and the format check once it is rebased on its parent. Whether it also builds alone is exactly what has not been verified.
* The rules a reviewer should hold each PR to are in `CONTRIBUTING.md` (errors, GIL, thread safety, parity).
* After PR 9 merges, the old suite is the acceptance test for the rest of commit `8971279`.
