/**
 * Patient Summary Review & Confirmation screen.
 *
 * Shows the patient exactly what they told the kiosk, grouped by section, read
 * from their own interview session. It used to call the physician dashboard's
 * summary route, which a patient token cannot read, so it always fell back to
 * placeholder text ("General Consultation", "No known drug allergies") that the
 * patient never said — and then asked them to confirm it.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { type ReviewItem, type SessionReview, getSessionReview } from "../api/interview";
import { HealthShield } from "../components/AyushmanIcons";
import { SkeletonCard } from "../components/Spinner";
import { showToast } from "../components/toast-store";
import { getLanguage } from "../store/language";
import { getCompletedInterview, getVisitSelection } from "../store/visit";
import { canSpeak, speak as speakInBrowser, stopSpeaking } from "../utils/speech";

/** English headings for the interview's sections (see Section in ontology.py). */
const SECTION_TITLES: Record<string, string> = {
  chief_complaint: "Main problem",
  hpi: "About this problem",
  past_medical: "Past illnesses",
  past_surgical: "Past operations",
  drug_history: "Medicines",
  allergy: "Allergies",
  family_history: "Family history",
  personal_history: "Lifestyle",
  ayush: "Ayurvedic assessment",
  review_of_systems: "Other symptoms",
};

function sectionTitle(section: string): string {
  return SECTION_TITLES[section] ?? section.replace(/_/g, " ");
}

export function PatientSummaryPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const visitSelection = getVisitSelection();
  const sessionId = getCompletedInterview();

  const [review, setReview] = useState<SessionReview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!sessionId || sessionId === "skipped") {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setReview(await getSessionReview(sessionId));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.error"));
    } finally {
      setLoading(false);
    }
  }, [sessionId, t]);

  useEffect(() => {
    void load();
    return stopSpeaking;
  }, [load]);

  const groups = useMemo(() => {
    const out: { section: string; items: ReviewItem[] }[] = [];
    for (const item of review?.items ?? []) {
      const last = out[out.length - 1];
      if (last && last.section === item.section) last.items.push(item);
      else out.push({ section: item.section, items: [item] });
    }
    return out;
  }, [review]);

  const readAloud = () => {
    const text = (review?.items ?? [])
      .filter((i) => !i.skipped)
      .map((i) => `${i.question} ${i.answer}.`)
      .join(" ");
    void speakInBrowser(text, review?.language ?? getLanguage()).catch(() => undefined);
  };

  const handleConfirm = () => {
    stopSpeaking();
    showToast(
      t("patientSummary.confirmedToast", "Thank you — your answers are with the doctor"),
      "success",
    );
    navigate("/visit/done");
  };

  if (loading) {
    return (
      <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center justify-center px-6 py-8">
        <div className="w-full max-w-lg space-y-4 text-center">
          <h2 className="text-xl font-bold text-gray-800">{t("patientSummary.generatingTitle")}</h2>
          <SkeletonCard />
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center px-6 py-8">
      <div className="w-full max-w-2xl">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold text-primary-600">{t("patientSummary.title")}</h1>
          <p className="mt-1 text-sm text-gray-600">
            {t(
              "patientSummary.reviewSubtitle",
              "This is what you told us. The doctor will see these answers.",
            )}
          </p>
        </div>

        <div className="mb-6 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary-100 bg-primary-50/50 p-3">
          <div className="flex items-center gap-2">
            <HealthShield size={20} className="text-primary-600" />
            <span className="text-xs font-semibold text-primary-800">
              {t("patientSummary.abdmNotice")}
            </span>
          </div>
          {visitSelection && (
            <span className="text-xs font-medium text-gray-600">
              {t("patientSummary.token", "Token #{{n}}", { n: visitSelection.tokenNumber })}
              {visitSelection.doctorName ? ` · ${visitSelection.doctorName}` : ""}
              {visitSelection.department ? ` · ${visitSelection.department}` : ""}
            </span>
          )}
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
            <button onClick={() => void load()} className="ml-3 underline">
              {t("common.retry", "Try again")}
            </button>
          </div>
        )}

        {!review && !error && (
          <div className="govt-card p-6 text-center text-gray-600">
            {t("patientSummary.noInterview", "No interview answers were recorded for this visit.")}
          </div>
        )}

        {review && canSpeak() && (
          <button
            type="button"
            onClick={readAloud}
            className="mb-4 flex items-center gap-2 rounded-md px-3 py-2 text-base text-primary-600 hover:bg-primary-50"
          >
            <span aria-hidden="true">🔊</span>
            {t("patientSummary.readAloud", "Read my answers aloud")}
          </button>
        )}

        <div className="space-y-4">
          {groups.map((group) => (
            <section key={group.section} className="govt-card p-4">
              <h2 className="mb-2 text-xs font-bold uppercase tracking-wider text-gray-500">
                {t(`patientSummary.sections.${group.section}`, sectionTitle(group.section))}
              </h2>
              <dl className="divide-y divide-gray-100">
                {group.items.map((item) => (
                  <div key={item.field_id} className="py-2">
                    <dt className="text-sm text-gray-500">{item.question}</dt>
                    <dd className="text-base font-medium text-gray-900">
                      {item.skipped ? (
                        <span className="italic text-gray-400">
                          {t("patientSummary.skipped", "Skipped")}
                        </span>
                      ) : (
                        item.answer
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>

        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
          <button
            type="button"
            onClick={() => navigate("/documents/upload")}
            className="btn-secondary flex-1 py-3.5 text-base"
          >
            {t("patientSummary.addPapers", "Add medical papers")}
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            className="btn-primary flex-1 py-3.5 text-base"
          >
            ✓ {t("patientSummary.confirmBtn")}
          </button>
        </div>
      </div>
    </main>
  );
}
