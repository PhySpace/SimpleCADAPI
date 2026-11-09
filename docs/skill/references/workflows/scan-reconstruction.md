# Workflow: Scan Reconstruction

Rebuild an editable SimpleCAD model from a physical part that exists only as a mesh (STL, OBJ, PLY), a point cloud, or
photos/images. The model is judged against the scan by tolerance, never by topology identity. This workflow is very
likely run unattended; the report and the evidence tiers are first-class.

## Goal and scope

Use when the deliverable is an editable, replayable model of a part and the only source is scan data or pictures. Not
for a STEP/BREP source (`workflows/step-reconstruction.md`), not for a vector-PDF drawing
(`workflows/drawing-reconstruction.md`), not for exporting a model to STL (`workflows/export-and-translation.md`).

## Read now (one parallel batch)

| File | Why |
| --- | --- |
| `workflows/scan-reconstruction.md` | this page: what the SDK supports, evidence tiers, steps, gates |
| `domains/step-inspection.md` | the inspection and comparison primitives that run on the candidate |
| `domains/part-modeling.md` | building the candidate part |

## Read when

| When | File |
| --- | --- |
| step 1: the request leaves units, purpose or fidelity open | `domains/requirement-refinement.md`, `discipline/requirement-and-cad-brief.md` |
| step 2: choosing the part-local frame and datums | `discipline/datums-and-coordinate-systems.md` |
| step 4: inferring feature families and provenance rows | `workflows/step-reconstruction.md`, `docs/guides/reconstruction-agent-strategy.md` |
| step 5: authoring the candidate source | `workflows/single-part-modeling.md`, `discipline/feature-tree-convention.md`, `docs/guides/notebook-runtime.md` |
| step 5: constraints represent the evidence | `domains/sketch-and-features.md` |
| step 5: the shape is freeform (lofts, B-spline sections, point grids) | `docs/api/loft_rsolid.md`, `docs/api/fit_cubic_bspline_control_points.md`, `docs/api/fit_point_grid_rface.md`, `docs/api/sew_faces_rshell.md`, `docs/api/make_solid_from_shell_rsolid.md` |
| step 6: comparing, or a comparison fails | `discipline/geometric-validation.md`, `discipline/failure-and-repair.md` |
| the part is a standard component | `domains/standard-parts.md` |
| the scan is one part of a product | `workflows/assembly-product-build.md` |
| delivering a package or STL | `docs/guides/product-export.md`, `domains/export-and-translation.md` |

## Unattended mode

| Interactive gate | Unattended replacement |
| --- | --- |
| Step 1: ask the units, the scale, the part's purpose, which features matter, the tolerance, parametric model vs shape match | Record each as an assumption in the ledger. Units: the file's header if it has one, else the unit that makes the part's size plausible, tier `[assumed]`. Tolerance: derived from the scan's own resolution (step 1), stated before any comparison |
| Step 1: consent gate on the brief | Self-review: re-read the brief against the request and the evidence, write one paragraph of decision with the open risks; go on only when every field is filled (a recorded assumption fills a field) |
| The source is missing, unreadable, or has no scale (photos, unitless point cloud) | Record the blocker in the report; do the strongest work the evidence supports and say which parts it supports; never invent dimensions or a scale |
| Step 3: noise or a bump the scan cannot tell from a feature | Treat as a feature only when it appears in at least two independent measurements; otherwise omit it and list it as uncertain |
| Step 4/5: a choice between analytic features and a freeform surface | Take the one that meets the tolerance and is easier to edit; record the other in the plan |
| Step 6: a person looks at the comparison renders | Look yourself: name the views, what you looked for, quote the observation; the numeric comparison still decides |
| A second reviewer of the verdict | Fresh-context checklist pass quoting observations (subagent if offered); otherwise the report says the review was not independent |
| Mesh libraries (`trimesh`, `numpy-stl`) are not installed | Use the numpy intake in step 1; the report says which checks were done by hand-written script |
| The same comparison fails twice for the same cause | Change the feature hypothesis or redefine the check in the report; never loosen the tolerance silently (`discipline/failure-and-repair.md`) |
| Closing message to the person | The report (step 8) |

## What the SDK supports and what it does not

Checked against `src/simplecadapi` and `references/docs/api`. Where a row says "not supported", no function exists; do not
guess one.

