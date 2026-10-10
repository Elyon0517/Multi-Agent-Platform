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

munder-difflin in turn vendored the office maps and tilesets from
[shahar061/the-office](https://github.com/shahar061/the-office) (ISC).

## Pixel art: LimeZu "Modern Interiors" (credit required)

`src/assets/tilesets/*.png` and the Tiled maps built on them (`src/assets/maps/*.tmj`) are from
**Modern Interiors - RPG Tileset [16X16]** by **LimeZu** — https://limezu.itch.io/ — under the LimeZu Complete
Version licence (see `src/assets/tilesets/LIMEZUASSETS-LICENSE.txt`). Credit is required. The licence forbids
redistributing the asset itself; before Agent Converge is published as open source these files must be replaced or
excluded (tracked in `docs/DISCOVERY.md` §19).

## Fonts (SIL OFL 1.1)

Press Start 2P (Cody Boisclair), Inter (The Inter Project Authors), JetBrains Mono (JetBrains).
Full text: `src/assets/fonts/LICENSE.txt`.
