/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        primary:          "#C17D5A",
        "primary-dark":   "#A0623F",
        bg:               "#FAF7F4",
        surface:          "#FFFFFF",
        border:           "#EDE8E2",
        "text-base":      "#2C2420",
        muted:            "#9C8880",
        gold:             "#D4A853",
        success:          "#5A8A6A",
        warning:          "#C49A3A",
        danger:           "#B85C5C",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      borderRadius: {
        xl:  "0.875rem",
        "2xl": "1.25rem",
      },
    },
  },
  plugins: [],
}