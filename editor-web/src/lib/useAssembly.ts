import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  connectorsOfState,
  emptyAssembly,
  fetchConnectors,
  fetchParts,
  normalizeAssembly,
  sameDoc,
  type AssemblyDoc,
  type ConnectorFrame,
  type PartRow,
} from "@/lib/assembly";
import type { FeatureState } from "@/lib/features";

export type ConnectorEntry = { status: "loading" | "ok" | "error"; connectors: ConnectorFrame[]; error?: string };

/** Which side of which constraint a click on a connector gizmo fills. */
export type PickTarget = { constraint: string; side: "a" | "b" } | null;

/** The assembly being edited (a draft of the document the notebook holds), the part list and the connectors of each part
 * (fetched on demand, cached per path, refreshable), the selected component and the armed picker. */
export function useAssemblyEditor(state: Pick<FeatureState, "assembly">, notebookKey: string | null) {
  const server = useMemo(() => normalizeAssembly(state.assembly?.doc ?? emptyAssembly()), [state.assembly]);
  const serverKey = JSON.stringify(server) + (state.assembly?.cell ?? "");
  const [doc, setDoc] = useState<AssemblyDoc>(server);
  const docRef = useRef(doc);
  docRef.current = doc;
  const dirty = !sameDoc(doc, server);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const [selected, setSelected] = useState<string | null>(null);
  const [target, setTarget] = useState<PickTarget>(null);

  // The draft follows the notebook (an apply, an agent's edit, another notebook) unless the person has unsent changes.
  useEffect(() => {
    if (!dirtyRef.current) setDoc(server);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey]);
  // Another notebook: nothing carries over.
  useEffect(() => {
    setDoc(server);
    setSelected(null);
    setTarget(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notebookKey]);

  const [parts, setParts] = useState<PartRow[]>([]);
  const [partsError, setPartsError] = useState<string | null>(null);
  const refreshParts = useCallback(() => {
    fetchParts().then((rows) => {
      setParts(rows);
      setPartsError(null);
    }).catch((e) => setPartsError(e instanceof Error ? e.message : String(e)));
  }, []);

  const [cache, setCache] = useState<Record<string, ConnectorEntry>>({});
  const cacheRef = useRef(cache);
  cacheRef.current = cache;
  /** The connectors of a part notebook: asked once per path (the server runs the part), again on `force`. */
  const loadConnectors = useCallback((path: string, force = false) => {
    const known = cacheRef.current[path];
    if (!path || (known && !force && known.status !== "error")) return;
    setCache((c) => ({ ...c, [path]: { status: "loading", connectors: known?.connectors ?? [] } }));
    fetchConnectors(path)
      .then((connectors) => setCache((c) => ({ ...c, [path]: { status: "ok", connectors } })))
      .catch((e) => setCache((c) => ({ ...c, [path]: { status: "error", connectors: [], error: e instanceof Error ? e.message : String(e) } })));
  }, []);
  // Another notebook may use other parts or have rewritten them.
  useEffect(() => {
    setCache({});
  }, [notebookKey]);

  return { doc, setDoc, dirty, server, selected, setSelected, target, setTarget, parts, partsError, refreshParts, cache, loadConnectors };
}
export type AssemblyEditor = ReturnType<typeof useAssemblyEditor>;

/** The connector list of the part notebook being edited (a draft of `state.connectors`). */
export function useConnectorDraft(state: Pick<FeatureState, "connectors">, notebookKey: string | null) {
  const server = useMemo(() => connectorsOfState(state), [state.connectors]);
  const serverKey = JSON.stringify(server);
  const [list, setList] = useState<ConnectorFrame[]>(server);
  const dirty = JSON.stringify(list.map(({ z_axis: _z, ...rest }) => rest)) !== JSON.stringify(server.map(({ z_axis: _z, ...rest }) => rest));
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    if (!dirtyRef.current) setList(server);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey]);
  useEffect(() => {
    setList(server);
    setSelected(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notebookKey]);
  return { list, setList, dirty, selected, setSelected };
}
export type ConnectorDraft = ReturnType<typeof useConnectorDraft>;
