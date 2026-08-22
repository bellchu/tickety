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
          '"DM Sans"', '"Inter"', "-apple-system", "BlinkMacSystemFont",
          '"Segoe UI"', "Roboto", '"Helvetica Neue"', "Arial",
          "sans-serif",
        ],
        serif: ['"DM Sans"', '"Arial"', "sans-serif"],
        mono: ['"DM Mono"', '"JetBrains Mono"', '"SF Mono"', '"Fira Code"', "monospace"],
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
          50:  "#FFFFFF",
          100: "#F8FAFE",
          200: "#F2F5F9",
          300: "#E8EDF3",
          400: "#D9DEE6",
          500: "#C5CCD6",
        },
        clay: {
          50:  "#F7F3FE",
          100: "#F2EAFC",
          200: "#E2D1FA",
          300: "#C9AAF3",
          400: "#A974EC",
          500: "#803CE8",
          600: "#6B2FD0",
          700: "#5623AA",
          800: "#411B82",
          900: "#2C1459",
        },
        moss: {
          400: "#48DCC8",
          500: "#03CCB5",
          600: "#008F7E",
        },
        amber: {
          400: "#F9C76A",
          500: "#F6AB3B",
          600: "#B96C0C",
        },
        rust: {
          400: "#FF969E",
          500: "#D95763",
          600: "#C23F4B",
        },
        ink: {
          300: "#B7BEC8",
          400: "#979DA5",
          500: "#59616B",
          600: "#303037",
          700: "#010D1B",
          800: "#010D1B",
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
