import * as THREE from 'three';

type ClickSelectionControls = {
  target: THREE.Vector3;
  update(): void;
};

type ClickSelectionOptions = {
  element: HTMLElement;
  camera: THREE.PerspectiveCamera;
  controls: ClickSelectionControls;
  movementThreshold?: number;
  onPointerStateChange?: (active: boolean) => void;
  onClick: (event: PointerEvent) => void;
};

export function bindClickSelection(options: ClickSelectionOptions): () => void {
  const { element, camera, controls, onClick, movementThreshold = 4 } = options;
  let pointerDown: {
    x: number;
    y: number;
    button: number;
    position: THREE.Vector3;
    up: THREE.Vector3;
    target: THREE.Vector3;
    zoom: number;
  } | null = null;

  const onPointerDown = (event: PointerEvent): void => {
    pointerDown = {
      x: event.clientX,
      y: event.clientY,
      button: event.button,
      position: camera.position.clone(),
      up: camera.up.clone(),
      target: controls.target.clone(),
      zoom: camera.zoom,
    };
    options.onPointerStateChange?.(true);
  };
  const onPointerUp = (event: PointerEvent): void => {
    const down = pointerDown;
    pointerDown = null;
    options.onPointerStateChange?.(false);
    if (!down || down.button !== 0 || event.button !== 0) return;
    if (Math.hypot(event.clientX - down.x, event.clientY - down.y) > movementThreshold) return;

    // The controls may have applied pointer movement between down and up
    // (turntable damping, trackball momentum). Drain it, then restore the
    // click-time camera — position and orientation — before picking.
    controls.update();
    camera.position.copy(down.position);
    camera.up.copy(down.up);
    camera.zoom = down.zoom;
    camera.updateProjectionMatrix();
    controls.target.copy(down.target);
    controls.update();
    onClick(event);
  };
  const onPointerLeave = (): void => {
    pointerDown = null;
    options.onPointerStateChange?.(false);
  };

  element.addEventListener('pointerdown', onPointerDown);
  element.addEventListener('pointerup', onPointerUp);
  element.addEventListener('pointerleave', onPointerLeave);
  return () => {
    element.removeEventListener('pointerdown', onPointerDown);
    element.removeEventListener('pointerup', onPointerUp);
    element.removeEventListener('pointerleave', onPointerLeave);
  };
}
