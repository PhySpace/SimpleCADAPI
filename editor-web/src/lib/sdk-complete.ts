import { acceptCompletion, snippet, type Completion, type CompletionContext, type CompletionResult } from "@codemirror/autocomplete";
import { pythonLanguage } from "@codemirror/lang-python";
import { Prec, type Extension } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";

/**
 * Code completion from the SDK itself. The server describes the running package (GET /api/sdk:
 * every public function and class with its parameters); from that:
 *
 * - `scad.` lists the functions (also `scad.ql.`, `scad.std.gear.`, and `ql.` / `Q.`);
 * - accepting one, or typing `(` after a known name, writes the call with every required
 *   parameter as `name=` and moves between them with Tab;
 * - inside a call, the parameters not given yet complete as `name=` (required ones first).
 */

interface Param {
  n: string;
  r: boolean;
  /** "p" positional only, "a" the *args parameter, "w" the **kwargs one, "" an ordinary one */
  k: "p" | "a" | "w" | "";
  d?: string;
}
interface Entry {
  n: string;
  k: "f" | "c";
  p: Param[];
  d: string;
}
interface SdkIndex {
  namespaces: Record<string, Entry[]>;
  submodules: Record<string, string[]>;
}

let index: SdkIndex | null = null;
let loading: Promise<SdkIndex | null> | null = null;
const load = (): Promise<SdkIndex | null> =>
  (loading ??= fetch("/api/sdk")
    .then((response) => (response.ok ? (response.json() as Promise<SdkIndex>) : null))
    .then((data) => (index = data))
    .catch(() => null));

/** how a name written in a cell reaches a namespace of the index */
const HEADS: Record<string, string> = { scad: "scad", ql: "scad.ql", Q: "scad.ql" };
const namespaceOf = (path: string): string | null => {
  const [head, ...rest] = path.split(".");
  const base = HEADS[head];
  return base ? [base, ...rest].join(".") : null;
};

