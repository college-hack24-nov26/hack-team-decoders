/**
 * Admin API — super-admin views and provisioning. All calls carry the physician
 * bearer token (role must be "admin", enforced server-side).
 */

import { api } from "./client";

/** Admin calls handle their own 401 (→ /admin/login), so they opt out of the
 *  global patient-login redirect. */
const ADMIN_OPTS = { skipUnauthorizedRedirect: true } as const;

export interface AdminOverview {
  patients: number;
  visits_total: number;
  visits_today: number;
  interviews: number;
  summaries_total: number;
  summaries_confirmed: number;
  red_flags: number;
  doctors: number;
  physicians: number;
}

export interface AdminPatient {
  id: string;
  name: string;
  age: number | null;
  gender: string | null;
  phone: string | null;
  abha_id: string | null;
  preferred_language: string;
  visit_count: number;
  created_at: string | null;
}

export interface PhysicianItem {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string | null;
}

export interface AdminDoctor {
  id: string;
  name: string;
  department: string;
  specialization: string | null;
  available: boolean;
  queue_count: number;
  photo_url: string | null;
}

export const adminApi = {
  overview: () => api<AdminOverview>("/admin/overview", { ...ADMIN_OPTS }),
  patients: () => api<AdminPatient[]>("/admin/patients", { ...ADMIN_OPTS }),
  physicians: () => api<PhysicianItem[]>("/admin/physicians", { ...ADMIN_OPTS }),
  createPhysician: (body: { email: string; password: string; full_name: string; role: string }) =>
    api<PhysicianItem>("/admin/physicians", { method: "POST", body, ...ADMIN_OPTS }),
  createDoctor: (body: { name: string; department: string; specialization?: string | null }) =>
    api<AdminDoctor>("/admin/doctors", { method: "POST", body, ...ADMIN_OPTS }),
};
