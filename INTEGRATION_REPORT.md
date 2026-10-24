# CADIR integration, 2026-10-15

## Sources

- Upstream: `PhySpace/SimpleCADAPI` `master` at `6d3c235d375d5d3debad2f37f118b5fea4867607` (version 2.2.5).
- Local source: `../CADIR` at `15f0eebe7fc0c98558a973346379d23c1f0c02e2`, plus its 41 tracked working-tree modifications and 16 untracked files.
- The local source was not modified by this integration.

## Active integration

- Added the local per-instance STEP/BREP geometric-feature catalog, recognizers for eight categories, section-family/path/guide evidence, reconstruction handoff, section atlas, and report-based rendering under `src/simplecadapi/inspect/brep/`.
- Kept the upstream modeling operations and model-graph serialization unchanged. The reconstruction handoff recommends only upstream APIs. For path-constrained variable-section lofts, it marks a section loft as an approximation and retains the recovered path as evidence.
- Added the computational-geometry analysis workflow, API references, and local geometry-analysis guides. The guides point to upstream modeling operations.
- Copied the local reverse-engineering `viewer/` source and the compatible Windows addon probe fix. Windows VTK rendering now uses the upstream worker path with a portable render lock.

## Preserved local history

`integration-records/commits/` contains the two local commit patches;
`integration-records/working-tree.patch` contains all tracked uncommitted changes;
`integration-records/untracked/` contains copies of all 16 untracked files.
`integration-records/sources.txt` records source revisions. These records retain
local modeling additions and older components even where the active 2.2.5 SDK
uses different architecture. They are not imported by the package.

## Validation

- STEP recognition and computational geometry, excluding rendering: 121 passed. Two workflow-route text assertions failed initially and passed after the route was corrected.
- Rendering, documentation generation, skill build, addon, and viewer tests: 144 passed, 3 failed. The skill-build failure was a Windows line-ending assertion already fixed in the local source; after porting that assertion, its focused rerun passed. The remaining two failures are Windows-incompatible upstream addon tests: `test_use_runs_prefixed_command_with_addon_dir_env` uses a POSIX environment-assignment prefix, and `test_skill_dir_name_avoids_double_prefix` requires `/` path separators. The addon-use implementation and those test bodies were not modified by this integration.
- The Windows VTK test `test_render_entity_kind_maps_splits_geometry_kinds`, which crashed when rendered in process, passed after routing Windows rendering through the worker process.
- Final focused rerun of feature-catalog, workflow-route, and skill-build cases: 10 passed.
- `uv build --offline` produced `integration-records/dist/simplecadapi-2.2.5.tar.gz` and `integration-records/dist/simplecadapi-2.2.5-py3-none-any.whl`. The wheel contains the new STEP recognizers, reconstruction contract, and analysis workflow.
- `git diff --check` passed. No upstream modeling-operation, topology-tracking, or model-graph serialization source file was changed.
