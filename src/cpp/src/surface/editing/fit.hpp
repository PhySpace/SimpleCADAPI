// Least-squares B-spline fitting in a GIVEN parametrisation: the samples carry their own parameters, the result
// spans exactly [first, last] with uniform clamped knots and interpolates the first and last sample.  Fitting in the
// shape's own parameters is what lets a rebuilt face keep its trimming loops in (u, v).  Not installed.
#pragma once

#include <vector>

#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <gp_XYZ.hxx>

namespace scad::surface::editing {

struct KnotVector {
  std::vector<double> knots;  // distinct
  std::vector<int> multiplicities;
  std::vector<double> flat;  // every knot repeated by its multiplicity
};

// Clamped, uniform interior knots on [first, last] for `poles` poles of `degree`.
KnotVector uniform_clamped_knots(double first, double last, int poles, int degree);

// The poles of the least-squares fit; parameters increase from the knot vector's first knot to its last.
std::vector<gp_XYZ> fit_poles(const std::vector<double>& parameters, const std::vector<gp_XYZ>& values,
                              const KnotVector& knots, int degree, int poles);

TColStd_Array1OfReal knot_array(const KnotVector& knots);
TColStd_Array1OfInteger multiplicity_array(const KnotVector& knots);

// `count` parameters evenly from `first` to `last`, both included.
std::vector<double> even_parameters(double first, double last, int count);

}  // namespace scad::surface::editing
