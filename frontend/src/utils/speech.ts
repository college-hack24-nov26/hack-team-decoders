/**
 * Browser speech — offline fallbacks for reading aloud and for voice input.
 *
 * The server voices (Sarvam / Azure TTS and ASR) sound better and cover more
 * languages, but need API keys. When they are not configured the kiosk would
 * otherwise be silent and deaf, which fails exactly the patients who cannot
 * read the screen. These helpers use the browser's own Web Speech API instead:
 *
 *   speak()            reads the on-screen (already translated) text aloud in
 *                      the patient's language, using a matching installed voice
 *   createRecognizer() transcribes speech while the mic button is held
 *                      (Chrome / Edge; other browsers return null)
 */

/** BCP-47 tags for the kiosk's interface languages. */
const SPEECH_TAGS: Record<string, string> = {
  en: "en-IN",
  hi: "hi-IN",
  bn: "bn-IN",
  mr: "mr-IN",
  te: "te-IN",
  ta: "ta-IN",
  gu: "gu-IN",
  kn: "kn-IN",
  ml: "ml-IN",
  pa: "pa-IN",
};

export function speechTag(language: string): string {
  return SPEECH_TAGS[language] ?? language;
}

// ---------------------------------------------------------------------------
// Reading aloud
// ---------------------------------------------------------------------------

export function canSpeak(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

/** The best installed voice for a language: exact region first, then any region. */
function pickVoice(tag: string): SpeechSynthesisVoice | undefined {
  const voices = window.speechSynthesis.getVoices();
  const base = tag.split("-")[0].toLowerCase();
  return (
    voices.find((v) => v.lang.toLowerCase() === tag.toLowerCase()) ??
    voices.find((v) => v.lang.toLowerCase().replace("_", "-").startsWith(`${base}-`)) ??
    voices.find((v) => v.lang.toLowerCase() === base)
  );
}

/**
 * Speak ``text`` in ``language``. Resolves true when it finished, false when it
 * was interrupted by stopSpeaking() or a newer speak() call. Rejects only when
 * the browser cannot speak at all.
 */
export function speak(text: string, language: string): Promise<boolean> {
  if (!canSpeak()) return Promise.reject(new Error("Speech synthesis is not supported"));
  const synth = window.speechSynthesis;
  synth.cancel();

  return new Promise((resolve, reject) => {
    const utterance = new SpeechSynthesisUtterance(text);
    const tag = speechTag(language);
    utterance.lang = tag;
    const voice = pickVoice(tag);
    if (voice) utterance.voice = voice;
    utterance.rate = 0.95;

    utterance.onend = () => resolve(true);
    utterance.onerror = (event) => {
      if (event.error === "interrupted" || event.error === "canceled") resolve(false);
      else reject(new Error(`Speech failed: ${event.error}`));
    };
    synth.speak(utterance);
  });
}

export function stopSpeaking(): void {
  if (canSpeak()) window.speechSynthesis.cancel();
}

// ---------------------------------------------------------------------------
// Voice input
// ---------------------------------------------------------------------------

/** The slice of the Web Speech recognition API used here (not in lib.dom). */
interface RecognitionResultList {
  length: number;
  [index: number]: { isFinal: boolean; 0: { transcript: string } };
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { resultIndex: number; results: RecognitionResultList }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start(): void;
  stop(): void;
}
type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export interface Recognizer {
  /** Stop listening and return everything heard (empty string if nothing). */
  stop(): Promise<string>;
}

/** Start transcribing in the browser, or return null where unsupported. */
export function createRecognizer(language: string): Recognizer | null {
  const Ctor = recognitionCtor();
  if (!Ctor) return null;

  const recognition = new Ctor();
  recognition.lang = speechTag(language);
  recognition.continuous = true;
  recognition.interimResults = true;

  const finals: string[] = [];
  let interim = "";
  let ended = false;
  let onEnded: (() => void) | null = null;

  recognition.onresult = (event) => {
    interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) finals.push(result[0].transcript);
      else interim += result[0].transcript;
    }
  };
  recognition.onerror = () => undefined;
  recognition.onend = () => {
    ended = true;
    onEnded?.();
  };

  try {
    recognition.start();
  } catch {
    return null;
  }

  return {
    stop() {
      return new Promise((resolve) => {
        const finish = () => resolve([...finals, interim].join(" ").replace(/\s+/g, " ").trim());
        if (ended) return finish();
        // The last result arrives just before 'end'; cap the wait so a stuck
        // recognizer never freezes the mic button.
        const timer = setTimeout(finish, 2000);
        onEnded = () => {
          clearTimeout(timer);
          finish();
        };
        recognition.stop();
      });
    },
  };
}
