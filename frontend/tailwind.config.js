/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Ayushman Bharat — official palette inspired by AB-PMJAY scheme
        primary: {
          50: "#E3F0FC",
          100: "#B8D9F8",
          200: "#89BFF3",
          300: "#5AA5EE",
          400: "#3691EA",
          500: "#0F6DB8",
          600: "#002B5B", // Deep Ayushman Bharat navy — primary action color
          700: "#002249",
          800: "#001937",
          900: "#001025",
        },
        saffron: {
          DEFAULT: "#FF9933",
          light: "#FFB366",
          dark: "#E68A2E",
        },
        govgreen: {
          DEFAULT: "#2E7D32",
          light: "#4CAF50",
          dark: "#1B5E20",
        },
        teal: {
          DEFAULT: "#00838F",
          light: "#26C6DA",
          dark: "#006064",
        },
        ayushman: {
          blue: "#002B5B",
          accent: "#0F6DB8",
          gold: "#D4A843",
          lightblue: "#E8F4FD",
          orange: "#E87722",
        },
        surface: {
          DEFAULT: "#F8FAFC",
          card: "#FFFFFF",
          section: "#F0F7FF",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Oxygen",
          "Ubuntu",
          "Cantarell",
          "Fira Sans",
          "Droid Sans",
          "Helvetica Neue",
          "sans-serif",
        ],
      },
      fontSize: {
        kiosk: ["1.5rem", { lineHeight: "2rem" }],
        base: ["1rem", { lineHeight: "1.5rem" }], // 16px
      },
      minHeight: {
        touch: "3rem",
      },
      minWidth: {
        touch: "3rem",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in-right": {
          "0%": { opacity: "0", transform: "translateX(100%)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        "slide-out-right": {
          "0%": { opacity: "1", transform: "translateX(0)" },
          "100%": { opacity: "0", transform: "translateX(100%)" },
        },
        "mic-pulse": {
          "0%": { transform: "scale(1)", opacity: "0.8" },
          "100%": { transform: "scale(2.5)", opacity: "0" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "progress-fill": {
          "0%": { strokeDashoffset: "283" },
          "100%": { strokeDashoffset: "var(--progress-offset)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.3s ease-out",
        "slide-in-right": "slide-in-right 0.3s ease-out",
        "slide-out-right": "slide-out-right 0.3s ease-out",
        "mic-pulse": "mic-pulse 1.5s ease-out infinite",
        shimmer: "shimmer 1.5s infinite linear",
        "progress-fill": "progress-fill 0.8s ease-out forwards",
      },
    },
  },
  plugins: [],
};
