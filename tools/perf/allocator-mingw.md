# Keep module-wide mimalloc out of the static Windows wheel

**Decision (2026-11-22):** no CMake switch. Replacing global C++ `new/delete` inside `_native` cut the equal-weight geometric mean of 19 operation latencies by **4.3%**, but not consistently across workloads or run pairs. More importantly, a second MinGW extension can see and grow the **same C++ hash table** as `_native`. Hiding the allocator symbols at the DLL boundary does not give the DLL exclusive ownership of those allocations.

[Raw timings, module hashes and lifecycle results](results/allocator-mingw-v224.json). This is an operator benchmark, not an end-to-end BLDC speedup estimate.

## What was compared

- **A:** ordinary import from `out/final-env` with its CPython 3.10.22. The installed `_native`, the member read directly from the final `.whl`, and the existing `out/static-build` extension all hashed to `368b5391d7ba392df5161a755a298bc201911a969a860e79f402d26793a8ecde`.
- **B:** same interpreter and Python package; a finder restricted to `simplecadapi._cpp._native` selected one private `.pyd`. The worker checked the loaded path. Existing binding objects, SDK and static OCCT archives, link order and MinGW GCC 15.2 were reused. A plain private relink had byte-identical `.text` to A. Neither the existing build nor either installed environment was rebuilt or patched.
- **Allocator:** upstream Microsoft mimalloc tag `v2.2.4`, commit `fbd8b99c2b828428947d70fdc046bb55609be93e`. Compiled `src/static.c` as **C++** (throwing `new` can use `std::bad_alloc`); one additional TU included only `mimalloc-new-delete.h`. No `MI_MALLOC_OVERRIDE`, redirect DLL, `MI_SHARED_LIB`, `--wrap`, OCCT allocator modification or floating-point flag change. Used `MI_WIN_USE_FLS=1`: the default static path in `src/prim/windows/prim.c` uses MSVC linker/section pragmas to register TLS callbacks. The FLS path instead uses fiber-local storage for thread cleanup and a GCC constructor/destructor for process attach/detach.
- **Link audit:** the map assigns all 20 scalar/array, sized, aligned and nothrow operators to the private object. `nm` found no definitions of CRT allocation entry points in the allocator object. `objdump -p` showed one export (`PyInit__native`); `calloc/free/malloc/realloc` still come from `msvcrt.dll`, FLS calls from `KERNEL32.dll`. The seven imported DLLs were the same as A; no external TK or C++ runtime DLL. OCCT was built with `USE_MMGR_TYPE=NATIVE`: `Standard::Allocate/Free` still has its own C allocation path. A C++-only change cannot accelerate all OCCT allocations.

To repeat the private link, start from the `_native` build edge's object list and `LINK_LIBRARIES` in `out/static-build/build.ninja`, as in `out/boolean-probe/build.py`. In a private directory with `mimalloc/` at the above commit:

```text
g++ -x c++ -std=c++17 -O3 -DNDEBUG -DMI_STATIC_LIB -DMI_WIN_USE_FLS=1 -DMI_WIN_NOREDIRECT -D_WIN32_WINNT=0x0601 -Imimalloc/include -c mimalloc/src/static.c -o mimalloc.o
g++ -std=c++20 -O3 -DNDEBUG -DMI_STATIC_LIB -Imimalloc/include -c operators.cpp -o operators.o
```

Link from the existing build directory with `g++ -O3 -shared -Wl,-Map,<private-map> -o <private-pyd> @<private-rsp>` and strip that output. Response file order: binding objects, absolute private `operators.o`, `mimalloc.o`, `-lbcrypt -lpsapi`, original `LINK_LIBRARIES`. Omit the two objects and extra libraries for the control relink.

## Timings

Eight serial, fresh Python processes on one Core Ultra 7 251HX, in order **AB BA BA AB**. `PYTHONHASHSEED=1`. Used the 19 builders and batch counts from `tools/perf/throughput.py` (snapshot hash in raw file): one warm-up call, three timed batches per operation per process. Each cell below is a geometric mean over four process medians, in ms/call. Change is `B/A − 1`; negative is faster. The four adjacent-pair all-operation changes were **−5.1%, ~0.0%, −6.0%, −5.8%**. No outliers were removed.

| Operation | Wheel A (ms) | Local allocator B (ms) | Change |
|---|---:|---:|---:|
| Box | 0.1104 | 0.0952 | −13.8% |
| Cylinder | 0.0959 | 0.0846 | −11.8% |
| Cut | 4.556 | 4.633 | +1.7% |
| Spur gear, 12 teeth | 12.253 | 10.944 | −10.7% |
| Spur gear, 48 teeth | 42.376 | 36.725 | −13.3% |
| Bearing | 1.005 | 1.017 | +1.2% |
| Bolt | 7.020 | 7.242 | +3.2% |
| Sprocket | 133.46 | 135.94 | +1.9% |
| Nut | 5.398 | 5.464 | +1.2% |
| Helical | 77.41 | 77.73 | +0.4% |
| Herringbone | 2182.62 | 2165.23 | −0.8% |
| Ring | 136.86 | 147.49 | +7.8% |
| Helical ring | 243.96 | 223.38 | −8.4% |
| Herringbone ring | 3057.61 | 3052.16 | −0.2% |
| Rack | 2.257 | 2.003 | −11.3% |
| Helical rack | 32.16 | 31.11 | −3.2% |
| Herringbone rack | 62.78 | 60.08 | −4.3% |
| Bevel | 51.65 | 48.97 | −5.2% |
| Cycloidal disc | 25.57 | 22.67 | −11.3% |

Box, cylinder, both spur gears and the cycloidal disc improved in all four comparisons. For the expensive herringbone cases the difference is under 1%. Ring is particularly noisy: one pair was +122.8%, the other three about −15%. Its aggregate is not a reliable slowdown estimate.

## Ownership and teardown checks

| Check | Observation and scope |
|---|---|
| Python worker lifetime | Per variant, 48 short-lived threads created 480 solids; the main thread serialized and released them after the workers exited. Both produced 480 identical canonical BREP hashes and exited normally. First import on a worker, then reuse on the main thread, also passed. These are lifetime checks, not leak measurements. |
| Process / module unload | All benchmark and lifecycle children exited normally. Ten bare `LoadLibraryW` / `FreeLibrary` cycles per variant returned the module handle count to zero as checked by `GetModuleHandleW`. Bare loading exercises static initialization/destruction, not forced unload after `PyInit` with live Python objects. |
| External OCCT | Tested the installed `cadquery-ocp-novtk` through `to_ocp` / `from_ocp`, including OCP imported first. A boolean cut had identical canonical BREP before and after copying in both variants. This API transfers Python bytes; this particular OCP binary also has a different pybind11 ABI key (MSVC v5). It does not test other extensions built with the SDK's MinGW ABI. |
| Same-ABI peer | A separate ordinary MinGW pybind11 3.1.0 extension read `get_internals().registered_types_cpp` on **A** before and after importing the SDK. Its `(size, bucket_count)` went from `(0, 1)` to `(264, 541)`, under the exact same MinGW v12 internals key embedded in B. The observer did not register custom types or force a bad free. |

The last check is the release blocker. `pybind11.h` inserts into that shared `std::unordered_map` in the calling extension; bucket growth can free the bucket array created by the previous writer. A same-ABI peer still uses ordinary `delete`, whereas B uses `mi_free`. Neither import order nor normal shutdown establishes a common allocator for that storage. A B crash is **not** claimed or needed to identify this missing ownership contract. The byte bridge and successful lifetime tests do not resolve it. An allocator confined to explicitly owned internal containers would be a different experiment.
