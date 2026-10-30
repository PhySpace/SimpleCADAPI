// File exchange: STEP, STL, OBJ, GLB (glTF 2.0 binary) and BREP.
//
// Ports of simplecadapi/kernel/ocp_export.py and the shape-level core of the
// exporter package (the product-package plumbing around it stays in Python or
// belongs to the product area).  Every entry point takes a std::filesystem::path
// (build one from UTF-8 with path_from_utf8) and reads or writes through C++
// streams, so Unicode paths behave the same on Windows, macOS and Linux.
//
// Failures leave as scad::Error carrying the operation name below.
//
// Thread-safety: STEP reading and writing share OpenCASCADE's global
// Interface_Static parameter table and are serialised by a process-wide mutex
// here; the other formats run concurrently.
#pragma once

#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

#include <TopoDS_Shape.hxx>

#include "scad/core/tolerance.hpp"
#include "scad/io/brep.hpp"
#include "scad/io/files.hpp"
#include "scad/io/mesh.hpp"
#include "scad/topo/shape.hpp"

namespace scad::io {

// ---------------------------------------------------------------------------
// Compounds (kernel/ocp_export.py)
// ---------------------------------------------------------------------------
// ValueError("No shapes to export") when empty.  make_compound returns the
// shape itself for a list of one; make_compound_always always builds a compound.
TopoDS_Shape make_compound(const std::vector<TopoDS_Shape>& shapes);
TopoDS_Shape make_compound_always(const std::vector<TopoDS_Shape>& shapes);

// ---------------------------------------------------------------------------
// STEP
// ---------------------------------------------------------------------------
struct StepReadOptions {
  bool require_single_root = false;  // exactly one transferred root, else an error
  bool require_valid = false;        // BRepCheck_Analyzer must accept the result
};

struct StepReadResult {
  TopoDS_Shape shape;  // the single root, or a compound of all roots
  int transferred_roots = 0;
  int shape_count = 0;
};

// Operation "export_step_shapes": STEPControl_Writer with STEPControl_AsIs on a
// compound of `shapes` (a lone shape is written as is), default schema and units.
void export_step_shapes(const std::vector<TopoDS_Shape>& shapes, const std::filesystem::path& path);
Bytes step_bytes(const std::vector<TopoDS_Shape>& shapes);

// Operation "import_step".  `name` is only used in diagnostics for the bytes form.
StepReadResult read_step(const std::filesystem::path& path, const StepReadOptions& options = {});
StepReadResult read_step_bytes(std::string_view bytes, const std::string& name = "model.step",
                               const StepReadOptions& options = {});
Shape import_step(const std::filesystem::path& path, const StepReadOptions& options = {});

// ---------------------------------------------------------------------------
// STL
// ---------------------------------------------------------------------------
// Operation "export_stl_shape" (kernel/ocp_export.py export_stl_shape): meshes
// with linear deflection 0.1 and OCCT's default angular deflection 0.5 and
// writes ASCII STL, one facet per mesh triangle (no vertex welding), floats with
// 9 significant digits.
void export_stl_shape(const TopoDS_Shape& shape, const std::filesystem::path& path);
// The same ASCII writer with explicit mesh parameters, for any number of shapes
// (written as one solid).  Operation "export_stl".
void export_stl_ascii(const std::vector<TopoDS_Shape>& shapes, const std::filesystem::path& path,
                      const MeshParameters& parameters);

// Operation "export_stl" (exporter/stl.py): the solids of `shapes`, tessellated
// and welded per solid, as binary STL.  Throws when there is nothing to export.
struct SurfaceExportReport {
  std::filesystem::path output_path;
  std::size_t solid_count = 0;
  std::size_t vertex_count = 0;
  std::size_t triangle_count = 0;
  SurfaceMeshParameters parameters;
};
SurfaceExportReport export_stl(const std::vector<TopoDS_Shape>& shapes, const std::filesystem::path& path,
                               const SurfaceMeshParameters& parameters = {});

// The solids (or, failing that, the shape itself) a surface exporter meshes.
std::vector<TopoDS_Shape> surface_solids(const TopoDS_Shape& shape);
// The merged, welded mesh of all `shapes`' solids.
WeldedMesh tessellate_surface(const std::vector<TopoDS_Shape>& shapes, const SurfaceMeshParameters& parameters,
                              std::size_t* solid_count = nullptr);

Bytes binary_stl_bytes(const WeldedMesh& mesh);  // 80-byte header, count, 50 bytes per facet

// Operation "import_stl": binary or ASCII STL as an indexed mesh with coincident
// vertices merged (exact float equality) and area-weighted vertex normals.
Mesh read_stl_bytes(std::string_view bytes);
Mesh read_stl(const std::filesystem::path& path);
// Faceted BREP of an STL: one planar face per triangle, sewn at `sewing_tolerance`.
// A closed result is returned as a Solid, otherwise as a Shell (or a Compound of
// shells).  Degenerate triangles are skipped.
TopoDS_Shape stl_to_shape(const Mesh& mesh, double sewing_tolerance = tol::kSewing);
Shape import_stl_shape(const std::filesystem::path& path, double sewing_tolerance = tol::kSewing);

// ---------------------------------------------------------------------------
// OBJ and GLB
// ---------------------------------------------------------------------------
// Operation "export_obj" (exporter/obj.py): `v` and `f` records only, "%.17g".
SurfaceExportReport export_obj(const std::vector<TopoDS_Shape>& shapes, const std::filesystem::path& path,
                               const SurfaceMeshParameters& parameters = {});
Bytes obj_bytes(const WeldedMesh& mesh);

// Operation "export_glb": a binary glTF 2.0 file with one mesh, one primitive
// (POSITION, NORMAL, indices).  Uses mesh() so faces keep their own vertices and
// sharp CAD edges; `face_ids` are stored in the primitive's `extras`.
Bytes glb_bytes(const Mesh& mesh);
void export_glb(const std::vector<TopoDS_Shape>& shapes, const std::filesystem::path& path,
                const MeshParameters& parameters = {});

// ---------------------------------------------------------------------------
// BREP files (operations "export_brep" / "import_brep")
// ---------------------------------------------------------------------------
void export_brep(const Shape& shape, const std::filesystem::path& path);
Shape import_brep(const std::filesystem::path& path, const BrepReadOptions& options = {});

}  // namespace scad::io
