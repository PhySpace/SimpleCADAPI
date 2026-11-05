import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { CONSTRAINT_SHORT, TOOLS } from "@/components/sketch/sketch-ui";
import { CONSTRAINT_INFO, statusBadge, type SolveResult } from "@/lib/sketch";
import { CORNER_WORD } from "@/lib/sketch-edit";
import { typedFields } from "@/lib/sketch-typed";

import zhCN from "./locales/zh-CN.json";

const SRC = join(import.meta.dirname, "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

/** Every literal key of the source: t("…") and t('…'), also as tt(…) (a t passed down under another name). */
function keys(): Map<string, string> {
  const found = new Map<string, string>();
  const call = /\bt{1,2}\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g;
  for (const path of sources(SRC)) {
    const text = readFileSync(path, "utf8");
    for (const match of text.matchAll(call)) found.set(JSON.parse(match[1].startsWith("'") ? `"${match[1].slice(1, -1).replace(/"/g, '\\"')}"` : match[1]), path);
  }
  return found;
}

describe("translations", () => {
  const table = zhCN as Record<string, string>;

  it("has a Chinese entry for every key the source uses", () => {
    const missing = [...keys()].filter(([key]) => !(key in table)).map(([key, path]) => `${path.slice(SRC.length + 1)}: ${key}`);
    expect(missing).toEqual([]);
  });

  it("keeps every interpolation of a key in its translation", () => {
    const broken = Object.entries(table).filter(([key, value]) => {
      const names = (text: string) => [...text.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]).sort().join(",");
      return names(key) !== names(value);
    });
    expect(broken).toEqual([]);
  });

  it("translates the keys the sketch tables hold (not literals in a t call)", () => {
    const solve = (status: string) => ({ status, dof: 2, diagnostics: [] }) as unknown as SolveResult;
    const tableKeys = [
      ...TOOLS.flatMap((tool) => [tool.name, tool.label]),
      ...Object.values(CONSTRAINT_SHORT),
      ...Object.values(CONSTRAINT_INFO).map((info) => info.label),
      ...Object.values(CORNER_WORD).map((word) => word.label),
      ...["point", "line", "circle", "arc", "spline"].flatMap((tool) =>
        [null, { tool: "line", from: { x: 0, y: 0 } }, { tool: "circle", center: { x: 0, y: 0 } }, { tool: "arc", center: { x: 0, y: 0 } }, { tool: "arc", center: { x: 0, y: 0 }, start: { x: 1, y: 0 } }].flatMap(
          (draft) => (typedFields(tool, draft as Parameters<typeof typedFields>[1]) ?? []).map((field) => field.label),
        ),
      ),
      ...["solved", "underconstrained", "conflicting", "failed"].flatMap((status) => [status, statusBadge(solve(status)).label]),
      statusBadge(null).label,
      statusBadge(null, "bad").label,
    ];
    expect([...new Set(tableKeys)].filter((key) => !(key in table))).toEqual([]);
  });
});
