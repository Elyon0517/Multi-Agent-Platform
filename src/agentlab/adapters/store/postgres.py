from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from agentlab.adapters.store.memory import NotFound
from agentlab.core.ports import RunBusy
from agentlab.core.schemas import Approval, Artifact, ArtifactKind, Event, Iteration, Run, Step


class PostgresStore:
    def __init__(self, database_url: str) -> None:
        self._dsn = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        self._connection: ContextVar[psycopg.Connection[dict[str, Any]] | None] = ContextVar(
            "store_connection", default=None
        )

    def delete_project(self, project_id: str) -> None:
        with self.transaction():
            self._query("SELECT pg_advisory_xact_lock_shared(712460801)")
            rows = self._query("SELECT schema_name FROM project_schema WHERE project_id=%s FOR UPDATE", (project_id,))
            if not rows:
                raise NotFound(project_id)
            self._query("DELETE FROM run_directory WHERE project_id=%s", (project_id,))
            self._query(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(rows[0]["schema_name"])))
            self._query("DELETE FROM project_schema WHERE project_id=%s", (project_id,))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        current = self._connection.get()
        if current is not None:
            with current.transaction():
                yield
            return
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            token = self._connection.set(connection)
            try:
                with connection.transaction():
                    yield
            finally:
                self._connection.reset(token)

    @contextmanager
    def lock_run(self, run_id: str) -> Iterator[None]:
        key = int.from_bytes(hashlib.sha256(run_id.encode()).digest()[:8], signed=True)
        with psycopg.connect(self._dsn, autocommit=True) as connection:
            if not connection.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]:  # type: ignore[index]
                raise RunBusy(run_id)
            try:
                yield
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (key,))

    def _query(self, statement: Any, params: Any = (), project_id: str | None = None) -> list[dict[str, Any]]:
        with self.transaction():
            connection = self._connection.get()
            assert connection is not None
            original_row = connection.execute("SHOW search_path").fetchone()
            assert original_row is not None
            original = original_row["search_path"]
            if project_id is not None:
                from agentlab.db.isolation import provision

                base_row = connection.execute("SELECT current_schema() AS name").fetchone()
                assert base_row is not None
                base = base_row["name"]
                target = provision(connection, base, project_id)
                connection.execute(
                    sql.SQL("SET LOCAL search_path TO {}, {}").format(sql.Identifier(target), sql.Identifier(base))
                )
            try:
                cursor = connection.execute(statement, params)
                return cursor.fetchall() if cursor.description else []
            finally:
                if connection.info.transaction_status != TransactionStatus.INERROR:
                    connection.execute("SELECT set_config('search_path', %s, true)", (original,))

    def append_usage(self, data: dict[str, Any]) -> bool:
        # The connection search path is restored to base by every project query.
        columns = list(data)
        return bool(
            self._query(
                sql.SQL("INSERT INTO usage_ledger ({}) VALUES ({}) ON CONFLICT (id) DO NOTHING RETURNING id").format(
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns),
                ),
                list(data.values()),
            )
        )

    def usage_entries(self) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM usage_ledger ORDER BY ts,id")

    def usage_by_role(self) -> list[dict[str, Any]]:
        return self._query("""SELECT role,
            sum(calls) FILTER (WHERE metered) AS calls,
            sum(calls) FILTER (WHERE NOT metered) AS unmetered_calls,
            sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out,
            sum(tokens_in + tokens_out) AS total_tokens, sum(cost_cents) AS cost_cents,
            array_agg(DISTINCT model ORDER BY model) FILTER (WHERE model <> '') AS models
            FROM usage_ledger WHERE role <> 'arbiter' GROUP BY role""")

    def usage_recorded(self, call_id: str, source: str, ref_id: str) -> bool:
        return bool(
            self._query(
                """SELECT 1 FROM usage_ledger WHERE id IN (%s,%s)
            OR (source=%s AND ref_id=%s AND id IN (%s,%s)) LIMIT 1""",
                (
                    "call-" + call_id,
                    "legacy-attempt-" + call_id,
                    source,
                    ref_id,
                    "legacy-turn-" + ref_id,
                    "legacy-planning-" + ref_id,
                ),
            )
        )

    def _owner(self, run_id: str) -> str:
        rows = self._query("SELECT project_id FROM run_directory WHERE run_id=%s", (run_id,))
        if not rows:
            raise NotFound(run_id)
        return str(rows[0]["project_id"])

    def _run_query(self, statement: Any, params: Any) -> list[dict[str, Any]]:
        return self._query(statement, params, self._owner(params[0]))

    def _schemas(self) -> list[str]:
        return [row["project_id"] for row in self._query("SELECT project_id FROM project_schema ORDER BY project_id")]

    def _record_owner(self, kind: str, key: str, data: dict[str, Any]) -> str | None:
        if kind == "project":
            return key
        if data.get("project_id"):
            return str(data["project_id"])
        run_id = data.get("run_id") or (key if kind.startswith("dispatch_") else None)
        if run_id:
            return self._owner(str(run_id))
        if data.get("planning_id"):
            for item in self.records("planning"):
                if item.get("id") == data["planning_id"]:
                    return str(item["project_id"])
            raise NotFound(str(data["planning_id"]))
        return None

    def _upsert(self, table: str, data: dict[str, Any]) -> None:
        columns = list(data)
        keys = ["run_id", "seq"] if table == "event" else ["id"]
        statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}").format(
            sql.Identifier(table),
            sql.SQL(",").join(map(sql.Identifier, columns)),
            sql.SQL(",").join(sql.Placeholder() for _ in columns),
            sql.SQL(",").join(map(sql.Identifier, keys)),
            sql.SQL(",").join(
                sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(k), sql.Identifier(k)) for k in columns if k not in keys
            ),
        )
        self._query(
            statement,
            [Jsonb(v) if isinstance(v, (dict, list)) else v for v in data.values()],
            self._record_owner(table, str(data.get("id", "")), data),
        )

    def _save(self, table: str, model: BaseModel) -> None:
        data = model.model_dump(mode="json")
        if table == "step":
            data.update(data.pop("usage"))
        self._upsert(table, data)

    def create_run(self, run: Run) -> Run:
        with self.transaction():
            self._query("SELECT 1", project_id=run.project_id)
            self._query("INSERT INTO run_directory VALUES (%s,%s)", (run.id, run.project_id))
            self._save("run", run)
        return run

    def get_run(self, run_id: str) -> Run:
        rows = self._run_query("SELECT * FROM run WHERE id=%s", (run_id,))
        if not rows:
            raise NotFound(run_id)
        return Run.model_validate(rows[0])

    def save_run(self, run: Run) -> None:
        if self._owner(run.id) != run.project_id:
            raise ValueError("run project ownership cannot change")
        self._save("run", run)

    def list_runs(self) -> list[Run]:
        rows = [row for pid in self._schemas() for row in self._query("SELECT * FROM run", project_id=pid)]
        return sorted((Run.model_validate(row) for row in rows), key=lambda run: (run.created_at, run.id), reverse=True)

    def add_iteration(self, it: Iteration) -> None:
        self._save("iteration", it)

    def save_iteration(self, it: Iteration) -> None:
        self._save("iteration", it)

    def iterations(self, run_id: str) -> list[Iteration]:
        return [
            Iteration.model_validate(row)
            for row in self._run_query("SELECT * FROM iteration WHERE run_id=%s ORDER BY n", (run_id,))
        ]

    def add_step(self, step: Step) -> None:
        self._save("step", step)

    def steps(self, run_id: str) -> list[Step]:
        items = self._run_query("SELECT * FROM step WHERE run_id=%s ORDER BY ordinal", (run_id,))
        for item in items:
            item.pop("tool_calls")
            item.pop("ordinal")
            item["usage"] = {key: item.pop(key) for key in ("tokens_in", "tokens_out", "cost_cents")}
        return [Step.model_validate(item) for item in items]

    def add_artifact(self, artifact: Artifact) -> None:
        self._save("artifact", artifact)

    def artifacts(self, run_id: str, kind: ArtifactKind | None = None) -> list[Artifact]:
        rows = self._run_query(
            "SELECT * FROM artifact WHERE run_id=%s AND (%s::text IS NULL OR kind=%s) ORDER BY ordinal",
            (run_id, kind, kind),
        )
        return [Artifact.model_validate({k: v for k, v in row.items() if k != "ordinal"}) for row in rows]

    def create_approval(self, approval: Approval) -> None:
        self._save("approval", approval)

    def pending_approval(self, run_id: str) -> Approval | None:
        rows = self._run_query(
            "SELECT * FROM approval WHERE run_id=%s AND status='pending' ORDER BY ordinal DESC LIMIT 1", (run_id,)
        )
        return Approval.model_validate({k: v for k, v in rows[0].items() if k != "ordinal"}) if rows else None

    def save_approval(self, approval: Approval) -> None:
        self._save("approval", approval)

    def append_event(self, event: Event) -> Event:
        with self.transaction():
            self._run_query("SELECT id FROM run WHERE id=%s FOR UPDATE", (event.run_id,))
            row = self._run_query("SELECT COALESCE(MAX(seq),0)+1 AS seq FROM event WHERE run_id=%s", (event.run_id,))[0]
            stored = event.model_copy(update={"seq": row["seq"]})
            self._save("event", stored)
            return stored

    def events(self, run_id: str, after_seq: int = 0) -> list[Event]:
        return [
            Event.model_validate(row)
            for row in self._run_query(
                "SELECT * FROM event WHERE run_id=%s AND seq>%s ORDER BY seq", (run_id, after_seq)
            )
        ]

    def save_checkpoint(self, run_id: str, data: dict[str, Any]) -> None:
        self._run_query(
            "INSERT INTO run_checkpoint(run_id,data) VALUES (%s,%s) ON CONFLICT(run_id) DO UPDATE "
            "SET data=EXCLUDED.data,updated_at=now()",
            (run_id, Jsonb(data)),
        )

    def checkpoint(self, run_id: str) -> dict[str, Any] | None:
        rows = self._run_query("SELECT data FROM run_checkpoint WHERE run_id=%s", (run_id,))
        return rows[0]["data"] if rows else None

    def put_record(self, kind: str, key: str, data: dict[str, Any]) -> None:
        if kind == "thread":
            with self.transaction():
                metadata = {k: v for k, v in data.items() if k != "messages"}
                self._upsert("thread", {"id": key, "project_id": data.get("project_id"), "payload": metadata})
                for seq, message in enumerate(data.get("messages", []), 1):
                    self._upsert(
                        "message",
                        {
                            "id": message["id"],
                            "thread_id": key,
                            "project_id": data.get("project_id"),
                            "seq": seq,
                            "author": message["author"],
                            "payload": {**message, "seq": seq},
                        },
                    )
        elif kind == "root_turn":
            self._upsert(
                "root_turn",
                {"id": key, "thread_id": data["thread_id"], "project_id": data.get("project_id"), "payload": data},
            )
        elif kind == "project":
            self._upsert(
                "project",
                {
                    "id": key,
                    "name": data["name"],
                    "goal": data["goal"],
                    "workspace_path": data["workspace"],
                    "phases": data["phases"],
                    "payload": data,
                },
            )
        elif kind == "memory":
            self._upsert(
                "memory",
                {
                    k: data[k]
                    for k in (
                        "id",
                        "project_id",
                        "namespace",
                        "kind",
                        "text",
                        "source",
                        "source_run_id",
                        "pinned",
                        "valid_to",
                        "superseded_by",
                    )
                }
                | {
                    "payload": data,
                    "embedding_model": data.get("embedding_model"),
                    "embedding_version": data.get("embedding_version"),
                },
            )
        else:
            self._query(
                "INSERT INTO state_record(kind,key,data) VALUES (%s,%s,%s) ON CONFLICT(kind,key) "
                "DO UPDATE SET data=EXCLUDED.data,updated_at=now()",
                (kind, key, Jsonb(data)),
                self._record_owner(kind, key, data),
            )

    def thread_record(self, thread_id: str, project_id: str | None) -> dict[str, Any] | None:
        rows = self._query("SELECT payload FROM thread WHERE id=%s", (thread_id,), project_id=project_id)
        if not rows or rows[0]["payload"].get("project_id") != project_id:
            return None
        data: dict[str, Any] = rows[0]["payload"]
        data["messages"] = [
            row["payload"]
            for row in self._query(
                "SELECT payload FROM message WHERE thread_id=%s ORDER BY seq", (thread_id,), project_id=project_id
            )
        ]
        return data

    def append_thread_message(self, thread_id: str, project_id: str | None, data: dict[str, Any]) -> dict[str, Any]:
        rows = self._query("SELECT payload FROM thread WHERE id=%s FOR UPDATE", (thread_id,), project_id=project_id)
        if not rows or rows[0]["payload"].get("project_id") != project_id:
            raise KeyError(thread_id)
        seq = self._query(
            "SELECT COALESCE(MAX(seq),0)+1 AS seq FROM message WHERE thread_id=%s", (thread_id,), project_id=project_id
        )[0]["seq"]
        if seq > 1000:
            raise ValueError("conversation is full")
        data = {**data, "seq": seq}
        self._query(
            "INSERT INTO message(id,thread_id,project_id,seq,author,payload) VALUES (%s,%s,%s,%s,%s,%s)",
            (data["id"], thread_id, project_id, seq, data["author"], Jsonb(data)),
            project_id=project_id,
        )
        return data

    def records(self, kind: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        scopes: list[str | None] = [None, *self._schemas()]
        for pid in scopes:
            if kind in {"thread", "root_turn"}:
                found = self._query(
                    sql.SQL("SELECT payload AS data FROM {} ORDER BY id").format(sql.Identifier(kind)), project_id=pid
                )
                if kind == "thread":
                    for item in found:
                        item["data"]["messages"] = [
                            r["payload"]
                            for r in self._query(
                                "SELECT payload FROM message WHERE thread_id=%s ORDER BY seq",
                                (item["data"]["id"],),
                                project_id=pid,
                            )
                        ]
                rows.extend(found)
            elif kind in {"project", "memory"}:
                rows.extend(
                    self._query(
                        sql.SQL("SELECT payload AS data FROM {} WHERE payload IS NOT NULL ORDER BY id").format(
                            sql.Identifier(kind)
                        ),
                        project_id=pid,
                    )
                )
            else:
                rows.extend(
                    self._query(
                        "SELECT data FROM state_record WHERE kind=%s ORDER BY updated_at,key", (kind,), project_id=pid
                    )
                )
        return [row["data"] for row in rows]
