// Which closed profile of a solved sketch lies inside which: the nesting that makes regions (an outer loop minus the
// loops directly inside it).  Internal to the sketch library; inspect_sketch_rsketchprofiles reports it and
// make_faces_from_sketch_rfacelist builds faces from it.
#pragma once

#include <vector>

#include "scad/sketch/profile.hpp"

namespace scad::sketch_detail {

// Per profile (same order as `profiles`): the index of the closed profile it lies directly inside (-1: none, and for
// every open chain), and its depth (0: outside every loop; -1 for an open chain).  Even depth: an outer loop of a
// region; odd: a hole of the region of its parent.  A loop is inside another when most of its points are and it is the
// smaller one; crossing loops are not regions and are nested by that test only.
struct ProfileNesting {
  int parent = -1;
  int depth = -1;
};
std::vector<ProfileNesting> profile_nesting(const Sketch& sketch, const SketchSolveResult& result,
                                            const std::vector<SketchProfile>& profiles);

}  // namespace scad::sketch_detail
