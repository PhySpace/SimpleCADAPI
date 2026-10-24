// Local features that rewrite faces of one solid: fillet, chamfer, shell, offset, draft.
#pragma once

#include <optional>
#include <string>

#include "scad/ops/features/support.hpp"
#include "scad/ops/features/tags.hpp"
#include "scad/ops/geometry/types.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

// Round `edges` (explicit, or a ql selector resolved in `solid`) by `radius`.  Role:
// fillet.patch.  A failing blend is explained with measurements (size against face room,
// tangent faces, ...), and a result no convex blend can produce is rejected.
// Error "fillet_rsolid".
Solid fillet_rsolid(const Solid& solid, const EdgeSelection& edges, const Scalar& radius, const BlendTags& tags = {});

struct ChamferOptions {
  // Degrees between the chamfer face and the reference face; the second leg is
  // distance * tan(angle).  Needs `reference_direction`.
  std::optional<double> angle;
  // Per edge, the adjacent face whose outward normal best matches this is the reference face.
  std::optional<Vec3> reference_direction;
  BlendTags tags;
};

// Bevel `edges` by `distance` (symmetric unless options.angle is given).  Role: chamfer.patch.
// Error "chamfer_rsolid".
Solid chamfer_rsolid(const Solid& solid, const EdgeSelection& edges, const Scalar& distance,
                     const ChamferOptions& options = {});

// Hollow `solid` inward by `thickness`, removing `faces_to_remove`.  Roles: shell.body_face,
// shell.offset_face, shell.closing_descendant, shell.wall.  Error "shell_rsolid".
Solid shell_rsolid(const Solid& solid, const FaceSelection& faces_to_remove, const Scalar& thickness,
                   const ShellTags& tags = {});

struct OffsetOptions {
  double tolerance = 1e-4;
  std::string kind = "ARC";  // join type: "ARC" or "INTERSECTION"
};

// Offset `solid` outward (positive) or inward (negative); faces in `openings` are left open.
// Recorded as make_offset_rsolid.
Solid offset_rsolid(const Solid& solid, const Scalar& amount, const FaceSelection& openings = {},
                    const OffsetOptions& options = {});

// Draft planar, cylindrical or conical faces by a signed angle in degrees about a neutral plane
// (origin and normal in current coordinates).  Recorded as make_draft_rsolid.
Solid draft_rsolid(const Solid& solid, const FaceSelection& faces_to_draft, const Scalar& angle,
                   const Scalar3& plane_origin = scalar3(0, 0, 0), const Scalar3& plane_normal = scalar3(0, 0, 1));

}  // namespace scad
