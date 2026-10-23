/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2018 German Aerospace Center (DLR)
*
* Created: 2018-05-23 Martin Siggel <Martin.Siggel@dlr.de>
*                with Merlin Pelz   <Merlin.Pelz@dlr.de>
*/

#ifndef GORDONSURFACEBUILDER_H
#define GORDONSURFACEBUILDER_H


#include <vector>
#include <Geom_BSplineSurface.hxx>
#include <Geom_BSplineCurve.hxx>

namespace occ_gordon_internal
{

/**
 * @brief This class is basically a helper class for the occ_gordon_internal::InterpolateCurveNetwork algorithm.
 * 
 * It implements the basics gordon surface algorithm.
 * 
 * Since it requires a compatible curve network, it is not very useful on its own.
 * For practical reasons, use occ_gordon_internal::InterpolateCurveNetwork.
 */
class GordonSurfaceBuilder
{
public:
    /**
     * @brief   Builds a Gordon Surface of a given compatible network of B-splines
     *          All parameters must be in the right order and the B-spline network must be 'closed',
     *          i.e., B-splines mustn't stick out!
     * @param profiles:
     *          vector of B-splines in u-direction
     *          compatible means: intersection parameters with v-directional B-splines are equal
     * @param guides:
     *          vector of B-splines in v-direction, orthogonal to u-direction
     *          compatible means: intersection parameters with u-directional B-splines are equal
     *                            (if not: reparametrize -> change B-spline knots)
     *                            DON'T need to have common knot vector because skinning method is creating it when
     *                            needed (for surface_v)
     * @param intersectParamsOnProfiles:
     *          Parameters on the profiles of the intersection with the guides (size = nGuides)
     * @param intersectParamsOnGuides:
     *          Parameters on the guides of the intersection with the profiles (size = nProfiles)
     * @param spatialTolerance:
     *          Maximum allowed distance between each guide and profile (in theory they must intersect)
     */
    GordonSurfaceBuilder(const std::vector<Handle(Geom_BSplineCurve)>& profiles,
                              const std::vector<Handle(Geom_BSplineCurve)>& guides,
                              const std::vector<double>& intersectParamsOnProfiles,
                              const std::vector<double>& intersectParamsOnGuides,
                              double spatialTolerance);
    
    /// Returns the interpolation surface
    Handle(Geom_BSplineSurface) SurfaceGordon();

    /// Returns the surface that interpolates the profiles
    Handle(Geom_BSplineSurface) SurfaceProfiles();
    
    /// Returns the surface that interpolates the guides
    Handle(Geom_BSplineSurface) SurfaceGuides();
    
    /// Returns the Surface that interpolations the intersection point of both surfaces
    Handle(Geom_BSplineSurface) SurfaceIntersections();
    
private:
    void Perform();

    void CheckCurveNetworkCompatibility(const std::vector<Handle(Geom_BSplineCurve) >& profiles,
                                        const std::vector<Handle(Geom_BSplineCurve) >& guides,
                                        const std::vector<double>& intersection_params_spline_u,
                                        const std::vector<double>& intersection_params_spline_v,
                                        double tol);

    void CreateGordonSurface(const std::vector<Handle(Geom_BSplineCurve)>& profiles,
                             const std::vector<Handle(Geom_BSplineCurve)>& guides,
                             const std::vector<double>& intersection_params_spline_u,
                             const std::vector<double>& intersection_params_spline_v);

    typedef std::vector<Handle(Geom_BSplineCurve)> CurveArray;
    CurveArray m_profiles;
    CurveArray m_guides;
    const std::vector<double>& m_intersection_params_spline_u, m_intersection_params_spline_v;
    Handle(Geom_BSplineSurface) m_skinningSurfProfiles, m_skinningSurfGuides, m_tensorProdSurf, m_gordonSurf;
    bool m_hasPerformed;
    double m_tol;
};

} // namespace occ_gordon_internal

#endif // GORDONSURFACEBUILDER_H
