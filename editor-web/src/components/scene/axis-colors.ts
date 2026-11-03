/** The universal axis colours, one module, NOT theme tokens: X red, Y green, Z blue.  Chosen to read on both the dark
 * and the light scene background and over the white-grey model; every axis drawing (connector frames, sketch plane
 * axes, datum triads) takes them from here. */

export const AXIS_X = '#e5484d';
export const AXIS_Y = '#30a46c';
export const AXIS_Z = '#3e63dd';
export const AXIS_COLORS = [AXIS_X, AXIS_Y, AXIS_Z] as const;
/** The thin dark outline drawn around every axis stroke so it stays visible over a white face. */
export const AXIS_OUTLINE = '#10131a';
/** The highlight (picker armed / hovered / selected) accent of a gizmo's ring and origin dot. */
export const AXIS_HIGHLIGHT = '#ffc53d';
