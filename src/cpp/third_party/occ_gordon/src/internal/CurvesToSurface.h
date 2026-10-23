/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2013 German Aerospace Center (DLR)
*
* Created: 2018-07-18 Jan Kleinert <Jan.Kleinert@dlr.de>
*/

#pragma once

#include <vector>

#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_RectangularTrimmedSurface.hxx>

namespace occ_gordon_internal {

class CurvesToSurface
{
public:
    /**
     * @brief Surface skinning algorithm
     *
     * Creates a surface by interpolation of B-spline curves. The direction of the input curves
     * is treated as u direction. The skinning will be performed in v direction. The interpolation
     * parameters will be determined automatically.
     *
     * By default, the curves are skinned continuously. This can be changed by setting the maximum degree
     * of the interpolation in v-direction using ::SetMaxDegree.
     *
     * @param splines_vector Curves to be interpolated.
     * @param continuousIfClosed Make a C2 continuous surface at the start/end junction if the first and last curve are the same
     */
    explicit CurvesToSurface(const std::vector<Handle(Geom_Curve) >& splines_vector,
                                              bool continuousIfClosed = false);

    /**
     * @brief Surface skinning algorithm
     *
     * Creates a surface by interpolation of B-spline curves. The direction of the input curves
     * is treated as u direction. The skinning will be performed in v direction.
     *
     * @param splines_vector Curves to be interpolated.
     * @param parameters Parameters of v-direction at which the resulting surface should interpolate the input curves.
     * @param continuousIfClosed Make a C2 continuous surface at the start/end junction if the first and last curve are the same
     */
    explicit CurvesToSurface(const std::vector<Handle(Geom_Curve) >& splines_vector,
                                              const std::vector<double>& parameters,
                                              bool continuousIfClosed = false);
    /**
     * @brief sets the maximum interpolation degree of the splines in skinning direction
     *
     * @param maxDegree maximum degree of the splines in skinning direction
     */
    void SetMaxDegree(int degree);

    /**
     * @brief returns the parameters at the profile curves
     */
    std::vector<double> GetParameters() const
    {
        return _parameters;
    }

    /**
      * @brief returns the skinned surface
      */
    Handle(Geom_BSplineSurface) Surface() {
        if ( !_hasPerformed ) {
            Perform();
        }
        return _skinnedSurface;
    }

private:
    void CalculateParameters(std::vector<Handle(Geom_BSplineCurve)> const& splines_vector);
    void Perform();
    void Invalidate() { _hasPerformed = false; }

    Handle(Geom_BSplineSurface) _skinnedSurface = nullptr;

    std::vector<Handle(Geom_BSplineCurve) > _inputCurves;
    std::vector<Handle(Geom_BSplineCurve) > _compatibleSplines;
    std::vector<double> _parameters;
    bool _continuousIfClosed = false;
    bool _hasPerformed = false;
    int _maxDegree = 3;
};

}
