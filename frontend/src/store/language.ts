/**
 * The patient's language. One choice, made once, driving everything.
 *
 * There is deliberately no separate "interface language" and "spoken language"
 * any more. A patient who picks Tamil is assumed to read only Tamil, hear only
 * Tamil, and speak only Tamil — so screen text, audio prompts, speech
 * recognition and the physician-facing translation all follow the same value.
 * Splitting them produced a screen in English narrating in Tamil, which serves
 * nobody.
 *
 * That assumption is only honest if every language offered is fully supported,
 * which is why the picker shows only the ten that have interface strings, a
 * Bulbul voice, and Saaras transcription. The remaining thirteen Sarvam can
 * transcribe are not offered until they have all three.
 *
 * Persisted in sessionStorage because i18next keeps the active language in
 * memory only: a page refresh mid-visit would otherwise drop the patient back to
 * English without explanation.
 */

import i18n, { SUPPORTED_LANGUAGES, type SupportedLanguage } from "../i18n";

const LANGUAGE_KEY = "medikiosk_language";

export function isSupportedLanguage(code: string): code is SupportedLanguage {
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(code);
}

/** The stored language, or null when the patient has not chosen yet. */
export function getStoredLanguage(): SupportedLanguage | null {
  const stored = sessionStorage.getItem(LANGUAGE_KEY);
  return stored && isSupportedLanguage(stored) ? stored : null;
}

/**
 * The language in force: the patient's choice, or i18next's current value.
 *
 * Falls back to i18next rather than hardcoding English so a deployment that sets
 * VITE_DEFAULT_LOCALE is respected before any choice is made.
 */
export function getLanguage(): string {
  return getStoredLanguage() ?? i18n.language;
}

/** Set the language for the whole app, and remember it for this visit. */
export async function setLanguage(code: string): Promise<void> {
  if (!isSupportedLanguage(code)) return;
  sessionStorage.setItem(LANGUAGE_KEY, code);
  await i18n.changeLanguage(code);
}

export function clearLanguage(): void {
  sessionStorage.removeItem(LANGUAGE_KEY);
}

/** Native names for the picker and the header dropdown, in their own script. */
export const LANGUAGE_NAMES: Record<SupportedLanguage, string> = {
  en: "English",
  hi: "हिन्दी",
  bn: "বাংলা",
  mr: "मराठी",
  te: "తెలుగు",
  ta: "தமிழ்",
  gu: "ગુજરાતી",
  kn: "ಕನ್ನಡ",
  ml: "മലയാളം",
  pa: "ਪੰਜਾਬੀ",
};

/**
 * English names, shown in brackets beside the native one.
 *
 * The native name is what a patient recognises; the English name is what lets an
 * attendant helping them, or a patient who knows their language's English name
 * but not its script, find the right tile. Duplicated here rather than taken from
 * GET /languages alone so the offline fallback list is not reduced to bare codes.
 */
export const LANGUAGE_ENGLISH_NAMES: Record<SupportedLanguage, string> = {
  en: "English",
  hi: "Hindi",
  bn: "Bengali",
  mr: "Marathi",
  te: "Telugu",
  ta: "Tamil",
  gu: "Gujarati",
  kn: "Kannada",
  ml: "Malayalam",
  pa: "Punjabi",
};
