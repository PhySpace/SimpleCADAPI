import { useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";

export type DragOffset = { x: number; y: number };

/** Drag a floating element by a handle: the element keeps its CSS position and is moved with a transform.
 *
 * `handleProps` go on the grab area (a header); `style` goes on the element.  The element is kept inside the window (at least `keep`
 * pixels of it stay visible on every side), a double click on the handle puts it back, and buttons or fields inside the handle
 * still work (a drag starts only on the handle's own surface or its text).  The offset lives in the hook: unmounting resets it. */
export function useDraggable(keep = 48) {
  const [offset, setOffset] = useState<DragOffset>({ x: 0, y: 0 });
  const element = useRef<HTMLElement | null>(null);
  const drag = useRef<{ startX: number; startY: number; from: DragOffset; left: number; top: number; width: number; height: number } | null>(null);

  const ref = useCallback((node: HTMLElement | null) => {
    element.current = node;
  }, []);

  const move = useCallback(
    (event: PointerEvent) => {
      const d = drag.current;
      if (!d) return;
      const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));
      const dx = clamp(event.clientX - d.startX, keep - d.left - d.width, window.innerWidth - keep - d.left);
      const dy = clamp(event.clientY - d.startY, -d.top, window.innerHeight - keep - d.top);
      setOffset({ x: d.from.x + dx, y: d.from.y + dy });
    },
    [keep],
  );
  const end = useCallback(() => {
    drag.current = null;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", end);
  }, [move]);
  useEffect(() => end, [end]);

  const onPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      if (event.button !== 0) return;
      const target = event.target as HTMLElement;
      if (target.closest("button, input, select, textarea, a, [role=switch], [role=slider], [data-no-drag]")) return;
      const node = element.current;
      if (!node) return;
      const box = node.getBoundingClientRect();
      drag.current = { startX: event.clientX, startY: event.clientY, from: offset, left: box.left - offset.x, top: box.top - offset.y, width: box.width, height: box.height };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", end);
      event.preventDefault();
    },
    [offset, move, end],
  );

  const handleProps = {
    onPointerDown,
    onDoubleClick: () => setOffset({ x: 0, y: 0 }),
    title: "Drag to move (double-click to put it back)",
    style: { cursor: "grab", touchAction: "none" } as CSSProperties,
  };
  const style: CSSProperties = offset.x || offset.y ? { transform: `translate(${offset.x}px, ${offset.y}px)` } : {};
  return { ref, handleProps, style, offset };
}
