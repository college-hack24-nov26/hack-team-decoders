/**
 * Interview API functions — typed wrappers for the Module A endpoints.
 */

import { getLanguage } from "../store/language";
import { api } from "./client";

/**
 * `?language=` for every interview call.
 *
 * Sent explicitly rather than relying on the patient record, which is a snapshot
 * from registration. The header dropdown can change the choice at any point, and
 * the interface strings are bundled client-side — so without this the screen
 * followed the dropdown while the questions and audio stayed in the language the
 * patient registered in.
 */
function langQuery(): string {
  return `?language=${encodeURIComponent(getLanguage())}`;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface QuestionOption {
  key: string;
  label_en: string;
  label_hi: string;
  /** Label already resolved into the patient's language. Prefer this: the
   *  _en/_hi pair only covers two of the 23 languages supported. */
  label?: string;
}

export interface QuestionData {
  field_id: string;
  section: string;
  prompt_en: string;
  prompt_hi: string;
  /** Prompt already resolved into the patient's language, translated by the
   *  backend for the languages that are not hand-authored. */
  prompt?: string;
  /** Language `prompt` and the option `label`s are actually in. */
  language?: string;
  input_type: "single_choice" | "multi_choice" | "free_text" | "yes_no" | "numeric" | "date";
  options: QuestionOption[];
  required: boolean;
  audio_url: string | null;
}

export interface ProgressData {
  answered: number;
  total: number;
  percent: number;
  /**
   * True until the chief complaint is answered, while the real total is still
   * unknown. Hide the bar rather than show a number that is about to change.
   */
  awaiting_chief_complaint: boolean;
}

export interface RedFlagData {
  id: string;
  name: string;
  description: string;
  severity: "critical" | "high" | "moderate";
  triggered_at: string;
}

export interface SessionData {
  session_id: string;
  status: string;
  mode: string;
  chief_complaint: string | null;
  progress: ProgressData;
  next_question: QuestionData | null;
}

export interface AnswerResult {
  accepted: boolean;
  red_flags_fired: RedFlagData[];
  next_question: QuestionData | null;
  progress: ProgressData;
  interview_complete: boolean;
}

export interface AsrResult {
  text: string;
  language: string;
  confidence: number;
  is_mock: boolean;
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export async function startSession(mode: "general" | "ayush"): Promise<SessionData> {
  return api<SessionData>(`/interview/sessions${langQuery()}`, {
    method: "POST",
    body: { mode },
  });
}

export async function getNextQuestion(sessionId: string): Promise<QuestionData | null> {
  return api<QuestionData | null>(`/interview/sessions/${sessionId}/next-question${langQuery()}`);
}

export async function submitAnswer(
  sessionId: string,
  fieldId: string,
  value: unknown,
  inputMode: "voice" | "touch",
  rawTranscript?: string,
): Promise<AnswerResult> {
  return api<AnswerResult>(`/interview/sessions/${sessionId}/answer${langQuery()}`, {
    method: "POST",
    body: {
      field_id: fieldId,
      value,
      input_mode: inputMode,
      raw_transcript: rawTranscript ?? null,
    },
  });
}

/** Decline an optional question. Recorded as an explicit skip, not as a value. */
export async function skipQuestion(sessionId: string, fieldId: string): Promise<AnswerResult> {
  return api<AnswerResult>(`/interview/sessions/${sessionId}/answer${langQuery()}`, {
    method: "POST",
    body: { field_id: fieldId, skipped: true, input_mode: "touch" },
  });
}

/**
 * Fetch a TTS clip as a playable object URL.
 *
 * Done with fetch rather than pointing an <audio src> straight at the URL
 * because the audio route is bearer-authenticated and an <audio> element sends
 * no Authorization header.
 */
export async function fetchAudioClip(audioUrl: string): Promise<string> {
  const API_ROOT = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
  const token = sessionStorage.getItem("medikiosk_token");

  const res = await fetch(`${API_ROOT}${audioUrl}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`Audio fetch failed: ${res.status}`);

  return URL.createObjectURL(await res.blob());
}

export async function completeSession(
  sessionId: string,
): Promise<{ session_id: string; status: string; completed_at: string }> {
  return api(`/interview/sessions/${sessionId}/complete`, { method: "POST" });
}

export interface ReviewItem {
  field_id: string;
  section: string;
  question: string;
  answer: string;
  skipped: boolean;
}

export interface SessionReview {
  session_id: string;
  status: string;
  mode: string;
  chief_complaint: string | null;
  language: string;
  items: ReviewItem[];
}

/** The patient's own answers, question by question, in their language. */
export async function getSessionReview(sessionId: string): Promise<SessionReview> {
  return api<SessionReview>(`/interview/sessions/${sessionId}/review${langQuery()}`);
}

export async function getRedFlags(sessionId: string): Promise<RedFlagData[]> {
  return api<RedFlagData[]>(`/interview/sessions/${sessionId}/red-flags`);
}

export async function transcribeAudio(audioBlob: Blob, language?: string): Promise<AsrResult> {
  const formData = new FormData();
  const extension = audioBlob.type.includes("mp4") ? "mp4" : "webm";
  formData.append("file", audioBlob, `recording.${extension}`);
  // Defaults to the active choice so speech is transcribed in the language the
  // patient is actually being addressed in, not the one they registered with.
  formData.append("language", language ?? getLanguage());

  const API_ROOT = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
  const token = sessionStorage.getItem("medikiosk_token");

  const res = await fetch(`${API_ROOT}/api/v1/interview/asr`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });

  if (!res.ok) throw new Error(`ASR failed: ${res.status}`);
  return res.json();
}
