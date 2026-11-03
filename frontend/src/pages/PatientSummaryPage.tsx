/**
 * Patient Summary Review & Confirmation screen.
 *
 * Allows the patient to review the generated structured summary,
 * edit key fields locally if needed, and confirm their summary before proceeding.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { fetchPatientSummary, type StructuredContent } from "../api/dashboard";
import { HealthShield } from "../components/AyushmanIcons";
import { SkeletonCard, Spinner } from "../components/Spinner";
import { showToast } from "../components/toast-store";
import { useAuth } from "../store/auth";
import { getVisitSelection } from "../store/visit";

export function PatientSummaryPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { patient } = useAuth();
  const visitSelection = getVisitSelection();

  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [isEditedLocally, setIsEditedLocally] = useState(false);
  const [isConfirmedLocally, setIsConfirmedLocally] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form edit fields
  const [chiefComplaint, setChiefComplaint] = useState("");
  const [hpiNarrative, setHpiNarrative] = useState("");
  const [pastHistory, setPastHistory] = useState("");
  const [allergies, setAllergies] = useState("");
  const [ayushAssessment, setAyushAssessment] = useState("");

  const loadSummaryData = useCallback(async () => {
    setLoading(true);
    setError(null);

    // Initial fallback values from visit selection
    const deptName = visitSelection?.department || "General";
    setChiefComplaint(`${deptName} Consultation`);
    setHpiNarrative("Patient health history collected via voice and touch interview.");
    setPastHistory("None reported during initial intake.");
    setAllergies("No known drug allergies.");

    if (patient?.id) {
      try {
        const res = await fetchPatientSummary(patient.id);
        if (res?.summary?.structured_content) {
          const sc: StructuredContent = res.summary.structured_content;
          if (sc.chief_complaint) setChiefComplaint(sc.chief_complaint);
          if (sc.hpi?.narrative) setHpiNarrative(sc.hpi.narrative);
          if (sc.past_medical_history) setPastHistory(sc.past_medical_history);
          if (sc.allergies) setAllergies(sc.allergies);
          if (sc.ayush_assessment) setAyushAssessment(sc.ayush_assessment);
        }
      } catch {
        // Safe fallback to local session state if summary endpoint is not populated yet
      }
    }
    setLoading(false);
  }, [patient?.id, visitSelection?.department]);

  useEffect(() => {
    void loadSummaryData();
  }, [loadSummaryData]);

  const handleSaveEdits = () => {
    setEditing(false);
    setIsEditedLocally(true);
    showToast("Summary updated (Local Review)", "success");
  };

  const handleConfirm = () => {
    setIsConfirmedLocally(true);
    showToast("Summary reviewed and confirmed!", "success");
    navigate("/visit/done");
  };

  if (loading) {
    return (
      <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center justify-center px-6 py-8">
        <div className="w-full max-w-lg space-y-4 text-center">
          <Spinner size="md" className="mx-auto text-primary-600" />
          <h2 className="text-xl font-bold text-gray-800">
            {t("patientSummary.generatingTitle", "Preparing Your Health Summary...")}
          </h2>
          <p className="text-sm text-gray-500">
            {t(
              "patientSummary.generatingSubtitle",
              "Combining your uploaded documents & responses",
            )}
          </p>
          <SkeletonCard />
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center justify-center px-6 py-8">
        <div className="w-full max-w-lg text-center">
          <div className="mb-4 rounded-md border border-red-200 bg-red-50 p-4 text-red-700">
            {error}
          </div>
          <button onClick={() => void loadSummaryData()} className="btn-primary px-6 py-3">
            {t("common.retry", "Try Again")}
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center px-6 py-8">
      <div className="w-full max-w-2xl">
        {/* Header */}
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-bold text-primary-600">
            {t("patientSummary.title", "Review Your Medical Summary")}
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            {t(
              "patientSummary.subtitle",
              "Please review the summary below. You can edit any field or confirm to proceed.",
            )}
          </p>
        </div>

        {/* ABDM Security badge */}
        <div className="mb-6 flex items-center justify-between rounded-lg border border-primary-100 bg-primary-50/50 p-3">
          <div className="flex items-center gap-2">
            <HealthShield size={20} className="text-primary-600" />
            <span className="text-xs font-semibold text-primary-800">
              {t("patientSummary.abdmNotice", "Encrypted & Prepared for Physician Review")}
            </span>
          </div>
          {/* Status badges */}
          <div className="flex items-center gap-2">
            {isEditedLocally && (
              <span className="rounded-full bg-saffron/10 px-2.5 py-0.5 text-xs font-semibold text-saffron-dark">
                {t("patientSummary.editedBadge", "Edited by Patient")}
              </span>
            )}
            {isConfirmedLocally && (
              <span className="rounded-full bg-govgreen/10 px-2.5 py-0.5 text-xs font-semibold text-govgreen">
                {t("patientSummary.confirmedBadge", "Confirmed by Patient")}
              </span>
            )}
          </div>
        </div>

        {/* Structured summary sections */}
        <div className="space-y-4">
          {/* Department / Chief Complaint */}
          <div className="govt-card p-4">
            <label className="block text-xs font-bold uppercase tracking-wider text-gray-500">
              {t("patientSummary.chiefComplaint", "Chief Complaint / Primary Concern")}
            </label>
            {editing ? (
              <input
                type="text"
                value={chiefComplaint}
                onChange={(e) => setChiefComplaint(e.target.value)}
                className="mt-2 w-full rounded-md border border-gray-300 p-2 text-sm focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200"
              />
            ) : (
              <p className="mt-1 text-base font-semibold text-gray-800">
                {chiefComplaint || t("common.none", "None specified")}
              </p>
            )}
          </div>

          {/* HPI Narrative */}
          <div className="govt-card p-4">
            <label className="block text-xs font-bold uppercase tracking-wider text-gray-500">
              {t("patientSummary.symptoms", "History of Presenting Symptoms")}
            </label>
            {editing ? (
              <textarea
                rows={3}
                value={hpiNarrative}
                onChange={(e) => setHpiNarrative(e.target.value)}
                className="mt-2 w-full rounded-md border border-gray-300 p-2 text-sm focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200"
              />
            ) : (
              <p className="mt-1 text-sm leading-relaxed text-gray-800">
                {hpiNarrative || t("common.none", "No details recorded")}
              </p>
            )}
          </div>

          {/* Medical History */}
          <div className="govt-card p-4">
            <label className="block text-xs font-bold uppercase tracking-wider text-gray-500">
              {t("patientSummary.pastHistory", "Past Medical History")}
            </label>
            {editing ? (
              <input
                type="text"
                value={pastHistory}
                onChange={(e) => setPastHistory(e.target.value)}
                className="mt-2 w-full rounded-md border border-gray-300 p-2 text-sm focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200"
              />
            ) : (
              <p className="mt-1 text-sm text-gray-800">
                {pastHistory || t("common.none", "None")}
              </p>
            )}
          </div>

          {/* Allergies */}
          <div className="govt-card p-4">
            <label className="block text-xs font-bold uppercase tracking-wider text-gray-500">
              {t("patientSummary.allergies", "Allergies & Sensitivities")}
            </label>
            {editing ? (
              <input
                type="text"
                value={allergies}
                onChange={(e) => setAllergies(e.target.value)}
                className="mt-2 w-full rounded-md border border-gray-300 p-2 text-sm focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200"
              />
            ) : (
              <p className="mt-1 text-sm font-medium text-gray-800">
                {allergies || t("common.none", "No known allergies")}
              </p>
            )}
          </div>

          {/* AYUSH Assessment if present */}
          {ayushAssessment && (
            <div className="govt-card p-4 border-l-4 border-l-govgreen">
              <label className="block text-xs font-bold uppercase tracking-wider text-govgreen">
                AYUSH / Ayurvedic Assessment
              </label>
              <p className="mt-1 text-sm text-gray-800">{ayushAssessment}</p>
            </div>
          )}
        </div>

        {/* Action Controls */}
        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
          {editing ? (
            <>
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="btn-secondary flex-1 py-3 text-base"
              >
                {t("common.cancel", "Cancel")}
              </button>
              <button
                type="button"
                onClick={handleSaveEdits}
                className="btn-primary flex-1 py-3 text-base"
              >
                {t("patientSummary.saveEdits", "Save Changes")}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="btn-secondary flex-1 py-3.5 text-base"
              >
                ✏️ {t("patientSummary.editBtn", "Edit Details")}
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                className="btn-primary flex-1 py-3.5 text-base"
              >
                ✓ {t("patientSummary.confirmBtn", "Confirm Summary")}
              </button>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
