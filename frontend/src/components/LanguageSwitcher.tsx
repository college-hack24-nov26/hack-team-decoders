/**
 * LanguageSwitcher — one dropdown, changing the whole app.
 *
 * Was a row of buttons, which worked for two languages and does not for ten.
 * More importantly it implied screen language was a separate setting from the
 * spoken one; it is not. Changing this changes the text, the audio prompts and
 * the language speech is transcribed in, together.
 *
 * Native names only, in their own script: a patient who cannot read English
 * cannot read "Tamil" either, but will recognise "தமிழ்".
 */

import { useTranslation } from "react-i18next";
import { SUPPORTED_LANGUAGES } from "../i18n";
import { LANGUAGE_NAMES, getLanguage, setLanguage } from "../store/language";

export function LanguageSwitcher() {
  const { t } = useTranslation();
  const current = getLanguage();

  return (
    <label className="flex items-center gap-2">
      <span className="sr-only">{t("language.chooseLanguage")}</span>
      <svg
        className="h-5 w-5 shrink-0 text-gray-500"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M12 21a9 9 0 100-18 9 9 0 000 18zm0 0c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3M3.6 9h16.8M3.6 15h16.8"
        />
      </svg>
      <select
        value={current}
        onChange={(event) => void setLanguage(event.target.value)}
        aria-label={t("language.chooseLanguage")}
        className="cursor-pointer rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-800 transition-colors duration-200 hover:border-primary-600 focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200"
      >
        {SUPPORTED_LANGUAGES.map((code) => (
          <option key={code} value={code} lang={code}>
            {LANGUAGE_NAMES[code]}
          </option>
        ))}
      </select>
    </label>
  );
}
