import { Circle, CornerRightUp, Waves, Crosshair, MousePointer2, Radius, Scissors, Slash, Spline, Trash2, UnfoldHorizontal } from "lucide-react";

import type { ConstraintKind } from "@/lib/sketch";
import type { Tool } from "@/lib/useSketchEditor";

/** The drawing tools: `name` on the button, `label` its tooltip (both English keys of the translation table). */
export const TOOLS: { id: Tool; name: string; label: string; key: string; icon: typeof Slash }[] = [
  { id: "select", name: "select", label: "Select / move", key: "V", icon: MousePointer2 },
  { id: "point", name: "point", label: "Point", key: "P", icon: Crosshair },
  { id: "line", name: "line", label: "Line (chained; Esc ends)", key: "L", icon: Slash },
  { id: "circle", name: "circle", label: "Circle: centre, then radius", key: "C", icon: Circle },
  { id: "arc", name: "arc", label: "Arc: centre, start, end (counter-clockwise)", key: "A", icon: Spline },
  { id: "spline", name: "spline", label: "Spline (pen): click anchors, press and drag for handles, click another spline's curve to add an anchor there; Enter makes it, a click on the first anchor closes it (SDK add_bspline_rsketch, anchor form)", key: "B", icon: Waves },
  { id: "delete", name: "delete", label: "Delete", key: "D", icon: Trash2 },
  { id: "trim", name: "trim", label: "Trim: cut an entity back to its neighbours (SDK trim_rsketch)", key: "T", icon: Scissors },
  { id: "extend", name: "extend", label: "Extend: grow a line's end to the next entity (SDK extend_rsketch)", key: "E", icon: UnfoldHorizontal },
  { id: "fillet", name: "fillet", label: "Fillet corner: round a corner of two lines with an arc (SDK fillet_corner_rsketch)", key: "R", icon: Radius },
  { id: "chamfer", name: "chamfer", label: "Chamfer corner: cut a corner of two lines with a straight edge (SDK chamfer_corner_rsketch)", key: "H", icon: CornerRightUp },
];

export const CONSTRAINT_SHORT: Record<ConstraintKind, string> = {
  fix: "fix", coincident: "coinc", point_on: "on", horizontal: "horiz", vertical: "vertical", points_horizontal: "align h", points_vertical: "align v",
  parallel: "para", perpendicular: "perp", collinear: "colin", tangent: "tang", concentric: "conc", midpoint: "mid", symmetric: "sym",
  equal_length: "= len", equal_radius: "= rad", length: "length", distance: "dist", distance_x: "dist x", distance_y: "dist y",
  line_distance: "line dist", angle: "angle", radius: "radius", diameter: "diam",
};

export const TOOLBAR_ORDER: ConstraintKind[] = [
  "horizontal", "vertical", "points_horizontal", "points_vertical", "coincident", "point_on", "midpoint", "parallel", "perpendicular", "collinear", "tangent",
  "concentric", "equal_length", "equal_radius", "symmetric", "fix", "length", "distance", "distance_x", "distance_y", "line_distance", "angle", "radius", "diameter",
];
