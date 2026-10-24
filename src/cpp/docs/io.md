# io: import, export, tessellation, serialization

Everything that moves a shape in or out of the process: `include/scad/io/`, `src/io/`, the Python
bindings in `bindings/python/bind_io.cpp`.  Ported from `simplecadapi/kernel/ocp_export.py`,
`ocp_mesh.py` (tessellation), `ocp_brep_snapshot.py`, `_internal/{mesh,brep_region,shape_pickle}.py`
and the core of `exporter/`.  Robot-description exporters (MJCF, URDF) and the product-package
plumbing stay Python.

## API map

| Header | What | Python (`simplecadapi._cpp`) |
|---|---|---|
| `brep.hpp` | BinTools V4 bytes, canonical bytes, files | `Shape.to_brep()`, `from_brep(bytes)`, `canonical_brep_bytes`, `export_brep`, `import_brep` |
| `mesh.hpp` | `mesh()`, `Mesh`, `TriMesh`, `cached_mesh`, `tessellate_solid` | `mesh(shape, ...)`, `Mesh`, `_internal_mesh.*` |
| `exchange.hpp` | STEP, STL, OBJ, GLB files and bytes, compounds | `export_step`, `import_step`, `export_stl`, `import_stl`, `import_stl_shape`, `export_obj`, `export_glb` |
| `step_assembly.hpp` | STEP assemblies: names, colours, materials, metadata | (C++; used by the product area) |
| `serialize.hpp` | geometry + semantic state | `serialize_shape`, `deserialize_shape`, pickle/`copy` |
| `brep_region.hpp` | `.scadbrep` snapshots | `_brep_region.*` |
| `files.hpp`, `hash.hpp`, `json.hpp` | portable files; SHA-256/SHA-1/uuid5/CRC-32; JSON (RFC 8259 parse, RFC 8785 write) | - |

Failures leave as `scad::Error` (Python `SimpleCADError`) with the operation names `export_step_shapes`,
`import_step`, `export_stl`, `export_stl_shape`, `import_stl`, `export_obj`, `export_glb`,
`export_brep`, `import_brep`, `export_step_assembly`, `import_step_assembly`, `serialize_shape`,
`deserialize_shape`, and (for `.scadbrep`) `brep_region`.

## Paths, Unicode and Windows

* The C++ API takes `std::filesystem::path`.  Build one from UTF-8 text with
  `scad::io::path_from_utf8` (a `char8_t` construction: correct on Windows, where a narrow `char`
  string would be the ANSI code page); read one back with `path_to_utf8`.  Python callers pass `str`
  or `os.PathLike`; pybind11's `std::filesystem::path` caster converts through the file-system
  encoding (UTF-16 on Windows).
* Files are opened by this library, as binary C++ streams constructed from the path object.
  OpenCASCADE is only handed *streams*: `STEPControl_Writer::WriteStream`,
  `STEPControl_Reader::ReadStream`, `STEPCAFControl_Writer::WriteStream`, `BinTools::Read/Write(stream)`.
  The STL, OBJ and GLB readers and writers are ours.  Nothing here calls an OCCT entry point that
  takes a file *name*.
* Should one ever be needed: OCCT >= 7.4 treats every narrow `const char*` file name as **UTF-8** on
  Windows (`OSD_OpenStream(T&, const char*, mode)` builds a `TCollection_ExtendedString(name, true)`
  and opens it through `_wfopen`/wide `open`), so pass `path_to_utf8(path)`; on POSIX the bytes are
  passed through.
* Writes are atomic: bytes go to `<name>.scad-<n>.tmp` next to the target and are renamed over it on
  success (`std::filesystem::rename` replaces on every supported platform).  A failed or abandoned
  write leaves no partial file and does not touch an existing one.
* Number formatting never consults the C locale (`std::to_chars` / `from_chars`; a stream imbued
  with the classic locale where the standard library lacks floating-point `from_chars`).

## Threading

* `mesh()`, `build_solid_trimesh()`, `tessellate_solid()` and friends mesh a **topology copy**
  (`BRepBuilderAPI_Copy`, geometry shared, no triangulation), so concurrent calls on one shape are safe
  and nothing is ever attached to the caller's shape.  `MeshParameters::parallel` (default on) lets
  `BRepMesh_IncrementalMesh` use OCCT's thread pool.  The Python wrappers release the GIL.
* STEP reading and writing take a process-wide mutex: OCCT's STEP translators read and write the
  global `Interface_Static` parameter table.  They also capture OCCT's messenger for the duration (the
  default prints transfer statistics to stdout) and fold the text into the error on failure.
* `cached_mesh()` is a mutex-protected least-recently-used cache (32 meshes / 256 MiB).
* `Shape` handles are not thread-safe (see `topo/shape.hpp`); `serialize()` reads semantic state and
  must run on the thread that owns the shape.

## Tessellation

`mesh(shape, linear_deflection=0.35, angular_deflection=0.22, relative=False, parallel=True)`
returns a `Mesh` of flat arrays:

