import { ExternalLink, Monitor, Moon, Play, Square, Sun } from "lucide-react";

import type { ThemePreference } from "@/lib/theme";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

/** Top bar: which notebook is open, whether its kernel is alive, and the
 * model's last message. Everything else lives on the cells. */
export function Header({
  notebook,
  kind,
  kernelAlive,
  status,
  onRunAll,
  running,
  onStop,
  marimoUrl,
  themePreference,
  onTheme,
}: {
  notebook: string | null;
  kind: string | null;
  kernelAlive: boolean;
  status: string;
  onRunAll: () => void;
  /** The kernel is running cells: the button stops them instead. */
  running: boolean;
  onStop: () => void;
  marimoUrl: string | null;
  themePreference: ThemePreference;
  onTheme: () => void;
}) {
  const failing = status.startsWith("error");
  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b-2 border-border bg-background px-3">
      <span className="text-[13px] font-bold uppercase tracking-[0.14em]">SimpleCAD</span>
      <span className="h-5 w-[2px] bg-border" />
      {notebook ? (
        <span className="flex items-center gap-2">
          <span className="text-name">{notebook}</span>
          {kind && kind !== "helper" && <Badge variant="outline">{kind}</Badge>}
        </span>
      ) : (
        <span className="text-muted-foreground">no notebook</span>
      )}
      <span
        className={`inline-block h-2 w-2 ${kernelAlive ? "bg-pass" : "bg-fail"}`}
        title={kernelAlive ? "kernel running" : "kernel stopped"}
      />
      <span
        className={`min-w-0 flex-1 truncate text-[11px] ${failing ? "text-fail" : "text-muted-foreground"}`}
        title={status}
      >
        {status}
      </span>
      {running ? (
        <Button size="sm" variant="destructive" onClick={onStop} title="Stop the run (interrupt the kernel)">
          <Square className="fill-current" /> stop
        </Button>
      ) : (
        <Button size="sm" variant="outline" onClick={onRunAll} title="Run every cell">
          <Play /> run all
        </Button>
      )}
      {marimoUrl && (
        <Button size="sm" variant="ghost" asChild>
          <a href={marimoUrl} target="_blank" rel="noreferrer" title="Open the raw marimo editor">
            <ExternalLink /> marimo
          </a>
        </Button>
      )}
      <Button
        size="sm"
        variant="ghost"
        onClick={onTheme}
        title={`Theme: ${themePreference} (click: ${NEXT_THEME[themePreference]})`}
        aria-label={`Theme: ${themePreference}. Switch to ${NEXT_THEME[themePreference]}`}
      >
        {themePreference === "system" ? <Monitor /> : themePreference === "light" ? <Sun /> : <Moon />}
        {themePreference}
      </Button>
    </header>
  );
}

const NEXT_THEME: Record<ThemePreference, ThemePreference> = { system: "light", light: "dark", dark: "system" };
