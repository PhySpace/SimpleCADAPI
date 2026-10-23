# SimpleCADAPI-cpp

The [SimpleCADAPI](../SimpleCADAPI) Python SDK, re-implemented below the Python boundary:
everything from the OpenCASCADE calls up to the operator layer is C++20, shipped as a single
pybind11 extension (`simplecadapi._cpp`) that mirrors the Python SDK's names and behaviour.

Why: the Python SDK is a heavy wrapper over OCCT (an eager wrapper tree on every shape, tag and
lineage bookkeeping in interpreted code). See [ARCHITECTURE.md](ARCHITECTURE.md).

Status of every operator: [PORTING_STATUS.md](PORTING_STATUS.md) (generated).
Working rules for contributors: [AGENTS.md](AGENTS.md).

## Targets

| Platform | Built and tested here | CI |
|---|---|---|
| macOS arm64 | yes | `ci.yml` |
| Linux x86_64 | yes (OrbStack Ubuntu 26.04 VM; it is x86_64) | `ci.yml` |
| Linux aarch64 | no | `ci.yml` (`ubuntu-24.04-arm`) |
| Windows x64 | no | `ci.yml` |

Only standard C++20 is used and compiler-specific switches live in `cmake/ScadCompile.cmake`,
but a platform that has not been built is unverified: treat Windows and Linux aarch64 as
"expected to work, first CI run decides".

## Build (development)

```bash
# macOS: brew install opencascade pybind11 cmake ninja
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python pybind11 pytest numpy
cmake -S . -B build/mac -G Ninja -DCMAKE_BUILD_TYPE=Debug \
  -DPython_EXECUTABLE=$PWD/.venv/bin/python \
  -Dpybind11_DIR=$(.venv/bin/python -m pybind11 --cmakedir) -DCMAKE_PREFIX_PATH=/opt/homebrew
ninja -C build/mac
ctest --test-dir build/mac --output-on-failure           # C++ (doctest)
SCAD_BUILD_DIR=$PWD/build/mac .venv/bin/python -m pytest  # Python
```

Linux: `apt install libocct-*-dev pybind11-dev ninja-build` (Ubuntu 26.04 ships OCCT 7.9.2),
same cmake line without `CMAKE_PREFIX_PATH`.

OCCT 7.8 or newer is required; the reference Python SDK runs on 7.9.3.

## Build (release wheels)

`tools/build_occt.py` builds OCCT 7.9.3 as static libraries the same way on every platform;
`pip wheel .` (scikit-build-core) links them into the extension, which then depends on nothing
but the Python it was built for. `cibuildwheel` drives this from `.github/workflows/wheels.yml`.

## Verifying behaviour

`tests/python/ref.py::golden(name, snippet)` runs `snippet` in the reference Python SDK
(`SCAD_REF_PYTHON`, default: the SimpleCADAPI checkout's venv), stores the answer in
`tests/golden/` and compares the C++ result to it on every platform.

## Research

[docs/research/smlib-usd-brep.md](docs/research/smlib-usd-brep.md): can NVIDIA's open-sourced
SMLib strengthen OCCT's curve/surface capability? (Measured on macOS arm64; recommendation inside.)
