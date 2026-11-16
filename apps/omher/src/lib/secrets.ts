// omher's one masker for token-like text (`ghp_…`, `glpat-…`, `sk-…`, `xoxb-…`, `AKIA…`, `token=…`). The patterns
// live in secrets.json, which the bridge (mask_secrets) and the desktop shell (tasks.rs mask_secrets) read too, so
// every surface masks the same strings the same way.
import spec from "./secrets.json";

const TOKENS = new RegExp(spec.tokens, "g");
const ASSIGNED = new RegExp(spec.assigned, "gi");

/** `text` with every token-like string replaced by `••••` (an assignment keeps its name: `token=••••`). */
export function maskSecrets(text: string): string {
  return text.replace(TOKENS, spec.mask).replace(ASSIGNED, (_m, name: string) => `${name}=${spec.mask}`);
}
