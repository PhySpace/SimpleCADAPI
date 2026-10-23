/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2018 German Aerospace Center (DLR)
*
* Created: 2018-05-23 Martin Siggel <Martin.Siggel@dlr.de>
*                with Merlin Pelz   <Merlin.Pelz@dlr.de>
*/

#ifndef INTERPOLATECURVENETWORK_H
#define INTERPOLATECURVENETWORK_H



#include <vector>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>

class math_Matrix;

namespace occ_gordon_internal
{

/**
 * @brief Curve network interpolation with gordon surfaces
 * 
 * The algorithm uses the gordon method, to create the interpolation surface.
 * To do this, it does the following:
 *  - Compute intersection points between profiles and guides
 *  - Sort the profiles and guides
 *  - Reparametrize profiles and curves to make the network compatible (in most cases necessary)
 *  - Compute the gordon surface
 */
class InterpolateCurveNetwork
{
public:
    /**
     * @brief InterpolateCurveNetwork interpolated a curve network of guide curves and profiles curves
     * @param profiles The profiles to be interpolated
     * @param guides   The guides curves to be interpolated
     * @param spatialTolerance Maximum allowed distance between each guide and profile (in theory they must intersect)
     */
    InterpolateCurveNetwork(const std::vector<Handle(Geom_BSplineCurve)>& profiles,
                                             const std::vector<Handle(Geom_BSplineCurve)>& guides,
                                             double spatialTolerance);

    /**
     * @brief InterpolateCurveNetwork interpolated a curve network of guide curves and profiles curves
     * @param profiles The profiles to be interpolated
     * @param guides   The guides curves to be interpolated
     * @param spatialTolerance Maximum allowed distance between each guide and profile (in theory they must intersect)
     */
    InterpolateCurveNetwork(const std::vector<Handle(Geom_Curve)>& profiles,
                                             const std::vector<Handle(Geom_Curve)>& guides,
                                             double spatialTolerance);

    operator Handle(Geom_BSplineSurface) ();
    
    /// Returns the interpolation surface
    Handle(Geom_BSplineSurface) Surface();

    /// Returns the surface that interpolates the profiles
    Handle(Geom_BSplineSurface) SurfaceProfiles();
    
    /// Returns the surface that interpolates the guides
    Handle(Geom_BSplineSurface) SurfaceGuides();
    
    /// Returns the Surface that interpolations the intersection point of both surfaces
    Handle(Geom_BSplineSurface) SurfaceIntersections();

    /// Returns the v parameters of the final surface, that correspond to the profile curve locations
    std::vector<double> ParametersProfiles();

    /// Returns the u parameters of the final surface, that correspond to the guide curve locations
    std::vector<double> ParametersGuides();

private:
    void Perform();


    void ComputeIntersections(math_Matrix& intersection_params_u,
                              math_Matrix& intersection_params_v) const;

    // Sorts the profiles and guides
    void SortCurves(math_Matrix& intersection_params_u, math_Matrix& intersection_params_v);

    void MakeCurvesCompatible();

    void EliminateInaccuraciesNetworkIntersections(const std::vector<Handle(Geom_BSplineCurve)> & sorted_splines_u,
                                                   const std::vector<Handle(Geom_BSplineCurve)> & sorted_splines_v,
                                                   math_Matrix & intersection_params_u,
                                                   math_Matrix & intersection_params_v) const;

    void EnsureC2();

    bool m_hasPerformed;
    double m_spatialTol;
    
    typedef std::vector<Handle(Geom_BSplineCurve)> CurveArray;
    CurveArray m_profiles;
    CurveArray m_guides;
    std::vector<double> m_intersectionParamsU, m_intersectionParamsV;
    Handle(Geom_BSplineSurface) m_skinningSurfProfiles, m_skinningSurfGuides, m_tensorProdSurf, m_gordonSurf;
};

/// Convenience function calling InterpolateCurveNetwork
Handle(Geom_BSplineSurface) curveNetworkToSurface(const std::vector<Handle(Geom_BSplineCurve)>& profiles,
                                                              const std::vector<Handle(Geom_BSplineCurve)>& guides,
                                                              double spatialTol = 3e-4);

/// Convenience function calling InterpolateCurveNetwork
Handle(Geom_BSplineSurface) curveNetworkToSurface(const std::vector<Handle(Geom_Curve)>& profiles,
                                                  const std::vector<Handle(Geom_Curve)>& guides,
                                                  double spatialTol = 3e-4);

} // namespace occ_gordon_internal

#endif // INTERPOLATECURVENETWORK_H
