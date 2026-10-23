// BREP bytes: the exchange form between this library, files, and the OCP wheel.
//
// The format is OpenCASCADE's BinTools binary, **format version 4**
// (BinTools_FormatVersion_VERSION_4), written without triangulation and
// without normals: every double is stored bit-exactly, so a shape read back is
// geometrically identical to the one written, and the bytes do not depend on
// whether the shape was meshed before.  Version 4 is what the Python SDK
// (cadquery-ocp, OCCT 7.9) writes and reads, and every OCCT from 7.3 on reads
// it, so `to_brep()` bytes can be handed to `OCP.BinTools.Read_s` and back.
//
// The reader also accepts every older BinTools version and OCCT's ASCII BRep
// text (`BRepTools::Write` output), detected from the first bytes.
#pragma once

#include <filesystem>
#include <string>
#include <string_view>

#include <TopoDS_Shape.hxx>

#include "scad/io/files.hpp"
#include "scad/topo/shape.hpp"

namespace scad::io {

inline constexpr int kBrepFormatVersion = 4;  // BinTools_FormatVersion_VERSION_4

struct BrepReadOptions {
  bool require_valid = false;  // BRepCheck_Analyzer must accept the shape
};

// ---- OCCT level ------------------------------------------------------------
// BinTools V4 bytes of `shape`, geometry only.  ValueError for a null shape.
Bytes to_brep_bytes(const TopoDS_Shape& shape);

// A shape from BinTools (any version) or ASCII BRep bytes.  ValueError when the
// bytes are not a BREP or hold a null shape.
TopoDS_Shape from_brep_bytes(std::string_view bytes, const BrepReadOptions& options = {});

// The deterministic encoding to hash.  Reading is not byte-idempotent (some
// zeros come back as -0.0, a few doubles move by an ulp per round trip,
// settling into a cycle), so the shape is encoded, decoded and re-encoded until
// the encodings repeat, and the smallest member of the cycle is returned (the
// first encoding when no cycle appears within 32 rounds).  Port of
// artifacts/brep.py write_brep_bytes.
Bytes canonical_brep_bytes(const TopoDS_Shape& shape);
std::string brep_sha256(const TopoDS_Shape& shape);  // "sha256:<hex>" of the canonical bytes

// ---- files -------------------------------------------------------------------
void write_brep(const std::filesystem::path& path, const TopoDS_Shape& shape);
TopoDS_Shape read_brep(const std::filesystem::path& path, const BrepReadOptions& options = {});

// ---- handles (Python: Shape.to_brep() / Shape.from_brep(bytes)) -------------
Bytes to_brep(const Shape& shape);
Shape from_brep(std::string_view bytes, const BrepReadOptions& options = {});
// The kind is read from the shape: a Solid comes back as Kind::Solid, and so on.
// Compound-of-one stays a Compound.

}  // namespace scad::io
