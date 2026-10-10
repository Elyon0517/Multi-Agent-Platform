from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentlab.adapters.workspace import GitWorkspace
from agentlab.bootstrap import Services
from agentlab.core.budget import BudgetGuard
from agentlab.core.conversation import Message, RootTurn, Source
from agentlab.core.llm.tools import tool_spec
from agentlab.core.monitor import UsageRecorder, commit_result_usage
from agentlab.core.ports import RunContext
from agentlab.core.project_config import project_config
from agentlab.core.schemas import AgentInput, Run, new_id
from agentlab.core.session.store import append_message, get_thread
from agentlab.core.session.tools import SessionTools


class SessionService:
    def __init__(self, svc: Services) -> None:
        self.svc = svc

    async def answer(
        self, project_id: str | None, thread_id: str, text: str, *, summary: bool = False
    ) -> tuple[RootTurn, str]:
        svc = self.svc
        thread = get_thread(svc.store, thread_id, project_id)
        turn_id = new_id()
        user = (
            None
            if summary
            else append_message(svc.store, thread_id, project_id, Message(author="user", text=text, turn_id=turn_id))
        )
        if user:
            from agentlab.core.schemas import Event, EventType

            svc.bus.publish(
                Event(
                    run_id="thread:" + thread_id,
                    type=EventType.MESSAGE_CREATED,
                    actor="user",
                    payload={"message": user.model_dump(mode="json")},
                )
            )
        project = svc.projects.get(project_id) if project_id else None
        cfg = project_config(svc.cfg, project.settings) if project and project.settings else svc.cfg
        ws = GitWorkspace(Path(project.workspace), secrets=svc.workspace_secrets()) if project else None
        tools = SessionTools(ws, svc.knowledge, svc.store, project_id, thread_id)
        run = Run(
            id=turn_id,
            goal=text,
            project_id=project_id or "global",
            workspace=project.workspace if project else "",
            budget_cents=cfg.budget.ask.max_turn_cents,
        )
        guard = BudgetGuard(run, cfg.budget.warn_ratio, lambda _: None)
        record: dict[str, Any] = {
            "id": turn_id,
            "thread_id": thread_id,
            "project_id": project_id,
            "user_message_id": user.id if user else None,
            "tool_calls": [],
            "attempts": [],
            "created_at": run.created_at.isoformat(),
            "status": "running",
        }

        def save() -> None:
            record.update(tokens_in=run.tokens_in, tokens_out=run.tokens_out, cost_cents=run.cost_cents)
            svc.store.put_record("root_turn", turn_id, record)

        def started(payload: dict[str, Any]) -> str:
            aid = new_id()
            ref, _ = svc.blobs.put(json.dumps(payload, ensure_ascii=False))
            attempt_data: dict[str, Any] = {"id": aid, "prompt_ref": ref, "status": "in_flight"}
            attempt_data.update({k: payload[k] for k in ("role", "alias", "model") if k in payload})
            record["attempts"].append(attempt_data)
            record["prompt_ref"] = ref
            save()
            return aid

        def finished(aid: str, payload: dict[str, Any]) -> None:
            ref, _ = svc.blobs.put(json.dumps(payload, ensure_ascii=False))
            next(a for a in record["attempts"] if a["id"] == aid).update(
                response_ref=ref, **{k: payload[k] for k in ("usage", "status") if k in payload})
            record["response_ref"] = ref
            save()

        def record_tool(payload: dict[str, Any]) -> None:
            record["tool_calls"].append(payload)
            save()

        search = next(
            (
                r
                for r in svc.store.records("gateway_capability")
                if r.get("model") == cfg.models.aliases[cfg.model_policy.roles["root"].primary].model
                and r.get("base_url") == svc.gateway()[0]
            ),
            None,
        )
        search_enabled = bool(search and search.get("responses_web_search"))
        specs = tools.specs
        if search_enabled:
            specs.append(
                tool_spec(
                    "web_search",
                    "Use the gateway's native web search for live information",
                    {"query": {"type": "string"}},
                )
            )

        web_sources: list[Source] = []

        async def execute(name: str, args: dict[str, Any]) -> Any:
            if name == "web_search" and search_enabled:
                if set(args) != {"query"} or not isinstance(args["query"], str):
                    raise ValueError("invalid search arguments")
                from agentlab.adapters.runtime.search import native_search

                result = await native_search(svc, cfg, args["query"], ctx)
                web_sources.extend(Source.model_validate(s) for s in result.get("sources", []))
                return result
            result = await tools.execute(name, args)
            if name == "artifact_read":
                return {"kind": result["kind"], "content": svc.blobs.get(result["content_ref"])[:15000]}
            return result

        def delta(content: str) -> None:
            import re

            from agentlab.core.schemas import Event, EventType

            match = re.search(r'"reply"\s*:\s*(".*)', content, re.S)
            if not match:
                return
            raw = match.group(1)
            try:
                reply, _ = json.JSONDecoder().raw_decode(raw)
            except json.JSONDecodeError:
                # Only emit complete JSON escapes; the next chunk supplies the rest.
                try:
                    reply = json.loads(raw + '"')
                except json.JSONDecodeError:
                    return
            svc.bus.publish(
                Event(
                    run_id="thread:" + thread_id,
                    type=EventType.MESSAGE_DELTA,
                    actor="root",
                    payload={"thread_id": thread_id, "turn_id": turn_id, "text": reply},
                )
            )

        ctx = RunContext(
            run=run,
            check_budget=guard.check,
            reserve_budget=guard.reserve,
            release_budget=guard.release,
            record_usage=UsageRecorder(svc.store, "turn", turn_id, project_id, guard.record),
            usage_transaction=svc.store.transaction,
            attempt_started=started,
            attempt_finished=finished,
            tool_specs=specs,
            execute_tool=execute,
            record_tool=record_tool,
            on_delta=delta,
        )
        save()
        try:
            memory = []
            if not project or not project.settings or project.settings.retrieval != "off":
                try:
                    hits = await svc.knowledge.search(
                        project_id,
                        "root",
                        text[:4000],
                        project.settings.retrieval_k if project and project.settings else 6,
                    )
                    memory = [{"ref": h.item.id, "text": h.item.text, "source": h.item.source} for h in hits]
                except Exception:
                    pass
            inp = AgentInput(
                run_id=turn_id,
                iteration=0,
                goal=text,
                context={
                    "history": [m.model_dump(mode="json") for m in thread.messages[-20:]],
                    "project": project.model_dump(mode="json") if project else None,
                    "web_search_available": search_enabled,
                    "summary_only": summary,
                    "memory": memory,
                    "current_time": run.created_at.isoformat(),
                },
            )
            result = await svc.runtime(cfg=cfg).run_agent("root", inp, RootTurn, ctx)
            commit_result_usage(ctx, result)
            record.update(model_alias=result.alias, model=result.model)
            turn = result.output
            for source in web_sources:
                if not any(s.ref == source.ref for s in turn.sources):
                    turn.sources.append(source)
            if not project and turn.intent == "task":
                turn = RootTurn(intent="clarify", reply="请先选择项目,再执行代码任务。")
            if summary and turn.intent == "task":
                turn = RootTurn(intent="answer", reply=turn.reply, sources=turn.sources)
            record.update(status="completed", intent=turn.intent, output=turn.model_dump(mode="json"))
            save()
            return turn, turn_id
        except Exception as exc:
            record.update(status="failed", error=type(exc).__name__)
            if summary:
                save()
                raise
            limited = type(exc).__name__ == "BudgetExceeded" or str(exc) == "tool_call_limit"
            reply = (
                "本轮预算或工具次数已达上限,请缩小问题后重试。" if limited else "本轮回答未完成,请检查网关配置后重试。"
            )
            fallback = RootTurn(intent="answer", reply=reply)
            record.update(intent=fallback.intent, output=fallback.model_dump(mode="json"))
            save()
            return fallback, turn_id
        finally:
            from agentlab.core.schemas import Event, EventType

            svc.bus.publish(
                Event(
                    run_id="thread:" + thread_id,
                    type=EventType.TURN_FINISHED,
                    actor="root",
                    payload={"thread_id": thread_id, "turn_id": turn_id},
                )
            )
            if ws:
                ws.close()
