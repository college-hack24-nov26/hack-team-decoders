/**
 * Login / Registration â€” three ways in, per the PS "Identify" step:
 *
 *   1. ABHA ID  â†’ POST /auth/abha/lookup
 *   2. Aadhaar  â†’ POST /auth/aadhaar/lookup
 *   3. New patient â†’ POST /auth/register
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { getLanguage } from "../store/language";
import { api } from "../api/client";
import { HealthShield, CornerMotif } from "../components/AyushmanIcons";
import { Spinner } from "../components/Spinner";
import { useAuth } from "../store/auth";

type Tab = "abha" | "aadhaar" | "register";

interface LookupResponse {
  found: boolean;
  patient_id: string | null;
  name: string | null;
  token: string | null;
}

interface SessionResponse {
  patient_id: string;
  token: string;
  name: string;
}

// "New patient" is first so the kiosk opens on that tab by default
const TABS: Tab[] = ["register", "abha", "aadhaar"];

// Pre-filled mock phone number for demo purposes
const MOCK_PHONE = "9876543210";

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { login } = useAuth();

  const [tab, setTab] = useState<Tab>("register");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  // Seeded from the redirect state when a session expires mid-visit, so the
  // patient is told what happened instead of silently landing back at login.
  const location = useLocation();
  const sessionExpired = Boolean(
    (location.state as { sessionExpired?: boolean } | null)?.sessionExpired,
  );
  const [notice, setNotice] = useState(sessionExpired ? t("login.sessionExpired") : "");

  const [abhaId, setAbhaId] = useState("");
  const [aadhaar, setAadhaar] = useState("");

  const [name, setName] = useState("");
  const [age, setAge] = useState("");
  const [gender, setGender] = useState("male");
  const [phone, setPhone] = useState(MOCK_PHONE);
  const [pendingAadhaar, setPendingAadhaar] = useState<string | null>(null);

  const switchTab = (next: Tab) => {
    setTab(next);
    setError("");
    setNotice("");
  };

  const digitsOnly = (value: string) => value.replace(/\D/g, "");

  const handleAbhaLookup = async () => {
    setError("");
    setLoading(true);
    try {
      const res = await api<LookupResponse>("/auth/abha/lookup", {
        method: "POST",
        body: { abha_id: abhaId.trim() },
        skipAuth: true,
      });

      if (res.found && res.token && res.patient_id) {
        login(res.token, { id: res.patient_id, name: res.name ?? "", language: getLanguage() });
        navigate("/select-doctor");
      } else {
        setError(t("login.abhaNotFound"));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setLoading(false);
    }
  };

  const handleAadhaarLookup = async () => {
    setError("");
    setNotice("");
    const value = digitsOnly(aadhaar);
    if (value.length !== 12) {
      setError(t("login.aadhaarInvalid"));
      return;
    }

    setLoading(true);
    try {
      const res = await api<LookupResponse>("/auth/aadhaar/lookup", {
        method: "POST",
        body: { aadhaar: value },
        skipAuth: true,
      });

      if (res.found && res.token && res.patient_id) {
        login(res.token, { id: res.patient_id, name: res.name ?? "", language: getLanguage() });
        navigate("/select-doctor");
        return;
      }

      setPendingAadhaar(value);
      setTab("register");
      setNotice(t("login.aadhaarNeedsDetails"));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async () => {
    setError("");
    const parsedAge = Number.parseInt(age, 10);

    if (!name.trim() || !phone.trim() || !age.trim()) {
      setError(t("login.fillAllFields"));
      return;
    }
    if (Number.isNaN(parsedAge) || parsedAge < 0 || parsedAge > 150) {
      setError(t("login.ageInvalid"));
      return;
    }
    if (digitsOnly(phone).length < 10) {
      setError(t("login.phoneInvalid"));
      return;
    }

    setLoading(true);
    try {
      const res = await api<SessionResponse>("/auth/register", {
        method: "POST",
        body: {
          name: name.trim(),
          age: parsedAge,
          gender,
          phone: digitsOnly(phone),
          // The one language the patient chose on the first screen. Drives
          // speech-to-text, audio prompts, screen text, and whether the
          // transcript is translated before summarisation.
          preferred_language: getLanguage(),
          ...(pendingAadhaar ? { aadhaar: pendingAadhaar } : {}),
        },
        skipAuth: true,
      });

      login(res.token, { id: res.patient_id, name: res.name, language: getLanguage() });
      navigate("/select-doctor");
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    "w-full rounded-md border border-gray-300 px-4 py-3 text-base focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200";
  const labelClass = "mb-1 block text-sm font-semibold text-gray-700";

  return (
    <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center justify-center px-6 py-8">
      <div className="w-full max-w-md">
        {/* Ayushman Bharat health card style header */}
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
            <HealthShield size={52} className="text-white" />
            <div>
              <div className="flex items-center justify-center gap-2">
                <span className="text-base font-bold tracking-wide">Patient Identification</span>
              </div>
              <p className="text-xs text-blue-200 opacity-80">
                Ayushman Bharat Health Account (ABHA)
              </p>
            </div>
          </div>
        </div>

        {/* DEMO MODE notice */}
        <div className="mb-4 rounded-md border border-saffron/30 bg-saffron/5 px-4 py-2 text-center text-xs text-saffron-dark">
          {t("login.demoNotice")}
        </div>

        <h1 className="mb-2 text-center text-2xl font-bold text-primary-600">{t("login.title")}</h1>
        <p className="mb-6 text-center text-gray-600">{t("login.subtitle")}</p>

        {/* Tabs */}
        <div
          className="mb-6 flex overflow-hidden rounded-lg border border-primary-100 bg-surface-section p-1"
          role="tablist"
        >
          {TABS.map((item) => (
            <button
              key={item}
              role="tab"
              aria-selected={tab === item}
              onClick={() => switchTab(item)}
              className={`flex-1 rounded-md px-2 py-2.5 text-center text-sm font-medium transition-all duration-200 ${
                tab === item ? "text-white shadow-sm" : "text-gray-500 hover:text-primary-600"
              }`}
              style={
                tab === item
                  ? { background: "linear-gradient(135deg, #002B5B 0%, #0F4C81 100%)" }
                  : undefined
              }
            >
              {t(`login.${item}Tab`)}
            </button>
          ))}
        </div>

        {notice && (
          <div
            className="mb-4 rounded-md border border-primary-200 bg-primary-50 px-4 py-3 text-sm text-primary-800"
            role="status"
          >
            {notice}
          </div>
        )}

        {error && (
          <div
            className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            role="alert"
          >
            {error}
          </div>
        )}

        {/* 1. ABHA */}
        {tab === "abha" && (
          <div className="space-y-4">
            <div>
              <label htmlFor="abha-id" className={labelClass}>
                {t("login.abhaLabel")}
              </label>
              <input
                id="abha-id"
                type="text"
                inputMode="numeric"
                autoComplete="off"
                value={abhaId}
                onChange={(e) => setAbhaId(e.target.value)}
                placeholder={t("login.abhaPlaceholder")}
                className={inputClass}
                aria-describedby="abha-help"
              />
              <p id="abha-help" className="mt-1 text-xs text-gray-500">
                {t("login.abhaHelp")}
              </p>
            </div>

            <button
              onClick={handleAbhaLookup}
              disabled={loading || !abhaId.trim()}
              className="btn-primary w-full py-4 text-lg"
            >
              {loading ? (
                <Spinner size="sm" className="border-white/40 border-t-white" />
              ) : (
                t("login.lookupButton")
              )}
            </button>

            <p className="mt-4 text-center text-sm text-gray-500">
              {t("login.noAbha")}{" "}
              <button
                onClick={() => switchTab("aadhaar")}
                className="font-medium text-primary-600 underline"
              >
                {t("login.useAadhaarLink")}
              </button>
            </p>
          </div>
        )}

        {/* 2. Aadhaar fallback */}
        {tab === "aadhaar" && (
          <div className="space-y-4">
            <div>
              <label htmlFor="aadhaar" className={labelClass}>
                {t("login.aadhaarLabel")}
              </label>
              <input
                id="aadhaar"
                type="text"
                inputMode="numeric"
                autoComplete="off"
                value={aadhaar}
                onChange={(e) => setAadhaar(e.target.value)}
                placeholder={t("login.aadhaarPlaceholder")}
                className={inputClass}
                aria-describedby="aadhaar-help"
              />
              <p id="aadhaar-help" className="mt-1 text-xs text-gray-500">
                {t("login.aadhaarHelp")}
              </p>
            </div>

            <button
              onClick={handleAadhaarLookup}
              disabled={loading || !aadhaar.trim()}
              className="btn-primary w-full py-4 text-lg"
            >
              {loading ? (
                <Spinner size="sm" className="border-white/40 border-t-white" />
              ) : (
                t("login.lookupButton")
              )}
            </button>

            <p className="mt-4 text-center text-sm text-gray-500">
              {t("login.noAbha")}{" "}
              <button
                onClick={() => switchTab("register")}
                className="font-medium text-primary-600 underline"
              >
                {t("login.registerLink")}
              </button>
            </p>
          </div>
        )}

        {/* 3. New patient registration */}
        {tab === "register" && (
          <div className="space-y-4">
            <div>
              <label htmlFor="reg-name" className={labelClass}>
                {t("login.nameLabel")}
              </label>
              <input
                id="reg-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("login.namePlaceholder")}
                className={inputClass}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="reg-age" className={labelClass}>
                  {t("login.ageLabel")}
                </label>
                <input
                  id="reg-age"
                  type="number"
                  inputMode="numeric"
                  min="0"
                  max="150"
                  value={age}
                  onChange={(e) => setAge(e.target.value)}
                  placeholder={t("login.agePlaceholder")}
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="reg-gender" className={labelClass}>
                  {t("login.genderLabel")}
                </label>
                <select
                  id="reg-gender"
                  value={gender}
                  onChange={(e) => setGender(e.target.value)}
                  className={inputClass}
                >
                  <option value="male">{t("login.genderMale")}</option>
                  <option value="female">{t("login.genderFemale")}</option>
                  <option value="other">{t("login.genderOther")}</option>
                </select>
              </div>
            </div>

            <div>
              <label htmlFor="reg-phone" className={labelClass}>
                {t("login.phoneLabel")}
              </label>
              <input
                id="reg-phone"
                type="tel"
                inputMode="numeric"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder={t("login.phonePlaceholder")}
                className={inputClass}
              />
            </div>

            {pendingAadhaar && (
              <p className="text-xs text-gray-500">
                {t("login.aadhaarLinked", { last4: pendingAadhaar.slice(-4) })}
              </p>
            )}

            <button
              onClick={handleRegister}
              disabled={loading}
              className="btn-primary w-full py-4 text-lg"
            >
              {loading ? (
                <Spinner size="sm" className="border-white/40 border-t-white" />
              ) : (
                t("login.registerButton")
              )}
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
