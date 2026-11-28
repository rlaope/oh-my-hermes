import { expect, test, type Page } from '@playwright/test';
import { mock, openApp, platformIsMac } from './term-find-helpers';
import { openFromSidebar } from './split-drag-helpers';

type Shim = { __omherSessions: {startTerminal(a: string, cwd: string): string; ptyOf(id: string): number | null}; __omherMockFgOwn?: Record<number,string>; __omherEmitSessionFg(x:{id:number;agent:string}):void };
const SID = 'cccccccc-2222-4333-8444-555555555555';
async function shell(page: Page) {
  await openApp(page);
  const id = await page.evaluate(() => (window as unknown as Shim).__omherSessions.startTerminal('shell','/home/you/codex-fixture'));
  await openFromSidebar(page,id);
  const term = page.locator(`[data-testid="terminal"][data-session="${id}"]`);
  await expect(term.locator('.xterm-rows')).toContainText('(mock)');
  return {id,term};
}
test.beforeEach(async () => { await mock('mock.reset'); });

test('Codex in a shell shows thread title without substituting a Claude model or subagents', async ({page}) => {
  await mock('mock.cliTitle',{agent:'codex',session:SID,title:'Codex recorded thread'});
  const {id} = await shell(page);
  await expect.poll(() => page.evaluate((i) => (window as unknown as Shim).__omherSessions.ptyOf(i),id)).not.toBeNull();
  await page.evaluate(([i,s]) => {
    const w = window as unknown as Shim;
    const p = w.__omherSessions.ptyOf(i)!;
    (w.__omherMockFgOwn ??= {})[p] = s;
    w.__omherEmitSessionFg({id:p,agent:'codex'});
  },[id,SID] as const);
  await page.getByTestId('panel-button').click();
  await expect(page.getByTestId('session-details')).toHaveAttribute('data-harness','codex');
  await expect(page.getByTestId('session-details-title')).toHaveText('Codex recorded thread',{timeout:15000});
  await expect(page.getByTestId('session-details-model')).toHaveCount(0);
  await expect(page.getByTestId('run-graph-box')).toHaveCount(0);
});

test('focused terminal opens the right panel with the advertised shortcut', async ({page}) => {
  const {term,id} = await shell(page);
  await term.locator('.xterm-helper-textarea').focus();
  const mac = await platformIsMac(page);
  await page.keyboard.press(mac ? 'Meta+.' : 'Control+.');
  await expect(page.getByTestId('session-details')).toHaveAttribute('data-session',id);
});
