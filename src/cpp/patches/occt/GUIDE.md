# How to modify the OCCT kernel systematically

This is the working method for SimpleCADAPI's modifications of OpenCASCADE (OCCT): where files go, how a geometric
special case becomes a strategy branch, how it is exposed to the SDK, and how it is verified and shipped. It comes from
the `fillet-robustness-4` patch set (Y transition, pinch corner, graph patch); the reasons behind each decision are in
`design-docs/y-patch-and-graph-patch.md`.

## 1. Principles

- **Geometric special cases are decided inside the kernel.** Not in Python (slow), not in the SDK's C++ operators
  (that couples the SDK to one kernel and makes a kernel migration a rewrite). The SDK only forwards a switch.
- **Small patches, new capabilities in the overlay.** A patch changes existing OCCT code only where it must: a switch,
  a call site, a fix. The algorithm itself is a new class in the overlay, separate from OCCT's sources, so that it
  replays on an OCCT upgrade and could be offered upstream on its own.
- **A strategy that is off changes nothing.** It runs either when the caller asks for it, or only when a specific
  situation is detected *and* the original algorithm fails there. An input that does not hit the detection takes the
  original code path and gets a bit-identical result.
- **Every strategy has gates.** The result must pass `BRepCheck_Analyzer`, `BOPAlgo_CheckerSI` level 5 and the history
  checks; if any fails, the original algorithm's behaviour is restored. Never return bad geometry silently.

## 2. Where files go

| Location | Content |
| --- | --- |
| `src/cpp/patches/occt/000N-<topic>.patch` | unified diffs of existing OCCT files, applied in number order |
| `src/cpp/patches/occt/manifest.json` | base version (tag, commit, archive sha256), patch-set name, patch list, before/after sha256 of every patched file |
| `src/cpp/patches/occt/overlay/<Package>_<Class>.{hxx,cxx}` | new classes; installed into OCCT's `src/<Package>/` (the part of the file name before the first `_`) and registered in that package's `FILES` |
| `src/cpp/patches/occt/tests/` | kernel-level check tools (a standalone CMake project): `cases` (Y/pinch family), `graphpatch`, `yfillet`, `check`, `inspect`, `shellfillet`, `sidetail`, `wires`, `fixsmall` |
| `src/cpp/patches/occt/README.md` | what each patch changes and why |
| `src/cpp/tools/occt_patches.py` | verifies hashes, applies patches exactly (no fuzz, idempotent), installs the overlay; `recipe()` fingerprints the whole set |
| `src/cpp/tools/build_occt.py` | builds static OCCT from source into a prefix and writes the fingerprint to `share/simplecadapi/occt-recipe.sha256` |
| `src/cpp/cmake/ScadOcct.cmake` | the toolkits the SDK links |
| `.github/workflows/ci.yml`, `release.yml` | CI and releases build the kernel from this patch set with `build_occt.py`; the cache key includes `src/cpp/patches/occt/**`, so a patch change rebuilds it |

When overlay code needs a new toolkit dependency, append it to that toolkit's `EXTERNLIB` in
`occt_patches.install_overlay()` (see how `TKPrim` is added to `TKFillet`).

## 3. Writing a strategy branch

A strategy has four parts. Example: the junction strategies in `overlay/BRepFilletAPI_YPatch*`.

1. **Detect**: a pure function from the shape and the caller's selection to a struct with evidence (junction vertex,
   concave and convex edges, the three supports, the support angle). Cheap, topological first, and reusing OCCT's own
   predicates (convexity: `ChFi3d::DefineConnectType`) instead of a second definition.
2. **Construct**: let OCCT's standard algorithm do everything it can and build only the missing piece. The junction
   strategies cut the junction wedge out, fillet the open shell with the standard algorithm, then add the corner faces
   (pinch bands or Y ribbons) and sew; far band ends and all other edges stay the standard algorithm's.
3. **Gate**: `BRepCheck_Analyzer`, `BOPAlgo_CheckerSI` level 5, no free edges after sewing, measured continuity
   (normal angles across seams). Any failure returns false.
4. **History**: `BRepTools_History` with Modified / Generated / Removed for every input sub-shape, composed explicitly
   through every stage, sub-shape by sub-shape (do not rely on `Merge`, see section 6).

Wiring into an existing OCCT entry point (patch `0004`):

- explicit switch: `BRepFilletAPI_MakeFillet::SetYPatch(bool)`, strategy first;
- default fallback: with the switch off the standard algorithm runs first; only when detection fires and the standard
  result fails, is invalid or self-intersects, the strategies replace it, in a fixed order (pinch, then Y). An input
  without a detection pays one topological scan and is otherwise unchanged;
- report: `NbYPatches()`, `YPatchJunction(i)` (with measured angles), `YPatchFallback()` (requested vs fallback);
- history: `Generated` / `Modified` / `IsDeleted` answer from the strategy's history when it produced the result, so
  callers that track faces and tags need no special case.

The order of several strategies is written in the entry point, never implied by code order.

## 4. Exposing a strategy in the SDK

- Detect at compile time with `#if __has_include(<BRepFilletAPI_YPatch.hxx>)`. The SDK must still compile against
  stock OCCT; requesting a strategy the kernel lacks raises `ValueError` naming the patch set, never silently ignores it.
- Use an explicit named boolean parameter, default `False` (`strategy_auto_y_patch`, `strategy_graph_patch`).
- Record it in the operation graph only when true, so records of the standard path stay as they were; replay it in
  `src/simplecadapi/recording/serializer.py` and in the C++ `executors.cpp`.
- Report capabilities through `simplecadapi._cpp._kernel_capabilities()`.
- Document in `src/simplecadapi/_glue/docstrings.json`, regenerate the API pages with `tools/auto_docs_gen.py` after
  building, update `CHANGELOG.md`.
