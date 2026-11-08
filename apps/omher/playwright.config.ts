import { defineConfig } from "@playwright/test";
// Each dag node runs its own ports (OMHER_PORT for vite, OMHER_MOCK_PORT for the mock bridge) so
// parallel e2e runs never collide. Defaults are for a person running `pnpm e2e` alone.
const port = Number(process.env.OMHER_PORT || 5307);
const mock = Number(process.env.OMHER_MOCK_PORT || 5308);
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1280, height: 820 } },
  webServer: [
    { command: `node e2e/mock-bridge.mjs --port ${mock}`, port: mock, reuseExistingServer: false },
    { command: `pnpm exec vite --port ${port} --strictPort`, port, reuseExistingServer: false,
      env: { VITE_OMHER_BRIDGE: `ws://127.0.0.1:${mock}/?token=e2e` } },
  ],
});
