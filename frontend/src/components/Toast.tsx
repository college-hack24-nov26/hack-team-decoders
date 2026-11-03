/**
 * Lightweight toast notification system — no external libraries.
 *
 * Usage:
 *   import { showToast } from "../components/toast-store";
 *   showToast("File uploaded successfully", "success");
 *   showToast("Upload failed", "error");
 */

import { useEffect, useState } from "react";
import { type ToastType, registerToastHandler, unregisterToastHandler } from "./toast-store";

interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
  exiting: boolean;
}

let toastIdCounter = 0;

const TYPE_STYLES: Record<ToastType, string> = {
  success: "border-govgreen bg-white text-gray-900",
  error: "border-red-500 bg-white text-gray-900",
  info: "border-primary-600 bg-white text-gray-900",
};

const TYPE_ICONS: Record<ToastType, string> = {
  success: "✓",
  error: "✗",
  info: "ℹ",
};

const ICON_STYLES: Record<ToastType, string> = {
  success: "bg-govgreen text-white",
  error: "bg-red-500 text-white",
  info: "bg-primary-600 text-white",
};

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    registerToastHandler((message: string, type: ToastType) => {
      const id = ++toastIdCounter;
      setToasts((prev) => [...prev, { id, message, type, exiting: false }]);

      // Start exit animation after 2.5s
      setTimeout(() => {
        setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
      }, 2500);

      // Remove from DOM after exit animation
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 3000);
    });

    return () => {
      unregisterToastHandler();
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed right-4 top-16 z-50 flex flex-col gap-2"
      aria-live="polite"
      aria-atomic="true"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`flex items-center gap-3 rounded-md border-l-4 px-4 py-3 shadow-sm transition-all duration-300 ${
            TYPE_STYLES[toast.type]
          } ${toast.exiting ? "animate-slide-out-right" : "animate-slide-in-right"}`}
          role="alert"
        >
          <span
            className={`flex h-5 w-5 items-center justify-center rounded-full text-xs font-bold ${
              ICON_STYLES[toast.type]
            }`}
          >
            {TYPE_ICONS[toast.type]}
          </span>
          <span className="text-sm font-medium">{toast.message}</span>
        </div>
      ))}
    </div>
  );
}
