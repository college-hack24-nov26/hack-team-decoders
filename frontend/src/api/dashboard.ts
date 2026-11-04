/**
 * Dashboard + Summaries API client — typed wrappers for Module C endpoints.
 */

import { api } from "./client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface QueuePatient {
  patient_id: string;
  name: string;
  age: number | null;
  gender: string | null;
  chief_complaint: string | null;
  session_status: string;
  has_red_flags: boolean;
  red_flag_count: number;
  summary_status: string | null;
  started_at: string | null;
  doctor_id: string | null;
  doctor_name: string | null;
  department: string | null;
  token_number: number | null;
}

export interface QueueResponse {
  patients: QueuePatient[];
  total: number;
}

export interface DashboardDoctor {
  id: string;
  name: string;
  department: string;
  specialization: string | null;
  available: boolean;
  /** Patients in the consult queue who picked this doctor. */
  waiting: number;
}

export interface HPISection {
  narrative: string;
  site: string;
  onset: string;
  character: string;
  radiation: string;
  associations: string;
  time_course: string;
  exacerbating_relieving: string;
  severity: string;
}

export interface MedicationItem {
  drug: string;
  dose: string;
  frequency: string;
}

export interface InvestigationItem {
  test: string;
  value: string;
  unit: string;
  reference_range: string;
  is_abnormal: boolean;
  date: string;
}

export interface StructuredContent {
  chief_complaint: string;
  hpi: HPISection;
  past_medical_history: string;
  past_surgical_history: string;
  drug_history: MedicationItem[];
  allergies: string;
  family_history: string;
  personal_history: string;
  review_of_systems: string;
  prior_investigations: InvestigationItem[];
  ayush_assessment: string;
  // AYUSH-specific fields — only populated for ayush-mode sessions, so optional.
  ayush_prakriti?: string;
  ayush_vikriti?: string;
  ayush_ashtavidha?: string;
  ayush_nidana?: string;
  ayush_ahara_vihara?: string;
  ayush_treatment_direction?: string;
  clinical_impression: string;
  red_flags_summary: string;
  patient_summary?: string;
  physician_notes?: string;
  sources?: Record<string, string>;
}

export interface SummaryData {
  id: string;
  patient_id: string;
  session_id: string;
  structured_content: StructuredContent;
  generated_by: string;
  physician_edited: boolean;
  status: string;
}

export interface RedFlagItem {
  symptom: string;
  severity: string;
  triggered_at: string | null;
}

export interface DocumentItem {
  id: string;
  doc_type: string;
  document_date: string | null;
  ocr_status: string;
  entities: { entity_type: string; value: Record<string, unknown>; is_abnormal: boolean | null }[];
}

export interface PatientSummaryResponse {
  patient: {
    id: string;
    name: string;
    age: number | null;
    gender: string | null;
    preferred_language: string;
  };
  /**
   * The interview session this view is about. Present even when `summary` is
   * null, which is exactly the case where the client has to call generate.
   */
  session_id: string | null;
  session_status: string | null;
  summary: SummaryData | null;
  documents: DocumentItem[];
  red_flags: RedFlagItem[];
  transcript?: {
    role: "assistant" | "patient";
    content: string;
    input_mode: string;
    created_at: string | null;
  }[];
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

export async function fetchQueue(): Promise<QueueResponse> {
  return api<QueueResponse>("/dashboard/queue");
}

export async function fetchDashboardDoctors(): Promise<DashboardDoctor[]> {
  return api<DashboardDoctor[]>("/dashboard/doctors");
}

export async function fetchPatientSummary(patientId: string): Promise<PatientSummaryResponse> {
  return api<PatientSummaryResponse>(`/dashboard/patients/${patientId}/summary`);
}

export async function generateSummary(sessionId: string): Promise<SummaryData> {
  return api<SummaryData>("/summaries/generate", {
    method: "POST",
    body: { session_id: sessionId },
  });
}

export async function editSummary(
  summaryId: string,
  structuredContent: Partial<StructuredContent>,
): Promise<SummaryData> {
  return api<SummaryData>(`/summaries/${summaryId}`, {
    method: "PATCH",
    body: { structured_content: structuredContent },
  });
}

export async function confirmSummary(
  summaryId: string,
  decision: "accept" | "reject",
  rejectionReason?: string,
): Promise<SummaryData> {
  return api<SummaryData>(`/summaries/${summaryId}/confirm`, {
    method: "POST",
    body: { decision, rejection_reason: rejectionReason },
  });
}

export async function pushToAbdm(summaryId: string): Promise<{ status: string; message: string }> {
  return api(`/summaries/${summaryId}/push-abdm`, { method: "POST" });
}

/**
 * Download the clinical report.
 *
 * Fetched rather than linked, because the route is bearer-authenticated and an
 * <a href> sends no Authorization header. Returns an object URL the caller
 * revokes when done.
 */
export async function fetchReportBlob(patientId: string): Promise<string> {
  const API_ROOT = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
  const token = sessionStorage.getItem("medikiosk_token");

  const res = await fetch(`${API_ROOT}/api/v1/dashboard/patients/${patientId}/report`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`Report download failed (${res.status})`);

  return URL.createObjectURL(await res.blob());
}
