# Multi-Agent Platform Discovery

> 状态：v1.5 · P0 / P1 / P2 完成，下一步 P3 与 §16.4 项目隔离 · 可持续更新
> 最近更新：2026-10-10
> 仓库名称：`multi-agent-platform`（Multi-Agent Platform）；Python 包、CLI 与 `AGENTLAB_*` 配置名保留兼容。
> 正本：本文件（`docs/DISCOVERY.md`）。原始 `dicovery-agent.pdf` v1.0 只读归档。
> 适用范围：个人本地 dev/研究工具，面向未来开源

## v1.1 变更摘要（相对 PDF v1.0，目标不变）

| # | 变更 | 原因 | ADR |
|---|---|---|---|
| 1 | 前端加入 **Office Floor 可视化**（移植 munder-difflin `scene/office/`，Pixi.js v8） | Agent 状态"看得见"，复用成熟实现 | ADR-011 |
| 2 | LLM 改为 **单一 OpenAI 兼容网关 + 角色→模型别名映射**；root 与 sub agent 可用同一 endpoint 的不同模型 | 用户的实际访问方式 | ADR-012 |
| 3 | 容器运行时使用 **Colima + docker CLI**（brew） | 本机无 Docker Desktop | ADR-013 |
| 4 | 借鉴 homerail：**配置严格校验（未知字段报错）**、**所有循环静态上限**、**确定性命令白名单** | 配置即代码的安全前提 | ADR-014 |
| 5 | 不做语音、不做跨平台桌面壳（Electron）；前端为 localhost Web | 范围收敛 | ADR-015 |
| 7 | munder 的 `window.cth`（Electron IPC）以 `ui/src/bridge.ts` 适配层重实现，场景代码几乎零改动 | 便于对照上游、降低移植风险 | ADR-017 |
| 6 | 新增「开发 Phase / Steps」章节，替代原里程碑的粗粒度描述；v1.2 按实际进度重排（§16） | 可执行性 | — |

---

## 一、项目定位与设计原则

| 维度 | 决定 |
|---|---|
| 定位 | 个人本地 dev/研究工具，未来开源 |
| 核心 MVP | Planner + Coder + Reviewer 的收敛 Loop |
| 拓扑 | Supervisor（root）自动分派，调度逻辑抽成独立 policy 层（auto / manual 两种 policy） |
| 消息 | 结构化对象，传 `artifact_id` 引用，**不传全文** |
| Agent 生命周期 | 任务级临时实例；记忆宿主为 `project × role`，不是实例 |
| 完成判定 | 所有 reviewer signoff（severity 阈值）→ 人工终审 |
| 冲突 | 升级给人 + 震荡检测自动触发升级 |
| Memory | Blackboard + Episodic + Semantic（MVP）；Procedural 延后 |
| 隔离 | per-role namespace 私有 + 共享黑板；per-project Postgres schema |
| 记忆写入 | 每轮 summarizer 自动抽取 + `pin_memory` 手动工具 |
| LLM | **纯云端调用，本地不跑模型**；单一 OpenAI 兼容网关（LiteLLM Proxy 统一出口） |
| 路由 | 静态 policy 表（角色→模型别名）+ root agent 受限 override（可复现优先） |
| 多模型评审 | 2–3 个不同 LLM 并行独立 review（核心卖点） |
| 预算 | 确定性中间件熔断 + LiteLLM virtual key 周限额，**不用 agent 做熔断** |
| 安全 | Docker 沙箱 + 只读挂载 + 默认断网 + 工具白名单；密钥永不进 agent 进程 |
| 运行形态 | 本地 daemon（CLI/TUI 为主）+ localhost TS UI（可选视图，非运行时依赖） |
| 可视化 | Office Floor（Pixi）+ Run 树（React Flow）+ 看板/评审对比 |

### 四条不可妥协的设计原则

1. **确定性的事情不交给 LLM**：预算熔断、收敛判定、震荡检测、重试、路由，全部是普通 Python 代码。
2. **配置即代码**：YAML + git 管理 agent 定义、模型策略、工具授权；DB 只存运行时状态。配置在加载时严格校验，未知字段直接报错。
3. **便宜的检查先跑**：编译、类型、lint、测试在 LLM 评审之前，失败直接退回，不花一个 reviewer token。
4. **一切可回放**：step 树 + artifact 内容寻址 + 事件日志，任何一次 run 都能重放和 diff。

---

## 二、编排框架：Google ADK vs LangGraph

**结论**：自研 Loop Driver + Google ADK 作为 Agent 执行层的分层方案。复杂部分（Gate、severity 收敛、震荡、熔断、人工卡点）全是确定性逻辑；框架只需做好：调模型、挂工具、并行跑 reviewer。

### 三层切分

```
Layer 3  Loop Driver（自研 · 纯 Python · 无框架依赖）
  状态机：PLAN→CODE→GATE→REVIEW→ARBITRATE→HUMAN→DONE
  职责：收敛判定、震荡检测、迭代上限、预算熔断、HIL 卡点、断点续跑（Postgres run / iteration）

Layer 2  Agent Runtime（Google ADK，可替换）
  LlmAgent(Planner/Coder/Reviewer×N/Summarizer/Arbiter)
  ParallelAgent 跑评审团 · Callbacks 做中间件 · MCPToolset 挂工具

Layer 1  Model Gateway（LiteLLM Proxy → 单一 OpenAI 兼容上游）
  统一 OpenAI 格式 · 角色→模型别名 · retry=3 · per-project virtual key 预算与 RPM · 密钥隔离
```

框架隔离接口 `core/ports.py::AgentRuntime`，实现：`adapters/runtime/adk.py`（默认）、`adapters/runtime/raw.py`（兜底，直接 OpenAI SDK）、`adapters/runtime/fake.py`（测试/离线骨架）。

---

## 三、Loop Engine（系统灵魂）

```
Task → Planner → Coder → [客观 Gate] → [LLM 评审团] → Arbiter → Human → Done
                   ↑          │ fail          │ changes      │ 冲突/震荡
                   └──────────┴───────────────┘              └→ Human
```

1. **客观 Gate 前置**：build / typecheck / lint / test / diff 合法性先跑，失败退回 Coder，不消耗 reviewer token。
2. **Reviewer 看 diff，不看 Coder 自述**：输入 = 原始需求 + Planner 验收标准 + 实际 `git diff` + Gate 输出 + 相关文件上下文。baseline/current 使用临时 index 的 `git write-tree` 捕获工作区，保留用户 index；快照对象也保存在独立临时对象库，用户对象库仅作为只读 alternate。大文件、二进制和脱敏内容显示 Git 改动元数据；大文件变为短源码时同时展示当前完整内容，不能因上下文过滤而变成空 diff。
3. **结构化评审 + severity 阈值**：`blocking + major == 0` 即 signoff；minor / nit 只记录。
4. **四个终止条件**：

| 条件 | 动作 |
|---|---|
| 全部 reviewer signoff | → 人工终审 |
| `iteration > max_iter`（默认 5） | → 升级给人 |
| run token 或成本超预算 | → 暂停，等人决策 |
| 震荡：连续 2 轮 `diff_hash` 相同，或 finding 指纹集合重复 | → 升级给人 |

5. **状态机（可续跑）**：

| 状态 | 下一步 |
|---|---|
| PLANNING | → CODING |
| CODING | → GATING |
| GATING | pass → REVIEWING；fail → CODING（带 gate 报告） |
| REVIEWING | → ARBITRATING |
| ARBITRATING | SIGNOFF → WAITING_HUMAN；BACK_TO_CODER → CODING；ESCALATE → WAITING_HUMAN |
| WAITING_HUMAN | signoff 的 approve → DONE；其他 approve → 恢复执行（预算/迭代上限须先提高）；reject+反馈 → 有 plan 时 CODING、否则 PLANNING；abort → CANCELLED |

每次状态迁移写一条 `iteration`/`event` 记录并 commit；进程挂掉后从 `run.status` 恢复。状态迁移表在 `core/loop/states.py` 中是**唯一事实源**，非法迁移抛异常（借鉴 homerail 的严格语义）。

---

## 四、客观 Gate：多语言适配器

```python
class GateAdapter(Protocol):
    language: str
    image: str
    def detect(self, workspace: Path) -> bool: ...
    async def run(self, workspace: Path, mode: GateMode) -> GateResult: ...
```

步骤（build / typecheck / lint / test / security）由 `config/gates/<lang>.yaml` 声明，适配器只负责执行与诊断解析。命令以 argv 列表执行，不经 shell。

