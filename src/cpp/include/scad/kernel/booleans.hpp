// Boolean operations on raw OCCT shapes (ocp_booleans.py).
//
// `run_boolean` is the one place the algorithm is configured (parallel, OBB,
// optional history).  The Python-named helpers are thin wrappers over it;
// tracking uses `run_boolean` / `fuse_shapes_with_history` directly so it can
// ask the retained history what happened to each input sub-shape.
#pragma once

#include <optional>
#include <vector>

#include <BRepTools_History.hxx>
#include <TopoDS_Shape.hxx>

#include "scad/kernel/topology.hpp"  // solids_of (ocp_booleans.solids_of lives there)

namespace scad::kernel {

enum class BooleanOp { Cut, Common, Fuse };

struct BooleanOptions {
  bool fill_history = false;       // keep BRepTools_History + section edges
  std::optional<double> fuzzy;     // fuzzy tolerance (SetFuzzyValue)
  bool glue = false;               // BOPAlgo_GlueShift instead of GlueOff
};

struct BooleanResult {
  bool done = false;               // BRepAlgoAPI::IsDone(); the other fields are empty when false
  TopoDS_Shape shape;              // usually a compound holding the result solid(s)
  opencascade::handle<BRepTools_History> history;  // null unless fill_history
  std::vector<TopoDS_Shape> section_edges;         // empty unless fill_history
};

// `argument` op (every shape in `tools`), run in one pass.
BooleanResult run_boolean(BooleanOp op, const TopoDS_Shape& argument, const std::vector<TopoDS_Shape>& tools,
                          const BooleanOptions& options = {});

// ShapeUpgrade_UnifySameDomain over faces, edges and B-splines.
TopoDS_Shape clean_shape(const TopoDS_Shape& shape);

struct FuseHistoryResult {
  TopoDS_Shape shape;
  opencascade::handle<BRepTools_History> history;  // fuse (+ clean) history, merged
  std::vector<TopoDS_Shape> section_edges;         // only those that are in `shape`
};

// Fuse `shapes` in one pass and keep the history, through the optional
// same-domain clean-up.  ValueError for no shapes or a failed fuse.  A single
// shape is returned as is, with an empty history.  With `glue`, an inconclusive
// glue result (the inputs came back as separate solids) is retried unglued.
FuseHistoryResult fuse_shapes_with_history(const std::vector<TopoDS_Shape>& shapes, bool glue = false,
                                           std::optional<double> tol = std::nullopt, bool clean = true);

// The same without history.
TopoDS_Shape fuse_shapes(const std::vector<TopoDS_Shape>& shapes, bool glue = false,
                         std::optional<double> tol = std::nullopt, bool clean = true);

// body - every tool.  `body` itself when there are no tools.
TopoDS_Shape cut_shapes(const TopoDS_Shape& body, const std::vector<TopoDS_Shape>& tools);

// Intersection of all shapes, folded left to right.
TopoDS_Shape common_shapes(const std::vector<TopoDS_Shape>& shapes);

}  // namespace scad::kernel
