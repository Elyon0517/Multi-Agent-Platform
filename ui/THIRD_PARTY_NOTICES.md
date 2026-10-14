# Third-party notices

## munder-difflin (MIT)

The following directories are adapted from [chaitanyagiri/munder-difflin](https://github.com/chaitanyagiri/munder-difflin),
Copyright (c) 2026 Chaitanya Giri, MIT License:

- `src/scene/office/` (Office Floor scene, characters, pathfinding, bubbles, envelopes, themes)
- `src/design/` (pixel design tokens and global styles)
- `src/components/` (PixelPanel, PixelButton, PixelBadge, Icon, SpritePortrait, TasksKanban, ToolWaterfall,
  MemoryGraphPanel, memoryGraph/*, BlockedBanner, ThreadsPanel, AgentStrip, AgentCard, AgentNameEditor,
  RecentText, OfficeThemePicker, AskMeTab, askMeOrder, TaskDetailOverlay)
- `src/markdown/`, `src/hooks/useTelemetry.ts`, `src/hooks/useTypewriter.ts`, `src/hooks/useWorkspaceImage.ts`,
  `src/i18n/`, `src/shared/`

Local changes: Electron IPC (`window.cth`) is reimplemented in `src/bridge.ts` on top of the Agent Converge SSE event
store (`src/store/store.ts`); event-to-avatar mapping lives in `src/scene/adapter/`. Terminal / PTY, voice
(RealtimeMichaelToggle, CostHud) and agent spawn/restore paths were removed from the ported components; the
theme switch no longer deletes agents.

```
MIT License

Copyright (c) 2026 Chaitanya Giri

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

## the-office (ISC)

`src/scene/office/TiledMapRenderer.ts`, `Camera.ts` and `SeatPool.ts` include code
ported from [shahar061/the-office](https://github.com/shahar061/the-office).
The maps and artwork from that repository are no longer bundled.

```
ISC License

Copyright (c) 2026 shahar061

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.
THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

## Original workspace artwork

`src/assets/tilesets/workspace.svg`, `src/assets/maps/studio.tmj`,
`src/assets/maps/atrium.tmj` and the character recipes in
`src/scene/office/portraitArt.ts` were authored for Agent Converge. Shapes,
layouts and character recipes do not use third-party image inputs or likeness
references. Permission for these original artwork files is in
`src/assets/LICENSE.txt`; the existing renderer code retains its upstream MIT/ISC notices.

## Fonts (SIL OFL 1.1)

Press Start 2P (Cody Boisclair), Inter (The Inter Project Authors), JetBrains Mono (JetBrains).
Full text: `src/assets/fonts/LICENSE.txt`.
