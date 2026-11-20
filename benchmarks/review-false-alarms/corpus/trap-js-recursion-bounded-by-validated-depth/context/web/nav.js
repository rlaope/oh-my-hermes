import { loadCategories } from "./categories.js";
import { flattenMenu } from "./menu.js";
import { settings } from "./settings.js";

export async function navItems(db) {
  const root = await loadCategories(db);
  return flattenMenu(root, settings.menuDepth).slice(1);
}
