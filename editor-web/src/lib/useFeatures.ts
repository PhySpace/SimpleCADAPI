import { useCallback, useEffect, useRef, useState } from "react";

import { featureCommand, fetchFeatureState, fetchSpecs, type Catalog, type FeatureCommand, type FeatureState } from "@/lib/features";

const EMPTY: FeatureState = { features: [], bodies: [], open: [], tip: null, product: null, defaults: {}, assembly: null, connectors: [], taken: [], undo: 0, redo: 0 };

/** The GUI features of the open notebook: the catalog (once), the state (refreshed on demand, debounced), commands. */
export function useFeatures() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [state, setState] = useState<FeatureState>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const alive = useRef(true);

  const refreshNow = useCallback(async () => {
    try {
      const next = await fetchFeatureState();
      if (alive.current) {
        setState(next);
        setError(null);
      }
    } catch (failure) {
      if (alive.current) setError(failure instanceof Error ? failure.message : String(failure));
    }
  }, []);

  /** Ask for the state ~200 ms from now; a burst of events asks once. */
  const refresh = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      timer.current = null;
      void refreshNow();
    }, 200);
  }, [refreshNow]);

  useEffect(() => {
    alive.current = true;
    void fetchSpecs().then((value) => alive.current && setCatalog(value)).catch((failure) => setError(String(failure)));
    void refreshNow();
    return () => {
      alive.current = false;
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [refreshNow]);

  /** Run a command; the state of the answer replaces ours. Rejects with the server's message. */
  const run = useCallback(async (command: FeatureCommand) => {
    const result = await featureCommand(command);
    if (alive.current) setState(result.state);
    return result;
  }, []);

  return { catalog, state, error, refresh, run };
}
