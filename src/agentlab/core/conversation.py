from __future__ import annotations

from pydantic import Field

from agentlab.core.schemas import Strict, new_id, utcnow


class Message(Strict):
    id: str = Field(default_factory=new_id)
    author: str
    text: str = Field(min_length=1, max_length=20000)
    run_id: str | None = None
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())


class Conversation(Strict):
    id: str = Field(default_factory=new_id)
    project_id: str
    title: str = Field(min_length=1, max_length=120)
    messages: list[Message] = Field(default_factory=list, max_length=1000)
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())
