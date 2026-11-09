// Markdown in bot bubbles: GFM tables with alignment, code blocks that wrap, task lists without a second
// marker, headings by size, and nothing (links, code) poking out of the bubble.
import { expect, test } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);

async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${MOCK}/?token=e2e`);
  await new Promise<void>((res, rej) => {
    ws.onopen = () => res();
    ws.onerror = () => rej(new Error("mock websocket error"));
  });
  const reply = await new Promise<any>((res) => {
    ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.id === "md1") res(msg);
    };
    ws.send(JSON.stringify({ id: "md1", op, ...params }));
  });
  ws.close();
  expect(reply.ok, JSON.stringify(reply)).toBe(true);
  return reply.result;
}

const TEXT = [
  "## 배포 점검 결과",
  "",
  "**결론:** `/v1/responses` 502는 upstream keep-alive 만료가 원인입니다. ~~옛 재시도 방식~~은 폐기.",
  "",
  "| 설정 | 전 | 후 | 상태 |",
  "|---|---:|---:|:---:|",
  "| p50 latency | 412 ms | 198 ms | ok |",
  "| 502 비율 | 3.1% | 0.04% | ok |",
  "| 재시도 횟수 | 0 | 1 | warn |",
  "| `gateway.upstream.keepalive_timeout_seconds_for_every_region_and_replica` | 60 | 75 | ? |",
  "",
  "1. `retry.ts` 수정",
  "   - backoff 200ms",
  "   - 최대 1회",
  "2. 배포 후 30분 관찰",
  "",
  "- [x] 테스트 통과",
  "- [ ] 문서 갱신",
  "",
  "> 주의: 재시도는 멱등 요청에만 적용합니다.",
  "",
  "```ts",
  "export async function withRetry<T>(fn: () => Promise<T>, tries = 1): Promise<T> { try { return await fn(); } catch (e) { if (tries <= 0) throw e; await sleep(200); return withRetry(fn, tries - 1); } }",
  "```",
  "",
  "---",
  "",
  "긴 URL https://github.com/rlaope/oh-my-hermes/actions/runs/42615558060/job/129150631784/attempts/3/logs 도 확인.",
].join("\n");

test.beforeEach(async () => {
  await mock("mock.reset");
});

test("tables, code blocks, task lists and headings render inside the bubble", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("bot-kami")).toHaveAttribute("aria-current", "true");
  await expect(page.getByTestId("bubble-user").first()).toBeVisible();
  await mock("mock.emit", { events: [{ event: "message", bot: "kami", id: "md-spec", text: TEXT }] });
  const bubble = page.getByTestId("bubble-bot").last();
  await expect(bubble.locator("table")).toBeVisible();
  await bubble.scrollIntoViewIfNeeded();

  const m = await bubble.evaluate((el) => {
    const r = (e: Element) => e.getBoundingClientRect();
    const b = el.querySelector(".b")!;
    const bb = r(b);
    const table = el.querySelector("table")!;
    const head = [...table.querySelectorAll("tr")[0].querySelectorAll("th")].map((th) => getComputedStyle(th).textAlign);
    const longCode = [...table.querySelectorAll("td code")].find((c) => c.textContent!.length > 40)!;
    const td = longCode.closest("td")!;
    const next = td.nextElementSibling!;
    const cb = r(longCode);
    const tdb = r(td);
    const task = el.querySelector(".task-list-item")!;
    const pre = el.querySelector("pre")!;
    const preCode = pre.querySelector("code")!;
    const p = el.querySelector("p")!;
    const inside = (e: Element) => {
      const x = r(e);
      return x.left >= bb.left - 0.5 && x.right <= bb.right + 0.5;
    };
    return {
      rows: table.querySelectorAll("tr").length,
      head,
      codeLines: Math.round(cb.height / parseFloat(getComputedStyle(longCode).lineHeight || "16")),
      codeInTd: cb.left >= tdb.left - 0.5 && cb.right <= tdb.right + 0.5,
      codeClearOfNext: cb.right <= r(next).left + 0.5,
      taskListStyle: getComputedStyle(task).listStyleType,
      taskMarker: getComputedStyle(task, "::marker").content,
      checkbox: task.querySelectorAll("input[type=checkbox]").length,
      preCodeBg: getComputedStyle(preCode).backgroundColor,
      preWraps: pre.scrollWidth <= pre.clientWidth,
      h2: parseFloat(getComputedStyle(el.querySelector("h2")!).fontSize),
      body: parseFloat(getComputedStyle(p).fontSize),
      outside: [...el.querySelectorAll(".b a, .b code")].filter((e) => !inside(e)).map((e) => e.textContent!.slice(0, 40)),
      blockquote: !!el.querySelector("blockquote"),
      hr: !!el.querySelector("hr"),
      del: !!el.querySelector("del"),
      nested: el.querySelectorAll("ol > li > ul > li").length,
    };
  });

  expect(m.rows).toBe(5);
  expect(m.head).toEqual(["left", "right", "right", "center"]);
  expect(m.codeLines).toBeGreaterThan(1); // the long cell wraps
  expect(m.codeInTd).toBe(true);
  expect(m.codeClearOfNext).toBe(true);
  expect(m.taskListStyle).toBe("none");
  expect(m.checkbox).toBe(1);
  expect(m.preCodeBg).toMatch(/^(transparent|rgba\(0, 0, 0, 0\))$/);
  expect(m.preWraps).toBe(true);
  expect(m.h2).toBeGreaterThan(m.body);
  expect(m.outside).toEqual([]);
  expect([m.blockquote, m.hr, m.del, m.nested]).toEqual([true, true, true, 2]);
});
