from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from agentlab.core.project_config import ProjectSettings
from agentlab.core.schemas import Strict, new_id, utcnow


class StepStatus(StrEnum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    BLOCKED = "blocked"


class ProjectStep(Strict):
    id: str = Field(default_factory=new_id)
    title: str
    acceptance: list[str] = []
    status: StepStatus = StepStatus.TODO
    run_ids: list[str] = []


class ProjectPhase(Strict):
    id: str = Field(default_factory=new_id)
    title: str
    steps: list[ProjectStep]

    @property
    def status(self) -> StepStatus:
        states = {s.status for s in self.steps}
        if states <= {StepStatus.DONE}:
            return StepStatus.DONE
        if StepStatus.BLOCKED in states:
            return StepStatus.BLOCKED
        return StepStatus.DOING if states & {StepStatus.DOING, StepStatus.DONE} else StepStatus.TODO


class Project(Strict):
    settings: ProjectSettings | None = None
    id: str = Field(default_factory=new_id)
    name: str
    goal: str
    workspace: str
    phases: list[ProjectPhase] = []
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())

    def steps(self) -> list[ProjectStep]:
        return [s for p in self.phases for s in p.steps]

    def next_step(self) -> ProjectStep | None:
        return next((s for s in self.steps() if s.status in (StepStatus.TODO, StepStatus.DOING)), None)

    def find_step(self, step_id: str) -> ProjectStep:
        return next(s for s in self.steps() if s.id == step_id)

    def progress(self) -> tuple[int, int]:
        steps = self.steps()
        return sum(s.status == StepStatus.DONE for s in steps), len(steps)


class PhasePlan(Strict):
    title: str
    steps: list[str]


class ProjectPlan(Strict):
    phases: list[PhasePlan] = Field(min_length=1)

    def to_phases(self) -> list[ProjectPhase]:
        return [ProjectPhase(title=p.title, steps=[ProjectStep(title=s) for s in p.steps]) for p in self.phases]