| 语言 | build | typecheck | lint/format | test | security |
|---|---|---|---|---|---|
| Python | `uv sync` | `mypy --strict` | `ruff check` + `ruff format --diff` | `pytest -q --cov` | `pip-audit` |
| TypeScript | `pnpm build` | `tsc --noEmit` | `eslint` + `prettier --check` | `vitest run` | `pnpm audit` |
| Java | `mvn -q -B compile` / `gradle build -x test` | 编译 + ErrorProne | `spotless:check` + checkstyle | `mvn -q test` | dependency-check |
| C++ | `cmake -G Ninja && ninja` | 编译 + clang-tidy | `clang-format --dry-run --Werror` | `ctest --output-on-failure` | ASan/UBSan + cppcheck |

C++：必须产出 `compile_commands.json`；增量缓存（ccache + 持久 build volume）+ 分级超时（build 600s / test 300s）。

当前 P1 Python 离线 Gate 以 compileall 替代 uv sync，未运行联网 pip-audit；上表是最终目标，不能视为当前已实现的依赖安装/安全审计。

Gate 分两档：`fast`（每轮）/ `full`（进入 WAITING_HUMAN 前一次）。只把结构化 diagnostics 和日志尾部送进 prompt，完整日志存 blob。

---

## 五、多模型评审团与仲裁

| Reviewer | 关注面 | 模型档 | 成本档 |
|---|---|---|---|
| correctness-reviewer | 正确性、边界、并发 | 强推理档 | 高 |
| arch-reviewer | 架构、接口、可维护性 | 强推理档（不同厂商/型号） | 高 |
| test-style-reviewer | 测试覆盖、风格、文档 | 廉价档 | 低 |

三条硬规则：
1. Reviewer 之间互相不可见（并行、独立调用）。
2. 不投票：任一 reviewer 报 `blocking` 且 `confidence > 0.7` → 直接退回 Coder。
3. Arbiter 不自行裁决真冲突：两 reviewer 的 hard finding 对同一 `(file, subject)` 固定动作提出 require / forbid 相反要求（不要求行号一致） → 打包双方论点升级给人；同一行的不同问题或不同严重程度不算矛盾。

Arbiter 做：去重合并、按 severity×confidence 排序、生成结构化修复指令、检测矛盾。不做：判断谁对、忽略低 confidence 的 blocking、自行降级 severity、为收敛强行拍板。**Arbiter 是确定性代码**（`core/loop/arbiter.py`），LLM 仅可选用于生成修复指令的自然语言措辞。

---

## 六、Agent 清单

| Role | 输入 | 输出 artifact | 默认模型别名 |
|---|---|---|---|
| supervisor (root) | 任务 + project 配置 | 调度决策（policy 层） | `root` |
| planner | 需求 + 仓库上下文 + semantic memory | `plan`（含验收标准） | `strong` |
| coder | plan + gate 报告 + arbiter 指令 | `diff` | `strong` |
| reviewer × 3 | 需求 + 验收标准 + diff + gate 输出 | `review`（结构化 JSON） | `strong` / `strong-alt` / `cheap` |
| arbiter | 全部 verdicts | `arbiter_decision` | 确定性代码 |
| summarizer | 本轮全部 artifact | episodic memory 条目 | `cheap` |

所有 agent 定义存于 `config/agents/*.yaml`，进 git。

---

## 七、LLM 网关、路由与 Retry 策略（v1.1 更新）

### 7.1 单网关多模型（ADR-012）

用户只有**一个 OpenAI 兼容 endpoint + 一个 key**，但不同角色用不同模型（例：root 用 GPT-6.1，sub reviewer/worker 用 GPT-5.5 或更低）。设计为三级映射：

```
role ──(model_policy.yaml)──▶ alias ──(models.yaml)──▶ provider model id ──▶ gateway endpoint
supervisor                    root                     gpt-6.1                AGENTLAB_LLM_BASE_URL
coder                         strong                   gpt-5.5
test-style-reviewer           cheap                    gpt-5-mini
```

- **接口位置**：`.env`（不进 git）只需 `AGENTLAB_LLM_BASE_URL` + `AGENTLAB_LLM_API_KEY`；模型 id 在 `config/models.yaml` 中填，**代码零改动即可换模型**。
- 代码中只出现**别名**（`root/strong/strong-alt/cheap`），永不硬编码模型名。
- LiteLLM Proxy 可选：S0–S1 直连网关（`raw`/`adk` runtime 都走 OpenAI 兼容协议）；S2 起接 LiteLLM 做 virtual key 预算。两条路径共享同一份 `models.yaml`。
- 多模型评审的"不同厂商"诉求降级为"不同型号"即可；若网关后有多家模型，直接在 `models.yaml` 配置。

### 7.2 静态路由策略

```yaml
# config/model_policy.yaml
roles:
  supervisor:          { primary: root,   temperature: 0.2, fallback: [strong] }
  planner:             { primary: strong, temperature: 0.2, fallback: [root] }
  coder:               { primary: strong, temperature: 0.1, fallback: [root] }
  correctness-reviewer:{ primary: strong, temperature: 0.0 }
  arch-reviewer:       { primary: strong-alt, temperature: 0.0 }
  test-style-reviewer: { primary: cheap,  temperature: 0.0 }
  summarizer:          { primary: cheap,  temperature: 0.3 }
override:
  allowed_by: supervisor
  allowed_transitions: [{ from: strong, to: root }, { from: strong-alt, to: root }]
  forbidden: [downgrade_reviewer_below_tier_2]
  must_log: true
```

### 7.3 Retry（retry = 3）

`num_retries = 3` 指同一次逻辑 LLM 调用的额外重试次数（最多 4 次请求）。仅瞬时错误（429 / 5xx / 连接 / 读超时 / 空响应）重试；401/403、上下文超长、内容拒绝、预算超限不重试。结构化输出修复独立预算 `max_repairs: 2`（Pydantic 错误原文回灌）。重试耗尽后最多换 1 个 fallback 模型。每次 attempt 前预留预算（并行请求共享预留量）；网关返回的 usage 逐次即时记账，包括空响应、拒绝与 JSON 修复失败。没有 usage 的传输失败无法准确计费，不伪造 token；每次逻辑调用一个 `step_id`，所有 attempt 挂同一 step。

### 7.4 Embedding 与 Rerank（API）

embedding 可以独立配置 URL/Key（支持时也可使用聊天网关），默认 `text-embedding-3-large`；`memory.embedding_model + embedding_version` 必须落库。全文用 Postgres `tsvector` BM25，与向量做 RRF 融合；rerank API 可选。

---

## 八、预算与熔断（确定性中间件，非 agent）

三道闸：
1. LiteLLM virtual key（每 project 一把）—— `max_budget` / `rpm_limit` / 模型白名单（S2 起）。
2. 应用层熔断中间件（ADK `before_model_callback` / raw runtime 调用前）—— 估算成本，超 run 预算直接短路，run 置 `WAITING_HUMAN`。
3. per-run 软预算 —— `run.budget_cents`，80% 告警，实际 usage 达到预算后，在下一批付费调用前暂停；已返回的成功结果先保存。

估算系数由 `models.yaml` 每个别名控制：`estimate_input_tokens_per_byte`（输入 UTF-8 字节到 token 的系数）与 `estimate_output_token_ratio`（输出 token 上限的预留比例）。当前均为 0.5；实际 usage 按完整账单计费，不乘估算系数。缺省均为 1.0，便于选择保守模式。可用预算约为总预算减去下一批调用的预估；80,000 字节 prompt、16384 输出上限及当前价格下，每 reviewer 预估 36.384c，三人共 109.152c。系数为估算策略，不保证网关结算硬上限。

明确不做：用"检查 agent"判断要不要熔断。

---

## 九、Memory 与知识层

| 类型 | 存储 | 写入方式 | MVP |
|---|---|---|---|
| Blackboard | `blackboard` 表（project+run，version 乐观锁） | agent 显式写 | Yes |
| Episodic | `memory(kind='episodic')` | summarizer 自动抽取 | Yes |
| Semantic | `memory(kind='semantic')` + pgvector | summarizer 提炼 + `pin_memory` | Yes |
| Procedural | `memory(kind='procedural')` | 从成功 run 提炼 | 延后 |

**三层作用域（v1.2，ADR-020）**

| 层 | namespace | 归属 | 谁能读 | 谁写 | 已实现 |
|---|---|---|---|---|---|
| Global 个人知识 | `global` | 跨所有 project | 所有 agent | 用户上传 PDF / Markdown / txt（切块 + embedding） | Yes（内存版） |
| Project | `project` | 单个 project | 该 project 的所有 agent | run 结束自动写结果；用户手写 note | Yes（内存版） |
| Agent 本地 | `agent:<role>` | `project × role` | 仅该 role | reviewer 提出 blocking/major 时自动记；用户手写 note | Yes（内存版） |

