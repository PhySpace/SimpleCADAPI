/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2019 German Aerospace Center (DLR)
*
* Created: 2019-09-30 Martin Siggel <Martin.Siggel@dlr.de>
*/

#ifndef INTERSECTBSPLINES_H
#define INTERSECTBSPLINES_H

#include <Geom_BSplineCurve.hxx>
#include <gp_Pnt.hxx>

#include <vector>

namespace occ_gordon_internal
{

struct CurveIntersectionResult
{
    double parmOnCurve1;
    double parmOnCurve2;
    gp_Pnt point;
};

/**
 * @brief Computes all intersections of 2 B-Splines curves
 *
 * An intersection is counted, whenever the two curves come closer than tolerance.
 * If a whole interval is closes than tolerance, the nearest point in the interval is searched.
 *
 * The function divides the input curves and checks, if their bounding boxes (convex hulls)
 * intersect each other. If so, this process is repeated until the curve segment is almost a line segment.
 * This result is used to locally optimize into a true minimum.
 */
std::vector<CurveIntersectionResult> IntersectBSplines(const Handle(Geom_BSplineCurve) curve1,
                                                       const Handle(Geom_BSplineCurve) curve2,
                                                       double absTolerance=1e-5);

} // namespace occ_gordon_internal

#endif // INTERSECTBSPLINES_H
