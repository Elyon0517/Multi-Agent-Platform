"""Role → ADK LlmAgent, built from the existing agent config. No ADK-specific configuration."""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.genai import types

# ADK needs a new message to start an invocation. Each role's real input is a branch-scoped event,
# so this shared placeholder is stripped before any model request is built.
KICKOFF = "agentlab:start"


def kickoff() -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=KICKOFF)])


def _is_kickoff(content: types.Content) -> bool:
    return content.role == "user" and [p.text for p in content.parts or []] == [KICKOFF]


def _strip_kickoff(callback_context: CallbackContext, llm_request: LlmRequest) -> LlmResponse | None:
    llm_request.contents = [c for c in llm_request.contents if not _is_kickoff(c)]
    return None


def agent_name(role: str) -> str:
    return role.replace("-", "_")


def build_agent(role: str, model: BaseLlm, prompt: str, tools: list[BaseTool]) -> LlmAgent:
    # An instruction provider bypasses ADK's {state} templating; prompts contain literal JSON braces.
    return LlmAgent(name=agent_name(role), model=model, instruction=lambda _ctx: prompt, tools=list(tools),
                    before_model_callback=_strip_kickoff)
