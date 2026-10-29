# Contributing to the native engine

This file is for a person who has to build, test, review or change `src/cpp`. It states the rules the code already
follows and the commands that run the checks. Design background is in [ARCHITECTURE.md](ARCHITECTURE.md); a guided tour of
the sources is in [docs/READING_ORDER.md](docs/READING_ORDER.md).

Paths below are relative to the repository root unless they start with `./`.

## 1. Prerequisites

| Need | Version | Notes |
|---|---|---|
| C++ compiler | C++20: Apple clang 15+, GCC 11+, Clang 14+, MSVC 2022 | `cmake/ScadCompile.cmake` is the only place that knows compiler flags |
| CMake | 3.20+ | `cmake_minimum_required` in `src/cpp/CMakeLists.txt` |
| Ninja | any | the commands below use `-G Ninja` (the CI and wheel builds do too) |
| OpenCASCADE | 7.8+ (`SCAD_OCCT_MIN_VERSION`); releases use 7.9.3 built statically | system install for development, or a static build from `src/cpp/tools/build_occt.py` |
| Python | 3.10 - 3.13 | `find_package(Python 3.10 ...)`; one compiled module file per Python version |
| pybind11 | 2.13+ | `pip install pybind11`; `python -m pybind11 --cmakedir` prints the CMake directory |
| clang-format | exactly 18.1.8 | `python3 -m pip install clang-format==18.1.8` (what CI installs) |

