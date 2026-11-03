/**
 * InterviewPage — the dual-mode (voice + touch) interview screen.
 *
 * Design principles:
 * - Large touch targets (elderly/low-literacy patients)
 * - Every question answerable by voice OR touch
 * - Red-flag alerts shown immediately, mid-interview
 * - Progress ring showing % of questions answered
 * - Typewriter effect on question text
 * - Pulse animation on active mic button
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { getLanguage } from "../store/language";
import { Spinner } from "../components/Spinner";
import { getVisitSelection, setCompletedInterview } from "../store/visit";
import {
  type AnswerResult,
  type ProgressData,
  type QuestionData,
  type RedFlagData,
  completeSession,
  fetchAudioClip,
  skipQuestion,
  startSession,
  submitAnswer,
  transcribeAudio,
} from "../api/interview";

// ---------------------------------------------------------------------------
// Progress Ring (SVG circle)
// ---------------------------------------------------------------------------

function ProgressRing({ percent }: { percent: number }) {
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (percent / 100) * circumference;

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width="100" height="100" className="rotate-[-90deg]">
        {/* Background circle */}
        <circle cx="50" cy="50" r={radius} fill="none" stroke="#E0E0E0" strokeWidth="8" />
        {/* Progress circle */}
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          stroke="#1A237E"
          strokeWidth="8"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-500 ease-out"
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-sm font-bold text-primary-600">
        {percent}%
      </span>
    </div>
  );
}

function ProgressBar({ progress }: { progress: ProgressData }) {
  if (progress.awaiting_chief_complaint) return null;

  return (
    <div className="flex items-center gap-4">
      <ProgressRing percent={progress.percent} />
      <div className="flex-1">
        <div className="mb-1 flex justify-between text-sm text-gray-600">
          <span>
            {progress.answered} / {progress.total} questions
          </span>
          <span>{progress.percent}%</span>
        </div>
        <div className="h-2 w-full rounded-full bg-gray-200">
          <div
            className="h-2 rounded-full bg-primary-600 transition-all duration-500"
            style={{ width: `${progress.percent}%` }}
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Typewriter text
// ---------------------------------------------------------------------------

function TypewriterText({ text, speed = 30 }: { text: string; speed?: number }) {
  const [displayed, setDisplayed] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    setDisplayed("");
    setDone(false);
    let i = 0;
    const interval = setInterval(() => {
      i++;
      setDisplayed(text.slice(0, i));
      if (i >= text.length) {
        clearInterval(interval);
        setDone(true);
      }
    }, speed);
    return () => clearInterval(interval);
  }, [text, speed]);

  return <span className={done ? "" : "typewriter"}>{displayed}</span>;
}

// ---------------------------------------------------------------------------
// Red Flag Alert
// ---------------------------------------------------------------------------

