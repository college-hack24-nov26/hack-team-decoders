/**
 * Summary review page — the physician's main working screen.
 *
 * Shows the structured summary sectioned per the fixed schema, with editable
 * fields and Accept/Reject controls.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import {
  type DocumentItem,
  type PatientSummaryResponse,
  type RedFlagItem,
  type StructuredContent,
  type SummaryData,
  confirmSummary,
  editSummary,
  fetchPatientSummary,
  fetchReportBlob,
  generateSummary,
  pushToAbdm,
} from "../api/dashboard";
import { Spinner, SkeletonCard } from "../components/Spinner";
import { showToast } from "../components/toast-store";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionField({
  label,
  value,
  field,
  editing,
  onChange,
}: {
  label: string;
  value: string;
  field: string;
  editing: boolean;
  onChange: (field: string, value: string) => void;
}) {
  if (editing) {
    return (
      <div className="mb-3">
        <label className="mb-1 block text-sm font-semibold text-gray-700">{label}</label>
        <textarea
          value={value}
          onChange={(e) => onChange(field, e.target.value)}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-200"
          rows={value.length > 100 ? 4 : 2}
        />
      </div>
    );
  }

  return (
    <div className="mb-3">
      <dt className="text-sm font-semibold text-gray-500">{label}</dt>
      <dd className="mt-1 text-gray-900">
        {value || <em className="text-gray-400">Not recorded</em>}
      </dd>
    </div>
  );
}

function RedFlagBanner({ flags }: { flags: RedFlagItem[] }) {
  if (flags.length === 0) return null;
  return (
    <div className="mb-4 rounded-md border-2 border-red-300 bg-red-50 p-5">
      <h3 className="mb-2 text-base font-bold text-red-800">Red Flags</h3>
      {flags.map((f, i) => (
        <p key={i} className="text-sm text-red-700">
          <span className="font-semibold">[{f.severity}]</span> {f.symptom.replace(/_/g, " ")}
        </p>
      ))}
    </div>
  );
}

const ENTITY_LABELS: Record<string, string> = {
  investigation_value: "Lab",
  medication: "Medicine",
  diagnosis: "Diagnosis",
  procedure: "Procedure",
};

/** One extracted entity as a readable line, e.g. "HbA1c: 7.8 % (ref 4.0-5.6)". */
function formatEntity(type: string, value: Record<string, unknown>): string {
  const s = (key: string) =>
    value[key] === undefined || value[key] === null ? "" : String(value[key]);
  switch (type) {
    case "investigation_value": {
      const ref = s("reference_range") ? ` (ref ${s("reference_range")})` : "";
      return `${s("test")}: ${s("value")} ${s("unit")}${ref}`.replace(/\s+/g, " ").trim();
    }
    case "medication":
      return [s("drug"), s("dose"), s("frequency")].filter(Boolean).join(" · ");
    case "diagnosis":
      return s("diagnosis") || Object.values(value).join(", ");
    case "procedure":
      return s("procedure") || Object.values(value).join(", ");
    default:
      return Object.entries(value)
        .map(([k, v]) => `${k.replace(/_/g, " ")}: ${String(v)}`)
        .join(", ");
  }
}

