// SPDX-License-Identifier: LGPL-2.1-only WITH OCCT-exception-1.0
#ifndef BRepFilletAPI_RibbonFit_HeaderFile
#define BRepFilletAPI_RibbonFit_HeaderFile
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>
#include <TopoDS_Face.hxx>

//! Tensor-product, three-dimensional fairing on a four-sided parametric domain.
//! Samples the reference position at (u,v) in [0,1]^2. Normal callback sides
//! 0,1,2,3 traverse u=0, u=1, v=0, v=1 respectively. Callbacks must be pure.
class BRepFilletAPI_RibbonFit
{
public:
  using Position = gp_Pnt (*)(const void*, double, double);
  using Normal   = gp_Vec (*)(const void*, int, double);
  Standard_EXPORT static bool TryBuild(const void*  context,
                                       Position     position,
                                       Normal       normal,
                                       TopoDS_Face& result,
                                       int          samples           = 21,
                                       double       positionTolerance = 1e-5,
                                       double       angleTolerance    = 1e-3);
};
#endif
