# OMHER selected-folder evidence: A2UI contract

Only an attached OMH folder chat uses this projection. The local UI projects the scoped bridge reply into one immutable `createSurface` message for the run and one for the selected node. It does not receive model-authored UI, negotiate a catalog over the network, or persist a surface. The renderer validates each whole snapshot and resolves the `root` record by ID before drawing anything. The catalog ID is an identifier, not a URL to open.

## Source and check

Vendored unmodified from [A2UI commit `5ff1b05f02d39f969b52a942e78e864ef3ac01fa`](https://github.com/a2ui-project/a2ui/tree/5ff1b05f02d39f969b52a942e78e864ef3ac01fa), Apache-2.0 (see LICENSE). The immutable source paths are `catalogs/basic/v1/catalog.json`, `specification/v1_0/json/common_types.json`, `specification/v1_0/json/agent_to_renderer.json`. `verify.py` pins all three SHA-256 digests and resolves references offline, including the catalog-relative common types and the protocol-relative catalog.

From `apps/omher`, run `python tests/a2ui-v1/verify.py` with an existing Python environment containing `jsonschema` and `referencing`, and the app's installed test dependencies. No Python validator ships in the UI. The gate captures **both complete messages passed to the real rendering function** for a recorded bridge fixture via the production `RunEvidence` component. It validates each with the upstream Draft 2020-12 protocol schema and checks that an extra top-level field and a multi-child Card fail. It also exercises the runtime profile and Markdown fallback via Vitest.

## Runtime profile (not general A2UI support)

`version: "1.0"`; `createSurface` has exactly `surfaceId`, `catalogId: "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"`, and `components`. Only these catalog records, with static scalar values, are supported:

| Record | Fields beyond `component` and `id` | OMHER rendering |
| --- | --- | --- |
| `Card` | `child`: one component ID | Bordered evidence card |
| `Column` | `children`: ordered array of IDs | Vertical stack, in reference order |
| `Text` | `text`: literal string; `variant`: `body` or `caption` | Inert typographic Markdown, theme text colors |
| `Divider` | `axis`: `horizontal` | Semantic horizontal rule |

The app requires these explicit variants and axis values; the upstream defaults are not implemented. No dynamic strings, templates, styles from the payload, catalog overrides, events, actions, functions, model data, URL/image/media widgets, or incremental protocol messages. No Row, List, Tabs or input widgets needed. An invalid graph (duplicate/missing ID, cycle, shared child, orphan), unsupported record/property, version/catalog mismatch, or a size/depth limit rejects the *entire* rich surface. The independently assembled fallback keeps the same admitted title, state, goal, topology or selected attempts and handoff as Markdown; it never fetches more data. Both paths drop raw HTML, remove link destinations, and substitute image alt text. Status and repair relationships are text, never commands.

## Compared with the previous folder panel

- **Retained:** attached folder/run/node selection; explicit native buttons; limited selected handoff; dependencies, status, focus/foreground/reconnect rereads; normal bot Plans, CLI graphs, threads, approvals and clarify handlers unchanged.
- **Adapted:** the previous spatial graph becomes a linear, wrapping dependency summary and keyboard-operable node picker. The selected node's own read supplies its attempts and text; no sibling-private detail is needed. Selected buttons expose `aria-pressed`; empty/loading/error messages are distinct. Cards use existing OMHER theme tokens, no animation or horizontal graph dragging.
- **Intentionally omitted:** zoom/pan, drawer preview expansion (the already-clipped handoff is shown in full), link chips, helper-session launch, retry/ask, and inferred executor/PR enrichment. No extra files, `gh`, gateway, or model calls to reconstruct them. A settled status is the DAG record's claim, not proof of execution or approval.
