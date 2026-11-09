# make_ball_bearing_rassembly

## API Definition

```python
def make_ball_bearing_rassembly(bore_diameter: Length, outer_diameter: Length, bearing_width: Length, ball_diameter: Length, ball_count: Count | None = None, raceway_clearance: Length = 0.02, edge_chamfer: Length = 0.0, assembly_id: str = 'ball_bearing', drive_angle_degrees: Angle | None = None, fuse_rolling_elements: bool = False, rolling_element_fuse_overlap: Length = 0.01, material: Material | None = None) -> Assembly
```

*Source: std/bearing.py*

## Import Surface

- standard library: `import simplecadapi as scad` then `scad.std.bearing.make_ball_bearing_rassembly(...)`; direct submodule import: `from simplecadapi.std.bearing import make_ball_bearing_rassembly`

## Description

Create a parameterized radial ball bearing assembly.

With ``fuse_rolling_elements=False`` the factory returns separate
``outer_ring``, ``inner_ring``, and ``ball_*`` components.  With
``fuse_rolling_elements=True`` all rolling elements are translated to
their authored pitch positions and unioned into the outer-ring body using
normal boolean mode (``glue=False``).  The fused mode is intended for
simplified solver or export bodies; it deliberately embeds the balls into
the outer-race inner wall and therefore does not preserve the nominal
raceway clearance as a free gap.

``material`` is assigned to the generated ring and rolling-element parts.
