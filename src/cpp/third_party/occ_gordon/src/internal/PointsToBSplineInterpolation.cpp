/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2018 German Aerospace Center (DLR)
*
* Created: 2018-08-06 Martin Siggel <Martin.Siggel@dlr.de>
*/

#include "PointsToBSplineInterpolation.h"

#include "internal/Error.h"
#include "BSplineAlgorithms.h"

#include <BSplCLib.hxx>
#include <math_Gauss.hxx>
#include <GeomConvert.hxx>
#include <Geom_TrimmedCurve.hxx>

#include <algorithm>
#include <cassert>

namespace
{

Handle(TColStd_HArray1OfReal) toArray(const std::vector<double>& vector)
{
    Handle(TColStd_HArray1OfReal) array = new TColStd_HArray1OfReal(1, static_cast<int>(vector.size()));
    int ipos                            = 1;
    for (std::vector<double>::const_iterator it = vector.begin(); it != vector.end(); ++it, ipos++) {
        array->SetValue(ipos, *it);
    }

    return array;
}

void clamp(Handle(Geom_BSplineCurve) & curve, double min, double max)
{

    Handle(Geom_Curve) c = new Geom_TrimmedCurve(curve, min, max);
    curve                = GeomConvert::CurveToBSplineCurve(c);
}

} // namespace

