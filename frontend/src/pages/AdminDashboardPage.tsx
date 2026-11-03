/**
 * Super-admin dashboard — the "see everything and provision the rest" screen.
 *
 * Three panels: system overview counts, create-a-doctor and create-a-login
 * forms, and the patient/physician lists. Redirects to /admin/login on 401,
 * which is what the shared api client raises when the token is missing or not
 * an admin's.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { adminApi, type AdminOverview, type AdminPatient, type PhysicianItem } from "../api/admin";
import { ApiError, getToken } from "../api/client";
import { Spinner } from "../components/Spinner";

const DEPARTMENTS = [
  "General Medicine",
  "Ayurveda",
  "Cardiology",
  "Pediatrics",
  "Orthopedics",
  "ENT",
];

export function AdminDashboardPage() {
  const navigate = useNavigate();
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [patients, setPatients] = useState<AdminPatient[]>([]);
  const [physicians, setPhysicians] = useState<PhysicianItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    // No token at all → straight to the admin login, without firing an API call
    // that would 401. This is what makes /admin usable as a bookmarked entry
    // point: an unauthenticated visit lands on the admin login, not a blank
    // dashboard or the patient login.
    if (!getToken()) {
      navigate("/admin/login");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [ov, pts, phys] = await Promise.all([
        adminApi.overview(),
        adminApi.patients(),
        adminApi.physicians(),
      ]);
      setOverview(ov);
      setPatients(pts);
      setPhysicians(phys);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        navigate("/admin/login");
        return;
      }
      setError(e instanceof ApiError ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [navigate]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <main className="flex min-h-[calc(100vh-12rem)] items-center justify-center">
        <Spinner />
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-8">
      <h1 className="mb-6 text-2xl font-bold text-primary-600">Administrator Dashboard</h1>

      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {notice && (
        <div className="mb-4 rounded-md border border-govgreen/30 bg-govgreen/5 px-4 py-3 text-sm text-govgreen-dark">
          {notice}
        </div>
      )}

      {/* Overview counts */}
      {overview && (
        <section className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          <Stat label="Patients" value={overview.patients} />
          <Stat label="Visits today" value={overview.visits_today} />
          <Stat label="Visits total" value={overview.visits_total} />
          <Stat label="Interviews" value={overview.interviews} />
          <Stat label="Summaries" value={overview.summaries_total} />
          <Stat label="Confirmed" value={overview.summaries_confirmed} />
          <Stat label="Red flags" value={overview.red_flags} tone="danger" />
          <Stat label="Doctors" value={overview.doctors} />
        </section>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <CreateDoctorForm
          onCreated={(name) => {
            setNotice(`Doctor "${name}" added.`);
            void load();
          }}
        />
        <CreatePhysicianForm
          onCreated={(email) => {
            setNotice(`Account "${email}" created.`);
            void load();
          }}
        />
      </div>

      {/* Physician accounts */}
      <section className="mt-8">
        <h2 className="mb-3 text-lg font-bold text-gray-800">Staff & Doctor Logins</h2>
        <div className="overflow-hidden rounded-lg border border-gray-200">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface-section text-gray-600">
              <tr>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Email</th>
                <th className="px-4 py-2">Role</th>
                <th className="px-4 py-2">Active</th>
              </tr>
            </thead>
            <tbody>
              {physicians.map((p) => (
                <tr key={p.id} className="border-t border-gray-100">
                  <td className="px-4 py-2 font-medium text-gray-900">{p.full_name}</td>
                  <td className="px-4 py-2 text-gray-600">{p.email}</td>
                  <td className="px-4 py-2">{p.role}</td>
                  <td className="px-4 py-2">{p.is_active ? "✅" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Patients */}
      <section className="mt-8">
        <h2 className="mb-3 text-lg font-bold text-gray-800">Patients ({patients.length})</h2>
        <div className="overflow-hidden rounded-lg border border-gray-200">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface-section text-gray-600">
              <tr>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Age / Gender</th>
                <th className="px-4 py-2">Phone</th>
                <th className="px-4 py-2">Visits</th>
              </tr>
            </thead>
            <tbody>
              {patients.map((p) => (
                <tr key={p.id} className="border-t border-gray-100">
                  <td className="px-4 py-2 font-medium text-gray-900">{p.name}</td>
                  <td className="px-4 py-2 text-gray-600">
                    {p.age ?? "—"} / {p.gender ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-gray-600">{p.phone ?? "—"}</td>
                  <td className="px-4 py-2">{p.visit_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "danger" }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div
        className={`text-2xl font-bold ${tone === "danger" && value > 0 ? "text-red-600" : "text-primary-600"}`}
      >
        {value}
      </div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}

function CreateDoctorForm({ onCreated }: { onCreated: (name: string) => void }) {
  const [name, setName] = useState("");
  const [department, setDepartment] = useState(DEPARTMENTS[0]);
  const [specialization, setSpecialization] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const input = "w-full rounded-md border border-gray-300 px-3 py-2 text-sm";

  const submit = async () => {
    setErr("");
    setBusy(true);
    try {
      await adminApi.createDoctor({ name: name.trim(), department, specialization });
      setName("");
      setSpecialization("");
      onCreated(name.trim());
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-gray-200 p-5">
      <h2 className="mb-3 text-lg font-bold text-gray-800">Add a Doctor</h2>
      {err && <p className="mb-2 text-sm text-red-600">{err}</p>}
      <div className="space-y-3">
        <input
          className={input}
          placeholder="Name (e.g. Dr. A Sharma)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <select
          className={input}
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
        >
          {DEPARTMENTS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <input
          className={input}
          placeholder="Specialization (optional)"
          value={specialization}
          onChange={(e) => setSpecialization(e.target.value)}
        />
        <button
          onClick={() => void submit()}
          disabled={busy || !name.trim()}
          className="btn-primary w-full py-2.5"
        >
          {busy ? "Adding…" : "Add Doctor"}
        </button>
      </div>
    </div>
  );
}

function CreatePhysicianForm({ onCreated }: { onCreated: (email: string) => void }) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("physician");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const input = "w-full rounded-md border border-gray-300 px-3 py-2 text-sm";

  const submit = async () => {
    setErr("");
    setBusy(true);
    try {
      await adminApi.createPhysician({
        email: email.trim(),
        password,
        full_name: fullName.trim(),
        role,
      });
      setEmail("");
      setFullName("");
      setPassword("");
      onCreated(email.trim());
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-gray-200 p-5">
      <h2 className="mb-3 text-lg font-bold text-gray-800">Create a Login</h2>
      {err && <p className="mb-2 text-sm text-red-600">{err}</p>}
      <div className="space-y-3">
        <input
          className={input}
          placeholder="Full name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
        />
        <input
          className={input}
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          className={input}
          type="password"
          placeholder="Password (min 6 chars)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <select className={input} value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="physician">Physician</option>
          <option value="staff">Staff</option>
          <option value="admin">Admin</option>
        </select>
        <button
          onClick={() => void submit()}
          disabled={busy || !email.trim() || password.length < 6}
          className="btn-primary w-full py-2.5"
        >
          {busy ? "Creating…" : "Create Account"}
        </button>
      </div>
    </div>
  );
}
