/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 暗色放映厅底色系
        ink: {
          950: "#0e0e0f",
          900: "#131314",
          850: "#18181a",
          800: "#1c1c1e",
          750: "#222225",
          700: "#2a2a2e",
          600: "#3a3a3e",
          500: "#4a4a4e",
          400: "#6a6a6e",
          300: "#8a8a8e",
          200: "#b0b0b4",
          100: "#d4d2d0",
          50: "#e8e6e3",
        },
        // 电影墙身份色 — 酒红幕布
        cinema: {
          DEFAULT: "#b91c1c",
          50: "#fef2f2",
          400: "#f87171",
          500: "#dc2626",
          600: "#b91c1c",
          700: "#991b1b",
          800: "#7f1d1d",
          900: "#450a0a",
        },
        // 游戏墙身份色 — 街机电光青
        arcade: {
          DEFAULT: "#22d3ee",
          50: "#ecfeff",
          400: "#22d3ee",
          500: "#06b6d4",
          600: "#0891b2",
          700: "#0e7490",
          800: "#155e75",
          900: "#083344",
        },
        gold: "#fbbf24",
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Microsoft YaHei",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "SF Mono",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }],
      },
    },
  },
  plugins: [],
};
