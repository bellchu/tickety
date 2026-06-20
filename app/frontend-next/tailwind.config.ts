import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          '"Geist"', '"Inter"', "-apple-system", "BlinkMacSystemFont",
          '"Segoe UI"', "Roboto", '"Helvetica Neue"', "Arial",
          "sans-serif",
        ],
        serif: ['"Newsreader"', '"Georgia"', "serif"],
        mono: ['"Geist Mono"', '"JetBrains Mono"', '"SF Mono"', '"Fira Code"', "monospace"],
      },
      colors: {
        linen: {
          50:  "#FBF8F3",
          100: "#F7F2EA",
          200: "#F3EBE2",
          300: "#EAE3D9",
          400: "#E0D8CE",
          500: "#C5BEB6",
        },
        clay: {
          50:  "#FAF3EE",
          100: "#F0DDD0",
          200: "#E2C4AE",
          300: "#D4A884",
          400: "#C77B4F",
          500: "#B5704A",
          600: "#9A5A36",
          700: "#7A4628",
          800: "#5C3520",
          900: "#3D2316",
        },
        moss: {
          400: "#8AA874",
          500: "#6B8E5A",
          600: "#557048",
        },
        amber: {
          400: "#E2B85C",
          500: "#D4A24C",
          600: "#B88638",
        },
        rust: {
          400: "#D67264",
          500: "#C44A3F",
          600: "#A33B31",
        },
        ink: {
          400: "#8A8276",
          500: "#5C554B",
          600: "#3D372F",
          700: "#2B2620",
          800: "#1C1814",
        },
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "slide-up": {
          "0%": { opacity: "0", transform: "translateY(20px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.3s ease-out",
        "slide-up": "slide-up 0.4s ease-out",
        shimmer: "shimmer 1.5s infinite",
      },
    },
  },
  plugins: [],
};
export default config;