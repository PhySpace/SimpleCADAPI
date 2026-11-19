"""OCCT polygonal HLR for spline-heavy review drawings."""

from io import BytesIO
import math


def mesh_shape(shape, deflection):
    try:
        from OCP.BRep import BRep_Builder
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.BRepTools import BRepTools
        from OCP.TopoDS import TopoDS_Shape
    except ImportError as exc:
        raise RuntimeError(
            "Polygonal projection requires the SimpleCADAPI verify extra: pip install simplecadapi[drawing,verify]"
        ) from exc
    from simplecadapi._cpp.occt.BRepTools import BRepTools as SourceBRepTools

    stream = BytesIO()
    SourceBRepTools.Write_s(shape, stream)
    stream.seek(0)
    mesh = TopoDS_Shape()
    BRepTools.Read_s(mesh, stream, BRep_Builder())
    if mesh.IsNull():
        raise RuntimeError("Polygonal projection could not read the source solid")
    build = BRepMesh_IncrementalMesh(mesh, deflection, False, 0.16, False)
    if not build.IsDone():
        raise RuntimeError("Polygonal projection could not mesh the source solid")
    return mesh


def projected_segments(mesh, frame):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_PolyAlgo, HLRBRep_PolyHLRToShape
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    right, _, normal = frame
    algo = HLRBRep_PolyAlgo()
    algo.Load(mesh)
    algo.Projector(
        HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*normal), gp_Dir(*right)))
    )
    algo.Update()
    output = HLRBRep_PolyHLRToShape()
    output.Update(algo)
    seen = set()
    for compound, visible in [
        (output.VCompound(), True),
        (output.OutLineVCompound(), True),
        (output.HCompound(), False),
        (output.OutLineHCompound(), False),
    ]:
        explorer = TopExp_Explorer(compound, TopAbs_EDGE)
        while explorer.More():
            edge = BRepAdaptor_Curve(TopoDS.Edge_s(explorer.Current()))
            a, b = (
                edge.Value(t) for t in (edge.FirstParameter(), edge.LastParameter())
            )
            points = [(a.X(), a.Y()), (b.X(), b.Y())]
            key = tuple(sorted(tuple(round(v, 7) for v in p) for p in points))
            if math.dist(*points) > 1e-7 and key not in seen:
                seen.add(key)
                yield points, visible
            explorer.Next()
