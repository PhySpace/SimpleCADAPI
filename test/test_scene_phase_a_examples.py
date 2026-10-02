"""Opt-in Phase A hierarchy characterization for selected large examples."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUN_SLOW_EXAMPLES = os.environ.get("SIMPLECADAPI_RUN_SLOW_SCENE_EXAMPLES") == "1"

EXAMPLE_CASES = (
    (
        "hydraulic_rod_assembly/hydraulic_rod_assembly.py",
        3,
        3,
        2,
    ),
    (
        "compact_two_stage_planetary_reducer/compact_two_stage_planetary_reducer.py",
        116,
        17,
        15,
    ),
    (
        "integrated_bldc_joint_actuator/integrated_bldc_joint_actuator.py",
        89,
        38,
        29,
    ),
)

_PROBE = r"""
import json
from pathlib import Path
import sys

import simplecadapi as scad
from simplecadapi.product.assembly import Assembly
from simplecadapi.runtime import run_notebook

path = Path(sys.argv[1]).resolve()
print(f"SCENE_PHASE_A_START={path.name}", flush=True)
assembly = run_notebook(path).product
if not isinstance(assembly, Assembly):
    raise TypeError(f"{path.name} did not produce an Assembly product")

nodes = []
def walk(item):
    nodes.append(item)
    if isinstance(item, Assembly):
        for component in item.components:
            walk(component.item)

walk(assembly)
definitions = {
    ("assembly", item.assembly_id)
    if isinstance(item, Assembly)
    else ("part", item.part_id)
    for item in nodes
}
part_definitions = {
    item.part_id
    for item in nodes
    if not isinstance(item, Assembly)
}
face_naming = {}
if path.name == "hydraulic_rod_assembly.py":
    naming_contract = {
        "outer_sleeve": ("sleeve.", "sleeve.gland.face.mount"),
        "piston_rod": ("rod.", "rod.piston.land.left.face.rear"),
    }
    for part_id, (prefix, connector_face_tag) in naming_contract.items():
        part = next(
            item
            for item in nodes
            if not isinstance(item, Assembly) and item.part_id == part_id
        )
        faces = part.body._iter_faces()
        face_naming[part_id] = {
            "face_count": len(faces),
            "unnamed_indices": [
                index
                for index, face in enumerate(faces)
                if not any(
                    tag.startswith(prefix)
                    for tag in scad.list_tags(face, scope="local")
                )
            ],
            "connector_face_count": len(
                scad.select_faces_by_tag(
                    part.body,
                    connector_face_tag,
                    scope="local",
                )
            ),
        }
print("SCENE_PHASE_A_FACTS=" + json.dumps({
    "expected_mesh_count": len(part_definitions),
    "face_naming": face_naming,
    "product_node_count": len(nodes),
    "unique_definition_count": len(definitions),
}, sort_keys=True), flush=True)
"""


@pytest.mark.skipif(
    not RUN_SLOW_EXAMPLES,
    reason="set SIMPLECADAPI_RUN_SLOW_SCENE_EXAMPLES=1 to run large examples",
)
@pytest.mark.parametrize(
    (
        "relative_path",
        "expected_nodes",
        "expected_definitions",
        "expected_meshes",
    ),
    EXAMPLE_CASES,
    ids=("hydraulic_rod_assembly", "planetary_reducer", "bldc_joint_actuator"),
)
def test_allowlisted_example_product_hierarchy_in_fresh_process(
    relative_path: str,
    expected_nodes: int,
    expected_definitions: int,
    expected_meshes: int,
):
    path = ROOT / "examples" / relative_path
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"
    label = relative_path
    print(
        f"\n[scene-example] starting {label}; "
        f"expected nodes={expected_nodes}, definitions={expected_definitions}, "
        f"meshes={expected_meshes}",
        flush=True,
    )
    started = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, "-c", _PROBE, str(path)],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    output: list[str] = []

    def relay_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output.append(line)
            print(f"[{relative_path}] {line}", end="", flush=True)

    relay = threading.Thread(target=relay_output, daemon=True)
    relay.start()
    try:
        next_heartbeat = 15.0
        while process.poll() is None:
            elapsed = time.monotonic() - started
            if elapsed >= 600:
                process.kill()
                process.wait()
                pytest.fail(f"{label} timed out after {elapsed:.1f}s")
            if elapsed >= next_heartbeat:
                print(
                    f"[scene-example] still building {label}; elapsed={elapsed:.1f}s",
                    flush=True,
                )
                next_heartbeat += 15.0
            time.sleep(0.5)
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        relay.join(timeout=5)

    elapsed = time.monotonic() - started
    stdout = "".join(output)
    print(
        f"[scene-example] finished {label}; "
        f"returncode={process.returncode}, elapsed={elapsed:.1f}s",
        flush=True,
    )
    assert process.returncode == 0, stdout
    fact_lines = [
        line.removeprefix("SCENE_PHASE_A_FACTS=")
        for line in stdout.splitlines()
        if line.startswith("SCENE_PHASE_A_FACTS=")
    ]
    assert len(fact_lines) == 1, stdout
    assert json.loads(fact_lines[0]) == {
        "expected_mesh_count": expected_meshes,
        "face_naming": (
            {
                "outer_sleeve": {
                    "connector_face_count": 1,
                    "face_count": 29,
                    "unnamed_indices": [],
                },
                "piston_rod": {
                    "connector_face_count": 1,
                    "face_count": 24,
                    "unnamed_indices": [],
                },
            }
            if relative_path.startswith("hydraulic_rod_assembly/")
            else {}
        ),
        "product_node_count": expected_nodes,
        "unique_definition_count": expected_definitions,
    }
