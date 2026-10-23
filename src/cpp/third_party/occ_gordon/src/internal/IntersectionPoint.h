/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2017 German Aerospace Center (DLR)
*
* Created: 2017-07-27 Jan Kleinert <Jan.Kleinert@dlr.de>
*/

#ifndef INTERSECTIONPOINTS_H
#define INTERSECTIONPOINTS_H

#include <gp_Pnt.hxx>

#include <vector>

//This struct is used by GetIntersectionPoint(const TopoDS_Wire& wire1, const TopoDS_Wire& wire2,[...]) in common/CommonFunctions.h
struct IntersectionPoint {
    double SquareDistance;
    gp_Pnt Center;
};

typedef std::vector<IntersectionPoint> intersectionPointList;

#endif // PNAMEDSHAPE_H
