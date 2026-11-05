# Pitch

- **Problem**: Vim-mode composer users cannot jump to an inline character or delete/change/yank to it; baseline `fb` leaves text and caret unchanged.
- **Appetite**: One additive Composer slice after accepted word objects, with zero source writes during planning and an unchanged compatibility floor.
- **Solution boundary**: Character-directed movement and operator edits within one logical line, including opposite-direction search, repeats, counts and cancellation.
- **Rabbit holes / no-gos**: Full Vim emulation, cross-line search, regexes, visual/dot-repeat, new decoders/dependencies, and whole-file rollback are outside the bet.
- **Success / stop signal**: Every acceptance assertion and existing TUI regression must pass on the future bound candidate; needing broader modal changes stops or reshapes the slice. Baseline evidence does not claim feature success.
