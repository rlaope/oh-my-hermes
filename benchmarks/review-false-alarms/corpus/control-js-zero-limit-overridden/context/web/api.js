/**
 * Build search query parameters.
 * opts.limit: rows to return; 0 returns only the total count.
 */
export function searchParams(opts) {
  const limit = opts.limit || 50;
  const params = new URLSearchParams({ q: opts.query, limit: String(limit) });
  if (opts.cursor) {
    params.set("cursor", opts.cursor);
  }
  return params;
}
