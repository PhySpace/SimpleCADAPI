# Discipline: Verifier Scripts

A verifier script measures a finished model against the specification and exits
non-zero when a requirement fails. It is separate from the modeling script: it
imports the model, measures it independently, and prints one line per check.

## Evidence labels

- **SDK contract:** `simplecadapi.verify.to_ocp(shape)` returns an OCP
  `TopoDS_Shape` copy of any SDK shape; `from_ocp(shape)` returns the SDK shape
  of an OCP shape. `Solid.get_volume()`, `simplecadapi.inspect.brep` and QL
  need no extra install.
- **Validation guidance:** the checks and the skeleton below are
  recommendations, not SDK methods.

## Use the SDK first, OCP for the rest

Measure with the SDK where it can answer: `get_volume()`, QL for face and edge
facts, `inspect.brep` for validity and shell closure
(`references/discipline/geometric-validation.md`). Reach for OCP only for what
the SDK does not expose: point-in-solid classification, minimum distance
between shapes, Boolean overlap volume, mass-property centroids and inertia.

The SDK itself does not use OCP. Install it for verifier scripts only:

```bash
pip install "simplecadapi[verify]"     # OCP 7.9, the OCCT generation the SDK ships
```

## `shape.wrapped` is an OCP shape (with the extra installed)

With OCP installed, `shape.wrapped` is an OCP shape of the class of its kind (`TopoDS_Solid`, `TopoDS_Face`, ...), so
OCP functions take it as written; `to_ocp` is the explicit form and returns the generic `TopoDS_Shape`:

```python
from simplecadapi.verify import to_ocp

BRepGProp.VolumeProperties_s(solid.wrapped, props)        # works
BRepGProp.VolumeProperties_s(to_ocp(solid), props)        # works
```

Either way it is a copy made through OpenCASCADE's binary format (milliseconds for a part): every `.wrapped` access
makes a new one, so convert once per shape and reuse the result; changes made to it do not reach the SDK shape, and tags
and tracking history stay on the SDK shape. An OCP shape you built yourself comes back with `from_ocp`. Without OCP
installed `.wrapped` is the SDK's own binding, which OCP functions reject (`incompatible function arguments`): install
the extra. `SCA_WRAPPED=native` forces the SDK's own binding.

The SDK's diagnostic functions (`inspect_shape_rbrepinspection`, ...) take an SDK shape's raw shape; they accept
either an OCP shape or the SDK's own, so a result of OCP code can be passed to them directly.

## Recipes (OCP 7.9)

```python
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_IN
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt


def volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def bounds(shape):                      # (xmin, ymin, zmin, xmax, ymax, zmax)
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    return box.Get()


def is_valid(shape):
    return BRepCheck_Analyzer(shape).IsValid()


def contains(solid, x, y, z, tol=1e-6):  # solid: an OCP solid, see the cast below
    return BRepClass3d_SolidClassifier(solid, gp_Pnt(x, y, z), tol).State() == TopAbs_IN


def gap(a, b):                          # minimum distance, 0 when they touch or overlap
    measure = BRepExtrema_DistShapeShape(a, b)
    assert measure.IsDone()
    return measure.Value()


def overlap_volume(a, b):               # interference between two parts
    common = BRepAlgoAPI_Common(a, b)
    assert common.IsDone()
    return volume(common.Shape())
```

- `to_ocp` returns a generic `TopoDS_Shape`. Functions that need the concrete
  type want a cast: `TopoDS.Solid_s(to_ocp(solid))`.
- OCP 7.9 casts and static methods end in `_s` (`TopoDS.Solid_s`,
  `BRepGProp.VolumeProperties_s`). OCP 8 renames them; the `verify` extra pins
  7.9 so documentation and code agree.
- Do not guess OCP names. Open the class in the OCCT reference, or
  `help(OCP.<Module>.<Class>)`, before the first call (a method that is not in
  the documentation does not exist, however plausible it looks).

## Skeleton

```python
"""verify_bracket.py: exits 1 when a requirement is not met."""
import math
import sys

from simplecadapi.verify import to_ocp

from bracket import build           # the modeling script's result: a Solid

checks = []


def check(name, ok, detail=""):
    checks.append(ok)
    print(("PASS" if ok else "FAIL"), name, detail)


part = build()
shape = to_ocp(part)

check("valid", is_valid(shape))
check("volume 5151.77 mm3 +-0.1%", math.isclose(volume(shape), 5151.77, rel_tol=1e-3), f"{volume(shape):.2f}")
x0, y0, z0, x1, y1, z1 = bounds(shape)
check("height 30 mm", math.isclose(z1 - z0, 30.0, abs_tol=1e-6), f"{z1 - z0:.4f}")
check("bore is empty", not contains(TopoDS.Solid_s(shape), 0, 0, 15))

sys.exit(0 if all(checks) else 1)
```

Rules for a verifier:

- Every user-specified dimension gets its own targeted check with the measured
  value printed; "valid" alone proves nothing about size.
- Tolerances come from the specification, not from what happens to pass.
- A check that cannot run (missing OCP, unreadable file) is a failure, not a
  skip: report it and exit non-zero.
- Do not edit the model to make a check pass; fix the model or report the
  discrepancy.
