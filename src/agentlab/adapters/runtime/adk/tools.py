"""Expose a role's granted tools to ADK. Grants, approvals and edit journaling stay in ctx.execute_tool."""
from __future__ import annotations

import json
from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from agentlab.adapters.runtime.adk.model import VALUE_KEY, CallState
from agentlab.core.llm.attempt import invoke_tool
from agentlab.core.ports import RunContext


class GrantedTool(BaseTool):
    def __init__(self, spec: dict[str, Any], ctx: RunContext, role: str, state: CallState) -> None:
        function = spec["function"]
        super().__init__(name=function["name"], description=function.get("description", ""))
        self._parameters = function.get("parameters")
        self._ctx, self._role, self._state = ctx, role, state

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name, description=self.description, parameters_json_schema=self._parameters,
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        call_id = tool_context.function_call_id or ""
        # The model's own argument text, so malformed JSON is reported exactly as the raw runtime does.
        arguments = self._state.arguments.get(call_id, json.dumps(args))
        value = await invoke_tool(self._ctx, self._role, call_id, self.name, arguments)
        # ADK function responses must be objects; the model adapter unwraps this before the next model call.
        return value if isinstance(value, dict) else {VALUE_KEY: value}


def granted_tools(ctx: RunContext, role: str, state: CallState) -> list[BaseTool]:
    return [GrantedTool(spec, ctx, role, state) for spec in ctx.tool_specs or []]
