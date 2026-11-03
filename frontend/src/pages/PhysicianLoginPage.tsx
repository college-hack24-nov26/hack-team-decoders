/**
 * Physician login — basic role-based auth for the dashboard.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api, setToken } from "../api/client";
import { CornerMotif } from "../components/AyushmanIcons";
import { Spinner } from "../components/Spinner";

export function PhysicianLoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError("Please enter both email and password");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const res = await api<{ token: string; physician_id: string; name: string }>(
        "/auth/physician/login",
        {
          method: "POST",
          body: { email, password },
          skipAuth: true,
        },
      );
      setToken(res.token);
      sessionStorage.setItem("medikiosk_physician", JSON.stringify(res));
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed. Check your credentials.");
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-[calc(100vh-10rem)] items-center justify-center px-6 py-8">
      <div className="govt-card w-full max-w-md overflow-hidden p-0">
        {/* AB branded header strip */}
        <div
          className="relative px-6 py-4 text-center text-white"
          style={{
            background: "linear-gradient(135deg, #002B5B 0%, #0F4C81 40%, #0F6DB8 100%)",
          }}
        >
          <div className="absolute left-0 top-0 opacity-60">
            <CornerMotif size={56} />
          </div>
          <div className="absolute bottom-0 right-0 rotate-180 opacity-60">
            <CornerMotif size={56} />
          </div>
          <div className="relative z-10 flex flex-col items-center gap-2">
            <img src="/kiosk/abdm-logo.png" alt="ABDM" className="h-10 w-auto" />
            <div>
              <span className="text-base font-bold">
                {t("dashboard.login.title", "Physician Dashboard")}
              </span>
              <p className="text-xs text-blue-200 opacity-80">
                {t("dashboard.login.subtitle", "Sign in to review patient summaries")}
              </p>
            </div>
          </div>
        </div>

        <div className="p-6">
          {error && (
            <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-semibold text-gray-700">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-4 py-3 focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200"
                placeholder="doctor@hospital.in"
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-semibold text-gray-700">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-md border border-gray-300 px-4 py-3 focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200"
                placeholder="••••••••"
              />
            </div>
            <button type="submit" disabled={loading} className="btn-primary w-full py-3">
              {loading ? (
                <Spinner size="sm" className="border-white/40 border-t-white" />
              ) : (
                "Sign in"
              )}
            </button>
          </form>

          <p className="mt-6 border-t border-gray-200 pt-4 text-center text-xs text-gray-400">
            Clinical staff accounts are provisioned by the hospital administrator.
          </p>
        </div>
      </div>
    </main>
  );
}
