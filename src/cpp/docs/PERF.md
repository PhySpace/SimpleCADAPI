# Performance log (arm6 benchmark)

Acceptance case: `tools/profile_arm6.py` of the SDK worktree (`sandbox-envs/desktop_arm_sources`), native backend
with a stub `OCP` that raises on import. wall s / cpu s of the parent process; the machine is shared, so compare
cpu and A/B runs. cProfile runs use `SCA_JOBS=1` (one process).

## 2026-10-22: canonical hashing, bounds, fingerprint memo

| scenario | before (lead) | after | ocp backend (same session) |
|---|---|---|---|
| cold | 29.5 / 17.4-18.8 | 20.1-20.2 / 14.3-15.2 | 36.0 / 19.3 |
| warm | 1.78 / 1.84 | 1.7 / 1.75 | 4.25 / 4.3 |
| edit J1 | 2.04 / 2.35 | 1.8 / 2.1 | 2.9 / 3.2 |
| edit UPPER_LENGTH | 24.2-24.4 / 16.9 | 15.6-16.2 / 10.1 | 18.9 / 11.1 |
| edit BASE_D | 4.4 / 5.6 | 3.2-3.7 / 4.5-4.8 | 6.1 / 7.1 |
| edit OPEN_STROKE | 2.7 / 3.6 | 2.35 / 3.3 | 3.6 / 4.6 |
| cProfile total, cold + edits, 1 process | 116 s | 75 s | 152 s (lead) |

Target "cold cpu <= 70% of 18.8 s (13.2 s)" is not met: 14.3-15.2 s (-20%). What is left in the parent is spread
thin (marimo/AST digesting, `_semantic_index` 1.1 s, `capture_result` 1.1 s, the bearing build 1 s, pickling).

Changes, each with the measured effect:

1. **Canonical JSON in C++** (`bindings/python/bind_canonical.cpp`, `canonical_bytes`, `canonical_hash`; pieces
   `canonical_append_string/number`, `canonical_key_less` in `scad/io/json.hpp`). One pass over the Python
   containers: validation, RFC 8785 text and SHA-256 together. Anything outside the fast domain (non-dict mappings,
   container subclasses, integers beyond +-(2^53-1), non-finite floats, lone surrogates, non-string keys, nesting
   over 48, cycles) answers `None` and the SDK runs its Python implementation, so every error keeps its type and
   message by construction. `safe_ints` folds `geometry_interface._json_safe` into the same pass. Single-process
   profile: `canonical_bytes` 132k calls / 29.5 s cumulative, `validate_json_value` 7.7 s, rfc8785 `dump` 23 s
   -> `canonical_hash` 47k calls / 0.3 s; profile total 116 -> 85 s. Tests: `tests/cpp/io/test_canonical_pieces.cpp`,
   `tests/python/test_io_canonical.py` (fuzz against an inline copy of the rfc8785 algorithm), SDK
   `test/test_native_canonical.py` (5,516 values recorded from a real arm6 build: bytes length and SHA-256 equal to
   the Python implementation's, plus 6,000 fuzzed values incl. error cases, compared for type and message).
2. **`_bounds`** (profile: 2,315 calls, 12.7 s self). The 9x call count was the geometry-interface label measuring
   every solid, shell and wire on top of its faces and edges. `AddOptimal` measures each face and edge on its own,
   so a solid / shell / wire box is the union of the boxes of its faces / edges: bitwise equal on all 185 solids and
   2,204 wires of arm6, so fingerprints are unchanged. The descriptor now measures each face and edge once
   (6,832 face leaf calls instead of 29,059 `_bounds` calls). The cost per call is the trimmed torus faces of the
   ball bearings (13 ms each, OCCT's generic path); everything else is below 0.1 ms. `_bounds` also memoises face
   boxes on (TShape, Location) with the TShape held (8192 entries, cleared when full).
3. **`attach_graph_node`** (profile: 108 calls, 7 s self): a profiler artefact. Timed inside the function over a
   whole cold + edits run: 750 calls, 3 ms in total. cProfile bills native method calls (invisible to it) and GC
   to whichever Python frame is running. Nothing to fix; no change made.
4. **Normal run, UPPER_LENGTH 24.2 s -> 15.6 s (ocp 18.9 s).** The workers were not the problem (worker start 0.45 s
   native vs 1.2-2.1 s ocp for `import simplecadapi`; the pickle of a Part with 12 holes is 67 KB, 0.6 ms dump /
   0.5 ms load, ocp 40 KB, 2.6 / 0.5 ms). The parent, restoring what the workers built, fingerprinted every Part
   body twice (`encode_topology_snapshot` and `InterfaceHashes`) and again in `project_product`, at 0.15 s each:
   `geometry_interface_fingerprint` is memoised per (OCCT shape identity, tolerance profile) with the solid held in
   a 64-entry LRU (`Shape._shape_key`: TShape address, orientation, location transform). 44 -> 23 descriptor
   computations in that edit.
5. `build/keys.py generator_profile()` called `importlib.metadata.version` (email parser over the dist-info) on
   every cell digest: 1,016 calls, ~1 s of parent cpu in cold; cached with `functools.lru_cache`.

Not done: `_semantic_index` / `capture_result` natively (1.1 s each, cold only); kernels (`cut_rsolid` 13 s of the
75 s profile) untouched.
