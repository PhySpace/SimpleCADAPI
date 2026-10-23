/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2018 German Aerospace Center (DLR)
*
* Created: 2018-05-23 Martin Siggel <Martin.Siggel@dlr.de>
*                with Merlin Pelz   <Merlin.Pelz@dlr.de>
*/

#include "InterpolateCurveNetwork.h"

#include "internal/Error.h"

#include "BSplineAlgorithms.h"
#include "CurveNetworkSorter.h"
#include "GordonSurfaceBuilder.h"

#include <math_Matrix.hxx>
#include <TColStd_HArray1OfReal.hxx>
#include <GeomConvert.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Precision.hxx>

#include <algorithm>
#include <cassert>
#include <cmath>
#include <sstream>
#include <iostream>
#include <iomanip>


namespace occ_gordon_internal
{

// scad patch P2 (ported from ocp_gordon, which the reference SDK runs): a polynomial
// curve whose intersection parameters already equal the target parameters needs no
// refit.  Without it every straight edge of a network is re-approximated, so shared
// boundary edges of neighbouring patches no longer coincide exactly.
inline bool SkipReparametrize(const Handle(Geom_BSplineCurve)& curve,
                              const std::vector<double>& oldParameters,
                              const std::vector<double>& newParameters)
{
    if (curve->IsRational() || curve->IsPeriodic()) {
        return false;
    }
    for (size_t i = 0; i < oldParameters.size(); ++i) {
        if (std::abs(oldParameters[i] - newParameters[i]) >= Precision::PConfusion()) {
            return false;
        }
    }
    return true;
}

template <class T>
T Clamp(T val, T min, T max)
{
    if (min > max) {
        throw error("Minimum may not be larger than maximum in clamp!");
    }

    return std::max(min, std::min(val, max));
}

InterpolateCurveNetwork::InterpolateCurveNetwork(const std::vector<Handle(Geom_Curve)>& profiles,
                                                 const std::vector<Handle(Geom_Curve)>& guides,
                                                 double spatialTol)
    : InterpolateCurveNetwork(BSplineAlgorithms::toBSplines(profiles),
                              BSplineAlgorithms::toBSplines(guides), spatialTol)
{
}

InterpolateCurveNetwork::InterpolateCurveNetwork(const std::vector<Handle(Geom_BSplineCurve)>& profiles,
                                                            const std::vector<Handle(Geom_BSplineCurve)>& guides,
                                                            double spatialTol)
    : m_hasPerformed(false)
    , m_spatialTol(spatialTol)
{
    // check whether there are any u-directional and v-directional B-splines in the vectors
    if (profiles.size() < 2) {
        throw error("There must be at least two profiles for the curve network interpolation.", MATH_ERROR);
    }

    if (guides.size() < 2) {
        throw error("There must be at least two guides for the curve network interpolation.", MATH_ERROR);
    }

    // remove duplicates from profiles and guides
    // we need it to build correct intersection matrix
    // Here we checking only first point of the curve to find duplicates
    // it should be enough, since surface closed in both U and V not supported by algorithm
    // if profiles or guides are closed curves, we will add the first curve at the end later
    // after sorting the intersection matrix
    std::vector<Handle(Geom_BSplineCurve)> uniqueProfiles;
    for (const auto& profile : profiles) {
        const bool isUnique = std::none_of(uniqueProfiles.begin(), uniqueProfiles.end(), [&](const Handle(Geom_BSplineCurve) & curve) {
            return profile->IsEqual(curve, Precision::PConfusion());  // scad patch P3: was Confusion
        });

        if (isUnique) {
            uniqueProfiles.push_back(profile);
        }
    }

    std::vector<Handle(Geom_BSplineCurve)> uniqueGuides;
    for (const auto& guide : guides) {
        const bool isUnique = std::none_of(uniqueGuides.begin(), uniqueGuides.end(), [&](const Handle(Geom_BSplineCurve) & curve) {
            return guide->IsEqual(curve, Precision::PConfusion());  // scad patch P3: was Confusion
        });

        if (isUnique) {
            uniqueGuides.push_back(guide);
        }
    }

    // check whether there are any u-directional and v-directional B-splines in the vectors
    if (uniqueProfiles.size() < 2) {
        throw error(
            "There must be at least two unique profiles for the curve network interpolation.",
            MATH_ERROR);
    }

    if (uniqueGuides.size() < 2) {
        throw error("There must be at least two unique guides for the curve network interpolation.",
            MATH_ERROR);
    }

    m_profiles.reserve(uniqueProfiles.size());
    m_guides.reserve(uniqueGuides.size());

    // Store the curves
    for (auto&& profile : uniqueProfiles) {
        m_profiles.push_back(profile);
    }
    for (auto&& guide : uniqueGuides) {
        m_guides.push_back(guide);
    }
}


void InterpolateCurveNetwork::ComputeIntersections(math_Matrix& intersection_params_u,
    math_Matrix& intersection_params_v) const
{
    const std::vector<Handle(Geom_BSplineCurve)>& profiles = m_profiles;
    const std::vector<Handle(Geom_BSplineCurve)>& guides = m_guides;

    for (int spline_u_idx = 0; spline_u_idx < static_cast<int>(profiles.size()); ++spline_u_idx) {
        for (int spline_v_idx = 0; spline_v_idx < static_cast<int>(guides.size()); ++spline_v_idx) {
            std::vector<std::pair<double, double> > currentIntersections = BSplineAlgorithms::intersections(profiles[static_cast<size_t>(spline_u_idx)],
                guides[static_cast<size_t>(spline_v_idx)],
                m_spatialTol);
            if (currentIntersections.size() < 1) {
                throw error("U-directional B-spline and V-directional B-spline don't intersect "
                    "each other!");
            }

            else if (currentIntersections.size() == 1) {
                intersection_params_u(spline_u_idx, spline_v_idx) = currentIntersections[0].first;
                intersection_params_v(spline_u_idx, spline_v_idx) = currentIntersections[0].second;
            }
            else if (currentIntersections.size() == 2) {
                // for closed curves we will get 2 intersections
                // take the smaller one - we will add duplicate curve at the end
                // later, after sorting the intersection matrix
                intersection_params_u(spline_u_idx, spline_v_idx) =
                    std::min(currentIntersections[0].first, currentIntersections[1].first);
                intersection_params_v(spline_u_idx, spline_v_idx) =
                    std::min(currentIntersections[0].second, currentIntersections[1].second);
            }

            else if (currentIntersections.size() > 2) {
                throw error("U-directional B-spline and V-directional B-spline have more than two intersections with each other! "
                    "Closed in bot U and V directions surface isn't supported at this time");
            }
        }
    }
}

void InterpolateCurveNetwork::SortCurves(math_Matrix& intersection_params_u, math_Matrix& intersection_params_v)
{
    CurveNetworkSorter sorterObj(std::vector<Handle(Geom_Curve)>(m_profiles.begin(), m_profiles.end()),
                                      std::vector<Handle(Geom_Curve)>(m_guides.begin(), m_guides.end()),
                                      intersection_params_u,
                                      intersection_params_v);
    sorterObj.Perform();

    // get the sorted matrices and vectors
    intersection_params_u = sorterObj.ProfileIntersectionParms();
    intersection_params_v = sorterObj.GuideIntersectionParms();

    // copy sorted curves back into our curve arrays
    struct Caster {
        Handle(Geom_BSplineCurve) operator()(const Handle(Geom_Curve)& curve) {
            return Handle(Geom_BSplineCurve)::DownCast(curve);
        }
    } caster;

    std::transform(sorterObj.Profiles().begin(), sorterObj.Profiles().end(), m_profiles.begin(), caster);
    std::transform(sorterObj.Guides().begin(), sorterObj.Guides().end(), m_guides.begin(), caster);
}

void InterpolateCurveNetwork::MakeCurvesCompatible()
{

    // reparametrize into [0,1]
    for (CurveArray::iterator it = m_profiles.begin(); it != m_profiles.end(); ++it) {
        BSplineAlgorithms::reparametrizeBSpline(*(*it), 0., 1., 1e-15);
    }

    for (CurveArray::iterator it = m_guides.begin(); it != m_guides.end(); ++it) {
        BSplineAlgorithms::reparametrizeBSpline(*(*it), 0., 1., 1e-15);
    }
    // now the parameter range of all  profiles and guides is [0, 1]

    int nGuides = static_cast<int>(m_guides.size());
    int nProfiles = static_cast<int>(m_profiles.size());
    // now find all intersections of all B-splines with each other
    math_Matrix tmp_intersection_params_u(0, nProfiles - 1, 0, nGuides - 1);
    math_Matrix tmp_intersection_params_v(0, nProfiles - 1, 0, nGuides - 1);

    // closed profiles/guides should not be handled by this method ideally
    // it will only work if first profile/guide intersects with guide/profile at it's lowest parameter
    // We cover case when curves alredy somewhat sorted and for closed profiles we already have 1 additional guide
    ComputeIntersections(tmp_intersection_params_u, tmp_intersection_params_v);

    // sort intersection_params_u and intersection_params_v and u-directional and v-directional B-spline curves
    SortCurves(tmp_intersection_params_u, tmp_intersection_params_v);

    // Need to check if profiles are closed curves
    // and if so - duplicate 1st guide at the end of guides array and fix intersection matrix
    // we know that parametrization for all profiles are the same, it's safe to check only first one
    // at this point that there are no duplicates and minimum parameter was used for intersection
    auto isClosedProfile = m_profiles.front()->IsClosed() || m_profiles.front()->IsPeriodic();
    auto isClosedGuides = m_guides.front()->IsClosed() || m_guides.front()->IsPeriodic();

    math_Matrix intersection_params_u(0, isClosedGuides ? nProfiles : nProfiles - 1, 
        0, isClosedProfile ? nGuides : nGuides - 1);
    math_Matrix intersection_params_v(0, isClosedGuides ? nProfiles : nProfiles - 1,
        0, isClosedProfile ? nGuides : nGuides - 1);

    if (isClosedProfile) {
        m_guides.push_back(m_guides.front());
        ++nGuides;

        // profiles
        for (int spline_u_idx = 0; spline_u_idx < nProfiles; ++spline_u_idx) {
            // guides
            for (int spline_v_idx = 0; spline_v_idx < nGuides - 1; ++spline_v_idx) {
                intersection_params_u(spline_u_idx, spline_v_idx) =
                    tmp_intersection_params_u(spline_u_idx, spline_v_idx);
                intersection_params_v(spline_u_idx, spline_v_idx) =
                    tmp_intersection_params_v(spline_u_idx, spline_v_idx);
            }
            intersection_params_u(spline_u_idx, nGuides - 1) =
				tmp_intersection_params_u(spline_u_idx, 0) < BSplineAlgorithms::PAR_CHECK_TOL // actually 1e-5
                ? 1.0
                : tmp_intersection_params_u(spline_u_idx, 0);

            intersection_params_v(spline_u_idx, nGuides - 1) =
                tmp_intersection_params_v(spline_u_idx, 0);
        }
    }
    else if (isClosedGuides) {
        m_profiles.push_back(m_profiles.front());
        ++nProfiles;

        for (int spline_v_idx = 0; spline_v_idx < nGuides; ++spline_v_idx) {
            for (int spline_u_idx = 0; spline_u_idx < nProfiles - 1; ++spline_u_idx) {
                intersection_params_u(spline_u_idx, spline_v_idx) =
                    tmp_intersection_params_u(spline_u_idx, spline_v_idx);
                intersection_params_v(spline_u_idx, spline_v_idx) =
                    tmp_intersection_params_v(spline_u_idx, spline_v_idx);
            }
            intersection_params_u(nProfiles - 1, spline_v_idx) =
                tmp_intersection_params_u(0, spline_v_idx);
            intersection_params_v(nProfiles - 1, spline_v_idx) =
                tmp_intersection_params_v(0, spline_v_idx) < BSplineAlgorithms::PAR_CHECK_TOL // actually 1e-5
                ? 1.0
                : tmp_intersection_params_v(0, spline_v_idx);
        }
    }
    else
    {
        intersection_params_u = tmp_intersection_params_u;
        intersection_params_v = tmp_intersection_params_v;
    }

    // eliminate small inaccuracies of the intersection parameters:
    EliminateInaccuraciesNetworkIntersections(m_profiles, m_guides, intersection_params_u, intersection_params_v);

    std::vector<double> newParametersProfiles;
    for (int spline_v_idx = 1; spline_v_idx <= nGuides; ++spline_v_idx) {
        double sum = 0;
        for (int spline_u_idx = 1; spline_u_idx <= nProfiles; ++spline_u_idx) {
            sum += intersection_params_u(spline_u_idx - 1, spline_v_idx - 1);
        }
        newParametersProfiles.push_back(sum / nProfiles);
    }

    std::vector<double> newParametersGuides;
    for (int spline_u_idx = 1; spline_u_idx <= nProfiles; ++spline_u_idx) {
        double sum = 0;
        for (int spline_v_idx = 1; spline_v_idx <= nGuides; ++spline_v_idx) {
            sum += intersection_params_v(spline_u_idx - 1, spline_v_idx - 1);
        }
        newParametersGuides.push_back(sum / nGuides);
    }

    if (newParametersProfiles.front() > BSplineAlgorithms::PAR_CHECK_TOL || newParametersGuides.front() > BSplineAlgorithms::PAR_CHECK_TOL) {
        throw error("At least one B-splines has no intersection at the beginning.");
    }

    // Get maximum number of control points to figure out detail of spline
    size_t max_cp_u = 0, max_cp_v = 0;
    for(CurveArray::const_iterator it = m_profiles.begin(); it != m_profiles.end(); ++it) {
        max_cp_u = std::max(max_cp_u, static_cast<size_t>((*it)->NbPoles()));
    }
    for(CurveArray::const_iterator it = m_guides.begin(); it != m_guides.end(); ++it) {
        max_cp_v = std::max(max_cp_v, static_cast<size_t>((*it)->NbPoles()));
    }

    // we want to use at least 10 and max 80 control points to be able to reparametrize the geometry properly
    size_t mincp = 10;
    size_t maxcp = 120;  // scad patch P3: was 80

    // since we interpolate the intersections, we cannot use fewer control points than curves
    // We need to add two since we want c2 continuity, which adds two equations
    size_t min_u = std::max(m_guides.size() + 2, mincp);
    size_t min_v = std::max(m_profiles.size() + 2, mincp);

    size_t max_u = std::max(min_u, maxcp);
    size_t max_v = std::max(min_v, maxcp);

    max_cp_u = Clamp(max_cp_u + 10, min_u, max_u);
    max_cp_v = Clamp(max_cp_v + 10, min_v, max_v);

    // reparametrize u-directional B-splines
    for (int spline_u_idx = 0; spline_u_idx < nProfiles; ++spline_u_idx) {

        std::vector<double> oldParametersProfile;
        for (int spline_v_idx = 0; spline_v_idx < nGuides; ++spline_v_idx) {
            oldParametersProfile.push_back(intersection_params_u(spline_u_idx, spline_v_idx));
        }

        if (SkipReparametrize(m_profiles[static_cast<size_t>(spline_u_idx)], oldParametersProfile, newParametersProfiles)) {
            continue;
        }

        // eliminate small inaccuracies at the first knot
        if (std::abs(oldParametersProfile.front()) < BSplineAlgorithms::PAR_CHECK_TOL) {
            oldParametersProfile.front() = 0;
        }

        if (std::abs(newParametersProfiles.front()) < BSplineAlgorithms::PAR_CHECK_TOL) {
            newParametersProfiles.front() = 0;
        }

        // eliminate small inaccuracies at the last knot
        if (std::abs(oldParametersProfile.back() - 1) < BSplineAlgorithms::PAR_CHECK_TOL) {
            oldParametersProfile.back() = 1;
        }

        if (std::abs(newParametersProfiles.back() - 1) < BSplineAlgorithms::PAR_CHECK_TOL) {
            newParametersProfiles.back() = 1;
        }

        Handle(Geom_BSplineCurve)& profile = m_profiles[static_cast<size_t>(spline_u_idx)];
        try {
            profile = BSplineAlgorithms::reparametrizeBSplineContinuouslyApprox(profile, oldParametersProfile, newParametersProfiles, max_cp_u).curve;
        }
        catch (const Standard_Failure& err) {
            std::ostringstream oss;
            const Standard_CString msg = err.GetMessageString();
            oss << "Profile reparametrization failed at profile index " << spline_u_idx
                << " (OCCT Standard_Failure): " << (msg ? msg : "<empty>");
            throw error(oss.str());
        }
        catch (const std::exception& err) {
            std::ostringstream oss;
            oss << "Profile reparametrization failed at profile index " << spline_u_idx
                << ": " << err.what();
            throw error(oss.str());
        }
        catch (...) {
            std::ostringstream oss;
            oss << "Profile reparametrization failed at profile index " << spline_u_idx
                << ": unknown non-standard exception";
            throw error(oss.str());
        }
    }

    // reparametrize v-directional B-splines
    for (int spline_v_idx = 0; spline_v_idx < nGuides; ++spline_v_idx) {

        std::vector<double> oldParameterGuide;
        for (int spline_u_idx = 0; spline_u_idx < nProfiles; ++spline_u_idx) {
            oldParameterGuide.push_back(intersection_params_v(spline_u_idx, spline_v_idx));
        }

        if (SkipReparametrize(m_guides[static_cast<size_t>(spline_v_idx)], oldParameterGuide, newParametersGuides)) {
            continue;
        }

        // eliminate small inaccuracies at the first knot
        if (std::abs(oldParameterGuide.front()) < BSplineAlgorithms::PAR_CHECK_TOL) {
            oldParameterGuide.front() = 0;
        }

        if (std::abs(newParametersGuides.front()) < BSplineAlgorithms::PAR_CHECK_TOL) {
            newParametersGuides.front() = 0;
        }

        // eliminate small inaccuracies at the last knot
        if (std::abs(oldParameterGuide.back() - 1) < BSplineAlgorithms::PAR_CHECK_TOL) {
            oldParameterGuide.back() = 1;
        }

        if (std::abs(newParametersGuides.back() - 1) < BSplineAlgorithms::PAR_CHECK_TOL) {
            newParametersGuides.back() = 1;
        }

        Handle(Geom_BSplineCurve)& guide = m_guides[static_cast<size_t>(spline_v_idx)];
        try {
            guide = BSplineAlgorithms::reparametrizeBSplineContinuouslyApprox(guide, oldParameterGuide, newParametersGuides, max_cp_v).curve;
        }
        catch (const Standard_Failure& err) {
            std::ostringstream oss;
            const Standard_CString msg = err.GetMessageString();
            oss << "Guide reparametrization failed at guide index " << spline_v_idx
                << " (OCCT Standard_Failure): " << (msg ? msg : "<empty>");
            throw error(oss.str());
        }
        catch (const std::exception& err) {
            std::ostringstream oss;
            oss << "Guide reparametrization failed at guide index " << spline_v_idx
                << ": " << err.what();
            throw error(oss.str());
        }
        catch (...) {
            std::ostringstream oss;
            oss << "Guide reparametrization failed at guide index " << spline_v_idx
                << ": unknown non-standard exception";
            throw error(oss.str());
        }
    }


    m_intersectionParamsU = newParametersProfiles;
    m_intersectionParamsV = newParametersGuides;
}

void InterpolateCurveNetwork::EliminateInaccuraciesNetworkIntersections(const std::vector<Handle(Geom_BSplineCurve)> & sortedProfiles,
                                                                             const std::vector<Handle(Geom_BSplineCurve)> & sortedGuides,
                                                                             math_Matrix & intersection_params_u,
                                                                             math_Matrix & intersection_params_v) const
{
    Standard_Integer nProfiles = static_cast<Standard_Integer>(sortedProfiles.size());
    Standard_Integer nGuides = static_cast<Standard_Integer>(sortedGuides.size());
    // eliminate small inaccuracies of the intersection parameters:

    // first intersection
    for (Standard_Integer spline_u_idx = 0; spline_u_idx < nProfiles; ++spline_u_idx) {
        if (std::abs(intersection_params_u(spline_u_idx, 0) - sortedProfiles[0]->Knot(1)) < 0.001) {
            if (std::abs(sortedProfiles[0]->Knot(1)) < 1e-10) {
                intersection_params_u(spline_u_idx, 0) = 0;
            }
            else {
                intersection_params_u(spline_u_idx, 0) = sortedProfiles[0]->Knot(1);
            }
        }
    }

    for (Standard_Integer spline_v_idx = 0; spline_v_idx < nGuides; ++spline_v_idx) {
        if (std::abs(intersection_params_v(0, spline_v_idx) - sortedGuides[0]->Knot(1)) < 0.001) {
            if (std::abs(sortedGuides[0]->Knot(1)) < 1e-10) {
                intersection_params_v(0, spline_v_idx) = 0;
            }
            else {
                intersection_params_v(0, spline_v_idx) = sortedGuides[0]->Knot(1);
            }
        }
    }

    // last intersection
    for (Standard_Integer spline_u_idx = 0; spline_u_idx < nProfiles; ++spline_u_idx) {
        if (std::abs(intersection_params_u(spline_u_idx, nGuides - 1) - sortedProfiles[0]->Knot(sortedProfiles[0]->NbKnots())) < 0.001) {
            intersection_params_u(spline_u_idx, nGuides - 1) = sortedProfiles[0]->Knot(sortedProfiles[0]->NbKnots());
        }
    }

    for (Standard_Integer spline_v_idx = 0; spline_v_idx < nGuides; ++spline_v_idx) {
        if (std::abs(intersection_params_v(nProfiles - 1, spline_v_idx) - sortedGuides[0]->Knot(sortedGuides[0]->NbKnots())) < 0.001) {
            intersection_params_v(nProfiles - 1, spline_v_idx) = sortedGuides[0]->Knot(sortedGuides[0]->NbKnots());
        }
    }
}

void occ_gordon_internal::InterpolateCurveNetwork::EnsureC2()
{
    assert(m_gordonSurf);

    // By construction, the 3 surfaces could have different degrees
    // resulting in a higher knot multiplicity. This then results
    // in OCCT reporting lower continuity.
    // To fix it, we try to remove those knots using a small tolerance
    // If successful, this surface should remain unchainged within the
    // tolerance. We want at least C2.
    int minUMult = std::max(1, m_gordonSurf->UDegree() - 2);
    for (int iu = 2; iu <= m_gordonSurf->NbUKnots()-1; ++iu)
    {
        if (m_gordonSurf->UMultiplicity(iu) > minUMult)
        {
            m_gordonSurf->RemoveUKnot(iu, minUMult, m_spatialTol);
        }
    }

    int minVMult = std::max(1, m_gordonSurf->VDegree() - 2);
    for (int iv = 2; iv <= m_gordonSurf->NbVKnots()-1; ++iv)
    {
        if (m_gordonSurf->VMultiplicity(iv) > minVMult)
        {
            m_gordonSurf->RemoveVKnot(iv, minVMult, m_spatialTol);
        }
    }
}


Handle(Geom_BSplineSurface) InterpolateCurveNetwork::Surface()
{
    Perform();

    return m_gordonSurf;
}

InterpolateCurveNetwork::operator Handle(Geom_BSplineSurface) ()
{
    return Surface();
}

Handle(Geom_BSplineSurface) InterpolateCurveNetwork::SurfaceProfiles()
{
    Perform();

    return m_skinningSurfProfiles;
}

Handle(Geom_BSplineSurface) InterpolateCurveNetwork::SurfaceGuides()
{
    Perform();

    return m_skinningSurfGuides;
}

Handle(Geom_BSplineSurface) InterpolateCurveNetwork::SurfaceIntersections()
{
    Perform();

    return m_tensorProdSurf;
}

std::vector<double> InterpolateCurveNetwork::ParametersProfiles()
{
    Perform();

    return m_intersectionParamsV;
}

std::vector<double> InterpolateCurveNetwork::ParametersGuides()
{
    Perform();

    return m_intersectionParamsU;
}

void InterpolateCurveNetwork::Perform()
{
    if (m_hasPerformed) {
        return;
    }

    // Gordon surfaces are only defined on a compatible curve network
    // We first have to reparametrize the network
    MakeCurvesCompatible();
    
    GordonSurfaceBuilder builder(m_profiles, m_guides, m_intersectionParamsU, m_intersectionParamsV, m_spatialTol);
    m_gordonSurf = builder.SurfaceGordon();
    m_skinningSurfProfiles = builder.SurfaceProfiles();
    m_skinningSurfGuides = builder.SurfaceGuides();
    m_tensorProdSurf = builder.SurfaceIntersections();

    EnsureC2();

    m_hasPerformed = true;
}

Handle(Geom_BSplineSurface) curveNetworkToSurface(const std::vector<Handle (Geom_BSplineCurve)> &profiles, const std::vector<Handle (Geom_BSplineCurve)> &guides, double tol)
{
    return InterpolateCurveNetwork(profiles, guides, tol).Surface();
}

Handle(Geom_BSplineSurface) curveNetworkToSurface(const std::vector<Handle(Geom_Curve)>& profiles, const std::vector<Handle(Geom_Curve)>& guides, double tol)
{
    return InterpolateCurveNetwork(profiles, guides, tol).Surface();
}

} // namespace occ_gordon_internal
