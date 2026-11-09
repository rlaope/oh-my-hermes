// Commands that deserve a warning line on the approval card. This only adds a label; the buttons keep
// the same weight and order (Deny first), and Hermes' own approval rules decide what is asked at all.
const RULES: [RegExp, string][] = [
  [/\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+/, "Deletes files and folders"],
  [/\b(rmdir|del|rd)\s+\/s\b|Remove-Item\b[^\n]*-Recurse/i, "Deletes files and folders"],
  [/\bsudo\b|\bdoas\b|\brunas\b/, "Runs as administrator"],
  [/\bgit\s+push\b[^\n]*(--force\b|--force-with-lease\b|\s-f\b)/, "Rewrites history on a remote branch"],
  [/\bgit\s+(reset\s+--hard|clean\s+-[a-zA-Z]*[fdx])/, "Throws away local changes"],
  [/\b(mkfs|diskutil\s+erase|format\s+[a-z]:)/i, "Erases a disk"],
  [/\bdd\s+[^\n]*\bof=\/dev\//, "Writes straight to a disk"],
  [/\b(chmod|chown)\s+(-R\s+)?[0-7]*\s*\/(\s|$)|\bchmod\s+-R\s+777\b/, "Changes permissions broadly"],
  [/\b(DROP\s+(TABLE|DATABASE)|TRUNCATE\s+TABLE)\b/i, "Deletes database data"],
  [/\b(curl|wget|iwr|Invoke-WebRequest)\b[^\n|]*\|\s*(sudo\s+)?(sh|bash|zsh|iex|python)\b/i, "Runs a script from the internet"],
  [/\bkubectl\s+delete\b|\bterraform\s+destroy\b/, "Deletes live infrastructure"],
  [/(^|[;&|]\s*):\(\)\s*\{/, "Fork bomb"],
];

/** Plain-language reasons this command is risky (deduplicated, in rule order). Empty = nothing flagged. */
export function riskOf(command: string): string[] {
  const out: string[] = [];
  for (const [re, why] of RULES) if (re.test(command) && !out.includes(why)) out.push(why);
  return out;
}
