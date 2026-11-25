import { defineConfig } from "@playwright/test";
// Each dag node runs its own ports (OMHER_PORT for vite, OMHER_MOCK_PORT for the mock bridge) so
// parallel e2e runs never collide. Defaults are for a person running `pnpm e2e` alone.
const port = Number(process.env.OMHER_PORT || 5307);
const mock = Number(process.env.OMHER_MOCK_PORT || 5308);
export default defineConfig({
  testDir: "e2e",
  // OMHER_E2E_SKIP: spec files this run leaves out, space-separated (CI's Linux runners leave out the specs that
  // measure text against the macOS and Windows UI fonts; the macOS job runs those).
  testIgnore: (process.env.OMHER_E2E_SKIP ?? "").split(/\s+/).filter(Boolean).map((f) => `**/${f.replace(/^e2e\//, "")}`),
  timeout: 30_000,
  // One mock bridge holds shared state (calls log, running turn): spec files must not run against it at once.
  workers: 1,
  // CI runs three shards at once on a 3-4 core runner (scripts/e2e-shards.sh), and under that load a first page.goto
  // can miss the 30 s budget (PR #3191: 1 of ~1,180 on windows-latest). One retry on CI only; Playwright still lists
  // a test that passed on retry as flaky in the log, so it stays visible. Local runs never retry.
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1280, height: 820 },
    // past the first-run cards, with all four mock bots in the sidebar list: specs see the app as a returning person
    // who added them does (onboarding.spec.ts and roster.spec.ts start from nothing)
    storageState: {
      cookies: [],
      origins: [
        {
          origin: `http://127.0.0.1:${port}`,
          localStorage: [
            { name: "omher.onboarded", value: "1" },
            { name: "omher.roster", value: JSON.stringify(["kami", "friren", "default", "omh-tui"]) },
          ],
        },
      ],
    },
  },
  webServer: [
    { command: `node e2e/mock-bridge.mjs --port ${mock}`, port: mock, reuseExistingServer: false },
    { command: `pnpm exec vite --host 127.0.0.1 --port ${port} --strictPort`, port, reuseExistingServer: false,
      env: { VITE_OMHER_BRIDGE: `ws://127.0.0.1:${mock}/?token=e2e` } },
  ],
});
