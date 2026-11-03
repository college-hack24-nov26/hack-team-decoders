/**
 * Ayushman Bharat Digital Mission logo — SVG recreation.
 *
 * Yoga figure (saffron) with 5 green leaves and radiating signal arcs.
 * Matches the official ABDM visual identity.
 */

type IconProps = {
  className?: string;
  size?: number;
};

/**
 * ABDM Logo — yoga figure + 5 leaves + signal arcs.
 */
export function AbdmLogo({ className = "", size = 48 }: IconProps) {
  return (
    <svg
      viewBox="0 0 240 200"
      width={size}
      height={(size / 240) * 200}
      className={className}
      fill="none"
      aria-hidden="true"
    >
      {/* === Signal arcs (dark gray, radiating outward) === */}
      {/* Inner arc */}
      <path
        d="M68 100 A52 52 0 0 1 172 100"
        stroke="#333"
        strokeWidth="5"
        strokeLinecap="round"
        fill="none"
      />
      {/* Middle arc */}
      <path
        d="M50 108 A70 70 0 0 1 190 108"
        stroke="#333"
        strokeWidth="5"
        strokeLinecap="round"
        fill="none"
      />
      {/* Outer arc */}
      <path
        d="M32 118 A90 90 0 0 1 208 118"
        stroke="#333"
        strokeWidth="5"
        strokeLinecap="round"
        fill="none"
      />

      {/* === 5 leaves === */}
      {/* Center leaf (light green) */}
      <path d="M120 42 Q130 75 120 108 Q110 75 120 42Z" fill="#8BC34A" />
      {/* Inner-left leaf */}
      <path d="M82 54 Q105 78 114 110 Q92 86 68 68Z" fill="#4CAF50" />
      {/* Inner-right leaf */}
      <path d="M158 54 Q135 78 126 110 Q148 86 172 68Z" fill="#4CAF50" />
      {/* Outer-left leaf (darkest) */}
      <path d="M54 78 Q84 92 112 112 Q76 100 46 92Z" fill="#1B5E20" />
      {/* Outer-right leaf (darkest) */}
      <path d="M186 78 Q156 92 128 112 Q164 100 194 92Z" fill="#1B5E20" />

      {/* === Yoga figure (saffron/orange) === */}
      {/* Head */}
      <circle cx="120" cy="120" r="10" fill="#E65100" />
      {/* Body — triangle */}
      <path d="M120 130 L106 158 L134 158Z" fill="#E65100" />
      {/* Crossed legs */}
      <ellipse cx="104" cy="166" rx="14" ry="9" fill="#E65100" />
      <ellipse cx="136" cy="166" rx="14" ry="9" fill="#E65100" />
    </svg>
  );
}

/**
 * Health shield with cross — compact, for security badges.
 */
export function HealthShield({ className = "", size = 24 }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 2l8 4v6c0 5.25-3.44 9.15-8 10-4.56-.85-8-4.75-8-10V6l8-4z" />
      <path d="M12 8v8M8 12h8" />
    </svg>
  );
}

/**
 * Decorative corner motif — tricolor arcs for banner corners.
 */
export function CornerMotif({ className = "", size = 80 }: IconProps) {
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={className}
      fill="none"
      aria-hidden="true"
    >
      <path d="M0 0 Q50 4 76 24 Q96 44 100 100" stroke="#FF9933" strokeWidth="1.5" opacity="0.2" />
      <path d="M0 0 Q40 8 60 28 Q80 48 88 100" stroke="#002B5B" strokeWidth="1.2" opacity="0.15" />
      <path d="M0 0 Q28 10 44 30 Q60 50 68 100" stroke="#138808" strokeWidth="1" opacity="0.12" />
      <circle cx="8" cy="8" r="5" fill="#FF9933" opacity="0.1" />
      <circle cx="18" cy="18" r="3" fill="#002B5B" opacity="0.06" />
    </svg>
  );
}
