/**
 * Tailwind CSS v3 config for Lowbid — self-hosted build, committed output.
 *
 *   npm run build:css   # -> static/css/tailwind.css (CI job tailwind-in-sync diffs it)
 *
 * Keep tailwindcss on v3.x (v4 is CSS-first and changes Preflight semantics).
 * `brand-*` utilities resolve through the --brand-*-rgb tokens so they follow the theme.
 */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./*/templates/**/*.html",
    "./static/js/*.js",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  "rgb(var(--brand-50-rgb) / <alpha-value>)",
          100: "rgb(var(--brand-100-rgb) / <alpha-value>)",
          200: "rgb(var(--brand-200-rgb) / <alpha-value>)",
          300: "rgb(var(--brand-300-rgb) / <alpha-value>)",
          400: "rgb(var(--brand-400-rgb) / <alpha-value>)",
          500: "rgb(var(--brand-500-rgb) / <alpha-value>)",
          600: "rgb(var(--brand-600-rgb) / <alpha-value>)",
          700: "rgb(var(--brand-700-rgb) / <alpha-value>)",
          800: "rgb(var(--brand-800-rgb) / <alpha-value>)",
          900: "rgb(var(--brand-900-rgb) / <alpha-value>)",
          950: "rgb(var(--brand-950-rgb) / <alpha-value>)",
        },
      },
      maxWidth: { "6xl": "72rem" },
    },
  },
  // Classes assembled at runtime in JS (toasts, badges) that the scanner cannot see.
  safelist: [
    { pattern: /(bg|text|border)-(brand|red|green|amber|blue|slate)-(100|200|300|400|500|600|700|800|900)/ },
    { pattern: /(grid-cols|col-span)-(1|2|3|4|6|12)/, variants: ["sm", "md", "lg"] },
  ],
};
