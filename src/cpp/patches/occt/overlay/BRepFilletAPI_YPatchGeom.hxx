// SPDX-License-Identifier: LGPL-2.1-only WITH OCCT-exception-1.0
// Internal geometry of BRepFilletAPI_YPatch (not part of the public API).
#ifndef _BRepFilletAPI_YPatchGeom_HeaderFile
#define _BRepFilletAPI_YPatchGeom_HeaderFile

#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <ShapeAnalysis_Surface.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Vec.hxx>

namespace YPatch
{
//! A support face: point, outward normal and inverse by uv.
struct Support
{
  TopoDS_Face                   face;
  BRepAdaptor_Surface           s;
  double                        sign;
  Handle(ShapeAnalysis_Surface) proj;

  explicit Support(const TopoDS_Face& f);
  gp_Pnt   P(const gp_Pnt2d& uv) const;
  gp_Vec   N(const gp_Pnt2d& uv) const; //!< outward unit normal
  gp_Pnt2d UV(const gp_Pnt& p) const;
  gp_Pnt2d UVNear(const gp_Pnt& p, const gp_Pnt2d& seed) const;
};

//! A selected edge parametrised by lambda in [0,1] from the junction vertex.
struct Rail
{
  TopoDS_Edge       edge;
  BRepAdaptor_Curve c;
  double            first, last;

  Rail(const TopoDS_Edge& e, const TopoDS_Vertex& v);
  double   Param(double lambda) const;
  gp_Pnt   P(double lambda) const;
  gp_Vec   T(double lambda) const; //!< unit tangent pointing away from the vertex
  gp_Pnt2d UV(const TopoDS_Face& f, double lambda) const;
};

//! A rolling-ball section: contacts on T and on X, and the centre.
struct Ball
{
  double   lambda = 0;
  gp_Pnt2d uvT, uvX;
  gp_Pnt   pT, pX, c;
};

//! The constant-radius band of one rail between the common face T and its own support X.
struct Band
{
  const Rail&    rail;
  const Support& T;
  const Support& X;
  double         r;
  double         sigma; //!< +1 concave (centre outside the material), -1 convex

  bool Solve(double lambda, Ball& b, const Ball* seed = nullptr) const;
};

double angle(const gp_Vec& a, const gp_Vec& b);
} // namespace YPatch

#endif
