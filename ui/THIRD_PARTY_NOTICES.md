# Project and third-party notices

## Project source license

Project-original code and documentation use the root MIT license, except where a file
states otherwise. The following notice is included here for production distributions.

```text
MIT License

Copyright (c) 2026 Elyon0517

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

## Project implementation

The current workspace renderer, pixel controls, document previews, telemetry readers,
localization bootstrap and theme loader are implemented in this repository.
The replacement scope, source comparison and compatibility tests are recorded in
[`docs/UI_REPLACEMENT.md`](../docs/UI_REPLACEMENT.md).
These notices describe the current source distribution; historical Git revisions
retain the notices that accompanied their code.

## Original workspace artwork

The vector atlas `src/assets/tilesets/workspace.svg`, maps `studio.tmj` and
`atrium.tmj`, fictional cast palettes and procedural character drawing routines
are project-authored. Their MIT permission notice is in `src/assets/LICENSE.txt`.

## Fonts (SIL OFL 1.1)

The following unmodified third-party fonts remain bundled for offline use:

- Press Start 2P — Cody Boisclair.
- Inter — The Inter Project Authors.
- JetBrains Mono — The JetBrains Mono Project Authors.

Copyright statements and the full SIL OFL 1.1 text are in
`src/assets/fonts/LICENSE.txt` and are included in the production notice file.

## Package dependencies

React, PixiJS and the other dependencies remain third-party software, with their
own licenses. Exact versions are recorded in `package-lock.json`; dependency
license texts are emitted by Vite in `DEPENDENCY_LICENSES.md` beside the built application.
