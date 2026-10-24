# Software renderer (`render` area)

Measured 2026-10-22 on macOS arm64 (8 cores), Release build, VTK 9.6.2 for the baselines. The machine was shared with
other builds while this ran: every timing is the **median of 7 runs** (warm: 7 calls after 2 discarded; cold: 7 fresh
processes), CPU time is process CPU (children included for cold runs). Reproduce with
`tools/bench/bench_render.py {compare,highlight,bench}` (run it with the SDK venv, native build on PYTHONPATH).

## What it is

`include/scad/render/render.hpp`; Python: `simplecadapi._cpp.RenderScene`, `render_scene(...)`, `RenderFrame`
(`rgba`, `depth`, `mesh_id`, `face_id`, per-panel projected anchors with visibility) and `simplecadapi._cpp.screenshot.render_screenshot`
(PIL text on top of the 3D layer, same keyword arguments as `render_screenshot_rpath`).

- Orthographic camera, VTK's `ResetCamera`+`Zoom(0.92)` fit, the SDK's view presets / `auto`.
- Deferred rasteriser: per band of rows the visibility (z, triangle, barycentrics) is resolved, then each pixel is shaded once
  (Phong with interpolated vertex normals, two-sided). Standard style = VTK headlight (ka .24 kd .72 ks .22 p28, specular tinted
  by the surface colour as `vtkProperty::SetColor` does); studio = the key/fill/rim rig of `_studio_lights`.
- B-rep edges: `edge_polylines()` (BRepAdaptor_Curve + GCPnts, no OCP), drawn as depth-tested capsules whose width is the
  VTK "ink" tube diameter (`edge_width_scale * span`) pulled toward the camera by its radius.
- Per-face colours (`face_colors[face_id]`), per-mesh opacity (back-to-front painter blend), line sets, point sets, corner axes.
- n x n supersampling (1..4) and a reduction that reproduces PIL's LANCZOS (horizontal then vertical, 8-bit intermediate).
- Outputs: RGBA, float depth (view distance, +inf = background), mesh id and face id per pixel (centre sample of each block),
  `Panel.project()`, and for every requested anchor its pixel, depth and `visible` (not behind the nearest surface at or next to
  its pixel, tolerance 0.2% of the span like `_view_ray_occluded`).
- Deterministic: bands are private to one worker and triangles are visited in index order; the doctests and
  `test_render_soft.py` compare 1/2/3/7/8 threads bit for bit.

Split: C++ = 3D layer, id/depth buffers, anchor visibility. Python (PIL) = title, legend, callout boxes and leader lines
(a port of `_add_geometry_callouts` placement), axis letters. Callout re-anchoring uses the id buffer: the nearest visible pixel
of the tag's own faces, else the callout is dropped for that panel.

## Benchmark (1400x900, SDK default: 4-panel studio grid, axes, includes tessellation and PNG encode)

Wall time, ms, median of 7. "soft" = `mesh + edges + render + PIL PNG save`, all in one warm process.
"VTK in-process" = the same native meshes fed to the SDK's own `_render_polydata_views_in_process` in a persistent process
(PNG written by VTK, supersample 2). "SDK path" = `simplecadapi.render_screenshot_rpath` (OCP backend, SCA_BACKEND unset: mesh in
the caller, one worker subprocess per call).

| Scene (triangles) | soft ss1 | soft ss2 | soft ss3 | VTK in-process ss2 | SDK path warm | soft ss2 cold process | VTK cold process | SDK path cold process |
|---|---|---|---|---|---|---|---|---|
| box (12) | 16.8 | 37.2 | 57.0 | 174.5 | 2844 | 192 | 3187 | 5328 |
| filleted box (2.4k) | 27.0 | 46.7 | 75.4 | 199.7 | 2834 | 214 | 3225 | 5335 |
| 20-tooth gear (20k) | 60.4 | 72.3 | 100.5 | 221.1 | 3115 | 261 | 3239 | 6897 |
| modeled bolt (27k) | 334 | 481 (noisy) | 347 | 431 | 2897 | 5288* | 7580* | 8185* |
| 30 gears (600k) | 1267 | 1337 | 1483 | 1562 | 6752 | 1672 | 5151 | 24438 |

