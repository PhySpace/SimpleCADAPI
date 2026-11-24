// SPDX-License-Identifier: LGPL-2.1-only WITH OCCT-exception-1.0
#ifndef BRepOffsetAPI_GraphPatch_HeaderFile
#define BRepOffsetAPI_GraphPatch_HeaderFile
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Trsf.hxx>

//! Degree-eight variational graph patch filling one loop of Count edges.
//!
//! Input contract: Edges[i] is an edge of Supports[i], the patch meets that support with
//! geometric continuity Orders[i] (0, 1 or 2: C0, G1, G2); consecutive edges (and the last with
//! the first) share an end point, each edge in either orientation, so the loop is closed and
//! ordered. Frame maps the local graph to world coordinates (no scaling, no mirror); null fits
//! a PCA plane to the boundary. The loop must project one-to-one onto the frame plane, and a
//! G1/G2 support must be a graph over it along its edge.
//!
//! The patch is a degree-eight Bezier graph over the frame plane, trimmed by the projected loop.
//! Boundary data a degree-eight graph can meet (planar supports, polynomial ones) are met
//! exactly (to ~1e-10). Others (curved supports: cylinder, sphere, B-spline) are fitted as
//! a whole; the patch is then accepted if, densely along every edge, it is within 1e-3 of the
//! support edge, its normal within 1e-3 rad of the support's (G1, G2) and its cross-boundary
//! normal curvature within 5% of the support's (G2), and the edges of the result carry that
//! gap as their tolerance. The freedom the boundary leaves follows the supports' own surfaces
//! continued over the loop, where they are graphs over the frame (a hole cut in one surface is
//! filled by that surface, to the accuracy of a degree-eight graph); otherwise the patch
//! minimises its squared Hessian.
//!
//! Returns false, leaving Result alone, on a broken contract, a loop that is no graph over the
//! frame, a fit outside those limits or an invalid face. With GRAPHPATCH_TRACE defined at the
//! compilation of the implementation, the refusing check and the fit's measures are printed.
class BRepOffsetAPI_GraphPatch
{
public:
  Standard_EXPORT static bool TryBuild(int                count,
                                       const TopoDS_Edge* edges,
                                       const TopoDS_Face* supports,
                                       const int*         orders,
                                       TopoDS_Face&       result,
                                       const gp_Trsf*     frame = nullptr);
};
#endif
