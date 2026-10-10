from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentlab.adapters.events import InProcessEventBus
from agentlab.adapters.gates.config_gate import ConfigGate, resolve_gate
from agentlab.adapters.runtime.fake import FakeRuntime
from agentlab.adapters.runtime.raw import OpenAICompatEmbedder
from agentlab.adapters.sandbox.docker import DockerSandbox
from agentlab.adapters.sandbox.local import LocalSandbox
from agentlab.adapters.store.blobs import FileBlobStore
from agentlab.adapters.store.memory import InMemoryStore
from agentlab.adapters.workspace import GitWorkspace
from agentlab.core.config import AppConfig, GateCfg, load_config
from agentlab.core.loop.driver import Driver
from agentlab.core.memory.store import InMemoryMemoryStore, PersistentMemoryStore
from agentlab.core.ports import AgentRuntime, Sandbox, Store
from agentlab.secrets import EnvFile, SettingView, views
from agentlab.services import KnowledgeService, MemoryHooks, ProjectService
from agentlab.settings import Settings


class MissingGatewayConfig(RuntimeError):
    pass


def gateway_creds(env: EnvFile, settings: Settings) -> tuple[str | None, str | None]:
    values = env.read()
    return (
        values.get("AGENTLAB_LLM_BASE_URL") or settings.llm_base_url,
        values.get("AGENTLAB_LLM_API_KEY") or settings.llm_api_key,
    )