Cold = whole fresh process: interpreter, imports, building the shape, first render, PNG. *The bolt rows are dominated by
building the modelled thread (seconds, in the module under test), not by drawing.
Breakdown, warm, ss2 (ms): box mesh 0.5 / raster 22.6 / PNG 14.1; gear mesh 34.6 / raster 22.1 / PNG 16; 30 gears mesh 1192 /
raster 137 / PNG 17; VTK on the same meshes: 174 / 182 / 370 ms for box / gear / 30 gears. Raster+shade at ss1 is 4 ms (box) to 14 ms
(gear) with 8 threads; at ss2 about half of the frame is the Lanczos reduction (gear: 19 ms raster + 16 ms resolve at 8 threads;
50 + 50 ms at 1 thread). CPU time of a soft ss2 frame is 3-4x its wall time (8 threads); VTK uses ~1 core.

Reading it honestly:
- The 2.3-5 s of the current path is process start + imports (+ OCP tessellation); against **VTK done right** (persistent process,
  warm) the soft renderer is **~4.7x faster on a box (37 vs 175 ms), ~3x on a gear (72 vs 221), ~1.2x on the 600k-triangle
  scene**, where tessellation dominates for both (1.2 s) and VTK's GPU-less drawing is not the bottleneck. It is **~75-90x faster
  than the current SDK path warm and ~25x cold-start** (192 ms vs 5.3 s).
- For heavy meshes the lever is no longer the renderer but tessellation (parallel faces already) or caching meshes between shots.
- Not measured: Windows/Linux numbers, GPU VTK, memory.

## Parity evidence (VTK in-process vs soft, same meshes; `docs/render/*.png` = VTK | soft | abs diff x4)

Text regions (titles, legend strip) are masked; silhouette = pixels differing from the empty-scene background by >12.

| Case | silhouette IoU | mean abs colour diff (px in both) | B-rep edge pixel F1 |
|---|---|---|---|
| box, studio, 4 views, ss2 | 0.9998 | 0.88 | 1.000 |
| filleted box, studio | 0.9998 | 1.42 | 0.984 |
| 20-tooth gear, studio | 0.999 | 1.89 | 0.955 |
| modeled bolt, studio | 0.9999 | 2.41 | 0.994 |
| gear, standard (gradient bg) | 0.997 | 1.84 | 0.950 |
| filleted box, standard, single view ss1 zoom 4 | 0.997 | 0.61 | 0.998 |
| highlight groups (2 coloured faces + coloured edge line), opaque context | 0.997 | 1.39 | 0.999 |
| same with 18% translucent context | 0.997 | 2.47 | 0.932 |

Edge F1 under 1 is ink-width/offset differences on dense curved edges (soft draws 4% more ink pixels on the gear).

## Capability inventory and status

"Tests" are what the SDK's tests assert today (render.py, render_worker.py, `test/test_render_screenshot_multiview.py`,
`tests/test_render_supersample.py`, `test_inspect_brep_queries.py`, `test_inspect_brep_manufacturing.py`,
`test_original_api_integration.py`). The SDK tests are weak: file exists / size > 0 / bytes differ / output size; none compares
pixels. The soft path is checked against VTK numerically (above) and by its own doctests.

