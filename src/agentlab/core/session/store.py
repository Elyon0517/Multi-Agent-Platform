from __future__ import annotations

from agentlab.core.conversation import Conversation, Message
from agentlab.core.ports import Store


def get_thread(store: Store, thread_id: str, project_id: str | None) -> Conversation:
    for row in store.records("thread"):
        if row["id"] == thread_id and row["project_id"] == project_id:
            return Conversation.model_validate(row)
    raise KeyError(thread_id)


def append_message(store: Store, thread_id: str, project_id: str | None, message: Message) -> Message:
    with store.lock_run("thread:" + thread_id), store.transaction():
        thread = get_thread(store, thread_id, project_id)
        if len(thread.messages) >= 1000:
            raise ValueError("conversation is full")
        message.seq = len(thread.messages) + 1
        thread.messages.append(message)
        store.put_record("thread", thread.id, thread.model_dump(mode="json"))
    return message
