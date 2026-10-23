/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2019 German Aerospace Center (DLR)
*
* Created: 2019-09-30 Martin Siggel <Martin.Siggel@dlr.de>
*/

#include "IntersectBSplines.h"
#include "BSplineAlgorithms.h"

#include "internal/Error.h"

#include <math_MultipleVarFunctionWithGradient.hxx>
#include <math_FRPR.hxx>
#include <Standard_Version.hxx>


#include <limits>
#include <list>
#include <algorithm>
#include <cassert>

namespace
{
    template <class ArrayType, typename BinaryPredicate, typename BinaryMerge>
    void ReplaceAdjacentWithMerged(ArrayType& list, BinaryPredicate is_adjacent, BinaryMerge merged)
    {
        for (auto it = std::begin(list); it != std::end(list);) {
            auto nextIt = it;

            if (++nextIt == std::end(list)) {
                return;
            }

            if (is_adjacent(*it, *nextIt)) {
                const auto merged_val = merged(*it, *nextIt);
                it = list.erase(it, ++nextIt);
                it = list.insert(it, merged_val);
            }
            else {
                it = nextIt;
            }
        }
    }


    template <typename T>
    T maxval(const T& v1, const T& v2)
    {
        return v1 > v2 ? v1 : v2;
    }

    template <typename T>
    T sqr(const T& v)
    {
        return v*v;
    }
    
    gp_Pnt minCoords(const gp_Pnt& p1, const gp_Pnt& p2)
    {
        gp_Pnt result = p1;
        result.SetX(p1.X() < p2.X()? p1.X() : p2.X());
        result.SetY(p1.Y() < p2.Y()? p1.Y() : p2.Y());
        result.SetZ(p1.Z() < p2.Z()? p1.Z() : p2.Z());
        return result;
        
    }
    
    gp_Pnt maxCoords(const gp_Pnt& p1, const gp_Pnt& p2)
    {
        gp_Pnt result = p1;
        result.SetX(p1.X() > p2.X()? p1.X() : p2.X());
        result.SetY(p1.Y() > p2.Y()? p1.Y() : p2.Y());
        result.SetZ(p1.Z() > p2.Z()? p1.Z() : p2.Z());
        return result;
        
    }

    class Intervall
    {
    public:
        Intervall(double mmin, double mmax)
            : min(mmin), max(mmax)
        {}
        double min;
        double max;
        
        bool operator==(const Intervall& other) const
        {
            const double EPS = 1e-15;
            return fabs(min - other.min) < EPS && fabs(max - other.max) < EPS;
        }
    };
    
    class BoundingBox
    {
    public:
        BoundingBox(const Handle(Geom_BSplineCurve) curve)
            : range(curve->FirstParameter(), curve->LastParameter())
        {
            low = gp_Pnt(std::numeric_limits<double>::max(), std::numeric_limits<double>::max(), std::numeric_limits<double>::max());
            high = gp_Pnt(-std::numeric_limits<double>::max(), -std::numeric_limits<double>::max(), -std::numeric_limits<double>::max());
            // compute min / max from control points
            for (Standard_Integer i = 1; i <= curve->NbPoles(); ++i) {
                gp_XYZ p = curve->Pole(i).XYZ();
                low = minCoords(low, p);
                high = maxCoords(high, p);
            }
        }
        
        bool Intersects(const BoundingBox& other, double eps) const
        {
            gp_Pnt min = maxCoords(low, other.low);
            gp_Pnt max = minCoords(high, other.high);
            return (min.X() < max.X() + eps) && (min.Y() < max.Y() + eps) && (min.Z() < max.Z() + eps);
        }
        
        BoundingBox& Merge(const BoundingBox& other)
        {
            assert(range.max == other.range.min);
            range.max = other.range.max;
            high = maxCoords(high, other.high);
            low = minCoords(low, other.low);

            return *this;
        }
        
        bool operator==(const BoundingBox& other) const
        {
            return range == other.range;
        }
        
        gp_Pnt low, high;
        Intervall range;
    };

