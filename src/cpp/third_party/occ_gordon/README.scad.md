# occ_gordon (vendored)

Gordon surface interpolation for OpenCASCADE, by the German Aerospace Center (DLR).

- Upstream: https://github.com/rainman110/occ_gordon
- Version: 1.4.0 + commit b9520328f46aa76559e61471050734ab41d984e4 (the OCCT 8 `D2` compatibility
  change in `BSplineApproxInterp.cpp`; the only source delta since the 1.4.0 tag a03ee19).
- License: Apache-2.0 (`LICENSE.txt`); every source file keeps its SPDX header.
- Dependencies: OpenCASCADE only (Foundation, ModelingData, ModelingAlgorithms).

## Why vendored, and why patched

The reference SDK (`simplecadapi`) calls `ocp_gordon`, a Python port of this library.  The two
agree on the algorithm but not on a few constants, and the port added one guard that matters for
exactness.  Measured on a 6-patch wavy cube (area 6882.5098 per face in the reference): upstream
gives 6886.08 and cannot reproduce a straight edge exactly; with the patches below it gives
6882.51 and the sewn cube closes.  The patches are marked `scad patch Pn` in the source.

| Id | File | Change |
|---|---|---|
| P0 | `src/occ_gordon/exports.h` | new: static build, `OCC_GORDON_EXPORT` is empty |
| P1 | `BSplineAlgorithms.cpp` | `FitCurveOptimal(parameters, 10)` (upstream 1): the reference iterates the parameter optimisation up to 10 times |
| P2 | `InterpolateCurveNetwork.cpp` | skip the refit of a non-rational, non-periodic curve whose intersection parameters already equal the targets (keeps straight edges exact) |
| P3 | `InterpolateCurveNetwork.cpp` | duplicate-curve test at `PConfusion` (was `Confusion`); control-point cap 120 (was 80) |
| P4 | `BSplineAlgorithms.cpp` | `Geom2dAPI_Interpolate` coincidence tolerance 1e-6 (was 1e-15) |

Not carried over from `ocp_gordon`: zero-length (point) profiles and guides.  The SDK's public
`make_gordon_surface_rface` only accepts `Edge` objects, so it never passes one.

Building: `cmake/ScadGordon.cmake` compiles these files into `scad_occ_gordon` (option
`SCAD_WITH_GORDON`).  Third-party warnings are silenced for this target only.
