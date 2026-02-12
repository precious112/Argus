import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        argus: {
          50: "#f0f7ff",
          100: "#e0effe",
          200: "#b9dffd",
          300: "#7cc5fc",
          400: "#36a9f8",
          500: "#0c8ee9",
          600: "#0070c7",
          700: "#0059a1",
          800: "#054c85",
          900: "#0a406e",
          950: "#072849",
        },
      },
    },
  },
  plugins: [typography],
};

export default config;
