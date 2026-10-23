"""Route B: native Coding/Review Harnesses under the existing deterministic Driver."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from agentlab.adapters.harness_workspace import HarnessWorkspace
from agentlab.adapters.runtime.harness_clients import ClaudeClient, CodexClient, HarnessFailure, HarnessReply
from agentlab.adapters.workspace import GitWorkspace
from agentlab.core.config import AppConfig
from agentlab.core.llm.retry import NonRetryable, ParallelFailure
from agentlab.core.monitor import commit_usage
from agentlab.core.ports import AgentRuntime, BlobStore, EditConflict, RunContext, Store
from agentlab.core.schemas import AgentInput, AgentResult, CoderOutput, Usage, Verdict

T = TypeVar("T", bound=BaseModel)


class HarnessRuntime:
    def __init__(self, cfg: AppConfig, raw_factory: Callable[[], AgentRuntime], store: Store, blobs: BlobStore,
                 workspace: GitWorkspace | None, directory: Path,
                 codex: Any = None, claude: Any = None) -> None:
        self.cfg, self.raw_factory, self.store, self.blobs = cfg, raw_factory, store, blobs
        self.workspace, self.directory = workspace, directory.resolve()
        self.codex, self.claude = codex or CodexClient(), claude or ClaudeClient()
        self._raw: AgentRuntime | None = None

    async def run_agent(self, role: str, inp: AgentInput, output_type: type[T], ctx: RunContext) -> AgentResult[T]:
        if role not in {"coder", "correctness-reviewer"}:
            if role in self.cfg.reviewer_roles or self.cfg.agents[role].kind == "reviewer":
                raise NonRetryable("sdk_profile_requires_single_reviewer")
            if self._raw is None:
                self._raw = self.raw_factory()
            return await self._raw.run_agent(role, inp, output_type, ctx)
        if self.workspace is None:
            raise ValueError("SDK worker requires a run workspace")
        if output_type is not (CoderOutput if role == "coder" else Verdict):
            raise ValueError("unsupported harness output type")
        is_coder = role == "coder"
        backend = "codex" if is_coder else "claude"
        package = "openai-codex" if is_coder else "claude-agent-sdk"
        sdk_version = version(package)  # Missing SDK is an explicit error, never a raw fallback.
        model = self.cfg.harness.codex_model if is_coder else self.cfg.harness.claude_model
        # SDK filesystem is context. Do not resend the custom Runtime's repository dump or tool prompts.
        context = {k: v for k, v in inp.context.items() if k != "files" and not k.startswith("_harness")}
        task = inp.model_copy(update={"context": context})
        prompt = ("Implement this task in the current source directory. Use your native tools. "
                  "Return a concise completion report; AgentLab exports actual filesystem changes.\n"
                  if is_coder else
                  "Review this fixed source revision against the task, diff and Gate evidence. "
                  "Read only. Return the requested Verdict schema; never edit files or run commands.\n")
        # PostgreSQL JSONB does not preserve object key order. Canonicalize the actual prompt too:
        # its hash participates in invocation identity, so equivalent restored inputs must stay identical.
        prompt += json.dumps(task.model_dump(mode="json", exclude_none=True), ensure_ascii=False, sort_keys=True)
        identity = {"task": task.model_dump(mode="json"), "role": role, "backend": backend,
                    "model": model, "schema": output_type.model_json_schema(),
                    "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest(),
                    "scope": inp.context.get("_harness_scope"),
                    "config": self.cfg.harness.model_dump(mode="json")}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        record = next((r for r in self.store.records("harness_invocation") if r["id"] == key), None)
        if record is None:
            # Even an older prompt/config fingerprint must not reopen a running write scope.
            # This also fails closed for checkpoints produced before canonical prompt serialization.
            scope_id = inp.context.get("_harness_scope")
            siblings = [r for r in self.store.records("harness_invocation")
                        if r["run_id"] == inp.run_id and r["role"] == role and (
                            (is_coder and scope_id and r.get("scope_id") == scope_id) or
                            (not is_coder and r.get("base_revision") == inp.revision_id
                             and (r.get("iteration") is None or r["iteration"] == inp.iteration))
                        )]
            if siblings:
                kind = ("harness_interrupted_requires_replan" if any(r["status"] == "running" for r in siblings)
                        else "harness_input_changed")
                raise NonRetryable(kind)
        alias = self.cfg.model_policy.roles[role].primary
        started = time.monotonic()
        usage_committed = False
        if record is None:
            revision = inp.context.get("_harness_revision") if is_coder else inp.revision_id
            if not revision:
                raise ValueError("harness source revision required")
            copy = HarnessWorkspace(self.workspace, self.directory / key)
            baseline = await asyncio.to_thread(copy.create, revision, inp.context.get("_harness_baseline"))
            if not is_coder:
                await asyncio.to_thread(copy.read_only)
            record = {"id": key, "run_id": inp.run_id, "project_id": ctx.run.project_id,
                      "role": role, "iteration": inp.iteration, "backend": backend, "sdk_version": sdk_version,
                      "base_revision": revision, "input_hash": key, "scope_id": inp.context.get("_harness_scope"),
                      "directory": str(copy.directory), "manifest_ref": self.blobs.put(json.dumps(baseline))[0],
                      "status": "prepared"}
            self.store.put_record("harness_invocation", key, record)
        if record["sdk_version"] != sdk_version:
            raise NonRetryable("harness_sdk_version_changed")
        copy = HarnessWorkspace(self.workspace, Path(record["directory"]))
        if (not copy.directory.is_relative_to(self.directory) or copy.directory != self.directory / key
                or copy.directory.resolve() != copy.directory):
            raise ValueError("invalid harness recovery path")

        def update(data: dict[str, Any]) -> None:
            assert record is not None
            record.update(data)
            self.store.put_record("harness_invocation", key, record)

        if record["status"] == "completed":
            output = output_type.model_validate_json(self.blobs.get(record["result_ref"]))
            reply = HarnessReply(usage=Usage.model_validate(record["usage"]), metered=record["metered"],
                                 model=record["model"])
        else:
            if record["status"] not in {"prepared", "sdk_completed"}:
                # An unknown old process may still own this copy. No replay, new turn, or concurrent writer.
                raise NonRetryable("harness_interrupted_requires_replan")
            if self.workspace.review_snapshot()[0] != record["base_revision"]:
                raise EditConflict("harness_source_changed", [])
            if record["status"] == "prepared":
                baseline = json.loads(self.blobs.get(record["manifest_ref"]))
                if await asyncio.to_thread(copy.scan) != baseline:
                    raise EditConflict("harness_copy_changed", [])
                attempt_id = ctx.attempt_started({"role": role, "alias": alias, "model": model or f"{backend}-default",
                                                  "backend": backend, "invocation_id": key,
                                                  "prompt": {"text": prompt,
                                                             "schema": output_type.model_json_schema()}}) \
                    if ctx.attempt_started else None
                update({"status": "running", "attempt_id": attempt_id})
                try:
                    kwargs: dict[str, Any] = {"source": copy.root, "state": copy.directory / "state", "prompt": prompt,
                              "model": model, "update": update}
                    reply = await (self.codex.run(**kwargs) if is_coder else
                                   self.claude.run(**kwargs, schema=output_type.model_json_schema()))
                    def preserve_metering() -> None:
                        if attempt_id and ctx.attempt_finished:
                            ctx.attempt_finished(attempt_id, {"usage": reply.usage.model_dump()})

                    commit_usage(ctx, reply.usage.for_call(role, alias, reply.model,
                                                         attempt_id or key, reply.metered), preserve_metering)
                    usage_committed = True
                    manifest = await asyncio.to_thread(copy.scan)
                    terminal = {"status": "sdk_completed",
                                "sdk_manifest_ref": self.blobs.put(json.dumps(manifest, sort_keys=True))[0],
                                "reply": {"text": reply.text, "structured": reply.structured,
                                          "usage": reply.usage.model_dump(),
                                          "metered": reply.metered, "model": reply.model}}

                    update(terminal)
                except HarnessFailure as exc:
                    failed_reply = exc.reply

                    def failed() -> None:
                        update({"status": "failed", "usage": failed_reply.usage.model_dump(),
                                "error_kind": "harness_failed"})
                        if attempt_id and ctx.attempt_finished:
                            ctx.attempt_finished(attempt_id, {"status": "failed", "error_kind": "harness_failed",
                                                              "usage": failed_reply.usage.model_dump()})

                    commit_usage(ctx, failed_reply.usage.for_call(role, alias, failed_reply.model,
                                                                attempt_id or key, failed_reply.metered), failed)
                    raise
                except BaseException:
                    # Keep the invocation unresolved. Explicit rejection creates a new write scope.
                    # The existing attempt machinery handles interrupted-call approval/accounting.
                    raise
            else:
                reply = HarnessReply(**{**record["reply"], "usage": Usage.model_validate(record["reply"]["usage"])})
            frozen_manifest = json.loads(self.blobs.get(record["sdk_manifest_ref"]))
            if await asyncio.to_thread(copy.scan) != frozen_manifest:
                raise EditConflict("harness_copy_changed", [])
            baseline = json.loads(self.blobs.get(record["manifest_ref"]))
            if is_coder:
                edits, manifest = await asyncio.to_thread(copy.edits, baseline)
                # A native completion summary is not AgentLab's read-only report deliverable.
                # Keep it in the invocation, so an empty/reverted diff cannot bypass Review/signoff.
                output = output_type.model_validate(CoderOutput(
                    edits=edits, blocked_reason=None if edits else "SDK produced no promotable text changes",
                ).model_dump())
            else:
                manifest = await asyncio.to_thread(copy.scan)
                if manifest != baseline:
                    raise EditConflict("harness_review_modified", list(manifest.keys() | baseline.keys()))
                if reply.structured is None:
                    raise ValueError("review structured output missing")
                output = output_type.model_validate(reply.structured)
                assert isinstance(output, Verdict)
                output = output_type.model_validate(output.model_copy(update={
                    "revision_id": inp.revision_id, "reviewer_id": role,
                }).model_dump())
            if await asyncio.to_thread(copy.scan) != frozen_manifest:
                raise EditConflict("harness_copy_changed", [])
            if self.workspace.review_snapshot()[0] != record["base_revision"]:
                raise EditConflict("harness_source_changed", [])
            result_ref = self.blobs.put(output.model_dump_json())[0]
            update({"status": "completed", "result_ref": result_ref,
                    "output_manifest_ref": self.blobs.put(json.dumps(manifest, sort_keys=True))[0],
                    "usage": reply.usage.model_dump(), "metered": reply.metered, "model": reply.model})
        usage = reply.usage.for_call(role, alias, reply.model, record.get("attempt_id") or key, reply.metered)

        def finish() -> None:
            if record and record.get("attempt_id") and ctx.attempt_finished:
                ctx.attempt_finished(record["attempt_id"], {"status": "completed", "usage": usage.model_dump(),
                                                          "response": output.model_dump_json()})

        if usage_committed:
            with ctx.usage_transaction():
                finish()
        else:
            commit_usage(ctx, usage, finish)
        result = AgentResult[T](role=role, output=output, alias=alias, model=reply.model, usage=reply.usage,
                                usage_recorded=ctx.record_usage is not None,
                                latency_ms=int((time.monotonic() - started) * 1000), routing_reason=f"{backend}_sdk")
        if ctx.on_result:
            ctx.on_result(result)
        return result

    async def run_parallel(self, inputs: dict[str, AgentInput], output_type: type[T],
                           ctx: RunContext) -> list[AgentResult[T]]:
        # This profile intentionally has one Reviewer; do not launch extra SDK reviewers.
        if len(inputs) != 1:
            raise ParallelFailure(NonRetryable("sdk_profile_requires_single_reviewer"), [])
        role, inp = next(iter(inputs.items()))
        return [await self.run_agent(role, inp, output_type, ctx)]
