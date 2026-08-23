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
        semantic: {
          primary: "var(--color-primary)",
          "primary-hover": "var(--color-primary-hover)",
          success: "var(--color-success)",
          warning: "var(--color-warning)",
          danger: "var(--color-danger)",
          info: "var(--color-info)",
        },
        linen: {
          50:  "#FFFEFB",
          100: "#FAF8F4",
          200: "#F7F4EE",
          300: "#F0ECE4",
          400: "#E8E1D6",
          500: "#D9D2C7",
        },
        clay: {
          50:  "#F0F1FF",
          100: "#E1E4FF",
          200: "#C8CEFF",
          300: "#A3AFFF",
          400: "#7486FF",
          500: "#3D5AFE",
          600: "#3047D8",
          700: "#2638AF",
          800: "#202F86",
          900: "#18245F",
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
          400: "#9B9084",
          500: "#5C5347",
          600: "#2A2520",
          700: "#1C1814",
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
