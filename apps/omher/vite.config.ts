import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 5207, strictPort: true },
  test: { environment: "node", include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
} as never);
