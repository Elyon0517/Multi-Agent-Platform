from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from agentlab.core.schemas import Strict, new_id, utcnow


class Source(Strict):
    kind: Literal["file", "memory", "web"]
    ref: str
    title: str = ""


class RootTurn(Strict):
    intent: Literal["answer", "clarify", "task"]
    reply: str = Field(min_length=1, max_length=20000)
    sources: list[Source] = []
    task: str | None = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def valid_task(self) -> RootTurn:
        if self.intent == "task" and (not self.task or not self.task.strip()):
            raise ValueError("task intent requires a task")
        if self.intent != "task" and self.task is not None:
            raise ValueError("task only applies to task intent")
        return self


class Message(Strict):
    id: str = Field(default_factory=new_id)
    author: Literal["user", "assistant", "system"]
    seq: int = 0
    kind: str = "text"
    turn_id: str | None = None
    sources: list[Source] = []
    payload: dict[str, object] = {}
    text: str = Field(min_length=1, max_length=20000)
    run_id: str | None = None
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())


class Conversation(Strict):
    id: str = Field(default_factory=new_id)
    project_id: str | None
    title: str = Field(min_length=1, max_length=120)
    messages: list[Message] = Field(default_factory=list, max_length=1000)
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())
