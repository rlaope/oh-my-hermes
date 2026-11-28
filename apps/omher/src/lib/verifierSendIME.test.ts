import { expect, it } from 'vitest';
import { composing, holdImeEnter, watchComposition } from './ime';

it('Korean IME Enter should be suppressed for commit, not for the later non-composing 229', () => {
  expect(composing({keyCode:229,isComposing:true})).toBe(true);
  // Composer only invokes send for Enter when this predicate is false.
  expect(composing({keyCode:229,isComposing:false})).toBe(false);
});

it('tracks the composition: only the Enter that commits it is held; a later 229 Enter sends', async () => {
  const field = new EventTarget();
  const undo = watchComposition(field);
  try {
    const enter = (isComposing: boolean) => ({ key: 'Enter', keyCode: 229, isComposing, nativeEvent: { isComposing }, held: false, preventDefault() { this.held = true; } });
    field.dispatchEvent(new Event('compositionstart'));
    // Chinese / Japanese candidate pick, Korean syllable commit: inside the composition
    expect(composing(enter(false))).toBe(true);
    field.dispatchEvent(new Event('compositionend'));
    // WebKit: the committing Enter, 229 and not composing, in the same task as compositionend
    const commit = enter(false);
    holdImeEnter(commit);
    expect(commit.held).toBe(true);
    await new Promise((r) => setTimeout(r, 0));
    // the person's next Enter: sends
    const next = enter(false);
    holdImeEnter(next);
    expect(next.held).toBe(false);
    // a field blurred mid-composition (no compositionend) does not swallow later Enters
    field.dispatchEvent(new Event('compositionstart'));
    field.dispatchEvent(new Event('focusout'));
    expect(composing(enter(false))).toBe(false);
  } finally {
    undo();
  }
});
