"""simplecadapi.dxf_engine — a declarative GB engineering-drawing engine.

Layers (the dimensioning mindset):
  model    declarations — views (and sections), datums, dimensions, centre lines, leaders, surface texture, the sheet
  refs     geometry references: what a dimension measures is taken from the model, not typed
  views    what a view shows: HLR edges, section cut and hatch loops, the axes of holes and shafts
  sheet    sheet format, frame, title block, standard scales, view arrangement
  bind     declared dimension → measured dimension and its text
  planner  the solver — views, row slots (small inside, large outside), minimum adjustment, GB rules R1-R7
  dims / leaders   placement of each element kind; collide: the one conflict test
  checks   the issues of a solved sheet (placement, truth, completeness, sheet, output) and what is not checked
  agent    evaluation, diagnostic picture and actions for an LLM in the loop
  hlr      OCCT hidden-line-removal projection (GB/T 4458.1)
  render   DXF with native DIMENSION entities (style "GB") + PNG, read back and verified

GB/T 4458.4-2003 dimensioning · GB/T 4457.4-2002 lines · GB/T 14692 projection · GB/T 17452 sections · GB/T 131 texture
"""
from .checks import Issue
from .model import (CenterDecl, DatumDecl, DimDecl, LeaderDecl, RoughDecl, SheetDecl,
                    ViewDecl)
from .planner import SheetPlan
from .refs import RefError

__all__ = ["SheetDecl", "ViewDecl", "DimDecl", "DatumDecl", "CenterDecl",
           "LeaderDecl", "RoughDecl", "SheetPlan", "Issue", "RefError"]
