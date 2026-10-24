// BREP region snapshots: the `.scadbrep` container.
//
// Port of simplecadapi/_internal/brep_region.py and kernel/ocp_brep_snapshot.py:
// a hash-pinned, mesh-free copy of one solid, or of one connected face shell,
// taken from a target STEP file, that a model can replay without that STEP.
//
//   container  = header (32 bytes, big-endian) || canonical-JSON manifest || BinTools payload
//   header     = "SCADBREP" u16 major(1) u16 minor(0) u32 flags(0) u64 manifest_size u64 payload_size
//   manifest   = RFC 8785 canonical JSON, a closed schema (every key checked)
//   payload    = BinTools V4, no triangulation, no normals
//
// The files interoperate with the Python SDK in both directions.  One thing
// cannot be shared: the manifest names the exporting OCP build ("7.9.3.1" for the
// cadquery-ocp wheel).  A reader here accepts any version whose major.minor equals
// this OCCT's (BinTools V4 is stable within it); a writer stamps `ocp_version`,
// which defaults to this OCCT's version -- pass the wheel's version string to
// produce a file the Python SDK will accept.
//
// Floating-point descriptors (volume, face area, centroid) are compared with a
// relative tolerance of 1e-9 instead of for exact equality, so an artifact
// written on one CPU verifies on another.
#pragma once

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <TopoDS_Shape.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>

#include "scad/core/value.hpp"
#include "scad/io/files.hpp"

namespace scad::io {

enum class RegionRootKind { Shell, Solid };
std::string_view to_string(RegionRootKind kind) noexcept;  // "shell" / "solid"

inline constexpr std::string_view kBRegionMagic = "SCADBREP";
inline constexpr std::uint16_t kBRegionMajorVersion = 1;
inline constexpr std::uint16_t kBRegionMinorVersion = 0;
inline constexpr std::size_t kBRegionHeaderSize = 32;
inline constexpr std::size_t kBRegionMaxArtifactBytes = std::size_t{64} << 20;
inline constexpr std::size_t kBRegionMaxManifestBytes = std::size_t{8} << 20;

// The OCCT version this build writes into new manifests ("7.9.3").
std::string default_ocp_version();
// "scadbrep-1-ocp-<ocp_version>-bintools-v4-no-mesh"
std::string region_profile(std::string_view ocp_version);

// ---------------------------------------------------------------------------
// Shape descriptors (kernel/ocp_brep_snapshot.py).  Errors are ValueError.
// ---------------------------------------------------------------------------
struct ShapeDescriptor {
  RegionRootKind root_kind = RegionRootKind::Solid;
  bool valid = false;
  std::int64_t solid_count = 0, shell_count = 0, face_count = 0, edge_count = 0, vertex_count = 0;
  std::optional<double> volume;  // solids
  std::optional<bool> closed;    // shells

  Value to_value() const;  // the manifest's "shape" members, in Python's key set
};

bool has_triangulation(const TopoDS_Shape& shape);
ShapeDescriptor shell_descriptor(const TopoDS_Shell& shell);
ShapeDescriptor solid_descriptor(const TopoDS_Solid& solid);  // positive finite volume required
TopoDS_Shell require_single_valid_shell(const TopoDS_Shape& shape);
TopoDS_Solid require_single_valid_solid(const TopoDS_Shape& shape);
ShapeDescriptor shape_descriptor(const TopoDS_Shape& shape, RegionRootKind kind);

// One record per face in TopExp::MapShapes order: surface_type ("GeomAbs_Plane"),
// orientation ("TopAbs_FORWARD"), area and centroid rounded to 12 places, edge_count.
Value face_fingerprints(const TopoDS_Shape& shape);

Bytes encode_shape(const TopoDS_Shape& shape, RegionRootKind kind);  // validated BinTools V4
TopoDS_Shape decode_shape(std::string_view payload, RegionRootKind kind);

// ---------------------------------------------------------------------------
// The container
// ---------------------------------------------------------------------------
// Failures are scad::MessageError("brep_region", ...), the BRepRegionError analogue.
Bytes encode_artifact(const Value& manifest, std::string_view payload);

struct DecodedRegion {
  TopoDS_Shape shape;  // a Solid or a Shell
  Value manifest;
  RegionRootKind root_kind = RegionRootKind::Solid;
};
DecodedRegion decode_artifact(std::string_view bytes, std::optional<RegionRootKind> expected = std::nullopt);

struct RegionFile {
  TopoDS_Shape shape;
  Value manifest;
  std::string sha256;  // "sha256:<hex>" of the whole file
};
// Reads `path`, requires its SHA-256 to equal `sha256` ("sha256:" prefix optional,
// case-insensitive), then decodes.  With `replay_root` the path is resolved
// inside that directory and may not escape it or traverse a symbolic link or
// reparse point (the GraphSession replay rule).
RegionFile read_artifact(const std::filesystem::path& path, std::string_view sha256, RegionRootKind expected,
                         const std::optional<std::filesystem::path>& replay_root = std::nullopt);

// ---------------------------------------------------------------------------
// Creating a snapshot (inspect/brep/snapshots.py, without face selection)
// ---------------------------------------------------------------------------
struct RegionSource {
  std::string name;          // the STEP file's name
  std::size_t byte_length = 0;
  std::string content_hash;  // "sha256:<hex>" of the STEP bytes
  int transferred_root_count = 1;
};

// A complete single solid, or a shell with explicit `source_face_ids` ("face:<n>",
// one per face in the shell's MapShapes order).  The artifact is decoded again
// before it is returned, as the Python writer does.
Bytes make_region_artifact(const TopoDS_Shape& shape, RegionRootKind kind, const RegionSource& source,
                           const std::vector<std::string>& source_face_ids = {},
                           std::string_view ocp_version = {});

// `copy_step_region_rpath(path, output_path)` for a whole solid: reads one STEP
// solid, writes the `.scadbrep` atomically.  Returns the absolute output path.
std::filesystem::path copy_step_solid_region(const std::filesystem::path& step_path,
                                             const std::filesystem::path& output_path,
                                             std::string_view ocp_version = {});

// _brep_region_path (operators/geometry.py): the checks on a `.scadbrep` locator
// -- extension, no ':' in the name, and for graph replay relative, no drive, no
// "..", '/' separators.  Returns the string to record (generic form when
// for_graph).  Throws ValueError.
std::string checked_region_path(std::string_view path, bool for_graph);

}  // namespace scad::io
