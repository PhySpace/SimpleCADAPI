/** The model before a failing step: a `preview` envelope's `partial` (`simplecadapi.runtime.live.preview_product`).
 *
 * A cell failed, so the product was not made; the kernel previewed what the cells before it made instead (the body the
 * failing feature was applied to) and says so.  `null` when the model is the whole product. */

import { t } from "@/i18n";

export type FailedCell = {
  /** The marimo cell id (the notebook's cells carry the same ids). */
  cell: string;
  /** The feature the cell makes, else the cell's name. */
  name: string;
  /** marimo's run state: `exception`, `interrupted` or `marimo-error`. */
  status: string;
  /** `Type: message`, cut short; empty when marimo kept none. */
  error: string;
};

export type PartialModel = {
  /** The failing steps (cells downstream of no other failed cell), in notebook order. */
  failed: FailedCell[];
  /** The ids of the cells after them that did not run. */
  skipped: string[];
  /** The bodies (or the product) on screen. */
  shown: string[];
};

const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);

export function parsePartial(value: unknown): PartialModel | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const failed = (Array.isArray(row.failed) ? row.failed : [])
    .filter((item): item is Record<string, unknown> => !!item && typeof item === "object" && typeof item.cell === "string")
    .map((item) => ({
      cell: String(item.cell),
      name: typeof item.name === "string" && item.name ? item.name : String(item.cell),
      status: typeof item.status === "string" ? item.status : "exception",
      error: typeof item.error === "string" ? item.error : "",
    }));
  if (!failed.length) return null;
  return { failed, skipped: strings(row.skipped), shown: strings(row.shown) };
}

/** What the notice says: the step the model stops before, why, and what did not run.  *titles* maps a cell id to the
 * title the notebook shows for it (a step without a feature header is told by its title). */
export function describePartial(partial: PartialModel, titles: ReadonlyMap<string, string> = new Map()): { title: string; reason: string; after: string } {
  const [first, ...rest] = partial.failed;
  const name = (cell: FailedCell) => titles.get(cell.cell) || cell.name;
  const what = first.status === "interrupted" ? "{{step}} was stopped" : first.status === "marimo-error" ? "{{step}} cannot run" : "{{step}} failed";
  const reason = first.error ? `${t(what, { step: name(first) })}: ${firstLine(first.error)}` : t(what, { step: name(first) });
  const later = partial.skipped.length + rest.length;
  const after = [
    rest.length ? t("{{steps}} failed too", { steps: rest.map(name).join(", ") }) : "",
    later ? (later === 1 ? t("1 later step did not run") : t("{{count}} later steps did not run", { count: later })) : "",
  ]
    .filter(Boolean)
    .join("; ");
  return { title: t("The model before {{step}}", { step: name(first) }), reason, after };
}

/** An error kept to one short line (the kernel already put the SDK's errors as "Type: operation: what happened"). */
function firstLine(error: string): string {
  const text = error.replace(/\s+/g, " ").trim();
  return text.length > 180 ? `${text.slice(0, 179)}…` : text;
}

/** Whether two partial states say the same thing (the log is told once per failure, not per slider tick). */
export function samePartial(a: PartialModel | null, b: PartialModel | null): boolean {
  return JSON.stringify(a?.failed.map((cell) => [cell.cell, cell.error]) ?? null) === JSON.stringify(b?.failed.map((cell) => [cell.cell, cell.error]) ?? null);
}
