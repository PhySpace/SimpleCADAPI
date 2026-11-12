#include "scad/kernel/booleans.hpp"

#include <BOPAlgo_GlueEnum.hxx>
#include <BOPAlgo_Operation.hxx>
#include <BRepAlgoAPI_BooleanOperation.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <Standard_Failure.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>

#include "scad/core/error.hpp"
#include "scad/kernel/membership.hpp"
#include "scad/kernel/topology.hpp"

namespace scad::kernel {

namespace {

BOPAlgo_Operation bop_of(BooleanOp op) noexcept {
  switch (op) {
    case BooleanOp::Cut:
      return BOPAlgo_CUT;
    case BooleanOp::Common:
      return BOPAlgo_COMMON;
    case BooleanOp::Fuse:
      return BOPAlgo_FUSE;
  }
  return BOPAlgo_UNKNOWN;
}

TopTools_ListOfShape list_of(const TopoDS_Shape& shape) {
  TopTools_ListOfShape out;
  out.Append(shape);
  return out;
}

TopTools_ListOfShape list_of(const std::vector<TopoDS_Shape>& shapes) {
  TopTools_ListOfShape out;
  for (const TopoDS_Shape& shape : shapes)
    out.Append(shape);
  return out;
}

// Glue is an optimisation, not a stronger boolean: for intersecting curved or
// N-ary inputs it can hand back a compound of the original solids without
// intersecting them.  Retrying unglued is safe because the public union
// contract rejects genuinely separate or lower-dimensional contacts anyway.
bool glue_result_is_inconclusive(const std::vector<TopoDS_Shape>& shapes, const TopoDS_Shape& result) {
  return shapes.size() > 1 && solids_of(result).size() != 1;
}

std::vector<TopoDS_Shape> tail_of(const std::vector<TopoDS_Shape>& shapes) {
  return std::vector<TopoDS_Shape>(shapes.begin() + 1, shapes.end());
}

bool is_valid_shape(const TopoDS_Shape& shape) {
  return !shape.IsNull() && BRepCheck_Analyzer(shape).IsValid() == Standard_True;
}

// Follow each section edge through a clean-up: it may have been merged into a longer edge or dropped with a removed
// face.  Only the edges that are in `cleaned` survive, each once.
std::vector<TopoDS_Shape> follow_section_edges(const opencascade::handle<BRepTools_History>& clean_history,
                                               const TopoDS_Shape& cleaned,
                                               const std::vector<TopoDS_Shape>& section_edges) {
  SubShapeIndex result(cleaned);
  TopTools_IndexedMapOfShape seen;
  std::vector<TopoDS_Shape> survivors;
  for (const TopoDS_Shape& edge : section_edges) {
    std::vector<TopoDS_Shape> candidates;
    for (const TopoDS_Shape& s : clean_history->Modified(edge))
      candidates.push_back(s);
    for (const TopoDS_Shape& s : clean_history->Generated(edge))
      candidates.push_back(s);
    if (candidates.empty() && !clean_history->IsRemoved(edge))
      candidates.push_back(edge);
    for (const TopoDS_Shape& candidate : candidates) {
      if (!result.contains(candidate))
        continue;
      const int before = seen.Extent();
      seen.Add(candidate);
      if (seen.Extent() > before)
        survivors.push_back(candidate);
    }
  }
  return survivors;
}

// BooleanOptions::clean.  The unified shape replaces the result only when it is as good: the same number of solids, and
// valid whenever the raw result was (FreeCAD and build123d fall back to the raw result the same way; unifying every
// boolean result has been seen to invalidate some).
void unify_result(BooleanResult& result) {
  try {
    ShapeUpgrade_UnifySameDomain unifier(result.shape, /*UnifyEdges=*/true, /*UnifyFaces=*/true,
                                         /*ConcatBSplines=*/true);
    unifier.Build();
    const TopoDS_Shape cleaned = unifier.Shape();
    if (cleaned.IsNull() || solids_of(cleaned).size() != solids_of(result.shape).size())
      return;
    if (!is_valid_shape(cleaned) && is_valid_shape(result.shape))
      return;
    if (!result.history.IsNull()) {
      const opencascade::handle<BRepTools_History> clean_history = unifier.History();
      result.history->Merge(clean_history);
      result.section_edges = follow_section_edges(clean_history, cleaned, result.section_edges);
    }
    result.shape = cleaned;
  } catch (const Standard_Failure&) {
    // the raw result stands
  }
}

}  // namespace

BooleanResult run_boolean(BooleanOp op, const TopoDS_Shape& argument, const std::vector<TopoDS_Shape>& tools,
                          const BooleanOptions& options) {
  return occt_guard([&] {
    BRepAlgoAPI_BooleanOperation builder;
    builder.SetOperation(bop_of(op));
    builder.SetRunParallel(true);
    builder.SetUseOBB(true);
    builder.SetToFillHistory(options.fill_history);
    builder.SetArguments(list_of(argument));
    builder.SetTools(list_of(tools));
    if (options.fuzzy)
      builder.SetFuzzyValue(*options.fuzzy);
    builder.SetGlue(options.glue ? BOPAlgo_GlueShift : BOPAlgo_GlueOff);
    builder.Build();

    BooleanResult out;
    out.done = builder.IsDone();
    if (!out.done)
      return out;
    out.shape = builder.Shape();
    if (options.fill_history) {
      out.history = builder.History();
      // Section edges are evidence, not the result: a kernel that cannot list
      // them must not fail the boolean (the Python SDK treats it the same way).
      try {
        for (const TopoDS_Shape& edge : builder.SectionEdges())
          out.section_edges.push_back(edge);
      } catch (const Standard_Failure&) {
        out.section_edges.clear();
      }
    }
    if (options.clean)
      unify_result(out);
    return out;
  });
}

TopoDS_Shape clean_shape(const TopoDS_Shape& shape) {
  return occt_guard([&] {
    ShapeUpgrade_UnifySameDomain unifier(shape, /*UnifyEdges=*/true, /*UnifyFaces=*/true,
                                         /*ConcatBSplines=*/true);
    unifier.Build();
    return unifier.Shape();
  });
}

FuseHistoryResult fuse_shapes_with_history(const std::vector<TopoDS_Shape>& shapes, bool glue,
                                           std::optional<double> tol, bool clean) {
  if (shapes.empty())
    throw ValueError("fuse_shapes requires at least one shape");
  if (shapes.size() == 1) {
    FuseHistoryResult single;
    single.shape = shapes.front();
    single.history = new BRepTools_History;
    return single;
  }

  BooleanOptions options;
  options.fill_history = true;
  options.fuzzy = tol;
  options.glue = glue;
  BooleanResult fused = run_boolean(BooleanOp::Fuse, shapes.front(), tail_of(shapes), options);
  if (!fused.done)
    throw ValueError("OCP fuse failed");

  if (glue && glue_result_is_inconclusive(shapes, fused.shape)) {
    return fuse_shapes_with_history(shapes, /*glue=*/false, tol, clean);
  }

  FuseHistoryResult out;
  out.shape = fused.shape;
  out.history = fused.history;
  out.section_edges = std::move(fused.section_edges);
  if (out.history.IsNull())
    out.history = new BRepTools_History;
  if (!clean)
    return out;

  return occt_guard([&] {
    ShapeUpgrade_UnifySameDomain unifier(out.shape, true, true, true);
    unifier.Build();
    out.shape = unifier.Shape();
    const opencascade::handle<BRepTools_History> clean_history = unifier.History();
    out.history->Merge(clean_history);

    out.section_edges = follow_section_edges(clean_history, out.shape, out.section_edges);
    return out;
  });
}

TopoDS_Shape fuse_shapes(const std::vector<TopoDS_Shape>& shapes, bool glue, std::optional<double> tol, bool clean) {
  if (shapes.empty())
    throw ValueError("fuse_shapes requires at least one shape");
  if (shapes.size() == 1)
    return shapes.front();

  BooleanOptions options;
  options.fuzzy = tol;
  options.glue = glue;
  const BooleanResult fused = run_boolean(BooleanOp::Fuse, shapes.front(), tail_of(shapes), options);
  if (!fused.done)
    throw ValueError("OCP fuse failed");
  if (glue && glue_result_is_inconclusive(shapes, fused.shape))
    return fuse_shapes(shapes, false, tol, clean);
  return clean ? clean_shape(fused.shape) : fused.shape;
}

TopoDS_Shape cut_shapes(const TopoDS_Shape& body, const std::vector<TopoDS_Shape>& tools, bool clean) {
  if (tools.empty())
    return body;
  BooleanOptions options;
  options.clean = clean;
  const BooleanResult cut = run_boolean(BooleanOp::Cut, body, tools, options);
  if (!cut.done)
    throw ValueError("OCP cut failed");
  return cut.shape;
}

TopoDS_Shape common_shapes(const std::vector<TopoDS_Shape>& shapes, bool clean) {
  if (shapes.empty())
    throw ValueError("common_shapes requires at least one shape");
  TopoDS_Shape result = shapes.front();
  for (std::size_t i = 1; i < shapes.size(); ++i) {
    BooleanOptions options;
    options.clean = clean;
    const BooleanResult common = run_boolean(BooleanOp::Common, result, {shapes[i]}, options);
    if (!common.done)
      throw ValueError("OCP common failed");
    result = common.shape;
  }
  return result;
}

}  // namespace scad::kernel
