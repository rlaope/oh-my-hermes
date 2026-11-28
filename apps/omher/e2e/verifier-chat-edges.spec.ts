import { expect, test, type Page } from '@playwright/test';
const port = Number(process.env.OMHER_MOCK_PORT || 5308);
async function mock(op: string, params: Record<string, unknown> = {}): Promise<any> {
  const ws = new WebSocket(`ws://127.0.0.1:${port}/?token=e2e`);
  await new Promise<void>((ok, reject) => { ws.onopen = () => ok(); ws.onerror = () => reject(Error('mock socket failed')); });
  const r = await new Promise<any>((ok) => {
    ws.onmessage = (e) => { const m = JSON.parse(String(e.data)); if (m.id === 'verify') ok(m); };
    ws.send(JSON.stringify({id:'verify', op, ...params}));
  });
  ws.close();
  expect(r.ok, JSON.stringify(r)).toBe(true);
  return r.result;
}
const calls = async (op: string) => (await mock('mock.calls')).calls.filter((c: any) => c.op === op && c.params.bot === 'kami');
const sends = async () => (await calls('chat.send')).map((c: any) => c.params.text);
const composer = (p: Page) => p.getByTestId('composer');
async function open(p: Page) {
  await p.goto('/');
  await expect(p.getByTestId('bot-kami')).toHaveAttribute('aria-current','true');
  await expect(p.getByTestId('bubble-user').first()).toBeVisible();
}
async function say(p: Page, text: string) {
  await composer(p).fill(text);
  await composer(p).press('Enter');
}
async function start(p: Page) {
  await mock('mock.manual', {bot:'kami'});
  await open(p);
  await say(p, 'start this turn');
  await expect(p.getByTestId('stop')).toBeVisible();
}
async function allow(p: Page) {
  await mock('mock.ask', {bot:'kami',kind:'approval'});
  const card = p.getByTestId('card-approval');
  await expect(card).toBeVisible();
  await card.focus();
  await p.keyboard.press('2');
  await expect.poll(async () => (await calls('approval.respond')).length).toBe(1);
  await expect(composer(p)).toHaveAttribute('placeholder', /Kami/);
}
test.beforeEach(async () => { await mock('mock.reset'); });

test('Korean IME: the first 229 commits; the second 229 after compositionend sends', async ({page}) => {
  await mock('mock.manual', {bot:'kami'});
  await open(page);
  const c = composer(page);
  await c.fill('야');
  await c.evaluate((el) => {
    el.dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true,data:'야'}));
    el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter',keyCode:229,isComposing:true,bubbles:true,cancelable:true}));
    el.dispatchEvent(new CompositionEvent('compositionend', {bubbles:true,data:'야'}));
  });
  expect(await sends()).toEqual([]);
  await c.dispatchEvent('keydown',{key:'Enter',keyCode:229,isComposing:false,bubbles:true,cancelable:true});
  await expect.poll(sends,{timeout:3000}).toEqual(['야']);
});

test('wake during a turn, fail one bots.list, then send by button after the bridge becomes idle', async ({page}) => {
  let drop = () => { throw Error('socket not connected'); };
  let lose = false;
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((raw) => {
      const msg = JSON.parse(String(raw));
      if (lose && msg.op === 'bots.list') {
        lose = false;
        ws.send(JSON.stringify({id:msg.id,ok:false,error:{code:'disconnected',message:'lost on wake'}}));
      } else server.send(raw);
    });
    drop = () => ws.close({code:1011});
  });
  await start(page);
  await allow(page);
  lose = true;
  drop();
  await mock('mock.endTurn', {bot:'kami',outcome:'done'});
  await expect.poll(() => lose, {timeout:10000}).toBe(false);
  await expect(composer(page)).toBeEnabled();
  await expect(composer(page)).toHaveAttribute('placeholder', /Kami/);
  await composer(page).fill('button after wake');
  await page.getByTestId('send').click();
  await expect.poll(sends,{timeout:5000}).toEqual(['start this turn','button after wake']);
});

test('approval answered but turn.end lost: follow-up must not stay held behind the phantom turn', async ({page}) => {
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    server.onMessage((raw) => { if (JSON.parse(String(raw)).event !== 'turn.end') ws.send(raw); });
  });
  await start(page);
  await allow(page);
  await mock('mock.endTurn', {bot:'kami',outcome:'done'});
  await say(page, 'after a lost turn end');
  await expect.poll(sends,{timeout:5000}).toEqual(['start this turn','after a lost turn end']);
});

test('no steer reply on a live socket: the first row must show held/uncertain or a reason', async ({page}) => {
  let dropped = 0;
  await page.routeWebSocket(/127\.0\.0\.1/, (ws) => {
    const server = ws.connectToServer();
    ws.onMessage((raw) => {
      if (JSON.parse(String(raw)).op === 'chat.steer') { dropped++; return; }
      server.send(raw);
    });
  });
  await start(page);
  await say(page, 'unacknowledged follow-up');
  await expect.poll(() => dropped).toBe(1);
  await mock('mock.endTurn',{bot:'kami',outcome:'done'});
  const row = page.getByTestId('bubble-user').filter({hasText:'unacknowledged follow-up'});
  await expect(row).toBeVisible();
  await expect.poll(async () => ({
    held: await row.getAttribute('data-held'),
    reason: (await row.innerText()).replace('unacknowledged follow-up','').trim(),
  }),{timeout:5000}).not.toEqual({held:null,reason:''});
});
