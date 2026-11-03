/**
 * Document timeline — chronological view of uploaded documents with entities.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { SkeletonCard } from "../components/Spinner";
import { useAuth } from "../store/auth";

interface Entity {
  id: string;
  entity_type: string;
  value: Record<string, unknown>;
  is_abnormal: boolean | null;
}

interface DocumentDetail {
  id: string;
  doc_type: string;
  document_date: string | null;
  uploaded_at: string;
  ocr_status: string;
  entities: Entity[];
}

interface TimelineItem {
  id: string;
  doc_type: string;
  document_date: string | null;
  uploaded_at: string;
  ocr_status: string;
  entity_count: number;
  abnormal_count: number;
}

interface TimelineResponse {
  patient_id: string;
  documents: TimelineItem[];
}

export function DocumentTimelinePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { patient } = useAuth();

  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!patient) return;
    api<TimelineResponse>(`/patients/${patient.id}/documents/timeline`)
      .then((res) => setTimeline(res.documents))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [patient]);

  const toggleExpand = async (docId: string) => {
    if (expanded === docId) {
      setExpanded(null);
      setDetail(null);
      return;
    }
    setExpanded(docId);
    try {
      const doc = await api<DocumentDetail>(`/documents/${docId}`);
      setDetail(doc);
    } catch {
      setDetail(null);
    }
  };

  const entityLabel = (e: Entity): string => {
    const v = e.value;
    switch (e.entity_type) {
      case "medication":
        return `${v.drug} ${v.dose} ${v.frequency || ""}`.trim();
      case "investigation_value":
        return `${v.test}: ${v.value} ${v.unit}`;
      case "diagnosis":
        return String(v.diagnosis || "");
      case "procedure":
        return String(v.procedure || "");
      default:
        return JSON.stringify(v);
    }
  };

  if (loading) {
    return (
      <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center px-6 py-8">
        <div className="w-full max-w-lg space-y-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center px-6 py-8">
      <div className="w-full max-w-lg">
        <h1 className="mb-2 text-center text-2xl font-bold text-primary-600">
          {t("documents.timeline.title")}
        </h1>
        <p className="mb-6 text-center text-gray-600">{t("documents.timeline.subtitle")}</p>

        {timeline.length === 0 && (
          <p className="text-center text-gray-500">{t("documents.timeline.empty")}</p>
        )}

        <div className="space-y-3">
          {timeline.map((item) => (
            <div key={item.id} className="govt-card p-4">
              <button
                onClick={() => toggleExpand(item.id)}
                className="flex w-full items-center justify-between text-left focus:outline-none"
              >
                <div>
                  <span className="text-sm font-semibold capitalize text-gray-900">
                    {item.doc_type.replace("_", " ")}
                  </span>
                  <span className="ml-2 text-xs text-gray-500">
                    {item.document_date || item.uploaded_at.slice(0, 10)}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {item.abnormal_count > 0 && (
                    <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-600">
                      {item.abnormal_count} {t("documents.timeline.abnormal")}
                    </span>
                  )}
                  <span className="text-xs text-gray-400">
                    {item.entity_count} {t("documents.timeline.entities")}
                  </span>
                  <svg
                    className={`h-4 w-4 text-gray-400 transition-transform duration-200 ${expanded === item.id ? "rotate-180" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    aria-hidden="true"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M19 9l-7 7-7-7"
                    />
                  </svg>
                </div>
              </button>

              {expanded === item.id && detail && detail.id === item.id && (
                <div className="mt-3 border-t border-gray-100 pt-3">
                  {detail.entities.length === 0 ? (
                    <p className="text-sm text-gray-500">{t("documents.timeline.noEntities")}</p>
                  ) : (
                    <ul className="space-y-2">
                      {detail.entities.map((e) => (
                        <li key={e.id} className="flex items-start gap-2 text-sm">
                          <span
                            className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${
                              e.is_abnormal === true
                                ? "bg-red-500"
                                : e.is_abnormal === false
                                  ? "bg-govgreen"
                                  : "bg-gray-300"
                            }`}
                            aria-hidden="true"
                          />
                          <span className="text-gray-800">
                            <span className="font-medium capitalize">
                              {e.entity_type.replace("_", " ")}:
                            </span>{" "}
                            {entityLabel(e)}
                          </span>
                          {e.is_abnormal === true && (
                            <span className="ml-auto shrink-0 rounded bg-red-50 px-1.5 py-0.5 text-xs font-medium text-red-600">
                              {t("documents.timeline.flagged")}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="mt-6 flex gap-3">
          <button
            onClick={() => navigate("/documents/upload")}
            className="btn-secondary flex-1 py-3"
          >
            {t("documents.timeline.uploadMore")}
          </button>
          <button onClick={() => navigate("/interview")} className="btn-primary flex-1 py-3">
            {t("documents.timeline.continueToInterview", "Continue to Interview")}
          </button>
        </div>
      </div>
    </main>
  );
}