    // Computes the total curvature of the curve
    // A curvature of 1 is equivalent to a straight line
    double curvature(const Handle(Geom_BSplineCurve)& curve)
    {
        double len = curve->Pole(1).Distance(curve->Pole(curve->NbPoles()));
        double total = 0.;
        for (Standard_Integer i = 1; i < curve->NbPoles(); ++i) {
            gp_Pnt p1 = curve->Pole(i);
            gp_Pnt p2 = curve->Pole(i+1);
            double dist = p1.Distance(p2);
            total += dist;
        }
        
        return total / len;
    }
    
    struct BoundingBoxPair
    {
        BoundingBoxPair (const BoundingBox& i1, const BoundingBox& i2)
            : b1(i1), b2(i2)
        {}
        BoundingBox b1;
        BoundingBox b2;
    };

    
    /// Computes possible ranges of intersections by a bracketing approach
    std::list<BoundingBoxPair> getRangesOfIntersection(const Handle(Geom_BSplineCurve) curve1, const Handle(Geom_BSplineCurve) curve2, double tolerance)
    {
        BoundingBox h1(curve1);
        BoundingBox h2(curve2);
        
        if (!h1.Intersects(h2, tolerance)) {
            // Bounding boxes do not intersect. No intersection possible
            return {};
        }
        
        double c1_curvature = curvature(curve1);
        double c2_curvature = curvature(curve2);
        double max_curvature = 1.0005;
        
        // If both curves are linear enough, we can stop refining
        if (c1_curvature <= max_curvature && c2_curvature <= max_curvature) {
            return {BoundingBoxPair(h1, h2)};
        }
        
        double curve1MidParm = 0.5*(curve1->FirstParameter() + curve1->LastParameter());
        double curve2MidParm = 0.5*(curve2->FirstParameter() + curve2->LastParameter());
        
        if (c1_curvature > max_curvature && c2_curvature > max_curvature) {
            // Refine both curves by splitting them in the parametric center
            Handle(Geom_BSplineCurve) c11 = occ_gordon_internal::BSplineAlgorithms::trimCurve(curve1, curve1->FirstParameter(), curve1MidParm);
            Handle(Geom_BSplineCurve) c12 = occ_gordon_internal::BSplineAlgorithms::trimCurve(curve1, curve1MidParm, curve1->LastParameter());

            Handle(Geom_BSplineCurve) c21 = occ_gordon_internal::BSplineAlgorithms::trimCurve(curve2, curve2->FirstParameter(), curve2MidParm);
            Handle(Geom_BSplineCurve) c22 = occ_gordon_internal::BSplineAlgorithms::trimCurve(curve2, curve2MidParm, curve2->LastParameter());
            
            auto result1 = getRangesOfIntersection(c11, c21, tolerance);
            auto result2 = getRangesOfIntersection(c11, c22, tolerance);
            auto result3 = getRangesOfIntersection(c12, c21, tolerance);
            auto result4 = getRangesOfIntersection(c12, c22, tolerance);
            
            // append all results
            result1.splice(std::begin(result1), result2);
            result1.splice(std::begin(result1), result3);
            result1.splice(std::begin(result1), result4);
            
            return result1;
        }
        else if (c1_curvature <= max_curvature && max_curvature < c2_curvature) {
            // Refine only curve 2
            Handle(Geom_BSplineCurve) c21 = occ_gordon_internal::BSplineAlgorithms::trimCurve(curve2, curve2->FirstParameter(), curve2MidParm);
            Handle(Geom_BSplineCurve) c22 = occ_gordon_internal::BSplineAlgorithms::trimCurve(curve2, curve2MidParm, curve2->LastParameter());
            
            auto result1 = getRangesOfIntersection(curve1, c21, tolerance);
            auto result2 = getRangesOfIntersection(curve1, c22, tolerance);
            
            result1.splice(std::begin(result1), result2);
            return result1;
        }
        else if (c2_curvature <= max_curvature && max_curvature < c1_curvature) {
            // Refine only curve 1
            Handle(Geom_BSplineCurve) c11 = occ_gordon_internal::BSplineAlgorithms::trimCurve(curve1, curve1->FirstParameter(), curve1MidParm);
            Handle(Geom_BSplineCurve) c12 = occ_gordon_internal::BSplineAlgorithms::trimCurve(curve1, curve1MidParm, curve1->LastParameter());
            
            auto result1 = getRangesOfIntersection(c11, curve2, tolerance);
            auto result2 = getRangesOfIntersection(c12, curve2, tolerance);
            
            result1.splice(std::begin(result1), result2);
            return result1;
        }
        
        return {};
    }

