import { ArrowDownToLine, ArrowUpFromLine, MoveVertical, ScanBox, Blend, Box, CircleDot, Circle, Combine, Copy, Cylinder, FlipHorizontal2, Globe, Layers, Move3d, RotateCw, Scaling, Scissors, Shell, Spline, Square, Triangle, type LucideIcon } from "lucide-react";

/** The icon of each feature operation, by spec id (an operation without one shows none). */
export const FEATURE_ICONS: Record<string, LucideIcon> = {
  box: Box,
  workplane: Square,
  workplane_from_selection: Square,
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