namespace occ_gordon_internal
{

PointsToBSplineInterpolation::PointsToBSplineInterpolation(const Handle(TColgp_HArray1OfPnt) & points,
                                                                     unsigned int maxDegree, bool continuousIfClosed)
    : m_pnts(points)
    , m_degree(static_cast<int>(maxDegree))
    , m_C2Continuous(continuousIfClosed)
{
    m_params = BSplineAlgorithms::computeParamsBSplineCurve(points);

    if (maxDegree < 1) {
        throw error("Degree must be larger than 1 in PointsToBSplineInterpolation!");
    }

    if (points.IsNull()) {
        throw error("No points given in PointsToBSplineInterpolation", NULL_POINTER);
    }

    if (points->Length() < 2) {
        throw error("Too few points in PointsToBSplineInterpolation", MATH_ERROR);
    }
}

PointsToBSplineInterpolation::PointsToBSplineInterpolation(const Handle(TColgp_HArray1OfPnt) & points,
                                                                     const std::vector<double>& parameters,
                                                                     unsigned int maxDegree, bool continuousIfClosed)
    : m_pnts(points)
    , m_params(parameters)
    , m_degree(static_cast<int>(maxDegree))
    , m_C2Continuous(continuousIfClosed)
{
    if (static_cast<int>(m_params.size()) != m_pnts->Length()) {
        throw error("Number of parameters and points don't match in PointsToBSplineInterpolation");
    }

    if (maxDegree < 1) {
        throw error("Degree must be larger than 1 in PointsToBSplineInterpolation!");
    }

    if (points.IsNull()) {
        throw error("No points given in PointsToBSplineInterpolation", NULL_POINTER);
    }

    if (points->Length() < 2) {
        throw error("Too few points in PointsToBSplineInterpolation", MATH_ERROR);
    }
}

Handle(Geom_BSplineCurve) PointsToBSplineInterpolation::Curve() const
{
    int degree = static_cast<int>(Degree());

    std::vector<double> params = m_params;

    std::vector<double> knots =
        BSplineAlgorithms::knotsFromCurveParameters(params, static_cast<unsigned int>(degree), isClosed());

    if (isClosed()) {
        // we remove the last parameter, since it is implicitly
        // included by wrapping the control points
        params.pop_back();
    }

    math_Matrix bsplMat =
        BSplineAlgorithms::bsplineBasisMat(degree, toArray(knots)->Array1(), toArray(params)->Array1());

    // build left hand side of the linear system
    int nParams = static_cast<int>(params.size());
    math_Matrix lhs(1, nParams, 1, nParams, 0.);
    for (int iCol = 1; iCol <= nParams; ++iCol) {
        lhs.SetCol(iCol, bsplMat.Col(iCol));
    }
    if (isClosed()) {
        // sets the continuity constraints for closed curves on the left hand side if requested
        // by wrapping around the control points

        // This is a trick to make the matrix square and enforce the endpoint conditions
        for (int iCol = 1; iCol <= degree; ++iCol) {
            lhs.SetCol(iCol, lhs.Col(iCol) + bsplMat.Col(nParams + iCol));
        }
    }

    // right hand side
    math_Vector rhsx(1, nParams, 0.);
    math_Vector rhsy(1, nParams, 0.);
    math_Vector rhsz(1, nParams, 0.);
    for (int i = 1; i <= nParams; ++i) {
        const gp_Pnt& p = m_pnts->Value(i);
        rhsx(i)         = p.X();
        rhsy(i)         = p.Y();
        rhsz(i)         = p.Z();
    }

    math_Gauss solver(lhs);

    math_Vector cp_x(1, nParams);
    math_Vector cp_y(1, nParams);
    math_Vector cp_z(1, nParams);

    solver.Solve(rhsx, cp_x);
    if (!solver.IsDone()) {
        throw error("Singular Matrix", MATH_ERROR);
    }

    solver.Solve(rhsy, cp_y);
    if (!solver.IsDone()) {
        throw error("Singular Matrix", MATH_ERROR);
    }

    solver.Solve(rhsz, cp_z);
    if (!solver.IsDone()) {
        throw error("Singular Matrix", MATH_ERROR);
    }

    int nCtrPnts = static_cast<int>(m_params.size());
    if (isClosed()) {
        nCtrPnts += degree - 1;
    }
    if (needsShifting()) {
        nCtrPnts += 1;
    }
    TColgp_Array1OfPnt poles(1, nCtrPnts);
    for (Standard_Integer icp = 1; icp <= nParams; ++icp) {
        gp_Pnt pnt(cp_x.Value(icp), cp_y.Value(icp), cp_z.Value(icp));
        poles.SetValue(icp, pnt);
    }

    if (isClosed()) {
        // wrap control points
        for (Standard_Integer icp = 1; icp <= degree; ++icp) {
            gp_Pnt pnt(cp_x.Value(icp), cp_y.Value(icp), cp_z.Value(icp));
            poles.SetValue(nParams + icp, pnt);
        }
    }
    if (needsShifting()) {
        // add a new control point and knot
        size_t deg = static_cast<size_t>(degree);
        knots.push_back(knots.back() + knots[2 * deg + 1] - knots[2 * deg]);
        poles.SetValue(nParams + degree + 1, poles.Value(degree + 1));

        // shift back the knots
        for (size_t iknot = 0; iknot < knots.size(); ++iknot) {
            knots[iknot] -= params[0];
        }
    }

    Handle(TColStd_HArray1OfReal) occFlatKnots = toArray(knots);
    int knotsLen                               = BSplCLib::KnotsLength(occFlatKnots->Array1());

    TColStd_Array1OfReal occKnots(1, knotsLen);
    TColStd_Array1OfInteger occMults(1, knotsLen);
    BSplCLib::Knots(occFlatKnots->Array1(), occKnots, occMults);

    Handle(Geom_BSplineCurve) result = new Geom_BSplineCurve(poles, occKnots, occMults, degree, false);

    // clamp bspline
    if (isClosed()) {
        clamp(result, m_params.front(), m_params.back());
    }

    return result;
}

double PointsToBSplineInterpolation::maxDistanceOfBoundingBox(const TColgp_Array1OfPnt& points) const
{
    double maxDistance = 0.;
    for (int i = points.Lower(); i <= points.Upper(); ++i) {
        for (int j = points.Lower(); j <= points.Upper(); ++j) {
            double dist = points.Value(i).Distance(points.Value(j));
            maxDistance = std::max(maxDistance, dist);
        }
    }
    return maxDistance;
}

bool PointsToBSplineInterpolation::isClosed() const
{
    double maxDistance = maxDistanceOfBoundingBox(m_pnts->Array1());
    double error       = 1e-6 * maxDistance;
    return m_pnts->Value(m_pnts->Lower()).IsEqual(m_pnts->Value(m_pnts->Upper()), error) && m_C2Continuous;
}

bool PointsToBSplineInterpolation::needsShifting() const
{
    return (Degree() % 2) == 0 && isClosed();
}

PointsToBSplineInterpolation::operator Handle(Geom_BSplineCurve)() const
{
    return Curve();
}

const std::vector<double>& PointsToBSplineInterpolation::Parameters() const
{
    return m_params;
}

unsigned int PointsToBSplineInterpolation::Degree() const
{
    int maxDegree = m_pnts->Length() - 1;
    if (isClosed()) {
        maxDegree -= 1;
    }
    int degree = std::min(maxDegree, m_degree);
    assert(degree > 0);
    return static_cast<unsigned int>(degree);
}

} // namespace occ_gordon_internal