macOS: `brew install opencascade pybind11 cmake ninja` gives a system OCCT under `/opt/homebrew` (this is how the
maintainer builds; Homebrew's OCCT version is not pinned by this repository). Debian/Ubuntu: the `libocct-*-dev` packages
(Ubuntu 26.04 ships 7.9.2), `pybind11-dev`, `ninja-build`. The Linux package route is not exercised by CI, which uses the
static OCCT below.

## 2. Configure and build

The CMake project is `src/cpp`. Use a build directory under `src/cpp/build/` (git-ignored). One build directory per
configuration; never share one between macOS and Linux checkouts on a shared filesystem.

Development build against a system OCCT, with the Python module and the C++ tests:

```bash
cmake -S src/cpp -B src/cpp/build/dev -G Ninja -DCMAKE_BUILD_TYPE=Debug \
  -DPython_EXECUTABLE="$(which python)" \
  -Dpybind11_DIR="$(python -m pybind11 --cmakedir)" \
  -DCMAKE_PREFIX_PATH=/opt/homebrew        # macOS Homebrew; omit on Linux with system OCCT
cmake --build src/cpp/build/dev
```

Debug builds turn on standard-library bounds checking (`_GLIBCXX_ASSERTIONS`, libc++ extensive hardening), so an
out-of-range `vector[]` fails at the access.

CMake options (`src/cpp/CMakeLists.txt`, `cmake/ScadOcct.cmake`, `cmake/ScadGordon.cmake`):

| Option | Default | Meaning |
|---|---|---|
| `SCAD_BUILD_PYTHON` | ON | build the pybind11 module `simplecadapi._cpp._native` |
| `SCAD_BUILD_TESTS` | ON | build the doctest executables |
| `SCAD_WARNINGS_AS_ERRORS` | OFF | `-Werror` / `/WX`. No CI job sets it today; use it locally before sending a change |
| `SCAD_BUILD_BENCH` | OFF | developer probes in `src/cpp/tools/bench` |
| `SCAD_SANITIZE` | OFF | AddressSanitizer + UBSan (GCC/Clang only) |
| `SCAD_WITH_GORDON` | ON | the vendored `occ_gordon` library behind `make_gordon_surface_rface` |
| `SCAD_OCCT_PREFIX` | empty | install prefix of a static OCCT (the directory holding `lib/cmake/opencascade`) |

Always on: `-Wall -Wextra -Wpedantic -Wshadow -Wnon-virtual-dtor -Woverloaded-virtual -Wconversion` (MSVC: `/W4`).

The module is written to `src/simplecadapi/_cpp/_native.<python-tag>.so` directly, so a checkout imports it without an
install step. Build only the module with `cmake --build src/cpp/build/dev --target _native`.

### Building one area

Each area is a static library `scad_<area>` and a test executable `test_<area>`, with sources globbed per directory (no
CMake edit to add a `.cpp`). Areas: `core kernel topo semantic reactive io ql render sketch surface ops_geometry
ops_features std product`. To work on one:

```bash
cmake --build src/cpp/build/dev --target scad_semantic test_semantic
src/cpp/build/dev/tests/cpp/test_semantic
```

An area never includes a header of an area above it (see the layer diagram in ARCHITECTURE.md; the link dependencies are
the `scad_add_area` lines in `src/cpp/src/CMakeLists.txt`).

### Static OCCT (what the CI and the release wheels link)

```bash
python3 src/cpp/tools/build_occt.py --prefix "$HOME/occt"     # optional: --tag V7_9_3 --jobs N --work DIR --source DIR --force
cmake -S src/cpp -B src/cpp/build/static -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DSCAD_OCCT_PREFIX="$HOME/occt" -Dpybind11_DIR="$(python -m pybind11 --cmakedir)"
```

The script needs only the Python standard library and builds Release static libraries (default tag `V7_9_3`); the
workflow comments put it at the better part of an hour per platform. It is skipped when the prefix already holds OCCT.

### Through the Python build (`uv`)

`uv sync --locked --group dev` builds the module through scikit-build-core (`pyproject.toml`: `cmake.source-dir =
"src/cpp"`, tests off, Python on). CI does exactly `CMAKE_ARGS="-DSCAD_OCCT_PREFIX=$HOME/occt" uv sync --locked --group
dev`. `pip wheel .` and `cibuildwheel` use the same configuration (`.github/workflows/release.yml`).

### Linux from a Mac

`src/cpp/scripts/linux.sh <area>...` builds `test_<area>` in an OrbStack VM named `ubuntu` (it runs `orb -m ubuntu`;
GCC with libstdc++ assertions, Python module off, ccache expected) and prints the tail of each test run. It is the
maintainer's convenience and needs `orb`; on a real Linux machine run the cmake commands above instead.

## 3. Test layers

Run the cheapest layer that can fail first.

| Layer | What it is | Command |
|---|---|---|
| 1. C++ unit tests | doctest, one executable per area, `src/cpp/tests/cpp/<area>/` | `ctest --test-dir src/cpp/build/dev --output-on-failure` (one area: `-R '^io$'`; one case: run `test_<area> -tc='*name*'`; list: `--list-test-cases`) |
| 2. Python parity tests | `src/cpp/tests/python/test_<area>_*.py`, the real module against goldens recorded from the 2.2.6 SDK | `python -m pytest src/cpp/tests/python -q` (area: `-k ops_features`) |
| 3. The old SDK suite | `test/` and `tests/`, the full Python SDK test suite, unchanged, now running on the native engine | `python -m pytest test tests -q` |
| 4. Wheel smoke test | an installed wheel loads, models, exchanges files, renders, reports errors | `python src/cpp/tests/wheel_smoke.py` (cibuildwheel runs it in a clean environment) |

Layers 2 and 3 import `simplecadapi._cpp`, so build `_native` first. If `simplecadapi` is not importable,
`src/cpp/tests/python/conftest.py` puts `src` on `sys.path`. Do not start Python with the current directory inside
`src/simplecadapi`: the package's `inspect` subpackage shadows the standard library module.

### Layer 1: C++

`src/cpp/tests/cpp/CMakeLists.txt` registers one test per area: `core kernel topo` and then every area listed in
`SCAD_AREAS`. `tests/cpp/semantic/test_tracking_golden.cpp` compares against `tracking_golden.hpp`, a file generated from
the reference SDK by `tests/cpp/semantic/tracking_golden_record.py`; `tests/cpp/io/test_brep_region.cpp` reads
`tests/golden/io_scadbrep_reference.json`.

CI runs the doctest executables in a sanitizer build (`.github/workflows/ci.yml`, job `sanitize`):

```bash
cmake -S src/cpp -B build/asan -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DSCAD_SANITIZE=ON -DSCAD_BUILD_PYTHON=OFF -DSCAD_BUILD_TESTS=ON -DSCAD_OCCT_PREFIX="$HOME/occt"
cmake --build build/asan
ASAN_OPTIONS=halt_on_error=1:abort_on_error=1:detect_leaks=1 \
LSAN_OPTIONS=suppressions=$PWD/src/cpp/tools/lsan.supp \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 ctest --test-dir build/asan --output-on-failure
```

### Layer 2: Python parity tests and goldens

The tests state expected values by calling `golden(name, snippet)` from `src/cpp/tests/python/ref.py`. The snippet is
Python written against the reference SDK; its JSON answer is stored in `src/cpp/tests/golden/<name>.json`, and the test
compares the native result to it. Goldens are committed. They are the behavioural contract of the port.

Rules:

* A golden that exists is read, never recomputed. Comparison goes through `ref.close`: counts, names, ids and strings are
  compared exactly; numbers use `GEOMETRY_REL = 1e-4` (OCCT builds differ at about 1e-5; a real geometry error is orders
  of magnitude larger).
* A missing golden: with no reference interpreter the test is skipped; with one (`SCAD_REF_PYTHON`, default is the
  maintainer's checkout `/Users/lildino/Project/ocws/SimpleCADAPI/.venv/bin/python`, so set it) the snippet is run
  and the file is written. The reference must be the 2.2.6 SDK that runs on OCP; a golden recorded from anything else
  is not a golden.
* `SCAD_REGOLDEN=1` re-records every golden it touches. **Do not use it to get a test green.** A changed golden is a
  statement that the 2.2.6 behaviour was recorded wrongly, and the pull request must say what 2.2.6 does and how that was
  checked. If the native engine differs from 2.2.6, fix the engine, or record the deviation (see section 9).
* `SCAD_GOLDEN_STRICT=1` (CI sets it for this layer): a missing golden is a failure, and `SCAD_REGOLDEN` is refused.
  Run with it before pushing: `SCAD_GOLDEN_STRICT=1 python -m pytest src/cpp/tests/python -q`.

### Layer 3: the old suite and the known-failures list

`test/conftest.py` reads `test/native_known_failures.json`, a map from a pytest node id to `[kind, reason]`:

* `internal`: the test inspects a Python-only internal (a private helper, `OperationNode` as a dataclass, ...) that has no
  native counterpart. It is skipped with the reason.
* any other kind (`open` today): a real parity difference; the test is expected to fail, not strictly, so a fix shows up
  as XPASS.

The file has 19 `internal` entries and 1 `open` entry. Adding an entry needs a reason a reviewer can check, and an
`internal` entry for a test that is dropped on purpose also goes into the table at the end of `docs/DEVIATIONS.md`. An
`open` entry is a bug report: prefer fixing.

The last recorded result of layers 2 and 3 is in the last row of the table in `docs/NATIVE_PROGRESS.md`.

## 4. Formatting

`src/cpp/.clang-format` (Google style, 120 columns, left pointer alignment, include order not sorted because order carries
meaning: own header, then ours, then OCCT). Check and fix:

```bash
CLANG_FORMAT=clang-format src/cpp/tools/check_format.sh          # lists files that would change, exit 1 if any
CLANG_FORMAT=clang-format src/cpp/tools/check_format.sh --fix    # rewrites them
```

It covers `*.cpp *.hpp *.h` under `src include bindings tests/cpp` of `src/cpp`; `third_party`, `tools` and `occt_dev` are
not formatted. Use clang-format 18.1.8; other versions format differently and CI (job `clang-format`) will disagree. There
is also an advisory `.clang-tidy` (job `clang-tidy`, changed files only, not a gate).

## 5. Error handling

Public operators fail with `scad::Error` (`include/scad/core/error.hpp`), the analogue of `SimpleCADError`: operation
name, what happened, possible causes, how to fix, optional technical details, measurements, evidence, rendered by
`format_llm_error` into the same text as the Python SDK, because language-model agents read it.

* Write the static half once per operator as an `ErrorSpec` and wrap the body in `guarded(spec, [&]{ ... })`. Any
  `std::exception` leaving the body becomes an `Error` built from the spec plus the cause (`technical_details_of`: "TypeName:
  message"); an `Error` passes through unchanged. Use `raise_harness_error(spec, ...)` to throw one directly.
* Use `ValueError`, `TypeError`, `IndexError`, `RuntimeError`, `NotImplementedError` where the Python code raises those.
  `Error` derives from `ValueError`. `MessageError` and its subclasses (`TagValidationError`, `SemanticCapabilityError`,
  `UnsupportedQueryCapabilityError`) are the message-first families.
* **OCCT exceptions do not derive from `std::exception`.** Wrap every direct OCCT call sequence in `occt_guard([&]{ ... })`
  (same header; `src/core/occt_guard.cpp`): a `Standard_Failure` becomes `KernelError(occt_class, message)` (a
  `RuntimeError`), anything else becomes `KernelError("UnknownException", ...)`. `tools/check_occt_guard.py` lists sites that
  construct a boolean, fillet or offset builder in a function that never mentions `occt_guard` (heuristic; CI runs it
  non-blocking).
* At the Python boundary a translator in `bindings/python/common.cpp` (`register_exceptions`) turns `scad::Error` into
  `simplecadapi._cpp.errors.SimpleCADError` (through `make_error`, which also names the message-first class) and other
  `scad::Exception`s into the builtin named by their `PyKind`. Anything else falls to pybind11's own translators.
* Never swallow an exception silently. Catch at a boundary, add context, rethrow.

## 6. The GIL

The C++ engine does not need Python, so operators may run without the GIL; the binding layer decides.

* `py::gil_scoped_release` appears only in `bind_io.cpp` (meshing, `to_brep`, STEP/STL/OBJ/GLB export, STEP import and assembly export),
  `bind_render.cpp`, `bind_std.cpp` (every std part, through `unlocked`) and `bind_ops_features.cpp` (extrude, revolve,
  fillet, chamfer and others, through `unlocked(keep_gil, ...)`). Geometry, sketch, surface, product, semantic and reactive
  bindings hold the GIL for the whole call.
* `fillet_rsolid` and `chamfer_rsolid` keep the GIL when the edge argument is a ql selector: a selector can carry a Python
  resolver or provider callback (`PyCallable` in `bind_ql.cpp`).
* Take every Python object out of the arguments before releasing; code that runs without the GIL must not touch a
  `py::object`. An exception thrown inside a released scope leaves with the GIL back (the guard is RAII).
* **Every C++ to Python callback re-acquires the GIL** with `py::gil_scoped_acquire` before touching Python: reactive
  executors (`GilSafeFunction` in `bind_reactive_session.cpp`), sketch solver backends (`PythonBackend` in
  `bind_sketch.cpp`), ql callbacks, and the error-guidance hook in `bind_sdk_compat.cpp` (the failing operation may be
  running without the GIL).
* **Lifetime.** Objects with static storage that own Python references (the reactive `ExecutorRegistry`, solver backends)
  are destroyed from `exit()` after `Py_Finalize`; taking the GIL then crashes the process. Release such references through
  `scad::pybind::drop_python_reference` (`bindings/python/py_lifetime.hpp`): at shutdown it leaks the single reference
  instead of touching the interpreter. Regression test: `tests/python/test_exit_with_python_callbacks.py`.

## 7. Thread safety

* A `Shape` and everything reachable from it share mutable state (tags, lineage) and are **not thread-safe**
  (`include/scad/topo/shape.hpp`). Give each thread its own shapes. `OperationGraph` is likewise a plain container.
* `Expr`/`Var`/`Const` nodes are immutable and shared, so they may be used from any thread.
* Process-wide state and how it is protected:
  * mesh cache (`src/io/mesh_cache.cpp`): one mutex, a bounded LRU (32 entries, 256 MiB); an entry keeps the `TopoDS_Shape`
    it was built from so the shape identity cannot be recycled.
  * symbol table (`src/core/symbol.cpp`): one mutex over the table; entries are never freed, so a per-thread cache of
    pointers to them skips the lock on the common lookup.
  * STEP/IGES exchange (`src/io/exchange_lock.hpp`): OCCT keeps translator parameters in process-global `Interface_Static`,
    so every STEP read or write takes one mutex.
  * ql evidence slot (`src/ql/diagnostics.cpp`): mutex.
  * counters (`g_history_queries`, `g_clone_views`) and the surface hooks (`src/surface/hooks.cpp`) are atomics.
* Per-thread state: the active recorder (`current_recorder()`, a `thread_local` in `src/topo/recorder.cpp`, installed with
  `RecorderScope`), the active reactive `Session` (`src/reactive/session.cpp`), the sketch id allocator, and the random
  engines used for ids. A recorder installed on one thread does not see operations run on another.
* The software renderer is deterministic: each pixel is computed by one worker from the same ordered triangle list, so the
  output does not depend on the thread count.

## 8. Style

* Port from the Python source *and its tests*. Name, keyword arguments, defaults and result must match the Python SDK;
  a golden test proves it. Error text must match in structure.
* An operator is done when it has (1) the same signature and behaviour as Python, (2) a `scad::Error` with the same
  operation name and guidance, (3) a doctest case in `tests/cpp/<area>` and a pytest case in `tests/python`, (4) no
  warnings with the flags above.
* RAII; no owning raw pointers, no `new`/`delete`; no `using namespace` in headers; no macros except include guards and test
  frameworks; OCCT `Handle(...)` only where OCCT demands it; `const` by default; `[[nodiscard]]` on results that must not be
  dropped.
* Portable standard C++20: no compiler extensions, no `std::format`, no `M_PI` (use `scad::kPi`), no POSIX-only calls outside
  `#ifdef` in `src/io`.
* Comment what is not obvious (OCCT quirks, why a tolerance has its value), not what the code says. Files are small and
  named for one capability.
* Do not hand-roll tag logic in an operator: finish through `include/scad/semantic/finalize.hpp`.

## 9. The parity rule

The native engine replaces the OCP-based one under the same public API.

* **Old tests are never dropped.** `test/` and `tests/` must keep passing on the native engine. A test that cannot apply
  (it tests a removed internal) is listed in `test/native_known_failures.json` or, if its subject was removed on purpose,
  in the table "Old tests that do not run on the native build" in `docs/DEVIATIONS.md`, with the reason. Deleting a
  failing test is not an option.
* **A difference from 2.2.6 is recorded** in `docs/DEVIATIONS.md` with its reason and the measured effect, or fixed.
* Internal representations may differ from Python (`DEVIATIONS.md`: "compact internally, canonical at the boundary"), but
  anything that is persisted, hashed or compared must come out in the Python format.

## 10. Status and other generated files

`PORTING_STATUS.md` is a snapshot made by `tools/gen_status.py` against the 2.2.6 reference (it lists each public operator
of `simplecadapi.operators` and whether the compiled package exports the name). "Exported" does not mean "aligned", and
the snapshot is not regenerated. What replaces it as the measure of completeness:
the golden parity tests (layer 2), the old suite (layer 3) and `test/test_public_api_surface.py`; the table in
`docs/NATIVE_PROGRESS.md` records the latest numbers.

`src/cpp/tools/gen_stubs.sh` generates the type stubs of `_native` with `pybind11-stubgen==2.5.5` (`--check` compares
against the checked-in ones; they are checked in under `src/simplecadapi/_cpp/_native/`, and CI runs `--check` (advisory until it has passed once on Linux: the checked-in files were generated on macOS)). `src/cpp/tools/landing_plan.py` prints the
pull-request partition described in `docs/LANDING_PLAN.md`.

## 11. Before you send a change

1. `CLANG_FORMAT=clang-format src/cpp/tools/check_format.sh`
2. Build with `-DSCAD_WARNINGS_AS_ERRORS=ON`; run `ctest` for the areas you touched (and every area above them in the
   layer diagram, because the headers are shared).
3. `SCAD_GOLDEN_STRICT=1 python -m pytest src/cpp/tests/python -q`, then `python -m pytest test tests -q` if you changed
   behaviour the SDK can see.
4. In the pull request: the commands you ran, any golden or known-failure entry you touched with the 2.2.6 evidence, and
   any new `DEVIATIONS.md` entry.
