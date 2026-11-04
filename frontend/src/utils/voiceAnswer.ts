/**
 * Turn a spoken transcript into an answer the interview API understands.
 *
 * Choice questions store option *keys* ("fever", "days"), and the red-flag rules
 * and HPI templates match on those keys. Sending the raw sentence ("I have had
 * fever for three days") stored text no rule recognised, so a spoken chief
 * complaint silently fell through to the generic template. This maps speech to
 * the option the patient meant, or reports that it could not.
 */

import type { QuestionData } from "../api/interview";

export type VoiceMatch = { ok: true; value: unknown } | { ok: false };

const YES_WORDS = [
  "yes",
  "yeah",
  "yep",
  "haan",
  "han",
  "ha",
  "ji",
  "हाँ",
  "हां",
  "जी",
  "होय",
  "ஆம்",
  "అవును",
  "ಹೌದು",
  "അതെ",
  "হ্যাঁ",
  "હા",
  "ਹਾਂ",
];
const NO_WORDS = [
  "no",
  "nope",
  "nahi",
  "nahin",
  "na",
  "नहीं",
  "ना",
  "नाही",
  "இல்லை",
  "కాదు",
  "లేదు",
  "ಇಲ್ಲ",
  "ഇല്ല",
  "না",
  "ના",
  "ਨਹੀਂ",
];

const NUMBER_WORDS: Record<string, number> = {
  one: 1,
  two: 2,
  three: 3,
  four: 4,
  five: 5,
  six: 6,
  seven: 7,
  eight: 8,
  nine: 9,
  ten: 10,
  ek: 1,
  do: 2,
  teen: 3,
  char: 4,
  chaar: 4,
  paanch: 5,
  panch: 5,
  chhah: 6,
  che: 6,
  saat: 7,
  aath: 8,
  nau: 9,
  das: 10,
  एक: 1,
  दो: 2,
  तीन: 3,
  चार: 4,
  पांच: 5,
  पाँच: 5,
  छह: 6,
  सात: 7,
  आठ: 8,
  नौ: 9,
  दस: 10,
};

/** Lowercase, Devanagari digits to ASCII, punctuation to spaces. */
function normalise(text: string): string {
  return text
    .toLowerCase()
    .replace(/[०-९]/g, (d) => String("०१२३४५६७८९".indexOf(d)))
    .replace(/[.,!?;:()"'।]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function hasWord(text: string, word: string): boolean {
  const w = normalise(word);
  if (!w) return false;
  return ` ${text} `.includes(` ${w} `);
}

/** Every option whose label (any language) or key appears in the transcript. */
function matchingOptions(question: QuestionData, text: string): string[] {
  const hits: string[] = [];
  for (const opt of question.options) {
    const candidates = [opt.label, opt.label_en, opt.label_hi, opt.key.replace(/_/g, " ")]
      .filter((c): c is string => Boolean(c))
      // "Stomach / abdominal pain" should match on either half.
      .flatMap((c) => [c, ...c.split("/")])
      .map(normalise)
      .filter((c) => c.length > 1);
    if (
      candidates.some((c) => ` ${text} `.includes(` ${c} `) || (c.length > 3 && text.includes(c)))
    ) {
      hits.push(opt.key);
    }
  }
  return hits;
}

export function matchVoiceAnswer(question: QuestionData, transcript: string): VoiceMatch {
  const text = normalise(transcript);
  if (!text) return { ok: false };

  switch (question.input_type) {
    case "free_text":
    case "date":
      return { ok: true, value: transcript.trim() };

    case "yes_no": {
      // "No" first: "not really" / "nahi" must not read as yes because of "ha".
      if (NO_WORDS.some((w) => hasWord(text, w)) || hasWord(text, "not")) {
        return { ok: true, value: false };
      }
      if (YES_WORDS.some((w) => hasWord(text, w))) return { ok: true, value: true };
      return { ok: false };
    }

    case "numeric": {
      const digits = text.match(/\b(10|[1-9])\b/);
      if (digits) return { ok: true, value: Number(digits[1]) };
      for (const [word, n] of Object.entries(NUMBER_WORDS)) {
        if (hasWord(text, word)) return { ok: true, value: n };
      }
      return { ok: false };
    }

    case "single_choice": {
      const hits = matchingOptions(question, text);
      if (hits.length > 0) return { ok: true, value: hits[0] };
      // The chief complaint has an "other" bucket: better routed to the generic
      // template than lost.
      if (
        question.field_id === "chief_complaint" &&
        question.options.some((o) => o.key === "other")
      ) {
        return { ok: true, value: "other" };
      }
      return { ok: false };
    }

    case "multi_choice": {
      const hits = matchingOptions(question, text);
      return hits.length > 0 ? { ok: true, value: hits } : { ok: false };
    }

    default:
      return { ok: false };
  }
}
