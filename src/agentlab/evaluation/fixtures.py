from pathlib import Path

from agentlab.core.ports import GateAdapter
from agentlab.core.schemas import GateMode, GateResult


class InvalidFixture(RuntimeError):
    def __init__(self, result: GateResult) -> None:
        self.result = result
        super().__init__(f"baseline must fail only at test; actual={result.failed_at or 'passed'}")


async def require_test_failure(gate: GateAdapter, workspace: Path, mode: GateMode = GateMode.FULL) -> GateResult:
    result = await gate.run(workspace, mode)
    if result.passed or result.failed_at != "test":
        raise InvalidFixture(result)
    return result


def changed_files(before: dict[str, bytes], after: dict[str, bytes]) -> list[str]:
    return sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