每次调用 agent 前，Driver 通过 `RunHooks.context_for` 检索 `global ∪ project ∪ agent:<self>`，top-6 注入 `AgentInput.context.memory`。检索：BM25 + 向量（网关 embedding）→ RRF；embedding 失败自动降级为纯关键词，且 memory 任何异常都不会中断 run。扫描版 PDF（无文字层）会被拒绝并提示。

**Project 进度**：project-planner（root 模型）把 project 目标拆成 phase → step；每个 step 可一键发起 run，run DONE 自动把 step 标为 done，失败/取消标 blocked；用户也可手动改状态（ADR-021）。

旧命名空间 `shared` 由 `project` 取代；记忆归属 `project × role`。版本化非覆盖：`valid_from / valid_to / superseded_by`，永不物理删除。检索：`pgvector HNSW top-50 ∪ tsvector BM25 top-50 → RRF → rerank top-8`。

---

## 十、数据模型

```
project    (id, name, goal, phases jsonb, workspace_path, config_ref, budget_cents, default_language, created_at)
agent_def  (id, project_id NULL, role, system_prompt_ref, model_policy, tool_grants[], version)
run        (id, project_id, goal, status, max_iter, budget_cents, cost_cents, token_in, token_out,
            started_at, paused_reason)
iteration  (id, run_id, n, phase, gate_result jsonb, verdicts jsonb, diff_hash, finding_set jsonb)
step       (id, run_id, iteration_id, agent_role, model_alias, model, prompt_ref, response_ref,
            tool_calls jsonb, tokens, latency_ms, cost_cents, parent_step_id, attempt_count,
            retry_reasons jsonb, routing_reason text)
artifact   (id, run_id, kind, content_ref, sha256, created_by_step)   -- plan|diff|review|test_log|doc
blackboard (id, project_id, run_id, key, value jsonb, version, updated_by, updated_at)
memory     (id, project_id NULL for global, namespace, kind [document|note|episodic|semantic|procedural], text, source, embedding vector(3072), embedding_model,
            embedding_version, source_run_id, valid_from, valid_to, superseded_by, pinned, tsv)
approval   (id, run_id, reason, payload jsonb, status, decided_by, decided_at)
event      (id, run_id, seq, ts, type, actor, payload jsonb)   -- v1.1 新增：可视化与回放的唯一事件流
```

- v1.1 新增 `event` 表：Office Floor、Run 树、TUI 都只消费这条事件流（SSE），见 §15.3。
- `prompt_ref / response_ref / content_ref` 指向 blob 存储（本地文件，sha256 寻址），DB 不存大文本。
- 隔离：单 Postgres 实例，每 project 一个 schema（`proj_<id>`）。导出 = `pg_dump -n schema`。

---

## 十一、安全与沙箱

| 面 | 措施 |
|---|---|
| 文件系统 | Docker 容器，仅 workspace 读写挂载，其余只读或不挂载 |
| `rm -rf` 防护 | 靠容器边界，不靠 prompt 约束 |
| 网络 | 默认 `--network none`；装依赖时切白名单代理 |
| 用户 | non-root，固定 uid/gid，`--cap-drop=ALL`，只读 rootfs + tmpfs |
| 资源 | `--memory` / `--cpus` / `--pids-limit` / 每步超时 |
| 工具授权 | per-agent 白名单（`agent_def.tool_grants`），runtime 调用前强制 |
| 命令执行 | argv 列表、不经 shell、可执行文件白名单（借鉴 homerail `command` 节点） |
| 密钥 | 永不进 agent 进程与沙箱；LLM key 只在 daemon/网关进程 |
| 危险操作 | 写 workspace 外、开网络、force push、删分支 → `approval` 卡点 |

写 workspace 外或秘密文件的尝试会暂停并生成审批；批准仅恢复到 Coder，用新反馈生成合法修改，不授权突破 workspace 边界。只有 signoff + FULL Gate 之后的批准才能完成项目 step。

容器运行时：Colima（`colima start --cpu 4 --memory 8`）+ docker CLI + docker-compose。

---

## 十二、技术选型总表

| 层 | 选择 |
|---|---|
| 编排 | 自研 Loop Driver（Python 3.12+） |
| Agent 运行时 | Google ADK（Python）；raw / fake 兜底 |
| 模型网关 | 单一 OpenAI 兼容 endpoint；LiteLLM Proxy（S2 起） |
| 存储 | Postgres 16 + pgvector；SQLAlchemy 2 + Alembic |
| 结构化输出 | Pydantic v2（`extra="forbid"`） |
| 沙箱 | Docker via Colima |
| 工具层 | MCP（自研工具也写成 MCP server） |
| 后端入口 | FastAPI daemon（localhost）+ Typer CLI + Textual TUI |
| 前端 | React 18 + Vite + TypeScript + zustand + TanStack Query + SSE |
| 可视化 | Pixi.js v8 Office Floor（移植自 munder-difflin）+ React Flow Run 树 + Monaco diff |
| Trace | Langfuse 自托管（经 OTel，S5） |
| 包管理 | uv（Python）/ npm（UI） |
| 配置 | YAML + git（`config/`），加载即严格校验 |

---

## 十三、目录结构

```
agentlab/
├── docker-compose.yml            # postgres+pgvector / litellm(可选) / langfuse(可选)
├── .env.example                  # AGENTLAB_LLM_BASE_URL / AGENTLAB_LLM_API_KEY / DATABASE_URL
├── config/
│   ├── models.yaml               # 别名 → 模型 id + 能力矩阵 + 价格
│   ├── model_policy.yaml         # 角色 → 别名 + override 白名单
│   ├── retry.yaml
│   ├── budget.yaml
│   ├── agents/*.yaml
│   ├── prompts/*.md
│   ├── gates/{python,typescript,java,cpp}.yaml
│   └── policies/{auto,manual}.yaml
├── src/agentlab/
│   ├── settings.py / bootstrap.py   # env + 组装根（composition root）
│   ├── core/
│   │   ├── ports.py              # AgentRuntime / GateAdapter / Sandbox / Store / MemoryStore / EventBus
│   │   ├── schemas.py            # Plan/Diff/Finding/Verdict/GateResult/Event
│   │   ├── config.py             # 严格配置模型
│   │   ├── routing.py            # role → alias → model
│   │   ├── budget.py
│   │   ├── loop/{states,driver,convergence,arbiter}.py
│   │   └── llm/retry.py
│   ├── adapters/
│   │   ├── runtime/{fake,raw,adk}.py
│   │   ├── gates/config_gate.py   # 读 config/gates/*.yaml，单一实现（ADR-018）
│   │   ├── sandbox/{local,docker}.py
│   │   ├── store/{memory,postgres,blobs}.py
│   │   ├── workspace.py / events.py
│   │   └── memory/{blackboard,pgvector}.py   # P6
│   ├── mcp/                      # workspace_fs / git / gate MCP server
│   ├── api/                      # FastAPI + SSE
│   ├── cli/                      # Typer + Textual
│   └── db/migrations/            # alembic
├── ui/                           # React + Vite + Pixi（Office Floor 移植）
│   ├── src/scene/office/         # ← munder-difflin（MIT）
│   ├── src/assets/               # ← tilesets（LimeZu，需署名）/ fonts（OFL）
│   └── THIRD_PARTY_NOTICES.md
├── evals/tasks/                  # 10 个固定回归任务
├── docker/                       # gate 镜像：py / node / jdk / cpp
└── tests/
```

---

## 十四、关键文件骨架

见代码：`core/loop/driver.py`（状态机主循环）、`core/schemas.py`（Finding/Verdict）、`core/loop/arbiter.py`、`core/loop/convergence.py`、`core/llm/retry.py`。原 PDF 中的伪代码已落为可测试实现。

---

## 十五、前端与可视化（v1.1 重写）

定位：localhost 的只读观察窗 + 审批入口，不是运行时依赖。关掉前端，CLI 照样跑完整流程。

### 15.1 视图

| 版本 | 内容 |
|---|---|
| v0（只读） | **Office Floor**、Run 列表、Run 时间线（iteration × phase）、Gate 诊断表、3 个 reviewer verdict 并排对比、成本与 token 看板 |
| v1（交互） | 审批卡点（approve / reject+反馈）、恢复暂停的 run、调整 budget 与 max_iter |
| v2（深度） | React Flow step 树、Monaco diff viewer、从任意 iteration 回放、memory 浏览与 pin、Memory Graph |

