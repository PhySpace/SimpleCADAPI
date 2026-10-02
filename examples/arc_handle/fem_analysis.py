"""Run Gmsh and CalculiX linear-static load cases for the arched handle.

Units are mm, N, and MPa. The material is an isotropic FDM PVC proxy, not a
certification of a particular filament, infill, raster direction, or print.

Boundary condition: both Y=-2.5 mm mounting-ear back faces are rigidly fixed
against the wall. Load condition: forces are distributed over the middle 20 mm
of the exposed grip surface. Positive Y pulls away from the wall and negative
Z applies the requested transverse component.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

import simplecadapi as scad
from simplecadapi.runtime import run_notebook


EXAMPLE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = EXAMPLE_DIR / "out" / "fem"
NOTEBOOK_PATH = EXAMPLE_DIR / "arc_handle.py"
PACKAGE_PATH = EXAMPLE_DIR / "out" / "arc_handle.scadpkg"
STEP_PATH = OUTPUT_DIR / "arc_handle.step"
MESH_PATH = OUTPUT_DIR / "arc_handle.msh"
MESH_REPORT_PATH = OUTPUT_DIR / "arc_handle.mesh.json"
SUMMARY_PATH = OUTPUT_DIR / "arc_handle.fem.json"

# Conservative linear-elastic proxy for unfilled FDM PVC. The printed object
# may be anisotropic and weaker across layers, so this supports comparison of
# hot spots, not a strength or safety claim.
MATERIAL_NAME = "FDM_PVC_ISOTROPIC_PROXY"
YOUNGS_MODULUS_MPA = 2_500.0
POISSON_RATIO = 0.38

MOUNTING_FACE_Y_MM = -2.5
MOUNTING_FACE_TOLERANCE_MM = 0.02
GRIP_HALF_WIDTH_MM = 10.0
GRIP_MIN_Y_MM = 15.0

CASE_DEFINITIONS = (
    ("normal_250N", 250.0 / math.sqrt(2.0), -250.0 / math.sqrt(2.0)),
    ("strong_500N", 500.0 / math.sqrt(2.0), -500.0 / math.sqrt(2.0)),
    ("combined_707N", 500.0, -500.0),
)

_FLOAT_PATTERN = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")


@dataclass(frozen=True, slots=True)
class MeshData:
    nodes: dict[int, tuple[float, float, float]]
    tetrahedra: tuple[tuple[int, int, int, int, int], ...]
    support_nodes: tuple[int, ...]
    load_nodes: tuple[int, ...]
    support_surface_tags: tuple[int, ...]
    load_surface_node_count: int


@dataclass(frozen=True, slots=True)
class CaseResult:
    name: str
    amplified_png_path: str
    force_y_n: float
    force_z_n: float
    resultant_force_n: float
    input_path: str
    dat_path: str
    frd_path: str
    png_path: str
    max_displacement_mm: float
    max_displacement_node: int
    max_von_mises_mpa: float
    max_von_mises_element: int
    max_von_mises_centroid_mm: tuple[float, float, float]
    stress_location: str
    reaction_force_n: tuple[float, float, float]
    balance_error_y_n: float
    balance_error_z_n: float


def _import_gmsh() -> Any:
    import gmsh

    return gmsh


def _import_vtk() -> Any:
    import vtk

    return vtk


def _surface_nodes(gmsh: Any, surface_tags: Iterable[int]) -> set[int]:
    nodes: set[int] = set()
    for tag in surface_tags:
        values, _coordinates, _parameters = gmsh.model.mesh.getNodes(
            2, int(tag), includeBoundary=True
        )
        nodes.update(int(value) for value in values)
    return nodes


def _mounting_surfaces(gmsh: Any) -> tuple[int, ...]:
    tags: list[int] = []
    for _dimension, tag in gmsh.model.getEntities(2):
        bounds = gmsh.model.getBoundingBox(2, int(tag))
        if (
            abs(float(bounds[1]) - MOUNTING_FACE_Y_MM) <= MOUNTING_FACE_TOLERANCE_MM
            and abs(float(bounds[4]) - MOUNTING_FACE_Y_MM) <= MOUNTING_FACE_TOLERANCE_MM
            and gmsh.model.occ.getMass(2, int(tag)) > 50.0
        ):
            tags.append(int(tag))
    if len(tags) != 2:
        raise RuntimeError(f"expected two mounting-wall faces, found {tags}")
    return tuple(sorted(tags))


def export_step() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # The notebook run is cell-cached, so loading the product here is cheap.
    scad.capture(run_notebook(NOTEBOOK_PATH).definition, PACKAGE_PATH)
    report = scad.exporter.step.export_product_package_to_step(
        data=PACKAGE_PATH,
        output_path=STEP_PATH,
    )
    if not STEP_PATH.is_file() or STEP_PATH.stat().st_size <= 0:
        raise RuntimeError(f"STEP export did not create {STEP_PATH}")
    print("step", report.output_path)
    print("step_schema", report.schema)
    print("step_definitions", ",".join(report.definition_ids))
    return STEP_PATH


def mesh_handle(*, mesh_size_mm: float) -> MeshData:
    if mesh_size_mm <= 0.0:
        raise ValueError("mesh_size_mm must be positive")
    step_path = export_step()
    gmsh = _import_gmsh()
    initialized = False
    try:
        gmsh.initialize()
        initialized = True
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.model.add("arc_handle_fem")
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        gmsh.model.occ.importShapes(str(step_path))
        gmsh.model.occ.synchronize()
        volumes = gmsh.model.getEntities(3)
        if len(volumes) != 1:
            raise RuntimeError(f"expected one imported solid, found {volumes}")
        support_surface_tags = _mounting_surfaces(gmsh)
        support_group = gmsh.model.addPhysicalGroup(2, list(support_surface_tags))
        gmsh.model.setPhysicalName(2, support_group, "wall_mounting_faces")
        volume_group = gmsh.model.addPhysicalGroup(3, [int(volumes[0][1])])
        gmsh.model.setPhysicalName(3, volume_group, "arc_handle_body")

        # Global 0.9 mm mesh, tightened near mounting holes and roots by the
        # imported end-region faces. The refinement is intentionally limited
        # so the long grip does not dominate element count.
        gmsh.option.setNumber("Mesh.MeshSizeMin", min(0.55, mesh_size_mm))
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size_mm)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.model.mesh.generate(3)

        node_tags, coordinates, _parameters = gmsh.model.mesh.getNodes()
        coordinate_values = np.asarray(coordinates, dtype=float).reshape((-1, 3))
        nodes = {
            int(tag): (float(point[0]), float(point[1]), float(point[2]))
            for tag, point in zip(node_tags, coordinate_values)
        }
        tetrahedron_type = int(gmsh.model.mesh.getElementType("Tetrahedron", 1))
        element_tags, element_nodes = gmsh.model.mesh.getElementsByType(tetrahedron_type)
        connectivity = np.asarray(element_nodes, dtype=np.int64).reshape((-1, 4))
        tetrahedra = tuple(
            (
                int(element),
                int(element_nodes_row[0]),
                int(element_nodes_row[1]),
                int(element_nodes_row[2]),
                int(element_nodes_row[3]),
            )
            for element, element_nodes_row in zip(element_tags, connectivity)
        )
        if not tetrahedra:
            raise RuntimeError("Gmsh generated no first-order tetrahedra")

        support_nodes = tuple(sorted(_surface_nodes(gmsh, support_surface_tags)))
        all_boundary_surfaces = [int(tag) for _dim, tag in gmsh.model.getEntities(2)]
        boundary_nodes = _surface_nodes(gmsh, all_boundary_surfaces)
        load_nodes = tuple(
            sorted(
                node
                for node in boundary_nodes
                if abs(nodes[node][0]) <= GRIP_HALF_WIDTH_MM
                and nodes[node][1] >= GRIP_MIN_Y_MM
            )
        )
        if not support_nodes:
            raise RuntimeError("mounting-wall faces contain no mesh nodes")
        if len(load_nodes) < 10:
            raise RuntimeError(f"central grip load selection is too small: {len(load_nodes)} nodes")
        gmsh.write(str(MESH_PATH))
    finally:
        if initialized:
            gmsh.finalize()

    payload = {
        "units": {"length": "mm"},
        "mesh_size_mm": mesh_size_mm,
        "node_count": len(nodes),
        "tetrahedron_count": len(tetrahedra),
        "support_surface_tags": support_surface_tags,
        "support_node_count": len(support_nodes),
        "load_node_count": len(load_nodes),
        "load_region": {
            "abs_x_max_mm": GRIP_HALF_WIDTH_MM,
            "y_min_mm": GRIP_MIN_Y_MM,
        },
    }
    MESH_REPORT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("mesh", MESH_PATH)
    print("mesh_nodes", len(nodes))
    print("mesh_tetrahedra", len(tetrahedra))
    print("support_nodes", len(support_nodes))
    print("load_nodes", len(load_nodes))
    return MeshData(
        nodes=nodes,
        tetrahedra=tetrahedra,
        support_nodes=support_nodes,
        load_nodes=load_nodes,
        support_surface_tags=support_surface_tags,
        load_surface_node_count=len(load_nodes),
    )


def _append_set(lines: list[str], name: str, node_ids: Iterable[int]) -> None:
    values = list(node_ids)
    lines.append(f"*NSET,NSET={name}")
    for start in range(0, len(values), 16):
        lines.append(",".join(str(value) for value in values[start : start + 16]))


def write_calculix_input(*, mesh: MeshData, case_name: str, force_y_n: float, force_z_n: float) -> Path:
    input_path = OUTPUT_DIR / f"arc_handle_{case_name}.inp"
    lines = [
        "*HEADING",
        f"Arched handle: {case_name} linear-static FDM PVC proxy",
        "** Units: mm, N, MPa",
        "*NODE,NSET=NALL",
    ]
    lines.extend(
        f"{node},{x:.12g},{y:.12g},{z:.12g}"
        for node, (x, y, z) in sorted(mesh.nodes.items())
    )
    lines.append("*ELEMENT,TYPE=C3D4,ELSET=EALL")
    lines.extend(
        f"{element},{first},{second},{third},{fourth}"
        for element, first, second, third, fourth in mesh.tetrahedra
    )
    _append_set(lines, "WALL_SUPPORT", mesh.support_nodes)
    _append_set(lines, "GRIP_LOAD", mesh.load_nodes)
    lines.extend(
        [
            f"*MATERIAL,NAME={MATERIAL_NAME}",
            "*ELASTIC",
            f"{YOUNGS_MODULUS_MPA:.12g},{POISSON_RATIO:.12g}",
            f"*SOLID SECTION,ELSET=EALL,MATERIAL={MATERIAL_NAME}",
            "*BOUNDARY",
            "WALL_SUPPORT,1,3",
            "*STEP",
            "*STATIC,SOLVER=ITERATIVE CHOLESKY",
            "*CLOAD",
        ]
    )
    per_node_y = force_y_n / len(mesh.load_nodes)
    per_node_z = force_z_n / len(mesh.load_nodes)
    for node in mesh.load_nodes:
        lines.append(f"{node},2,{per_node_y:.12g}")
        lines.append(f"{node},3,{per_node_z:.12g}")
    lines.extend(
        [
            "*NODE PRINT,NSET=NALL",
            "U",
            "*NODE PRINT,NSET=WALL_SUPPORT,TOTALS=ONLY",
            "RF",
            "*EL PRINT,ELSET=EALL",
            "S",
            "*NODE FILE",
            "U",
            "*EL FILE",
            "S",
            "*END STEP",
        ]
    )
    input_path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return input_path


def _numbers(line: str) -> list[float]:
    return [float(value) for value in _FLOAT_PATTERN.findall(line)]


def _von_mises(values: list[float]) -> float:
    sxx, syy, szz, sxy, sxz, syz = values
    return math.sqrt(
        0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
        + 3.0 * (sxy**2 + sxz**2 + syz**2)
    )


def parse_dat(path: Path) -> dict[str, Any]:
    displacement: list[tuple[float, int]] = []
    stress: list[tuple[float, int, int]] = []
    reaction: tuple[float, float, float] | None = None
    section: str | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        lowered = line.lower()
        if "displacements (vx,vy,vz)" in lowered:
            section = "displacement"
            displacement = []
            continue
        if "total force (fx,fy,fz) for set wall_support" in lowered:
            section = "reaction"
            reaction = None
            continue
        if "stresses (elem, integ.pnt." in lowered:
            section = "stress"
            stress = []
            continue
        values = _numbers(line)
        if section == "displacement" and len(values) == 4:
            magnitude = math.sqrt(sum(value * value for value in values[1:]))
            displacement.append((magnitude, int(values[0])))
        elif section == "stress" and len(values) >= 8:
            stress.append((_von_mises(values[2:8]), int(values[0]), int(values[1])))
        elif section == "reaction" and len(values) == 3:
            reaction = (values[0], values[1], values[2])
    if not displacement or not stress or reaction is None:
        raise RuntimeError(f"could not parse complete CalculiX results from {path}")
    max_displacement, displacement_node = max(displacement)
    max_stress, stress_element, _integration_point = max(stress)
    return {
        "max_displacement_mm": max_displacement,
        "max_displacement_node": displacement_node,
        "max_von_mises_mpa": max_stress,
        "max_von_mises_element": stress_element,
        "reaction_force_n": reaction,
    }

def _element_centroid(mesh: MeshData, element_id: int) -> tuple[float, float, float]:
    found = next(element for element in mesh.tetrahedra if element[0] == element_id)
    points = [mesh.nodes[node] for node in found[1:]]
    return (
        sum(point[0] for point in points) / 4.0,
        sum(point[1] for point in points) / 4.0,
        sum(point[2] for point in points) / 4.0,
    )




def _classify_location(point: tuple[float, float, float]) -> str:
    x, y, z = point
    if abs(abs(x) - 55.0) < 8.0 and y < 4.0:
        return "mounting-ear wall face / countersunk-hole region"
    if abs(abs(x) - 50.0) < 8.0 and y < 16.0:
        return "grip-to-mounting-ear transition"
    if abs(x) < 15.0:
        return "central grip"
    return "arched grip"


def _render_von_mises(
    *, frd_path: Path, png_path: Path, deformation_scale: float
) -> None:
    from ccx2paraview import Converter

    Converter(str(frd_path), ["vtu"]).run()
    candidates = sorted(frd_path.parent.glob(f"{frd_path.stem}*.vtu"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if not candidates:
        raise RuntimeError(f"ccx2paraview created no VTU file for {frd_path}")
    vtu_path = candidates[0]
    vtk = _import_vtk()
    reader = vtk.vtkXMLUnstructuredGridReader()
    reader.SetFileName(str(vtu_path))
    reader.Update()
    dataset = reader.GetOutput()
    point_data = dataset.GetPointData()
    stress_name = "S_Mises" if point_data.HasArray("S_Mises") else "S_Mises_Magnitude"
    displacement_name = "U" if point_data.HasArray("U") else "DISP"
    if not point_data.HasArray(stress_name) or not point_data.HasArray(displacement_name):
        names = [point_data.GetArrayName(index) for index in range(point_data.GetNumberOfArrays())]
        raise RuntimeError(f"VTU has no expected fields: {names}")
    warp = vtk.vtkWarpVector()
    warp.SetInputData(dataset)
    warp.SetInputArrayToProcess(0, 0, 0, 0, displacement_name)
    warp.SetScaleFactor(float(deformation_scale))
    warp.Update()
    surface = vtk.vtkDataSetSurfaceFilter()
    surface.SetInputData(warp.GetOutput())
    surface.Update()
    array = warp.GetOutput().GetPointData().GetArray(stress_name)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(surface.GetOutputPort())
    mapper.SetScalarModeToUsePointFieldData()
    mapper.SelectColorArray(stress_name)
    mapper.SetScalarRange(array.GetRange())
    lookup = vtk.vtkLookupTable()
    lookup.SetHueRange(0.667, 0.0)
    lookup.SetNumberOfTableValues(256)
    lookup.Build()
    mapper.SetLookupTable(lookup)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    scalar_bar = vtk.vtkScalarBarActor()
    scalar_bar.SetLookupTable(lookup)
    scalar_bar.SetTitle("von Mises [MPa]")
    scalar_bar.SetNumberOfLabels(5)
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.96, 0.97, 0.98)
    renderer.AddActor(actor)
    renderer.AddViewProp(scalar_bar)
    renderer.ResetCamera()
    camera = renderer.GetActiveCamera()
    camera.Azimuth(35.0)
    camera.Elevation(22.0)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(1280, 900)
    window.AddRenderer(renderer)
    window.Render()
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGBA()
    capture.ReadFrontBufferOff()
    capture.Update()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(png_path))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    if not png_path.is_file() or png_path.stat().st_size <= 0:
        raise RuntimeError(f"failed to write stress preview: {png_path}")


def run_case(*, mesh: MeshData, case_name: str, force_y_n: float, force_z_n: float, ccx: Path) -> CaseResult:
    input_path = write_calculix_input(
        mesh=mesh,
        case_name=case_name,
        force_y_n=force_y_n,
        force_z_n=force_z_n,
    )
    completed = subprocess.run(
        [str(ccx), input_path.stem],
        cwd=OUTPUT_DIR,
        capture_output=True,
        text=True,
        check=False,
        timeout=1_200,
    )
    log_path = input_path.with_suffix(".ccx.log")
    log_path.write_text((completed.stdout or "") + "\n" + (completed.stderr or ""), encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"CalculiX {case_name} failed; see {log_path}")
    dat_path = input_path.with_suffix(".dat")
    frd_path = input_path.with_suffix(".frd")
    if not dat_path.is_file() or not frd_path.is_file():
        raise RuntimeError(f"CalculiX {case_name} produced incomplete results")
    parsed = parse_dat(dat_path)
    centroid = _element_centroid(mesh, int(parsed["max_von_mises_element"]))
    png_path = OUTPUT_DIR / f"arc_handle_{case_name}_von_mises.png"
    amplified_png_path = OUTPUT_DIR / f"arc_handle_{case_name}_von_mises_20x.png"
    _render_von_mises(frd_path=frd_path, png_path=png_path, deformation_scale=1.0)
    _render_von_mises(
        frd_path=frd_path,
        png_path=amplified_png_path,
        deformation_scale=20.0,
    )
    reaction = tuple(float(value) for value in parsed["reaction_force_n"])
    return CaseResult(
        name=case_name,
        force_y_n=force_y_n,
        force_z_n=force_z_n,
        resultant_force_n=math.hypot(force_y_n, force_z_n),
        input_path=str(input_path),
        dat_path=str(dat_path),
        frd_path=str(frd_path),
        png_path=str(png_path),
        max_displacement_mm=float(parsed["max_displacement_mm"]),
        max_displacement_node=int(parsed["max_displacement_node"]),
        max_von_mises_mpa=float(parsed["max_von_mises_mpa"]),
        max_von_mises_element=int(parsed["max_von_mises_element"]),
        max_von_mises_centroid_mm=centroid,
        stress_location=_classify_location(centroid),
        reaction_force_n=(float(reaction[0]), float(reaction[1]), float(reaction[2])),
        balance_error_y_n=reaction[1] + force_y_n,
        balance_error_z_n=reaction[2] + force_z_n,
        amplified_png_path=str(amplified_png_path),
    )


def main(*, mesh_size_mm: float, ccx: Path) -> None:
    mesh = mesh_handle(mesh_size_mm=mesh_size_mm)
    results = [
        run_case(
            mesh=mesh,
            case_name=name,
            force_y_n=force_y_n,
            force_z_n=force_z_n,
            ccx=ccx,
        )
        for name, force_y_n, force_z_n in CASE_DEFINITIONS
    ]
    payload = {
        "analysis": "linear_static",
        "units": {"length": "mm", "force": "N", "stress": "MPa"},
        "assumptions": {
            "material": {
                "name": MATERIAL_NAME,
                "youngs_modulus_mpa": YOUNGS_MODULUS_MPA,
                "poisson_ratio": POISSON_RATIO,
                "scope": "isotropic FDM PVC proxy; no print-orientation, infill, layer-adhesion, creep, or failure model",
            },
            "support": "both mounting-ear back faces at Y=-2.5 mm fixed in X, Y, and Z",
            "load": "uniform nodal force over exposed central 20 mm-wide grip surface region",
        },
        "mesh": json.loads(MESH_REPORT_PATH.read_text(encoding="utf-8")),
        "cases": [asdict(result) for result in results],
    }
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for result in results:
        print("case", result.name)
        print("  force_n", f"Fy={result.force_y_n:.3f}", f"Fz={result.force_z_n:.3f}", f"resultant={result.resultant_force_n:.3f}")
        print("  max_von_mises_mpa", f"{result.max_von_mises_mpa:.6f}")
        print("  max_displacement_mm", f"{result.max_displacement_mm:.6f}")
        print("  location", result.stress_location, tuple(round(value, 3) for value in result.max_von_mises_centroid_mm))
        print("  balance_error_n", f"Fy={result.balance_error_y_n:.6g}", f"Fz={result.balance_error_z_n:.6g}")
        print("  stress_png", result.png_path)
    print("summary", SUMMARY_PATH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh-size", type=float, default=0.9)
    parser.add_argument("--ccx", type=Path, default=Path("/opt/homebrew/bin/ccx_2.23"))
    arguments = parser.parse_args()
    main(mesh_size_mm=arguments.mesh_size, ccx=arguments.ccx)
