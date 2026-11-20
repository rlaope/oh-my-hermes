function intInRange(name, raw, min, max) {
  const value = Number(raw);
  if (!Number.isInteger(value) || value < min || value > max) {
    throw new Error(`${name} must be an integer from ${min} to ${max}, got ${raw}`);
  }
  return value;
}

export const settings = Object.freeze({
  menuDepth: intInRange("MENU_DEPTH", process.env.MENU_DEPTH ?? "2", 1, 4),
});
