import { Layers, Search, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { SketchEditor } from "@/lib/useSketchEditor";

/** The popover of the project tool: the other sketch features of the notebook, with a search box.  Choosing one asks
 * the SDK to project it into this sketch (project_rsketch); the entities arrive as fixed construction geometry. */
export function SketchProject({ editor }: { editor: SketchEditor }) {
  const [query, setQuery] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const rows = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return editor.projectFrom.filter((slug) => words.every((w) => slug.toLowerCase().includes(w)));
  }, [editor.projectFrom, query]);
  useEffect(() => input.current?.focus(), []);
  return (
    <div className="pointer-events-auto absolute left-[108px] top-[205px] z-30 w-60 border-2 border-primary bg-popover shadow-[4px_4px_0_var(--shadow-hard)]" data-testid="sketch-project" role="dialog" aria-label="Project a sketch">
      <div className="flex items-center gap-1.5 border-b-2 border-border px-2 py-1">
        <Layers className="size-3.5 shrink-0" />
        <span className="flex-1 text-[10px] font-bold uppercase tracking-[0.12em]">project sketch</span>
        <button type="button" aria-label="Close" className="text-muted-foreground hover:text-foreground" onClick={() => editor.setProjectOpen(false)}>
          <X className="size-3.5" />
        </button>
      </div>
      <div className="flex items-center gap-1.5 border-b border-border px-1.5">
        <Search className="size-3.5 text-muted-foreground" />
        <input
          ref={input}
          aria-label="Search sketches"
          data-testid="sketch-project-search"
          placeholder="search sketches"
          className="h-7 flex-1 bg-transparent text-[12px] outline-none"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === "Escape") {
              e.preventDefault();
              editor.setProjectOpen(false);
            } else if (e.key === "Enter" && rows.length === 1) {
              e.preventDefault();
              editor.projectSketch(rows[0]);
            }
          }}
        />
      </div>
      <ul className="max-h-48 overflow-y-auto">
        {rows.map((slug) => (
          <li key={slug}>
            <button type="button" data-testid={`project-${slug}`} disabled={editor.editBusy} className="flex w-full items-center px-2 py-1 text-left text-[12px] text-name hover:bg-accent disabled:opacity-50" onClick={() => editor.projectSketch(slug)}>
              {slug}
            </button>
          </li>
        ))}
        {rows.length === 0 && <li className="px-2 py-2 text-[11px] text-muted-foreground">No sketch matches.</li>}
      </ul>
      <p className="border-t border-border px-2 py-1 text-[10px] leading-tight text-muted-foreground">The sketch's lines, circles, arcs and points come in as fixed construction geometry you can snap and constrain to.</p>
    </div>
  );
}
