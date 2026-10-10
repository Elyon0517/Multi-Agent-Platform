from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentlab.adapters.events import InProcessEventBus
from agentlab.adapters.gates.config_gate import ConfigGate, resolve_gate
from agentlab.adapters.runtime.fake import FakeRuntime
from agentlab.adapters.runtime.raw import OpenAICompatEmbedder
from agentlab.adapters.sandbox.docker import DockerSandbox
from agentlab.adapters.sandbox.local import LocalSandbox
from agentlab.adapters.store.blobs import FileBlobStore
from agentlab.adapters.store.memory import InMemoryStore
from agentlab.adapters.workspace import GitWorkspace
from agentlab.core.config import AppConfig, load_config
from agentlab.core.loop.driver import Driver
from agentlab.core.memory.store import InMemoryMemoryStore
from agentlab.core.ports import AgentRuntime, Sandbox, Store
from agentlab.secrets import EnvFile, SettingView, views
from agentlab.services import KnowledgeService, MemoryHooks, ProjectService
from agentlab.settings import Settings


class MissingGatewayConfig(RuntimeError):
    pass


def gateway_creds(env: EnvFile, settings: Settings) -> tuple[str | None, str | None]:
    values = env.read()
    return (values.get("AGENTLAB_LLM_BASE_URL") or settings.llm_base_url,
            values.get("AGENTLAB_LLM_API_KEY") or settings.llm_api_key)


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

    def runtime(self, name: str | None = None) -> AgentRuntime:
        name = name or self.settings.runtime
        if name == "fake":
            from agentlab.demo import demo_scripts
            return FakeRuntime(demo_scripts())
        url, key = self.gateway()
        if not url or not key:
            raise MissingGatewayConfig("set AGENTLAB_LLM_BASE_URL and AGENTLAB_LLM_API_KEY (Settings tab or .env)")
        if name == "adk":
            from agentlab.adapters.runtime.adk import AdkRuntime
            return AdkRuntime(self.cfg, url, key)
        from agentlab.adapters.runtime.raw import RawRuntime
        return RawRuntime(self.cfg, url, key)

    def sandbox(self) -> Sandbox:
        if self.settings.sandbox == "docker":
            return DockerSandbox(default_image="python:3.12-slim")
        return LocalSandbox()

    def gates(self) -> list[ConfigGate]:
        sandbox = self.sandbox()
        return [ConfigGate(g, sandbox, lambda text: self.blobs.put(text)[0]) for g in self.cfg.gates.values()]

    def driver(self, workspace: Path, runtime: str | None = None, language: str | None = None) -> Driver:
        ws = GitWorkspace(workspace)
        if (runtime or self.settings.runtime) == "fake":
            from agentlab.demo import demo_gate_cfg
            gate = ConfigGate(demo_gate_cfg(), LocalSandbox())
        else:
            gate = resolve_gate(self.gates(), ws.root, language)
        return Driver(self.cfg, self.store, self.blobs, self.bus, self.runtime(runtime), gate, ws, self.hooks)


def build_services(settings: Settings | None = None) -> Services:
    s = settings or Settings()
    cfg = load_config(s.config_dir)
    env = EnvFile(s.env_file)
    embedder = OpenAICompatEmbedder(lambda: gateway_creds(env, s), cfg.models.embedding.model)
    return Services(
        settings=s, cfg=cfg, store=InMemoryStore(), blobs=FileBlobStore(s.data_dir / "blobs"),
        bus=InProcessEventBus(), env=env, knowledge=KnowledgeService(InMemoryMemoryStore(embedder)),
        projects=ProjectService(),
    )
