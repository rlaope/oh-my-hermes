// Vite build of the omher.app preview: the real app (../src at the pinned commit, see tools/build_omher_preview.sh)
// with the in-page host instead of a bridge. Output: site/app-preview/ (hashed assets, relative base).
//
// The app needs a few small hooks to run on its own in a page, applied here as exact-once replacements so the
// app's source and behaviour stay untouched (a missing anchor fails the build instead of shipping a still app):
//   - plan timers tick every second instead of every 10 s, so running parts count up live;
//   - a SESSIONS chat's mock agent says it is a preview instead of echoing "(mock …)".
// (From 0.2.1 the app itself draws each part's vendor mark and lists GPT-6.1 for Codex; from 0.2.5 the Plans list
// re-reads itself (runs/live.ts) and the story calls its refreshRuns, so those hooks are gone.)
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = process.env.OMHER_PREVIEW_OUT || resolve(here, "../../../site/app-preview");

const HOOKS: Record<string, [string, string][]> = {
  "src/elsewhere/useNow.ts": [["export function useNow(on: boolean, ms = 10_000): number {", "export function useNow(on: boolean, ms = 1000): number {"]],
  "src/sessions/host.ts": [
    [
      "this.say(`(mock ${agentDef(this.agent).label}) You said: ${text}${pics}`, 360);",
      'this.say(`This session is a preview, so ${agentDef(this.agent).label} did not run. Download omher to start a real one in your own folder.`, 360);',
    ],
  ],
};

function previewHooks(): Plugin {
  const seen = new Set<string>();
  return {
    name: "omher-preview-hooks",
    enforce: "pre",
    transform(code, id) {
      const rel = Object.keys(HOOKS).find((k) => id.split("?")[0].endsWith(k));
      if (!rel) return null;
      let out = code;
      for (const [from, to] of HOOKS[rel]) {
        const n = out.split(from).length - 1;
        if (n !== 1) this.error(`preview hook: ${rel}: anchor found ${n}x: ${from.slice(0, 60)}`);
        out = out.replace(from, to);
      }
      seen.add(rel);
      return { code: out, map: null };
    },
    buildEnd(err) {
      if (err) return;
      const missing = Object.keys(HOOKS).filter((k) => !seen.has(k));
      if (missing.length) this.error(`preview hook: never reached ${missing.join(", ")}`);
    },
  };
}

export default defineConfig({
  root: here,
  base: "./",
  plugins: [previewHooks(), react()],
  clearScreen: false,
  server: { port: 5390, strictPort: true, fs: { allow: [resolve(here, "..")] } },
  build: {
    outDir: OUT,
    emptyOutDir: true,
    assetsInlineLimit: 8192,
    chunkSizeWarningLimit: 900,
    // only the app's own code: no source maps on the public site
    sourcemap: false,
  },
});
