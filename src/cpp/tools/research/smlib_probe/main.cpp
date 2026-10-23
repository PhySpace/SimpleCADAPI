#include <Geom_BSplineSurface.hxx>
#include <GeomAPI_PointsToBSplineSurface.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepGProp.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS.hxx>
#include <GProp_GProps.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array2OfReal.hxx>
#include <chrono>
#include <tuple>
#include <cmath>
#include <cstdio>
#include "sm_side.hpp"

static double surf_fn(double x, double y) {  // a wavy, mildly sharp-featured height field
  return 0.35 * std::sin(1.7 * x) * std::cos(1.3 * y) + 0.15 * std::exp(-((x - 1) * (x - 1) + (y + 0.5) * (y + 0.5)) * 6.0);
}

static void report(const char* name, const Handle(Geom_BSplineSurface)& s, const std::vector<double>& xyz, double ms) {
  double maxd = 0, sum = 0; int n = 0;
  for (size_t i = 0; i < xyz.size(); i += 3) {
    GeomAPI_ProjectPointOnSurf proj(gp_Pnt(xyz[i], xyz[i + 1], xyz[i + 2]), s);
    const double d = proj.NbPoints() ? proj.LowerDistance() : 1e9;
    maxd = std::fmax(maxd, d); sum += d; ++n;
  }
  TopoDS_Face f = BRepBuilderAPI_MakeFace(s, 1e-6).Face();
  GProp_GProps p; BRepGProp::SurfaceProperties(f, p);
  std::printf("%-22s poles %3dx%-3d deg %d/%d  max dev %.3e  mean dev %.3e  area %.6f  valid=%d  %.1f ms\n", name,
              s->NbUPoles(), s->NbVPoles(), s->UDegree(), s->VDegree(), maxd, sum / n, p.Mass(),
              (int)BRepCheck_Analyzer(f).IsValid(), ms);
}

static Handle(Geom_BSplineSurface) to_occt(const NurbsSurfaceData& d) {
  TColgp_Array2OfPnt poles(1, d.nu, 1, d.nv);
  TColStd_Array2OfReal w(1, d.nu, 1, d.nv);
  for (int i = 0; i < d.nu; ++i)
    for (int j = 0; j < d.nv; ++j) {
      const size_t k = ((size_t)i * d.nv + j) * 3;
      poles(i + 1, j + 1) = gp_Pnt(d.poles[k], d.poles[k + 1], d.poles[k + 2]);
      w(i + 1, j + 1) = d.weights.empty() ? 1.0 : d.weights[(size_t)i * d.nv + j];
    }
  TColStd_Array1OfReal uk(1, (int)d.uknots.size()), vk(1, (int)d.vknots.size());
  TColStd_Array1OfInteger um(1, (int)d.umults.size()), vm(1, (int)d.vmults.size());
  for (size_t i = 0; i < d.uknots.size(); ++i) { uk((int)i + 1) = d.uknots[i]; um((int)i + 1) = d.umults[i]; }
  for (size_t i = 0; i < d.vknots.size(); ++i) { vk((int)i + 1) = d.vknots[i]; vm((int)i + 1) = d.vmults[i]; }
  return new Geom_BSplineSurface(poles, w, uk, vk, um, vm, d.udeg, d.vdeg);
}

static void scattered_test(const char* label, int count) {
  // Deterministic pseudo-random points of the height field (LCG), unordered.
  unsigned long long s = 88172645463325252ULL;
  auto rnd = [&]() { s = s * 6364136223846793005ULL + 1442695040888963407ULL; return ((s >> 11) & ((1ULL << 53) - 1)) / double(1ULL << 53); };
  std::vector<double> xyz;
  for (int i = 0; i < count; ++i) { const double x = -3 + 6 * rnd(), y = -3 + 6 * rnd(); xyz.insert(xyz.end(), {x, y, surf_fn(x, y)}); }
  auto t0 = std::chrono::steady_clock::now();
  NurbsSurfaceData d = sm_fit_scattered(xyz);
  double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  std::printf("[%s] SMLib scattered fit of %d unordered points: status=%ld ok=%d", label, count, d.status, (int)d.ok);
  if (!d.ok) { std::printf("\n"); return; }
  std::printf("  %dx%d poles deg %d/%d  %.1f ms\n", d.nu, d.nv, d.udeg, d.vdeg, ms);
  report("  vs its own samples", to_occt(d), xyz, ms);
  // Held-out check: fresh points the fit never saw.
  std::vector<double> held;
  for (int i = 0; i < 400; ++i) { const double x = -2.8 + 5.6 * rnd(), y = -2.8 + 5.6 * rnd(); held.insert(held.end(), {x, y, surf_fn(x, y)}); }
  report("  vs held-out points", to_occt(d), held, 0);
}

