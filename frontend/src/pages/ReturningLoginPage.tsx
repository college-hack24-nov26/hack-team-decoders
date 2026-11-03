/**
 * Returning-patient login (F2) — phone lookup, then past visits.
 *
 * No password: a walk-up kiosk, not a bank. On success we greet the patient by
 * name and show their recent visits so they recognise their own record before
 * starting a new one.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { returningLogin, type PastVisit } from "../api/clinic";
import { Spinner } from "../components/Spinner";
import { setToken } from "../api/client";
import { getLanguage } from "../store/language";
import { useAuth } from "../store/auth";

export function ReturningLoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { login } = useAuth();

  const [phone, setPhone] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [greeting, setGreeting] = useState<string | null>(null);
  const [visits, setVisits] = useState<PastVisit[]>([]);

  const digitsOnly = (value: string) => value.replace(/\D/g, "");

  const handleLookup = async () => {
    setError("");
    const value = digitsOnly(phone);
    if (value.length < 10) {
      setError(t("login.phoneInvalid"));
      return;
    }

    setLoading(true);
    try {
      const res = await returningLogin(value);
      if (!res.found || !res.token || !res.patient_id) {
        setError(t("returning.notFound"));
        return;
      }
      // setToken so the follow-up doctor-selection calls are authenticated even
      // before the auth context re-renders.
      setToken(res.token);
      login(res.token, {
        id: res.patient_id,
        name: res.name ?? "",
        language: res.preferred_language ?? getLanguage(),
      });
      setGreeting(res.name ?? "");
      setVisits(res.visits);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("common.error"));
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    "w-full rounded-md border border-gray-300 px-4 py-3 text-lg focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200";

  // -- After a successful lookup: greeting + visit history -------------------
  if (greeting !== null) {
    return (
      <main className="flex flex-col items-center px-6 py-8">
        <div className="w-full max-w-lg">
          <h1 className="mb-1 text-2xl font-bold text-primary-600">
            {t("returning.welcomeBack", { name: greeting })}
          </h1>
          <p className="mb-6 text-gray-600">{t("returning.pastVisits")}</p>

          {visits.length === 0 ? (
            <p className="mb-6 rounded-md border border-gray-200 bg-surface-section p-4 text-gray-500">
              {t("returning.noVisits")}
            </p>
          ) : (
            <ul className="mb-6 space-y-3">
              {visits.slice(0, 5).map((v) => (
                <li key={v.visit_id} className="govt-card p-4">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-gray-900">
                      {v.department ?? t("returning.generalVisit")}
                    </span>
                    <StatusBadge status={v.status} />
                  </div>
                  <div className="mt-1 text-sm text-gray-500">
                    {formatDate(v.date)}
                    {v.doctor_name ? ` · ${v.doctor_name}` : ""}
                  </div>
                  {v.chief_complaint && (
                    <div className="mt-1 text-sm text-gray-700">{v.chief_complaint}</div>
                  )}
                </li>
              ))}
            </ul>
          )}

          <button
            onClick={() => navigate("/select-doctor")}
            className="btn-primary w-full py-4 text-lg"
          >
            {t("returning.startNewVisit")}
          </button>
        </div>
      </main>
    );
  }

  // -- Phone entry -----------------------------------------------------------
  return (
    <main className="flex min-h-[calc(100vh-12rem)] flex-col items-center justify-center px-6 py-8">
      <div className="w-full max-w-md">
        <h1 className="mb-2 text-center text-2xl font-bold text-primary-600">
          {t("returning.title")}
        </h1>
        <p className="mb-6 text-center text-gray-600">{t("returning.subtitle")}</p>

        {error && (
          <div
            className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            role="alert"
          >
            {error}{" "}
            <button onClick={() => navigate("/login/new")} className="font-semibold underline">
              {t("returning.registerInstead")}
            </button>
          </div>
        )}

        <label htmlFor="phone" className="mb-1 block text-sm font-semibold text-gray-700">
          {t("login.phoneLabel")}
        </label>
        <div className="flex items-stretch gap-2">
          <span className="flex items-center rounded-md border border-gray-300 bg-surface-section px-3 text-lg text-gray-600">
            +91
          </span>
          <input
            id="phone"
            type="tel"
            inputMode="numeric"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder={t("login.phonePlaceholder")}
            className={inputClass}
          />
        </div>

        <button
          onClick={handleLookup}
          disabled={loading || !phone.trim()}
          className="btn-primary mt-5 w-full py-4 text-lg"
        >
          {loading ? (
            <Spinner size="sm" className="border-white/40 border-t-white" />
          ) : (
            t("returning.findRecord")
          )}
        </button>
      </div>
    </main>
  );
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const done = status === "completed";
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
        done ? "bg-govgreen/10 text-govgreen-dark" : "bg-primary-50 text-primary-700"
      }`}
    >
      {done ? `✅ ${t("returning.statusCompleted")}` : `🔄 ${t("returning.statusInProgress")}`}
    </span>
  );
}

function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
