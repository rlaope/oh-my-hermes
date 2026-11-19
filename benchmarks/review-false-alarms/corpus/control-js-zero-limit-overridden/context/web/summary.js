import { searchParams } from "./api.js";

export async function resultCount(query) {
  const response = await fetch(`/search?${searchParams({ query, limit: 0 })}`);
  const body = await response.json();
  return body.total;
}
