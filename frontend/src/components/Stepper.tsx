import { useLocation } from "react-router-dom";

interface Step {
  label: string;
  paths: string[];
}

const STEPS: Step[] = [
  { label: "Login", paths: ["/", "/login", "/login/new", "/login/returning"] },
  { label: "Language", paths: ["/"] },
  { label: "Consent", paths: ["/consent"] },
  { label: "Documents", paths: ["/documents/upload", "/documents/timeline"] },
  { label: "Interview", paths: ["/interview"] },
  { label: "Summary", paths: ["/patient-summary"] },
  { label: "Done", paths: ["/visit/done"] },
];

/** Map actual progression through the flow based on path ordering. */
function getProgressIndex(pathname: string): number {
  if (pathname === "/" || pathname.startsWith("/login")) return 0;
  if (pathname === "/select-doctor") return 1;
  if (pathname === "/consent") return 2;
  if (pathname.startsWith("/documents")) return 3;
  if (pathname === "/interview") return 4;
  if (pathname === "/patient-summary") return 5;
  if (pathname === "/visit/done") return 6;
  return 0;
}

export function Stepper() {
  const { pathname } = useLocation();

  // Don't show stepper on physician/dashboard routes
  if (pathname.startsWith("/physician") || pathname.startsWith("/dashboard")) {
    return null;
  }

  const activeIndex = getProgressIndex(pathname);

  return (
    <nav
      className="border-b border-primary-100/30 bg-gradient-to-r from-primary-50/30 via-white to-primary-50/30 px-4 py-2"
      aria-label="Patient flow progress"
    >
      <div className="mx-auto flex max-w-4xl items-center justify-between overflow-x-auto">
        {STEPS.map((step, index) => {
          const isCompleted = index < activeIndex;
          const isCurrent = index === activeIndex;

          return (
            <div key={step.label} className="flex items-center">
              {/* Step indicator */}
              <div className="flex flex-col items-center">
                <div
                  className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold transition-colors ${
                    isCompleted
                      ? "bg-govgreen text-white"
                      : isCurrent
                        ? "bg-primary-600 text-white"
                        : "border border-gray-300 bg-white text-gray-400"
                  }`}
                >
                  {isCompleted ? (
                    <svg
                      className="h-3.5 w-3.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={3}
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  ) : (
                    <span>{index + 1}</span>
                  )}
                </div>
                <span
                  className={`mt-1 text-xs whitespace-nowrap ${
                    isCurrent
                      ? "font-semibold text-primary-600"
                      : isCompleted
                        ? "text-govgreen font-medium"
                        : "text-gray-400"
                  }`}
                >
                  {step.label}
                </span>
              </div>

              {/* Connector line */}
              {index < STEPS.length - 1 && (
                <div
                  className={`mx-1 h-0.5 w-4 sm:w-8 ${
                    index < activeIndex ? "bg-govgreen" : "bg-gray-200"
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
    </nav>
  );
}
