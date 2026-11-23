// Runs the Y-junction case family: the standard algorithm, a plain MakeFillet (the default
// Y fallback), then the Y patch.
//   cases [name-filter | =exact-name]
// Environment: YPATCH_SRC_ROUNDTRIP reads each input
// back from BREP first.  Writes src-<case>.brep and, on success, case-<case>.brep.
#include "cases.hxx"
#include <BRepFilletAPI_MakeFillet.hxx>
#include <ChFi3d_FilBuilder.hxx>
#include <BRepFilletAPI_YPatch.hxx>
#include <BRep_Builder.hxx>
#include <chrono>
#include <cstdlib>
#include <sstream>
#include <BinTools.hxx>
#include <functional>
#include <ShapeUpgrade_UnifySameDomain.hxx>
#include <BRepAlgoAPI_Splitter.hxx>
#include <TopTools_MapOfShape.hxx>

static TopoDS_Shape roundtrip(const TopoDS_Shape& s)
{
  std::stringstream ss;
  BRepTools::Write(s, ss);
  TopoDS_Shape back;
  BRep_Builder b;
  BRepTools::Read(back, ss, b);
  return back;
}

int main(int argc, char** argv)
{
  int               failures = 0;
  std::vector<Case> all      = family();
  if (const char* path = std::getenv("YPATCH_SDK_FIXTURE")) // the SDK's plate/post (binary BREP)
  {
    TopoDS_Shape s;
    BinTools::Read(s, path);
    for (const double r : {1., 2.5, 5., 8., 12.})
    {
      all.push_back({"sdk-plate-post-" + radiusTag(r), s,
                     {{gp_Pnt(35.3553, -35.3553, 40), r}, {gp_Pnt(35.3553, 35.3553, 40), r}, {gp_Pnt(75, -50, 40), r}}});
      all.push_back({"sdk-plate-post-both-sides-" + radiusTag(r), s,
                     {{gp_Pnt(35.3553, -35.3553, 40), r}, {gp_Pnt(35.3553, 35.3553, 40), r}, {gp_Pnt(75, -50, 40), r},
                      {gp_Pnt(75, 50, 40), r}}});
    }
  }
  for (auto& c : all)
  {
    const std::string want = argc > 1 ? argv[1] : "";
    if (!want.empty() && (want[0] == '=' ? c.name != want.substr(1) : c.name.find(want) == std::string::npos))
      continue;
    std::printf("== %s\n", c.name.c_str());
    if (std::getenv("YPATCH_SRC_ROUNDTRIP"))
      c.shape = roundtrip(c.shape);
    std::vector<std::pair<TopoDS_Edge, double>> picked; // in pick order: runs are reproducible
    TopTools_DataMapOfShapeReal                 radii;
    for (auto& [p, r] : c.picks)
    {
      picked.emplace_back(edge_at(c.shape, p), r);
      radii.Bind(picked.back().first, r);
    }
    // the standard algorithm alone (ChFi3d, as MakeFillet runs it, without any Y strategy)
    bool standardSound = false;
    {
      ChFi3d_FilBuilder f(c.shape);
      for (auto& [e, r] : picked)
        f.Add(r, e);
      try
      {
        f.Compute();
        if (f.IsDone())
        {
          const int si   = si_count(f.Shape());
          standardSound  = valid(f.Shape()) && si == 0;
          std::printf("  standard: done valid %d si %d\n", valid(f.Shape()), si);
        }
        else
          std::printf("  standard: not done\n");
      }
      catch (Standard_Failure& e)
      {
        std::printf("  standard: throws %s\n", e.GetMessageString());
      }
    }
    // a plain MakeFillet (no SetYPatch): with a junction it must succeed; where the standard
    // result is sound it must be that result
    const bool hasJunction = !BRepFilletAPI_YPatch::Detect(c.shape, radii).IsEmpty();
    {
      BRepFilletAPI_MakeFillet plain(c.shape);
      for (auto& [e, r] : picked)
        if (plain.Contour(e) == 0)
          plain.Add(r, e);
      bool ok = false, sound = false;
      try
      {
        plain.Build();
        ok    = plain.IsDone();
        sound = ok && valid(plain.Shape()) && si_count(plain.Shape()) == 0;
      }
      catch (Standard_Failure&)
      {
      }
      const char* path = !ok ? "-" : plain.YPatchFallback() ? "Y fallback" : plain.NbYPatches() ? "Y" : "standard";
      bool        pass = true;
      if (hasJunction && !c.expect_refusal)
        pass = sound;
      if (standardSound)
        pass = pass && ok && !plain.YPatchFallback() && plain.NbYPatches() == 0;
      std::printf("  plain: done %d sound %d path %s%s\n", (int)ok, (int)sound, path, pass ? "" : " FAILED");
      failures += pass ? 0 : 1;
    }
    auto js = BRepFilletAPI_YPatch::Detect(c.shape, radii);
    std::printf("  junctions %d", js.Length());
    for (auto& j : js)
      std::printf(" [support angle %.3f deg]", j.SupportAngle * 180 / M_PI);
    std::printf("\n");
    TopoDS_Shape                                         out;
    Handle(BRepTools_History)                            h;
    NCollection_Vector<BRepFilletAPI_YPatch::Junction> rep;
    auto t0 = std::chrono::steady_clock::now();
    bool ok = BRepFilletAPI_YPatch::Perform(c.shape, radii, out, h, rep, std::getenv("YPATCH_PINCH") != nullptr);
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    std::printf("  ypatch: ok %d %.0f ms", ok, ms);
    if (ok == c.expect_refusal)
      ++failures;
    if (!ok && c.expect_refusal)
      std::printf(" (refused, as expected)");
    if (ok)
    {
      std::printf(" valid %d si %d faces %d", valid(out), si_count(out), count(out, TopAbs_FACE));
      // Strict history, from Perform and from the entry point the SDK uses (MakeFillet with
      // SetYPatch): no input face is deleted (none lies wholly inside a removed wedge in
      // this family), its images are result faces; a junction edge generates its band and
      // its ribbon (>= 2 faces), every selected edge generates >= 1; every result face is an
      // image of an input face or generated by a selected edge.
      TopTools_IndexedMapOfShape junctionEdges;
      for (auto& j : BRepFilletAPI_YPatch::Detect(c.shape, radii))
      {
        junctionEdges.Add(j.Concave);
        junctionEdges.Add(j.Convex);
      }
      BRepFilletAPI_MakeFillet mf(c.shape);
      mf.SetYPatch(Standard_True);
      for (auto& [e, r] : picked)
        if (mf.Contour(e) == 0)
          mf.Add(r, e);
      mf.Build();
      const bool viaMakeFillet = mf.IsDone() && mf.NbYPatches() == rep.Length();
      std::printf(" makefillet %s", viaMakeFillet ? "ok" : "FAILED");
      if (!viaMakeFillet)
        std::printf(" [done %d y-patches %d, expected %d]", (int)mf.IsDone(), mf.NbYPatches(), rep.Length());
      failures += viaMakeFillet ? 0 : 1;
      using List  = TopTools_ListOfShape;
      auto strict = [&](const char* tag, const TopoDS_Shape& result, const std::function<bool(const TopoDS_Shape&)>& deleted,
                        const std::function<List(const TopoDS_Shape&)>& modified,
                        const std::function<List(const TopoDS_Shape&)>& generated) {
        TopTools_IndexedMapOfShape outFaces, inFaces, covered;
        TopExp::MapShapes(result, TopAbs_FACE, outFaces);
        TopExp::MapShapes(c.shape, TopAbs_FACE, inFaces);
        bool good = true;
        for (int i = 1; i <= inFaces.Extent(); ++i)
        {
          const TopoDS_Shape& f = inFaces(i);
          List                m = modified(f);
          if (m.IsEmpty() && !deleted(f))
            m.Append(f);
          bool ok = !deleted(f) && !m.IsEmpty();
          for (List::Iterator it(m); it.More(); it.Next())
          {
            ok = ok && outFaces.Contains(it.Value());
            covered.Add(it.Value());
          }
          if (!ok)
            std::printf(" [%s: face %d deleted %d images %d]", tag, i, (int)deleted(f), m.Extent());
          good = good && ok;
        }
        for (auto& [e, r] : picked)
        {
          int n = 0;
          const List g = generated(e);
          for (List::Iterator it(g); it.More(); it.Next())
            if (outFaces.Contains(it.Value()))
            {
              ++n;
              covered.Add(it.Value());
            }
          const int need = junctionEdges.Contains(e) ? 2 : 1;
          if (n < need)
            std::printf(" [%s: edge at (%.1f %.1f %.1f) generates %d < %d]", tag, mid(e).X(), mid(e).Y(), mid(e).Z(), n, need);
          good = good && n >= need;
        }
        // faces generated by any input edge are tracked (a seed drags its tangent chain along)
        TopTools_IndexedMapOfShape inEdges;
        TopExp::MapShapes(c.shape, TopAbs_EDGE, inEdges);
        for (int i = 1; i <= inEdges.Extent(); ++i)
        {
          const List g = generated(inEdges(i));
          for (List::Iterator it(g); it.More(); it.Next())
            covered.Add(it.Value());
        }
        for (int i = 1; i <= outFaces.Extent(); ++i)
          if (!covered.Contains(outFaces(i)))
          {
            std::printf(" [%s: result face %d untracked]", tag, i);
            good = false;
          }
        return good;
      };
      bool historyOk =
        strict("perform", out, [&](const TopoDS_Shape& s) { return h->IsRemoved(s); },
               [&](const TopoDS_Shape& s) { return h->Modified(s); }, [&](const TopoDS_Shape& s) { return h->Generated(s); })
        && (!viaMakeFillet
            || strict("makefillet", mf.Shape(), [&](const TopoDS_Shape& s) { return mf.IsDeleted(s); },
                      [&](const TopoDS_Shape& s) { return mf.Modified(s); },
                      [&](const TopoDS_Shape& s) { return mf.Generated(s); }));
      // the default fallback (no SetYPatch) answers the same history when it takes the Y path
      BRepFilletAPI_MakeFillet plain(c.shape);
      for (auto& [e, r] : picked)
        if (plain.Contour(e) == 0)
          plain.Add(r, e);
      plain.Build();
      const bool fallbackOk =
        !plain.IsDone() || !plain.YPatchFallback()
        || strict("fallback", plain.Shape(), [&](const TopoDS_Shape& s) { return plain.IsDeleted(s); },
                  [&](const TopoDS_Shape& s) { return plain.Modified(s); },
                  [&](const TopoDS_Shape& s) { return plain.Generated(s); });
      historyOk = historyOk && fallbackOk;
      std::printf(" history %s\n", historyOk ? "ok" : "BROKEN");
      failures += historyOk ? 0 : 1;
      for (auto& j : rep)
        std::printf("    P*(%.4f %.4f %.4f) seam %.2e deg band %.2e deg\n", j.Split.X(), j.Split.Y(), j.Split.Z(),
                    j.SeamAngle * 180 / M_PI, j.BandAngle * 180 / M_PI);
      BRepTools::Write(out, ("case-" + c.name + ".brep").c_str());
    }
    else
      std::printf("\n");
    BRepTools::Write(c.shape, ("src-" + c.name + ".brep").c_str());
  }
  std::printf("failures %d\n", failures);
  return failures;
}
