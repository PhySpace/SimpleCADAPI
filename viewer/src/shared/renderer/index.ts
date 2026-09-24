// Standalone BRep renderer component — public entry point.
//
// Embed this to render a scene-2.0 package (faces + edges) with CAD-grade
// presentation: image-based studio lighting, GTAO ambient occlusion, free
// trackball camera, and toggleable seam/degenerate edge display. Selection
// and annotation are NOT part of this component; build them on top
// (reference implementation: src/scene-view.ts).

export {
  BRepRenderer,
  EDGE_LAYER,
  FACE_LAYER,
  OVERLAY_LAYER,
  type BRepRendererOptions,
  type CameraState,
} from './brep-renderer';
