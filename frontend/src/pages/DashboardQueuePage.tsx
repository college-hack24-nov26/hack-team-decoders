/**
 * Patient queue screen — the first thing the physician sees after login.
 *
 * Red-flag patients are visually distinguished and sorted to the top. The
 * doctors patients can pick at the kiosk are listed alongside, with how many
 * are waiting for each, and choosing one filters the queue to that doctor.
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  type DashboardDoctor,
  type QueuePatient,
  fetchDashboardDoctors,
  fetchQueue,
} from "../api/dashboard";
import { SkeletonCard } from "../components/Spinner";

/** Filter value for patients who did not pick a doctor. */
const UNASSIGNED = "__unassigned__";

export function DashboardQueuePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [queue, setQueue] = useState<QueuePatient[]>([]);
  const [doctors, setDoctors] = useState<DashboardDoctor[]>([]);
  const [doctorFilter, setDoctorFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchQueue(), fetchDashboardDoctors().catch(() => [] as DashboardDoctor[])])
      .then(([res, docs]) => {
        if (cancelled) return;
        setQueue(res.patients);
        setDoctors(docs);
        setLoading(false);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load queue");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const visible = useMemo(() => {
    if (doctorFilter === null) return queue;
    if (doctorFilter === UNASSIGNED) return queue.filter((p) => !p.doctor_id);
    return queue.filter((p) => p.doctor_id === doctorFilter);
  }, [queue, doctorFilter]);

  const unassignedCount = queue.filter((p) => !p.doctor_id).length;
  const selectedDoctor = doctors.find((d) => d.id === doctorFilter);

  if (loading) {
    return (
      <main className="min-h-[calc(100vh-10rem)] bg-surface px-6 py-8">
        <div className="mx-auto max-w-6xl space-y-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </main>
    );
  }

  const filterButton = (id: string | null, label: string, sub: string, count: number) => {
    const active = doctorFilter === id;
    return (
      <button
        key={id ?? "all"}
        type="button"
        onClick={() => setDoctorFilter(id)}
        className={`flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left transition ${
          active
            ? "border-primary-600 bg-primary-50"
            : "border-transparent hover:border-gray-200 hover:bg-white"
        }`}
      >
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-gray-900">{label}</span>
          {sub && <span className="block truncate text-xs text-gray-500">{sub}</span>}
        </span>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-bold ${
            count > 0 ? "bg-primary-600 text-white" : "bg-gray-100 text-gray-400"
          }`}
        >
          {count}
        </span>
      </button>
    );
  };

  return (
    <main className="min-h-[calc(100vh-10rem)] bg-surface px-6 py-8">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-primary-600">
              {t("dashboard.queue.title", "Patient Queue")}
            </h1>
            <p className="text-xs text-gray-500">
              {selectedDoctor
                ? `${selectedDoctor.name} · ${selectedDoctor.department}`
                : doctorFilter === UNASSIGNED
                  ? t("dashboard.queue.unassigned", "No doctor chosen")
                  : t("dashboard.queue.allDoctors", "All doctors")}
            </p>
          </div>
          <span
            className="rounded-full px-4 py-1 text-sm font-medium text-white shadow-sm"
            style={{
              background: "linear-gradient(135deg, #002B5B 0%, #0F6DB8 100%)",
            }}
          >
            {visible.length} {t("dashboard.queue.patients", "patients")}
          </span>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-red-700">
            {error}
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
          {/* Doctors on duty */}
          <aside className="govt-card h-fit p-3">
            <h2 className="mb-2 px-1 text-xs font-bold uppercase tracking-wider text-gray-500">
              {t("dashboard.queue.doctorsOnDuty", "Doctors on duty")}
            </h2>
            <div className="space-y-1">
              {filterButton(null, t("dashboard.queue.allDoctors", "All doctors"), "", queue.length)}
              {doctors.map((d) =>
                filterButton(
                  d.id,
                  d.name,
                  `${d.department}${d.available ? "" : ` · ${t("doctor.unavailable", "Not available today")}`}`,
                  d.waiting,
                ),
              )}
              {unassignedCount > 0 &&
                filterButton(
                  UNASSIGNED,
                  t("dashboard.queue.unassigned", "No doctor chosen"),
                  "",
                  unassignedCount,
                )}
            </div>
          </aside>

          {/* Queue */}
          <section>
            {visible.length === 0 ? (
              <div className="govt-card p-6 text-center">
                <p className="text-base text-gray-500">
                  {t(
                    "dashboard.queue.empty",
                    "No patients waiting. The queue will update automatically.",
                  )}
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {visible.map((patient) => (
                  <button
                    key={patient.patient_id}
                    onClick={() => navigate(`/dashboard/patient/${patient.patient_id}`)}
                    className={`govt-card govt-card-hover w-full p-5 text-left ${
                      patient.has_red_flags ? "border-red-300" : ""
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-3">
                        {patient.has_red_flags && (
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-red-50">
                            <svg
                              className="h-4 w-4 text-red-600"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                            >
                              <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0zM12 9v4M12 17h.01" />
                            </svg>
                          </span>
                        )}
                        <div className="min-w-0">
                          <h3 className="text-base font-semibold text-gray-900">
                            {patient.token_number !== null && (
                              <span className="mr-2 rounded bg-primary-50 px-1.5 py-0.5 text-xs font-bold text-primary-700">
                                #{patient.token_number}
                              </span>
                            )}
                            {patient.name}
                          </h3>
                          <p className="text-sm text-gray-500">
                            {patient.age && `${patient.age}y`}
                            {patient.gender && ` / ${patient.gender}`}
                            {patient.chief_complaint &&
                              ` — ${patient.chief_complaint.replace(/_/g, " ")}`}
                          </p>
                          {(patient.doctor_name || patient.department) && (
                            <p className="mt-0.5 truncate text-xs text-gray-400">
                              {[patient.doctor_name, patient.department]
                                .filter(Boolean)
                                .join(" · ")}
                            </p>
                          )}
                        </div>
                      </div>

                      <div className="flex shrink-0 items-center gap-2">
                        {patient.has_red_flags && (
                          <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-bold text-red-600">
                            {patient.red_flag_count} RED FLAG
                            {patient.red_flag_count > 1 ? "S" : ""}
                          </span>
                        )}
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            patient.summary_status === "confirmed"
                              ? "bg-govgreen/10 text-govgreen"
                              : patient.summary_status === "draft"
                                ? "bg-saffron/10 text-saffron-dark"
                                : "bg-gray-100 text-gray-500"
                          }`}
                        >
                          {patient.summary_status ?? "awaiting summary"}
                        </span>
                        <span className="text-gray-400">→</span>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
