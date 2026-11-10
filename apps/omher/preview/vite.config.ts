// Vite build of the omher.app preview: the real app (../src at the pinned commit, see tools/build_omher_preview.sh)
// with the in-page host instead of a bridge. Output: site/app-preview/ (hashed assets, relative base).
//
// The app needs a few small hooks to run on its own in a page, applied here as exact-once replacements so the
// app's source and behaviour stay untouched (a missing anchor fails the build instead of shipping a still app):
//   - the Plans list re-reads when the preview's plan changes (the real bridge has no plan event yet);
//   - plan timers tick every second instead of every 10 s, so running parts count up live;
//   - a SESSIONS chat's mock agent says it is a preview instead of echoing "(mock …)";
//   - a plan part shows its model's vendor mark (and the agent CLI of a lane) instead of the Hermes mark.
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = process.env.OMHER_PREVIEW_OUT || resolve(here, "../../../site/app-preview");

const HOOKS: Record<string, [string, string][]> = {
  "src/runs/RunsTab.tsx": [
    [
      "function useRuns(bot: string, n = 0) {\n  const [list, setList]",
      `function useRuns(bot: string, n0 = 0) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const f = () => setTick((x) => x + 1);
    window.addEventListener("omher-preview:runs", f);
    return () => window.removeEventListener("omher-preview:runs", f);
  }, []);
  const n = n0 * 100000 + tick;
  const [list, setList]`,
    ],
  ],
  // the demo cast: every part shows its model's vendor mark (GLM, Kimi, DeepSeek, Claude, OpenAI), then the agent CLI
  // a lane went to; no Hermes mark (the v0.2 graph restyle does the same in the app)
  "src/runs/boxView.ts": [
    [
      'const marks = run.agent ? [run.agent] : ["hermes", ...(n.executor ? [n.executor] : [])];',
      `const vendor = __markFor(n.model ?? n.planned?.model, n.provider);
  const marks = run.agent ? [run.agent] : [vendor ? \`m:\${vendor}\` : "hermes", ...(n.executor ? [n.executor] : [])];`,
    ],
    ["// ---- a node's lines ----", 'import { markFor as __markFor } from "../ui/ModelIcon";\n// ---- a node\'s lines ----'],
  ],
  "src/runs/RunGraph.tsx": [
    [
      '{id === "hermes" ? <HermesMark size={12} /> : <AgentIcon id={id} size={12} />}',
      '{id === "hermes" ? <HermesMark size={12} /> : id.startsWith("m:") ? <__ModelIcon model={id.slice(2)} size={12} /> : <AgentIcon id={id} size={12} />}',
    ],
    ['import { AgentIcon, HermesMark } from "../ui";', 'import { AgentIcon, HermesMark } from "../ui";\nimport { ModelIcon as __ModelIcon } from "../ui/ModelIcon";'],
  ],
  "src/elsewhere/useNow.ts": [["export function useNow(on: boolean, ms = 10_000): number {", "export function useNow(on: boolean, ms = 1000): number {"]],
  "src/sessions/host.ts": [
    // the Codex session's model list shows today's model
    ['{ id: "gpt-5.5-codex", label: "GPT-5.5 Codex" },\n    { id: "gpt-5.5", label: "GPT-5.5" },', '{ id: "gpt-6.1-sol", label: "GPT-6.1 Sol" },\n    { id: "gpt-6.1-sol-mini", label: "GPT-6.1 Sol mini" },'],
    [
      "this.say(`(mock ${agentDef(this.agent).label}) You said: ${text}`, 360);",
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