@dataclass
class Services:
    settings: Settings
    cfg: AppConfig
    store: Store
    blobs: FileBlobStore
    bus: InProcessEventBus
    env: EnvFile
    knowledge: KnowledgeService
    projects: ProjectService
    hooks: MemoryHooks = field(init=False)

    def __post_init__(self) -> None:
        self.hooks = MemoryHooks(self.knowledge, self.projects)
        self.hooks.session_services = self
        self.bus.listeners.append(self.hooks.on_event)

    def delete_project(self, project_id: str) -> list[str]:
        import shutil
        from contextlib import ExitStack

        from agentlab.core.ports import RunBusy

        with ExitStack() as locks:
            locks.enter_context(self.store.lock_run("project:" + project_id))
            self.projects.get(project_id)
            runs = [r for r in self.store.list_runs() if r.project_id == project_id]
            for run in runs:
                locks.enter_context(self.store.lock_run(run.id))
                locks.enter_context(self.store.lock_run("finishing:" + run.id))
                locks.enter_context(self.store.lock_run("summarizer:" + run.id))
            if any(r.status not in {"DONE", "CANCELLED"} for r in runs):
                raise RunBusy("project has unfinished runs")
            threads = [t["id"] for t in self.store.records("thread") if t.get("project_id") == project_id]
            for thread in threads:
                locks.enter_context(self.store.lock_run("turn:" + thread))
                locks.enter_context(self.store.lock_run("thread:" + thread))
            snapshots = []
            for run in runs:
                checkpoint = self.store.checkpoint(run.id) or {}
                snapshot = checkpoint.get("workspace", {}).get("snapshot_dir")
                if snapshot:
                    path = Path(snapshot).resolve()
                    root = (self.settings.data_dir / "snapshots").resolve()
                    if path.is_relative_to(root) and path != root:
                        snapshots.append(path)
            # Content-addressed blobs may be shared, including Root turn and failed-call refs.
            def references(value: Any) -> set[str]:
                if isinstance(value, str):
                    return {value} if value.startswith("blob://") else set()
                if isinstance(value, dict):
                    return set().union(*(references(child) for child in value.values()))
                if isinstance(value, list):
                    return set().union(*(references(child) for child in value))
                return set()

            owned: set[str] = set()
            other: set[str] = set()
            run_owners = {r.id: r.project_id for r in self.store.list_runs()}
            for identifier, owner in run_owners.items():
                target = owned if owner == project_id else other
                target.update(references(self.store.checkpoint(identifier)))
                for row in [*self.store.artifacts(identifier), *self.store.steps(identifier),
                            *self.store.events(identifier), *self.store.iterations(identifier)]:
                    target.update(references(row.model_dump(mode="json")))
            planning_owners = {a.get("id"): a.get("project_id") for a in self.store.records("planning")}
            for kind in ("root_turn", "thread", "attempt", "planning", "planning_call", "summarization",
                         "summarizer_call"):
                for data in self.store.records(kind):
                    record_owner = data.get("project_id") or run_owners.get(data.get("run_id", ""))
                    record_owner = record_owner or planning_owners.get(data.get("planning_id"))
                    (owned if record_owner == project_id else other).update(references(data))
            self.store.delete_project(project_id)
            memory = self.knowledge.memory
            memory._items = {key: item for key, item in memory._items.items() if item.project_id != project_id}
            if isinstance(memory, PersistentMemoryStore):
                memory._persisted = {key: value for key, value in memory._persisted.items() if key in memory._items}
            self.projects._projects.pop(project_id, None)
            self.projects.planning_attempts = [a for a in self.projects.planning_attempts
                                              if a.get("project_id") != project_id]
            for identifier in [*(r.id for r in runs), *("thread:" + t for t in threads)]:
                self.bus.forget(identifier)
            for path in snapshots:
                shutil.rmtree(path, ignore_errors=True)
            for ref in owned - other:
                sha = ref.removeprefix("blob://")
                if len(sha) == 64 and all(c in "0123456789abcdef" for c in sha):
                    (self.blobs._root / sha[:2] / sha).unlink(missing_ok=True)
            return [r.id for r in runs]

    def gateway(self) -> tuple[str | None, str | None]:
        return gateway_creds(self.env, self.settings)

    def anthropic_gateway(self, cfg: AppConfig | None = None) -> tuple[str | None, str | None]:
        gateway = (cfg or self.cfg).models.providers.get("anthropic")
        values = self.env.read()
        return (
            values.get(gateway.base_url_env if gateway else "AGENTLAB_ANTHROPIC_BASE_URL")
            or self.settings.anthropic_base_url,
            values.get(gateway.api_key_env if gateway else "AGENTLAB_ANTHROPIC_API_KEY")
            or self.settings.anthropic_api_key,
        )

    def workspace_secrets(self) -> tuple[str, ...]:
        return tuple(
            v
            for v in (self.gateway()[1], self.anthropic_gateway()[1], self.env.read().get("AGENTLAB_EMBEDDING_API_KEY"))
            if v
        )

    def setting_views(self) -> list[SettingView]:
        url, key = self.gateway()
        return views(
            {
                "AGENTLAB_LLM_BASE_URL": url,
                "AGENTLAB_LLM_API_KEY": key,
                "AGENTLAB_EMBEDDING_BASE_URL": self.env.read().get("AGENTLAB_EMBEDDING_BASE_URL"),
                "AGENTLAB_EMBEDDING_API_KEY": self.env.read().get("AGENTLAB_EMBEDDING_API_KEY"),
                "AGENTLAB_ANTHROPIC_BASE_URL": self.anthropic_gateway()[0],
                "AGENTLAB_ANTHROPIC_API_KEY": self.anthropic_gateway()[1],
            }
        )

    def runtime(self, name: str | None = None, cfg: AppConfig | None = None) -> AgentRuntime:
        cfg = cfg or self.cfg
        name = name or self.settings.runtime
        if name == "fake":
            from agentlab.demo import demo_scripts

            return FakeRuntime(demo_scripts())
        url, key = self.gateway()
        if not url or not key:
            raise MissingGatewayConfig("set AGENTLAB_LLM_BASE_URL and AGENTLAB_LLM_API_KEY (Settings tab or .env)")
        if name == "adk":
            from agentlab.adapters.runtime.adk import AdkRuntime

            return AdkRuntime(cfg, url, key)
        from agentlab.adapters.runtime.raw import RawRuntime

        return RawRuntime(cfg, url, key, self.anthropic_gateway(cfg))

    def sandbox(self) -> Sandbox:
        if self.settings.sandbox == "docker":
            return DockerSandbox(default_image="python:3.12-slim")
        return LocalSandbox()

    def gates(self) -> list[ConfigGate]:
        sandbox = self.sandbox()
        return [ConfigGate(g, sandbox, lambda text: self.blobs.put(text)[0]) for g in self.cfg.gates.values()]

    def driver(
        self, workspace: Path, runtime: str | None = None, language: str | None = None, project_id: str | None = None
    ) -> Driver:
        cfg = self.cfg.model_copy(update={"frozen_prompts": {r: self.cfg.prompt(r) for r in self.cfg.agents}})
        project = self.projects.get(project_id) if project_id else None
        if project and project.settings:
            from agentlab.core.project_config import project_config

            cfg = project_config(cfg, project.settings)
        ws = GitWorkspace(
            workspace,
            secrets=self.workspace_secrets(),
            snapshot_dir=self.settings.data_dir.resolve() / "snapshots" / uuid4().hex,
        )
        if (runtime or self.settings.runtime) == "fake":
            from agentlab.demo import demo_gate_cfg

            gate = ConfigGate(demo_gate_cfg(), LocalSandbox())
        else:
            gate = resolve_gate(self.gates(), ws.root, language)
        driver = Driver(cfg, self.store, self.blobs, self.bus, self.runtime(runtime, cfg), gate, ws, self.hooks)
        driver.recovery_options = {
            "runtime": runtime or self.settings.runtime,
            "sandbox": self.settings.sandbox,
            "gate": gate.cfg.model_dump(mode="json"),
            "project_settings": project.settings.model_dump(mode="json") if project and project.settings else None,
        }
        driver.runtime_factory = lambda: self.runtime(runtime, driver.cfg)
        return driver

    def restore_driver(self, run_id: str) -> Driver:
        run = self.store.get_run(run_id)
        data = self.store.checkpoint(run_id)
        if not data or not data.get("workspace"):
            raise ValueError("run has no recovery checkpoint")
        cfg = AppConfig.model_validate(data["config"])
        options = data["options"]
        workspace = GitWorkspace(
            Path(run.workspace), secrets=self.workspace_secrets(), snapshot_dir=Path(data["workspace"]["snapshot_dir"])
        )
        if run.status not in {"DONE", "CANCELLED"}:
            workspace.restore_state(data["workspace"])

        def runtime_factory(config: AppConfig = cfg) -> AgentRuntime:
            if options["runtime"] == "fake":
                from agentlab.demo import demo_scripts

                return FakeRuntime(demo_scripts())
            url, secret = self.gateway()
            if not url or not secret:
                raise MissingGatewayConfig("gateway credentials required to resume")
            if options["runtime"] == "adk":
                from agentlab.adapters.runtime.adk import AdkRuntime

                return AdkRuntime(config, url, secret)
            from agentlab.adapters.runtime.raw import RawRuntime

            return RawRuntime(config, url, secret, self.anthropic_gateway(config))

        sandbox = DockerSandbox(default_image="python:3.12-slim") if options["sandbox"] == "docker" else LocalSandbox()
        if options["runtime"] == "fake":
            sandbox = LocalSandbox()
        gate = ConfigGate(GateCfg.model_validate(options["gate"]), sandbox, lambda text: self.blobs.put(text)[0])
        runtime = FakeRuntime({}) if run.status in {"WAITING_HUMAN", "DONE", "CANCELLED"} else runtime_factory()
        driver = Driver(cfg, self.store, self.blobs, self.bus, runtime, gate, workspace, self.hooks)
        driver.runtime_factory = lambda: runtime_factory(driver.cfg)
        driver.restore_checkpoint(data)
        return driver


