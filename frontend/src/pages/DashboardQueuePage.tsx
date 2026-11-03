/**
 * Patient queue screen — the first thing the physician sees after login.
 *
 * Red-flag patients are visually distinguished and sorted to the top.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { type QueuePatient, type QueueResponse, fetchQueue } from "../api/dashboard";
import { SkeletonCard } from "../components/Spinner";

export function DashboardQueuePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [queue, setQueue] = useState<QueuePatient[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchQueue()
      .then((res: QueueResponse) => {
        if (!cancelled) {
          setQueue(res.patients);
          setLoading(false);
        }
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

  if (loading) {
    return (
      <main className="min-h-[calc(100vh-10rem)] bg-surface px-6 py-8">
        <div className="mx-auto max-w-5xl space-y-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-[calc(100vh-10rem)] bg-surface px-6 py-8">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-primary-600">
              {t("dashboard.queue.title", "Patient Queue")}
            </h1>
            <p className="text-xs text-gray-500">Ayushman Bharat Digital Health Mission</p>
          </div>
          <span
            className="rounded-full px-4 py-1 text-sm font-medium text-white shadow-sm"
            style={{
              background: "linear-gradient(135deg, #002B5B 0%, #0F6DB8 100%)",
            }}
          >
            {queue.length} {t("dashboard.queue.patients", "patients")}
          </span>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-red-700">
            {error}
          </div>
        )}

        {queue.length === 0 ? (
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
            {queue.map((patient) => (
              <button
                key={patient.patient_id}
                onClick={() => navigate(`/dashboard/patient/${patient.patient_id}`)}
                className={`govt-card govt-card-hover w-full p-5 text-left ${
                  patient.has_red_flags ? "border-red-300" : ""
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {patient.has_red_flags && (
                      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-red-50">
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
                    <div>
                      <h3 className="text-base font-semibold text-gray-900">{patient.name}</h3>
                      <p className="text-sm text-gray-500">
                        {patient.age && `${patient.age}y`}
                        {patient.gender && ` / ${patient.gender}`}
                        {patient.chief_complaint &&
                          ` — ${patient.chief_complaint.replace(/_/g, " ")}`}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {patient.has_red_flags && (
                      <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-bold text-red-600">
                        {patient.red_flag_count} RED FLAG{patient.red_flag_count > 1 ? "S" : ""}
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
      </div>
    </main>
  );
}
