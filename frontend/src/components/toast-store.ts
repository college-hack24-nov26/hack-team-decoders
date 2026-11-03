/**
 * Toast state store — shared between the imperative showToast() API
 * and the ToastContainer component.
 */

export type ToastType = "success" | "error" | "info";

let addToastFn: ((message: string, type: ToastType) => void) | null = null;

/** Called by ToastContainer to register its add handler. */
export function registerToastHandler(fn: (message: string, type: ToastType) => void) {
  addToastFn = fn;
}

/** Called by ToastContainer on unmount. */
export function unregisterToastHandler() {
  addToastFn = null;
}

/** Imperative API to show a toast from anywhere. */
export function showToast(message: string, type: ToastType = "info") {
  if (addToastFn) {
    addToastFn(message, type);
  }
}
