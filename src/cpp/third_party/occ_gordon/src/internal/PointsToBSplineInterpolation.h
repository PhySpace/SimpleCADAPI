/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2018 German Aerospace Center (DLR)
*
* Created: 2018-08-06 Martin Siggel <Martin.Siggel@dlr.de>
*/

#ifndef POINTSTOBSPLINEINTERPOLATION_H
#define POINTSTOBSPLINEINTERPOLATION_H

#include <Geom_BSplineCurve.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <math_Matrix.hxx>
#include <vector>

namespace occ_gordon_internal
{

/**
 * @brief Implements the b-spline interpolation algorithm as described by
 * Park (2000): Choosing nodes and knots in closed B-spline curve interpolation to point data
 */
class PointsToBSplineInterpolation
{
public:
    explicit PointsToBSplineInterpolation(const Handle(TColgp_HArray1OfPnt) & points,
                                          unsigned int maxDegree = 3, bool continuousIfClosed = false);

    PointsToBSplineInterpolation(const Handle(TColgp_HArray1OfPnt) & points,
                                 const std::vector<double>& parameters, unsigned int maxDegree = 3,
                                 bool continuousIfClosed = false);

    /// Returns the interpolation curve
    Handle(Geom_BSplineCurve) Curve() const;

    operator Handle(Geom_BSplineCurve)() const;

    /// Returns the parameters of the interpolated points
    const std::vector<double>& Parameters() const;

    /// Returns the degree of the b-spline interpolation
    unsigned int Degree() const;

private:
    /// computes the maximum distance of the given points
    /// TODO: move to bsplinealgorithms::scale
    double maxDistanceOfBoundingBox(const TColgp_Array1OfPnt& points) const;

    bool isClosed() const;

    bool needsShifting() const;

    /// curve coordinates to be fitted by the B-spline
    const Handle(TColgp_HArray1OfPnt) m_pnts;

    std::vector<double> m_params;

    /// degree of the B-spline
    int m_degree;

    /// determines the continuous closing of curve
    bool m_C2Continuous;
};

} // namespace occ_gordon_internal

#endif // POINTSTOBSPLINEINTERPOLATION_H
