# simplecadapi native engine

The geometry engine of the `simplecadapi` Python SDK, written in C++20 on OpenCASCADE (OCCT). Everything from the OCCT
calls up to the operator layer (shapes, tags and lineage, operators, constrained sketches, parts and assemblies, the
selector language, the reactive parameter graph, import/export, a software renderer) lives here and is shipped inside the
`simplecadapi` wheel as one pybind11 extension, `simplecadapi._cpp._native`, with a thin Python package
(`src/simplecadapi/_cpp`, `src/simplecadapi/_glue`) around it. It keeps the names, arguments, results and error text of
SDK 2.2.6; it removes the cost of the old Python wrapper tree and of OCP.

The layers that are still Python (notebook runtime, editor, inspection, translators, scene, artifacts) run on top of it
unchanged.

## Where to start

| You want to | Read |
|---|---|
| understand the design and the layer rules | [ARCHITECTURE.md](ARCHITECTURE.md) |
| build it, run the tests, follow the rules for a change | [CONTRIBUTING.md](CONTRIBUTING.md) |
| review the code in a sensible order, find the Python module and tests of each area | [docs/READING_ORDER.md](docs/READING_ORDER.md) |
| see how the initial commit is meant to be landed as small pull requests | [docs/LANDING_PLAN.md](docs/LANDING_PLAN.md) |
| know where the native engine differs from 2.2.6 on purpose | [docs/DEVIATIONS.md](docs/DEVIATIONS.md) |
| see the latest test results and the open items | [docs/NATIVE_PROGRESS.md](docs/NATIVE_PROGRESS.md) |

Other documents in `docs/`: `io.md` (serialization format and exchange), `render.md` (software renderer),
`sketch-solver.md` (the in-house sketch solver), `memory.md` and `PERF.md` (measurements), `OCCT_BINDINGS.md` (the raw
OCCT classes exposed as `simplecadapi._cpp.occt`), `NATIVE_INTEGRATION.md` (the historical plan for running the SDK on this engine), `briefs.md` (historical per-area work orders),
`research/smlib-usd-brep.md` (evaluation of an optional curve/surface kernel).

## Layout

```
include/scad/<area>/   public C++ headers
src/<area>/            implementation, one static library scad_<area> per area
tests/cpp/<area>/      doctest executable test_<area>
bindings/python/       pybind11 module, one bind_<area>.cpp per area; occt/ is the raw OCCT class binding
tests/python/          parity tests against goldens recorded from the 2.2.6 SDK (tests/golden/)
cmake/  tools/  scripts/  third_party/ (doctest, occ_gordon)
```

Areas: `core`, `kernel`, `topo`, `semantic`, `reactive`, `io`, `ql`, `render`, `sketch`, `surface`, `ops_geometry`,
`ops_features`, `product`, `std` (dependencies: ARCHITECTURE.md).

## Build in one line

From the repository root: `uv sync --locked --group dev` builds the module and the Python environment. Direct CMake
builds, the static OCCT used by releases, the test layers and the formatting rule are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Platforms

Release wheels are built for Linux x86_64 and aarch64, macOS arm64 and Windows x86_64, for Python 3.10 to 3.13, against
one static OCCT 7.9.3 (`.github/workflows/release.yml`). The regular CI (`.github/workflows/ci.yml`) runs on Linux x86_64.
Development is done on macOS arm64 and Linux x86_64; the other targets are built only by the release workflow.
