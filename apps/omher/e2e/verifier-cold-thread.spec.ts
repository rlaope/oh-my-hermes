import { expect, test } from '@playwright/test';

const bot = 'kami';
const port = Number(process.env.OMHER_MOCK_PORT || 5308);
const answer = 'A delayed but valid history row';

async function mock(op: string, params: Record<string, unknown> = {}) {
  const ws = new WebSocket(`ws://127.0.0.1:${port}/?token=e2e`);
  await new Promise<void>((ok, bad) => { ws.onopen = () => ok(); ws.onerror = () => bad(new Error('mock connection failed')); });
  const response = await new Promise<any>((ok) => {
    ws.onmessage = (event) => { const r = JSON.parse(String(event.data)); if (r.id === 'cold-probe') ok(r); };
    ws.send(JSON.stringify({ op, id: 'cold-probe', ...params }));
  });
  ws.close();
  expect(response.ok, JSON.stringify(response)).toBe(true);
  return response.result;
}

test('a valid cold thread history at 25s must load or show a failure rather than spin forever', async ({ page }) => {
  await mock('mock.reset');
  const { threads: [thread] } = await mock('mock.threads', { bot, threads: [{ title: 'Slow history', messages: [['assistant', answer]] }] });
  let release: (() => void) | undefined;
  let opens = 0;
  await page.routeWebSocket(/127\.0\.0\.1/, ws => {
    const server = ws.connectToServer();
    let held = '';
    ws.onMessage(raw => {
      const m = JSON.parse(String(raw));
      if (m.op === 'thread.open' && m.thread === thread && ++opens === 1) held = m.id;
      server.send(raw);
    });
    server.onMessage(raw => {
      const m = JSON.parse(String(raw));
      if (held && m.id === held) {
        expect(m.ok).toBe(true);
        expect(m.result.messages.map((x: { text: string }) => x.text)).toContain(answer);
        release = () => ws.send(raw);
      } else ws.send(raw);
    });
  });
  await page.clock.install();
  await page.goto('/');
  await page.getByTestId(`thread-row-${thread}`).getByTestId('thread-open').click();
  const chat = page.getByTestId('thread-chat');
  const loading = chat.getByText('Loading…', { exact: true });
  await expect(loading).toBeVisible();
  await expect.poll(() => Boolean(release)).toBe(true);
  await page.clock.runFor(25_000);
  release!();
  // A healthy app shows the returned row (old head) or a visible failure if it chose to abandon the reply.
  const history = chat.getByText(answer, { exact: true });
  const error = chat.getByTestId('chat-error');
  await page.clock.runFor(45_000);
  console.log('cold browser open', { opens, loading: await loading.count(), error: await error.count(), history: await history.count() });
  await expect(history.or(error)).toBeVisible({ timeout: 1500 });
  await expect(loading).toHaveCount(0);
});
