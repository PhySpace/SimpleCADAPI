// Shape serialization: geometry plus the semantic state of every entity.
//
// The C++ counterpart of simplecadapi/_internal/shape_pickle.py.  A shape is
// reduced to
//   * the exact kernel shape as BinTools V4 bytes (bit-exact doubles, no
//     triangulation: derived data such as meshes is recomputed, never stored), and
//   * the semantic state -- tag bindings, lineage witnesses, metadata, runtime
//     values and topo_id -- of every topology entity under the root that has
//     any, keyed by the entity's 1-based position in TopExp::MapShapes(root,
//     kind).  BinTools keeps the sub-shape order, so positions line up one to
//     one after a round trip.
//
// Byte format "SCADSHAP" 1.0 (all integers big-endian) -- see docs/io.md:
//
//   offset size  field
//   0      8     magic "SCADSHAP"
//   8      2     major version (1)
//   10     2     minor version (0)
//   12     4     flags (0; unknown bits are rejected)
//   16     8     state_size   bytes of the state section
//   24     8     brep_size    bytes of the BREP section
//   32     4     CRC-32 of state section || BREP section
//   36     4     reserved (0)
//   40     ...   state section: one scad::Value, binary-encoded (docs/io.md)
//   ...    ...   BREP section: BinTools V4, as to_brep_bytes()
//
// A reader accepts the same major version and any minor version, ignoring
// state keys it does not know.
#pragma once

#include <cstdint>
#include <string_view>

#include "scad/io/files.hpp"
#include "scad/topo/shape.hpp"

namespace scad::io {

inline constexpr std::uint16_t kSerializeMajorVersion = 1;
inline constexpr std::uint16_t kSerializeMinorVersion = 0;

// Python operation names: serialize_shape / deserialize_shape.
Bytes serialize(const Shape& shape);
// The root's kind is the one that was serialized; its entities carry the saved
// state.  Throws scad::Error on truncated, corrupted or incompatible bytes.
Shape deserialize(std::string_view bytes);

}  // namespace scad::io
