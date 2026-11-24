import { afterEach, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import * as catalog from "./catalog";
import { EvidenceSurface, RunEvidence } from "./Evidence";
import type { AgentRun } from "../../lib/runs";

const data = JSON.parse(readFileSync(fileURLToPath(new URL("../../lib/__fixtures__/runs-bridge.json", import.meta.url)), "utf-8"));
const run: AgentRun = data.runs.find((r: AgentRun) => r.id.endsWith("/route-hint-dedup"));
const node = run.nodes.find((n) => n.id === "implement")!;
const surface = () => catalog.evidenceSurface("A run", "Waiting", ["Recorded evidence"], "dag-test");
afterEach(() => { vi.restoreAllMocks(); });

it("renders complete production run and node messages, not data-dependent widgets", () => {
  const gate = vi.spyOn(catalog, "readSurface");
  const text = data.handoffs[run.id][node.id] + "\n\n![scan](https://private.invalid/pixel) [notes](https://private.invalid/)";
  const html = renderToStaticMarkup(<RunEvidence run={run} selected={node.id} evidence={{ node, text }} onNode={() => {}} />);
  expect(gate).toHaveBeenCalledTimes(2);
  const messages = gate.mock.calls.map(([message]) => message);
  for (const result of gate.mock.results) expect(result.value).toBeInstanceOf(Map);
  expect(html).toContain("basic-v1"); expect(html).toContain(run.title); expect(html).toContain("scan");
  expect(html).not.toMatch(/<(?:a |img|iframe|script)|private\.invalid/);
  expect(JSON.stringify(messages[0])).not.toContain("private.invalid");
  expect(JSON.stringify(messages[1])).toContain("private.invalid");
  // The offline upstream-schema gate captures the same two inputs that reached the native rendering gate.
  if (process.env.OMHER_SCHEMA_CAPTURE) writeFileSync(process.env.OMHER_SCHEMA_CAPTURE, JSON.stringify(messages));
});

it("resolves the referenced child order, not record order or recognized field IDs", () => {
  const m = surface();
  const body = m.createSurface.components.find((x) => x.component === "Column")!;
  body.children.reverse(); m.createSurface.components.reverse();
  const html = renderToStaticMarkup(<EvidenceSurface message={m} markdown="fallback" />);
  expect(html.indexOf("Recorded evidence")).toBeLessThan(html.indexOf("A run"));
});

it("rejects a wrong envelope, catalog, active component, property, binding or graph as a whole", () => {
  const m = surface(), s = m.createSurface, r = s.components;
  const badRecords: unknown[][] = [
    [...r, r[0]], [...r, {id:"orphan", component:"Divider", axis:"horizontal"}],
    ...[{child:"root"}, {child:"missing"}, {child:["body"]}, {child:{id:"body"}}, {weight:1}, {action:{event:{name:"go"}}}].map(x => [{...r[0], ...x}, ...r.slice(1)]),
    ...[{component:"Image"}, {component:"Button"}, {text:{path:"/private"}}, {text:{call:"openUrl"}}, {variant:"h1"}].map(x => [...r.slice(0,2), {...r[2], ...x}, ...r.slice(3)]),
    [r[0], {...r[1], children:{path:"/",componentId:"title"}}, ...r.slice(2)],
    [r[0], {...r[1], children:["title", "title"]}, ...r.slice(2)],
  ];
  for (const input of [null, { ...m, version:"0.9" }, {...m, updateComponents:{}}, {...m, createSurface:{...s, dataModel:{}}},
    {...m, createSurface:{...s, catalogId:"unknown"}}, ...badRecords.map(components => ({...m, createSurface:{...s, components}}))]) {
    expect(catalog.readSurface(input)).toBeNull();
    const html = renderToStaticMarkup(<EvidenceSurface message={input} markdown={"**Run B** · failed\n\nSelected handoff: [why](https://private.invalid) ![log](https://private.invalid/i)"} />);
    expect(html).toContain("markdown"); expect(html).toContain("<strong>Run B</strong>"); expect(html).toContain("Selected handoff");
    expect(html).not.toMatch(/private\.invalid|<img|<a |A run/);
  }
});

it("does not render a late reply for a different selected node", () => {
  const html = renderToStaticMarkup(<RunEvidence run={run} selected="verify" evidence={{node, text:"PRIVATE_LATE"}} onNode={() => {}} />);
  expect(html).not.toContain("PRIVATE_LATE"); expect(html).toContain('role="status"');
});
