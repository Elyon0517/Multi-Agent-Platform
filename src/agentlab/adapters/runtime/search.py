from __future__ import annotations

from typing import Any

import openai

from agentlab.core.budget import estimate_cents
from agentlab.core.config import AppConfig
from agentlab.core.monitor import commit_usage
from agentlab.core.ports import RunContext
from agentlab.core.schemas import Usage


async def native_search(svc: Any, cfg: AppConfig, query: str, ctx: RunContext) -> dict[str, Any]:
    model_alias = cfg.model_policy.roles["root"].primary
    alias = cfg.models.aliases[model_alias]
    estimate = estimate_cents(alias, len(query.encode()), 2048) + cfg.budget.ask.web_search_cents
    if ctx.reserve_budget:
        ctx.reserve_budget(estimate)
    else:
        ctx.check_budget(estimate)
    attempt = (
        ctx.attempt_started(
            {
                "api": "responses",
                "role": "root",
                "alias": model_alias,
                "model": alias.model,
                "input": query,
                "tools": [{"type": "web_search"}],
            }
        )
        if ctx.attempt_started
        else None
    )
    received = False
    try:
        url, key = svc.gateway()
        async with openai.AsyncOpenAI(base_url=url, api_key=key, timeout=45, max_retries=0) as client:
            response = await client.responses.create(
                model=alias.model,
                input="Search web pages and cite source URLs: " + query[:4000],
                include=["web_search_call.action.sources"],
                tools=[{"type": "web_search"}],
                max_output_tokens=2048,
            )
        data = response.model_dump(mode="json")
        searches = sum(o.get("type") == "web_search_call" for o in data["output"])
        usage = response.usage
        charged = Usage(
            tokens_in=usage.input_tokens if usage else 0,
            tokens_out=usage.output_tokens if usage else 0,
            cost_cents=alias.cost_cents(usage.input_tokens, usage.output_tokens) if usage else 0,
        )
        charged.cost_cents += searches * cfg.budget.ask.web_search_cents
        received = True

        def finished() -> None:
            if attempt and ctx.attempt_finished:
                ctx.attempt_finished(
                    attempt, {"status": "completed", "response": data, "usage": charged.model_dump(mode="json")}
                )

        commit_usage(ctx, charged.for_call("root", model_alias, alias.model, attempt, usage is not None), finished)
        sources = []
        for output in data["output"]:
            for content in output.get("content", []):
                for annotation in content.get("annotations", []):
                    if annotation.get("url"):
                        sources.append({"kind": "web", "ref": annotation["url"], "title": annotation.get("title", "")})
        return {"text": response.output_text, "sources": sources, "output": data["output"]}
    except BaseException as exc:
        # A persistence error after a provider response must never become a zero-usage call.
        if not received:
            error_kind = type(exc).__name__

            def failed() -> None:
                if attempt and ctx.attempt_finished:
                    ctx.attempt_finished(attempt, {"status": "failed", "error": error_kind})

            commit_usage(ctx, Usage().for_call("root", model_alias, alias.model, attempt, False), failed)
        raise
    finally:
        if ctx.release_budget:
            ctx.release_budget(estimate)


async def probe_search(svc: Any) -> dict[str, Any]:
    url, key = svc.gateway()
    model = svc.cfg.models.aliases[svc.cfg.model_policy.roles["root"].primary].model
    result: dict[str, Any] = {"model": model, "base_url": url, "responses_web_search": False, "chat_web_search": False}
    if not url or not key:
        return result
    async with openai.AsyncOpenAI(base_url=url, api_key=key, timeout=30, max_retries=0) as client:
        for api in ("responses", "chat"):
            try:
                if api == "responses":
                    response = await client.responses.create(
                        model=model,
                        tools=[{"type": "web_search"}],
                        input="Search the web for the official Python documentation. Cite its URL.",
                        max_output_tokens=256,
                    )
                    result["responses_web_search"] = any(o.type == "web_search_call" for o in response.output)
                else:
                    chat = await client.chat.completions.create(
                        model=model,
                        max_tokens=256,
                        messages=[{"role": "user", "content": "Search the web for Python documentation; cite it."}],
                        extra_body={"web_search_options": {}},
                    )
                    result["chat_web_search"] = bool(chat.choices and chat.choices[0].message.annotations)
            except Exception as exc:
                result[api + "_error"] = type(exc).__name__
    svc.store.put_record("gateway_capability", "native_search", result)
    return result
