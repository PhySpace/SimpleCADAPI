import { useEffect, useRef, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { EditorView } from "@codemirror/view";
import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ParamControl, type ParamMeta, type ParamValue } from "@/components/ParamControl";
import { cadTheme } from "@/lib/cm-theme";

/** A local module of the workspace (shared dimensions, helpers): what the
 * server sends as the `module` envelope. */
export type ModuleState = {
  path: string;
  name: string;
  code: string;
  used_by: string[];
  params: ParamMeta[];
  origin?: string;
};

const AUTOSAVE_MS = 700;
const EXTENSIONS = [python(), EditorView.lineWrapping];

/** A module open next to the notebooks: its dataclass fields as controls, its
 * source below. Every edit is written to the file at once, and every notebook
 * that imports it follows (the server reloads it and reruns what reads it). */
export function ModuleView({
  module,
  socket,
  onClose,
}: {
  module: ModuleState;
  socket: { send: (message: Record<string, unknown>) => void } | null;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(module.code);
  const dirty = useRef(false);
  const saveTimer = useRef<number | null>(null);
  const paramTimer = useRef<number | null>(null);
  const pending = useRef(new Map<string, ParamValue>());

  // A different module, an external edit or a parameter edit replaces the
  // text; our own autosave echo must not clobber what is being typed.
  useEffect(() => {
    if (module.origin === "save" && dirty.current) return;
    setDraft(module.code);
    dirty.current = false;
  }, [module.path, module.code, module.origin]);

  const edit = (value: string) => {
    setDraft(value);
    dirty.current = true;
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null;
      dirty.current = false;
      socket?.send({ type: "module.save", path: module.path, code: value });
    }, AUTOSAVE_MS);
  };

  const forward = (id: string, value: ParamValue) => {
    pending.current.set(id, value);
    if (paramTimer.current !== null) return;
    paramTimer.current = window.setTimeout(() => {
      paramTimer.current = null;
      socket?.send({ type: "module.param", path: module.path, values: Object.fromEntries(pending.current) });
      pending.current.clear();
    }, 120);
  };

  const groups = new Map<string, ParamMeta[]>();
  for (const param of module.params) {
    const list = groups.get(param.group) ?? [];
    list.push(param);
    groups.set(param.group, list);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-8 shrink-0 items-center gap-2 border-b border-border px-3">
        <span className="min-w-0 flex-1 truncate text-name" title={module.path}>
          {module.path}
        </span>
        {module.used_by.length > 0 ? (
          <span className="label hidden truncate xl:inline" title={module.used_by.join(", ")}>
            used by {module.used_by.map((path) => path.replace(/\.py$/, "")).join(", ")}
          </span>
        ) : (
          <Badge variant="secondary">unused</Badge>
        )}
        <button
          type="button"
          className="flex h-6 w-6 items-center justify-center border-2 border-transparent text-muted-foreground hover:border-input hover:text-foreground"
          title="Close the module view"
          onClick={onClose}
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-3 px-2 py-2">
          {[...groups].map(([group, params]) => (
            <section key={group} className="border-2 border-border">
              <header className="flex h-7 items-center border-b-2 border-border px-2">
                <span className="label text-foreground">{group}</span>
                <span className="label ml-2">{params.length} fields</span>
              </header>
              <div className="grid grid-cols-2 gap-x-5 gap-y-2.5 px-2.5 py-2">
                {params.map((param) => (
                  <ParamControl key={param.id} param={param} forwardParam={forward} />
                ))}
              </div>
            </section>
          ))}
          <section className="border-2 border-border">
            <header className="flex h-7 items-center border-b-2 border-border px-2">
              <span className="label text-foreground">source</span>
              <span className="label ml-2">autosaved</span>
            </header>
            <CodeMirror
              value={draft}
              height="auto"
              extensions={EXTENSIONS}
              theme={cadTheme}
              basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: false }}
              onChange={edit}
            />
          </section>
        </div>
      </ScrollArea>
    </div>
  );
}