### 15.2 从 munder-difflin 移植的内容（ADR-011）

| munder 源 | Multi-Agent Platform 用途 | 改动 |
|---|---|---|
| `scene/office/*`（OfficeFloor、Character、CharacterSprite、Camera、pathfinding、ThoughtBubble、ToolBubble、MessageEnvelope、DeskScreen、SeatPool、TiledMapRenderer、theme*、cast、portraitArt、glRecovery、cafeteriaLines） | Office Floor 主场景 | 数据源 `window.cth`(Electron IPC) → `EventSource` SSE；删 `pixi.js/unsafe-eval`（浏览器无需） |
| `design/tokens.{ts,css}`, `global.css`, `fonts.css` | 像素风设计系统 | 原样 |
| `components/PixelPanel / PixelButton / PixelBadge / Icon / SpritePortrait` | 基础组件 | 原样 |
| `components/TasksKanban` | Run 看板（状态列 = loop state） | 数据源替换 |
| `components/ToolWaterfall` | 每个 agent 的 LLM 调用 / Gate 瀑布图（AgentDetail → tools） | 数据源：`step.finished` / `gate.finished` 事件折叠 |
| `components/MemoryGraphPanel` + `memoryGraph/*` | memory 图谱（v2） | 数据源替换 |
| `components/BlockedBanner` | WAITING_HUMAN 审批横幅 | 动作 → `/runs/{id}/approval` |
| `components/ThreadsPanel` | agent 间 artifact 流转（AgentDetail → messages）；回复 = 带反馈 reject | 数据源替换 |
| `components/AgentStrip` + `AgentCard` + `AgentNameEditor` | 底部 agent 卡片条：头像、状态、alias·model、context 进度、私人便签、拖拽排序、改名 | 去掉 PTY / 语音 / 新增 agent / 恢复团队；改名、排序、便签存 localStorage |
| `components/RecentText` + `hooks/useTypewriter` | agent 最新输出（打字机） | 数据源：`step.finished.summary` |
| `components/OfficeThemePicker` | 切换地图（office / brooklyn99） | 切换不再删除 agent，去掉确认弹窗 |
| `components/AskMeTab` + `askMeOrder` | 待人工决策列表；回答 approve/abort/其它文字 = 反馈 | `WAITING_HUMAN` run 映射为 humanQA 卡片 |
| `components/TaskDetailOverlay` | 看板卡片详情 | assign → 跳到该 run |
| `assets/tilesets/*`, `assets/maps/*.tmj` | 地图与素材 | **LimeZu 许可，必须署名** |
| `assets/fonts/*` | Press Start 2P / Inter / JetBrains Mono | OFL 1.1 |
| `i18n/locales/{en,zh-CN}.json` 的 `office.*` 段 | 场景文案 | 只保留用到的 key |

不移植：语音（realtime/freeflow、RealtimeMichaelToggle、CostHud）、PTY/xterm、Electron main/preload、hire/onboarding（AddAgentModal、OnboardingWizard）、Slack/webhook 触发器、Skills/Workers、更新器、SettingsModal。

**精简版控制台（ADR-022）**：munder 的 CommandCenterPanel（13 个标签、大半依赖 PTY）不整体移植，改为右侧 8 个标签：runs / project / tasks / ask me / memory / graph / activity / settings。点任意头像或卡片在顶部展开 AgentDetail（activity / tools / messages）。

**Settings**：网关 URL + API key 输入（password 输入框，可切换显示）；写入本地 `.env`（chmod 600）；后端只返回 `••••••••` + 后 4 位，永不回传完整 key（ADR-023）。

### 15.3 角色与状态映射

Office Floor 只认事件流，映射规则集中在 `ui/src/scene/adapter/` 一处：

| Multi-Agent Platform | munder Agent 字段 |
|---|---|
| supervisor | `isGod = true`（坐 Michael 的办公室） |
| planner / coder / reviewer×3 / summarizer / arbiter | 普通工位，各分配一个 cast 角色与 accent |
| `step.started` (LLM 推理中) | `status = 'thinking'` |
| `step.tool_call` | `status = 'working'`, `carrying = <ToolKind>` |
| `step.finished` | `status = 'success'` → `idle` |
| run `WAITING_HUMAN` | supervisor `status = 'blocked'` + BlockedBanner |
| `artifact.created`（A → B 交接） | MessageEnvelope 飞行动画 |
| run 状态迁移 | TasksKanban 卡片移动 |
| 震荡/超限升级 | `StatusGlyph = 'looping'` |

### 15.4 类型来源

FastAPI 导出 OpenAPI → `openapi-typescript` 生成 TS 类型，前后端 schema 单一事实源。

---

## 十六、开发 Phase / Steps（v1.2 更新：按实际进度重排）

图例：`[x]` 完成并有测试 · `[~]` 部分完成 / 已有骨架未接线 · `[ ]` 未开始 · `[!]` 阻塞（等用户）

### 16.0 进度总览

| Phase | 内容 | 状态 | 说明 |
|---|---|---|---|
| P0 | 架构骨架 | **完成** | 2026-10-09；fake 模型下 loop 端到端跑通，UI 可视化可演示 |
| P1 | S0 Walking Skeleton（接真实 LLM + Docker 沙箱） | **已完成** | 网关已配置，Python 固定任务验证通过 |
| P2 | S1 持久化 + 断点续跑 | 已完成 | PostgreSQL / Alembic / CLI 恢复 / kill -9 验证 |
| P3 | S2 评审团真实化 + HIL 完整 | 部分 | 并行 / 仲裁逻辑、ASK ME 回答流已完成；ADK、工具白名单、危险操作卡点未做 |
| P4 | S5a 可视化 v0 | **大部分完成** | munder 可视化已全部接上（2026-10-09 v1.2）；缺 Gate 诊断表、openapi 类型 |
| P5 | S3 多语言 Gate | 部分 | 4 种语言 YAML 已写；镜像未建、未实测 |
| P6 | S4 Memory + Project 化 | **部分（提前）** | 三层记忆版本与项目设置已落 Postgres；项目私有文档、embedding model/version/dimensions 元数据、关键词/混合选择和 YAML 配置导入导出已接线；pgvector 索引、summarizer、完整记忆导入导出未做 |
| P7 | S5b 可视化 v2 + 可观测 | 部分 | Memory Graph 已接 agent 记忆；React Flow / Monaco / 回放 / Langfuse 未做 |
| P8 | S6 Eval | 部分完成 | 已有 py-fix-add 固定任务与 smoke；完整评分卡待做 |

### 16.1 已完成（P0 · 2026-10-09）

**配置与核心（`config/`、`src/agentlab/core/`）**
- [x] 全套 YAML：models / model_policy / retry / budget / agents×8 / prompts×8 / gates×4 / policies×2 / litellm
- [x] 严格加载：未知字段、未知别名、缺 prompt 文件、角色无路由，启动即报错（`core/config.py`）
- [x] 角色 → 别名 → 模型 id 三级路由 + supervisor override 白名单 + reviewer 不得降档（`core/routing.py`）
- [x] 状态迁移表为唯一事实源，非法迁移抛异常（`core/loop/states.py`）
- [x] 收敛判定 `blocking + major == 0`、finding 指纹、Gate 失败指纹（`core/loop/convergence.py`）
- [x] 震荡检测：diff_hash 相同或 finding 集合重复（同上）
- [x] 确定性 Arbiter：去重排序、高置信 blocking 否决、跨 reviewer 矛盾升级（`core/loop/arbiter.py`）
- [x] Retry=3（仅瞬时错误）+ 每次 attempt 前过熔断 + JSON 修复独立预算 + fallback 1 个模型（`core/llm/`）
- [x] 预算守卫：超预算暂停到 WAITING_HUMAN，80% 告警一次（`core/budget.py`）
- [x] Loop Driver：PLANNING → CODING → GATING → REVIEWING → ARBITRATING → WAITING_HUMAN → DONE，四个终止条件全实现；approve / reject(带反馈) / abort；预算暂停后可加预算恢复（`core/loop/driver.py`）

**适配器（`src/agentlab/adapters/`）**
- [x] `FakeRuntime`（离线演示 / 测试）
- [x] `RawRuntime`：OpenAI 兼容网关，错误分类为可重试 / 不可重试（已用真实网关验证，见 §16.1c）
- [x] `ConfigGate`：按 YAML 执行步骤 + tsc / pytest / 通用诊断解析，日志尾部入 prompt、全文存 blob
- [x] `LocalSandbox`（环境变量去密钥）、`DockerSandbox`（断网 / 只读 rootfs / cap-drop / 资源限制）
- [x] `GitWorkspace`：禁止写出 workspace 与 `.git`；`InMemoryStore`、`FileBlobStore`（sha256 寻址）、进程内 EventBus

