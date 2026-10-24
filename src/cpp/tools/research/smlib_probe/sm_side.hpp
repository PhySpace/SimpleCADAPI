#pragma once
#include <vector>
// Plain data crossing the SMLib/OCCT boundary: no headers from either library.
struct NurbsSurfaceData {
  int udeg = 0, vdeg = 0, nu = 0, nv = 0;
  std::vector<double> poles;      // nu*nv*3, row-major (u-major)
  std::vector<double> weights;    // empty when non-rational
  std::vector<double> uknots, vknots;
  std::vector<int> umults, vmults;
  bool ok = false;
  long status = 0;
};
// Interpolate an nrows x ncols grid of points (xyz triples).
NurbsSurfaceData sm_interpolate_grid(const std::vector<double>& xyz, int nrows, int ncols);

NurbsSurfaceData sm_fit_scattered(const std::vector<double>& xyz);
