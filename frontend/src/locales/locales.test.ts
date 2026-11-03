/**
 * Locale file tests.
 *
 * The important one is deep key parity across every locale: a string the UI asks
 * for but a locale lacks renders as "[some.key]" on screen (see
 * parseMissingKeyHandler in i18n.ts). English is the source of truth, and every
 * other locale is checked against it — previously only Hindi was, so the eight
 * generated locales could have drifted unnoticed.
 */

import { describe, expect, it } from "vitest";
import bn from "../locales/bn/translation.json";
import en from "../locales/en/translation.json";
import gu from "../locales/gu/translation.json";
import hi from "../locales/hi/translation.json";
import kn from "../locales/kn/translation.json";
import ml from "../locales/ml/translation.json";
import mr from "../locales/mr/translation.json";
import pa from "../locales/pa/translation.json";
import ta from "../locales/ta/translation.json";
import te from "../locales/te/translation.json";
import { SUPPORTED_LANGUAGES } from "../i18n";

type Json = Record<string, unknown>;

/** Every locale except the English source, which they are all compared against. */
const TRANSLATIONS: Record<string, Json> = {
  hi: hi as Json,
  bn: bn as Json,
  mr: mr as Json,
  te: te as Json,
  ta: ta as Json,
  gu: gu as Json,
  kn: kn as Json,
  ml: ml as Json,
  pa: pa as Json,
};

/** Generator bookkeeping, not user-facing copy, so excluded from comparisons. */
const META_KEY = "_meta";

/** Flatten to dotted leaf paths, e.g. "consent.sections.interview.title". */
function leafKeys(obj: Json, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([key, value]) => {
    if (!prefix && key === META_KEY) return [];
    const path = prefix ? `${prefix}.${key}` : key;
    return value !== null && typeof value === "object" ? leafKeys(value as Json, path) : [path];
  });
}

function valueAt(obj: Json, path: string): unknown {
  return path.split(".").reduce<unknown>((acc, part) => (acc as Json)?.[part], obj);
}

const enKeys = leafKeys(en as Json).sort();
const locales = Object.entries(TRANSLATIONS);

describe("locale files", () => {
  it("every language offered by i18n has a resource bundle", () => {
    for (const code of SUPPORTED_LANGUAGES) {
      const known = code === "en" || code in TRANSLATIONS;
      expect(known, `${code} is offered but has no locale file`).toBe(true);
    }
  });

  it("covers the Phase 1 screens", () => {
    for (const section of ["app", "languageSelect", "login", "consent", "interview", "common"]) {
      expect(en).toHaveProperty(section);
    }
  });

  it.each(locales)("%s has exactly the same keys as English", (_code, translation) => {
    expect(leafKeys(translation).sort()).toEqual(enKeys);
  });

  it.each(locales)("%s has no empty strings", (code, translation) => {
    for (const key of enKeys) {
      expect(String(valueAt(translation, key)).trim(), `${code}.${key}`).not.toHaveLength(0);
    }
  });

  it.each(locales)("%s keeps interpolation placeholders intact", (code, translation) => {
    // A dropped {{name}} silently renders the literal braces to the patient, and
    // a renamed one renders nothing at all.
    const placeholder = /\{\{(\w+)\}\}/g;
    for (const key of enKeys) {
      const enVars = [...String(valueAt(en as Json, key)).matchAll(placeholder)]
        .map((m) => m[1])
        .sort();
      const localeVars = [...String(valueAt(translation, key)).matchAll(placeholder)]
        .map((m) => m[1])
        .sort();
      expect(localeVars, `${code}.${key}`).toEqual(enVars);
    }
  });

  it.each(locales)("%s is actually translated, not copied from English", (code, translation) => {
    // Spot-check prose keys. Short UI labels can legitimately coincide; whole
    // sentences cannot, so a match here means the generator fell back silently.
    const prose = [
      "languageSelect.title",
      "login.title",
      "consent.title",
      "consent.audio.interview",
      "interview.title",
      "interview.subtitle",
      "common.error",
    ];
    for (const key of prose) {
      expect(valueAt(translation, key), `${code}.${key}`).not.toEqual(valueAt(en as Json, key));
    }
  });

  it.each(locales)("%s uses a non-Latin script for its prose", (code, translation) => {
    // Catches a locale that is really English text under an Indian language code,
    // which key parity and non-equality checks would both miss.
    const sample = String(valueAt(translation, "consent.audio.interview"));
    const nonLatin = [...sample].filter((ch) => ch.charCodeAt(0) > 0x0900).length;
    expect(nonLatin / sample.length, `${code} looks Latin-scripted`).toBeGreaterThan(0.4);
  });

  it("generated locales declare that they are unreviewed", () => {
    // Hindi is hand-written; the rest came from the generator and must say so, so
    // nobody mistakes machine output for reviewed clinical copy.
    for (const [code, translation] of locales) {
      if (code === "hi") continue;
      const meta = translation[META_KEY] as Record<string, string> | undefined;
      expect(meta?.reviewed, `${code} is missing its _meta.reviewed marker`).toBe("no");
    }
  });
});
