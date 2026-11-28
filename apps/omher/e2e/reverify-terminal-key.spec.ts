import { expect, test } from '@playwright/test';
import { feed, mock, newTerminal, openApp, platformIsMac, typed } from './term-find-helpers';

test('a terminal program that enabled modern key encoding still receives Ctrl+period', async ({page}) => {
  await mock('mock.reset');
  await openApp(page, {term: {kittyKeys: true}});
  expect(await platformIsMac(page)).toBe(false);
  await newTerminal(page);
  await feed(page, '\x1b[>1u');
  await page.locator('.xterm-helper-textarea').focus();
  // Positive control: the program sees a nearby Ctrl punctuation key using the Kitty wire encoding.
  await page.keyboard.press('Control+,');
  await expect.poll(() => typed(page)).toBe('\x1b[44;5u');
  await page.keyboard.press('Control+.');
  await expect.poll(async () => ({wire: await typed(page), panel: await page.getByTestId('details-panel').count()}), {timeout: 1800})
    .toEqual({wire: '\x1b[44;5u\x1b[46;5u', panel: 0});
});
