import { useEffect, useLayoutEffect, useRef } from "react";

const EASE = "cubic-bezier(0.2, 0, 0, 1)";

/** A box that changes what it shows on `state` (a card folding into its pill and back) grows or shrinks from the size it
 * had to the size it gets, and its new content fades in, instead of jumping.  The size before is the one last seen by a
 * ResizeObserver, so a change in the middle of a transition starts from where the box is on screen. */
export function useSizeTransition<T extends HTMLElement>(state: unknown, ms = 220) {
  const ref = useRef<T>(null);
  const seen = useRef<{ width: number; height: number } | null>(null);
  const shown = useRef(state);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(() => {
      const box = element.getBoundingClientRect();
      seen.current = { width: box.width, height: box.height };
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || shown.current === state) return;
    shown.current = state;
    const before = seen.current;
    const after = element.getBoundingClientRect();
    seen.current = { width: after.width, height: after.height };
    if (!before || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    element.getAnimations().forEach((animation) => animation.cancel());
    element.animate(
      [
        { width: `${before.width}px`, height: `${before.height}px` },
        { width: `${after.width}px`, height: `${after.height}px` },
      ],
      { duration: ms, easing: EASE },
    );
    for (const child of element.children) child.animate([{ opacity: 0 }, { opacity: 1 }], { duration: ms, easing: "ease-out" });
  }, [state, ms]);

  return ref;
}