**接口与基础设施**
- [x] FastAPI：`/health` `/roster` `/runs` `/runs/{id}` `/runs/{id}/decision` `/runs/{id}/events`(SSE) `/artifacts/{run}/{id}`
- [x] CLI：`agentlab config-check` / `demo` / `run` / `serve`
- [x] Colima + docker + compose 插件；`docker compose up -d postgres` 实测建出 §10 全部 10 张表

**UI（`ui/`）**
- [x] munder 可视化移植：Office Floor、像素设计系统、TasksKanban、MemoryGraphPanel、BlockedBanner、ThreadsPanel 等
- [x] `bridge.ts` 适配层重实现 `window.cth`；`scene/adapter/mapping.ts` 事件 → 小人状态 / 信封动画
- [x] Run 列表、Run 时间线（step 表）、评审对比、审批横幅（approve / reject+反馈 / abort）
- [x] 浏览器实测：点 Demo → 小人工作 → 审批横幅 → Approve → DONE
- [x] 署名：`ui/THIRD_PARTY_NOTICES.md`

**质量**
- [x] 历史 P0 验收通过；当前测试数量与验证结果统一见 §16.1d

### 16.1b 已完成（v1.2 · 2026-10-09，用户便利功能 + munder 补全）
- [x] Settings：API key / 网关 URL 输入（mask，后端不回传完整 key），写 `.env`，新 run 立即生效
- [x] Global 知识库：上传 PDF / md / txt → 切块 → embedding → 所有 agent 检索；可删除；"Test retrieval" 查看某个 agent 会拿到什么
- [x] Project：project-planner 自动生成 phase/step；step 一键 run；run 完成自动打勾；进度条
- [x] 三层记忆注入 Driver（`RunHooks`）；reviewer 本地记忆自动写；run 结果写 project 记忆；memory 故障降级不影响 run
- [x] munder 补全：AgentStrip/AgentCard、AgentDetail（RecentText / ToolWaterfall / ThreadsPanel）、OfficeThemePicker、AskMeTab、TaskDetailOverlay、Activity
- [x] 测试：历史 v1.2 验收通过；当前数量统一见 §16.1d；浏览器实测 settings / 换主题 / project→run→ask me 反馈→approve→进度打勾全流程

### 16.1c P1 实测（2026-10-09）
- [x] Colima（4 CPU / 8 GB）启动，Postgres + pgvector healthy；应用存储仍是内存版，未接数据库。
- [x] `agentlab ping` 四个模型别名验证 Chat Completions、JSON 与 usage；目前全部暂用 `gpt-6-astra`。费用、上下文与工具能力配置仍未核实。
- [x] `agentlab smoke --trials 3`：3/3 从失败测试收敛到 signoff，每次 1 轮；原测试保持不变，完整 Docker Gate 通过，停在人工终审，无自动批准。
- [x] Python 镜像预装 pytest / mypy / ruff，默认 non-root、断网、只读 rootfs；超时清理容器。字节码与检查缓存放在容器 /tmp。
- [x] 文件上下文每次调用刷新；修正 Coder prompt 与 FileEdit 输出结构；project run 继承 workspace 并验证 project/step 归属。
- [x] P1 阶段测试与构建通过；当前数量统一见 §16.1d。界面中英文选择与偏好保存已接入。
- [!] 离线 Gate 以 compileall 替代 uv sync；目标项目依赖须预装到镜像。联网 pip-audit 暂未接入，Gate 不代表依赖安全审计。
- [!] 对项目隔离、两种调度模式、对话侧栏的完整实现仍见 §16.4；P1 不代表这些功能已经完成。

### 16.1d 可靠性修复验收（2026-10-09）
- 异常（越界、重试耗尽、401、无效 JSON、git）统一暂停并生成审批；后台任务回收异常，错误信息只保留安全类别。
- 只有 signoff 人工批准可 DONE；其余升级恢复执行，预算/迭代上限须显式提高。CLI auto-approve 仅用于 signoff；无 plan 的 reject 回到 PLANNING。
- SSE 订阅在历史快照前注册，支持 Last-Event-ID，退出清理队列；UI 去重事件并读取累计费用/token。
- reviewer 迭代号与实际 iteration 对齐；finding 身份由 runtime 强制覆盖；矛盾检测依赖明确 subject / stance，BLOCK 无 hard finding 升级为不一致。
- usage 逐 attempt 记账，JSON 修复耗尽仍保留费用；并行等待所有结果并保留完成 step；预算采用共享预留。
- project-planner 使用同一预算守卫，规划账目见 `/project-planning`；失败不发布空 project。账目在 P2 已接入持久化。
- diff 使用 run 起始/current 临时 Git index/tree 对比，不修改用户 index，排除秘密路径并将已识别密钥内容替换为可见脱敏标记；大文件/二进制改动显示 metadata，排除开始前的用户改动。同一 workspace 的并发用户修改仍需 worktree 隔离（§16.4）。
- memory 使用退役与 superseded_by 保留旧版本；chunk 严守长度上限；模型 schema 使用合法 JSON。
- SQL 增补 project.goal/phases、global nullable project_id、memory document/note/source；兼容迁移 0002 已在本地数据库应用。
- 上一批验收：后端 99 项、前端 17 项；类型、lint 与构建通过。修复后真实模型 smoke 1/1，一轮 signoff，原测试未改且 FULL Gate 通过。

### 16.2 已知缺口（P0 中有配置或骨架，但尚未接线）

| 项 | 现状 | 归属 Phase |
|---|---|---|
| 持久化 | P2 已完成；配置数据库 URL 后启用，显式 memory 模式仍为临时数据 | 已完成 |
| 浏览器内上传 | 自动化测试工具无法驱动 file input；API 层已测（curl + pytest） | — |
| CLI 审批 / resume | status / show / resume / decide 已实现 | 已完成 |
| supervisor（root）角色 | 项目 auto 模式调用并持久化 Dispatch；角色模型与任务经过确定性校验，非法分配需人类填写反馈后 reject 重生成，phase 顺序仍由 Driver 执行 | 已接线 |
| summarizer 角色 | 配置有，Driver 尚未调用；现在的 project/agent 记忆由确定性规则写入 | P6 |
| 工具白名单 `tool_grants` | 已配置，未强制执行（当前 agent 无工具调用） | P3 |
| 危险操作卡点 `dangerous_ops_require_approval` | 已配置，未强制执行 | P3 |
| `AdkRuntime` | 仅占位，调用即 NotImplementedError | P3 |
| Gate 镜像 | Python 镜像与 Docker Gate 已实测；其余语言尚未建镜像 | P5 |
| Gate 诊断表、成本看板 | UI 未做 | P4 |
| `step.prompt_ref / response_ref` | prompt / response 内容寻址并落库；逐 attempt 可追溯 | 已完成 |
| UI 类型 | 手写 TS 类型，未用 openapi-typescript 生成 | P4 |

### 16.3 接下来的步骤

#### P1 · S0 Walking Skeleton（Python 固定任务验证完成）
目标：真实模型 + 真实沙箱，Coder 把一个小 repo 的失败测试改绿。
- [x] Colima 启动；`docker compose up` 起 Postgres + pgvector
- [x] 用户提供网关：`.env` 填 `AGENTLAB_LLM_BASE_URL` / `AGENTLAB_LLM_API_KEY`；`config/models.yaml` 填真实模型 id
- [x] `agentlab ping`：对每个别名发一次最小请求，验证连通、JSON 输出、usage 字段
- [x] 用真实网关跑 `RawRuntime`，修正 prompt 格式与结构化输出问题
- [x] 建 `docker/gate-python` 镜像；Gate 默认走 `DockerSandbox`
- [x] Planner / Coder / Reviewer 输入加入当前文件内容（有大小上限，排除隐藏文件、敏感文件名、二进制与软链接）
- [x] 准备 `evals/tasks/py-fix-add` 作为第一个固定任务
- 演示：`agentlab run "make tests pass" -w <小repo>` 用真实模型改绿
- 完成标准：真实模型下 3 次运行中至少 2 次自动收敛到 signoff

