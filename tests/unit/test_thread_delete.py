from pathlib import Path

from fastapi.testclient import TestClient

from agentlab.api.app import create_app
from tests.unit.test_memory_project import _svc


def test_delete_conversation_refuses_active_runs_and_keeps_finished_history(tmp_path: Path):
    from agentlab.core.conversation import Conversation
    from agentlab.core.schemas import Run, RunStatus

    svc = _svc(tmp_path)
    thread = Conversation(project_id=None, title="chat")
    svc.store.put_record("thread", thread.id, thread.model_dump(mode="json"))
    active = Run(goal="busy", workspace=str(tmp_path), thread_id=thread.id)
    svc.store.create_run(active)
    with TestClient(create_app(svc)) as client:
        assert client.delete(f"/threads/{thread.id}").status_code == 409
        active.status = RunStatus.DONE
        svc.store.save_run(active)
        assert client.delete(f"/projects/someone-else/threads/{thread.id}").status_code == 404
        assert client.delete(f"/threads/{thread.id}").json() == {"deleted": True}
        assert client.delete(f"/threads/{thread.id}").status_code == 404
    assert svc.store.get_run(active.id).thread_id is None
