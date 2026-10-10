import { useState } from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

/** A generic, collapsible view of JSON data: objects and arrays open to
 * `openDepth` levels, short number arrays stay on one line, numbers are
 * rounded for reading. Used wherever the editor shows raw entity data. */
export function JsonTree({
  value,
  openDepth = 2,
  className,
}: {
  value: unknown;
  openDepth?: number;
  className?: string;
}) {
  return (
    <div className={cn("font-mono text-[11px] leading-[1.55]", className)}>
      <Node value={value} depth={0} openDepth={openDepth} />
    </div>
  );
}

type Entry = [string, unknown];

function isContainer(value: unknown): value is Record<string, unknown> | unknown[] {
  return typeof value === "object" && value !== null;
}

function entriesOf(value: Record<string, unknown> | unknown[]): Entry[] {
  return Array.isArray(value)
    ? value.map((item, index) => [String(index), item])
    : Object.entries(value);
}

/** A flat array of a few numbers reads best inline: [1.2, 0, -3]. */
function inlineNumbers(value: unknown): string | null {
  if (!Array.isArray(value) || value.length === 0 || value.length > 6) return null;
  if (!value.every((item) => typeof item === "number")) return null;
  return `[${value.map((item) => formatNumber(item as number)).join(", ")}]`;
}

export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  if (Number.isInteger(value)) return String(value);
  const text = value.toFixed(4).replace(/\.?0+$/, "");
  return text === "-0" ? "0" : text;
}

function Scalar({ value }: { value: unknown }) {
  if (typeof value === "number") return <span className="text-name">{formatNumber(value)}</span>;
  if (typeof value === "boolean") return <span className="text-focus">{String(value)}</span>;
  if (value === null || value === undefined) return <span className="text-muted-foreground">null</span>;
  return <span className="break-all text-foreground">{String(value)}</span>;
}

function summary(value: Record<string, unknown> | unknown[]): string {
  return Array.isArray(value) ? `[${value.length}]` : `{${Object.keys(value).length}}`;
}

function Node({ value, depth, openDepth }: { value: unknown; depth: number; openDepth: number }) {
  if (!isContainer(value)) return <Scalar value={value} />;
  const inline = inlineNumbers(value);
  if (inline) return <span className="text-name">{inline}</span>;
  const entries = entriesOf(value);
  if (entries.length === 0) return <span className="text-muted-foreground">{Array.isArray(value) ? "[]" : "{}"}</span>;
  return (
    <ul className={cn(depth > 0 && "ml-[5px] border-l border-border pl-2")}>
      {entries.map(([key, child]) => (
        <Row key={key} name={key} value={child} depth={depth} openDepth={openDepth} />
      ))}
    </ul>
  );
}

function Row({ name, value, depth, openDepth }: { name: string; value: unknown; depth: number; openDepth: number }) {
  const container = isContainer(value) && inlineNumbers(value) === null;
  const empty = container && entriesOf(value as Record<string, unknown> | unknown[]).length === 0;
  const [open, setOpen] = useState(depth + 1 < openDepth);
  if (!container || empty) {
    return (
      <li className="flex gap-1.5">
        <span className="shrink-0 text-muted-foreground">{name}</span>
        <Node value={value} depth={depth + 1} openDepth={openDepth} />
      </li>
    );
  }
  return (
    <li>
      <button
        type="button"
        className="flex w-full items-center gap-0.5 text-left hover:text-foreground"
        onClick={() => setOpen((current) => !current)}
      >
        <ChevronRight className={cn("h-3 w-3 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
        <span className="text-muted-foreground">{name}</span>
        {!open && <span className="ml-1.5 text-muted-foreground/70">{summary(value as Record<string, unknown> | unknown[])}</span>}
      </button>
      {open && <Node value={value} depth={depth + 1} openDepth={openDepth} />}
    </li>
  );
}
