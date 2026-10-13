/** The colors of the 3D scene in each theme.  The page's own colors are CSS variables
 * (src/index.css); the scene is drawn by three.js and needs its own copy. */
export type SceneTheme = 'light' | 'dark';

export interface ScenePalette {
  /** Viewport background, sRGB. */
  clear: string;
  /** Multiplier on the linear background: the present pass tone-maps it (ACES), which
   * leaves a pure white at about 0.9; a brighter input lands on the page's white. */
  clearBoost: number;
  /** Outline color of the model's edges. */
  edge: string;
  gridMinor: string;
  gridMajor: string;
  /** X, Y, Z. */
  axes: [string, string, string];
  /** The negative end of each axis. */
  axisTail: string;
  vertex: string;
  /** Highlight of picked entities. */
  selection: string;
}

export const PALETTES: Record<SceneTheme, ScenePalette> = {
  dark: {
    clear: '#000000',
    clearBoost: 1,
    edge: '#3a414d',
    gridMinor: '#262626',
    gridMajor: '#444444',
    axes: ['#ff4d5e', '#3ddc84', '#4aa3ff'],
    axisTail: '#555555',
    vertex: '#d8ff83',
    selection: '#ff9a2e',
  },
  light: {
    clear: '#ffffff',
    clearBoost: 8,
    edge: '#1b1f27',
    gridMinor: '#e0e0e0',
    gridMajor: '#bdbdbd',
    axes: ['#d12b3c', '#12803f', '#1a62c4'],
    axisTail: '#9a9a9a',
    vertex: '#2a7a00',
    selection: '#d56a00',
  },
};
