import { defineConfig } from "@playwright/test";
// Each dag node runs its own ports (OMHER_PORT for vite, OMHER_MOCK_PORT for the mock bridge) so
// parallel e2e runs never collide. Defaults are for a person running `pnpm e2e` alone.
const port = Number(process.env.OMHER_PORT || 5307);
const mock = Number(process.env.OMHER_MOCK_PORT || 5308);
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  // One mock bridge holds shared state (calls log, running turn): spec files must not run against it at once.
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1280, height: 820 },
    // past the first-run cards: specs see the app as a returning person does (onboarding.spec.ts clears it)
    storageState: { cookies: [], origins: [{ origin: `http://127.0.0.1:${port}`, localStorage: [{ name: "omher.onboarded", value: "1" }] }] },
  },
  webServer: [
    { command: `node e2e/mock-bridge.mjs --port ${mock}`, port: mock, reuseExistingServer: false },
    { command: `pnpm exec vite --host 127.0.0.1 --port ${port} --strictPort`, port, reuseExistingServer: false,
      env: { VITE_OMHER_BRIDGE: `ws://127.0.0.1:${mock}/?token=e2e` } },
  ],
});
