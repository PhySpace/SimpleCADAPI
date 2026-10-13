import { useCallback, useEffect, useState } from "react";

/** What the person chose; `system` follows the operating system. */
export type ThemePreference = "system" | "light" | "dark";
/** What is on screen. */
export type ResolvedTheme = "light" | "dark";

const KEY = "sca-theme";
const ORDER: ThemePreference[] = ["system", "light", "dark"];

const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;

function readPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    /* private mode: the choice just does not persist */
  }
  return "system";
}

const resolve = (preference: ThemePreference): ResolvedTheme =>
  preference === "system" ? (systemDark() ? "dark" : "light") : preference;

/** Put the theme on the page: the `dark` class selects the dark tokens, `color-scheme`
 * makes native controls and scrollbars follow. index.html does the same before first paint. */
function apply(theme: ResolvedTheme) {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.style.colorScheme = theme;
}

/** The theme: a remembered preference (system, light, dark) and the theme it resolves to.
 * While the preference is `system` a change of the operating system's theme is followed live. */
export function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(readPreference);
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolve(readPreference()));

  useEffect(() => {
    const update = () => {
      const next = resolve(preference);
      setResolved(next);
      apply(next);
    };
    update();
    if (preference !== "system") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, [preference]);

  const choose = useCallback((next: ThemePreference) => {
    setPreference(next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      /* not persisted */
    }
  }, []);

  /** system -> light -> dark -> system */
  const cycle = useCallback(() => choose(ORDER[(ORDER.indexOf(preference) + 1) % ORDER.length]), [choose, preference]);

  return { preference, resolved, choose, cycle };
}
