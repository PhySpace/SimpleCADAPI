"""Fresh builders and a fresh on-disk notebook workspace for each BLDC sample."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def notebook():
    from simplecadapi import capture
    from simplecadapi.runtime import run_notebook

    with tempfile.TemporaryDirectory(prefix="bldc-", dir=ROOT / "out") as tmp:
        dest = Path(tmp)
        for p in (ROOT / "examples/integrated_bldc_joint_actuator").glob("*.py"):
            shutil.copyfile(p, dest / p.name)
        start = time.perf_counter()
        run = run_notebook(dest / "integrated_bldc_joint_actuator.py")
        built = time.perf_counter()
        path = dest / "model.scadpkg"
        capture(run.definition, path, include_scene=False)
        elapsed = time.perf_counter() - start
        checks = {}
        bodies = {}
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.startswith("definitions/part/"):
                    d = json.loads(archive.read(name))
                    checks[d["definition_id"]] = [d["interface_hashes"]["geometry"], d["tolerance_profile"]]
                    bodies[d["definition_id"]] = d["solid_cache"]["body_ref"]["sha256"]
        return dict(build_s=built-start, capture_s=elapsed-(built-start), total_s=elapsed,
                    parts=checks, brep_sha256=bodies, components=len(run.product.component_ids()), constraints=len(run.product.constraint_ids()),
                    root_cells=dict(Counter(cell.status for cell in run.cells)))


def operators():
    import simplecadapi as s

    cases = {
        'box': (50, lambda: s.make_box_rsolid(width=10,height=12,depth=7)),
        'cylinder': (50, lambda: s.make_cylinder_rsolid(radius=2,height=10)),
        'cut': (5, lambda: s.cut_rsolid(s.make_box_rsolid(10,12,7), s.make_cylinder_rsolid(2,10))),
        'spur12': (3, lambda: s.std.gear.make_spur_gear_rsolid(n_teeth=12,module=1,gear_height=4)),
        'spur48': (1, lambda: s.std.gear.make_spur_gear_rsolid(n_teeth=48,module=1,gear_height=4)),
        'bearing': (2, lambda: s.std.bearing.make_ball_bearing_rassembly(bore_diameter=8,outer_diameter=22,bearing_width=7,ball_diameter=3.5)),
        'bolt': (5, lambda: s.std.fastener.make_bolt_rsolid(8,24,thread_detail='cosmetic')),
        'sprocket': (1, lambda: s.std.chain.make_roller_chain_sprocket_rsolid(12,12.7,7.92,5.0)),
        'nut': (2, lambda: s.std.fastener.make_nut_rsolid(diameter=8,width=13,height=6.5,thread_detail='cosmetic')),
        'helical': (1, lambda: s.std.gear.make_helical_gear_rsolid(12,2.0,helix_angle=25,gear_height=8)),
        'herringbone': (1, lambda: s.std.gear.make_herringbone_gear_rsolid(12,2.0,helix_angle=25,gear_height=10)),
        'ring': (1, lambda: s.std.gear.make_spur_ring_gear_rsolid(20,2.0,gear_height=5,rim_thickness=4)),
        'ring_helical': (1, lambda: s.std.gear.make_helical_ring_gear_rsolid(20,2.,helix_angle=20.,gear_height=8.)),
        'ring_herringbone': (1, lambda: s.std.gear.make_herringbone_ring_gear_rsolid(20,2.,helix_angle=20.,gear_height=10.)),
        'rack': (1, lambda: s.std.gear.make_spur_rack_rsolid(module=2.,n_teeth=10)),
        'rack_helical': (1, lambda: s.std.gear.make_helical_rack_rsolid(module=2.,n_teeth=10)),
        'rack_herringbone': (1, lambda: s.std.gear.make_herringbone_rack_rsolid(module=2.,n_teeth=10)),
        'bevel': (1, lambda: s.std.gear.make_straight_bevel_gear_rsolid(18,4.0,45.0,20.,18.)),
        'cycloidal': (1, lambda: s.std.gear.make_cycloidal_disc_rsolid(8,15.,1.2,.7,4.)),
    }
    samples = {}
    for name,(count,fn) in cases.items():
        fn(); values=[]
        for _ in range(7):
            start=time.perf_counter_ns()
            for _ in range(count):fn()
            values.append((time.perf_counter_ns()-start)/count/1e6)
        samples[name]=values
    return samples


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('case',choices=['operators','bldc']);parser.add_argument('out',type=Path);a=parser.parse_args()
    from simplecadapi._cpp import _native
    (ROOT/'out').mkdir(exist_ok=True)
    payload=dict(python=sys.version,platform=platform.platform(),native_sha256=hashlib.sha256(Path(_native.__file__).read_bytes()).hexdigest(),data=(operators if a.case=='operators' else notebook)())
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf8')
