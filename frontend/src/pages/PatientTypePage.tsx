/**
 * Patient type selection — the first screen after language (F2).
 *
 * Two large cards: new patient (register) or returning patient (phone lookup).
 * Kept deliberately sparse and big — this is the first thing an anxious,
 * possibly elderly walk-up patient sees, so it must be obvious which card is
 * theirs without reading fine print.
 */

import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

export function PatientTypePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <main className="flex flex-col items-center justify-center px-6 py-10">
      <h1 className="mb-2 text-center text-2xl font-bold text-primary-600">
        {t("patientType.title")}
      </h1>
      <p className="mb-8 max-w-md text-center text-base text-gray-600">
        {t("patientType.subtitle")}
      </p>

      <div className="grid w-full max-w-3xl gap-5 sm:grid-cols-2">
        <button
          onClick={() => navigate("/login/new")}
          className="govt-card govt-card-hover flex min-h-[13rem] flex-col items-center justify-center gap-4 p-8 text-center"
        >
          <span className="text-5xl" aria-hidden="true">
            🏥
          </span>
          <span className="text-xl font-bold text-gray-900">{t("patientType.newTitle")}</span>
          <span className="text-sm text-gray-500">{t("patientType.newSubtitle")}</span>
        </button>

        <button
          onClick={() => navigate("/login/returning")}
          className="govt-card govt-card-hover flex min-h-[13rem] flex-col items-center justify-center gap-4 p-8 text-center"
        >
          <span className="text-5xl" aria-hidden="true">
            🙋
          </span>
          <span className="text-xl font-bold text-gray-900">{t("patientType.returningTitle")}</span>
          <span className="text-sm text-gray-500">{t("patientType.returningSubtitle")}</span>
        </button>
      </div>
    </main>
  );
}
