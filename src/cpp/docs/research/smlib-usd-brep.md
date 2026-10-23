# Can SMLib (NVIDIA usd-brep) strengthen our OCCT curve/surface layer?

Evaluated 2026-10-21 against `NVIDIA-Omniverse/usd-brep` @ `c9c5979` (VERSION 1.0.0,
committed 2026-10-09). Everything below marked **measured** was run on macOS arm64 with
Apple clang 21 and OCCT 7.9.3 (the probe is in `tools/research/smlib_probe/`). Everything
marked **read** comes from the repository text. Nothing here was tested on Windows or Linux.

## What it is

- SMLib (ex Solid Modeling Solutions, acquired by NVIDIA 2022) open-sourced as part of
  `usd-brep`, **Apache-2.0** (read: every inspected source file carries
  `SPDX-License-Identifier: Apache-2.0`; `THIRD_PARTY_NOTICES.md` lists OpenUSD (TOSL 1.0),
  oneTBB (Apache-2.0), hwloc (BSD-3)).
- The kernel is `source/SMLib` (224 `.cpp`, 238 headers, ~39 MB of source) on top of NLib
  (`NL_*.h`: Piegl/Tiller-style NURBS curve/surface fitting, offsetting, approximation,
  knot removal, least squares) plus `source/SM_API` (a C-style façade, 29 files).
- Capabilities relevant to us (read): interpolation/approximation with tangent and
  boundary constraints (`N_FitSrfInterpBoundary`, `N_FitSrfApproxTol`,
  `N_FitSrfApproxTangentsTol`, ...), skinning, sweeps, offset curves/surfaces,
  `SmApiConvertToLinesAndArcs`, `SmApiMakeCurvesCompatible`, `SmApiRemoveCurveKnots`,
  blend surfaces, B-spline volumes with bend/twist/space-bend (free-form deformation),
  fillets, booleans, healing.

## What we established

| Question | Result |
|---|---|
| Does the kernel build without NVIDIA's tooling? | **Measured: yes.** 237 translation units (SMLib + SM_API) built with a 20-line CMake file, Release, **0 errors**. Only dependency: oneTBB (5 files use it). No OpenUSD, no Packman, no premake. Static library: 17.6 MB unstripped. |
| Can it live in the same process as OCCT? | **Measured: yes.** Linked into one binary with OCCT 7.9.3 libraries: no symbol clash, ran correctly. The probe keeps the two worlds in separate translation units (SMLib headers define macros like `ULONG`); the real adapter must do the same. |
| Can geometry move between them? | **Measured: yes, losslessly.** SMLib's `GetControlPointNet` + `GetKnots` (unique knots + multiplicities) map one-to-one onto `Geom_BSplineSurface`'s constructor. An SMLib surface became a valid OCCT face (`BRepCheck_Analyzer` valid) with max deviation **3.8e-13** from the data. ~40 lines. |
| Is NVIDIA's own OCCT bridge reusable? | **Read: no.** `OCCT_BREP_IMPORT/EXPORT` converts OCCT `.brep` files to/from OpenUSD staging types (`pxr::GfMatrix4d`, ...). The converter is welded to OpenUSD. |
| Is it better than OCCT for gridded surface fitting? | **Measured: no clear win.** 30x30 grid of a wavy surface. SMLib interpolation: 30x30 poles, dev 3.8e-13. OCCT `GeomAPI_PointsToBSplineSurface` degree 3, tol 1e-3: **24x24** poles, dev 8.6e-4 (within tol) -- *more compact*; OCCT interpolation: 32x32, dev 1.4e-15. (An earlier run with OCCT at degree 3..8 + C2 gave dev 0.17; that was a poor parameter choice on my part, not an OCCT defect.) |
| Does it fit scattered (unordered) points, which OCCT has no direct API for? | **Measured: only for tiny inputs.** `SmApiCreateSurfaceFromRandomPoints`: 50 points 88 ms (25x25 poles); 100 points **6.0 s** (50x50 poles); 200 points did not finish in 40 s. The pole count grows as n^2/4 and time roughly as n^6. Not a scalable tool in this form. Other NLib entry points (least squares, tolerance + knot removal) were **not** tested. |
| Can SMLib calls run concurrently? | **Read, from NVIDIA's header:** no. "Use one worker process per concurrent job." Shared default `SmContext` with unlocked counters; lazy init is not synchronized. This directly conflicts with our goal of releasing the GIL and running ops on threads. |

## Risks

- **Young.** 1.0.0, two weeks old. `KNOWN_ISSUES.md` lists healing that mis-repairs
  periodic/closed surfaces (tori, spheres, cylinders), `remove_fillet` that removes nothing
  and reports success, `heal_brep` that reports success on failure, and face area/volume
  errors up to ~1.4% for faces bounded by rational circles at default accuracy.
- **No outside contributions** ("currently not accepting contributions"): a defect we hit
  means a private fork, not an upstream fix.
- **Build/platform.** NVIDIA's build is premake5 + Packman; the macOS premake package "is
  not on the public Packman server either". The README documents Linux x86_64, macOS
  universal (Apple Silicon only) and Windows (VS2019 toolset pinned). Linux aarch64 is not
  mentioned. Our own CMake works on macOS arm64 (measured); the other three targets are
  untested.
- **Size.** +17.6 MB unstripped static (before LTO/strip) on every wheel if linked always.

## Recommendation

**Do not fuse at the B-rep level, and do not make SMLib a default dependency.** OCCT keeps
topology, booleans, fillets and healing. SMLib is at most an *optional geometry provider*:
it returns NURBS curves/surfaces, we convert them to `Geom_BSpline*` and OCCT builds faces
from them. That path is proven above and keeps SMLib's topology, tolerance model and known
healing bugs out of our solids.

Concretely, when the surface family is ported:

1. Define a narrow `SurfaceProvider` / `CurveProvider` interface in `scad::surface` with the
   OCCT implementation as the default.
2. Add `SCAD_WITH_SMLIB` (default OFF): builds SMLib+SM_API from a pinned checkout with our
   own CMake, in its own static library and its own translation units, behind one global
   mutex (or a worker process) because of the concurrency rule.
3. **A/B before adopting.** Candidates where SMLib plausibly beats OCCT, each to be measured
   on our own tests rather than assumed: tolerance-driven approximation with knot removal,
   boundary- and tangent-constrained fitting (our `make_surface_patch_rface`,
   `make_gordon_surface_rface`, `loft_rshell`), curve offset, `ConvertToLinesAndArcs`,
   curve compatibility for lofts, and NURBS surface offset (OCCT's offset surface is not
   NURBS). Adopt an operation only where it wins on accuracy, pole count, or robustness.
4. Free-form deformation (B-spline volumes, bend/twist) is the one capability family OCCT
   has no counterpart for. If the product wants it, that is the strongest reason to carry
   SMLib; it is untested here.

## Reproducing

```
GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 https://github.com/NVIDIA-Omniverse/usd-brep /tmp/usdbrep/repo
mkdir -p /tmp/usdbrep/smlib-try && cp tools/research/smlib_probe/CMakeLists.smlib.txt /tmp/usdbrep/smlib-try/CMakeLists.txt
cmake -S /tmp/usdbrep/smlib-try -B /tmp/usdbrep/smlib-try/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=/opt/homebrew
ninja -C /tmp/usdbrep/smlib-try/build     # libsmlib.a + libsmapi.a, ~3 min on 8 cores
```
The CMake file hard-codes `/tmp/usdbrep/repo/source` as the checkout location.
`tools/research/smlib_probe/{sm_side,main}.cpp` is the probe; it is two translation units on
purpose. Not part of the build.
