type SpinnerProps = {
  className?: string;
  size?: "sm" | "md";
};

/** A quiet loading indicator used in place of transient loading copy. */
export function Spinner({ className = "", size = "md" }: SpinnerProps) {
  const dimensions = size === "sm" ? "h-5 w-5" : "h-8 w-8";

  return (
    <span
      className={`inline-block animate-spin rounded-full border-2 border-primary-200 border-t-primary-600 ${dimensions} ${className}`}
      role="status"
      aria-label="Loading"
    />
  );
}

/** Skeleton loader — shimmer bars for loading states. */
export function SkeletonBlock({
  lines = 3,
  className = "",
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={`space-y-3 ${className}`} role="status" aria-label="Loading content">
      <div className="skeleton-heading" />
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className={i === lines - 1 ? "skeleton-text-sm" : "skeleton-text"} />
      ))}
    </div>
  );
}

/** Full card skeleton. */
export function SkeletonCard() {
  return (
    <div className="govt-card space-y-3" role="status" aria-label="Loading">
      <div className="skeleton-heading" />
      <div className="skeleton-text" />
      <div className="skeleton-text" />
      <div className="skeleton-text-sm" />
      <div className="skeleton-button mt-4" />
    </div>
  );
}
