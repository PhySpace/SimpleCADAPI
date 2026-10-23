"""Reference-interpreter snippets shared by the io pytest files.

Each constant is a snippet for tests/python/ref.py::golden: it runs in the
reference SDK (the Python SimpleCADAPI on OCP) and returns JSON.
"""

# OpenCASCADE prints its transfer statistics on the process's stdout, which is where
# ref.py expects only the JSON answer; QUIET/LOUD move fd 1 aside around the noisy part.
QUIET = '''
import ctypes, os
_saved_stdout = os.dup(1)
os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
'''
LOUD = '''
ctypes.CDLL(None).fflush(None)
os.dup2(_saved_stdout, 1)
'''

SCADBREP_SNIPPET = QUIET + '''
import base64, hashlib, tempfile
from pathlib import Path
from simplecadapi.inspect import brep
from simplecadapi.kernel.ocp_export import export_step_shapes
from simplecadapi._internal.brep_region import HEADER
from simplecadapi._internal.canonical_json import parse_canonical_json

def build(kind):
    if kind == "box":
        return scad.make_box_rsolid(width=10.0, height=20.0, depth=30.0, bottom_face_center=(5.0, 0.0, 0.0))
    return scad.make_cylinder_rsolid(radius=4.0, height=10.0)

out = {}
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    for kind in ("box", "cylinder"):
        solid = build(kind)
        step = tmp / f"{kind}.step"
        export_step_shapes([solid.wrapped], str(step))
        snap = tmp / f"{kind}.scadbrep"
        brep.copy_step_region_rpath(path=step, output_path=snap)
        data = snap.read_bytes()
        size = HEADER.unpack_from(data)[4]
        out[kind] = {
            "artifact_b64": base64.b64encode(data).decode(),
            "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
            "volume": solid.get_volume(),
            "faces": len(solid._iter_faces()),
            "manifest": parse_canonical_json(data[HEADER.size:HEADER.size + size]),
        }
    step = tmp / "box.step"
    model = brep.load_step_rbrepmodel(step)
    top = max(range(len(model.faces)), key=lambda i: model.describe_entity(f"face:{i}")["geometry"]["centroid"][2])
    snap = tmp / "box_top.scadbrep"
    brep.copy_step_region_rpath(path=step, output_path=snap, face_ids=[f"face:{top}"])
    data = snap.read_bytes()
    size = HEADER.unpack_from(data)[4]
    out["box_top"] = {
        "artifact_b64": base64.b64encode(data).decode(),
        "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        "face": top,
        "manifest": parse_canonical_json(data[HEADER.size:HEADER.size + size]),
    }
''' + LOUD + '''
result = out
'''


# A box with a through hole and a cylinder: STEP / STL / BREP / mesh reference numbers.
EXCHANGE_SNIPPET = QUIET + '''
import base64, hashlib, tempfile
from pathlib import Path
from simplecadapi.kernel.ocp_export import export_step_shapes, export_stl_shape
from simplecadapi.artifacts.brep import write_brep_bytes
from simplecadapi._internal.mesh import cached_mesh
from simplecadapi.exporter import tessellate_solid

out = {}
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    body = scad.make_box_rsolid(10, 10, 10)
    tool = scad.make_cylinder_rsolid(2.0, 15.0, bottom_face_center=(3, 3, -2.5))
    holed = scad.cut_rsolid(body, tool)
    cylinder = scad.make_cylinder_rsolid(radius=3.0, height=5.0)
    box = scad.make_box_rsolid(width=10.0, height=20.0, depth=30.0)
    for name, solid in (("box", box), ("cylinder", cylinder), ("holed", holed)):
        step = tmp / f"{name}.step"
        export_step_shapes([solid.wrapped], str(step))
        stl = tmp / f"{name}.stl"
        export_stl_shape(solid.wrapped, str(stl))
        facets = stl.read_text().count("facet normal")
        brep_bytes = write_brep_bytes(solid)
        tri = cached_mesh(solid)
        v, t = tessellate_solid(solid.wrapped, linear_deflection=0.1, angular_deflection_degrees=20.0, relative=False)
        bb = solid.wrapped
        from simplecadapi._cpp.occt.Bnd import Bnd_Box
        from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib
        box3 = Bnd_Box()
        BRepBndLib.Add_s(bb, box3)
        lo_hi = [float(x) for x in box3.Get()]
        out[name] = {
            "volume": solid.get_volume(),
            "faces": len(solid._iter_faces()),
            "edges": len(solid._iter_edges()) if hasattr(solid, "_iter_edges") else None,
            "bbox": lo_hi,
            "step_b64": base64.b64encode(step.read_bytes()).decode(),
            "ascii_stl_facets": facets,
            "brep_b64": base64.b64encode(brep_bytes).decode(),
            "brep_sha256": hashlib.sha256(brep_bytes).hexdigest(),
            "trimesh": {"vertices": int(tri.vertex_count), "triangles": int(tri.triangle_count),
                        "bounds": [list(map(float, p)) for p in tri.bounds]},
            "welded": {"vertices": int(len(v)), "triangles": int(len(t))},
        }
''' + LOUD + '''
result = out
'''
