# Third-party notices

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
