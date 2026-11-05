/** The editor's languages.  The English text is the key: `t("Collapse the panel")` reads as what it shows, English
 * needs no table, and a missing translation shows the English.  `locales/zh-CN.json` maps English to Chinese; the
 * coverage test (i18n.test.ts) fails when a literal key passed to t in the source has no entry there.
 *
 * Not translated: SDK names (operations, parameters, entity ids), code, cell titles, and what the server says
 * verbatim (an error of the kernel). */

import i18n from "i18next";
import { initReactI18next, useTranslation } from "react-i18next";

import zhCN from "./locales/zh-CN.json";

export const LANGUAGES = [
  { code: "en", label: "EN" },
  { code: "zh-CN", label: "中" },
] as const;
export type Language = (typeof LANGUAGES)[number]["code"];

const STORE_KEY = "sca.language";

/** The saved choice, else the browser's language (Chinese for any zh-*, English otherwise). */
export function initialLanguage(): Language {
  try {
    const saved = window.localStorage.getItem(STORE_KEY);
    if (saved === "en" || saved === "zh-CN") return saved;
  } catch {
    // storage blocked: follow the browser
  }
  const preferred = typeof navigator !== "undefined" ? navigator.languages ?? [navigator.language] : [];
  return preferred.some((tag) => tag?.toLowerCase().startsWith("zh")) ? "zh-CN" : "en";
}

void i18n.use(initReactI18next).init({
  lng: typeof window === "undefined" ? "en" : initialLanguage(),
  fallbackLng: "en",
  resources: { "zh-CN": { translation: zhCN } },
  // English sentences are keys: they contain dots and colons
  keySeparator: false,
  nsSeparator: false,
  interpolation: { escapeValue: false }, // React escapes
  returnEmptyString: false,
});

export function setLanguage(language: Language): void {
  void i18n.changeLanguage(language);
  document.documentElement.lang = language;
  try {
    window.localStorage.setItem(STORE_KEY, language);
  } catch {
    // storage blocked: the choice lasts until the page reloads
  }
}

/** `t` and the current language, re-rendering on a change. */
export function useI18n() {
  const { t, i18n: instance } = useTranslation();
  return { t, language: (instance.resolvedLanguage ?? instance.language) as Language };
}

/** Outside React (a message built in a library function): the current language at the time of the call. */
export const t = (key: string, options?: Record<string, unknown>): string => i18n.t(key, options) as string;

export default i18n;
