# Working rules (read before touching anything)

These apply to every contributor, human or agent. The owner of this repo is asleep or away
while work happens, so decisions are yours to make; write down any that are not obvious.

## Ownership

Each area owns its directories and nothing else:

| Area | Owns |
|---|---|
| semantic | `include/scad/semantic/`, `src/semantic/`, `tests/cpp/semantic/`, `bindings/python/bind_semantic.cpp`, `src/kernel/*` additions it needs |
| reactive | `include/scad/reactive/`, `src/reactive/`, `tests/cpp/reactive/`, `bindings/python/bind_reactive.cpp` |
| ql | `include/scad/ql/`, `src/ql/`, `tests/cpp/ql/`, `bindings/python/bind_ql.cpp` |
| io | `include/scad/io/`, `src/io/`, `tests/cpp/io/`, `bindings/python/bind_io.cpp` |
| sketch | `include/scad/sketch/`, `src/sketch/`, `tests/cpp/sketch/`, `bindings/python/bind_sketch.cpp` |
| surface | `include/scad/surface/`, `src/surface/`, `tests/cpp/surface/`, `bindings/python/bind_surface.cpp` |
| ops_geometry | `include/scad/ops/geometry/`, `src/ops/geometry/`, `tests/cpp/ops_geometry/`, `bindings/python/bind_ops_geometry.cpp` |
| ops_features | `include/scad/ops/features/`, `src/ops/features/`, `tests/cpp/ops_features/`, `bindings/python/bind_ops_features.cpp` |
| std | `include/scad/std/`, `src/std/`, `tests/cpp/std/`, `bindings/python/bind_std.cpp` |
| product | `include/scad/product/`, `src/product/`, `tests/cpp/product/`, `bindings/python/bind_product.cpp` |

Shared, owned by the lead: `CMakeLists.txt`, `cmake/`, `include/scad/{core,topo,kernel}/`,
`src/{core,topo,kernel}/`, `bindings/python/{bindings.hpp,module.cpp,common.cpp,bind_core.cpp,bind_topo.cpp}`,
`python/`, `tests/python/{ref.py,conftest.py}`, docs. If you need a change there, make the
smallest additive edit (new function, new overload) with the Edit tool, never a rewrite, and
say so in your final report. Do not rename or reorder existing declarations: other areas are
compiling against them right now.

Python tests live in `tests/python/test_<area>_*.py`. Golden files in `tests/golden/<area>_*.json`.

## Building (each person uses their own build directory)

```
# macOS arm64 (Homebrew OCCT 7.9.3)
cmake -S . -B build/<you> -G Ninja -DCMAKE_BUILD_TYPE=Debug \
  -DPython_EXECUTABLE=$PWD/.venv/bin/python \
  -Dpybind11_DIR=$($PWD/.venv/bin/python -m pybind11 --cmakedir) -DCMAKE_PREFIX_PATH=/opt/homebrew
ninja -C build/<you> scad_<area> test_<area>       # only your area; never build "all" while others are mid-edit
./build/<you>/tests/cpp/test_<area>
ninja -C build/<you> _native                       # the Python module (needs every area to compile)
SCAD_BUILD_DIR=$PWD/build/<you> .venv/bin/python -m pytest tests/python -q -k <area>
```

Build only your own targets; a sibling's half-written file must not stop you. Use a build
directory named after your area so builds never collide.

Linux (OrbStack Ubuntu, **x86_64**; same checkout path). Shortcut: `scripts/linux.sh <area>...` builds and runs `test_<area>` there (GCC 15 + libstdc++ assertions: it catches out-of-range reads, missing includes and deep-recursion overflows that macOS tolerates). Run it before you report. By hand:
`orb -m ubuntu bash -lc 'cd /Users/lildino/Project/ocws/SimpleCADAPI-native/cpp && cmake -S . -B build/linux-<you> -G Ninja ... && ninja -C build/linux-<you> test_<area>'`
(`build/linux-*` and `build/mac*` are different trees on a shared filesystem: never mix them.)

## Definition of done for an operator

1. Same name, same keyword arguments, same defaults, same result as the Python SDK (golden test).
2. Errors are `scad::Error` with the same operation name and guidance structure.
3. A doctest case (C++) and a pytest case (Python module) each.
4. Builds warning-free with `-Wall -Wextra -Wpedantic -Wshadow -Wconversion` (already on).
5. `PORTING_STATUS.md` regenerates with it marked `done` (`tools/gen_status.py --cpp build/<you>/python`).

## Style

- Read the Python source of what you port *and its tests* in `../SimpleCADAPI/test/` first.
- No comments that restate the code. Comment the non-obvious: OCCT quirks, why a tolerance is what it is.
- Small files by capability; the Python files are huge, the C++ ones should not be.
- RAII, no raw owning pointers, no `new`/`delete`, no `using namespace` in headers, no macros
  except include guards and test frameworks. OCCT `Handle(...)` only where OCCT demands it.
- `const` by default; `[[nodiscard]]` on functions whose result must not be dropped.
- Never swallow an exception silently. Catch at a boundary, add context, rethrow.
- Do not modify `../SimpleCADAPI` (the reference). Do not commit; do not push; do not touch git.

## Reporting

End your work with a short report: what is done (with test counts), what is not and why,
decisions you made, shared-file edits you made, and anything the next person must know.
