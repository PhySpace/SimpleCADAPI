import { ArrowDownToLine, ArrowUpFromLine, Boxes, Code, MoveVertical, PenLine, Repeat2, ScanBox, Blend, Box, CircleDot, Combine, Copy, Cylinder, FlipHorizontal2, Globe, Move3d, RotateCw, Scaling, Scissors, Shell, Spline, Square, Triangle, type LucideIcon } from "lucide-react";

/** The icon of each feature operation, by spec id (an operation without one shows none). */
export const FEATURE_ICONS: Record<string, LucideIcon> = {
  box: Box,
  workplane: Square,
  workplane_from_selection: Square,
  sketch: PenLine,
  extrude_sketch: ArrowUpFromLine,
  boss_sketch: ArrowUpFromLine,
  cut_sketch: ArrowDownToLine,
  revolve_sketch: Repeat2,
  curve: Spline,
  wire: Spline,
  assembly: Boxes,
  cylinder: Cylinder,
  sphere: Globe,
  cone: Triangle,
  cut: Scissors,
  union: Combine,
  intersect: Combine,
  hole: CircleDot,
  extrude_face: ArrowUpFromLine,
  extrude_face_join: ArrowUpFromLine,
  extrude_face_cut: ArrowDownToLine,
  press_pull: MoveVertical,
  inset_face: ScanBox,
  extrude_sketch_join: ArrowUpFromLine,
  extrude_sketch_cut: ArrowDownToLine,
  fillet: Blend,
  chamfer: Triangle,
  shell: Shell,
  linear_pattern: Copy,
  radial_pattern: RotateCw,
  mirror: FlipHorizontal2,
  translate: Move3d,
  rotate: RotateCw,
  scale: Scaling,
};


/** A feature written as code (no operation of the catalog behind it). */
export const CODE_FEATURE_ICON: LucideIcon = Code;
