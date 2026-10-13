import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/** Cells of the 3x3 spinner that form its ring, clockwise from the top left. */
const RING = [0, 1, 2, 5, 8, 7, 6, 3];

const STEP = 8; // dot pitch, CSS px
const DOT = 2; // dot size, CSS px
/** Dot brightness in four steps (a 2-bit look), kept low: the veil should sit
 * behind the window, not compete with it. The brightest step is the crest. */
const LEVELS = [0.03, 0.075, 0.13, 0.22];
/** One long swell: wavelength 2π/WAVE_NUMBER ≈ 780 px, a period of ≈ 7 s. */
const WAVE_NUMBER = 0.008;
const WAVE_SPEED = 0.0009;

/** A gray veil over the whole workspace while the model is being made: a
 * dot-matrix with a ripple that spreads from the middle, and a small retro
 * window saying what is going on and for how long.  It appears only after
 * `DELAY_MS`, so quick operations do not flash it. */
export function LoadingMask({ active, message, theme }: { active: boolean; message: string; theme: string }) {
  const DELAY_MS = 250;
  const [visible, setVisible] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!active) {
      setVisible(false);
      setElapsed(0);
      return;
    }
    const started = Date.now();
    const show = window.setTimeout(() => setVisible(true), DELAY_MS);
    const tick = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 500);
    return () => {
      window.clearTimeout(show);
      window.clearInterval(tick);
    };
  }, [active]);

  if (!visible) return null;
  const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const seconds = String(elapsed % 60).padStart(2, "0");
  return (
    <div
      role="status"
      aria-live="polite"
      className="absolute inset-0 z-50 flex cursor-progress items-center justify-center bg-overlay"
    >
      <Ripple theme={theme} />
      <div className="relative w-[280px] border-2 border-foreground/80 bg-background shadow-[6px_6px_0_0_var(--shadow-hard)]">
        <div className="flex h-6 items-center justify-between bg-foreground/85 px-2 text-[11px] font-bold uppercase tracking-[0.18em] text-background">
          <span>loading</span>
          <span className="tabular-nums">
            {minutes}:{seconds}
          </span>
        </div>
        <div className="flex items-center gap-4 px-4 py-4">
          <Spinner />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[12px] uppercase tracking-[0.1em] text-foreground" title={message}>
              {message}
            </p>
            <p className="mt-1 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              please wait<span className="sca-blink">_</span>
            </p>
          </div>
        </div>
        <Progress />
      </div>
    </div>
  );
}

/** Eight squares chasing each other round a ring. */
function Spinner() {
  return (
    <div className="grid h-[34px] w-[34px] shrink-0 grid-cols-3 grid-rows-3 gap-[3px]" aria-hidden>
      {Array.from({ length: 9 }, (_, cell) => {
        const order = RING.indexOf(cell);
        return (
          <span
            key={cell}
            className={cn("block bg-foreground", order < 0 && "invisible", order >= 0 && "sca-chase")}
            style={order >= 0 ? { animationDelay: `${order * 0.1}s` } : undefined}
          />
        );
      })}
    </div>
  );
}

/** A strip of blocks filling and emptying: the load has no known length. */
function Progress() {
  return (
    <div className="flex gap-[3px] border-t-2 border-foreground px-2 py-1.5" aria-hidden>
      {Array.from({ length: 20 }, (_, index) => (
        <span key={index} className="sca-bar block h-[6px] flex-1 bg-foreground" style={{ animationDelay: `${index * 0.07}s` }} />
      ))}
    </div>
  );
}

/** A CSS color variable of the page (a #rrggbb token) as "r,g,b", for drawing on a canvas. */
function cssRgb(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const match = /^#([0-9a-f]{6})$/i.exec(value);
  if (!match) return fallback;
  const n = parseInt(match[1], 16);
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`;
}

/** The dot-matrix: square dots whose brightness follows a ring-shaped wave
 * travelling out from the middle, quantised to four levels. */
function Ripple({ theme }: { theme: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // The dots take the theme's ink: the crest is the focus color, the rest the foreground.
  const inks = useRef({ crest: "255,154,46", base: "255,255,255" });
  useEffect(() => {
    inks.current = { crest: cssRgb("--focus", "255,154,46"), base: cssRgb("--foreground", "255,255,255") };
  }, [theme]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let width = 0;
    let height = 0;
    let frame = 0;
    let last = 0;

    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.max(1, Math.round(width * ratio));
      canvas.height = Math.max(1, Math.round(height * ratio));
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };

    const draw = (time: number) => {
      context.clearRect(0, 0, width, height);
      const cx = width / 2;
      const cy = height / 2;
      const reach = Math.hypot(cx, cy);
      const paths = LEVELS.map(() => new Path2D());
      for (let y = STEP / 2; y < height; y += STEP) {
        for (let x = STEP / 2; x < width; x += STEP) {
          const distance = Math.hypot(x - cx, y - cy);
          // a long swell spreading outwards, fading gently with distance
          const wave = (Math.sin(distance * WAVE_NUMBER - time * WAVE_SPEED) + 1) / 2;
          const strength = wave * (1 - 0.4 * Math.min(distance / reach, 1));
          const level = Math.min(LEVELS.length - 1, Math.floor(strength * LEVELS.length));
          paths[level].rect(x - DOT / 2, y - DOT / 2, DOT, DOT);
        }
      }
      paths.forEach((path, level) => {
        context.fillStyle = `rgba(${level === LEVELS.length - 1 ? inks.current.crest : inks.current.base},${LEVELS[level]})`;
        context.fill(path);
      });
    };

    const loop = (time: number) => {
      if (time - last > 42) {
        last = time;
        draw(time);
      }
      frame = window.requestAnimationFrame(loop);
    };

    resize();
    const observer = new ResizeObserver(() => {
      resize();
      if (still) draw(0);
    });
    observer.observe(canvas);
    if (still) draw(0);
    else frame = window.requestAnimationFrame(loop);
    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  return <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" aria-hidden />;
}