| Step | Supported by the SDK | Not supported |
| --- | --- | --- |
| Read a mesh (STL/OBJ/PLY) or point cloud | nothing | no mesh or point-cloud importer; STL/OBJ are export-only (`export_product_package_to_stl`, `export_product_package_to_obj`). Read the file with your own numpy code (step 1). `trimesh` and `numpy-stl` are in the dev dependency group only, so check with `python -c "import trimesh"` before relying on them |
| Read photos or images | nothing | no image-to-geometry, no photogrammetry. `inspect.drawing` reads vector PDF only; raster images are "no supported route" (`domains/drawing-inspection.md`). Looking at an image is your host's vision, not an SDK step |
| Mesh to BREP, mesh to STEP, remeshing, smoothing, hole filling of a mesh | nothing | none of it. A mesh cannot become a solid by an SDK call. `fill_holes_rshell` and `sew_faces_rshell` act on BREP faces and shells, not on mesh triangles |
| Sections, dimensions, fits of the scan | nothing | the section and measurement tools (`inspect_section_rdescriptor`, `measure_model_section_rdimensions`, `fit_face_analytic_rdescriptor`) take a BREP model, STEP or shape, never a mesh. Cut, measure and fit the scan with your own numpy code |
| Curve and surface fitting from sampled points (your own samples) | `fit_cubic_bspline_control_points` (ordered 2D/3D samples to a cubic B-spline with an error), `fit_point_grid_rface` (rectangular 3D grid to a B-spline face), `make_spline_rwire`, `make_interpolated_spline_rwire`, `add_bspline_rsketch` | scattered (unordered) point sets: order and grid them yourself first |
| Build solids from the evidence | `extrude_rsolid`, `revolve_rsolid`, `sweep_rsolid`, `loft_rsolid`, `sweep_multisection_rsolid`, booleans, `make_polyline_rwire`, `make_face_from_wire_rface`, `sew_faces_rshell`, `make_solid_from_shell_rsolid`, sketches (`domains/part-modeling.md`, `domains/sketch-and-features.md`) | a faceted solid from thousands of triangles is composable from the polyline, face, sew and solid functions above, but it is neither editable nor a reconstruction; do not deliver it as one |
| Inspect and render the candidate | `inspect_shape_rbrepinspection`, `measure_shape_mass_rtuple`, `render_shape_views_rpath`, `render_screenshot_rpath`; after export, the STEP tools of `domains/step-inspection.md` | rendering the scan itself (use matplotlib, a core dependency, in your own script) |
| Compare candidate with scan | export the candidate to STL (`export_product_package_to_stl`) and compare in your own script (step 6) | no mesh-vs-BREP distance, no scan-vs-model section diff, no `compare_*` tool that accepts a mesh |
| Delivery | `sca run`, `capture`, package and exports (`docs/guides/product-export.md`) | |

## Evidence tiers

Every dimension, feature and statement in the brief, the provenance rows and the report carries one tier mark. They
follow the drawing workflow's idea (what you read, what you attributed, what you derived) with scan-specific meaning.

| Mark | Tier | Meaning | How to cite |
| --- | --- | --- | --- |
| `[measured]` | measured | a number your script computed from the file: bounding box, a section width, a hole diameter from a vertex ring, mesh volume | script path, the plane or vertex set, the printed value |
| `[fitted]` | fitted | a parameter from a fit with a residual: cylinder radius, plane normal, spline control points | the fit, the point count, the residual and the tolerance it was judged against |
| `[inferred]` | inferred | design intent read off the shape: symmetry, a round number, a standard size, a pattern count | the measurements it rests on and the check that could show it wrong |
| `[assumed]` | assumed | no evidence: units without a header, a hidden side, any photo dimension without a known reference, scale | the ledger row: `value / evidence / how to change it / the check that would show it wrong` |

Rules: a photo gives `[assumed]` dimensions unless the request supplies a reference length, and then at best
`[inferred]`; a point cloud gives no volume; only `[measured]` and `[fitted]` values may close a gate; rounding a measured
value to a design value is `[inferred]`, and the measured value stays in the row.

## Steps

1. **Intake and brief.** Decide the mode (`discipline/operating-modes.md`). Read the source with your own script and print
   facts before any interpretation: format, triangle and vertex counts, bounding box, units (STL has none; OBJ rarely; PLY
   may say in its header), open and non-manifold edges, signed volume, whether normals agree. A working numpy reader for
   binary and ASCII STL, tested on a box:

   ```python
   """Facts about a mesh file, by plain numpy: nothing here is SimpleCADAPI."""
   import sys
   import numpy as np

   def read_stl(path):
       raw = open(path, "rb").read()
       n = int.from_bytes(raw[80:84], "little")
       if len(raw) == 84 + 50 * n:                      # binary
           rec = np.frombuffer(raw[84:], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
           return rec["v"].astype(float)                # (T, 3, 3)
       v = [list(map(float, l.split()[1:4])) for l in raw.decode().splitlines() if l.strip().startswith("vertex")]
       return np.array(v).reshape(-1, 3, 3)             # ascii

   tri = read_stl(sys.argv[1])
   pts = tri.reshape(-1, 3)
   uniq, inv = np.unique(np.round(pts, 6), axis=0, return_inverse=True)
   f = inv.reshape(-1, 3)
   edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
   _, cnt = np.unique(edges, axis=0, return_counts=True)
   vol = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
   print("triangles", len(tri), "vertices", len(uniq))
   print("bbox min", uniq.min(0), "max", uniq.max(0), "size", np.ptp(uniq, axis=0))
   print("edges used once (open)", int((cnt == 1).sum()), "used >2 (non-manifold)", int((cnt > 2).sum()))
   print("signed volume", vol, "(valid only if watertight and consistently oriented)")
   ```

   The brief states the purpose, units and how they were decided, the tolerance, what fidelity is wanted (editable
   parametric model, or shape match), and the features that matter. Derive the tolerance from the scan, not from hope:
   no tighter than the vertex spacing or the scanner's stated accuracy, and write it down before step 6.
   Interactive: ask once, batched, then consent gate on the brief. **Unattended:** record every open field in the ledger
   and run the self-review gate (table above).
