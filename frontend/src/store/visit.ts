/**
 * Visit progress — what this patient has finished during this kiosk session.
 *
 * Separate from auth state because it answers a different question: auth says
 * who the patient is, this says how far through Identify → Converse → Scan they
 * have got, so a screen can send them forward instead of dead-ending or looping
 * them back into an interview they already completed.
 *
 * sessionStorage, not a React context, because these three screens are reached
 * by navigation rather than nesting, and the value has to survive a refresh on a
 * kiosk mid-visit. It is NOT a security boundary: the completed interview id is
 * re-validated against the patient's own sessions by the backend on every call,
 * exactly as consent is (see the note in store/auth.ts).
 */

const SESSION_KEY = "medikiosk_interview_session";
const VISIT_KEY = "medikiosk_visit";

/**
 * The doctor/department/token the patient chose this visit.
 *
 * Kept next to the interview id and for the same reason: it must survive a
 * mid-visit refresh, and the screens that need it (doctor selection → consent →
 * done) are reached by navigation, not nesting. Not a security boundary — the
 * backend re-validates visit ownership on every call.
 */
export interface VisitSelection {
  visitId: string;
  tokenNumber: number;
  department: string | null;
  doctorId: string | null;
  doctorName: string | null;
}

export function setVisitSelection(selection: VisitSelection): void {
  sessionStorage.setItem(VISIT_KEY, JSON.stringify(selection));
}

export function getVisitSelection(): VisitSelection | null {
  const raw = sessionStorage.getItem(VISIT_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as VisitSelection;
  } catch {
    return null;
  }
}

/** Record the interview session the patient just completed. */
export function setCompletedInterview(sessionId: string): void {
  sessionStorage.setItem(SESSION_KEY, sessionId);
}

/**
 * The completed interview session id, or null.
 *
 * Wave 4 needs exactly this to call POST /summaries/generate, which is why the
 * id is kept rather than thrown away once the interview screen unmounts.
 */
export function getCompletedInterview(): string | null {
  return sessionStorage.getItem(SESSION_KEY);
}

export function clearVisit(): void {
  sessionStorage.removeItem(SESSION_KEY);
  sessionStorage.removeItem(VISIT_KEY);
}
