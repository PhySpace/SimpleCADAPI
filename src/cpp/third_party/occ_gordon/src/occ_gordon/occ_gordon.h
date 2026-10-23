#pragma once

/**
 * SPDX-License-Identifier: Apache-2.0
 * SPDX-FileCopyrightText: 2024 German Aerospace Center (DLR)
 */

#include <occ_gordon/exports.h>

#include <Geom_BSplineSurface.hxx>
#include <Geom_Curve.hxx>
#include <Geom_BSplineCurve.hxx>

#include <vector>

namespace occ_gordon
{

/**
 * @brief Interpolates the curve network by a B-spline surface
 *
 * This uses the Gordon interpolation method.
 * The u curves and v curves must intersect each other within the tolerance.
 *
 * __Note:__ The input curves are reparametrized to fullfill the compatibity criteria of the gordon method,
 *       which might introduce a small error.
 *
 * @throws std::runtime_error in case the surface cannot be built
 *
 * @param ucurves Multiple curves that will be interpolated in u direction by the final shape
 * @param vcurves Multiple curves that will be interpolated in v direction by the final shape,
 *                must intersect the ucurves
 * @param tolerance Tolerance, in which the u- and v-curves need to intersect each other
 */
OCC_GORDON_EXPORT Handle(Geom_BSplineSurface)
    interpolate_curve_network(const std::vector<Handle(Geom_Curve)>& ucurves,
                              const std::vector<Handle(Geom_Curve)>& vcurves,
                              double tolerance);

/**
 * @brief Interpolates the curve network by a B-spline surface
 *
 * This uses the Gordon interpolation method.
 * The u curves and v curves must intersect each other within the tolerance.
 *
 * __Note:__ The input curves are reparametrized to fullfill the compatibity criteria of the gordon method,
 *       which might introduce a small error.
 *
 * @throws std::runtime_error in case the surface cannot be built
 *
 * @param ucurves Multiple B-Spline curves that will be interpolated in u direction by the final shape
 * @param vcurves Multiple B-Spline curves that will be interpolated in v direction by the final shape,
 *                must intersect the ucurves
 * @param tolerance Tolerance, in which the u- and v-curves need to intersect each other
 */
OCC_GORDON_EXPORT Handle(Geom_BSplineSurface)
    interpolate_curve_network(const std::vector<Handle(Geom_BSplineCurve)>& ucurves,
                              const std::vector<Handle(Geom_BSplineCurve)>& vcurves,
                              double tolerance);

} // namespace geoml