2. **Fix the frame.** Choose the part-local frame and datums (`discipline/datums-and-coordinate-systems.md`): align to
   the bounding box or to the principal axes only when the shape supports it, and put the origin on a datum the part
   defines (a bore axis, a mating face), not on the scan's arbitrary origin. Record the transform that maps scan
   coordinates to part coordinates. Photos: no frame exists until a known length and a view direction do; say so.
3. **Measure the scan.** With your own script, cut the mesh at planes through the datums and at spacing that resolves the
   smallest feature you need (triangle-plane intersection, then chain segments into contours); print contour extents,
   enclosed areas, hole diameters and centres, wall thickness. Fit analytic carriers to vertex clusters (plane, cylinder,
   sphere) with residuals. Store the arrays in files, not in the conversation. Every number gets a tier mark.
   **Unattended:** a feature counts only when two independent measurements show it; the rest is listed as uncertain.
4. **Infer the feature tree.** Reuse the family table of `workflows/step-reconstruction.md` (revolve, extrude, sweep,
   loft, pattern, mixed) and write one provenance row per region: observed section behaviour, proposed operation and
   axis, tier, confidence, the check that could falsify it. Verify repetition and symmetry on at least two units before
   patterning. A region the scan cannot resolve (hidden, occluded, below the tolerance) is a gap, recorded as such.
   **Unattended:** between analytic features and a freeform surface take the one that meets the tolerance and is easier
   to change; record the other.
5. **Build the candidate** via `workflows/single-part-modeling.md` (block structure per
   `discipline/feature-tree-convention.md`): analytic features first, named parameters for the measured dimensions,
   freeform sections only where the evidence is freeform. Overshoot through-cut tools; validate one representative
   feature before patterning. Run it with `sca run` and load its product with `run_notebook`.
6. **Compare with the scan, in your own script.** Export the candidate (`sca run <part>.py --out out/<part>.scadpkg`,
   then `export_product_package_to_stl` with a deflection well below the tolerance) and read the STL with the step-1
   reader. Compare, with the tolerance fixed in step 1:
   - bounding box and volume (candidate volume from `measure_shape_mass_rtuple` or the package; scan volume only if
     watertight);
   - the step-3 section planes: contour extents and areas, scan against candidate;
   - sampled distance from scan vertices to the candidate's tessellation, as max, mean and the share beyond tolerance,
     and the regions where it is beyond tolerance.
   Print one table, one row per check. Render the candidate with `render_shape_views_rpath` and the scan with
   matplotlib from the same views. **Unattended:** look at both yourself and quote the observation.
   A failed row is closed by changing the feature hypothesis, or by redefining the check in the report with the reason;
   never by loosening the tolerance without saying so. Keep the best valid candidate; repeated non-improvement changes
   the hypothesis instead of the parameters (`discipline/failure-and-repair.md`).
7. **Accept by tier.** Topology identity does not exist for a scan, so it is never claimed.
   - **A:** every comparison row is within tolerance and every feature in the tree is `[measured]` or `[fitted]`.
   - **B:** within tolerance except listed regions, or some features are `[inferred]`; each is named.
   - **C:** a functional approximation with listed unrecovered regions or `[assumed]` dimensions that matter.
   Photos-only and point-cloud-without-scale runs cannot reach A. The report states the tier reached and why.
8. **Report.** Unattended: write `report.md` next to the source (`discipline/operating-modes.md`) with the sections below;
   interactive: the same content in the closing message.

## Validation gates

Each binds an artifact, in both modes.

- The intake facts, the transform to part coordinates and the tolerance exist as printed output or files before step 3.
- Every dimension in the candidate traces to a provenance row with a tier mark; no `[assumed]` value hides in a parameter.
- The candidate replays in a fresh process (`export_model_json` then `replay_model_json`) and its STEP export passes
  `validate_step_roundtrip_rdescriptor`.
- The comparison table of step 6 exists, ran against the fixed tolerance, and its failing rows are explained.
- Global similarity never overrides a locally falsified feature.

## Failure routes

- The scan is open, non-manifold or has no consistent orientation: volume and watertight claims are dropped (report the
  numbers you could not trust); sections and fits may still be used.
- No affordable evidence for a region: record the gap; do not invent geometry and call it recovered.
- Candidate disagrees with scan in one region only: re-open that feature's hypothesis, not the whole tree.
- A needed capability is not in the table above: report it as not supported and continue with the evidence that exists.

## Report

Unattended default `report.md`; it lists, as `discipline/operating-modes.md` requires:

- the assumption ledger (units, scale, tolerance, hidden regions, intent), each row with its tier;
- what was reconstructed, omitted and uncertain, one line per feature with its tier mark;
- the step-6 comparison table and the acceptance tier reached;
- which checks were done by hand-written scripts (the SDK has no mesh tools), with the script paths;
- checks not run, with the reason, and any review that was not independent;
- the commands that reproduce the result.
