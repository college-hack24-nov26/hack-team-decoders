/**
 * App — routing shell for MediKiosk.
 *
 *   /          language selection
 *   /login     ABHA lookup, Aadhaar fallback, or new-patient registration
 *   /consent   audio-guided consent capture      (requires a session)
 *   /interview dual-mode voice+touch interview   (requires VALID CONSENT)
 *
 * The /interview guard asks the backend (GET /consent/current) rather than
 * trusting client state, so editing sessionStorage cannot get a patient past
 * the consent step.
 */

import { useEffect, useState } from "react";
import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { api, setUnauthorizedHandler } from "./api/client";
import { Footer } from "./components/Footer";
import { Header } from "./components/Header";
import { Spinner } from "./components/Spinner";
import { Stepper } from "./components/Stepper";
import { ToastContainer } from "./components/Toast";
import { AdminDashboardPage } from "./pages/AdminDashboardPage";
import { AdminLoginPage } from "./pages/AdminLoginPage";
import { ConsentPage } from "./pages/ConsentPage";
import { DoctorSelectPage } from "./pages/DoctorSelectPage";
import { DocumentTimelinePage } from "./pages/DocumentTimelinePage";
import { DocumentUploadPage } from "./pages/DocumentUploadPage";
import { InterviewPage } from "./pages/InterviewPage";
import { LanguageSelectPage } from "./pages/LanguageSelectPage";
import { LoginPage } from "./pages/LoginPage";
import { PatientTypePage } from "./pages/PatientTypePage";
import { PhysicianLoginPage } from "./pages/PhysicianLoginPage";
import { ReturningLoginPage } from "./pages/ReturningLoginPage";
import { DashboardQueuePage } from "./pages/DashboardQueuePage";
import { PatientSummaryPage } from "./pages/PatientSummaryPage";
import { SummaryReviewPage } from "./pages/SummaryReviewPage";
import { VisitDonePage } from "./pages/VisitDonePage";
import { useAuth } from "./store/auth";
import { AuthProvider } from "./store/AuthProvider";

/** Page wrapper with fade-in transition on route change. */
function PageTransition({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const [displayKey, setDisplayKey] = useState(location.key);

  useEffect(() => {
    setDisplayKey(location.key);
  }, [location.key]);

  return (
    <div key={displayKey} className="page-enter flex-1">
      {children}
    </div>
  );
}

function Layout() {
  return (
    <div className="flex min-h-screen flex-col bg-surface ab-gradient-bg">
      <Header />
      <Stepper />
      <PageTransition>
        <Outlet />
      </PageTransition>
      <Footer />
      <ToastContainer />
      {/* Floating "Back to Home" button — links outside the SPA to the landing page */}
      <a
        href="/"
        className="fixed bottom-6 left-6 z-50 flex items-center gap-2 rounded-full border border-primary-100 bg-white px-4 py-2.5 text-sm font-semibold text-primary-600 shadow-lg transition hover:bg-primary-50 hover:shadow-xl"
        title="Back to Home"
        style={{ borderColor: "rgba(0, 43, 91, 0.15)" }}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="h-4 w-4"
        >
          <path d="M19 12H5M12 19l-7-7 7-7" />
        </svg>
        Home
      </a>
    </div>
  );
}

/** Requires a session token. */
function RequireAuth() {
  const { token } = useAuth();
  return token ? <Outlet /> : <Navigate to="/login" replace />;
}

type ConsentCheck = "checking" | "granted" | "missing" | "unauthenticated";

/** Requires a valid, current consent record — verified with the backend. */
function RequireConsent() {
  const { token } = useAuth();
  const [check, setCheck] = useState<ConsentCheck>("checking");

  useEffect(() => {
    if (!token) {
      setCheck("unauthenticated");
      return;
    }

    let cancelled = false;
    api<{ active: boolean }>("/consent/current")
      .then((res) => {
        if (!cancelled) setCheck(res.active ? "granted" : "missing");
      })
      .catch(() => {
        if (!cancelled) setCheck("unauthenticated");
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  if (check === "checking") {
    return (
      <main
        className="flex min-h-[calc(100vh-10rem)] items-center justify-center px-6 py-8"
        aria-busy="true"
      >
        <Spinner />
      </main>
    );
  }

  if (check === "unauthenticated") return <Navigate to="/login" replace />;
  if (check === "missing") return <Navigate to="/consent" replace />;
  return <Outlet />;
}

/**
 * Sends the patient back to login whenever the backend rejects their token.
 *
 * Lives inside the router so it can navigate. Without it an expired session left
 * the patient stranded on whatever screen they were on, reading a raw backend
 * string ("Invalid or expired token") with every button silently failing.
 */
function UnauthorizedRedirect() {
  const navigate = useNavigate();
  const { logout } = useAuth();

  useEffect(() => {
    setUnauthorizedHandler(() => {
      logout();
      navigate("/login", { replace: true, state: { sessionExpired: true } });
    });
    return () => setUnauthorizedHandler(null);
  }, [navigate, logout]);

  return null;
}

function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<LanguageSelectPage />} />
        {/* Patient type selection, then the two entry paths. /login/new keeps the
            existing ABHA / Aadhaar / register screen; /login/returning is the
            phone-lookup flow. */}
        <Route path="/login" element={<PatientTypePage />} />
        <Route path="/login/new" element={<LoginPage />} />
        <Route path="/login/returning" element={<ReturningLoginPage />} />

        <Route element={<RequireAuth />}>
          <Route path="/select-doctor" element={<DoctorSelectPage />} />
          <Route path="/consent" element={<ConsentPage />} />
        </Route>

        <Route element={<RequireConsent />}>
          <Route path="/documents/upload" element={<DocumentUploadPage />} />
          <Route path="/documents/timeline" element={<DocumentTimelinePage />} />
          <Route path="/interview" element={<InterviewPage />} />
          <Route path="/patient-summary" element={<PatientSummaryPage />} />
          <Route path="/summary" element={<PatientSummaryPage />} />
          <Route path="/visit/done" element={<VisitDonePage />} />
        </Route>

        {/* Physician dashboard — separate auth path */}
        <Route path="/physician" element={<PhysicianLoginPage />} />
        <Route path="/dashboard" element={<DashboardQueuePage />} />
        <Route path="/dashboard/patient/:patientId" element={<SummaryReviewPage />} />

        {/* Super-admin — separate auth path */}
        <Route path="/admin/login" element={<AdminLoginPage />} />
        <Route path="/admin" element={<AdminDashboardPage />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter basename="/kiosk">
      <AuthProvider>
        <UnauthorizedRedirect />
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
