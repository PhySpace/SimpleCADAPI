# Memory: Python SDK vs the C++ port

Measured 2026-10-21 (box, fillet rows re-measured 2026-10-22 after the compaction work; gear row not re-measured) on macOS arm64 with `tools/bench/bench_memory.py` (one case per fresh
process, N objects kept alive, RSS from `ps`, delta after one warm-up object). The port is a
Release build; the reference is the Python SDK on OCP 7.9.3. Single runs, not averaged.

| Case | Python SDK | C++ port | Ratio |
|---|---|---|---|
| Process after `import` | 279-360 MB | 43-44 MB | ~8x |
| `make_box_rsolid` (2000 kept) | 206 KB / object | 26.3 KB / object | 7.8x |
| box + every face/edge touched (1000 kept) | 244 KB / object | 26.3 KB / object | 9.3x |
| box filleted on all edges (200 kept) | 759 KB / object | 113.3 KB / object | 6.7x |
| spur gear, 20 teeth (20 kept) | 1818 KB / object | 1004 KB / object | 1.8x |
| bare OCCT box, no SDK layers (floor) | 12.3 KB | 15.3 KB | - |

The same runs gave speed (Release, per object): box 25x, spur gear 19.5x faster than the SDK (measured before the compaction work).

## How to read it

- **The floor is OCCT itself**: a bare box is 12-15 KB in both. The SDK adds ~194 KB per box
  (17x the floor); the port now adds ~14 KB (2x the floor; it was ~62 KB), and 55 KB on a
  filleted box (floor 58 KB).
- **The import figure is mostly dependencies**, not wrapper design: the SDK process also loads
  marimo, plotly, rich, jsonschema and others. Do not quote the 8x as an implementation gain.
- **Heavy shapes converge** (gear 1.8x): their memory is OCCT geometry, which both share.
- Touching all faces and edges costs the port nothing extra (77.0 vs 76.8 KB): the entities are
  created when the shape is tagged at construction, not when enumerated.

## Where the cost went, measured (2026-10-22), and what was done

The earlier lead ("tag bindings dominate") was only part of it. A live-bytes-by-call-stack profile
(`tools/bench/probe <case> N prof`, build with `-DSCAD_BUILD_BENCH=ON`) put the 75.7 KB of a box
at: tracking payload Values 34 KB, OCCT 13.5 KB, `auto_tag_faces` 13.5 KB, `apply_tag` 8 KB,
registry 7 KB. After compacting bindings, packing the rarely read metadata and trimming entities
(`docs/DEVIATIONS.md` has every step, the measurements and the list of ids that were and were not
changed): box 26.0 KB (floor 12.1), filleted box 112.6 KB (floor 58.3, was 289.7), box cut by a
cylinder 37.0 KB (was 92.5). Fillet of all edges takes 4.9 ms (bare OCCT 3.8; was 7.2: 41% of it was
a precise volume check). The reactive recorder adds 6 KB per box and 112 KB per all-edges fillet.

Reproduce: `cmake -DSCAD_BUILD_BENCH=ON ...; ninja probe; probe box 2000; probe time fillet 300;
probe wall cut 200; probe box 500 prof 30; probe fillet 5 peak; probe sizes`.

## Not measured

Windows and Linux; peak (not retained) memory while building; memory under the reactive
graph recorder; fragmentation over long sessions; a static-OCCT wheel (the module is 5.7 MB
dynamically linked against Homebrew OCCT; a static build will be larger on disk).
