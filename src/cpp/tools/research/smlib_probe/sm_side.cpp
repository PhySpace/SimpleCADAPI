#include "sm_side.hpp"
#include <SmApiGeneral.h>
#include <SmApiSurfaces.h>
#include <SmBSplineSurface.h>
#include <SmTArray.h>

NurbsSurfaceData sm_interpolate_grid(const std::vector<double>& xyz, int nrows, int ncols) {
  NurbsSurfaceData out;
  SmApiCreateContext();
  SmTArray<SmPoint3d> pts;
  for (size_t i = 0; i < xyz.size(); i += 3) pts.Add(SmPoint3d(xyz[i], xyz[i + 1], xyz[i + 2]));
  SmSurface* srf = nullptr;
  out.status = SmApiCreateSurfaceFromOrderedPoints(pts, (ULONG)nrows, (ULONG)ncols, srf);
  if (out.status != 1000L /*SM_SUCCESS*/ || !srf) return out;
  auto* bs = dynamic_cast<SmBSplineSurface*>(srf);
  if (!bs) return out;
  ULONG nu = 0, nv = 0;
  SmTArray<SmPoint3d> cps;
  SmTArray<double> w;
  bs->GetControlPointNet(nu, nv, cps, w);
  out.nu = (int)nu; out.nv = (int)nv;
  out.udeg = (int)bs->GetDegree(SM_SP_U);
  out.vdeg = (int)bs->GetDegree(SM_SP_V);
  for (ULONG i = 0; i < cps.GetSize(); ++i) {
    out.poles.push_back(cps[i].x); out.poles.push_back(cps[i].y); out.poles.push_back(cps[i].z);
  }
  for (ULONG i = 0; i < w.GetSize(); ++i) out.weights.push_back(w[i]);
  SmTArray<double> k; SmTArray<ULONG> m;
  bs->GetKnots(SM_SP_U, k, &m);
  for (ULONG i = 0; i < k.GetSize(); ++i) { out.uknots.push_back(k[i]); out.umults.push_back((int)m[i]); }
  SmTArray<double> k2; SmTArray<ULONG> m2;
  bs->GetKnots(SM_SP_V, k2, &m2);
  for (ULONG i = 0; i < k2.GetSize(); ++i) { out.vknots.push_back(k2[i]); out.vmults.push_back((int)m2[i]); }
  out.ok = true;
  return out;
}

NurbsSurfaceData sm_fit_scattered(const std::vector<double>& xyz) {
  NurbsSurfaceData out;
  SmApiCreateContext();
  SmTArray<SmPoint3d> pts;
  for (size_t i = 0; i < xyz.size(); i += 3) pts.Add(SmPoint3d(xyz[i], xyz[i + 1], xyz[i + 2]));
  SmSurface* srf = nullptr;
  out.status = SmApiCreateSurfaceFromRandomPoints(pts, srf);
  if (out.status != 1000L || !srf) return out;
  auto* bs = dynamic_cast<SmBSplineSurface*>(srf);
  if (!bs) return out;
  ULONG nu = 0, nv = 0; SmTArray<SmPoint3d> cps; SmTArray<double> w;
  bs->GetControlPointNet(nu, nv, cps, w);
  out.nu = (int)nu; out.nv = (int)nv;
  out.udeg = (int)bs->GetDegree(SM_SP_U); out.vdeg = (int)bs->GetDegree(SM_SP_V);
  for (ULONG i = 0; i < cps.GetSize(); ++i) { out.poles.push_back(cps[i].x); out.poles.push_back(cps[i].y); out.poles.push_back(cps[i].z); }
  for (ULONG i = 0; i < w.GetSize(); ++i) out.weights.push_back(w[i]);
  SmTArray<double> k; SmTArray<ULONG> m; bs->GetKnots(SM_SP_U, k, &m);
  for (ULONG i = 0; i < k.GetSize(); ++i) { out.uknots.push_back(k[i]); out.umults.push_back((int)m[i]); }
  SmTArray<double> k2; SmTArray<ULONG> m2; bs->GetKnots(SM_SP_V, k2, &m2);
  for (ULONG i = 0; i < k2.GetSize(); ++i) { out.vknots.push_back(k2[i]); out.vmults.push_back((int)m2[i]); }
  out.ok = true; return out;
}
