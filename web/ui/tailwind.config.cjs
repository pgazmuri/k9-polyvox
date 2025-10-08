const defaultTheme = require("tailwindcss/defaultTheme");

module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        midnight: "#070A1B",
        nebula: "#1D1F3C",
        pulse: "#5C5CFF",
        aurora: "#2ED7C9"
      },
      fontFamily: {
        sans: ["'Inter Variable'", ...defaultTheme.fontFamily.sans]
      },
      boxShadow: {
        glow: "0 0 25px rgba(94, 80, 255, 0.35)"
      }
    }
  },
  plugins: []
};
