# Regression baseline

Run `uv run agentlab eval --output evals/results/latest.json` for the deterministic
baseline: ten fixed Python repairs plus the five DISCOVERY §2.5 conversation cases.
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
