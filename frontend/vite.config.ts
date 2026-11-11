import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// (No @types/node here, so the environment is read through globalThis.)
const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env;
const apiTarget = env?.MRFORGE_API ?? "http://127.0.0.1:8000";

// The API runs on 8000 (`mrforge serve`); in development Vite forwards /api to it
// (set MRFORGE_API to point at another server, for example a scratch copy used for checks).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": apiTarget } },
  test: { environment: "node" },
});