| Capability | VTK path | SDK tests assert | Soft renderer | Status |
|---|---|---|---|---|
| Shaded faces, standard style | Phong, headlight, colour (.55,.64,.73), gradient bg, FXAA at ss1 | file written, >0 bytes; standard != studio bytes | same model; no FXAA (ss1 is aliased edge ink, ss>=2 matches) | works (compared) |
| Studio style | 3 lights (warm key/cool fill/rim) from camera pose, steel (.66,.68,.72) + specular, black bg | default style is studio; studio != standard | ported formulas | works (compared) |
| B-rep edge overlay, visible vs hidden | tube ink radius = span*0.0019, z-buffered: hidden edges never drawn | `_edge_polydata` of a box has 12 lines | capsule ink, depth-tested with radius bias; hidden ones absent (doctest) | works (compared) |
| Per-face / per-tag highlight colours | polydata group per tag, palette of 8 | highlighted_groups has 1 entry per tag | `face_colors` by face id, no extra meshes | works (compared opaque) |
| Legend (tags, +X/+Y/+Z, highlighted edges) | vtkTextActor boxes / side panel when >8 | legend[0][0] == "Body" (mocked) | PIL port, side strip handled in C++ (`legend_panel_fraction`) | works, text layout not pixel-compared |
| Tag labels and callouts, per-view occlusion suppression, re-anchoring | cell-locator ray per anchor; re-anchor to a visible sample of the tag's dataset; leader + label boxes | md5 with callouts != without, front and back views | anchors from the depth buffer, re-anchor from the id buffer, PIL boxes | works (ported test passes); layout not compared to VTK |
| Multiview grid | min(2,n) columns, one renderer per panel, <=4 views | grid called with views; size | same layout, per-panel camera | works (compared) |
| Axes | vtkAxesActor in a 20% corner viewport, labels | show_axes forwarded | thick lines + stepped cone in the same viewport, letters from PIL | partial (shape approximate, not compared) |
| Supersampling, output size | window at ss x size, PIL LANCZOS | output size == requested; ss 1..3 validated | same reduction in C++ | works (compared) |
| Zoom, view presets, "auto", view_up | ResetCamera + Zoom(.92), Zoom(zoom/4) single view | rejects bad presets | ported, parallel scale verified against VTK incl. portrait aspect | works |
| Background | gradient (standard) / black (studio) | - | same, overridable | works |
| Transparency (context opacity .12/.18, entity map .28) | depth peeling | file written | far-to-near painter blend per triangle, forward shaded | partial (2.5 MAD; a highlight line shows through context where VTK hides it) |
| Highlight edges / vertices (region, entity map, blend diagnostics) | line actors 4.5 px, point actors 15 px | file written | line and point sets, width in output px | works (opaque compared); widths on VTK/macOS are capped, soft honours them |
| XCAF / STEP colours | per-cell RGBA scalars | colours read back from the document, mesh has `STEP_RGBA` | `face_colors` accepts the RGBA | renderer ready; XCAF reading is not in the C++ port |
| Coloured components palette, entity map, region, manufacturing hint groups | many polydata groups, legend/callout | file written | same primitives (mesh groups, edge groups, point groups) | renderer ready; the inspect orchestration (BRepModel, XCAF selectors) stays Python and needs a thin port to build a `RenderScene` |
| Picking / exact occlusion | not available | - | `face_id`/`mesh_id`/`depth` buffers | new |
| Crash isolation, GL lock | subprocess + flock | `_run_render_worker` retry test | not needed (no GL) | n/a |
| Perspective camera | not used | - | not implemented | n/a |

## Remaining work to replace render.py

~1-2 days: wire `render_screenshot_rpath` to `screenshot.render_screenshot` behind the native backend (tag lookups already use
`_has_tag`); a `RenderScene` builder for the inspect family (`render_region_rpath`, entity maps, coloured components,
manufacturing hints, step comparison) which only needs shapes/faces/edges the module already exposes plus the XCAF colour
read (io area); polishing translucent context (order-independent blending for the highlight-edge case); axes cones; text
layout comparison against VTK screenshots (fonts differ: PIL vs VTK's FreeType) and a decision about the soft renderer at ss1
(no FXAA). Optional speed: the Lanczos reduction is half of an ss2 frame and can be vectorised or skipped over flat blocks.
