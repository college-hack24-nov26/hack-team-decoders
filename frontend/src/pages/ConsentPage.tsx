/**
 * Consent screen — granular, audio-guided, revocable consent capture.
 *
 * Built for a patient who cannot read the screen:
 *   - every section has a play/stop control that speaks the full explanation
 *     in the selected language
 *   - each scope is accepted individually, so optional scopes (documents,
 *     ABDM push) can be declined without blocking the visit
 *   - Continue unlocks once the mandatory scopes are accepted; playback is
 *     recorded, not required, so a literate patient in a queue is not held up
 *
 * The kiosk narrates itself: the first screen touch starts section one and
 * chains through the rest, like an attendant standing beside the patient.
 *
 * Audio comes from the server TTS provider (Sarvam), matching the interview
 * screens. The browser's SpeechSynthesis API is kept only as a fallback for when
 * the server has no TTS provider configured: it is device-dependent, sounds
 * robotic on kiosk hardware, and produces nothing at all on a device with no
 * Hindi voice installed — which fails exactly the patients who depend on it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api, apiBlob } from "../api/client";
import { getLanguage } from "../store/language";
import { CornerMotif, HealthShield } from "../components/AyushmanIcons";
import { Spinner } from "../components/Spinner";
import { useAuth } from "../store/auth";

type ScopeKey = "interview" | "documents" | "share_with_physician" | "abdm_push";

interface Section {
  key: string;
  scope: ScopeKey;
  required: boolean;
}

const SECTIONS: Section[] = [
  { key: "interview", scope: "interview", required: true },
  { key: "sharePhysician", scope: "share_with_physician", required: true },
  { key: "documents", scope: "documents", required: false },
  { key: "abdmPush", scope: "abdm_push", required: false },
];

const RETENTION_DAYS = 90;

export function ConsentPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { patient } = useAuth();

  /** The patient's one language — screen, audio and transcription alike. */
  const language = getLanguage();

  const [accepted, setAccepted] = useState<Record<ScopeKey, boolean>>({
    interview: false,
    share_with_physician: false,
    documents: false,
    abdm_push: false,
  });
  const [heard, setHeard] = useState<Record<string, boolean>>({});
  const [playing, setPlaying] = useState<string | null>(null);
  const [readAloudConfirmed, setReadAloudConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  /** Server audio failed, so say so rather than substituting a robotic voice. */
  const [audioUnavailable, setAudioUnavailable] = useState(false);

  /** Whether the guided read-through is muted.
   *
   * Starts unmuted: the patient walks up, touches the screen, and the kiosk
   * begins explaining. Pressing stop mutes it for the rest of the visit rather
   * than only stopping the current clip, because someone who silences a kiosk
   * once does not want it starting again on their next tap.
   */
  const [muted, setMuted] = useState(false);
  /** Index of the section the guided sequence is on, or null when idle. */
  const [guideIndex, setGuideIndex] = useState<number | null>(null);
  /** The first screen touch has happened, so audio playback is now permitted. */
  const startedRef = useRef(false);
  const [started, setStarted] = useState(false);

  /** The <audio> element playing server TTS, so stop() can interrupt it. */
  const audioRef = useRef<HTMLAudioElement | null>(null);
  /** Object URL of the clip in flight, revoked once it is done with. */
  const objectUrlRef = useRef<string | null>(null);
  /** What to run when the current clip ends, so the guide can chain sections.
   *  Held in a ref because the audio element's handler would otherwise close
   *  over a stale copy of it. */
  const onClipEndRef = useRef<(() => void) | null>(null);

  const releaseAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);

  // Stop playback if the patient navigates away mid-sentence.
  useEffect(() => releaseAudio, [releaseAudio]);

  const speak = useCallback(
    async (sectionKey: string) => {
      // Never start new audio if the patient has muted the kiosk.
      if (muted) return;

      releaseAudio();
      setPlaying(sectionKey);

      const finish = () => {
        setHeard((prev) => ({ ...prev, [sectionKey]: true }));
        setPlaying(null);
        releaseAudio();
        // Hand control back to the guided sequence, if one is running.
        onClipEndRef.current?.();
      };

      try {
        const blob = await apiBlob(
          `/consent/audio/${sectionKey}?language=${encodeURIComponent(language)}`,
        );
        const url = URL.createObjectURL(blob);
        objectUrlRef.current = url;

        const audio = new Audio(url);
        audioRef.current = audio;

        // Only 'ended' marks a section heard — pausing or seeking away must not.
        audio.onended = finish;
        audio.onerror = () => {
          releaseAudio();
          setPlaying(null);
          setAudioUnavailable(true);
        };

        await audio.play();
      } catch {
        // Server audio unavailable — no Sarvam credit, or the provider is down.
        //
        // The browser's own speech synthesis used to cover this, and it was
        // removed on purpose. It reads the *English* source aloud in a robotic
        // voice, so a Tamil patient got English they cannot follow while the
        // screen said Tamil. Saying plainly that audio is unavailable is more
        // use than pretending to speak.
        releaseAudio();
        setPlaying(null);
        setAudioUnavailable(true);
      }
    },
    [language, muted, releaseAudio],
  );

  /** Stop the current clip without muting future audio.
   *
   * Used by per-section pause buttons: the patient wants to pause this one
   * clip, not silence the entire kiosk for the rest of their visit.
   */
  const stopCurrent = useCallback(() => {
    onClipEndRef.current = null;
    setGuideIndex(null);
    setPlaying(null);
    releaseAudio();
  }, [releaseAudio]);

  /** Silence the kiosk for the rest of the visit.
   *
   * Mutes rather than merely stopping the current clip: a patient who hushes a
   * talking kiosk does not want it resuming on their next tap.
   */
  const stop = useCallback(() => {
    onClipEndRef.current = null;
    setGuideIndex(null);
    setPlaying(null);
    setMuted(true);
    // releaseAudio last — ensures the audio element is actually paused after
    // state is already updated, so no in-flight onended callback can re-start
    // the guide before React commits the muted=true render.
    releaseAudio();
  }, [releaseAudio]);

  // ── Guided read-through ────────────────────────────────────────────────
  //
  // The kiosk explains itself: touch the screen and it starts talking through
  // the sections in order, like an attendant standing next to you, instead of
  // waiting to be asked four separate times. That is the difference between a
  // form that happens to have speakers and something that feels staffed.

  /** Play section ``index``, then chain to the next when it finishes. */
  const playFromRef = useRef<(index: number) => void>(() => {});
  playFromRef.current = (index: number) => {
    if (muted || index >= SECTIONS.length) {
      setGuideIndex(null);
      onClipEndRef.current = null;
      return;
    }
    setGuideIndex(index);
    onClipEndRef.current = () => playFromRef.current(index + 1);
    void speak(SECTIONS[index].key);
  };

  // Browsers refuse to play audio before a user gesture, so the first touch
  // anywhere is what starts it. Registered once: re-arming on every tap would
  // restart the narration mid-sentence.
  useEffect(() => {
    const begin = () => {
      if (startedRef.current || muted) return;
      startedRef.current = true;
      setStarted(true);
      playFromRef.current(0);
    };

    window.addEventListener("pointerdown", begin);
    window.addEventListener("keydown", begin);
    return () => {
      window.removeEventListener("pointerdown", begin);
      window.removeEventListener("keydown", begin);
    };
  }, [muted]);

  const toggle = (scope: ScopeKey) => setAccepted((prev) => ({ ...prev, [scope]: !prev[scope] }));

  /** Sections the patient actually has to have had explained to them.
   *
   * Required scopes always count. An optional scope only counts once accepted:
   * declining the ABHA push is a decision that needs no explanation, and
   * demanding the patient sit through audio for something they just refused is
   * pure friction — it was leaving the Continue button greyed with no clue why.
   */
  const sectionsNeedingConfirmation = useMemo(
    () => SECTIONS.filter((s) => s.required || accepted[s.scope]),
    [accepted],
  );

  /** Whether the audio actually played through for every section that mattered.
   *
   * Recorded, not enforced. Ticking "I understand and I agree" on each scope is
   * the affirmation; the narration is how the terms are conveyed to someone who
   * cannot read them. Blocking Continue on full playback punished the literate
   * patient in a queue without making the other patient any better informed.
   */
  const heardEverything = useMemo(
    () => sectionsNeedingConfirmation.every((s) => heard[s.key]),
    [heard, sectionsNeedingConfirmation],
  );

  const mandatoryAccepted = SECTIONS.filter((s) => s.required).every((s) => accepted[s.scope]);
  const canSubmit = mandatoryAccepted && !loading;

  /** Why Continue is disabled, so the patient is never left guessing. */
  const blockedReason = useMemo(() => {
    if (loading || canSubmit) return "";
    return t("consent.mustAccept");
  }, [loading, canSubmit, t]);

  const handleSubmit = async () => {
    setError("");
    setLoading(true);
    stop();
    try {
      await api("/consent", {
        method: "POST",
        body: {
          scope: {
            interview: accepted.interview,
            documents: accepted.documents,
            abdm_push: accepted.abdm_push,
            share_with_physician: accepted.share_with_physician,
            retention_days: RETENTION_DAYS,
          },
          // The language consent was actually given in.
          language,
          // The patient was shown the terms and affirmed each scope explicitly.
          audio_confirmed: true,
          // Whether the narration actually played through, recorded as fact
          // rather than inferred, so an audit can tell a patient who was read to
          // from one who read it themselves.
          confirmation_method: readAloudConfirmed
            ? "read_by_attendant"
            : heardEverything
              ? "audio"
              : "read_by_patient",
        },
      });
      navigate("/documents/upload");
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center px-6 py-8">
      <div className="w-full max-w-lg">
        {/* Ayushman Bharat consent header */}
        <div
          className="relative mb-5 overflow-hidden rounded-xl px-5 py-4 text-center text-white shadow-md"
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
          <div className="relative z-10 flex flex-col items-center gap-2">
            <HealthShield size={48} className="text-white" />
            <div>
              <span className="text-sm font-bold tracking-wide">Informed Consent</span>
              <p className="text-xs text-blue-200 opacity-80">
                Your data is protected under DISHA &amp; ABDM guidelines
              </p>
            </div>
          </div>
        </div>

        <h1 className="mb-2 text-center text-2xl font-bold text-primary-600">
          {t("consent.title")}
        </h1>
        <p className="mb-4 text-center text-gray-600">{t("consent.subtitle")}</p>

        {patient?.name && (
          <p className="mb-4 text-center text-sm text-gray-500">
            {t("consent.forPatient", { name: patient.name })}
          </p>
        )}

        {audioUnavailable && (
          <div
            className="mb-4 rounded-md border border-saffron/30 bg-saffron/5 px-4 py-3 text-sm text-saffron-dark"
            role="status"
          >
            {t("language.audioUnavailable")}
          </div>
        )}

        {/* One control, visible once the kiosk starts talking and until the
            patient mutes it. Shown between clips too (not just while playing)
            so it doesn't flash in and out between sections. */}
        {started && !muted && (
          <button
            onClick={stop}
            className="mb-4 flex w-full items-center justify-center gap-2 rounded-xl border border-primary-200 bg-primary-50 px-4 py-3 text-sm font-medium text-primary-800 transition hover:bg-primary-100 focus:outline-none focus:ring-4 focus:ring-primary-200"
          >
            <span aria-hidden="true">■</span>
            {t("consent.stopAllAudio")}
            {playing && guideIndex !== null && (
              <span className="text-primary-600">
                {t("consent.readingProgress", {
                  current: guideIndex + 1,
                  total: SECTIONS.length,
                })}
              </span>
            )}
          </button>
        )}

        {error && (
          <div
            className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            role="alert"
          >
            {error}
          </div>
        )}

        <div className="mb-6 space-y-3">
          {SECTIONS.map((section) => {
            const isPlaying = playing === section.key;
            const hasHeard = heard[section.key];

            return (
              <section key={section.key} className="govt-card p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <h2 className="text-base font-semibold text-gray-900">
                      {t(`consent.sections.${section.key}.title`)}{" "}
                      <span
                        className={`ml-1 align-middle text-xs font-medium ${
                          section.required ? "text-red-600" : "text-gray-400"
                        }`}
                      >
                        {section.required ? t("consent.required") : t("consent.optional")}
                      </span>
                    </h2>
                    <p className="mt-1 text-sm text-gray-600">
                      {t(`consent.sections.${section.key}.description`)}
                    </p>
                  </div>

                  <button
                    onClick={() =>
                      isPlaying ? stopCurrent() : muted ? undefined : void speak(section.key)
                    }
                    disabled={muted && !isPlaying}
                    className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-md border shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-primary-200 disabled:opacity-40 disabled:cursor-not-allowed disabled:translate-y-0 disabled:shadow-sm ${
                      isPlaying
                        ? "border-red-300 bg-red-50 text-red-600"
                        : hasHeard
                          ? "border-govgreen/30 bg-govgreen/5 text-govgreen"
                          : "border-primary-200 bg-primary-50 text-primary-600 hover:bg-primary-100"
                    }`}
                    aria-label={
                      isPlaying
                        ? t("consent.stopAudio")
                        : `${t("consent.playAudio")}: ${t(`consent.sections.${section.key}.title`)}`
                    }
                  >
                    {isPlaying ? (
                      <svg
                        className="h-5 w-5"
                        fill="currentColor"
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                      >
                        <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
                      </svg>
                    ) : (
                      <svg
                        className="h-5 w-5"
                        fill="currentColor"
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                      >
                        <path d="M8 5v14l11-7z" />
                      </svg>
                    )}
                  </button>
                </div>

                <label className="mt-4 flex cursor-pointer items-center gap-3">
                  <input
                    type="checkbox"
                    checked={accepted[section.scope]}
                    onChange={() => toggle(section.scope)}
                    className="h-6 w-6 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                  />
                  <span className="text-sm font-medium text-gray-700">{t("consent.iAccept")}</span>
                </label>
              </section>
            );
          })}
        </div>

        {audioUnavailable && (
          <div className="mb-6 rounded-md border-2 border-primary-200 bg-primary-50 p-5">
            <label className="flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                checked={readAloudConfirmed}
                onChange={(e) => setReadAloudConfirmed(e.target.checked)}
                className="h-6 w-6 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
              />
              <span className="text-sm font-medium text-gray-800">
                {t("consent.audioConfirmation")}
              </span>
            </label>
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="btn-primary w-full py-4 text-lg"
        >
          {loading ? (
            <Spinner size="sm" className="border-white/40 border-t-white" />
          ) : (
            t("consent.submitButton")
          )}
        </button>

        {blockedReason && (
          <p className="mt-3 text-center text-sm text-gray-500" role="status">
            {blockedReason}
          </p>
        )}
      </div>
    </main>
  );
}
