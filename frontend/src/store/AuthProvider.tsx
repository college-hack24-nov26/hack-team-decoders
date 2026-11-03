/**
 * AuthProvider — supplies session state to the app.
 *
 * Persisted in sessionStorage so a refresh mid-visit doesn't lose the session,
 * and so it clears automatically when the kiosk browser session ends.
 */

import { ReactNode, useCallback, useMemo, useState } from "react";
import { clearToken, getToken, setToken } from "../api/client";
import { AuthContext, AuthContextType, AuthState, PatientInfo } from "./auth";

const PATIENT_KEY = "medikiosk_patient";

function loadInitialState(): AuthState {
  const token = getToken();
  const raw = sessionStorage.getItem(PATIENT_KEY);

  let patient: PatientInfo | null = null;
  if (raw) {
    try {
      patient = JSON.parse(raw) as PatientInfo;
    } catch {
      patient = null; // ignore corrupt storage
    }
  }

  return { token, patient };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(loadInitialState);

  const login = useCallback((token: string, patient: PatientInfo) => {
    setToken(token);
    sessionStorage.setItem(PATIENT_KEY, JSON.stringify(patient));
    setState({ token, patient });
  }, []);

  const logout = useCallback(() => {
    clearToken();
    sessionStorage.removeItem(PATIENT_KEY);
    setState({ token: null, patient: null });
  }, []);

  const value: AuthContextType = useMemo(
    () => ({ ...state, login, logout }),
    [state, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
