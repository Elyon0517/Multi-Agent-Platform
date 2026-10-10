from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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

    def gateway(self) -> tuple[str | None, str | None]:
        return gateway_creds(self.env, self.settings)

    def setting_views(self) -> list[SettingView]:
        url, key = self.gateway()
        return views({"AGENTLAB_LLM_BASE_URL": url, "AGENTLAB_LLM_API_KEY": key})

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

        return RawRuntime(cfg, url, key)

    def sandbox(self) -> Sandbox:
        if self.settings.sandbox == "docker":
            return DockerSandbox(default_image="python:3.12-slim")
        return LocalSandbox()

    def gates(self) -> list[ConfigGate]:
        sandbox = self.sandbox()
        return [ConfigGate(g, sandbox, lambda text: self.blobs.put(text)[0]) for g in self.cfg.gates.values()]

    def driver(self, workspace: Path, runtime: str | None = None, language: str | None = None) -> Driver:
        cfg = self.cfg.model_copy(update={"frozen_prompts": {r: self.cfg.prompt(r) for r in self.cfg.agents}})
        key = self.gateway()[1]
        ws = GitWorkspace(
            workspace,
            secrets=(key,) if key else (),
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
        }
        driver.runtime_factory = lambda: self.runtime(runtime, cfg)
        return driver

    def restore_driver(self, run_id: str) -> Driver:
        run = self.store.get_run(run_id)
        data = self.store.checkpoint(run_id)
        if not data or not data.get("workspace"):
            raise ValueError("run has no recovery checkpoint")
        cfg = AppConfig.model_validate(data["config"])
        options = data["options"]
        key = self.gateway()[1]
        workspace = GitWorkspace(
            Path(run.workspace), secrets=(key,) if key else (), snapshot_dir=Path(data["workspace"]["snapshot_dir"])
        )
        if run.status not in {"DONE", "CANCELLED"}:
            workspace.restore_state(data["workspace"])

        def runtime_factory() -> AgentRuntime:
            if options["runtime"] == "fake":
                from agentlab.demo import demo_scripts

                return FakeRuntime(demo_scripts())
            url, secret = self.gateway()
            if not url or not secret:
                raise MissingGatewayConfig("gateway credentials required to resume")
            if options["runtime"] == "adk":
                from agentlab.adapters.runtime.adk import AdkRuntime
                return AdkRuntime(cfg, url, secret)
            from agentlab.adapters.runtime.raw import RawRuntime

            return RawRuntime(cfg, url, secret)

        sandbox = DockerSandbox(default_image="python:3.12-slim") if options["sandbox"] == "docker" else LocalSandbox()
        if options["runtime"] == "fake":
            sandbox = LocalSandbox()
        gate = ConfigGate(GateCfg.model_validate(options["gate"]), sandbox, lambda text: self.blobs.put(text)[0])
        runtime = FakeRuntime({}) if run.status in {"WAITING_HUMAN", "DONE", "CANCELLED"} else runtime_factory()
        driver = Driver(cfg, self.store, self.blobs, self.bus, runtime, gate, workspace, self.hooks)
        driver.runtime_factory = runtime_factory
        driver.restore_checkpoint(data)
        return driver


def build_services(settings: Settings | None = None) -> Services:
    s = settings or Settings()
    cfg = load_config(s.config_dir)
    env = EnvFile(s.env_file)
    embedder = OpenAICompatEmbedder(lambda: gateway_creds(env, s), cfg.models.embedding.model)
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