    class CurveCurveDistanceObjective : public math_MultipleVarFunctionWithGradient
    {
    public:
        CurveCurveDistanceObjective(const Handle(Geom_Curve)& c1, const Handle(Geom_Curve)& c2, double scale)
            : m_c1(c1), m_c2(c2), m_invScaleSqr(1. / sqr(std::max(scale, std::numeric_limits<double>::epsilon())))
        {}

        virtual Standard_Integer NbVariables()  const override
        {
            return 2;
        }

        Standard_Boolean Value (const math_Vector& X, Standard_Real& F) override
        {
            math_Vector G(1, 2);
            return Values(X, F, G);
        }

        Standard_Boolean Gradient (const math_Vector& X, math_Vector& G) override
        {
            Standard_Real F = 0.;
            return Values(X, F, G);
        }

        // Reparametrization function R -> [0,1]
        static double activate(double z)
        {
            return 0.5 * (sin(z) + 1.);
        }

        // Derivative of reparametrization function
        static double d_activate(double z)
        {
            return 0.5 * cos(z);
        }

        double getUParam(double x0) const
        {
            double umin = m_c1->FirstParameter();
            double umax = m_c1->LastParameter();

            return activate(x0)*(umax - umin) + umin;
        }

        double getVParam(double x1) const
        {
            double vmin = m_c2->FirstParameter();
            double vmax = m_c2->LastParameter();

            return activate(x1)*(vmax - vmin) + vmin;
        }

        double d_getUParam(double x0) const
        {
            double umin = m_c1->FirstParameter();
            double umax = m_c1->LastParameter();

            return d_activate(x0)*(umax - umin);
        }

        double d_getVParam(double x1) const
        {
            double vmin = m_c2->FirstParameter();
            double vmax = m_c2->LastParameter();

            return d_activate(x1)*(vmax - vmin);
        }

        virtual  Standard_Boolean Values (const math_Vector& X, Standard_Real& F, math_Vector& G) override
        {

            // We use a reparametrization trick to ensure that u is in [umin, umax] and v in [vmin, vmax]
            double u = getUParam(X.Value(1));
            double v = getVParam(X.Value(2));

            gp_Pnt p1, p2;
            gp_Vec d1, d2;
            m_c1->D1(u, p1, d1);
            m_c2->D1(v, p2, d2);

            gp_Vec diff = p1.XYZ() - p2.XYZ();
            F = diff.SquareMagnitude() * m_invScaleSqr;
            G(1) = 2. * diff.Dot(d1) * d_getUParam(X.Value(1)) * m_invScaleSqr;
            G(2) = -2. * diff.Dot(d2) * d_getVParam(X.Value(2)) * m_invScaleSqr;

            return true;
        }

    private:
        const Handle(Geom_Curve) m_c1, m_c2;
        const double m_invScaleSqr;
    };

    void CheckGradient(math_MultipleVarFunctionWithGradient& func, const math_Vector& X, double step)
    {
        int nvars = func.NbVariables();

        // Analytical gradient and temporary storage
        math_Vector analyticalGrad(1, nvars);
        math_Vector dummy(1, nvars);
        double baseValue = 0.0;

        // Evaluate function and analytical gradient at X
        func.Values(X, baseValue, analyticalGrad);

        // Compute numerical gradient using finite differences
        math_Vector numericalGrad(1, nvars);
        for (int i = 1; i <= nvars; ++i) {
            math_Vector Xplus(X);
            math_Vector Xminus(X);

            Xplus.Value(i) += step;
            Xminus.Value(i) -= step;

            double f_plus = 0.0, f_minus = 0.0;
            func.Values(Xplus, f_plus, dummy);
            func.Values(Xminus, f_minus, dummy);

            // Central difference for better accuracy
            numericalGrad.Value(i) = (f_plus - f_minus) / (2.0 * step);
        }

        // Compare analytical vs. numerical gradients
        std::cout << std::fixed << std::setprecision(8);
        std::cout << "=== Gradient Check ===" << std::endl;

        for (int i = 1; i <= nvars; ++i) {
            double diff = std::abs(numericalGrad.Value(i) - analyticalGrad.Value(i));
            std::cout << "dF/dX" << i << " | Analytical: " << analyticalGrad.Value(i)
                      << "  Numerical: " << numericalGrad.Value(i)
                      << "  | Diff: " << diff << std::endl;
        }

        std::cout << "======================\n" << std::endl;
    }

} // namespace