| member | type | shape |
|---|---|---|
| `vertices` | float32 | (n, 3) |
| `normals` | float32 | (n, 3), unit, per vertex |
| `triangles` | uint32 | (m, 3), counter-clockwise seen from outside |
| `face_ids` | uint32 | (m,), face index per triangle |
| `face_ranges` | uint32 | (faces, 3): face index, first triangle, triangle count |

Each face keeps its own vertices, so normals are sharp across CAD edges.  Face indices follow
`TopExp_Explorer` order, i.e. the order of `solid.faces()`; for a valid solid or shell that is also
the numbering of `face_<i>` topo ids.  Faces OCCT could not mesh appear in `face_ranges` with count 0.
In Python the arrays are **read-only zero-copy numpy views** of the `Mesh`'s memory; each view holds a
reference that keeps the `Mesh` alive.

`TriMesh` (`_internal_mesh.cached_mesh`) is the double-precision mesh of `_internal/mesh.py`: vertices
(n, 3) float64, triangles (m, 3) int64, per-corner normals (m, 3, 3) and per-face triangle ranges with
the source face's topo id.  Defaults 0.35 / 0.22 are the Python SDK's.  Its face meshing is whole-shape
(shared edge discretisation) where Python meshes face by face; counts agree with the reference SDK on
its tests (box 12/24, cylinder r=3 h=5 228/234 triangles/vertices).

`tessellate_solid()` is `exporter/_surface_mesh.py`: the solid meshed once with deflection 0.1 and
angular deflection 20 degrees (absolute), vertices welded on a grid of
`max(min(linear * 1e-7, 1e-7), 1e-9)`, collapsed triangles dropped.  STL and OBJ writers are fed
from it.

## STL, OBJ, GLB

* **Binary STL** (`export_stl`): exactly `exporter/stl.py`.  80-byte header
  `"SimpleCAD OpenCASCADE BREP tessellation"` zero padded, `uint32` triangle count, then per triangle
  twelve little-endian `float32` (unit normal from the triangle, three vertices) and a zero `uint16`.
  A collapsed triangle is an error.
