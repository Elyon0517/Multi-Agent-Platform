from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from agentlab.adapters.runtime.fake import FakeRuntime
from agentlab.adapters.runtime.raw import RawRuntime
from agentlab.bootstrap import build_services
from agentlab.core.conversation import Conversation, RootTurn
from agentlab.core.llm.structured import Completion, StructuredCaller
from agentlab.core.schemas import CoderOutput, FileEdit, Plan, RunStatus
from agentlab.core.session.service import SessionService
from agentlab.demo import demo_scripts, seed_demo_workspace
from agentlab.settings import Settings


def scorecard(run_id: str, checks: list[dict[str, Any]], blind_spots: int = 0) -> dict[str, Any]:
    hard = sum(not c["passed"] and c["severity"] == "hard" for c in checks)
    soft = sum(not c["passed"] and c["severity"] == "soft" for c in checks)
    return {
        "run_id": run_id,
        "passed": hard == 0,
        "verdict": "PASS" if hard == 0 else "FAIL",
        "score": sum(c["passed"] for c in checks),
        "total": len(checks),
        "hard_error_count": hard,
        "soft_warning_count": soft,
        "blind_spot_count": blind_spots,
        "categories": {c["name"]: c["passed"] for c in checks},
        "checks": checks,
    }


def check(name: str, passed: bool, detail: str, source: str = "runtime", severity: str = "hard") -> dict[str, Any]:
    return {"name": name, "passed": passed, "severity": severity, "gate": name, "source_type": source, "detail": detail}


