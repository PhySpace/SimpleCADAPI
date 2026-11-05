import { Languages, Monitor, Moon, Sun } from "lucide-react";

import type { ThemePreference } from "@/lib/theme";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LANGUAGES, setLanguage, useI18n } from "@/i18n";

/** Top bar: which notebook is open, whether its kernel is alive, the model's last message, the theme and the language.
 * The mode switch and "run all" are at the top of the left column; undo and redo are the feature tree's. */
export function Header({
  notebook,
  kind,
  kernelAlive,
  status,
  themePreference,
  onTheme,
}: {
  notebook: string | null;
  kind: string | null;
  kernelAlive: boolean;
  status: string;
  themePreference: ThemePreference;
  onTheme: () => void;
}) {
  const { t, language } = useI18n();
  const failing = status.startsWith("error");
  const nextLanguage = LANGUAGES[(LANGUAGES.findIndex((item) => item.code === language) + 1) % LANGUAGES.length];
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
        <span className="text-muted-foreground">{t("no notebook")}</span>
      )}
      <span
        className={`inline-block h-2 w-2 ${kernelAlive ? "bg-pass" : "bg-fail"}`}
        title={kernelAlive ? t("kernel running") : t("kernel stopped")}
      />
      <span
        className={`min-w-0 flex-1 truncate text-[11px] ${failing ? "text-fail" : "text-muted-foreground"}`}
        title={status}
      >
        {status}
      </span>
      <Button
        size="sm"
        variant="ghost"
        onClick={onTheme}
        title={t("Theme: {{theme}} (click: {{next}})", { theme: t(themePreference), next: t(NEXT_THEME[themePreference]) })}
        aria-label={t("Theme: {{theme}}. Switch to {{next}}", { theme: t(themePreference), next: t(NEXT_THEME[themePreference]) })}
      >
        {themePreference === "system" ? <Monitor /> : themePreference === "light" ? <Sun /> : <Moon />}
        {t(themePreference)}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => setLanguage(nextLanguage.code)}
        title={t("Language (click: {{next}})", { next: nextLanguage.label })}
        aria-label={t("Language (click: {{next}})", { next: nextLanguage.label })}
      >
        <Languages />
        {LANGUAGES.find((item) => item.code === language)?.label ?? "EN"}
      </Button>
    </header>
  );
}

const NEXT_THEME: Record<ThemePreference, ThemePreference> = { system: "light", light: "dark", dark: "system" };
