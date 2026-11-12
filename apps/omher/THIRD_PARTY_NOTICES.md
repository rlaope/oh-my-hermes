# Third-party notices for omher

omher ships data taken from the projects below. Each keeps its own licence; the notices are reproduced in full.

## Terminal colour themes

The terminal themes a person can pick in Settings › Terminal, other than omher's own two, are colour palettes
carried over from Orca by `scripts/import-orca-themes.mjs` into `src/sessions/term/themes-orca.ts`. Only the
palette data (theme names and colour values) is taken; no Orca code is.

### Orca (stablyai/orca)

Source: <https://github.com/stablyai/orca>, `src/shared/terminal-themes/` (`defaults.ts`, `popular-dark-core.ts`,
`popular-dark-extended.ts`, `popular-light.ts`, `classic.ts`): 31 palettes. The rule that picks the minimum
contrast from a theme's background (4.5:1 on a light background, 3:1 on a dark one) also follows Orca's.

```
MIT License

Copyright (c) 2026 Lovecast Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### GitHub VS Code themes (Primer), as bundled with Orca

Source: `resources/plugins/launch/stablyai.orca-github-vscode-theme/terminal/` in the Orca repository, which carries
the terminal colours of GitHub's VS Code themes (<https://github.com/primer/github-vscode-theme>): 5 palettes
(GitHub Light Default, GitHub Light High Contrast, GitHub Dark Default, GitHub Dark High Contrast, GitHub Dark
Dimmed).

```
MIT License

Copyright (c) 2020 Primer

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
