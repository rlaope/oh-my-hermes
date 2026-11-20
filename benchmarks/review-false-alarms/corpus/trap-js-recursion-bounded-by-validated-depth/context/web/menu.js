export function flattenMenu(category, depth) {
  const items = [{ id: category.id, label: category.label, level: 0 }];
  if (depth === 0) return items;
  for (const child of category.children) {
    for (const item of flattenMenu(child, depth - 1)) {
      items.push({ ...item, level: item.level + 1 });
    }
  }
  return items;
}
