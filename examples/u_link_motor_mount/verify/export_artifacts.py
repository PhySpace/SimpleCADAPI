"""Check the exchange files written by ``export.py``.

    uv run python examples/u_link_motor_mount/export.py
    uv run python examples/u_link_motor_mount/verify/export_artifacts.py

  C1 the package, STEP and STL exist and are not empty
  C2 the package reopens: root assembly ``u-link-motor-mount-assembly``, and
     it is the product the notebook builds now (same content hash)
  C3 body and shell BReps are valid
  C4 the named mounting and back faces resolve on the body
  C5 export facts: STL has 2 solids, STEP has both part definitions and 2
     occurrences
"""

import json
import sys
from pathlib import Path

from simplecadapi import ql
from simplecadapi.inspect import brep
from simplecadapi.product.packages import read_product_package
from simplecadapi.runtime import run_notebook

HERE = Path(__file__).resolve().parents[1]
OUT_DIR = HERE / "out"
sys.path.insert(0, str(HERE))

from dimensions import TAG_BACK, TAG_MOUNT_LEFT, TAG_MOUNT_RIGHT  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")
    if not ok:
        failures.append(name)


paths = {suffix: OUT_DIR / f"u_link_assembly.{suffix}" for suffix in ("scadpkg", "step", "stl")}
check("C1 artifacts", all(p.exists() and p.stat().st_size > 0 for p in paths.values()),
      {k: (p.stat().st_size if p.exists() else 0) for k, p in paths.items()})

run = run_notebook(HERE / "u_link_motor_mount.py")
root = read_product_package(paths["scadpkg"]).root_definition
check("C2 package reopens as the current product", root.definition_kind == "assembly"
      and root.definition_id == "u-link-motor-mount-assembly"
      and root.content_hash == run.definition.content_hash,
      f"kind={root.definition_kind} id={root.definition_id}")

body = run.values["body"].body
shell = run.values["shell"].body
valid = all(brep.inspect_shape_rbrepinspection(shape=s.wrapped).valid for s in (body, shell))
check("C3 brep valid", valid, f"body={body.get_volume():.3f} shell={shell.get_volume():.3f}")

hits = {tag: len(ql.faces().where(ql.tag(tag)).resolve(body))
        for tag in (TAG_MOUNT_LEFT, TAG_MOUNT_RIGHT, TAG_BACK)}
check("C4 named faces", all(n == 1 for n in hits.values()), hits)

facts = json.loads((OUT_DIR / "export_facts.json").read_text())
stl, step = facts["stl"], facts["step"]
check("C5 export facts", stl["solid_count"] == 2 and stl["triangle_count"] > 0
      and {"u-link-motor-mount", "u-link-shell"} <= set(step["definition_ids"])
      and step["occurrence_count"] == 2,
      f"stl solids={stl['solid_count']} step defs={step['definition_ids']} "
      f"occ={step['occurrence_count']}")

print(f"export artifacts: {'ALL PASS' if not failures else 'FAILED ' + str(failures)}")
sys.exit(1 if failures else 0)
