import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      screens: {
        xs: "480px",
      },
      fontFamily: {
        sans: [
          "var(--font-dm-sans)", '"Inter"', "-apple-system", "BlinkMacSystemFont",
          '"Segoe UI"', "Roboto", '"Helvetica Neue"', "Arial",
          "sans-serif",
        ],
        serif: ["var(--font-dm-sans)", '"Inter"', "sans-serif"],
        mono: ["var(--font-dm-mono)", '"JetBrains Mono"', '"SF Mono"', '"Fira Code"', "monospace"],
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
          200: "#F2F4FA",
          300: "#EAEFF7",
          400: "#DDE2EA",
          500: "#C9CDD3",
        },
        clay: {
          50:  "#FAF7FE",
          100: "#F2EBFC",
          200: "#E3D2F8",
          300: "#C9A6F2",
          400: "#A773EC",
          500: "#803CE8",
          600: "#7032CC",
          700: "#57229F",
          800: "#3D1871",
          900: "#260D49",
        },
        moss: {
          400: "#46B98C",
          500: "#238D67",
          600: "#187653",
        },
        amber: {
          400: "#F6AB3B",
          500: "#C97700",
          600: "#985C00",
        },
        rust: {
          400: "#E66979",
          500: "#CF3E54",
          600: "#B4233B",
        },
        ink: {
          400: "#626B76",
          500: "#595D66",
          600: "#303037",
          700: "#010D1B",
          800: "#021123",
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
