// omher's one masker for token-like text (`ghp_…`, `glpat-…`, `sk-…`, `xoxb-…`, `AKIA…`, `token=…`). The patterns
// live in secrets.json, which the bridge (mask_secrets) and the desktop shell (tasks.rs mask_secrets) read too, so
// every surface masks the same strings the same way.
import spec from "./secrets.json";

const SPLIT = spec.split.map(([p, n]) => [new RegExp(p as string, "g"), n as number] as const);
const TOKENS = new RegExp(spec.tokens, "g");
const ASSIGNED = new RegExp(spec.assigned, "gi");

/** A `split` match: the prefix and the body's pieces up to exactly `n` token characters become `••••` (the pieces
 *  after stay); left as it is when the pieces do not make exactly `n` at the end of one. */
function splitToken(all: string, body: string, n: number): string {
  let k = 0;
  for (let i = 0; i < body.length; i++) {
    if (/\s/.test(body[i])) continue;
    if (++k === n) return i + 1 === body.length || /\s/.test(body[i + 1]) ? spec.mask + body.slice(i + 1) : all;
  }
  return all;
}

/** `text` with every token-like string replaced by `••••` (an assignment keeps its name: `token=••••`); a `ghp_…` or
 *  `glpat-…` broken over lines is taken by its known length, in any letter case. */
export function maskSecrets(text: string): string {
  for (const [rx, n] of SPLIT) text = text.replace(rx, (all, body: string) => splitToken(all, body, n));
  return text.replace(TOKENS, spec.mask).replace(ASSIGNED, (_m, name: string) => `${name}=${spec.mask}`);
}
