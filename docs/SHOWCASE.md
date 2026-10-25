# Reproduce the office walkthrough

Verified locally on 2026-10-24 using Python 3.12, Node 24 and Chromium headless.

## Commands

From the repository root:

```bash
uv sync
uv run pytest -q
cd ui
npm ci
npm test
npm run build
npx playwright install chromium
npm run test:e2e
npm run test:showcase
```

`test:showcase` starts the real API on 8877 and Vite on 5185, runs scenario S2,
then stops both servers. Those ports must be available. It uses the real API, event stream,
file edits, revision validation, Gate and configured review orchestration. Model replies
are scripted; usage and displayed costs are synthetic rather than billed provider usage.

## Results and scope

- Python: 407 passed, 40 skipped. Skips are the suite's optional/environment-dependent tests.
- UI: 77 unit tests passed; TypeScript and production build passed.
- Default browser suite: 2 passed; old-version comparison skipped without `BASELINE_UI_URL`,
  and the opt-in API walkthrough is skipped there because it runs separately below.
- API-backed browser walkthrough: passed. A failed pytest Gate is followed by a fix,
  a reviewer-requested docstring and a passing final Gate. The run reaches `DONE`.
- `office-review.png` captures the office during review; `completed-run.png` captures
  the completed run with real Gate history. They live in `docs/screenshots/`.
- This scenario supplies an explicit workspace, so the runtime completes in place.
  It does not verify isolated workspace merge/signoff or live model-provider reliability.
- Gate diagnostics now interpolate the failed step rather than showing `{{step}}`.

For a human-paced walkthrough use `uv run python scripts/showcase.py --only S2 --speed 2`
and run `npm run dev` from `ui/` in a second terminal. Open `http://localhost:5173/?follow=1`.
The server stays available after completion for inspection; Ctrl+C stops it.
