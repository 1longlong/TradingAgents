// REQ-WEB-014/021, ADR-003: accessible persistent interface-language control.
import { Languages } from "lucide-react";
import { ui, useUILanguage } from "../i18n/ui";

export function LanguageSwitch() {
  const { i18n } = useUILanguage();
  const next = i18n.language.startsWith("zh") ? "en" : "zh";
  return (
    <button
      type="button"
      className="language-switch"
      onClick={() => void i18n.changeLanguage(next)}
      aria-label={ui(next === "zh" ? "Switch to Chinese" : "Switch to English")}
    >
      <Languages size={16} aria-hidden="true" />
      <span lang={next === "zh" ? "zh-CN" : "en"}>
        {next === "zh" ? "中文" : "English"}
      </span>
    </button>
  );
}
