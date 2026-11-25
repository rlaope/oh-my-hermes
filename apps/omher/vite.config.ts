import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  // scripts/e2e-shards.sh starts several dev servers at once: each gets its own dep-optimizer cache so they never
  // write one node_modules/.vite together. Unset, Vite's default applies.
  cacheDir: process.env.OMHER_VITE_CACHE_DIR || undefined,
  server: { port: 5207, strictPort: true },
  test: { environment: "node", include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
} as never);
