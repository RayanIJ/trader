import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Deliberately muted, non-casino palette. Risk state uses clear semantics.
        ok: "#22c55e",
        degraded: "#f59e0b",
        down: "#ef4444",
        live: "#dc2626",
        panel: "#11161d",
        panelborder: "#1f2933",
      },
    },
  },
  plugins: [],
};

export default config;
