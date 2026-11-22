// SPDX-License-Identifier: LGPL-2.1-only WITH OCCT-exception-1.0
#ifndef BRepFilletAPI_TangentY_HeaderFile
#define BRepFilletAPI_TangentY_HeaderFile
#include <TopoDS_Solid.hxx>
#include <TopoDS_Edge.hxx>

//! Restricted, opt-in Y transition. Accepts one canonical millimetre plate/post
//! solid, its tangent top-side line and root semicircle (either order), and one
//! constant radius. No result history. Result is assigned only on success.
class BRepFilletAPI_TangentY
{
public:
  Standard_EXPORT static bool TryBuild(const TopoDS_Solid& source,
                                       const TopoDS_Edge&  first,
                                       const TopoDS_Edge&  second,
                                       double              radius,
                                       TopoDS_Solid&       result);
};
#endif
