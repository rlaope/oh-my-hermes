/**
 * Loads the category graph. A category can be listed under several parents
 * (category_links), and admins edit links freely, so the graph can contain a
 * cycle; anything that walks it must bound its depth.
 */
export async function loadCategories(db) {
  const rows = await db.all("SELECT id, label FROM categories");
  const links = await db.all("SELECT parent_id, child_id FROM category_links");
  const byId = new Map(rows.map((row) => [row.id, { id: row.id, label: row.label, children: [] }]));
  byId.set(0, { id: 0, label: "All", children: [] });
  for (const { parent_id, child_id } of links) {
    byId.get(parent_id)?.children.push(byId.get(child_id));
  }
  return byId.get(0);
}
