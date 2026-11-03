import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router-dom";
import { HealthShield } from "./AyushmanIcons";
import { LanguageSwitcher } from "./LanguageSwitcher";

export function Header() {
  const { t } = useTranslation();
  const location = useLocation();

  const isPhysicianPortal =
    location.pathname === "/physician" || location.pathname.startsWith("/dashboard");

  return (
    <>
      {/* Tricolor strip */}
      <div className="tricolor-strip" aria-hidden="true">
        <div className="tricolor-saffron" />
        <div className="tricolor-white" />
        <div className="tricolor-green" />
      </div>

      {/* Main header */}
      <header className="border-b border-gray-200 bg-white px-6 py-3 shadow-sm">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          {/* Left: ABDM logo + Title */}
          <div className="flex items-center gap-3">
            <a href="/" className="flex items-center" aria-label="Back to Home">
              <img
                src={`${import.meta.env.BASE_URL}abdm-logo.png`}
                alt="Ayushman Bharat Digital Mission"
                className="h-12 w-auto"
                style={{ objectFit: "contain" }}
              />
            </a>
            <div>
              <span className="block text-lg font-bold tracking-tight text-primary-600">
                {t("app.name", "MediKiosk")}
              </span>
              <span className="block text-xs font-medium text-ayushman-accent">
                Ayushman Bharat Digital Health Mission
              </span>
            </div>
          </div>

          {/* Right */}
          <div className="flex items-center gap-4">
            <div className="ab-badge hidden lg:inline-flex">
              <HealthShield size={14} className="text-ayushman-accent" />
              AB-PMJAY
            </div>

            {isPhysicianPortal ? (
              <Link
                to="/login"
                className="btn-primary hidden items-center gap-1.5 px-3 py-2 text-xs sm:inline-flex"
              >
                Kiosk Portal
              </Link>
            ) : (
              <Link
                to="/physician"
                className="btn-primary hidden items-center gap-1.5 px-3 py-2 text-xs sm:inline-flex"
              >
                Doctor Portal
              </Link>
            )}
            <div className="hidden text-right md:block">
              <span className="block text-xs font-medium text-gray-600">
                Ministry of Health &amp; Family Welfare
              </span>
              <span className="block text-xs text-gray-400">Government of India</span>
            </div>
            <div className="hidden h-8 w-px bg-gray-200 sm:block" aria-hidden="true" />
            <LanguageSwitcher />
          </div>
        </div>
      </header>

      {/* Ayushman Bharat sub-header bar — text only, no logos */}
      <div
        className="flex items-center justify-center px-4 py-1.5 text-center text-xs font-medium text-white"
        style={{
          background: "linear-gradient(90deg, #002B5B 0%, #0F6DB8 50%, #002B5B 100%)",
        }}
      >
        आयुष्मान भारत — Ayushman Bharat Digital Health Mission
      </div>
    </>
  );
}
