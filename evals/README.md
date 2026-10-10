# Regression baseline

Run `uv run agentlab eval --output evals/results/latest.json` for the deterministic
baseline: ten fixed Python repairs, five DISCOVERY §2.5 conversation cases, and three memory quality cases.
Each repair first runs the full Python Gate and requires failure specifically at `test`;
a failure at typecheck, lint or format is reported as `failure_kind: fixture`, before any
model call. Fake mode also uses the full Gate rather than the pytest-only demo Gate.
Each repair executes the real objective Gate and review loop, stops at human signoff,
and verifies original tests, budget and the three-reviewer panel. The manifest
`allowed_files` check fails when files other than `calc.py` change, including Gate
configuration; this is a scoring check, not an execution restriction. Task conversations
use the same run creation service as the API and verify progress and approval messages.

Scorecards contain checks (`name`, `passed`, `severity`, `gate`, `source_type`, `detail`)
and the DISCOVERY P8 summary fields. Hard failures yield exit code 1; soft failures
only increment warnings. JSON output is suitable for CI and comparisons.

`--runtime raw` exercises the configured gateway and prompts. This performs paid model
calls and changes only disposable fixture copies. Both eval and smoke create workspaces
under `~/.agentlab-workspaces`, outside the application Git checkout and visible to
Colima. Raw eval uses the Docker sandbox; fake eval uses the local sandbox. Fake mode validates orchestration,
tools, persistence and scoring; each fake case contributes one `blind_spot_count`,
because scripted intent and reviewer outputs do not measure model/prompt quality.
Do not interpret a fake PASS as evidence that a new root prompt is semantically correct.

Run `uv run agentlab ping --search` before testing native web search. Responses search
is enabled only for the exact probed gateway/model. Search request/response blobs,
tool results and usage are persisted with each root turn. `budget.ask.web_search_cents`
is a configurable gateway search fee estimate, added to actual token usage; adjust it
to the gateway's billing schedule. Chat search with no citation evidence is not enabled.

Each evaluation saves `scorecard.json`, per-task JSON records and final `.diff` files
under `data_dir/eval-results/<id>`. Records include `stopped_reason`, `changed_files`
and the initial Gate result, and survive disposable workspace cleanup.

Results are generated locally; do not commit machine-specific transcripts or credentials.

Each repair task and conversation case has a **600-second total deadline**, covering
fixture preflight, model calls/retries, tools, Gate and review. Override it with
`agentlab eval --task-timeout 120`. A deadline produces a failed `timeout` card,
then evaluation continues to the next case. Per-case JSON preserves `run_state`
and `last_event` (including an in-progress `step.tool_call`), or null when no run
has been created. Final diff capture has a separate 5-second bound. Cancellation
kills local subprocess groups and removes the named Docker container; Docker
cleanup allows up to 30 seconds plus bounded process cleanup.

Fake runs use the host venv's mypy/ruff/pytest; raw runs use the Gate image's pinned
versions. If only raw fails, compare those versions before attributing it to a
model regression.


Run only the summarizer quality cases with:

```bash
uv run agentlab eval --manifest evals/memory.json --runtime raw --output evals/results/memory.json
```

These synthetic inputs go through the production `MemoryHooks.on_finished` stage:
repeated docstring findings must merge into one active project lesson with version
history; user communication preferences must go to global; project conventions
must remain project-scoped. Pinned entries and documents must remain unchanged.
Scorecards preserve the memory versions, proposed/applied operations and model-call
usage. There is no code execution or full coding run in this suite. Each summarizer
invocation uses its independent 25c budget; the repeat case has two invocations.

`--runtime fake` verifies the eval wiring and rubric using fixture-specific outputs,
and adds a blind spot to every case; it does not demonstrate semantic quality.
The sanitized `memory-scorecard-real.json` records the real gateway run on 2026-10-10:
3/3 scenarios passed. This small regression suite is not a general quality benchmark.
