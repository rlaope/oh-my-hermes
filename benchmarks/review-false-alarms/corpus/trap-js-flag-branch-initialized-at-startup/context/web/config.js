import { readFileSync } from "node:fs";

function deepFreeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

export function loadConfig(path) {
  return deepFreeze(JSON.parse(readFileSync(path, "utf8")));
}