#### P2 · S1 持久化 + 断点续跑（1–2 天）
- [x] `PostgresStore` 实现 `core/ports.py::Store`，与 `InMemoryStore` 跑同一套测试
- [x] Alembic 接管 `0001_init.sql` 与后续迁移（包含 `0002_model_alignment.sql`）
- [x] baseline tree 引用、独立 Git 对象库及 workspace/Git 根目录归属持久化；重启恢复沿用原 baseline，不重新捕获用户当前文件
- [x] 冻结的 reviewer batch 输入和已成功结果落库；恢复只补跑缺失 reviewer，不重新检索记忆或重复计费
- [x] run 费用/token、逐 attempt usage、预算/迭代上限调整与 project-planner 账目落库；未返回 usage 的在途请求显式记为结算未知，不声称 exactly-once 计费
- [x] 恢复操作使用事务与运行锁，防止多个 driver 同时续跑；重启后保留 WAITING_HUMAN 与 pending approval，不自动批准
- [x] 验收覆盖预算暂停、部分评审成功、execution_error 和 signoff 等断点，并验证 reject/abort/终止的缓存及对象库清理
- [x] prompt / response 写入 blob，`step.prompt_ref / response_ref` 落库
- [x] `kill -9` 后 `agentlab resume <run_id>` 从 `run.status` 继续
- [x] CLI：`resume / status / show / decide`
- 演示：真实小 repo 跑到一半 kill -9，resume 后完成

#### P3 · S2 评审团真实化 + HIL（2–3 天）系统真正形态
- [x] 3 个 reviewer 并行、互相不可见（fake 下验证）
- [x] Arbiter 冲突打包升级（fake 下验证）
- [x] 审批流：approval 表结构 + API 审批
- [ ] 3 个 reviewer 用不同模型别名真实运行
- [ ] supervisor 接入：仅在 policy 允许处做调度 / override 决策，决策写 `routing_reason`
- [ ] 工具层（MCP）+ `tool_grants` 强制 + 危险操作走 approval
- [ ] LiteLLM Proxy + per-project virtual key
- [ ] `AdkRuntime`（ParallelAgent + before_model_callback 熔断）
- 演示：一个带安全隐患的改动，三方结果并排展示

#### P4 · S5a 可视化 v0 收尾（0.5–1 天）
- [x] SSE 事件流、Office Floor 接事件流、Run 列表 / 时间线、评审对比、审批横幅
- [ ] Gate 诊断表（file:line、code、message）
- [ ] 成本与 token 看板（按 run / 角色 / 模型）
- [ ] openapi-typescript 生成类型，替换手写类型

#### P5 · S3 多语言 Gate（每语言 0.5–1 天）
- [x] 4 种语言 Gate YAML
- [ ] `docker/` 下 node / jdk / cpp 镜像
- [ ] 按顺序实测 TypeScript → Java → C++（ccache、compile_commands.json、分级超时）
- 演示：同一套 loop 在 4 种语言的 repo 上跑通

#### P6 · S4 Memory + Project 化（2–3 天）
- [x] memory / blackboard 表（DDL）
- [x] 三层作用域 global / project / agent，Driver 注入（内存版）
- [x] Global 文档上传（PDF / md / txt）+ 切块 + 网关 embedding + BM25∪向量 RRF（内存版）
- [x] project-planner 生成 phase/step；run 完成自动更新进度
- [ ] 把以上三块落到 Postgres（`memory` 表 + pgvector HNSW + tsvector；`project` 表加 phases JSONB）
- [ ] summarizer 接入，每轮自动抽 episodic
- [ ] `pin_memory` 工具；rerank
- [ ] per-project schema、`pg_dump -n` 导入导出
- 演示：第二个 project 复用第一个 project 沉淀的经验

#### P7 · S5b 可视化 v2 + 可观测（2–3 天）
- [~] Memory Graph 已移植（等 P6 提供数据）
- [ ] React Flow step 树、Monaco diff、iteration 回放
- [ ] Langfuse（OTel）

#### P8 · S6 Eval（持续，P1 起就开始积累）
- [ ] 10 个固定回归任务；`agentlab eval` 输出评分卡
- 评分卡结构（摘自 homerail `scorecard.ts`，无需再查原 repo）：每项 check = `{name, passed, severity(hard|soft), gate, source_type, detail}`；汇总 = `{run_id, passed, verdict, score, total, hard_error_count, soft_warning_count, blind_spot_count, categories: {name: passed}}`；任一 hard 失败即 FAIL，soft 只计数；CLI 退出码 = passed ? 0 : 1，便于 CI

---

## 16.4 项目级调度模式与隔离要求（2026-10-09 补充）

用户要求两种模式，创建 project 时选择，并能在控制台修改后用于后续 run：

| 模式 | 用户配置 | 调度行为 |
|---|---|---|
| Root 自动分派 | root 模型、项目目标、可用模型目录与预算 | root 在允许的模型目录中选择其他 agent 的模型、分配任务；决策结构化校验并记录 |
| 完全手动 | root 及其他 agent 的模型与任务 | 严格执行用户的角色/模型/任务绑定，root 不自行改写绑定 |

模型目录为平台共享的可用 model ID 和能力/价格信息；模型与任务绑定为 project 私有配置。root 使用 supervisor 角色；project-planner 随该项目 root 配置。预算、Gate、评审收敛与危险操作审批继续由确定性代码执行。手动绑定不得被未授权 fallback 改变。创建 run 保存配置快照；控制台修改仅影响新 run。

界面：左侧常驻 project 列表，展开显示该项目的对话；中央显示当前对话与 Office，右侧控制台显示当前项目的模型、任务与审批。对话需独立 thread_id 与消息历史，thread 下可有多个 run；现有 run 时间线不等同于对话。

隔离：project 各自拥有 workspace、模型/任务配置、对话、运行记录、预算与记忆；agent 私有记忆按 project × role 归属。global 知识为明确共享的个人知识，项目私有文档不得进入 global。切换 project 同步切换 run、agent 状态、事件、看板、审批和检索范围；后端校验 project/thread/run/step 归属。workspace 路径重叠需要检测；并发修改同一仓库需要独立 worktree/沙箱。

workspace 子目录边界已在 P2 修复：`ensure_repo` 使用 `git rev-parse --show-toplevel`，拒绝已有 monorepo 内的非根目录 workspace，不创建嵌套仓库。子目录范围支持仍未实现；本轮已拒绝项目 workspace 重叠，提示使用独立 worktree。

2026-10-10 UX / E2E 实现与检查结果：

