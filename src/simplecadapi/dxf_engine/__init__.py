"""simplecadapi.dxf_engine — a declarative GB engineering-drawing engine.

Layers (the dimensioning mindset):
  model    dimensioning semantics declarations — datum system / size·position·overall dimensions / parameter-coverage tracing
  planner  dimensioning-plan solver — view layout, row-slot allocation (small inside, large outside), minimum adjustment, GB rules R1-R7
  hlr      OCCT hidden-line-removal projection (GB/T 4458.1)
  render   hand-made primitive rendering — text parallel to the dimension line (heads up / left), solid arrows, thin solid lines

GB/T 4458.4-2003 dimensioning · GB/T 4457.4-2002 lines · GB/T 14692 projection
"""
from .model import (CenterDecl, DatumDecl, DimDecl, LeaderDecl, SheetDecl,
                    ViewDecl)
from .planner import SheetPlan

__all__ = ["SheetDecl", "ViewDecl", "DimDecl", "DatumDecl", "CenterDecl",
           "LeaderDecl", "SheetPlan"]
