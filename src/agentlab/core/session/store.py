from __future__ import annotations

from agentlab.core.conversation import Conversation, Message
from agentlab.core.ports import Store


def get_thread(store: Store, thread_id: str, project_id: str | None) -> Conversation:
    row = store.thread_record(thread_id, project_id)
    if row is None:
        raise KeyError(thread_id)
    return Conversation.model_validate(row)


def append_message(store: Store, thread_id: str, project_id: str | None, message: Message) -> Message:
    with store.lock_run("thread:" + thread_id), store.transaction():
        stored = store.append_thread_message(thread_id, project_id, message.model_dump(mode="json"))
        message.seq = stored["seq"]
    return message
