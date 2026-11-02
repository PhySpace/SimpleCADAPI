import { Circle, CornerRightUp, Crosshair, MousePointer2, Radius, Scissors, Slash, Spline, Trash2, UnfoldHorizontal } from "lucide-react";

import type { ConstraintKind } from "@/lib/sketch";
import type { Tool } from "@/lib/useSketchEditor";

export const TOOLS: { id: Tool; label: string; key: string; icon: typeof Slash }[] = [
  { id: "select", label: "Select / move", key: "V", icon: MousePointer2 },
  { id: "point", label: "Point", key: "P", icon: Crosshair },
  { id: "line", label: "Line (chained; Esc ends)", key: "L", icon: Slash },
  { id: "circle", label: "Circle: centre, then radius", key: "C", icon: Circle },
  { id: "arc", label: "Arc: centre, start, end (counter-clockwise)", key: "A", icon: Spline },
  { id: "delete", label: "Delete", key: "D", icon: Trash2 },
  { id: "trim", label: "Trim: cut an entity back to its neighbours (SDK trim_rsketch)", key: "T", icon: Scissors },
  { id: "extend", label: "Extend: grow a line's end to the next entity (SDK extend_rsketch)", key: "E", icon: UnfoldHorizontal },
  { id: "fillet", label: "Fillet corner: round a corner of two lines with an arc (SDK fillet_corner_rsketch)", key: "R", icon: Radius },
  { id: "chamfer", label: "Chamfer corner: cut a corner of two lines with a straight edge (SDK chamfer_corner_rsketch)", key: "H", icon: CornerRightUp },
];

export const CONSTRAINT_SHORT: Record<ConstraintKind, string> = {
  fix: "fix", coincident: "coinc", point_on: "on", horizontal: "horiz", vertical: "vert", points_horizontal: "align h", points_vertical: "align v",
  parallel: "para", perpendicular: "perp", collinear: "colin", tangent: "tang", concentric: "conc", midpoint: "mid", symmetric: "sym",
  equal_length: "= len", equal_radius: "= rad", length: "length", distance: "dist", distance_x: "dist x", distance_y: "dist y",
  line_distance: "line dist", angle: "angle", radius: "radius", diameter: "diam",
};

export const TOOLBAR_ORDER: ConstraintKind[] = [
  "horizontal", "vertical", "points_horizontal", "points_vertical", "coincident", "point_on", "midpoint", "parallel", "perpendicular", "collinear", "tangent",
  "concentric", "equal_length", "equal_radius", "symmetric", "fix", "length", "distance", "distance_x", "distance_y", "line_distance", "angle", "radius", "diameter",
];