function RedFlagAlert({ flags }: { flags: RedFlagData[] }) {
  const { t } = useTranslation();
  if (flags.length === 0) return null;

  return (
    <div
      className="mx-auto mb-4 max-w-2xl rounded-md border-2 border-red-400 bg-red-50 p-4"
      role="alert"
      aria-live="assertive"
    >
      <div className="flex items-center gap-3">
        <svg
          className="h-6 w-6 shrink-0 text-red-600"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
        >
          <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0zM12 9v4M12 17h.01" />
        </svg>
        <div>
          <h3 className="text-base font-bold text-red-800">
            {t("interview.redFlagTitle", "Priority Alert — Please inform staff")}
          </h3>
          {flags.map((f) => (
            <p key={f.id} className="mt-1 text-sm text-red-700">
              <span className="font-semibold">[{f.severity.toUpperCase()}]</span> {f.name}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mic Button with pulse rings
// ---------------------------------------------------------------------------

type MicState = "idle" | "recording" | "transcribing" | "done" | "error";

function MicButton({
  micState,
  transcript,
  onStart,
  onStop,
}: {
  micState: MicState;
  transcript: string;
  onStart: () => void;
  onStop: () => void;
}) {
  const { t } = useTranslation();

  const stateConfig: Record<MicState, { bg: string; label: string; icon: string }> = {
    idle: {
      bg: "bg-primary-50 text-primary-600 border-primary-200 hover:bg-primary-100",
      label: t("interview.holdToSpeak", "Hold to speak"),
      icon: "●",
    },
    recording: {
      bg: "bg-red-500 text-white border-red-500",
      label: t("interview.recording", "Recording… release to send"),
      icon: "●",
    },
    transcribing: {
      bg: "bg-saffron/10 text-saffron-dark border-saffron/30 cursor-wait",
      label: t("interview.transcribing", "Transcribing…"),
      icon: "…",
    },
    done: {
      bg: "bg-govgreen/10 text-govgreen border-govgreen/30",
      label: t("interview.transcribed", "Got it!"),
      icon: "✓",
    },
    error: {
      bg: "bg-red-50 text-red-600 border-red-200",
      label: t("interview.micError", "Could not access microphone"),
      icon: "✗",
    },
  };

  const cfg = stateConfig[micState];
  const isRecording = micState === "recording";
  const isBusy = micState === "transcribing";

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative">
        {/* Pulse rings when recording */}
        {isRecording && (
          <>
            <div className="mic-pulse-ring" />
            <div className="mic-pulse-ring" />
            <div className="mic-pulse-ring" />
          </>
        )}
        <button
          type="button"
          onMouseDown={isBusy ? undefined : onStart}
          onMouseUp={isRecording ? onStop : undefined}
          onTouchStart={isBusy ? undefined : onStart}
          onTouchEnd={isRecording ? onStop : undefined}
          disabled={isBusy}
          className={`relative flex h-16 w-16 items-center justify-center rounded-full border-2 text-2xl transition-all duration-200 ${cfg.bg} disabled:cursor-not-allowed`}
          aria-label={cfg.label}
        >
          {cfg.icon}
        </button>
      </div>

      <p
        className={`text-sm font-medium ${
          micState === "recording"
            ? "text-red-600"
            : micState === "transcribing"
              ? "text-saffron-dark"
              : micState === "done"
                ? "text-govgreen"
                : micState === "error"
                  ? "text-red-500"
                  : "text-gray-500"
        }`}
      >
        {cfg.label}
      </p>

      {transcript && micState === "done" && (
        <div className="w-full max-w-sm rounded-md border border-govgreen/20 bg-govgreen/5 px-4 py-2 text-sm text-govgreen-dark">
          <span className="font-semibold">Heard: </span>
          {transcript}
        </div>
      )}

      {transcript.startsWith("[Mock ASR]") && (
        <div className="w-full max-w-sm rounded-md border border-saffron/20 bg-saffron/5 px-4 py-2 text-xs text-saffron-dark">
          ASR not configured — set WHISPER_API_URL in backend/.env to enable real voice input.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main InterviewPage
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Skip Interview Modal (password-locked, demo shortcut)
// ---------------------------------------------------------------------------

function SkipInterviewModal({
  open,
  onClose,
  onSuccess,
}: {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [pw, setPw] = useState("");
  const [shake, setShake] = useState(false);

  if (!open) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (pw === "winexe") {
      onSuccess();
    } else {
      setShake(true);
      setTimeout(() => setShake(false), 500);
      setPw("");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      {/* inline shake keyframe so we don't touch tailwind.config */}
      <style>{`@keyframes shake{0%,100%{transform:translateX(0)}20%,60%{transform:translateX(-6px)}40%,80%{transform:translateX(6px)}}`}</style>
      <form
        onSubmit={handleSubmit}
        className="w-80 rounded-xl bg-white p-6 shadow-xl"
        style={shake ? { animation: "shake 0.4s ease" } : undefined}
      >
        <h3 className="mb-1 text-base font-bold text-gray-800">Skip Interview</h3>
        <p className="mb-4 text-xs text-gray-500">Enter admin password to skip</p>
        <input
          type="password"
          autoFocus
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          placeholder="Password"
          className="mb-3 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200"
        />
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 rounded-md border border-gray-300 py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            className="flex-1 rounded-md bg-primary-600 py-2 text-sm font-semibold text-white hover:bg-primary-700"
          >
            Unlock
          </button>
        </div>
      </form>
    </div>
  );
}

export function InterviewPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  /** The patient's single language: screen text, audio, and transcription alike.
   *
   * Read from the store rather than `i18n.language` so a mid-interview refresh
   * keeps the choice; the store falls back to i18next when nothing is stored.
   */
  const lang = getLanguage();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState<QuestionData | null>(null);
  const [progress, setProgress] = useState<ProgressData>({
    answered: 0,
    total: 1,
    percent: 0,
    awaiting_chief_complaint: true,
  });
  const [redFlags, setRedFlags] = useState<RedFlagData[]>([]);
  const [complete, setComplete] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);

  /** Interview mode is DERIVED from the department the patient already picked on
   * the selection screen — the Ayurveda department is an AYUSH interview, every
   * other department is a general/allopathic one. It is not asked again here: a
   * second mode question after the department choice is the same decision twice.
   */
  const visitSelection = getVisitSelection();
  const mode: "general" | "ayush" =
    visitSelection?.department === "AYUSH" || visitSelection?.department === "Ayurveda"
      ? "ayush"
      : "general";

  const [micState, setMicState] = useState<MicState>("idle");
  const [lastTranscript, setLastTranscript] = useState("");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  // Skip-interview modal state
  const [showSkipModal, setShowSkipModal] = useState(false);

  const [selectedOptions, setSelectedOptions] = useState<string[]>([]);
  const [freeText, setFreeText] = useState("");

  // Skip entire interview (admin shortcut) — navigates to document upload
  const handleSkipInterview = useCallback(() => {
    setShowSkipModal(false);
    // Use a sentinel session id so downstream pages know it was skipped
    setCompletedInterview("skipped");
    navigate("/documents/upload");
  }, [navigate]);

  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Autoplay question audio
  useEffect(() => {
    const url = question?.audio_url;
    if (audioRef.current) {
      audioRef.current.pause();
      URL.revokeObjectURL(audioRef.current.src);
      audioRef.current = null;
    }
    if (!url) return;

    let revoked = false;
    let objectUrl: string | null = null;

    fetchAudioClip(url)
      .then((src) => {
        if (revoked) {
          URL.revokeObjectURL(src);
          return;
        }
        objectUrl = src;
        const element = new Audio(src);
        audioRef.current = element;
        void element.play().catch(() => undefined);
      })
      .catch(() => undefined);

    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [question?.field_id, question?.audio_url]);

  const replayPrompt = useCallback(() => {
    const element = audioRef.current;
    if (!element) return;
    element.currentTime = 0;
    void element.play().catch(() => undefined);
  }, []);

  const handleStart = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const session = await startSession(mode);
      setSessionId(session.session_id);
      setQuestion(session.next_question);
      setProgress(session.progress);
      setStarted(true);
    } catch (e) {
      setError((e as Error).message || "Failed to start session");
    } finally {
      setLoading(false);
    }
  }, [mode]);

  const handleAnswer = useCallback(
    async (value: unknown, inputMode: "voice" | "touch" = "touch", transcript?: string) => {
      if (!sessionId || !question) return;
      setLoading(true);
      setError(null);
      try {
        const result: AnswerResult = await submitAnswer(
          sessionId,
          question.field_id,
          value,
          inputMode,
          transcript,
        );
        setQuestion(result.next_question);
        setProgress(result.progress);
        if (result.red_flags_fired.length > 0) {
          setRedFlags((prev) => [...prev, ...result.red_flags_fired]);
        }
        if (result.interview_complete) {
          await completeSession(sessionId);
          setCompletedInterview(sessionId);
          setComplete(true);
        }
        setSelectedOptions([]);
        setFreeText("");
      } catch (e) {
        setError((e as Error).message || "Failed to submit answer");
      } finally {
        setLoading(false);
      }
    },
    [sessionId, question],
  );

  const handleSkip = useCallback(async () => {
    if (!sessionId || !question) return;
    setLoading(true);
    setError(null);
    try {
      const result = await skipQuestion(sessionId, question.field_id);
      setQuestion(result.next_question);
      setProgress(result.progress);
      if (result.red_flags_fired.length > 0) {
        setRedFlags((prev) => [...prev, ...result.red_flags_fired]);
      }
      if (result.interview_complete) {
        await completeSession(sessionId);
        setCompletedInterview(sessionId);
        setComplete(true);
      }
      setSelectedOptions([]);
      setFreeText("");
    } catch (e) {
      setError((e as Error).message || "Failed to skip question");
    } finally {
      setLoading(false);
    }
  }, [sessionId, question]);

  // Voice recording handlers
  const startRecording = useCallback(async () => {
    setLastTranscript("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Negotiate the best audio format the browser supports (iOS needs mp4, Android/PC prefer webm)
      let mimeType = "";
      if (MediaRecorder.isTypeSupported("audio/webm")) {
        mimeType = "audio/webm";
      } else if (MediaRecorder.isTypeSupported("audio/mp4")) {
        mimeType = "audio/mp4";
      }

      const mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      mediaRecorder.ondataavailable = (e) => chunksRef.current.push(e.data);
      mediaRecorder.start();
      mediaRecorderRef.current = mediaRecorder;
      setMicState("recording");
    } catch {
      setMicState("error");
      setError(
        t(
          "interview.micError",
          "Could not access microphone. Please allow microphone access and try again.",
        ),
      );
    }
  }, [t]);

  const stopRecording = useCallback(async () => {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state !== "recording") return;

    setMicState("transcribing");

    const stopped = new Promise<void>((resolve) => {
      recorder.addEventListener("stop", () => resolve(), { once: true });
    });

    recorder.stop();
    await stopped;
    recorder.stream.getTracks().forEach((track) => track.stop());
    mediaRecorderRef.current = null;

    const mimeType = recorder.mimeType || "audio/webm";
    const audioBlob = new Blob(chunksRef.current, { type: mimeType });

    if (audioBlob.size === 0) {
      setMicState("idle");
      setError(t("interview.tooShort", "That was too short. Hold the button while you speak."));
      return;
    }

    setLoading(true);
    try {
      const asrResult = await transcribeAudio(audioBlob, lang);
      setLastTranscript(asrResult.text);

      if (!asrResult.text.trim() || asrResult.text.startsWith("[Mock ASR]")) {
        setMicState("done");
        setLoading(false);
        if (!asrResult.text.trim()) {
          setError(t("interview.notHeard", "Sorry, we could not hear that. Please try again."));
          setMicState("idle");
        }
        return;
      }

      setMicState("done");
      await handleAnswer(asrResult.text, "voice", asrResult.text);
      setTimeout(() => setMicState("idle"), 1500);
    } catch (e) {
      setMicState("error");
      setError((e as Error).message || "Transcription failed");
      setTimeout(() => setMicState("idle"), 2000);
    } finally {
      setLoading(false);
    }
  }, [lang, handleAnswer, t]);

  // ---------------------------------------------------------------------------
  // Render: Intro screen (before start) — shows the derived interview type
  // ---------------------------------------------------------------------------

  // Floating skip button + modal (rendered in every state)
  const skipInterviewOverlay = (
    <>
      <button
        type="button"
        onClick={() => setShowSkipModal(true)}
        title="Skip Interview (admin)"
        className="fixed bottom-4 right-4 z-40 flex h-9 items-center gap-1.5 rounded-full border border-gray-200 bg-white/80 px-3 text-xs font-medium text-gray-400 shadow-sm backdrop-blur transition-colors hover:border-gray-400 hover:text-gray-600"
      >
        Skip
      </button>
      <SkipInterviewModal
        open={showSkipModal}
        onClose={() => setShowSkipModal(false)}
        onSuccess={handleSkipInterview}
      />
    </>
  );

  if (!started) {
    return (
      <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center justify-center gap-6 px-6 py-8">
        {skipInterviewOverlay}
        <img src="/kiosk/abdm-logo.png" alt="ABDM" className="h-14 w-auto opacity-80" />
        <h1 className="text-2xl font-bold text-primary-600">
          {t("interview.title", "Health Interview")}
        </h1>
        <p className="max-w-md text-center text-base text-gray-600">
          {t(
            "interview.subtitle",
            "We'll ask you some questions about your health. You can speak or tap your answers.",
          )}
        </p>

        {/* Interview type is shown for context only — it was decided by the
            department the patient already chose, so there is nothing to pick. */}
        <div className="w-full max-w-md rounded-xl border border-gray-200 bg-white px-6 py-5 text-center shadow-sm">
          {visitSelection?.department && (
            <p className="text-sm text-gray-500">
              {t("interview.departmentLabel", "Department")}:{" "}
              <span className="font-semibold text-gray-700">{visitSelection.department}</span>
            </p>
          )}
          <p className="mt-1 text-lg font-bold text-primary-600">
            {mode === "ayush"
              ? t("interview.modeAyush", "AYUSH / Ayurvedic")
              : t("interview.modeGeneral", "General / Allopathic")}
          </p>
          <p className="mt-1 text-xs font-normal text-gray-400">
            {mode === "ayush"
              ? t("interview.modeAyushHint", "Includes Prakriti & Dashavidha Pariksha")
              : t("interview.modeGeneralHint", "Standard clinical history")}
          </p>
        </div>

        <button
          type="button"
          onClick={handleStart}
          disabled={loading}
          className="btn-primary mt-4 px-10 py-4 text-lg"
        >
          {loading ? (
            <Spinner size="sm" className="border-white/40 border-t-white" />
          ) : (
            t("interview.start", "Start Interview")
          )}
        </button>
      </main>
    );
  }

  // ---------------------------------------------------------------------------
  // Render: Interview complete
  // ---------------------------------------------------------------------------

  if (complete) {
    return (
      <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center justify-center gap-6 px-6 py-8">
        {skipInterviewOverlay}
        <RedFlagAlert flags={redFlags} />
        <div className="w-full max-w-lg text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-govgreen/10">
            <svg
              className="h-8 w-8 text-govgreen"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2.5}
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-govgreen">{t("interview.complete")}</h1>
          <p className="mt-3 text-base text-gray-600">{t("interview.completeMsg")}</p>

          <div className="mt-6">
            <ProgressBar progress={progress} />
          </div>

          <div className="mt-6 flex flex-col gap-3">
            <button
              type="button"
              onClick={() => navigate("/patient-summary")}
              className="btn-primary w-full py-4 text-lg"
            >
              {t("interview.viewSummary", "Review My Summary")}
            </button>
          </div>
        </div>
      </main>
    );
  }

  // ---------------------------------------------------------------------------
  // Render: Active question
  // ---------------------------------------------------------------------------

  // The backend resolves the prompt into the patient's language. The authored
  // English/Hindi pair is only a fallback for an older backend response.
  const prompt = question?.prompt || (lang === "hi" ? question?.prompt_hi : question?.prompt_en);

  return (
    <main className="mx-auto flex min-h-[calc(100vh-10rem)] max-w-2xl flex-col gap-4 px-6 py-6">
      {skipInterviewOverlay}
      <RedFlagAlert flags={redFlags} />
      <ProgressBar progress={progress} />

      {error && (
        <div
          className="rounded-md border border-saffron/30 bg-saffron/5 p-3 text-sm text-saffron-dark"
          role="alert"
        >
          {error}
        </div>
      )}

      {question && (
        <div className="govt-card p-6">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            {question.section.replace(/_/g, " ")}
          </p>
          <h2 className="mb-5 text-xl font-bold text-primary-600">
            {prompt && <TypewriterText text={prompt} speed={30} />}
          </h2>

          {/* -- Single choice / Yes-No -- */}
          {(question.input_type === "single_choice" || question.input_type === "yes_no") && (
            <div className="grid gap-2">
              {question.input_type === "yes_no" ? (
                <>
                  <button
                    type="button"
                    onClick={() => handleAnswer(true, "touch")}
                    disabled={loading}
                    className="w-full rounded-md border border-govgreen/30 bg-govgreen/5 px-5 py-4 text-left text-lg font-semibold text-govgreen-dark transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md disabled:opacity-50"
                  >
                    {t("common.yes")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleAnswer(false, "touch")}
                    disabled={loading}
                    className="w-full rounded-md border border-red-200 bg-red-50 px-5 py-4 text-left text-lg font-semibold text-red-700 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md disabled:opacity-50"
                  >
                    {t("common.no")}
                  </button>
                </>
              ) : (
                question.options.map((opt) => (
                  <button
                    key={opt.key}
                    type="button"
                    onClick={() => handleAnswer(opt.key, "touch")}
                    disabled={loading}
                    className="w-full rounded-md border border-gray-200 bg-surface-section px-5 py-4 text-left text-lg font-semibold text-gray-800 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary-400 hover:shadow-md disabled:opacity-50"
                  >
                    {opt.label || (lang === "hi" ? opt.label_hi : opt.label_en)}
                  </button>
                ))
              )}
            </div>
          )}

          {/* -- Multi choice -- */}
          {question.input_type === "multi_choice" && (
            <div className="grid gap-2">
              {question.options.map((opt) => (
                <button
                  key={opt.key}
                  type="button"
                  onClick={() => {
                    setSelectedOptions((prev) =>
                      prev.includes(opt.key)
                        ? prev.filter((k) => k !== opt.key)
                        : [...prev, opt.key],
                    );
                  }}
                  className={`w-full rounded-md border px-5 py-4 text-left text-lg font-semibold transition-all duration-200 hover:-translate-y-0.5 ${
                    selectedOptions.includes(opt.key)
                      ? "border-primary-600 bg-primary-50 text-primary-800"
                      : "border-gray-200 bg-surface-section text-gray-800 hover:border-primary-300 hover:shadow-sm"
                  }`}
                >
                  {selectedOptions.includes(opt.key) ? "✓ " : ""}
                  {opt.label || (lang === "hi" ? opt.label_hi : opt.label_en)}
                </button>
              ))}
              <button
                type="button"
                onClick={() => handleAnswer(selectedOptions, "touch")}
                disabled={loading || selectedOptions.length === 0}
                className="btn-primary mt-3 w-full py-3 text-lg"
              >
                {t("interview.confirm", "Confirm")}
              </button>
            </div>
          )}

          {/* -- Free text -- */}
          {question.input_type === "free_text" && (
            <div className="space-y-3">
              <textarea
                value={freeText}
                onChange={(e) => setFreeText(e.target.value)}
                placeholder={
                  lang === "hi" ? "यहाँ टाइप करें या नीचे बोलें..." : "Type here or speak below..."
                }
                className="h-28 w-full rounded-md border border-gray-300 p-4 text-base focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200"
              />
              <button
                type="button"
                onClick={() => handleAnswer(freeText, "touch")}
                disabled={loading || !freeText.trim()}
                className="btn-primary w-full py-3 text-lg"
              >
                {t("interview.submit", "Submit")}
              </button>
            </div>
          )}

          {/* -- Numeric (1-10 scale) -- */}
          {question.input_type === "numeric" && (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => handleAnswer(n, "touch")}
                    disabled={loading}
                    className={`flex h-14 w-14 items-center justify-center rounded-md border text-lg font-bold transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md ${
                      n >= 8
                        ? "border-red-200 bg-red-50 text-red-700"
                        : n >= 5
                          ? "border-saffron/30 bg-saffron/5 text-saffron-dark"
                          : "border-govgreen/30 bg-govgreen/5 text-govgreen-dark"
                    } disabled:opacity-50`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Replay prompt */}
          {question.audio_url && (
            <button
              type="button"
              onClick={replayPrompt}
              className="mt-4 flex items-center gap-2 rounded-md px-3 py-2 text-base text-primary-600 hover:bg-primary-50"
            >
              <span aria-hidden="true">🔊</span>
              {t("interview.replay", "Hear the question again")}
            </button>
          )}

          {/* Voice input */}
          <div className="mt-6 flex flex-col items-center gap-2 border-t border-gray-100 pt-5">
            <MicButton
              micState={micState}
              transcript={lastTranscript}
              onStart={startRecording}
              onStop={stopRecording}
            />
          </div>

          {/* Skip */}
          {!question.required && (
            <button
              type="button"
              onClick={handleSkip}
              disabled={loading}
              className="mt-3 w-full text-center text-sm text-gray-400 underline hover:text-gray-600"
            >
              {t("interview.skip", "Skip this question")}
            </button>
          )}
        </div>
      )}
    </main>
  );
}