namespace occ_gordon_internal
{


std::vector<CurveIntersectionResult> IntersectBSplines(const Handle(Geom_BSplineCurve) curve1, const Handle(Geom_BSplineCurve) curve2, double tolerance)
{
    const double optimizerScale = (BSplineAlgorithms::scale(curve1) + BSplineAlgorithms::scale(curve2)) / 2.;
    auto hulls = getRangesOfIntersection(curve1, curve2, tolerance);
    
    std::list<BoundingBox> curve1_ints, curve2_ints;
    for (const auto& hull : hulls) {
        curve1_ints.push_back(hull.b1);
        curve2_ints.push_back(hull.b2);
    }
    
    auto compare = [](const BoundingBox& b1, const BoundingBox& b2) {
        return b1.range.min < b2.range.min;
    };
    
    // sort ascending parameter
    curve1_ints.sort(compare);
    curve2_ints.sort(compare);

    // Remove duplicates
    curve1_ints.unique();
    curve2_ints.unique();
    
    auto is_adjacent = [](const BoundingBox& b1, const BoundingBox& b2) {
        const double EPS = 1e-15;
        return fabs(b1.range.max - b2.range.min) < EPS;
    };
    
    auto merge_boxes = [](const BoundingBox& b1, const BoundingBox& b2) {
        BoundingBox result(b1);
        return result.Merge(b2);
    };
    
    // merge neighboring intervals
    ReplaceAdjacentWithMerged(curve1_ints, is_adjacent, merge_boxes);
    ReplaceAdjacentWithMerged(curve2_ints, is_adjacent, merge_boxes);
    
    // combine intersection intervals
    std::vector<BoundingBoxPair> intersectionCandidates;
    for (const BoundingBox& b1 : curve1_ints) {
        for (const BoundingBox& b2 : curve2_ints) {
            if (b1.Intersects(b2, tolerance)) {
                intersectionCandidates.push_back(BoundingBoxPair(b1, b2));
            }
        }
    }


    std::vector<CurveIntersectionResult> results;

    for (const BoundingBoxPair& boxes : intersectionCandidates) {
        
        auto c1 = BSplineAlgorithms::trimCurve(curve1, boxes.b1.range.min,boxes.b1.range.max);
        auto c2 = BSplineAlgorithms::trimCurve(curve2, boxes.b2.range.min,boxes.b2.range.max);

        CurveCurveDistanceObjective obj(c1, c2, optimizerScale);

        // The objective is designed such that x=[0, 0] is in the middle of the parameter space of both curves
        math_Vector guess(1, 2);
        guess(1) = 0.;
        guess(2) = 0.;

        // Only comment in for debugging purposes
        //CheckGradient(obj, guess, 1e-6);

        math_FRPR optimizer(obj, 1e-10, 200);
        optimizer.Perform(obj, guess);

        if (!optimizer.IsDone()) {
            std::cerr << "Unable to compute exact intersection in `IntersectBSplines` due to failure in minimization. Please file a report";
            continue;
        }

        // convert parameter space of optimized into u/v curve parameters
        double u = obj.getUParam(optimizer.Location().Value(1));
        double v = obj.getVParam(optimizer.Location().Value(2));

        double distance = c1->Value(u).Distance(c2->Value(v));
        if (distance < std::max(1e-10, tolerance)) {
            CurveIntersectionResult result;
            result.parmOnCurve1 = u;
            result.parmOnCurve2 = v;
            result.point = (curve1->Value(u).XYZ() + curve2->Value(v).XYZ())*0.5;
            results.push_back(result);
        }
    }
    
    return results;
}



} // namespace occ_gordon_internal