async def evaluate(manifest: Path, runtime: str = "fake") -> dict[str, Any]:
    data = json.loads(manifest.read_text())
    cards = []
    eval_dir = Settings().data_dir.resolve() / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agentlab-eval-", dir=eval_dir) as temp:
        root = Path(temp)
        svc = build_services(
            Settings(
                store_backend="memory",
                data_dir=root / "state",
                runtime=runtime,
                sandbox="local" if runtime == "fake" else "docker",
            )
        )
        for task in data["tasks"]:
            workspace = root / task["id"]
            shutil.copytree(manifest.parent / "tasks" / task["id"], workspace)
            original_test = (workspace / "test_calc.py").read_bytes()
            driver = svc.driver(workspace, runtime, "python")
            if runtime == "fake":
                scripts = demo_scripts()
                scripts["planner"] = lambda inp: Plan(
                    summary=inp.goal, steps=["Fix implementation"], acceptance_criteria=["Tests pass unchanged"]
                )
                solution = task["solution"]

                def coder(inp: Any, solution: str = solution) -> CoderOutput:
                    return CoderOutput(edits=[FileEdit(path="calc.py", content=solution)])

                scripts["coder"] = coder
                driver.runtime = FakeRuntime(scripts)
            try:
                await driver.workspace.ensure_repo()  # type: ignore[attr-defined]
                run = await driver.create_async(task["goal"])
                run = await driver.run(run.id)
                checks = [
                    check(
                        "signoff",
                        run.status == RunStatus.WAITING_HUMAN and run.paused_reason == "signoff",
                        f"{run.status}/{run.paused_reason}",
                    ),
                    check(
                        "tests_preserved",
                        (workspace / "test_calc.py").read_bytes() == original_test,
                        "Original test bytes",
                        "workspace",
                    ),
                    check("budget", run.cost_cents <= run.budget_cents, f"{run.cost_cents:.3f}c"),
                    check(
                        "review_panel",
                        len([s for s in svc.store.steps(run.id) if s.role in svc.cfg.reviewer_roles]) >= 3,
                        "Three reviewers",
                    ),
                    check(
                        "gate",
                        bool(svc.store.events(run.id))
                        and any(
                            e.type == "gate.finished" and e.payload.get("passed") for e in svc.store.events(run.id)
                        ),
                        "Objective tests",
                        "gate",
                    ),
                ]
                cards.append(scorecard(task["id"], checks, int(runtime == "fake")))
            except Exception as exc:
                cards.append(scorecard(task["id"], [check("execution", False, type(exc).__name__)]))
            finally:
                driver.workspace.close()  # type: ignore[attr-defined]
        for case in data["conversations"]:
            project = svc.projects.create(
                case["id"], "Conversation evaluation", str(seed_demo_workspace(root / case["id"]))
            )
            thread = Conversation(project_id=project.id, title=case["id"])
            svc.store.put_record("thread", thread.id, thread.model_dump(mode="json"))
            if case["id"] == "root-document":
                await svc.knowledge.ingest("design.md", b"Python is the project implementation language", project.id)
                case = {
                    **case,
                    "sources": [{"kind": "memory", "ref": svc.knowledge.memory.items_in("project", project.id)[0].id}],
                }
            original_runtime = svc.runtime
            if runtime == "fake":
                completions = []
                if case.get("tool"):
                    completions.append(
                        Completion(
                            "",
                            10,
                            5,
                            [
                                {
                                    "id": "fixture",
                                    "type": "function",
                                    "function": {"name": case["tool"], "arguments": json.dumps(case["arguments"])},
                                }
                            ],
                        )
                    )
                turn = RootTurn(
                    intent=case["intent"], reply=case["reply"], sources=case.get("sources", []), task=case.get("task")
                )
                completions.append(Completion(turn.model_dump_json(), 10, 5))

                async def fake_chat(completions: list[Completion] = completions, **kwargs: Any) -> Completion:
                    return completions.pop(0)

                fake = object.__new__(RawRuntime)
                fake._caller = StructuredCaller(svc.cfg, fake_chat)

                def fake_runtime(name: str | None = None, cfg: Any = None, fake: RawRuntime = fake) -> RawRuntime:
                    return fake

                svc.runtime = fake_runtime  # type: ignore[method-assign]
            try:
                turn, turn_id = await SessionService(svc).answer(project.id, thread.id, case["text"])
                record = next(r for r in svc.store.records("root_turn") if r["id"] == turn_id)
                svc.runtime = original_runtime  # type: ignore[method-assign]
                dispatched = None
                if turn.intent == "task":
                    from agentlab.run_service import CreateRun, create_run_service

                    dispatched, task_driver = await create_run_service(
                        svc,
                        CreateRun(
                            project_id=project.id, thread_id=thread.id, goal=turn.task or case["text"], runtime=runtime
                        ),
                        record_user=False,
                    )
                    try:
                        dispatched = await task_driver.run(dispatched.id)
                    finally:
                        task_driver.workspace.close()  # type: ignore[attr-defined]
                task_messages = next(t for t in svc.store.records("thread") if t["id"] == thread.id)["messages"]

                cards.append(
                    scorecard(
                        case["id"],
                        [
                            check("intent", turn.intent == case["intent"], turn.intent),
                            check("reply", bool(turn.reply), turn.reply),
                            check("sources", not case.get("sources") or bool(turn.sources), "Source references"),
                            check(
                                "no_run_for_answer",
                                bool(dispatched)
                                if turn.intent == "task"
                                else all(r.thread_id != thread.id for r in svc.store.list_runs()),
                                "Task dispatch uses the shared run service",
                            ),
                            check(
                                "task_progress_and_approval",
                                turn.intent != "task"
                                or (
                                    any(m.get("kind") == "progress" for m in task_messages)
                                    and any(m.get("kind") == "approval" for m in task_messages)
                                ),
                                "Conversation progress and inline approval",
                            ),
                            check("replay", bool(record["attempts"]), "Prompt/response blobs"),
                        ],
                        int(runtime == "fake"),
                    )
                )
            finally:
                svc.runtime = original_runtime  # type: ignore[method-assign]
    checks = [check(card["run_id"], card["passed"], card["verdict"], "scorecard") for card in cards]
    return {
        **scorecard("baseline", checks, sum(c["blind_spot_count"] for c in cards)),
        "runtime": runtime,
        "scorecards": cards,
    }
