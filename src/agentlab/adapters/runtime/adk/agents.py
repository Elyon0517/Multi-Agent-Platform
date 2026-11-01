"""Role → ADK LlmAgent, built from the existing agent config. No ADK-specific configuration."""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.tools.base_tool import BaseTool


def agent_name(role: str) -> str:
    return role.replace("-", "_")


def build_agent(role: str, model: BaseLlm, prompt: str, tools: list[BaseTool]) -> LlmAgent:
    # An instruction provider bypasses ADK's {state} templating; prompts contain literal JSON braces.
    return LlmAgent(name=agent_name(role), model=model, instruction=lambda _ctx: prompt, tools=list(tools))