int main(int argc, char** argv) {
  setvbuf(stdout, nullptr, _IONBF, 0);
  if (argc > 1) { scattered_test("scattered", std::atoi(argv[1])); return 0; }
  const int N = 30;
  std::vector<double> xyz;
  for (int i = 0; i < N; ++i)
    for (int j = 0; j < N; ++j) {
      const double x = -3.0 + 6.0 * i / (N - 1), y = -3.0 + 6.0 * j / (N - 1);
      xyz.insert(xyz.end(), {x, y, surf_fn(x, y)});
    }

  // --- SMLib builds it, OCCT receives plain NURBS data.
  auto t0 = std::chrono::steady_clock::now();
  NurbsSurfaceData d = sm_interpolate_grid(xyz, N, N);
  double sm_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  std::printf("SMLib status=%ld ok=%d  %dx%d poles, degree %d/%d, rational=%d\n", d.status, (int)d.ok, d.nu, d.nv, d.udeg, d.vdeg, (int)!d.weights.empty());
  if (d.ok) {
    TColgp_Array2OfPnt poles(1, d.nu, 1, d.nv);
    TColStd_Array2OfReal w(1, d.nu, 1, d.nv);
    for (int i = 0; i < d.nu; ++i)
      for (int j = 0; j < d.nv; ++j) {
        const size_t k = ((size_t)i * d.nv + j) * 3;  // (u-major) assumption: verified by deviation below
        poles(i + 1, j + 1) = gp_Pnt(d.poles[k], d.poles[k + 1], d.poles[k + 2]);
        w(i + 1, j + 1) = d.weights.empty() ? 1.0 : d.weights[(size_t)i * d.nv + j];
      }
    TColStd_Array1OfReal uk(1, (int)d.uknots.size()), vk(1, (int)d.vknots.size());
    TColStd_Array1OfInteger um(1, (int)d.umults.size()), vm(1, (int)d.vmults.size());
    for (size_t i = 0; i < d.uknots.size(); ++i) { uk((int)i + 1) = d.uknots[i]; um((int)i + 1) = d.umults[i]; }
    for (size_t i = 0; i < d.vknots.size(); ++i) { vk((int)i + 1) = d.vknots[i]; vm((int)i + 1) = d.vmults[i]; }
    Handle(Geom_BSplineSurface) s = new Geom_BSplineSurface(poles, w, uk, vk, um, vm, d.udeg, d.vdeg);
    report("SMLib interpolate", s, xyz, sm_ms);
  }

  // --- OCCT baselines on identical data.
  TColgp_Array2OfPnt grid(1, N, 1, N);
  for (int i = 0; i < N; ++i)
    for (int j = 0; j < N; ++j) { const size_t k = ((size_t)i * N + j) * 3; grid(i + 1, j + 1) = gp_Pnt(xyz[k], xyz[k + 1], xyz[k + 2]); }
  for (double tol : {1e-3, 1e-5}) {
    t0 = std::chrono::steady_clock::now();
    GeomAPI_PointsToBSplineSurface approx(grid, 3, 8, GeomAbs_C2, tol);
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    char nm[64]; std::snprintf(nm, sizeof nm, "OCCT approx tol=%.0e", tol);
    report(nm, approx.Surface(), xyz, ms);
  }
  for (auto cfg : {std::make_tuple(3, 3, 1e-3), std::make_tuple(3, 3, 1e-5), std::make_tuple(3, 5, 1e-4)}) {
    t0 = std::chrono::steady_clock::now();
    GeomAPI_PointsToBSplineSurface a(grid, std::get<0>(cfg), std::get<1>(cfg), GeomAbs_C2, std::get<2>(cfg));
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    char nm[64]; std::snprintf(nm, sizeof nm, "OCCT deg%d-%d tol=%.0e", std::get<0>(cfg), std::get<1>(cfg), std::get<2>(cfg));
    report(nm, a.Surface(), xyz, ms);
  }
  t0 = std::chrono::steady_clock::now();
  GeomAPI_PointsToBSplineSurface interp; interp.Interpolate(grid);
  double ims = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  report("OCCT interpolate", interp.Surface(), xyz, ims);
  scattered_test("scattered", 900);
  return 0;
}