| 用户路径 | 本轮实现 | 验证与边界 |
|---|---|---|
| 创建 project → 配置 agent | 新建表单与控制台均可选 auto/manual、root、模型目录、各角色任务、budget/max_iter、检索模式/k | manual 必须绑定全部 worker，禁用 fallback；project-planner 使用项目 root。角色集合固定，summarizer 尚未接入循环 |
| auto → run → 恢复 | supervisor 输出 Dispatch，限制在模型目录与 reviewer tier 范围；artifact、分配、输入与 run 配置一起 checkpoint | fake E2E 和 Postgres 重建 Services 验证；本轮新增调度尚未做真实网关验收 |
| 左侧 project → 对话 → run | Conversation/Message 持久化；thread 可关联多 run；用户目标与终止状态写入历史，最近 20 条作为下一 run 上下文 | project/thread 归属先验证，消息与 run 创建同事务；目前是任务对话，不是通用即时聊天 |
| 切换 project | 清空 active run/thread、事件、telemetry、审批、任务、选择和答案草稿；重新加载项目 roster 与 runs | Vitest 与浏览器验证；异步响应守卫，组件唯一 key；私人便签按 project × role 分开 |
| 同 workspace 多 run | 未完成 run 占用 workspace，新 run 返回 409；同一项目须结束/abort 当前 run，或者另建 worktree | 创建 run 时在 workspace 锁内检查。禁止重叠 project；外部编辑器/进程不受此锁约束 |
| 人工终审 | 控制台可查看实际 diff、plan、dispatch、review、Gate 等 artifacts；审批保留 budget/max_iter 与错误反馈 | 浏览器看到 calc.py 的实际代码变化；纯文本 viewer，Monaco/回放仍未实现 |
| memory 文档 | global 明确共享；project 上传/替换/移除仅影响本项目，保留历史版本；agent 私有记忆需 project | 相同文档名跨项目隔离测试，移除文档不误删同 source 的 note |
| RAG | 项目选择 off / keyword / hybrid，默认 keyword；检索按项目与角色授权范围，失败降级 | 混合检索的向量仍在 Python 中做 cosine + BM25/RRF；Postgres 持久化不等于已使用 pgvector HNSW |
| embedding 配置 | 独立 embedding URL/Key 保存至本机 .env；模型/维度/version 在 models.yaml；可测试接口、重建共享知识与项目/agent 记忆向量 | 有凭据不等于可用：只有实际调用成功才 ready；当前没有可用 embedding 服务，真实向量验收需用户补充 |
| 配置即代码 | 控制台支持项目设置 YAML 导出/校验导入，适合提交 Git；run 固化完整配置 | 全局模型能力/价格仍在 config/*.yaml，项目选项是持久化运行数据。导入不改变已存在 run |

本轮检查可复现：后端 `tests/unit/test_project_experience.py`、Postgres `test_project_dispatch_and_conversation_survive_postgres_restart`，前端 `store.test.ts`；浏览器在隔离 fake 服务验证了创建 auto/manual 项目、对话启动、审批、实际 diff 和项目切换。测试 workspace 与 UI 服务数据不写入生产项目。

剩余需要产品确认或外部资料：
- 用户提供可调用的 embedding URL、Key、model ID、维度，再做真实混合检索验收与 pgvector 索引选择。当前网关的聊天模型不能代替 embedding 模型。
- 项目目前共享 Postgres 表，通过 project_id 隔离，并非 §9 目标中的每项目物理 schema；升级物理隔离需选迁移策略，不能对现有数据直接假定完成。
- 当前所有聊天别名映射 gpt-6-astra；输入独立，不代表跨模型多样性。新增 Claude 等 provider 后仍需明确 provider/routing 配置。
- ADK、工具白名单执行、危险操作审批、summarizer、memory pin UI、全量 memory 导入导出、其他语言 Gate 镜像和 Monaco/iteration 回放仍是后续工作。当前不会开放任意 agent 工具来绕过安全边界。

---

## 十七、可参考的开源项目

| 目标 | 参考 | 重点看 |
|---|---|---|
| ADK 多 agent 编排 | google/adk-python + adk-samples | ParallelAgent / LoopAgent、callbacks、LongRunningFunctionTool |
| 收敛 loop 与 Gate | OpenHands、SWE-agent | 动作空间、沙箱执行器、测试反馈回灌格式 |
| 代码编辑与 diff 应用 | Aider | repo map、edit format、commit 策略 |
| 多模型路由与预算 | BerriAI/litellm | proxy virtual key、budget、retry、fallback |
| 沙箱 | OpenHands runtime | Docker 隔离、网络策略、挂载 |
| Trace | langfuse/langfuse | OTel ingest、self-host compose |
| Hybrid 检索 | pgvector 官方示例 + RRF | HNSW 参数、tsvector 融合 |
| **可视化** | **munder-difflin**（已移植完毕，见 §15.2 与 `ui/THIRD_PARTY_NOTICES.md`） | Pixi office floor、状态→动画映射、像素设计系统 |
| **DAG 严格语义** | **homerail**（已消化完毕，ADR-014 + P8 评分卡结构） | WorkflowSpec 严格校验、while 静态上限、command 白名单、scorecard/replay |

---

## 十八、风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| ADK 无图级 checkpoint | 复杂回放受限 | Loop Driver 自管状态机 + artifact 内容寻址 |
| ADK HIL 需手写样板 | 开发成本 | HIL 走 `approval` 表 + run 状态 |
| ADK 版本迭代快 | 升级痛 | `AgentRuntime` 接口隔离；保留 raw runtime |
| C++ Gate 构建慢 | 每轮几分钟 | ccache + 持久 build volume + fast/full 两档 |
| 三个 reviewer 成本高 | 烧钱 | Gate 前置 + 第三 reviewer 廉价档 + 硬预算 |
| 多模型结构化输出格式不一 | 解析失败 | Pydantic + `max_repairs=2` + 能力矩阵降级 ReAct |
| 云端全量依赖 | 断网即停摆 | retry=3 + fallback + run 可暂停续跑 |
| Reviewer 无限挑 nit | 永不收敛 | `blocking + major == 0` 即 signoff |
| 单网关单 key（v1.1） | 网关限流影响所有角色 | 角色级 RPM 配置 + 预算中间件；reviewer 并发可配 |
| munder 移植代码量大（~5.6k 行场景 + 组件） | 维护负担 | 只改数据适配层，场景代码尽量保持原样便于对照上游 |
| LimeZu 素材许可（v1.1） | 开源分发受限（"不可再分发素材"） | 开源前评估：替换为自绘/CC0 素材或要求使用者自购；署名常驻 |

---

## 十九、待办与开放问题

- [x] 网关 URL / key 与模型 id 已配置，P1 已验证；更多模型由用户后续补充。
- [ ] 网关是否提供 embedding 端点？否则 S4 需额外 embedding 来源
- [ ] C++ Gate 的 GTest 发现策略：CTest 注册 vs 直接跑二进制
- [ ] Java 项目 Maven 与 Gradle 优先级
- [ ] 是否需要"同一 reviewer 跑两次取一致性"（成本翻倍，先不做）
- [ ] 开源前清单：移除个人路径、示例 config、LICENSE、最小可复现 demo repo、**LimeZu 素材替换方案**

---

## 附录：决策记录（ADR 摘要）

| # | 决策 | 日期 | 理由 |
|---|---|---|---|
| ADR-001 | 编排用「自研 Loop Driver + Google ADK 执行层」 | 2026-10-09 | ADK 的 ParallelAgent、Callbacks、MCP 契合度高；checkpoint 短板由自研状态机补齐 |
| ADR-002 | Python 后端 + TypeScript 前端 | 2026-10-09 | ADK 生态为 Python；前端仅作观察窗 |
| ADR-003 | 不跑本地模型，全部云端 API | 2026-10-09 | 降低硬件与运维负担 |
| ADR-004 | 客观 Gate 前置于 LLM 评审 | 2026-10-09 | 砍掉 60–70% 无效评审轮次 |
| ADR-005 | `blocking + major == 0` 即 signoff | 2026-10-09 | 防止多 reviewer 在 nit 上死循环 |
| ADR-006 | 熔断用确定性中间件，不用 agent | 2026-10-09 | 非确定性的熔断等于没有熔断 |
| ADR-007 | LLM retry = 3（额外重试，共 4 次请求），仅瞬时错误 | 2026-10-09 | 区分可重试与不可重试；JSON 修复独立预算 |
| ADR-008 | 支持 Python / TS / Java / C++，Gate 做适配器 | 2026-10-09 | 目标代码库多语言 |
| ADR-009 | 记忆归属 `project × role` 而非 agent 实例 | 2026-10-09 | agent 是任务级临时实例 |
| ADR-010 | 记忆版本化（`superseded_by` / `valid_to`），不物理删除 | 2026-10-09 | 可回溯；开源后可审计 |
| ADR-011 | 前端全量借鉴 munder-difflin 可视化（Pixi Office Floor + 像素设计系统 + 看板/瀑布/记忆图） | 2026-10-09 | 成熟实现，MIT；素材按 LimeZu/OFL 署名 |
| ADR-012 | 单一 OpenAI 兼容网关 + 角色→别名→模型 id 三级映射 | 2026-10-09 | 用户同一 endpoint 不同模型；换模型零代码改动 |
| ADR-013 | 容器运行时用 Colima + docker CLI | 2026-10-09 | 本机无 Docker Desktop，轻量 |
| ADR-014 | 配置严格校验、循环静态上限、命令白名单（借鉴 homerail） | 2026-10-09 | 配置即代码的前提是"写错就报错" |
| ADR-015 | 不做语音、不做 Electron 跨平台壳 | 2026-10-09 | 范围收敛，前端为 localhost Web |
| ADR-016 | 新增 `event` 表作为可视化/回放唯一事件流 | 2026-10-09 | Office Floor、Run 树、TUI 共用一个数据源（DRY） |
| ADR-017 | UI 用 Adapter 模式重实现 `window.cth`，而非改写 munder 场景代码 | 2026-10-09 | 场景 ~5.6k 行保持原样，改动集中在 `bridge.ts` + `scene/adapter/mapping.ts` |
| ADR-018 | Gate 步骤由 `config/gates/*.yaml` 声明，单一 `ConfigGate` 执行 + 按工具选诊断解析器 | 2026-10-09 | 新增语言 = 加 YAML + 镜像，不加类（OCP） |
| ADR-019 | 人工 reject 后重置本轮迭代计数（`run.iteration_base`），震荡检测只看当前轮 | 2026-10-09 | 人给了新信息，不应因旧历史立即判定震荡或超限 |
| ADR-020 | 记忆三层作用域 global / project / agent:<role>，检索取并集 | 2026-10-09 | 用户要求：个人简历全局可读、project 有整体进度、agent 有本地记忆；所有 agent 可读 global（用户确认） |
| ADR-021 | project-planner（root 模型）自动生成 phase/step；run DONE 自动打勾 | 2026-10-09 | 用户选择"planner 自动生成"；手动改状态作为兜底 |
| ADR-022 | 控制台做精简版（8 标签），不整体移植 CommandCenterPanel | 2026-10-09 | 用户选择；原版大半依赖 PTY / 触发器 |
| ADR-023 | API key 由 UI 写入本地 `.env`（chmod 600），后端只回 mask | 2026-10-09 | 用户选择 .env；最简单且已在 .gitignore |
| ADR-024 | memory 故障降级为关键词检索，hook 异常不改变 run 结果 | 2026-10-09 | 实测：网关不可达时 embedding 报错曾导致 run 卡死 |


### 可靠性复核补充（2026-10-09）

- workspace 路径对原始路径和 resolve 后路径 casefold，禁止大小写别名写入 `.env*` / `.git` 等保留路径；密钥后缀精确匹配 `.pem` / `.key`，普通 private/secret 文件名允许编辑。
- 临时 index/tree 由 Git 捕获实际文件，不以文本上下文筛选结果决定 diff。大文件/二进制/脱敏内容保留改动标记与 Git metadata；文件读取失败直接暂停，不伪装成删除或未变。Git 操作有 30 秒超时；异步 diff 和 API baseline 捕获在工作线程，事件发布留在事件循环。
- 成功输出即使实际费用超估算也交给 handler；下一批调用按完整预估预检，输入与输出按每个模型别名的可配置系数估算。reviewer batch 的输入（含记忆）冻结；部分成功结果缓存并只重跑缺失项，不重复记账；缓存仍随内存运行态，重启恢复由 P2 实现。
- 项目规划成功但实际超预算时保留 plan，`/project-planning` 账目记录 `budget_overrun`；调用前仍检查预算。价格和 token 预估不等于网关结算保证。
- minor/nit 不参与冲突判断。subject 采用固定动作词表，词表外值确定性归一为 "" 并记脱敏日志，不导致整个 Verdict 校验失败；仅对同一 file/subject 的相反 stance 升级；未识别的矛盾不声称自动语义识别。reviewer_conflict / inconsistent_verdict 批准须提供反馈。
- 模型别名可配置 `max_output_tokens`（当前 16384）和 `output_token_parameter`（`max_tokens` 或 `max_completion_tokens`）。大文件完整替换需按网关能力提高输出上限与预算；100KB 是文件写入上限，并不保证所有模型一次能够输出。finish_reason=length 明确暂停并记账，不回灌截断 JSON 重试。
- reviewer 子调用取消会作为 agent_cancelled 暂停并保留其他结果，不可将部分 verdict 当成完整评审；外层任务取消仍传播取消信号。

上一轮复核验收：后端 120 项、前端 17 项，ruff / mypy / UI build 通过；真实模型 Docker smoke 1/1，一轮 signoff，原测试未改且 FULL Gate 通过。


### Git 评审完整性复核（2026-10-09）

已替换文本快照拼接；新增大文件缩小、二进制/大文件变更与删除、mode 变化、ignored Coder 文件、用户 staged index 保留、密钥不落入新 Git blob、跨行冲突、未知 subject、可配置估算、事件线程与缓存冻结/清理的回归用例。reject/abort/终止会清理 run 的缓存；已成功交付的 batch 立即释放输入快照。Git baseline tree ID 与 batch 仍需 P2 持久化才能跨重启恢复。

上一轮验收：后端 132 项、前端 17 项，ruff / mypy / UI build 通过；真实模型 Docker smoke 1/1，一轮 signoff，原测试未改且 FULL Gate 通过。


### 子仓库与快照性能复核（2026-10-10）

- 子模块和内嵌仓库使用原生 mode `160000` + 子仓库 HEAD；未初始化的 gitlink 保留 index 中的 commit。无 HEAD 的内嵌仓库展示可见标记；dirty 子仓库展示状态/patch 指纹，父 project 的 Coder 禁止写入子仓库（包含 gitlink 根路径、后代路径和符号链接别名），统一 WorkspaceEscape 审批；内部编辑和详细评审必须在该子仓库运行独立 project。审批不授予父 project 对子仓库的写权限。
- 文件先做密钥检测和脱敏，再通过单次 `hash-object -w --no-filters --stdin-paths` 批量哈希；index 与 object database 均隔离在临时目录，不往用户 `.git/objects` 写入快照对象。objects 通过只读 alternate 引用原仓库，run 终止/abort 释放临时对象，进程退出由临时目录生命周期回收。P2 须同时持久化对象库和 tree 引用，不能只保存 tree ID。
- 本机 2000 小文件基准：begin_run 1.321s，单文件改变后的 diff 0.590s，父仓库新增对象 0。回归校验每次 snapshot 仅一个 hash-object 请求，父仓库 objects/index 不变；测试不依赖易波动的时间阈值。
- 文件不可读使用 `workspace_unreadable`，与 `workspace_escape` 区分；API baseline 不可读返回 422 和安全错误类型，而非 500。
- execution_error 批准重试仍保留同一批冻结输入和成功结果，避免再次付费；该批缓存不因反复批准而新增条目。成功交付、reject、abort、终止清理。P2 持久化须保留上述生命周期，并为长期暂停运行设计显式归档/清理机制。

上一轮验收：后端 141 项、前端 17 项，ruff / mypy 通过；真实模型 Docker smoke 1/1，一轮 signoff，FULL Gate 通过，原测试未改。


### 子仓库写入边界补充（2026-10-10）

- apply_edits 在写入任何一个文件前验证全部路径：结合 parent index 中的 160000 gitlink 与解析后祖先目录的 .git 标记，拒绝父 project 的子仓库编辑。未初始化子模块和无 HEAD 的内嵌仓库同样受保护；独立子仓库 project 不受父仓库标记影响。
- 仅 WorkspaceUnreadable 使用 workspace_unreadable；带 workspace_escape kind 的权限异常仍进入越界审批，磁盘写满等其他 OSError 使用 execution_error。
- API 将仓库初始化和 baseline 捕获共同纳入错误处理；Git CalledProcessError / TimeoutExpired 返回 503 + 安全错误类型，并清理临时对象目录，不发布半创建的 run。明确的不可读/越界错误返回 422。

本次验收：后端 152 项，ruff / mypy 通过；新增 11 个回归用例覆盖写入边界、独立子项目、磁盘写满与 API 创建失败清理。


### 16.1h · P2 持久化验收（2026-10-10）

- PostgresStore 与 InMemoryStore 共用事务回滚、事件序号、审批、checkpoint 和运行锁契约。Alembic 接管既有 SQL；迁移版本表按当前 schema 隔离。
- `.agentlab/snapshots/<id>` 保存脱敏 Git 对象与原 baseline；数据库保存 tree/metadata、冻结输入、已成功结果、配置及 prompt 快照。成功结果保存到阶段处理完成，阶段数据与状态在同一事务提交，事件在提交后发布。
- 每个网络 attempt 在发送前记录 in_flight；返回 usage、响应和累计费用在同一事务提交。有效响应在 AgentResult 写入前崩溃也可恢复。未返回 usage 的请求保留结算未知并进入 interrupted_call 审批，批准仅授权重试，无法保证网关 exactly-once 计费。
- 预算、迭代调整、项目规划草稿/结果与逐次 usage、文档版本和来源删除均持久化。记忆检索沿用 BM25/cosine + JSON embedding；SQL 向量检索优化未包含在 P2。
- CLI 支持 db-upgrade / status / show / resume / decide；API 支持重启后的 decision 与 resume。WAITING_HUMAN 不自动批准；reject/abort 清理缓存，终止释放对象，长期暂停通过显式 abort 清理。需共同备份数据库与 `.agentlab`，对象库缺失会拒绝恢复。
- 15 项集成用例覆盖 Store 契约、预算、部分评审、execution_error、signoff、结算未知、规划失败 usage、版本化记忆、多进程记忆刷新、API 重启审批、reject/abort 清理与真实 kill -9。
- 真实网关 + Docker 恢复 smoke：run `6b2e0c696274`，付费 planner 返回后 kill -9，CLI resume 后 FULL Gate 通过、停在 signoff；planner step 仍为 1，累计 8451 input / 631 output tokens，按配置估算 5.4875c。未代替用户批准最终 signoff。
- Smoke workspace 放在 `~/.agentlab-workspaces`，避免 macOS 临时路径无法被 Colima 挂载，以及在父仓库中意外创建嵌套仓库。
- 历史 §16.1d–g 中“P2 待持久化”的说明记录的是当时状态；由本节更新。当前总验收：后端 167 项、前端 17 项，ruff / mypy / UI build 通过。
