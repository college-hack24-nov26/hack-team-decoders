/**
 * Auth state contract.
 *
 * Deliberately holds only the session token and patient identity. Consent is
 * NOT tracked here: a client-side "hasConsent" flag would be trivially
 * forgeable, so consent status is always read from the backend
 * (GET /consent/current) and enforced there too.
 */

import { createContext, useContext } from "react";

export interface PatientInfo {
  id: string;
  name: string;
  language: string;
}

export interface AuthState {
  token: string | null;
  patient: PatientInfo | null;
}

export interface AuthActions {
  login: (token: string, patient: PatientInfo) => void;
  logout: () => void;
}

export type AuthContextType = AuthState & AuthActions;

export const AuthContext = createContext<AuthContextType | null>(null);

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
