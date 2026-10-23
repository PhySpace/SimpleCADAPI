// Loading `.scadbrep` region snapshots as shapes.
#pragma once

#include <string_view>

#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// A hash-pinned, target-derived BREP snapshot as one Solid / one Shell.  The SHA-256 of the
// whole file is verified before the shape is decoded.  The shape is tagged
// imported / sidecar / solid|shell, carries "brep_region" metadata, and every face a
// `provenance.exact_transcription` binding naming the source STEP face.
//
// While recording, `path` must be relative and is resolved inside the working directory
// (the model JSON records the locator and digest, not the sidecar bytes).
// Error "load_brep_region_rsolid" / "load_brep_region_rshell".
Solid load_brep_region_rsolid(std::string_view path, std::string_view sha256,
                              const OptionalString& tag_prefix = std::nullopt);
Shell load_brep_region_rshell(std::string_view path, std::string_view sha256,
                              const OptionalString& tag_prefix = std::nullopt);

}  // namespace scad