def build_services(settings: Settings | None = None) -> Services:
    s = settings or Settings()
    cfg = load_config(s.config_dir)
    env = EnvFile(s.env_file)
    embedder = OpenAICompatEmbedder(
        lambda: (env.read().get("AGENTLAB_EMBEDDING_BASE_URL"), env.read().get("AGENTLAB_EMBEDDING_API_KEY")),
        cfg.models.embedding.model,
        cfg.models.embedding.dimensions,
        cfg.models.embedding.version,
    )
    store: Store = InMemoryStore()
    if s.store_backend not in {"auto", "memory", "postgres"}:
        raise ValueError("store_backend must be auto, memory or postgres")
    if s.store_backend == "postgres" or (s.store_backend == "auto" and s.database_url):
        if not s.database_url:
            raise ValueError("postgres requires AGENTLAB_DATABASE_URL")
        from agentlab.adapters.store.postgres import PostgresStore
        from agentlab.db.migrate import upgrade

        upgrade(s.database_url)
        store = PostgresStore(s.database_url)
        from agentlab.core.monitor import recover_interrupted_calls

        recover_interrupted_calls(store)
    memory = (
        PersistentMemoryStore(store, embedder)
        if not isinstance(store, InMemoryStore)
        else InMemoryMemoryStore(embedder)
    )
    return Services(
        settings=s,
        cfg=cfg,
        store=store,
        blobs=FileBlobStore(s.data_dir / "blobs"),
        bus=InProcessEventBus(),
        env=env,
        knowledge=KnowledgeService(memory),
        projects=ProjectService(store),
    )
