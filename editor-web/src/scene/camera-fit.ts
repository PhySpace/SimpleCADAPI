/** Pure camera-fit math (no three.js objects), shared by the viewer's FIT / first framing and by the overlays that
 * want "the distance at which the model fills the view". */

/** The default margin around the model's bounding sphere: the sphere fills 1 / 1.15 of the narrower view angle. */
export const FIT_MARGIN = 1.15;

/** The horizontal field of view (radians) of a perspective camera. */
export function horizontalFov(verticalFov: number, aspect: number): number {
  return 2 * Math.atan(Math.tan(verticalFov / 2) * aspect);
}

/** The camera distance from the sphere's centre at which a sphere of `radius` is fully inside the view, with
 * `margin` (1.15 = 15 % of air) around it, for a vertical field of view in radians and width/height `aspect`.
 * The sphere is tangent to the view cone of the NARROWER of the two angles, so a tall, narrow viewport frames
 * the model as well as a wide one. */
export function fitDistance(radius: number, verticalFov: number, aspect: number, margin = FIT_MARGIN): number {
  const half = Math.min(verticalFov, horizontalFov(verticalFov, Math.max(aspect, 1e-6))) / 2;
  return (Math.max(radius, 0) * margin) / Math.sin(half);
}
