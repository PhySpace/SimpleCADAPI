# OCCT fillet-robustness-4

How to modify the kernel systematically (layout, strategy branches, SDK exposure, workflow, pitfalls): [GUIDE.md](GUIDE.md).

Base: OCCT V7_9_3, commit `a016080bf6738d6aeae020badee4e888ad1540a5`.

`0001-tangent-end.patch` backports the algorithm changes published in [OCCT PR 1642](https://github.com/Open-Cascade-SAS/OCCT/pull/1642) by Angelo Bartolomé: classify exactly one tangent endpoint edge as `OnSame`, recenter periodic coordinates, and ignore seam endpoint touches/parallel extrema. It does not claim to fix the limitations listed in that PR. OCCT source remains under its LGPL-2.1-with-exception terms; see the upstream LICENSE_LGPL_21.txt and OCCT_LGPL_EXCEPTION.txt delivered with the source. No source from solidcore is copied.

`0002-root-solid-orientation.patch` is this project's fix for equivalent solid representations: distribute a reversed solid root's orientation to its immediate children before building ancestry maps. Geometry and child TShape identities remain intact. It fixes valid sewn pyramid fixtures where reconstruction formerly returned negative-volume invalid output.

`0003-tangent-corner-boundaries.patch` reconstructs a four-boundary corner
between two tangent fillet contours when the Plate-to-BSpline approximation
exceeds its target. It preserves boundary geometry, uses an invertible cubic
Hermite law for endpoint compatibility, and builds same-parameter pcurves with
endpoint-dense adaptive interpolation and `GeomLib_CheckCurveOnSurface` checks.
The new corner also checks its support-normal agreement before reconstruction.
Independent acceptance rejected the previous patch (`b18e7b67...`) for a real
interior self-intersection in R100/r5 despite boundary/STEP checks passing. That
exact patch remains frozen in `benchmarks/fillet/results/` with the report.

The current candidate adds OCCT self-interference checking before inserting
the corner surface, and a failed replacement stops the operation instead of
falling back to the inaccurate Plate. R100/r5 is therefore refused. This closes
an unsafe return, not the original fillet request. The SDK independently checks
generated spline corner faces and exact output validity. These checks are
numerical diagnostics, not a proof that every possible self-intersection is
excluded. The same-radius nonfolding construction, material semantics, general
inset handling and production release remain unfinished.

`0004-fillet-y-patch.patch` adds the strategy entry points to `BRepFilletAPI_MakeFillet`: `SetYPatch` (Y transition
first), a default fallback (standard algorithm first; at a detected concave/convex tangent junction whose standard
result fails, is invalid or self-intersects, the junction strategy replaces it), `NbYPatches`, `YPatchJunction`,
`YPatchFallback`, and history (`Generated`/`Modified`/`IsDeleted`) answered from the strategy's own history.

Overlay classes (compiled into their toolkits by `occt_patches.install_overlay`):

| Class | Toolkit | Role |
| --- | --- | --- |
| `BRepFilletAPI_YPatch` (+ `YPatchGeom`, `YPatchBuild`) | TKFillet | junction detection, Y transition and pinch corner, gates, history |
| `BRepOffsetAPI_GraphPatch` | TKOffset | degree-8 graph patch over an ordered C0/G1/G2 loop, continuing curved supports |
| `BRepFilletAPI_RibbonFit` | TKFillet | four-sided fairing on callbacks (research API) |
| `BRepFilletAPI_TangentY` | TKFillet | canonical plate/post Y (research sample; superseded by `BRepFilletAPI_YPatch`) |

Kernel-level checks: `tests/` (see `tests/CMakeLists.txt`).

`manifest.json` locks every input and output file. `tools/occt_patches.py` checks those digests, validates all hunks, and only then writes. Reapplying is harmless; applying to another release or a locally modified target refuses explicitly.

Build the full kernel into a fresh prefix:

```powershell
python src/cpp/tools/build_occt.py --prefix <NEW_PREFIX> --work <BUILD_DIR> --jobs 4
```

Use `--unpatched` only to build the control kernel. The install records `share/simplecadapi/occt-build.json`; a prefix with another patch identity is rejected unless `--force` is specified. No existing system prefix is silently replaced.
