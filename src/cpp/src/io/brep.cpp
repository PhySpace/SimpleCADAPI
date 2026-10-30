#include "scad/io/brep.hpp"

#include <algorithm>
#include <sstream>
#include <vector>

#include <BRepCheck_Analyzer.hxx>
#include <BRepTools.hxx>
#include <BRep_Builder.hxx>
#include <BinTools.hxx>
#include <BinTools_FormatVersion.hxx>

#include "bytes.hpp"
#include "scad/core/error.hpp"
#include "scad/io/hash.hpp"

namespace scad::io {

namespace {

constexpr std::string_view kBinToolsPreamble = "\nOpen CASCADE Topology V";
constexpr int kMaxDecodeRounds = 32;

bool is_binary_brep(std::string_view bytes) {
  return bytes.substr(0, kBinToolsPreamble.size()) == kBinToolsPreamble;
}

// Legacy / external ASCII dumps start with "DBRep_DrawableShape" or straight with the version banner.
bool looks_like_ascii_brep(std::string_view bytes) {
  const std::string_view head = bytes.substr(0, 256);
  return head.find("CASCADE Topology V") != std::string_view::npos;
}

}  // namespace

Bytes to_brep_bytes(const TopoDS_Shape& shape) {
  if (shape.IsNull())
    throw ValueError("cannot write a null shape as BREP");
  return occt_guard([&] {
    std::ostringstream out(std::ios::binary);
    BinTools::Write(shape, out, /*theWithTriangles=*/false, /*theWithNormals=*/false, BinTools_FormatVersion_VERSION_4);
    if (!out)
      throw RuntimeError("OpenCASCADE failed to write the BREP bytes");
    Bytes bytes = std::move(out).str();
    if (bytes.empty())
      throw RuntimeError("OpenCASCADE produced empty BREP bytes");
    return bytes;
  });
}

TopoDS_Shape from_brep_bytes(std::string_view bytes, const BrepReadOptions& options) {
  if (bytes.empty())
    throw ValueError("BREP bytes are empty");
  const bool binary = is_binary_brep(bytes);
  if (!binary && !looks_like_ascii_brep(bytes))
    throw ValueError("the bytes are not an OpenCASCADE BREP (neither BinTools binary nor ASCII BRep)");
  TopoDS_Shape shape = occt_guard([&] {
    detail::ViewStream in(bytes);
    TopoDS_Shape result;
    if (binary) {
      BinTools::Read(result, in);
    } else {
      BRep_Builder builder;
      BRepTools::Read(result, in, builder);
    }
    return result;
  });
  if (shape.IsNull())
    throw ValueError("OpenCASCADE could not read a shape from the BREP bytes");
  if (options.require_valid && !occt_guard([&] { return BRepCheck_Analyzer(shape).IsValid() == Standard_True; }))
    throw ValueError("OpenCASCADE reports invalid topology in the BREP");
  return shape;
}

Bytes canonical_brep_bytes(const TopoDS_Shape& shape) {
  Bytes current = to_brep_bytes(shape);
  std::vector<Bytes> seen;
  while (std::find(seen.begin(), seen.end(), current) == seen.end()) {
    if (static_cast<int>(seen.size()) == kMaxDecodeRounds)
      return seen.front();
    seen.push_back(current);
    current = to_brep_bytes(from_brep_bytes(current));
  }
  const auto cycle_start = std::find(seen.begin(), seen.end(), current);
  return *std::min_element(cycle_start, seen.end());
}

std::string brep_sha256(const TopoDS_Shape& shape) {
  return sha256_tagged(canonical_brep_bytes(shape));
}

void write_brep(const std::filesystem::path& path, const TopoDS_Shape& shape) {
  write_file(path, to_brep_bytes(shape));
}

TopoDS_Shape read_brep(const std::filesystem::path& path, const BrepReadOptions& options) {
  return from_brep_bytes(read_file(path), options);
}

Bytes to_brep(const Shape& shape) {
  return to_brep_bytes(shape.wrapped());
}

Shape from_brep(std::string_view bytes, const BrepReadOptions& options) {
  return Shape::from_occt(from_brep_bytes(bytes, options));
}

}  // namespace scad::io