function DocumentTimeline({ documents }: { documents: DocumentItem[] }) {
  if (documents.length === 0) return null;
  return (
    <div className="govt-card p-5">
      <h3 className="mb-3 text-base font-semibold text-gray-800">Documents</h3>
      <div className="space-y-2">
        {documents.map((doc) => (
          <div key={doc.id} className="rounded-md border border-gray-100 bg-surface-section p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-700">
                {doc.doc_type.replace(/_/g, " ")}
              </span>
              {doc.document_date && (
                <span className="text-xs text-gray-500">{doc.document_date}</span>
              )}
            </div>
            {doc.entities.length > 0 && (
              <ul className="mt-2 space-y-1">
                {doc.entities.map((e, i) => (
                  <li
                    key={i}
                    className={`text-xs ${e.is_abnormal ? "font-semibold text-red-600" : "text-gray-600"}`}
                  >
                    <span className="mr-1 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-gray-500">
                      {ENTITY_LABELS[e.entity_type] ?? e.entity_type.replace(/_/g, " ")}
                    </span>
                    {formatEntity(e.entity_type, e.value)}
                    {e.is_abnormal && " — abnormal"}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SummaryReviewPage() {
  const { t } = useTranslation();
  void t;
  const navigate = useNavigate();
  const { patientId } = useParams<{ patientId: string }>();

  const [data, setData] = useState<PatientSummaryResponse | null>(null);
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [editing, setEditing] = useState(false);
  const [editedContent, setEditedContent] = useState<StructuredContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [rejectionReason, setRejectionReason] = useState("");
  const [viewingTranscript, setViewingTranscript] = useState(false);

  useEffect(() => {
    if (!patientId) return;
    let cancelled = false;
    fetchPatientSummary(patientId)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          if (res.summary) {
            setSummary(res.summary as unknown as SummaryData);
            setEditedContent(res.summary.structured_content as unknown as StructuredContent);
          }
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load patient data");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [patientId]);

  const handleGenerate = useCallback(async () => {
    if (!data?.session_id) {
      setError("This patient has no interview session to summarise yet.");
      return;
    }
    setGenerating(true);
    setError("");
    try {
      const result = await generateSummary(data.session_id);
      setSummary(result);
      setEditedContent(result.structured_content);
      setSuccess("Summary generated successfully");
      showToast("Summary generated", "success");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
      showToast("Generation failed", "error");
    } finally {
      setGenerating(false);
    }
  }, [data]);

  const handleSave = useCallback(async () => {
    if (!summary || !editedContent) return;
    setError("");
    try {
      const result = await editSummary(summary.id, editedContent);
      setSummary(result);
      setEditing(false);
      setSuccess("Changes saved");
      showToast("Changes saved", "success");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
      showToast("Save failed", "error");
    }
  }, [summary, editedContent]);

  const handleDecision = useCallback(
    async (decision: "accept" | "reject") => {
      if (!summary) return;

      let reason: string | undefined;
      if (decision === "reject") {
        reason = rejectionReason.trim();
        if (!reason) {
          setError("Please say what was wrong with the draft before rejecting it.");
          return;
        }
      }

      setError("");
      try {
        const result = await confirmSummary(summary.id, decision, reason);
        setSummary(result);
        setRejecting(false);
        setRejectionReason("");
        setSuccess(decision === "accept" ? "Summary confirmed" : "Summary rejected");
        showToast(
          decision === "accept" ? "Summary confirmed" : "Summary rejected",
          decision === "accept" ? "success" : "info",
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : "Action failed");
      }
    },
    [summary, rejectionReason],
  );

  const handleDownloadReport = useCallback(async () => {
    if (!patientId) return;
    try {
      const url = await fetchReportBlob(patientId);
      const link = document.createElement("a");
      link.href = url;
      link.download = `medikiosk_report_${patientId.slice(0, 8)}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
      showToast("Report downloaded", "success");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Report download failed");
      showToast("Download failed", "error");
    }
  }, [patientId]);

  const handlePush = useCallback(async () => {
    if (!summary) return;
    try {
      const result = await pushToAbdm(summary.id);
      setSuccess(result.message);
      showToast(result.message, "success");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Push failed");
      showToast("Push failed", "error");
    }
  }, [summary]);

  const handleFieldChange = (field: string, value: string) => {
    if (!editedContent) return;
    const parts = field.split(".");
    if (parts.length === 2 && parts[0] === "hpi") {
      setEditedContent({
        ...editedContent,
        hpi: { ...editedContent.hpi, [parts[1]]: value },
      });
    } else {
      setEditedContent({ ...editedContent, [field]: value });
    }
  };

  if (loading) {
    return (
      <main className="min-h-[calc(100vh-10rem)] bg-surface px-6 py-8">
        <div className="mx-auto max-w-6xl grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <SkeletonCard />
          </div>
          <div>
            <SkeletonCard />
          </div>
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="flex min-h-[calc(100vh-10rem)] items-center justify-center px-6 py-8">
        <p className="text-base text-red-600">Patient not found</p>
      </main>
    );
  }

  const content = editedContent ?? summary?.structured_content;

  return (
    <main className="min-h-[calc(100vh-10rem)] bg-surface px-6 py-8">
      <div className="mx-auto max-w-6xl">
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <div>
            <button
              onClick={() => navigate("/dashboard")}
              className="mb-1 text-sm text-primary-600 hover:underline"
            >
              ← Back to queue
            </button>
            <h1 className="text-xl font-bold text-gray-900">
              {data.patient.name}
              <span className="ml-3 text-base font-normal text-gray-500">
                {data.patient.age}y / {data.patient.gender}
              </span>
            </h1>
          </div>
          <div className="flex gap-2">
            {data.transcript && data.transcript.length > 0 && (
              <button
                onClick={() => setViewingTranscript(true)}
                className="btn-secondary py-2 text-sm"
              >
                View Transcript
              </button>
            )}
            {summary && (
              <button onClick={handleDownloadReport} className="btn-secondary py-2 text-sm">
                Download Report
              </button>
            )}
          </div>
        </div>

        {/* Transcript Modal */}
        {viewingTranscript && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
            <div className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-lg bg-white shadow-xl">
              <div className="flex items-center justify-between border-b px-5 py-3">
                <h2 className="text-lg font-bold">Interview Transcript</h2>
                <button
                  onClick={() => setViewingTranscript(false)}
                  className="text-gray-500 hover:text-gray-700"
                >
                  ✕
                </button>
              </div>
              <div className="flex-1 overflow-y-auto p-5">
                {data.transcript?.map((turn, i) => (
                  <div
                    key={i}
                    className={`mb-4 flex ${turn.role === "assistant" ? "justify-start" : "justify-end"}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-lg px-4 py-2 ${
                        turn.role === "assistant"
                          ? "bg-gray-100 text-gray-800"
                          : "bg-primary-50 text-primary-900 border border-primary-100"
                      }`}
                    >
                      <div className="mb-1 text-xs font-semibold uppercase tracking-wide opacity-50">
                        {turn.role === "assistant" ? "Kiosk" : "Patient"}
                        {turn.input_mode && turn.role === "patient" && ` (${turn.input_mode})`}
                      </div>
                      <p className="whitespace-pre-wrap text-sm">{turn.content}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Alerts */}
        {error && (
          <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        {success && (
          <div className="mb-3 rounded-md border border-govgreen/20 bg-govgreen/5 px-4 py-3 text-sm text-govgreen">
            {success}
          </div>
        )}

        <RedFlagBanner flags={data.red_flags} />

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Summary (2/3 width) */}
          <div className="lg:col-span-2">
            {!summary ? (
              <div className="govt-card p-6 text-center">
                <p className="mb-4 text-gray-600">No summary generated yet for this patient.</p>
                <button onClick={handleGenerate} disabled={generating} className="btn-primary">
                  {generating ? (
                    <Spinner size="sm" className="border-white/40 border-t-white" />
                  ) : (
                    "Generate Summary"
                  )}
                </button>
              </div>
            ) : (
              <div className="govt-card p-6">
                {/* Status bar */}
                <div className="mb-4 flex items-center justify-between border-b border-gray-200 pb-3">
                  <div className="flex items-center gap-3">
                    <span
                      className={`rounded-full px-3 py-1 text-xs font-bold ${
                        summary.status === "confirmed"
                          ? "bg-govgreen/10 text-govgreen"
                          : summary.status === "rejected"
                            ? "bg-red-50 text-red-700"
                            : "bg-saffron/10 text-saffron-dark"
                      }`}
                    >
                      {summary.status.toUpperCase()}
                    </span>
                    <span className="text-xs text-gray-500">
                      Generated by: {summary.generated_by}
                      {summary.physician_edited && " • Physician edited"}
                    </span>
                  </div>
                  {summary.status === "draft" && (
                    <button
                      onClick={() => setEditing(!editing)}
                      className="text-sm font-medium text-primary-600 hover:underline"
                    >
                      {editing ? "Cancel edit" : "Edit"}
                    </button>
                  )}
                </div>

                {/* Disclaimer */}
                <div className="mb-4 rounded-md border border-saffron/30 bg-saffron/5 px-4 py-2 text-sm text-saffron-dark">
                  AI-generated draft — requires physician verification before clinical use (Ayushman
                  Bharat ABDM compliance).
                </div>

                {/* Structured content */}
                {content && (
                  <dl>
                    <SectionField
                      label="Chief Complaint"
                      value={content.chief_complaint}
                      field="chief_complaint"
                      editing={editing}
                      onChange={handleFieldChange}
                    />

                    <h3 className="mb-2 mt-4 text-sm font-bold uppercase tracking-wide text-gray-500">
                      History of Present Illness
                    </h3>
                    {Object.entries(content.hpi || {}).map(([key, val]) => (
                      <SectionField
                        key={key}
                        label={key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                        value={String(val)}
                        field={`hpi.${key}`}
                        editing={editing}
                        onChange={handleFieldChange}
                      />
                    ))}

                    <SectionField
                      label="Past Medical History"
                      value={content.past_medical_history}
                      field="past_medical_history"
                      editing={editing}
                      onChange={handleFieldChange}
                    />
                    <SectionField
                      label="Past Surgical History"
                      value={content.past_surgical_history}
                      field="past_surgical_history"
                      editing={editing}
                      onChange={handleFieldChange}
                    />
                    <SectionField
                      label="Allergies"
                      value={content.allergies}
                      field="allergies"
                      editing={editing}
                      onChange={handleFieldChange}
                    />
                    <SectionField
                      label="Family History"
                      value={content.family_history}
                      field="family_history"
                      editing={editing}
                      onChange={handleFieldChange}
                    />
                    <SectionField
                      label="Personal History"
                      value={content.personal_history}
                      field="personal_history"
                      editing={editing}
                      onChange={handleFieldChange}
                    />
                    <SectionField
                      label="Review of Systems"
                      value={content.review_of_systems}
                      field="review_of_systems"
                      editing={editing}
                      onChange={handleFieldChange}
                    />

                    {content.ayush_assessment && (
                      <>
                        <h3 className="mb-2 mt-4 text-sm font-bold uppercase tracking-wide text-green-700">
                          Ayurvedic Assessment (AYUSH)
                        </h3>
                        <SectionField
                          label="Overall Assessment"
                          value={content.ayush_assessment}
                          field="ayush_assessment"
                          editing={editing}
                          onChange={handleFieldChange}
                        />
                      </>
                    )}
                    {content.ayush_prakriti && (
                      <SectionField
                        label="Prakriti (Constitution)"
                        value={String(content.ayush_prakriti)}
                        field="ayush_prakriti"
                        editing={editing}
                        onChange={handleFieldChange}
                      />
                    )}
                    {content.ayush_vikriti && (
                      <SectionField
                        label="Vikriti (Current Imbalance)"
                        value={String(content.ayush_vikriti)}
                        field="ayush_vikriti"
                        editing={editing}
                        onChange={handleFieldChange}
                      />
                    )}
                    {content.ayush_ashtavidha && (
                      <SectionField
                        label="Ashtavidha Pariksha"
                        value={String(content.ayush_ashtavidha)}
                        field="ayush_ashtavidha"
                        editing={editing}
                        onChange={handleFieldChange}
                      />
                    )}
                    {content.ayush_nidana && (
                      <SectionField
                        label="Nidana (Causation)"
                        value={String(content.ayush_nidana)}
                        field="ayush_nidana"
                        editing={editing}
                        onChange={handleFieldChange}
                      />
                    )}
                    {content.ayush_ahara_vihara && (
                      <SectionField
                        label="Ahara-Vihara (Diet & Lifestyle)"
                        value={String(content.ayush_ahara_vihara)}
                        field="ayush_ahara_vihara"
                        editing={editing}
                        onChange={handleFieldChange}
                      />
                    )}
                    {content.ayush_treatment_direction && (
                      <SectionField
                        label="Treatment Direction (Shamana/Shodhana)"
                        value={String(content.ayush_treatment_direction)}
                        field="ayush_treatment_direction"
                        editing={editing}
                        onChange={handleFieldChange}
                      />
                    )}

                    {content.red_flags_summary && (
                      <div className="mt-3 rounded-md bg-red-50 p-3">
                        <dt className="text-sm font-semibold text-red-700">Red Flags Summary</dt>
                        <dd className="mt-1 text-sm text-red-800">{content.red_flags_summary}</dd>
                      </div>
                    )}

                    {content.clinical_impression && (
                      <div className="mt-3 rounded-md bg-primary-50 p-3">
                        <dt className="text-sm font-semibold text-primary-600">
                          Suggested Impression (AI-generated, unverified)
                        </dt>
                        <dd className="mt-1 text-sm text-primary-800">
                          {content.clinical_impression}
                        </dd>
                      </div>
                    )}
                  </dl>
                )}

                {/* Action buttons */}
                <div className="mt-5 flex flex-wrap gap-2 border-t border-gray-200 pt-4">
                  {editing && (
                    <button onClick={handleSave} className="btn-primary py-2 text-sm">
                      Save Changes
                    </button>
                  )}
                  {summary.status === "draft" && !editing && !rejecting && (
                    <>
                      <button
                        onClick={() => handleDecision("accept")}
                        className="btn-primary py-2 text-sm"
                      >
                        ✓ Accept
                      </button>
                      <button
                        onClick={() => setRejecting(true)}
                        className="rounded-md bg-red-600 px-5 py-2 text-sm font-semibold text-white shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:bg-red-700 hover:shadow-md"
                      >
                        ✗ Reject
                      </button>
                    </>
                  )}

                  {rejecting && (
                    <div className="w-full">
                      <label
                        htmlFor="rejection-reason"
                        className="mb-1 block text-sm font-semibold text-gray-700"
                      >
                        What was wrong with this draft?
                      </label>
                      <textarea
                        id="rejection-reason"
                        value={rejectionReason}
                        onChange={(e) => setRejectionReason(e.target.value)}
                        rows={3}
                        className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-red-500 focus:outline-none focus:ring-2 focus:ring-red-200"
                        placeholder="e.g. the HPI does not match what the patient told me"
                      />
                      <div className="mt-2 flex gap-2">
                        <button
                          onClick={() => handleDecision("reject")}
                          className="rounded-md bg-red-600 px-5 py-2 text-sm font-semibold text-white hover:bg-red-700"
                        >
                          Confirm rejection
                        </button>
                        <button
                          onClick={() => {
                            setRejecting(false);
                            setRejectionReason("");
                          }}
                          className="btn-secondary py-2 text-sm"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                  {summary.status === "confirmed" && (
                    <button onClick={handlePush} className="btn-primary py-2 text-sm">
                      Push to ABDM (stub)
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Sidebar: documents */}
          <div className="lg:col-span-1">
            <DocumentTimeline documents={data.documents} />
          </div>
        </div>
      </div>
    </main>
  );
}
