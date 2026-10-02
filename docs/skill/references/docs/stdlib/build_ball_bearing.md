# build_ball_bearing

## API Definition

```python
def build_ball_bearing(*, bore_diameter: float, outer_diameter: float, bearing_width: float, ball_diameter: float, ball_count: Optional[int] = None, raceway_clearance: float = 0.02, edge_chamfer: float = 0.0, assembly_id: str = 'std_ball_bearing', revision: str = '1.0.0', drive_angle_degrees: Optional[float] = None, fuse_rolling_elements: bool = True, rolling_element_fuse_overlap: float = 0.01, material: Optional[Material] = None, ground: Optional[str] = 'outer_ring')
```

*Source: std/bearing.py*

## Import Surface

- standard library: `import simplecadapi as scad` then `scad.std.bearing.build_ball_bearing(...)`; direct submodule import: `from simplecadapi.std.bearing import build_ball_bearing`

## Description

Build one ball bearing as a reusable durable sub-assembly definition.

Returns an ``AssemblyBuildResult`` whose definition re-declares the
standard library contract: public ``outer_axis``/``inner_axis`` connectors
over one internal ``inner_outer_revolute`` constraint, returned unsolved so
a parent assembly can drive both rings through external fixed constraints.
``ground`` selects the ring the nested definition grounds for its own
constraint solve (``"outer_ring"``, ``"inner_ring"``, or ``None``).
