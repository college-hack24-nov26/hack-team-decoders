import { describe, expect, it } from "vitest";
import type { QuestionData } from "../api/interview";
import { matchVoiceAnswer } from "./voiceAnswer";

function question(partial: Partial<QuestionData>): QuestionData {
  return {
    field_id: "q",
    section: "hpi",
    prompt_en: "",
    prompt_hi: "",
    input_type: "single_choice",
    options: [],
    required: true,
    audio_url: null,
    ...partial,
  };
}

const chiefComplaint = question({
  field_id: "chief_complaint",
  options: [
    { key: "chest_pain", label_en: "Chest pain", label_hi: "सीने में दर्द" },
    { key: "fever", label_en: "Fever", label_hi: "बुखार" },
    { key: "abdominal_pain", label_en: "Stomach / abdominal pain", label_hi: "पेट दर्द" },
    { key: "other", label_en: "Something else", label_hi: "कुछ और" },
  ],
});

describe("matchVoiceAnswer", () => {
  it("maps a spoken sentence to the option key", () => {
    expect(matchVoiceAnswer(chiefComplaint, "I have had fever since Monday")).toEqual({
      ok: true,
      value: "fever",
    });
  });

  it("matches Hindi labels and either half of a split label", () => {
    expect(matchVoiceAnswer(chiefComplaint, "मुझे बुखार है")).toEqual({ ok: true, value: "fever" });
    expect(matchVoiceAnswer(chiefComplaint, "my stomach hurts")).toEqual({
      ok: true,
      value: "abdominal_pain",
    });
  });

  it("routes an unrecognised chief complaint to other", () => {
    expect(matchVoiceAnswer(chiefComplaint, "my knee is swollen")).toEqual({
      ok: true,
      value: "other",
    });
  });

  it("reads yes and no, with no taking precedence", () => {
    const q = question({ input_type: "yes_no" });
    expect(matchVoiceAnswer(q, "yes I do")).toEqual({ ok: true, value: true });
    expect(matchVoiceAnswer(q, "nahi")).toEqual({ ok: true, value: false });
    expect(matchVoiceAnswer(q, "no ha I don't")).toEqual({ ok: true, value: false });
    expect(matchVoiceAnswer(q, "maybe")).toEqual({ ok: false });
  });

  it("reads severity numbers as digits or words", () => {
    const q = question({ input_type: "numeric" });
    expect(matchVoiceAnswer(q, "about 7")).toEqual({ ok: true, value: 7 });
    expect(matchVoiceAnswer(q, "five")).toEqual({ ok: true, value: 5 });
    expect(matchVoiceAnswer(q, "पाँच")).toEqual({ ok: true, value: 5 });
    expect(matchVoiceAnswer(q, "very bad")).toEqual({ ok: false });
  });

  it("passes free text through", () => {
    const q = question({ input_type: "free_text" });
    expect(matchVoiceAnswer(q, "  paracetamol twice a day ")).toEqual({
      ok: true,
      value: "paracetamol twice a day",
    });
  });
});
