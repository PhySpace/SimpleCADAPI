// SPDX-License-Identifier: LGPL-2.1-only WITH OCCT-exception-1.0
#ifndef BRepOffsetAPI_GraphPatch_HeaderFile
#define BRepOffsetAPI_GraphPatch_HeaderFile
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Trsf.hxx>

//! Degree-eight variational graph patch. The arrays contain Count ordered seam
//! edges, their incident support faces and geometric continuity orders 0/1/2.
//! Frame maps the local graph to world coordinates; null fits a PCA plane.
//! On a failed domain, fit or topology check return false, leaving Result alone.
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
