import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The API runs on 8000 (`mrforge serve`); in development Vite forwards /api to it.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "node" },
});
