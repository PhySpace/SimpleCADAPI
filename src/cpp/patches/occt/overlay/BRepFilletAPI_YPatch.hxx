// SPDX-License-Identifier: LGPL-2.1-only WITH OCCT-exception-1.0
#ifndef _BRepFilletAPI_YPatch_HeaderFile
#define _BRepFilletAPI_YPatch_HeaderFile

#include <BRepTools_History.hxx>
#include <TopTools_DataMapOfShapeReal.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Vertex.hxx>
#include <gp_Pnt.hxx>
#include <NCollection_Vector.hxx>

//! Y transition between a concave and a convex constant-radius fillet whose edges meet,
//! tangentially or nearly so, at a vertex where their two non-shared support faces are
//! tangent or nearly tangent.
//!
//! Situation (the "Y junction"): edges Ein = T^A (concave) and Eout = T^B (convex) share the
//! face T and the vertex V; A and B meet at V along an unselected edge with a dihedral angle
//! close to 180 degrees.  Two rolling-ball bands cannot meet there: one ball centre lies
//! outside the material, the other inside, and both claim the same wedge of T.
//!
//! Strategy: both bands stop at the cross-sections whose contacts on T coincide (P*); the
//! wedge between V and P* is covered by two G1 ribbons, each tangent to its own support
//! and band, tangent to each other along a seam from V to P*.  Every other fillet,
//! including the far ends of these two bands, is computed by the standard algorithm.
class BRepFilletAPI_YPatch
{
public:
  //! One detected junction and, after Perform, its measured result.
  struct Junction
  {
    TopoDS_Vertex Vertex;
    TopoDS_Edge   Concave, Convex;          //!< Ein (T^A) and Eout (T^B)
    TopoDS_Face   Common, Concave2, Convex2; //!< T, A, B
    Standard_Real RConcave = 0., RConvex = 0.;
    Standard_Real SupportAngle = 0.;     //!< angle between the A and B normals at V (radians)
    gp_Pnt        Split;                 //!< P*, where both bands touch T
    Standard_Real SeamAngle    = -1.;    //!< max normal angle across the ribbon seam (radians)
    Standard_Real BandAngle    = -1.;    //!< max normal angle ribbon/band and ribbon/support
  };

  //! Largest A/B support angle (radians) still treated as a junction (near tangency).
  static constexpr Standard_Real MaxSupportAngle() { return 0.35; } // ~20 degrees

  //! Finds every junction among the constant-radius fillet edges in theRadii.
  Standard_EXPORT static NCollection_Vector<Junction> Detect(const TopoDS_Shape&               theShape,
                                                             const TopTools_DataMapOfShapeReal& theRadii);

  //! Builds the filleted solid: theRadii holds every requested edge (each constant radius).
  //! Returns false, leaving theResult untouched, when no junction exists or any step fails
  //! (construction, sewing, validity, self-interference, continuity gate).  theHistory maps
  //! input sub-shapes to the result (Modified / Generated / Removed).
  Standard_EXPORT static Standard_Boolean Perform(const TopoDS_Shape&               theShape,
                                                  const TopTools_DataMapOfShapeReal& theRadii,
                                                  TopoDS_Shape&                      theResult,
                                                  Handle(BRepTools_History)&         theHistory,
                                                  NCollection_Vector<Junction>&      theReport);
};

#endif
