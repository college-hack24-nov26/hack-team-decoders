/**
 * Doctor selection (F2) — pick a department, then a doctor, then get a token.
 *
 * Two steps on one screen: department grid first, then the available doctors in
 * that department. Selecting a doctor books a visit and shows the token number
 * before continuing to consent.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { createVisit, listDoctors, type DoctorItem } from "../api/clinic";
import { Spinner } from "../components/Spinner";
import { setVisitSelection } from "../store/visit";

const DEPARTMENTS: { key: string; icon: string }[] = [
  { key: "Allopathy", icon: "🏥" },
  { key: "AYUSH", icon: "🌿" },
];

export function DoctorSelectPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [department, setDepartment] = useState<string | null>(null);
  const [doctors, setDoctors] = useState<DoctorItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [booking, setBooking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!department) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    listDoctors(department)
      .then((list) => {
        if (!cancelled) setDoctors(list);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : t("common.error"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [department, t]);

  const book = async (doctor: DoctorItem | null) => {
    setBooking(true);
    setError("");
    try {
      const visit = await createVisit({
        doctorId: doctor?.id,
        department: department ?? undefined,
      });
      setVisitSelection({
        visitId: visit.id,
        tokenNumber: visit.token_number,
        department: visit.department,
        doctorId: visit.doctor_id,
        doctorName: visit.doctor_name,
      });
      navigate("/consent");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("common.error"));
      setBooking(false);
    }
  };

  return (
    <main className="flex flex-col items-center px-6 py-8">
      <div className="w-full max-w-3xl">
        <h1 className="mb-2 text-center text-2xl font-bold text-primary-600">
          {department ? t("doctor.selectDoctor") : t("doctor.selectDepartment")}
        </h1>
        <p className="mb-6 text-center text-gray-600">
          {department ? department : t("doctor.departmentSubtitle")}
        </p>

        {error && (
          <div
            className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            role="alert"
          >
            {error}
          </div>
        )}

        {/* Step 1 — department grid */}
        {!department && (
          <div className="mx-auto grid max-w-xl grid-cols-1 gap-6 sm:grid-cols-2">
            {DEPARTMENTS.map((d) => (
              <button
                key={d.key}
                onClick={() => setDepartment(d.key)}
                className="govt-card govt-card-hover flex min-h-[8rem] flex-col items-center justify-center gap-3 p-5 text-center"
              >
                <span className="text-4xl" aria-hidden="true">
                  {d.icon}
                </span>
                <span className="text-base font-semibold text-gray-900">
                  {t(`doctor.dept.${departmentKey(d.key)}`, d.key)}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* Step 2 — doctors in the chosen department */}
        {department && (
          <>
            {loading ? (
              <div className="flex justify-center py-10">
                <Spinner />
              </div>
            ) : doctors.length === 0 ? (
              <div className="rounded-md border border-gray-200 bg-surface-section p-6 text-center text-gray-500">
                {t("doctor.noneAvailable")}
                <div className="mt-4">
                  <button
                    onClick={() => void book(null)}
                    disabled={booking}
                    className="btn-primary px-6 py-3"
                  >
                    {t("doctor.continueAnyway")}
                  </button>
                </div>
              </div>
            ) : (
              <ul className="space-y-3">
                {doctors.map((doc) => (
                  <li key={doc.id}>
                    <button
                      onClick={() => void book(doc)}
                      disabled={booking}
                      className="govt-card govt-card-hover flex w-full items-center justify-between gap-4 p-5 text-left disabled:opacity-60"
                    >
                      <div>
                        <div className="text-lg font-semibold text-gray-900">{doc.name}</div>
                        {doc.specialization && (
                          <div className="text-sm text-gray-500">{doc.specialization}</div>
                        )}
                      </div>
                      <span className="shrink-0 rounded-full bg-primary-50 px-3 py-1 text-sm font-medium text-primary-700">
                        {t("doctor.inQueue", { count: doc.queue_count })}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <button
              onClick={() => {
                setDepartment(null);
                setDoctors([]);
              }}
              className="mt-6 text-sm font-medium text-primary-600 underline"
            >
              {t("doctor.changeDepartment")}
            </button>
          </>
        )}

        {booking && (
          <p className="mt-4 text-center text-sm text-gray-500" role="status">
            {t("doctor.booking")}
          </p>
        )}
      </div>
    </main>
  );
}

/** Map a department display name to its locale key suffix. */
function departmentKey(name: string): string {
  return name.toLowerCase().replace(/[^a-z]+/g, "_");
}
