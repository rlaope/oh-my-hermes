// The ONE place that reads src/assets/agents/ (the harness and agent marks as their vendors publish them: Lobe
// Icons, MIT; pi from pi-mono, MIT; omp's, OmO's and DSH's official marks; Kimi Code's npm icon; Hermes Agent's
// icon render; the OMH kami mark). Every other module asks for a mark by file name through here, so adding a
// harness is one asset file plus one registry row (src/harness/registry.ts).
const RAW = import.meta.glob<string>("../assets/agents/*.svg", { query: "?raw", import: "default", eager: true });
const URL_SVG = import.meta.glob<string>("../assets/agents/*.svg", { import: "default", eager: true });
const URL_PNG = import.meta.glob<string>("../assets/agents/*.png", { import: "default", eager: true });

const SAFE = /^[\w.-]+$/;

/** The SVG text of `file` (a name in src/assets/agents, no folder), or undefined. */
export function assetRaw(file: string): string | undefined {
  return SAFE.test(file) ? RAW[`../assets/agents/${file}`] : undefined;
}

/** A URL for `file` (PNG, or an SVG drawn as an image), or undefined. */
export function assetUrl(file: string): string | undefined {
  if (!SAFE.test(file)) return undefined;
  return URL_PNG[`../assets/agents/${file}`] ?? URL_SVG[`../assets/agents/${file}`];
}

/** Every file name in src/assets/agents. */
export function assetFiles(): string[] {
  return [...Object.keys(RAW), ...Object.keys(URL_PNG)].map((k) => k.slice("../assets/agents/".length)).sort();
}
