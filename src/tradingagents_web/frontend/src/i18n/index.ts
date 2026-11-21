// REQ-WEB-014, ADR-003: two interface locales; report language is independent.
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./en.json";
import zh from "./zh.json";

export function normalizeLanguage(value: string | null): "en" | "zh" {
  return value === "zh" || value?.startsWith("zh-") ? "zh" : "en";
}
function storedLanguage() {
  try {
    return window.localStorage.getItem("ta.language");
  } catch {
    return null;
  }
}
function applyLanguage(language: string) {
  const locale = normalizeLanguage(language);
  document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  try {
    window.localStorage.setItem("ta.language", locale);
  } catch {
    /* Storage is optional. */
  }
}
i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en, workspace: en.workspace },
    zh: { translation: zh, workspace: zh.workspace },
  },
  lng: normalizeLanguage(storedLanguage()),
  fallbackLng: "en",
  supportedLngs: ["en", "zh"],
  interpolation: { escapeValue: false },
});
i18n.on("languageChanged", applyLanguage);
applyLanguage(i18n.language);
export default i18n;
