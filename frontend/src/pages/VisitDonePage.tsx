/**
 * The end of the kiosk journey: terminal confirmation screen.
 */

import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { clearVisit, getCompletedInterview } from "../store/visit";
import { useAuth } from "../store/auth";

export function VisitDonePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { patient, logout } = useAuth();

  const interviewDone = getCompletedInterview() !== null;

  const handleFinish = () => {
    clearVisit();
    logout();
    navigate("/");
  };

  return (
    <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center justify-center px-6 py-8">
      <div className="w-full max-w-lg text-center">
        {/* Success illustration */}
        <div className="mb-4 flex flex-col items-center gap-2">
          <div
            className="flex h-16 w-16 items-center justify-center rounded-full"
            aria-hidden="true"
            style={{
              background:
                "linear-gradient(135deg, rgba(46, 125, 50, 0.1), rgba(76, 175, 80, 0.15))",
            }}
          >
            <svg
              className="h-8 w-8 text-govgreen"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2.5}
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
        </div>

        <h1 className="mb-2 text-2xl font-bold text-primary-600">
          {patient?.name ? t("visitDone.titleNamed", { name: patient.name }) : t("visitDone.title")}
        </h1>

        <p className="mb-2 text-base text-gray-700">{t("visitDone.saved")}</p>
        <p className="mb-4 text-base font-medium text-primary-600">{t("visitDone.queue")}</p>

        {/* AB acknowledgment with emblem */}
        <div className="mb-4 flex items-center justify-center gap-3 rounded-lg border border-primary-100 bg-primary-50/50 px-4 py-3">
          <img src="/kiosk/abdm-logo.png" alt="ABDM" className="h-10 w-auto" />
          <p className="text-left text-xs text-primary-800">
            <span className="font-semibold">आयुष्मान भारत</span> — Your health record is secured
            under the ABDM framework and DISHA guidelines.
          </p>
        </div>

        {!interviewDone && (
          <div
            className="mb-6 rounded-md border border-saffron/30 bg-saffron/5 px-4 py-3 text-left text-sm text-saffron-dark"
            role="status"
          >
            <p className="mb-2">{t("visitDone.interviewPending")}</p>
            <button
              onClick={() => navigate("/interview")}
              className="font-semibold text-primary-600 underline hover:no-underline"
            >
              {t("visitDone.goToInterview")}
            </button>
          </div>
        )}

        <div className="flex flex-col gap-3">
          <button
            onClick={() => navigate("/documents/upload")}
            className="btn-secondary w-full py-3 text-base"
          >
            {t("visitDone.addMorePapers")}
          </button>
          <button onClick={handleFinish} className="btn-primary w-full py-3 text-base">
            {t("visitDone.finish")}
          </button>
        </div>
      </div>
    </main>
  );
}
