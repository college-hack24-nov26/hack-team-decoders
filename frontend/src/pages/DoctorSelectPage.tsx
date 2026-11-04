/**
 * Doctor selection (F2) — pick a department, then a doctor, then get a token.
 *
 * Two steps on one screen: department grid first, then the doctors in that
 * department. Selecting a doctor books a visit and shows the token number
 * before continuing to consent.
 *
 * The department grid is built from the doctors the backend returns, not from a
 * hard-coded list. A fixed list ("Allopathy" / "AYUSH") never matched the
 * departments doctors are actually stored under, so every department opened
 * onto "no doctors available".
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { createVisit, listDoctors, type DoctorItem } from "../api/clinic";
import { Spinner } from "../components/Spinner";
import { setVisitSelection } from "../store/visit";

/** The AYUSH systems of medicine; every other department is modern medicine. */
const AYUSH_DEPARTMENTS = new Set([
  "Ayurveda",
  "Yoga & Naturopathy",
  "Unani",
  "Siddha",
  "Sowa-Rigpa",
  "Homeopathy",
]);

const DEPARTMENT_ICONS: Record<string, string> = {
  "General Medicine": "🩺",
  Cardiology: "❤️",
  Pediatrics: "🧒",
  Orthopedics: "🦴",
  ENT: "👂",
  Gynaecology: "🤰",
  Dermatology: "🧴",
  Ayurveda: "🌿",
  Homeopathy: "💧",
  Unani: "🌱",
  Siddha: "🍃",
  "Yoga & Naturopathy": "🧘",
};

interface Department {
  name: string;
  doctors: DoctorItem[];
  available: number;
}

export function DoctorSelectPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [department, setDepartment] = useState<string | null>(null);
  const [allDoctors, setAllDoctors] = useState<DoctorItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [booking, setBooking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    listDoctors()
      .then((list) => {
        if (!cancelled) setAllDoctors(list);
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
  }, [t]);

  const departments = useMemo(() => {
    const byName = new Map<string, Department>();
    for (const doc of allDoctors) {
      const entry = byName.get(doc.department) ?? {
        name: doc.department,
        doctors: [],
        available: 0,
      };
      entry.doctors.push(doc);
      if (doc.available) entry.available += 1;
      byName.set(doc.department, entry);
    }
    const sorted = [...byName.values()].sort((a, b) => a.name.localeCompare(b.name));
    return {
      modern: sorted.filter((d) => !AYUSH_DEPARTMENTS.has(d.name)),
      ayush: sorted.filter((d) => AYUSH_DEPARTMENTS.has(d.name)),
    };
  }, [allDoctors]);

  const doctors = useMemo(
    () =>
      allDoctors
        .filter((d) => d.department === department)
        .sort((a, b) => Number(b.available) - Number(a.available) || a.queue_count - b.queue_count),
    [allDoctors, department],
  );

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

  const departmentLabel = (name: string) => t(`doctor.dept.${departmentKey(name)}`, name);

  const renderGroup = (title: string, list: Department[]) =>
    list.length > 0 && (
      <section className="mb-8">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
          {title}
        </h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          {list.map((d) => (
            <button
              key={d.name}
              onClick={() => setDepartment(d.name)}
              className="govt-card govt-card-hover flex min-h-[7.5rem] flex-col items-center justify-center gap-2 p-4 text-center"
            >
              <span className="text-3xl" aria-hidden="true">
                {DEPARTMENT_ICONS[d.name] ?? "🏥"}
              </span>
              <span className="text-base font-semibold text-gray-900">
                {departmentLabel(d.name)}
              </span>
              <span className="text-xs text-gray-500">
                {t("doctor.availableCount", "{{count}} available", { count: d.available })}
              </span>
            </button>
          ))}
        </div>
      </section>
    );

  return (
    <main className="flex flex-col items-center px-6 py-8">
      <div className="w-full max-w-3xl">
        <h1 className="mb-2 text-center text-2xl font-bold text-primary-600">
          {department ? t("doctor.selectDoctor") : t("doctor.selectDepartment")}
        </h1>
        <p className="mb-6 text-center text-gray-600">
          {department ? departmentLabel(department) : t("doctor.departmentSubtitle")}
        </p>

        {error && (
          <div
            className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            role="alert"
          >
            {error}
          </div>
        )}

        {loading && (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        )}

        {/* Step 1 — department grid */}
        {!loading && !department && (
          <>
            {renderGroup(t("doctor.groupModern", "Modern medicine"), departments.modern)}
            {renderGroup(t("doctor.groupAyush", "AYUSH"), departments.ayush)}
            {allDoctors.length === 0 && !error && (
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
            )}
          </>
        )}

        {/* Step 2 — doctors in the chosen department */}
        {department && (
          <>
            <ul className="space-y-3">
              {doctors.map((doc) => (
                <li key={doc.id}>
                  <button
                    onClick={() => void book(doc)}
                    disabled={booking || !doc.available}
                    className="govt-card govt-card-hover flex w-full items-center justify-between gap-4 p-5 text-left disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <div>
                      <div className="text-lg font-semibold text-gray-900">{doc.name}</div>
                      {doc.specialization && (
                        <div className="text-sm text-gray-500">{doc.specialization}</div>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <span
                        className={`rounded-full px-3 py-1 text-xs font-semibold ${
                          doc.available
                            ? "bg-govgreen/10 text-govgreen"
                            : "bg-gray-100 text-gray-500"
                        }`}
                      >
                        {doc.available
                          ? t("doctor.available", "Available")
                          : t("doctor.unavailable", "Not available today")}
                      </span>
                      <span className="rounded-full bg-primary-50 px-3 py-1 text-sm font-medium text-primary-700">
                        {t("doctor.inQueue", { count: doc.queue_count })}
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>

            <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
              <button
                onClick={() => setDepartment(null)}
                className="text-sm font-medium text-primary-600 underline"
              >
                {t("doctor.changeDepartment")}
              </button>
              <button
                onClick={() => void book(null)}
                disabled={booking}
                className="text-sm font-medium text-gray-500 underline"
              >
                {t("doctor.continueAnyway")}
              </button>
            </div>
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
