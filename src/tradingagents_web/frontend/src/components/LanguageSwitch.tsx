import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";

export function LanguageSwitch() {
  const { i18n, t } = useTranslation();
  const next = i18n.language.startsWith("zh") ? "en" : "zh";

  function toggle() {
    void i18n.changeLanguage(next);
    window.localStorage.setItem("ta.language", next);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="inline-flex items-center gap-2 rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
      aria-label={t("nav.language")}
    >
      <Languages size={16} />
      {next === "zh" ? "中文" : "EN"}
    </button>
  );
}
