import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

/** The side panels leave to the left and the right, the other mode's arrive from there: out, swap, then in. */
export type ModePhase = "idle" | "out" | "pre" | "in";

export const OUT_MS = 230;
export const IN_MS = 330;
const EASE_OUT = "cubic-bezier(0.55, 0, 0.9, 0.35)"; // leaving: slow start, then away
const EASE_IN = "cubic-bezier(0.12, 0.85, 0.25, 1)"; // arriving: fast, settling

/** The transform of a side panel in a phase; `side` is -1 for the left panel and 1 for the right one. Nothing is set when idle. */
export function sideStyle(phase: ModePhase, side: -1 | 1): CSSProperties | undefined {
  const away = `translateX(${side * 108}%)`;
  switch (phase) {
    case "out":
      return { transform: away, transition: `transform ${OUT_MS}ms ${EASE_OUT}`, willChange: "transform" };
    case "pre":
      return { transform: away, transition: "none", willChange: "transform" };
    case "in":
      return { transform: "translateX(0)", transition: `transform ${IN_MS}ms ${EASE_IN}`, willChange: "transform" };
    default:
      return undefined;
  }
}

/** Run a mode change with the panel animation; `swap` is called when both panels are out of sight (change what they show there).
 * A change asked for during a change is ignored; with reduced motion it happens at once. */
export function useModeTransition(swap: (target: string) => void) {
  const [phase, setPhase] = useState<ModePhase>("idle");
  const busy = useRef(false);
  const timers = useRef<number[]>([]);
  const swapRef = useRef(swap);
  swapRef.current = swap;

  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), []);

  const go = useCallback((target: string) => {
    if (busy.current) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      swapRef.current(target);
      return;
    }
    busy.current = true;
    setPhase("out");
    timers.current.push(
      window.setTimeout(() => {
        swapRef.current(target);
        setPhase("pre");
        // two frames: the swapped panels must be laid out off-screen before they are told to come in
        requestAnimationFrame(() =>
          requestAnimationFrame(() => {
            setPhase("in");
            timers.current.push(
              window.setTimeout(() => {
                setPhase("idle");
                busy.current = false;
              }, IN_MS + 30),
            );
          }),
        );
      }, OUT_MS + 20),
    );
  }, []);

  return { phase, go, moving: phase !== "idle" };
}