* **ASCII STL** (`export_stl_shape`, `export_stl(..., ascii=True)`): `kernel/ocp_export.py`'s
  `export_stl_shape` -- mesh at 0.1 / 0.5, one facet per mesh triangle, no welding -- written with 9
  significant digits (OCCT's own writer keeps 7).
* **Reading** (`read_stl`): binary when the size is exactly `84 + 50 * count`, otherwise ASCII.
  Coincident vertices are merged, normals recomputed (area weighted).  `stl_to_shape` sews one planar
  face per triangle and returns a Solid when the shell closes.
* **OBJ** (`export_obj`): `v` records with `%.17g` and `f` records, 1-based, `\n` newlines, ASCII.
* **GLB** (`export_glb`): glTF 2.0 binary, one mesh, one primitive with `POSITION`, `NORMAL` and
  `uint32` indices from `mesh()`.  CAD coordinates are written as they are (Z up, millimetres, no
  node transform); the per-face triangle ranges are in the primitive's `extras`.

## STEP

`export_step_shapes` is `STEPControl_Writer` with `STEPControl_AsIs` on the compound of the shapes (a
lone shape as itself), default schema (AP214CD) and units (mm).  `read_step` reads with
`STEPControl_Reader::TransferRoots`; the result is the single root or a compound of all roots.
Neither product counters nor the header timestamp are reproducible between calls: two writes of one
shape differ in a few bytes.

`step_assembly.hpp` is `export_product_package_to_step` without the package reader: definitions with a
body (`TopoDS_Shape`) or components (`id`, `name`, placement as the rotation columns plus origin,
metadata record); one XCAF label per definition shared by all occurrences; names and JSON comments;
XCAF material (density, unit) and surface colour; schema AP242DIS (`write.step.schema`, restored
afterwards); and the `SimpleCAD metadata` property definition whose descriptive items
(`SimpleCAD:definition:<kind>:<id>`, `SimpleCAD:occurrence:<parent>:<component>`) hold the records as
`json.dumps(sort_keys=True, ensure_ascii=True)` text.  `read_step_assembly` returns the document as a
tree of `StepNode` (name, body, placement relative to the parent, surface colour).

## BREP bytes -- hand-off to OCP

`Shape.to_brep()` is **BinTools format version 4, geometry only** (no triangulation, no normals):
`BinTools::Write(shape, stream, false, false, BinTools_FormatVersion_VERSION_4)`.  Every double is
bit-exact; the bytes begin `"\nOpen CASCADE Topology V4, (c) Open Cascade\n"`.  Every OCCT from 7.3
reads it, so in the cadquery-ocp wheel:

```python
data = shape.to_brep()
occ = TopoDS_Shape(); BinTools.Read_s(occ, io.BytesIO(data))      # wheel -> OCP shape
buffer = io.BytesIO(); BinTools.Write_s(occ, buffer, False, False, BinTools_FormatVersion_VERSION_4)
shape = simplecadapi._cpp.from_brep(buffer.getvalue())             # OCP shape -> this library
```

The two OCCT copies never share memory: only bytes cross.  `from_brep` also accepts older BinTools
versions and ASCII `BRepTools::Write` text.  `canonical_brep_bytes` is
`artifacts/brep.py::write_brep_bytes`: the smallest member of the encode/decode cycle, the encoding to
hash (reading is not byte-idempotent: some zeros come back as -0.0 and a few doubles move by an ulp).
OCCT's readers are not hardened against hostile input; treat BREP bytes from untrusted sources
accordingly.

## Shape serialization (`SCADSHAP` 1.0)

`serialize(shape)` / `deserialize(bytes)` replace `_internal/shape_pickle.py`; Python pickling and
`copy.deepcopy` of shapes go through them (`__reduce__`).  What is stored: the exact geometry, and the
semantic state (tag bindings, lineage witnesses, metadata, runtime values) of every entity under the
root that has any.  Derived data is recomputed, never stored: runtime keys starting with `mesh.` are
dropped.

All integers are big-endian.  A byte string is `header (40) || state section || BREP section`.

| offset | size | field |
|---|---|---|
| 0 | 8 | magic `SCADSHAP` |
| 8 | 2 | major version = 1 |
| 10 | 2 | minor version = 0 |
| 12 | 4 | flags = 0 (any other value is rejected) |
| 16 | 8 | `state_size` |
| 24 | 8 | `brep_size` |
| 32 | 4 | CRC-32 (zlib polynomial) of the state section followed by the BREP section |
| 36 | 4 | reserved = 0 |
| 40 | `state_size` | state section |
| 40 + `state_size` | `brep_size` | BREP section: BinTools V4 as above |

The file length must equal `40 + state_size + brep_size`.  A reader accepts its own major version and
any minor version, and ignores state keys it does not know.

The **state section** is one `scad::Value`, binary-encoded: a tag byte then a payload --
`0` null, `1` false, `2` true, `3` int (zig-zag LEB128), `4` double (IEEE-754 bits, 8 bytes), `5` string
(LEB128 length, UTF-8), `6` array (LEB128 count, items), `7` object (LEB128 count, then key string and
value per member, insertion order kept).  The document:

```
{"format": "scad-shape-state", "version": 1, "root_kind": "solid",
 "entities": [ {"kind": "face", "index": 3, "topo_id": "face_3",
                "bindings": [TagBinding.to_value()...], "lineage": [TagLineageWitness.to_value()...],
                "metadata": {...}, "runtime": {...}} ... ]}
```

`index` is the entity's 1-based position in `TopExp::MapShapes(root, kind)`; BinTools keeps sub-shape
order, so positions line up after the round trip.  A restored root numbers its topo ids by the same
rule, so they equal the originals whenever the serialized shape was a root.  (For a face taken from a
solid the restored id is its position in the new root; the saved id stays in the document.)

## `.scadbrep` region snapshots

Bit-compatible with `_internal/brep_region.py`: header `"SCADBREP"`, `u16` major (1), `u16` minor (0),
`u32` flags (0), `u64` manifest size, `u64` payload size (32 bytes); an RFC 8785 canonical JSON
manifest (closed schema, every key checked); a BinTools V4 payload.  The C++ writer reproduces the
Python file **byte for byte** for the same STEP-derived solid (tested against a snapshot written by the
reference SDK).

Differences, all deliberate:
* The manifest names the OCP build (`profile`, `generator.ocp_version`, e.g. `7.9.3.1`).  A reader
  here accepts any version whose major.minor equals this OCCT's; a writer stamps
  `default_ocp_version()` (`7.9.3`) unless told otherwise -- pass `"7.9.3.1"` for a file the Python SDK
  will accept (it requires an exact match with its own wheel).
* Volume, face area and centroid in the manifest are compared with relative tolerance 1e-9 (the Python
  reader compares for exact equality, which breaks across CPUs).
* Replay confinement (`read_artifact(..., replay_root)`) resolves the path inside the root and refuses
  symbolic links and (MSVC) junctions along it; it cannot repeat Python's `O_NOFOLLOW` + `fstat`
  identity check portably, so it re-checks the file's size after reading instead.
* `copy_step_solid_region` snapshots a whole solid.  Selecting a connected face region by id needs the
  `inspect.brep` entity model, which stays Python; `make_region_artifact` takes the resulting shell and
  its source face ids.

## Python reference parity (`tests/python/test_io_*.py`)

Goldens in `tests/golden/io_*.json` come from the reference SDK (`tests/python/io_snippets.py`):
solids, STEP text, canonical BREP bytes, ASCII-STL facet counts, per-face and welded mesh counts, and
`.scadbrep` artifacts.  Matched exactly on the sampled shapes: volume, face count, BinTools canonical
bytes, `cached_mesh` vertex/triangle counts, `tessellate_solid` counts, ASCII facet counts, `.scadbrep`
bytes.  Live interop tests (skipped without the reference interpreter) hand our STEP, BREP bytes and
snapshots to the reference SDK / OCP.
