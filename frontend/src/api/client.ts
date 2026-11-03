/**
 * API client — thin fetch wrapper for the MediKiosk backend.
 *
 * Base URL: VITE_API_BASE_URL points at the backend origin (see .env.example,
 * e.g. http://localhost:8000) and the /api/v1 prefix is added here so callers
 * pass clean paths like "/auth/login". When the variable is unset we use a
 * relative URL, which lets Vite's dev proxy forward /api to the backend.
 */

const API_ROOT = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
const API_BASE = `${API_ROOT}/api/v1`;

/** Error carrying the HTTP status so callers can distinguish 401 from 403. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const TOKEN_KEY = "medikiosk_token";

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

/**
 * Called when the backend rejects our token, so the app can send the patient
 * back to login instead of leaving them on a screen that cannot submit.
 *
 * Registered by the app shell rather than imported here, because this module
 * must not depend on the router.
 */
let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

/**
 * A 401 means the session is gone — expired, or the server restarted with a new
 * JWT secret. Both are unrecoverable for this token, so the only useful response
 * is to drop it and re-authenticate.
 *
 * Without this a patient sat on the consent screen seeing "Invalid or expired
 * token" with no way forward: every button kept calling an API that would never
 * accept them again. On an unattended kiosk that is a dead end.
 */
function handleUnauthorized(): void {
  clearToken();
  onUnauthorized?.();
}

interface ApiOptions {
  method?: string;
  body?: unknown;
  /** Skip the Authorization header (for public endpoints). */
  skipAuth?: boolean;
  /**
   * Don't fire the global 401 handler (which sends the patient to /login).
   *
   * The global handler assumes a patient session. Physician and admin screens
   * live behind their own logins, so a 401 there should bounce to /physician or
   * /admin/login — which the calling page does itself — not to the patient
   * login. Those callers set this and handle the 401 in their own catch.
   */
  skipUnauthorizedRedirect?: boolean;
}

export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { method = "GET", body, skipAuth = false, skipUnauthorizedRedirect = false } = opts;

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (!skipAuth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    const detail =
      payload && typeof payload.detail === "string"
        ? payload.detail
        : `Request failed (${res.status})`;
    if (res.status === 401 && !skipAuth && !skipUnauthorizedRedirect) handleUnauthorized();
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/**
 * Fetch a binary response (audio, files) rather than JSON.
 *
 * Separate from `api` because that one sets a JSON Content-Type and parses the
 * body as JSON, which would corrupt an audio stream.
 */
export async function apiBlob(path: string): Promise<Blob> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { headers });

  if (!res.ok) {
    // Error bodies are still JSON; fall back to the status when they are not.
    const payload = await res.json().catch(() => null);
    const detail =
      payload && typeof payload.detail === "string"
        ? payload.detail
        : `Request failed (${res.status})`;
    if (res.status === 401) handleUnauthorized();
    throw new ApiError(res.status, detail);
  }

  return await res.blob();
}
