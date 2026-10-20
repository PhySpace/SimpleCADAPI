import { useCallback, useEffect, useRef, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { EditorView } from "@codemirror/view";
import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ParamControl, type ParamMeta, type ParamValue } from "@/components/ParamControl";
import { cadTheme } from "@/lib/cm-theme";
import { createSettler, SETTLE_MS } from "@/lib/settle";
import { sdkCompletion } from "@/lib/sdk-complete";

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
const EXTENSIONS = [python(), EditorView.lineWrapping, sdkCompletion];
/** a constant: a new object each render makes the editor wrapper rebuild its configuration, which drops a snippet in progress */
const BASIC_SETUP = { lineNumbers: true, foldGutter: false, highlightActiveLine: false };

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
  const socketRef = useRef(socket);
  socketRef.current = socket;
  const pathRef = useRef(module.path);
  pathRef.current = module.path;
  const settler = useRef(
    createSettler<ParamValue>(SETTLE_MS, (values) =>
      socketRef.current?.send({ type: "module.param", path: pathRef.current, values }),
    ),
  );
  // values of the module that was left are not the next one's
  useEffect(() => () => settler.current.cancel(), [module.path]);

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

  // the editor takes this once: a new function each render would rebuild its configuration
  const editRef = useRef(edit);
  editRef.current = edit;
  const handleChange = useCallback((value: string) => editRef.current(value), []);

  // A drag is sent when it pauses or ends, not step by step: every value the
  // server gets is a rebuild.
  const forward = (id: string, value: ParamValue, now = false) => {
    settler.current.push(id, value);
    if (now) settler.current.flush();
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
              basicSetup={BASIC_SETUP}
              onChange={handleChange}
            />
          </section>
        </div>
      </ScrollArea>
    </div>
  );
}
