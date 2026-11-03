/**
 * Document upload screen — camera capture + file picker, multi-doc upload.
 */

import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { HealthShield } from "../components/AyushmanIcons";
import { SkeletonCard } from "../components/Spinner";
import { showToast } from "../components/toast-store";

interface UploadedDoc {
  id: string;
  doc_type: string;
  ocr_status: string;
  document_date: string | null;
}

export function DocumentUploadPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [uploads, setUploads] = useState<UploadedDoc[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setError("");
    setUploading(true);

    for (const file of Array.from(files)) {
      try {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("doc_type", "unknown");

        const res = await fetch(
          `${(import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "")}/api/v1/documents`,
          {
            method: "POST",
            headers: {
              Authorization: `Bearer ${sessionStorage.getItem("medikiosk_token")}`,
            },
            body: formData,
          },
        );

        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: "Upload failed" }));
          throw new Error(err.detail || `HTTP ${res.status}`);
        }

        const doc: UploadedDoc = await res.json();
        setUploads((prev) => [...prev, doc]);
        showToast("Document uploaded successfully", "success");
      } catch (e) {
        const msg = e instanceof Error ? e.message : t("common.error");
        setError(msg);
        showToast(msg, "error");
      }
    }
    setUploading(false);
  };

  return (
    <main className="flex min-h-[calc(100vh-10rem)] flex-col items-center px-6 py-8">
      <div className="w-full max-w-lg">
        <h1 className="mb-2 text-center text-2xl font-bold text-primary-600">
          {t("documents.upload.title")}
        </h1>
        <p className="mb-4 text-center text-gray-600">{t("documents.upload.subtitle")}</p>

        {/* Ayurvedic illustration + AB info badge */}
        <div className="mb-4 flex items-center justify-center gap-3 rounded-lg border border-primary-100 bg-primary-50/50 px-4 py-2">
          <HealthShield size={18} className="shrink-0 text-primary-600" />
          <p className="text-xs text-primary-800">
            Your documents are encrypted &amp; stored securely under ABDM guidelines
          </p>
        </div>

        {error && (
          <div
            className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
            role="alert"
          >
            {error}
          </div>
        )}

        {/* Upload area */}
        <div
          className="govt-card mb-6 border-2 border-dashed border-primary-200 p-5"
          style={{ backgroundColor: "rgba(232, 244, 253, 0.3)" }}
        >
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => cameraInputRef.current?.click()}
              disabled={uploading}
              className="flex min-h-28 flex-col items-center justify-center gap-2 rounded-lg p-4 text-white shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-primary-200 disabled:opacity-50"
              style={{
                background: "linear-gradient(135deg, #002B5B 0%, #0F4C81 100%)",
              }}
            >
              <svg
                className="h-8 w-8"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"
                />
              </svg>
              <span className="text-sm font-semibold">{t("documents.upload.camera")}</span>
            </button>

            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="flex min-h-28 flex-col items-center justify-center gap-2 rounded-md border border-gray-300 bg-white p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary-600 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-primary-200 disabled:opacity-50"
            >
              <svg
                className="h-8 w-8 text-primary-600"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                />
              </svg>
              <span className="text-sm font-medium text-gray-700">
                {t("documents.upload.file")}
              </span>
            </button>
          </div>
        </div>

        {/* Hidden inputs */}
        <input
          ref={cameraInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/tiff,application/pdf"
          multiple
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />

        {uploading && (
          <div className="mb-4">
            <SkeletonCard />
          </div>
        )}

        {/* Uploaded list */}
        {uploads.length > 0 && (
          <div className="mb-6 space-y-2">
            <h2 className="text-sm font-semibold text-gray-700">
              {t("documents.upload.uploaded")}
            </h2>
            {uploads.map((doc) => (
              <div key={doc.id} className="govt-card flex items-center justify-between p-4">
                <div>
                  <span className="text-sm font-medium text-gray-900">{doc.doc_type}</span>
                  {doc.document_date && (
                    <span className="ml-2 text-xs text-gray-500">{doc.document_date}</span>
                  )}
                </div>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    doc.ocr_status === "done"
                      ? "bg-govgreen/10 text-govgreen"
                      : "bg-red-50 text-red-600"
                  }`}
                >
                  {doc.ocr_status}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Navigation */}
        <div className="flex gap-3">
          {uploads.length > 0 && (
            <button
              onClick={() => navigate("/documents/timeline")}
              className="btn-secondary flex-1 py-3 text-base"
            >
              {t("documents.upload.viewTimeline")}
            </button>
          )}
          <button
            onClick={() => navigate("/interview")}
            className="btn-primary flex-1 py-3 text-base"
          >
            {uploads.length > 0
              ? t("documents.upload.continueInterview", "Continue to Interview")
              : t("documents.upload.skip", "Skip for now")}
          </button>
        </div>
      </div>
    </main>
  );
}
