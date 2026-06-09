import type { Config } from "tailwindcss";

// Avenue MDP design tokens
const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Avenue red brand palette
        brand: {
          DEFAULT: "#E01E26",
          foreground: "#FFFFFF",
          50: "#FEECEC",
          100: "#FCD0D2",
          200: "#F8A6A9",
          300: "#F27A7F",
          400: "#EC4A52",
          500: "#E01E26",
          600: "#BE1820",
          700: "#8F1218",
        },
        // Neutral palette
        neutral: {
          DEFAULT: "#A7A9AC",
          50: "#F5F5F6",
          100: "#E9EAEB",
          200: "#D3D4D6",
          300: "#BCBEC1",
          400: "#A7A9AC",
          500: "#898B8E",
          600: "#6B6D70",
          700: "#4D4F51",
          800: "#2F3032",
          900: "#161718",
        },
        // Status colors
        success: "#16A34A",
        warning: "#D97706",
        danger: "#DC2626",
        info: "#2563EB",
        // shadcn-style aliases — background/foreground lấy từ CSS var (globals.css)
        // để bg-background = #FAF4F4 (page bg), không bị literal trắng ghi đè.
        background: "var(--background)",
        foreground: "var(--foreground)",
        muted: "#6B6D70",
        border: "#E9EAEB",
        ring: "#E01E26",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
      },
      borderRadius: {
        // card/modal: lg ; input/button: md ; badge: sm (theo context/04)
        lg: "0.625rem", // 10px
        md: "0.375rem", // 6px
        sm: "0.25rem", // 4px
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(22 23 24 / 0.04), 0 1px 3px 0 rgb(22 23 24 / 0.06)",
      },
    },
  },
  plugins: [],
};
export default config;
