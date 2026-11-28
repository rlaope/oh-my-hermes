import { afterEach, expect, it, vi } from 'vitest';
import { useShortcuts } from './shortcuts';

const {togglePanel, kitty} = vi.hoisted(() => ({togglePanel:vi.fn(), kitty:{on:false}}));
vi.mock('../sessions/term/engine-input', () => ({programReadsKeys: () => kitty.on}));
vi.mock('react', async (load) => ({...(await load<typeof import('react')>()), useEffect: (cb: () => unknown) => cb()}));
vi.mock('./menuClose', () => ({listenMenuClose: () => {}}));
vi.mock('../state/store', async (load) => ({...(await load<typeof import('../state/store')>()), getStore: () => ({actions:{togglePanel},getState:() => ({ui:{view:'session',session:'s1'}})})}));
afterEach(() => { vi.unstubAllGlobals(); togglePanel.mockClear(); kitty.on = false; });

function key(platform: string, inTerminal: boolean, stopPropagation = vi.fn()) {
  const handlers: ((e: unknown) => void)[] = [];
  vi.stubGlobal('navigator',{platform});
  vi.stubGlobal('window',{addEventListener:(t: string, f: (e: unknown) => void) => {if (t === 'keydown') handlers.push(f);}});
  useShortcuts();
  const mac = platform === 'MacIntel';
  handlers.forEach((h) => h({key:'.',code:'Period',metaKey:mac,ctrlKey:!mac,altKey:false,shiftKey:false,
    target:{closest:(s:string) => inTerminal && s === '.xterm'},preventDefault:vi.fn(),stopPropagation}));
}
it('macOS Cmd+. while the terminal has focus toggles the right panel', () => {
  key('MacIntel',true);
  expect(togglePanel).toHaveBeenCalledOnce();
});
it('Windows Ctrl+. outside the terminal toggles the right panel', () => {
  key('Win32',false);
  expect(togglePanel).toHaveBeenCalledOnce();
});
it('Windows Ctrl+. while the terminal has focus still opens the advertised right panel', () => {
  key('Win32',true);
  expect(togglePanel).toHaveBeenCalledOnce();
});
it('Windows Ctrl+. while the terminal\'s program has the Kitty keyboard protocol on goes to the program', () => {
  kitty.on = true;
  const stop = vi.fn();
  key('Win32',true,stop);
  expect(togglePanel).not.toHaveBeenCalled();
  expect(stop).not.toHaveBeenCalled();
});
