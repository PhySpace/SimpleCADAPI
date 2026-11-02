import { Blend, Box, CircleDot, Circle, Combine, Copy, Cylinder, FlipHorizontal2, Globe, Layers, Move3d, RotateCw, Scaling, Scissors, Shell, Spline, Square, Triangle, type LucideIcon } from "lucide-react";

/** The icon of each feature operation, by spec id (an operation without one shows none). */
export const FEATURE_ICONS: Record<string, LucideIcon> = {
  box: Box,
  cylinder: Cylinder,
  sphere: Globe,
  cone: Triangle,
  extrude_rect: Square,
  extrude_circle: Circle,
  extrude_polygon: Layers,
  revolve: RotateCw,
  loft_circles: Layers,
  loft_rects: Layers,
  sweep_circle: Spline,
  cut: Scissors,
  union: Combine,
  intersect: Combine,
  hole: CircleDot,
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

