/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2018 German Aerospace Center (DLR)
*
* Created: 2019-04-24 Martin Siggel <Martin.Siggel@dlr.de>
*/

#ifndef BSPLINEAPPROXINTERP_H
#define BSPLINEAPPROXINTERP_H



#include "ApproxResult.h"

#include <vector>
#include <Geom_BSplineCurve.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <math_Matrix.hxx>
#include <TColStd_Array1OfInteger.hxx>

class gp_Pnt;

namespace occ_gordon_internal {

struct ProjectResult
{
    ProjectResult(double p, double e)
        : parameter(p), error(e)
    {
    }

    double parameter;
    double error;
};

class BSplineApproxInterp
{
public:
    BSplineApproxInterp(const TColgp_Array1OfPnt& points, int nControlPoints, int degree = 3, bool continuous_if_closed = false);

    /// The specified point will be interpolated instead of approximated
    void InterpolatePoint(size_t pointIndex, bool withKink=false);

    /// Returns the resulting curve and the fit error
    ApproxResult FitCurve(const std::vector<double>& initialParms = std::vector<double>()) const;

    /// Fits the curve by optimizing the parameters.
    /// Important: Parameters of points that are interpolated are not optimized
    ApproxResult FitCurveOptimal(const std::vector<double>& initialParms = std::vector<double>(), int maxIter=10) const;

private:
    ProjectResult projectOnCurve(const gp_Pnt& pnt, const Handle(Geom_Curve)& curve, double initial_Parm) const;
    std::vector<double> computeParameters(double alpha) const;
    void computeKnots(int ncp, const std::vector<double>& params, std::vector<double>& knots, std::vector<int>& mults) const;
    
    ApproxResult solve(const std::vector<double>& params, const TColStd_Array1OfReal& knots, const TColStd_Array1OfInteger& mults) const;
    math_Matrix getContinuityMatrix(int nCtrPnts, int contin_cons, const std::vector<double>& params, const TColStd_Array1OfReal& flatKnots) const;

    void optimizeParameters(const Handle(Geom_Curve)& curve, std::vector<double>& parms) const;

    bool isClosed() const;
    bool firstAndLastInterpolated() const;

    /// computes the maximum distance of the given points
    double maxDistanceOfBoundingBox(const TColgp_Array1OfPnt& points) const;
    
    /// curve coordinates to be fitted by the B-spline
    TColgp_Array1OfPnt m_pnts;

    std::vector<size_t> m_indexOfInterpolated;
    std::vector<size_t> m_indexOfApproximated;
    std::vector<size_t> m_indexOfKinks;

    /// degree of the B-spline
    int m_degree;

    /// Number of control points of the B-spline
    int m_ncp;

    /// determines the continuous closing of curve
    bool  m_C2Continuous;
};

} // namespace occ_gordon_internal

#endif // BSPLINEAPPROXINTERP_H
