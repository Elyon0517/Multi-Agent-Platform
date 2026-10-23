"""Durable, content-conditional file writes shared by Coder deliveries and tools."""

from __future__ import annotations

import hashlib
from typing import Literal

from agentlab.core.ports import BlobStore, EditConflict, Store, Workspace
from agentlab.core.schemas import FileEdit, Run, Strict


class EditFile(Strict):
    path: str
    before_hash: str | None
    after_hash: str
    content_ref: str
    status: Literal["pending", "applied", "conflict"] = "pending"
    observed_hash: str | None = None


class EditOperation(Strict):
    id: str
    run_id: str
    project_id: str
    scope_id: str
    sequence: int
    source: Literal["coder_output", "workspace_write"]
    files: list[EditFile]
    status: Literal["pending", "applied", "conflict"] = "pending"


class EditJournal:
    def __init__(self, store: Store, blobs: BlobStore, workspace: Workspace) -> None:
        self.store, self.blobs, self.workspace = store, blobs, workspace

    def _operations(self, run: Run, scope_id: str) -> list[EditOperation]:
        return sorted((EditOperation.model_validate(row) for row in self.store.records("edit_operation")
                       if row["run_id"] == run.id and row["scope_id"] == scope_id), key=lambda op: op.sequence)

    def _save(self, op: EditOperation) -> None:
        op.status = ("conflict" if any(f.status == "conflict" for f in op.files) else
                     "applied" if all(f.status == "applied" for f in op.files) else "pending")
        self.store.put_record("edit_operation", op.id, op.model_dump(mode="json"))

    def _observe(self, path: str) -> str | None:
        try:
            return self.workspace.file_hash(path)
        except OSError:
            # A deleted/replaced parent, inaccessible file or changed symlink cannot authorize a write.
            return "unreadable"

    def recover(self, run: Run, scope_id: str) -> None:
        operations = self._operations(run, scope_id)
        # Later intentional writes supersede earlier writes to the same path. Only each
        # path's latest intent is replayable; never restore an older version over it.
        heads = {f.path: (op, f) for op in operations for f in op.files}
        conflicts = []
        for op, entry in heads.values():
            entry.observed_hash = self._observe(entry.path)
            entry.status = ("applied" if entry.observed_hash == entry.after_hash else
                            "pending" if entry.observed_hash == entry.before_hash else "conflict")
            if entry.status == "conflict":
                conflicts.append((op.id, entry.path))
        for op in operations:
            self._save(op)
        self.workspace.remember_edits([entry.path for _, entry in heads.values() if entry.status == "applied"])
        if conflicts:
            raise EditConflict(conflicts[0][0], [path for _, path in conflicts])
        for op, entry in heads.values():
            if entry.status != "pending":
                continue
            content = self.blobs.get(entry.content_ref)
            if hashlib.sha256(content.encode()).hexdigest() != entry.after_hash:
                raise ValueError("recorded edit content hash mismatch")
            try:
                self.workspace.apply_edits([FileEdit(path=entry.path, content=content)],
                                           expected_hashes={entry.path: entry.before_hash})
            except EditConflict as exc:
                entry.status = "conflict"
                entry.observed_hash = self._observe(entry.path)
                self._save(op)
                raise EditConflict(op.id, [entry.path]) from exc
            entry.status, entry.observed_hash = "applied", entry.after_hash
            self._save(op)

    def apply(
        self, run: Run, scope_id: str, action_id: str, edits: list[FileEdit], baseline: dict[str, str],
        source: Literal["coder_output", "workspace_write"],
    ) -> list[str]:
        edits = self.workspace.validate_edits(edits)
        operation_id = hashlib.sha256(f"{run.id}:{scope_id}:{action_id}".encode()).hexdigest()
        operations = self._operations(run, scope_id)
        existing = next((op for op in operations if op.id == operation_id), None)
        if existing:
            expected = [(f.path, f.after_hash) for f in existing.files]
            actual = [(e.path, hashlib.sha256(e.content.encode()).hexdigest()) for e in edits]
            if actual != expected:
                raise EditConflict(operation_id, [e.path for e in edits])
        else:
            # Check/recover prior tool writes before accepting another write in this Coder execution.
            self.recover(run, scope_id)
            previous = {f.path: f.after_hash for op in operations for f in op.files}
            entries = [EditFile(
                path=e.path, before_hash=previous.get(e.path, baseline.get(e.path)),
                after_hash=hashlib.sha256(e.content.encode()).hexdigest(), content_ref=self.blobs.put(e.content)[0],
            ) for e in edits]
            if entries:
                self._save(EditOperation(
                    id=operation_id, run_id=run.id, project_id=run.project_id, scope_id=scope_id,
                    sequence=max((op.sequence for op in operations), default=0) + 1, source=source, files=entries,
                ))
        # The complete intent is committed before the first file is touched. Even an
        # "applied" record must be rechecked against disk after process recovery.
        self.recover(run, scope_id)
        return [e.path for e in edits]
