// Failure-evidence images: an operation that diagnoses a failure asks for a picture of it.
//
// The picture is drawn by whoever registered a provider (the Python module does: matplotlib for the 2D plans, the
// software renderer for solids); with none registered, or with rendering switched off, there is simply no image and
// the error stays text-complete.  A provider may refuse (nullopt) and may throw: neither reaches the caller.
#pragma once

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include "scad/core/error.hpp"
#include "scad/core/value.hpp"
#include "scad/topo/shape.hpp"

namespace scad {

struct DiagnosticImage {
  std::string kind;       // "render" (3D), "wire_plan_render" (2D plan of wires), "sketch_render" (a sketch)
  std::string operation;  // the failing operation ("union_rsolid")
  std::string view;       // what the picture shows ("default", "best-fit plane projection")
  std::string caption;
  std::string dedup_key;               // the same failure is drawn once per process
  std::vector<Shape> shapes;           // what to draw (3D kinds, and the wires of the plans)
  std::vector<Shape> highlight_edges;  // edges of `shapes` a 3D picture draws as orange lines
  Value payload = Value::object();     // kind-specific data: marks, labels, entities, what is implicated
};

using DiagnosticImageProvider = std::function<std::optional<ErrorEvidence>(const DiagnosticImage&)>;

// An empty function removes the provider.
void set_diagnostic_image_provider(DiagnosticImageProvider provider);

// The evidence for `request`, or nothing.  Never throws.
std::optional<ErrorEvidence> diagnostic_image(const DiagnosticImage& request);

}  // namespace scad
