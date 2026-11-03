/**
 * Language selection — first screen of the Identify flow.
 *
 * Reads the language list from GET /languages so adding a language server-side
 * shows up here, and falls back to the locally bundled list if the backend is
 * unreachable.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { CornerMotif } from "../components/AyushmanIcons";
import { SUPPORTED_LANGUAGES } from "../i18n";
import {
  LANGUAGE_ENGLISH_NAMES,
  LANGUAGE_NAMES,
  isSupportedLanguage,
  setLanguage,
} from "../store/language";

interface LanguageItem {
  code: string;
  name: string;
  native_name: string;
  /** "full" | "voice_input" | "text_only". */
  support?: string;
}

/**
 * Bundled list, used when GET /languages is unreachable.
 *
 * Safe to enumerate locally because these are exactly the languages whose
 * strings ship in the bundle — if the app loaded, they are available. The backend
 * list is still preferred so a language added server-side appears without a
 * frontend release.
 */
const FALLBACK: LanguageItem[] = SUPPORTED_LANGUAGES.map((code) => ({
  code,
  name: LANGUAGE_ENGLISH_NAMES[code],
  native_name: LANGUAGE_NAMES[code],
  support: "full",
}));

/**
 * The tile's glyph: the first letter of the language's own name, in its own script.
 *
 * A letter in the script beats a generic globe on every tile — ಕ, த and অ are
 * distinguishable at a glance and need no reading, whereas ten identical globes
 * carry no information at all. Derived rather than mapped so a language added
 * server-side gets a sensible glyph without a frontend change.
 *
 * Array.from, not [0]: indexing a string splits surrogate pairs and would render
 * half a codepoint.
 */
function scriptGlyph(nativeName: string): string {
  return Array.from(nativeName)[0] ?? "?";
}

export function LanguageSelectPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [languages, setLanguages] = useState<LanguageItem[]>(FALLBACK);

  useEffect(() => {
    let cancelled = false;

    api<{ languages: LanguageItem[] }>("/languages", { skipAuth: true })
      .then((res) => {
        // Only fully-supported languages are offered: screen text, audio and
        // speech recognition all present. Listing a language that half-works
        // would contradict the promise this screen makes — that picking Tamil
        // means Tamil throughout, not Tamil audio over an English screen.
        const offerable = res.languages.filter(
          (l) => l.support === "full" && isSupportedLanguage(l.code),
        );
        if (!cancelled && offerable.length > 0) setLanguages(offerable);
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, []);

  const handleSelect = async (code: string) => {
    // One choice, applied everywhere: screen text, audio prompts, and the
    // language speech is transcribed in.
    await setLanguage(code);
    navigate("/login");
  };

  // No forced min-height: the tiles now sit in two rows, so reserving a
  // near-full viewport left a band of dead space that pushed the footer past the
  // fold on a kiosk screen.
  return (
    <main className="flex flex-col items-center justify-center px-6 py-6">
      {/* Ayushman Bharat welcome banner */}
      <div
        className="relative mb-6 w-full max-w-5xl overflow-hidden rounded-xl px-6 py-5 text-center text-white shadow-lg"
        style={{
          background: "linear-gradient(135deg, #002B5B 0%, #0F4C81 40%, #0F6DB8 100%)",
        }}
      >
        <div className="absolute left-0 top-0 opacity-60">
          <CornerMotif size={60} />
        </div>
        <div className="absolute bottom-0 right-0 rotate-180 opacity-60">
          <CornerMotif size={60} />
        </div>

        <div className="relative z-10 flex flex-col items-center gap-3">
          <img
            src="/kiosk/abdm-logo.png"
            alt="Ayushman Bharat Digital Mission"
            className="h-16 w-auto"
          />
          <span className="text-sm font-semibold tracking-wide text-saffron-light">
            आयुष्मान भारत · Ayushman Bharat
          </span>
          <p className="text-xs text-blue-200 opacity-80">
            Digital Health Mission — AI-Powered Patient Intake Kiosk
          </p>
        </div>
      </div>

      {/* Language icon */}
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full border-2 border-primary-200 bg-primary-50 text-primary-600">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-10 w-10"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129"
          />
        </svg>
      </div>

      <h1 className="mb-2 text-center text-2xl font-bold text-primary-600">
        {t("languageSelect.title")}
      </h1>
      <p className="mb-6 max-w-md text-center text-base text-gray-600">
        {t("languageSelect.subtitle")}
      </p>

      {/* Five across on a kiosk screen, so the ten languages read as one block
          the eye can scan rather than a list that runs off the fold. Narrower
          breakpoints step down instead of shrinking the tiles, because these are
          touch targets first and a cramped row is a mis-tap. */}
      <div className="grid w-full max-w-5xl grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {languages.map((lang) => (
          <button
            key={lang.code}
            onClick={() => void handleSelect(lang.code)}
            lang={lang.code}
            className="govt-card govt-card-hover flex min-h-[7rem] flex-col items-center justify-center gap-2 p-4 text-center"
            aria-label={`${t("languageSelect.select")} ${lang.native_name}`}
          >
            {/* A letter from the language's own alphabet, not a globe. */}
            <span
              lang={lang.code}
              aria-hidden="true"
              className="flex h-11 w-11 items-center justify-center rounded-full text-2xl font-semibold leading-none text-white"
              style={{
                background: "linear-gradient(135deg, #002B5B 0%, #0F6DB8 100%)",
              }}
            >
              {scriptGlyph(lang.native_name)}
            </span>
            {/* Native name leads, because a patient who cannot read English
                cannot read "Tamil" either but will recognise "தமிழ்". The English
                name follows in brackets for whoever is helping them. */}
            <span className="block text-lg font-semibold leading-tight text-gray-900">
              {lang.native_name}
            </span>
            <span className="block text-xs leading-tight text-gray-500">({lang.name})</span>
          </button>
        ))}
      </div>
    </main>
  );
}
