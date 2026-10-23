// Threaded fasteners (std/fastener.py): bolts and nuts, with metric coarse-pitch defaults.
#pragma once

#include <optional>
#include <string>

#include "scad/topo/shape.hpp"

namespace scad {

struct BoltOptions {
  // hex | square | cylindrical | button | countersunk (any case).
  std::string head_style = "hex";
  // auto (full up to 3d long, else the standard partial length) | full | partial | none.
  std::string thread_style = "auto";
  // cosmetic: smooth major-diameter shank, thread intent in metadata.  modeled: a helical groove is cut.
  std::string thread_detail = "modeled";
  std::string thread_form = "v";  // v | trapezoidal
  std::optional<double> thread_pitch;   // required outside the metric coarse series
  std::optional<double> thread_depth;
  std::optional<double> thread_length;  // only with thread_style "partial"
  std::optional<double> head_width, head_height;  // default: ISO 4014 for hex, proportions of d otherwise
  std::string drive_style = "none";  // none | slot | cross | hex_socket
  std::optional<double> drive_size, drive_depth;
  std::optional<double> underhead_fillet_radius;  // default 0.06 d (none under a countersunk head)
};

// A bolt along +Z with the underside of its head on the Z = 0 plane.  Metadata "std.fastener.bolt"
// records the resolved dimensions.  Tags role.fastener.bolt and group.fasteners.
// ValueError for an unknown style, a head not wider than the shank, a thread that does not fit,
// a drive too large for the head, an unstable modeled thread.
Solid make_bolt_rsolid(double diameter, double length, const BoltOptions& options = {});

struct NutOptions {
  std::string nut_style = "hex";       // hex | square | round | knurled
  std::string hole_style = "through";  // through | blind
  std::string thread_detail = "modeled";
  std::string thread_form = "v";
  std::optional<double> thread_pitch, thread_depth;
  std::optional<double> hole_depth;  // blind holes only; default 0.75 of the height
  int knurl_count = 24;              // knurled nuts: at least 8
};

// A nut along +Z with its bottom face on the Z = 0 plane.  Metadata "std.fastener.nut".
// Tags role.fastener.nut and group.fasteners.
Solid make_nut_rsolid(double diameter, double width, double height, const NutOptions& options = {});

}  // namespace scad
