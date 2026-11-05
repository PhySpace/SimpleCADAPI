/** Level of detail for the preview's parts.  A part arrives tessellated coarsely (fast to make and send); a part seen up
 * close is tessellated again by the kernel (`POST /api/preview/refine`) until its chords deviate from the true surface
 * and edges by less than about half a pixel.  The topology does not change between levels, so entities, picks and
 * highlights keep their names; only the triangles and edge polylines get denser.
 *
 * Levels only go up while a model is on screen (a part seen up close once stays fine): coming back costs nothing, and a
 * new model starts at level 0 again. */

/** Tessellation tolerances per level: linear in mm, angular in radians.  Level 0 is what the kernel previews with. */
export const LOD_LEVELS: readonly { linear: number; angular: number }[] = [
  { linear: 0.35, angular: 0.22 },
  { linear: 0.1, angular: 0.1 },
  { linear: 0.03, angular: 0.05 },
  { linear: 0.01, angular: 0.025 },
];

/** The deviation aimed at, in pixels. */
export const TARGET_PIXELS = 0.5;

/** No part is refined past this many triangles (a level about doubles them). */
export const MAX_PART_TRIANGLES = 1_500_000;

/** The level whose linear tolerance stays under TARGET_PIXELS at `mmPerPixel` (the size of a pixel on the part). */
export function levelFor(mmPerPixel: number): number {
  const allowed = mmPerPixel * TARGET_PIXELS;
  for (let level = 0; level < LOD_LEVELS.length; level++) if (LOD_LEVELS[level].linear <= allowed) return level;
  return LOD_LEVELS.length - 1;
}

/** The highest level up to `wanted` that keeps a part of `triangles` (at `current`) under MAX_PART_TRIANGLES. */
export function cappedLevel(wanted: number, current: number, triangles: number): number {
  let level = wanted;
  while (level > current && triangles * 2 ** (level - current) > MAX_PART_TRIANGLES) level--;
  return level;
}

/** The size of one pixel, in mm, at `distance` (scene metres) from a perspective camera of vertical `fovDeg` drawing
 * `heightPx` pixels high. */
export function mmPerPixel(distance: number, fovDeg: number, heightPx: number): number {
  return (2 * distance * Math.tan((fovDeg * Math.PI) / 360) * 1000) / Math.max(heightPx, 1);
}