- Check preconditions in the SDK before the kernel call (e.g. each graph-patch boundary must be an edge of its support),
  so the error says which one failed instead of a bare kernel refusal.

## 5. Workflow

Keep intermediate products outside the repository (e.g. `D:/occt-kernel/`).

1. **Dev loop, no prefix rebuild**: build the `tests/` CMake project against the installed prefix with
   `-DYPATCH_DEV=ON`; it compiles the checkout's overlay sources into the tools, shadowing the prefix's copies. When
   the patched `MakeFillet` changes too, add `-DYPATCH_MAKEFILLET=<dir of the patched MakeFillet>`. A build-and-test
   round takes seconds.
2. **Regenerate a patch**: pristine files under `a/src/<Package>/`, edited ones under `b/src/<Package>/`; one
   `diff --git` line per file, then `diff -u --label a/src/... --label b/src/...` (no timestamps in the labels, or
   `occt_patches` reads a wrong file name); update the file's before/after hashes in `manifest.json`.
3. **Rebuild the prefix incrementally**: restore the pristine versions of patched files in the source tree first (the
   new after-hash makes `apply()` reject the old patched state); `occt_patches.install_overlay(<tree>)`; in the build
   directory `cmake --build . --target install` (only the changed toolkits recompile); write `occt_patches.recipe()`
   into the prefix's `occt-recipe.sha256`. Install a new kernel into a new prefix (e.g. `C:/OCCT-modified/static-ypatch`)
   and keep the previous one as the control.
4. **Rebuild the SDK**: a separate build directory (e.g. `out/ypatch-build`) configured with
   `-DSCAD_OCCT_PREFIX=<prefix> -DOpenCASCADE_DIR=<prefix>/lib/cmake/opencascade`. The `.pyd` lands in
   `src/simplecadapi/_cpp/`; rename the module loaded in `.venv` first, then copy the new one (a loaded DLL cannot be
   overwritten but can be renamed).
5. **Test**:
   - kernel: `cases.exe` over the whole family must print `failures 0`, strict history included;
   - SDK: `ctest`; `pytest src/cpp/tests/python` and `pytest test tests` as two runs (one run collides on test module
     names);
   - continuity: zebra pictures with `tools/render/zebra.py`, looked at one by one;
   - ground truth: the same cases in Plasticity driven by desktop automation (scripts under
     `out/plasticity-gt/tools/` on the development machine), comparing deviations and P*.
6. **Commit**: one decision per commit, the message as a decision record (DECISION / PROBLEM / WHY / REJECTED /
   EVIDENCE / NOT DONE), written to a file and committed with `git commit -F`.

## 6. Pitfalls already met

- **Line endings**: the repository stores bytes exactly (`* -text` in `.gitattributes`). Python's `write_text` on
  Windows writes CRLF; use `write_bytes` or `newline='\n'` and check with `file` before committing.
- **English only under `src/`**: `test/test_library_is_english.py` rejects Chinese text there; decision records and
  reports in Chinese belong in `design-docs/`.
- **`BRepFilletAPI_MakeFillet::IsDeleted` answers for faces only**: for edges and vertices it says "deleted". Test their
  survival by presence in the result.
- **`BRepBuilderAPI_Sewing::IsModified/Modified` only know whole shapes added with `Add`**: for sub-shapes use
  `IsModifiedSubShape/ModifiedSubShape`, or the supports are reported deleted.
- **`BRepTools_History::Merge` loses mappings**: a shape generated in the second history from a modified image is not
  carried back to the original. Compose multi-stage histories explicitly.
- **The standard fillet depends on the order of `Add`**: the same edges added in another order can turn "not done"
  into "done". Tests add edges in a fixed order.
- **Periodic seams**: with a cylinder's seam vertex on a chain to be filleted, the standard algorithm built a band twice.
  Move the parametric origin away from the selected edges first, then merge the old seam's vertex (edges only).
- **Dangling temporaries**: `TopTools_ListOfShape::Iterator it(f())` with `f()` returning a list by value iterates a
  destroyed temporary. Store the list in a local first.
- **History checks must be strict**: "kept, modified or deleted" lets a wrong "deleted" pass. Require: no input face
  reported deleted, junction edges generating enough faces, every result face traced to an input face or edge.
- **Keep experiment outputs apart from final outputs**: experiment runs overwrote result files and a later comparison
  silently used the wrong ones. Use a fresh output folder for every final run.
- **Check nobody is editing the overlay before syncing**: a prefix rebuild copies the overlay folder as it is, a
  half-edited file included; such a build is provisional.
- **A text BREP round trip is not a fix**: when writing a shape as text and reading it back makes a case pass, the case
  is numerically marginal there; fix the geometry.
- **Do not fit degenerate surfaces in 2D**: the pinch bands collapse to a point (section radius like x²/4R); fitting
  sampled positions with a tensor spline folded them. Build such surfaces exactly (exact sections, 1D laws along the
  rail, a degenerated edge at the apex).

## 7. Acceptance checklist for a new strategy

- [ ] detect / construct / gate / history; off means bit-identical results
- [ ] a whole family, not one sample: tangent and near-tangent, several sizes, arbitrary placement, every position of a
      periodic seam, one and several occurrences, one case that must be refused
- [ ] strict history through the public entry point (e.g. `MakeFillet`)
- [ ] zebra pictures, comparison with Plasticity ground truth
- [ ] patch regenerated, manifest updated, prefix rebuilt incrementally, SDK rebuilt, C++ and Python suites green
- [ ] SDK parameter, operation-graph record and replay, capability query, docs, CHANGELOG
- [ ] decision record in `design-docs/` and decision-record commit messages
