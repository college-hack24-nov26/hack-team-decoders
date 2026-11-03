/**
 * Clinic API — returning-patient login, doctor listing, and visit booking (F2).
 */

import { api } from "./client";

export interface PastVisit {
  visit_id: string;
  date: string;
  doctor_name: string | null;
  department: string | null;
  chief_complaint: string | null;
  status: string;
}

export interface ReturningLoginResponse {
  found: boolean;
  patient_id: string | null;
  token: string | null;
  name: string | null;
  preferred_language: string | null;
  visits: PastVisit[];
}

export interface DoctorItem {
  id: string;
  name: string;
  department: string;
  specialization: string | null;
  available: boolean;
  queue_count: number;
  photo_url: string | null;
}

export interface VisitResponse {
  id: string;
  patient_id: string;
  doctor_id: string | null;
  doctor_name: string | null;
  department: string | null;
  status: string;
  token_number: number;
  chief_complaint: string | null;
  interview_session_id: string | null;
  summary_id: string | null;
  created_at: string | null;
  completed_at: string | null;
}

/** Phone-based lookup for a returning patient. `skipAuth`: no token yet. */
export async function returningLogin(
  phone: string,
  name?: string,
): Promise<ReturningLoginResponse> {
  return api<ReturningLoginResponse>("/auth/login/returning", {
    method: "POST",
    body: name ? { phone, name } : { phone },
    skipAuth: true,
  });
}

export async function listDoctors(department?: string): Promise<DoctorItem[]> {
  const query = department ? `?department=${encodeURIComponent(department)}` : "";
  const res = await api<{ doctors: DoctorItem[] }>(`/doctors${query}`);
  return res.doctors;
}

export async function createVisit(input: {
  doctorId?: string;
  department?: string;
  chiefComplaint?: string;
}): Promise<VisitResponse> {
  return api<VisitResponse>("/visits", {
    method: "POST",
    body: {
      doctor_id: input.doctorId ?? null,
      department: input.department ?? null,
      chief_complaint: input.chiefComplaint ?? null,
    },
  });
}
