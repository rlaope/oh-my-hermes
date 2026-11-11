// Commands that deserve a warning line on the approval card. This only adds a label; the buttons keep
// the same weight and order (Deny first), and Hermes' own approval rules decide what is asked at all.
import { t, type Key } from "../../i18n";

const RULES: [RegExp, Key][] = [
  [/\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+/, "risk.delete"],
  [/\b(rmdir|del|rd)\s+\/s\b|Remove-Item\b[^\n]*-Recurse/i, "risk.delete"],
  [/\bsudo\b|\bdoas\b|\brunas\b/, "risk.admin"],
  [/\bgit\s+push\b[^\n]*(--force\b|--force-with-lease\b|\s-f\b)/, "risk.force"],
  [/\bgit\s+(reset\s+--hard|clean\s+-[a-zA-Z]*[fdx])/, "risk.discard"],
  [/\b(mkfs|diskutil\s+erase|format\s+[a-z]:)/i, "risk.erase"],
  [/\bdd\s+[^\n]*\bof=\/dev\//, "risk.rawDisk"],
  [/\b(chmod|chown)\s+(-R\s+)?[0-7]*\s*\/(\s|$)|\bchmod\s+-R\s+777\b/, "risk.perms"],
  [/\b(DROP\s+(TABLE|DATABASE)|TRUNCATE\s+TABLE)\b/i, "risk.db"],
  [/\b(curl|wget|iwr|Invoke-WebRequest)\b[^\n|]*\|\s*(sudo\s+)?(sh|bash|zsh|iex|python)\b/i, "risk.pipe"],
  [/\bkubectl\s+delete\b|\bterraform\s+destroy\b/, "risk.infra"],
  [/(^|[;&|]\s*):\(\)\s*\{/, "risk.forkBomb"],
];

/** Plain-language reasons this command is risky (deduplicated, in rule order). Empty = nothing flagged. */
export function riskOf(command: string): string[] {
  const out: string[] = [];
  for (const [re, key] of RULES) {
    const why = t(key);
    if (re.test(command) && !out.includes(why)) out.push(why);
  }
  return out;
}