/** `scad.ql.faces` before the cursor: the namespace path and the name being typed */
const MEMBER = /(?<![\w.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\.(\w*)$/;

const lookup = (path: string, name: string): Entry | null => {
  const space = namespaceOf(path);
  return (space && index?.namespaces[space]?.find((entry) => entry.n === name)) || null;
};

const escapeSnippet = (text: string) => text.replace(/[\\${}]/g, "\\$&");

/** `(width=${1}, height=${2})`: every parameter that has to be written, in order */
export const callTemplate = (entry: Entry): string => {
  let slot = 0;
  const args = entry.p
    .filter((param) => param.k !== "w" && (param.r || param.k === "a"))
    .map((param) => {
      slot += 1;
      // positional ones cannot be named: a hint the person overwrites
      return param.k === "p" || param.k === "a" ? `\${${slot}:${escapeSnippet(param.n)}}` : `${param.n}=\${${slot}}`;
    });
  return `(${args.length ? args.join(", ") : "${}"})`;
};

const signature = (entry: Entry): string => {
  const required = entry.p.filter((param) => param.r || param.k === "a").map((param) => (param.k === "a" ? `*${param.n}` : param.n));
  const more = entry.p.some((param) => !param.r && param.k !== "a" && param.k !== "w");
  return `(${required.join(", ")}${more ? (required.length ? ", …" : "…") : ""})`;
};

const info = (entry: Entry) => () => {
  const root = document.createElement("div");
  const call = document.createElement("div");
  call.className = "sca-api-signature";
  call.textContent =
    entry.n +
    "(" +
    entry.p.map((param) => (param.k === "a" ? "*" : param.k === "w" ? "**" : "") + param.n + (param.d !== undefined ? `=${param.d}` : "")).join(", ") +
    ")";
  root.append(call);
  if (entry.d) {
    const doc = document.createElement("div");
    doc.className = "sca-api-doc";
    doc.textContent = entry.d;
    root.append(doc);
  }
  return root;
};

const entryCompletion = (entry: Entry): Completion => ({
  label: entry.n,
  type: entry.k === "c" ? "class" : "function",
  detail: signature(entry),
  info: info(entry),
  apply: (view, completion, from, to) => {
    // editing an existing call: only the name
    if (view.state.sliceDoc(to, to + 1) === "(") {
      view.dispatch({ changes: { from, to, insert: entry.n }, selection: { anchor: from + entry.n.length } });
      return;
    }
    snippet(`${escapeSnippet(entry.n)}${callTemplate(entry)}`)(view, completion, from, to);
  },
});

/** `scad.` + the typed start of a name */
const memberSource = async (context: CompletionContext): Promise<CompletionResult | null> => {
  const line = context.state.doc.lineAt(context.pos);
  const match = MEMBER.exec(line.text.slice(0, context.pos - line.from));
  if (!match) return null;
  const space = namespaceOf(match[1]);
  if (!space) return null;
  const data = index ?? (await load());
  if (!data || (!data.namespaces[space] && !data.submodules[space])) return null;
  const options: Completion[] = [
    ...(data.namespaces[space] ?? []).map(entryCompletion),
    ...(data.submodules[space] ?? []).map((name): Completion => ({ label: name, type: "namespace", detail: "module" })),
  ];
  return { from: context.pos - match[2].length, options, validFor: /^\w*$/ };
};

/** the innermost call the cursor is in: its function, and what is written between the parentheses */
const enclosingCall = (text: string, pos: number): { path: string; name: string; args: string } | null => {
  let depth = 0;
  for (let i = pos - 1; i >= Math.max(0, pos - 4000); i--) {
    const ch = text[i];
    if (ch === ")" || ch === "]" || ch === "}") depth++;
    else if (ch === "(" || ch === "[" || ch === "{") {
      if (depth > 0) depth--;
      else if (ch !== "(") return null;
      else {
        const named = /(?<![\w.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\.([A-Za-z_]\w*)\s*$/.exec(text.slice(Math.max(0, i - 160), i));
        return named ? { path: named[1], name: named[2], args: text.slice(i + 1, pos) } : null;
      }
    }
  }
  return null;
};

/** the top level of an argument list: nested brackets emptied out */
const topLevel = (args: string): string => {
  let depth = 0;
  let out = "";
  for (const ch of args) {
    if (ch === "(" || ch === "[" || ch === "{") depth++;
    else if (ch === ")" || ch === "]" || ch === "}") depth = Math.max(0, depth - 1);
    else if (depth === 0) out += ch;
  }
  return out;
};

/** inside `scad.f(`: the parameters not given yet, as `name=` */
const kwargSource = async (context: CompletionContext): Promise<CompletionResult | null> => {
  const word = context.matchBefore(/\w*/);
  if (!word || (word.from === word.to && !context.explicit)) return null;
  const text = context.state.sliceDoc(0, context.pos);
  const call = enclosingCall(text, context.pos);
  if (!call) return null;
  const data = index ?? (await load());
  if (!data) return null;
  const entry = lookup(call.path, call.name);
  if (!entry) return null;
  const top = topLevel(call.args);
  const segments = top.split(",");
  // only where an argument starts: not after `name=` and not inside an expression
  if (!/^\s*\w*$/.test(segments[segments.length - 1])) return null;
  const given = new Set([...top.matchAll(/(?<![=!<>])\b([A-Za-z_]\w*)\s*=(?!=)/g)].map((m) => m[1]));
  const positional = segments.slice(0, -1).filter((segment) => segment.trim() && !/(?<![=!<>])=(?!=)/.test(segment)).length;
  const free = entry.p.filter((param) => param.k !== "a" && param.k !== "w");
  const options: Completion[] = free
    .filter((param, k) => !given.has(param.n) && k >= positional && param.k !== "p")
    .map((param) => ({
      label: `${param.n}=`,
      type: "property",
      detail: param.r ? "required" : param.d !== undefined ? `default ${param.d}` : "",
      // above Python's own names (bool, ...): inside this call these are what is wanted
      boost: param.r ? 99 : 50,
    }));
  return options.length ? { from: word.from, options, validFor: /^\w*$/ } : null;
};

/** `(` typed after a known function: write the call with its required parameters */
const parenthesis = EditorView.inputHandler.of((view, from, to, text) => {
  if (text !== "(" || from !== to || !index) return false;
  const line = view.state.doc.lineAt(from);
  const match = MEMBER.exec(line.text.slice(0, from - line.from));
  const entry = match && match[2] ? lookup(match[1], match[2]) : null;
  if (!entry || view.state.sliceDoc(to, to + 1) === "(") return false;
  snippet(callTemplate(entry))(view, null, from, to);
  return true;
});

export const sdkCompletion: Extension = [
  pythonLanguage.data.of({ autocomplete: memberSource }),
  pythonLanguage.data.of({ autocomplete: kwargSource }),
  Prec.high(parenthesis),
  // Tab takes the highlighted suggestion (else it moves to the next parameter of a call)
  Prec.highest(keymap.of([{ key: "Tab", run: acceptCompletion }])),
];

void load();
