import { Link } from "react-router-dom";

export function Footer() {
  const year = new Date().getFullYear();

  return (
    <>
      <div className="ab-divider mx-auto mt-8 max-w-5xl" aria-hidden="true" />

      <footer className="border-t border-gray-200 bg-white px-6 py-4">
        <div className="mx-auto max-w-5xl">
          {/* Branding row */}
          <div className="mb-3 flex flex-col items-center gap-2 sm:flex-row sm:justify-center sm:gap-4">
            <div className="flex items-center gap-2">
              <img src="/kiosk/abdm-logo.png" alt="ABDM" className="h-8 w-auto" />
              <div className="text-center sm:text-left">
                <span className="block text-xs font-bold text-primary-600">
                  आयुष्मान भारत डिजिटल हेल्थ मिशन
                </span>
                <span className="block text-xs text-gray-500">
                  Ayushman Bharat Digital Health Mission
                </span>
              </div>
            </div>
            <div className="hidden h-6 w-px bg-gray-200 sm:block" aria-hidden="true" />
            <div className="text-center sm:text-left">
              <span className="block text-xs font-medium text-gray-600">
                National Health Authority
              </span>
              <span className="block text-xs text-gray-400">Government of India</span>
            </div>
          </div>

          <div className="flex flex-col items-center gap-2 text-center text-xs text-gray-500 sm:flex-row sm:justify-between sm:text-left">
            <p>
              © {year} MediKiosk — Ayushman Bharat Digital Health Mission. Content owned &amp;
              maintained by National Health Authority, Government of India.
            </p>
            <div className="flex gap-4">
              <Link to="/physician" className="font-medium text-primary-600 hover:underline">
                Doctor / Staff Login
              </Link>
              <Link to="/admin/login" className="font-medium text-primary-600 hover:underline">
                Admin
              </Link>
              <span>Terms of Use</span>
              <span>Privacy Policy</span>
              <span>Accessibility</span>
              <span>Help</span>
            </div>
          </div>
          <p className="mt-2 text-center text-xs text-gray-400">
            Designed, developed &amp; hosted by National Informatics Centre (NIC) · Powered by
            AB-PMJAY
          </p>
        </div>
      </footer>
    </>
  );
}
