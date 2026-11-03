/**
 * Super-admin login. Reuses the physician login endpoint, but only lets a
 * role="admin" account through — a plain physician is bounced with a clear
 * message rather than landing on an admin dashboard every call would 403.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api, setToken } from "../api/client";
import { Spinner } from "../components/Spinner";

interface LoginResponse {
  token: string;
  physician_id: string;
  name: string;
  email: string;
  role: string;
}

export function AdminLoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setError("");
    setLoading(true);
    try {
      const res = await api<LoginResponse>("/auth/physician/login", {
        method: "POST",
        body: { email: email.trim(), password },
        skipAuth: true,
      });
      if (res.role !== "admin") {
        setError("This account is not an administrator.");
        return;
      }
      setToken(res.token);
      sessionStorage.setItem("medikiosk_physician", JSON.stringify(res));
      navigate("/admin");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    "w-full rounded-md border border-gray-300 px-4 py-3 text-base focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200";

  return (
    <main className="flex min-h-[calc(100vh-12rem)] flex-col items-center justify-center px-6 py-8">
      <div className="w-full max-w-md">
        <h1 className="mb-1 text-center text-2xl font-bold text-primary-600">
          Administrator Login
        </h1>
        <p className="mb-6 text-center text-sm text-gray-500">
          Manage doctors, staff accounts, and view system activity.
        </p>

        {error && (
          <div
            className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            role="alert"
          >
            {error}
          </div>
        )}

        <label className="mb-1 block text-sm font-semibold text-gray-700" htmlFor="admin-email">
          Email
        </label>
        <input
          id="admin-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={`${inputClass} mb-4`}
        />

        <label className="mb-1 block text-sm font-semibold text-gray-700" htmlFor="admin-pw">
          Password
        </label>
        <input
          id="admin-pw"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void submit()}
          className={inputClass}
        />

        <button
          onClick={() => void submit()}
          disabled={loading || !email.trim() || !password}
          className="btn-primary mt-5 w-full py-3.5 text-lg"
        >
          {loading ? <Spinner size="sm" className="border-white/40 border-t-white" /> : "Sign in"}
        </button>
      </div>
    </main>
  );
}
