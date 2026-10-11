# Multi-Agent Platform Discovery

> 状态：v1.11 · P0 / P1 / P2 完成；v1.6 新增 Root 会话入口（§2.5、ADR-025）；v1.7 新增 Monitor 模块（按 agent 统计 token，§15.5、ADR-027）；v1.8 已接入 summarizer 与删除项目（§9.1、ADR-028）；v1.9 决定 Gate 改为可选、取消多语言 Gate（§4、ADR-029），embedding / rerank 默认本地运行（§7.4、ADR-030），开源前替换所有可能侵权的素材与影视 IP（§15.6、ADR-031）；v1.10 每个 run 使用独立 worktree，同一仓库可并行多个任务，取消工具调用次数上限（§16.5、ADR-033）；接入 MCP：GitHub 与 Fetch（§16.6、ADR-034）；v1.11 开发能力补强：空交付暂停、停止按钮、coder 只读外部工具、项目检查命令（§16.7、ADR-035）· 可持续更新
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

## v1.6 变更摘要（2026-10-10，目标不变，补充交互入口）

| # | 变更 | 原因 | ADR |
|---|---|---|---|
| 1 | 新增 **Root 会话层**：用户在对话中只与 root 交流；root 每轮判断意图——**回答**（只读工具检索后直接回复）、**澄清**、或**任务**（交给收敛 Loop） | 原设计中每条消息都会进入编码流水线，问答无法得到回复；参照 Codex / Claude Code 的单一会话入口 | ADR-025 |
| 2 | 对话窗口显示 root 的回复、任务进度与内联审批，而不只是 run 状态 | 对话是主要交互界面 | ADR-025 |
| 3 | 上网搜索直接使用模型 / 网关自带的搜索能力，不单独接搜索服务 | 实时信息（如天气、最新文档）需要搜索；保持简单 | ADR-026 |
| 4 | （v1.7）新增 **Monitor 模块**：按 agent 统计累计消耗的 token（跨所有 project 汇总，不按 project 区分） | 了解哪个 agent 用得最多，便于调整模型与分工 | ADR-027 |
| 5 | （v1.8）**summarizer 接入**：每个 run 结束时从人工反馈与 review findings 总结经验，按重要性写入 global / project / agent，写入时去重并退役旧条目；新增**删除项目**，项目记忆随项目一起删除 | 记忆目前只有固定规则写入的流水，没有整理与归纳；项目无法删除 | ADR-028 |
| 6 | （v1.9）**Gate 改为可选**：有匹配的 Gate（目前只有 Python）就照常运行；没有就跳过 GATING，由 reviewer 评审 + 人工终审收敛，终审时标明「未经过自动测试」。取消 P5 多语言 Gate（TS / Java / C++ 镜像） | 任务可能是任何语言的项目（如 Go），不应因没有 Gate 配置而无法创建 run；参照 Claude Code，不为每种语言预先准备工具链 | ADR-029 |
| 7 | （v1.9）**embedding / rerank 默认在本地运行**（进程内 CPU 小模型），在 Settings 填写远程 OpenAI 兼容接口时改用远程；都不可用时仍降级为关键词检索 | 其他用户无需申请任何 key 即可使用向量检索；pgvector / rerank 不再等待外部 embedding 服务 | ADR-030 |
| 8 | （v1.9）**开源前替换所有可能侵权的内容**：LimeZu 办公室 tileset 与基于它的地图、《The Office》/《Brooklyn Nine-Nine》主题名、角色名与形象、剧中台词与梗；改为授权干净（CC0 等）或原创的素材、主题与角色 | LimeZu 许可禁止再分发；影视剧名、角色与台词属于 NBC 等权利人，开源分发有商标 / 版权风险 | ADR-031 |
| 9 | （v1.10）**每个 run 一个独立 Git worktree**：同一仓库可同时进行多个任务（包括等待审批的任务），互不阻塞、互不覆盖；批准 signoff 时只把该任务自己的改动应用回你的工作目录，有冲突就停下。另：取消工具调用次数上限，自主开发只由预算约束 | 用户需要在同一项目里并行工作；旧规则让一个等待审批的任务挡住所有新任务 | ADR-033 |
| 10 | （v1.10）**接入 MCP 工具服务器**：GitHub（官方 github-mcp-server）与 Fetch（读取网页）；只读工具直接执行，会改动外部状态的工具在对话中弹出「允许 / 拒绝」后才执行；Root 与 planner 可用（planner 只有只读工具） | 让 agent 像 Codex / Claude Code 一样核验 GitHub 仓库与网页内容，而不是声称无法访问 | ADR-034 |

---

## 一、项目定位与设计原则

| 维度 | 决定 |
|---|---|
| 定位 | 个人本地 dev/研究工具，未来开源 |
| 交互入口 | 对话中只与 root 交流；root 每轮判断「回答 / 澄清 / 任务」，回答直接回复，任务交给收敛 Loop（§2.5） |
| 核心 MVP | Planner + Coder + Reviewer 的收敛 Loop |
| 拓扑 | Supervisor（root）自动分派，调度逻辑抽成独立 policy 层（auto / manual 两种 policy） |
| 消息 | 结构化对象，传 `artifact_id` 引用，**不传全文** |
| Agent 生命周期 | 任务级临时实例；记忆宿主为 `project × role`，不是实例 |
| 完成判定 | 所有 reviewer signoff（severity 阈值）→ 人工终审；有 Gate 时还需 FULL Gate 通过，无 Gate 时终审标明未经过自动测试（v1.9，§4） |
| 冲突 | 升级给人 + 震荡检测自动触发升级 |
| Memory | Blackboard + Episodic + Semantic（MVP）；Procedural 延后 |
| 隔离 | per-role namespace 私有 + 共享黑板；per-project Postgres schema |
| 记忆写入 | 每个 run 结束时 summarizer 从你的反馈与 review findings 总结经验，按重要性写入 global / project / agent，并去重、退役旧条目（§9.1）+ `pin_memory` 手动工具 |
| LLM | **纯云端调用，本地不跑 LLM**；单一 OpenAI 兼容网关（LiteLLM Proxy 统一出口）。例外（v1.9，ADR-030）：embedding / rerank 小模型默认在本地 CPU 运行，可改用远程接口 |
| 路由 | 静态 policy 表（角色→模型别名）+ root agent 受限 override（可复现优先） |
| 多模型评审 | 2–3 个不同 LLM 并行独立 review（核心卖点） |
| 预算 | 确定性中间件熔断 + LiteLLM virtual key 周限额，**不用 agent 做熔断** |
| 安全 | Docker 沙箱 + 只读挂载 + 默认断网 + 工具白名单；密钥永不进 agent 进程 |
| 运行形态 | 本地 daemon（CLI/TUI 为主）+ localhost TS UI（可选视图，非运行时依赖） |
| 可视化 | Office Floor（Pixi）+ Run 树（React Flow）+ 看板/评审对比 |

### 四条不可妥协的设计原则

1. **确定性的事情不交给 LLM**：预算熔断、收敛判定、震荡检测、重试、路由，全部是普通 Python 代码。root 判断「回答还是做任务」属于语义判断，交给 LLM（§2.5）。
2. **配置即代码**：YAML + git 管理 agent 定义、模型策略、工具授权；DB 只存运行时状态。配置在加载时严格校验，未知字段直接报错。
3. **便宜的检查先跑**：项目有 Gate 时，编译、类型、lint、测试在 LLM 评审之前，失败直接退回，不花一个 reviewer token。没有 Gate 的项目跳过这一步（v1.9，ADR-029），不因此拒绝任务。
4. **一切可回放**：step 树 + artifact 内容寻址 + 事件日志，任何一次 run 都能重放和 diff。

---

## 二、编排框架：Google ADK vs LangGraph

**结论**：自研 Loop Driver + Google ADK 作为 Agent 执行层的分层方案。复杂部分（Gate、severity 收敛、震荡、熔断、人工卡点）全是确定性逻辑；框架只需做好：调模型、挂工具、并行跑 reviewer。

### 分层结构

```
Layer 4  Root Session（交互层 · v1.6，§2.5）
  每条用户消息 → root：回答（查文件 / 记忆 / 上网后直接回复）| 澄清 | 任务（分配给 Layer 3）
  职责：理解意图、回答问题、把任务进度与审批带回对话

Layer 3  Loop Driver（自研 · 纯 Python · 无框架依赖）
  状态机：PLAN→CODE→[GATE（有则运行）]→REVIEW→ARBITRATE→HUMAN→DONE
  职责：收敛判定、震荡检测、迭代上限、预算熔断、HIL 卡点、断点续跑（Postgres run / iteration）

Layer 2  Agent Runtime（Google ADK，可替换）
  LlmAgent(Planner/Coder/Reviewer×N/Summarizer/Arbiter)
  ParallelAgent 跑评审团 · Callbacks 做中间件 · MCPToolset 挂工具

Layer 1  Model Gateway（LiteLLM Proxy → 单一 OpenAI 兼容上游）
  统一 OpenAI 格式 · 角色→模型别名 · retry=3 · per-project virtual key 预算与 RPM · 密钥隔离
```

框架隔离接口 `core/ports.py::AgentRuntime`，实现：`adapters/runtime/adk.py`（默认）、`adapters/runtime/raw.py`（兜底，直接 OpenAI SDK）、`adapters/runtime/fake.py`（测试/离线骨架）。

---

## 2.5 Root 会话与意图分流（v1.6 新增，ADR-025）

**问题**：v1.5 及以前，对话里的每条消息都会创建一个编码 run（Planner → Coder → Gate → 评审 → 人工终审），对话中只记录用户原话和 `Run <状态>` 系统消息。用户问一个问题得不到回答，反而触发一整轮流水线。

**目标形态**（参照 Codex / Claude Code）：用户在对话里只和 **root** 说话，像和一个助手聊天。root 自己判断这条消息该怎么处理：能直接回答就回答；需要改代码就把任务分给 multi-agent 团队，并在对话里汇报进度；拿不准就问一句。用户也可以直接说「只回答就行」或「直接改」，root 照做。

分工原则：root 负责理解和沟通，**不自己写代码**；编码交给 §3 的收敛 Loop（Planner / Coder / Gate / 评审 / 人工终审）。

### 2.5.1 流程

```
用户消息 ──▶ root
              ├─ 回答 ─▶ 需要时查项目文件、记忆或上网搜索 ─▶ 直接回复（附来源）
              ├─ 澄清 ─▶ 问用户一个问题
              └─ 任务 ─▶ 回复「我理解的任务」─▶ 分配给 multi-agent 团队（创建 run）
                            └─▶ 进度、审批、最终结果回到同一个对话
```

### 2.5.2 root 的输出（RootTurn）

| 字段 | 含义 |
|---|---|
| `intent` | `answer` / `clarify` / `task` |
| `reply` | 给用户看的回复（Markdown） |
| `sources` | 回答引用的文件、记忆或网页（可为空） |
| `task` | 仅 task：整理后的任务目标，交给 Planner |

### 2.5.3 root 能用的能力

- **项目文件**：浏览、读取、搜索当前项目的文件（只读）。
- **记忆**：检索 global / 项目 / agent 记忆（沿用 §9 的范围）。
- **上网搜索**：直接使用模型或网关自带的联网搜索能力（ADR-026），不单独接搜索服务。网关不支持时，root 如实说明拿不到实时信息，不编造。
- **任务进行中提问**：同一对话有正在进行的任务时，root 能看到它的进度、diff 和评审结果，用来回答「现在到哪了？」「为什么测试没过？」这类问题。

为了不失控，只保留单轮预算（§8）；（v1.10）不再限制工具调用次数，预算在每次模型调用和工具调用前检查。root 的回答路径本身不改文件；要改代码就走任务路径。

### 2.5.4 对话中显示什么

| 消息 | 作者 | 来源 |
|---|---|---|
| 用户输入 | `user` | 用户 |
| 回答 / 澄清 / 任务确认 | `assistant`（root） | 流式输出 |
| 任务进度（计划完成、测试结果、评审结论、等待审批） | `system` | 由 run 事件自动生成 |
| 审批卡片（批准 / 反馈 / 中止） | `system` | 复用现有审批 |
| 任务结果总结 | `assistant`（root） | 任务结束后 root 总结改了什么、结果如何 |

### 2.5.5 上下文与模型

- **上下文**：当前对话最近 20 条消息 + 项目信息 + 相关记忆。
- **模型**：使用项目设置的 root 模型（§16.4）。配置上新增 agent 定义 `root`（输出 `root_turn`）；`supervisor` 继续负责 auto 模式下给各 agent 分配模型与任务。
- **项目外对话**：未选择项目时也可以聊天和提问；要改代码需要先选项目。

---

## 三、Loop Engine（系统灵魂）

```
Task → Planner → Coder → [客观 Gate] → [LLM 评审团] → Arbiter → Human → Done
                   ↑          │ fail          │ changes      │ 冲突/震荡
                   └──────────┴───────────────┘              └→ Human
```

Task 的来源：root 会话判定为任务（§2.5），或在控制台、CLI 直接创建 run。问答类消息不进入本 Loop。

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
| CODING | 有 Gate → GATING；无 Gate → REVIEWING |
| GATING | pass → REVIEWING；fail → CODING（带 gate 报告） |
| REVIEWING | → ARBITRATING |
| ARBITRATING | SIGNOFF → WAITING_HUMAN；BACK_TO_CODER → CODING；ESCALATE → WAITING_HUMAN |
| WAITING_HUMAN | signoff 的 approve → DONE；其他 approve → 恢复执行（预算/迭代上限须先提高）；reject+反馈 → 有 plan 时 CODING、否则 PLANNING；abort → CANCELLED |

每次状态迁移写一条 `iteration`/`event` 记录并 commit；进程挂掉后从 `run.status` 恢复。状态迁移表在 `core/loop/states.py` 中是**唯一事实源**，非法迁移抛异常（借鉴 homerail 的严格语义）。

---

## 四、客观 Gate（v1.9 起为可选）

**v1.9 决定（ADR-029）**：Gate 是「有就用」的客观检查，不再是创建 run 的前提。

| 情况 | 行为 |
|---|---|
| 项目匹配到 Gate（目前内置只有 Python） | 照常：CODING → GATING（fast）→ REVIEWING …，进入人工终审前跑一次 FULL Gate，失败退回 Coder |
| 没有匹配的 Gate（Go、Rust、TS 等任意项目） | 跳过 GATING：CODING → REVIEWING；不跑 FULL Gate；signoff 审批记录 `automated_checks: not_run`，终审界面明确标出「未经过自动测试」 |

- 不再为每种语言建镜像。原计划的 TypeScript / Java / C++ Gate（下表）取消，相关 YAML 移除；需要时再按下面的方式扩展。
- 以后可选扩展：在项目设置中填写自定义检查命令（如 `go test ./...`），使用本机环境执行。是否做、何时做按需决定，不在当前计划内。
- 收敛逻辑不变：仍需 `blocking + major == 0` 与人工终审；只是缺少「代码能跑」的客观信号，由 reviewer 与人工承担。

以下为原多语言设计（v1.8 及以前），仅 Python 部分仍有效：

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
| root（会话，v1.6） | 用户消息 + 对话历史 + 项目信息 + 文件 / 记忆 / 搜索结果 | `root_turn`（回答 / 澄清 / 任务，§2.5） | 项目 root 模型 |
| supervisor (root) | 任务 + project 配置 | 调度决策（policy 层，auto 模式 Dispatch） | `root` |
| planner | 需求 + 仓库上下文 + semantic memory | `plan`（含验收标准） | `strong` |
| coder | plan + gate 报告 + arbiter 指令 | `diff` | `strong` |
| reviewer × 3 | 需求 + 验收标准 + diff + gate 输出 | `review`（结构化 JSON） | `strong` / `strong-alt` / `cheap` |
| arbiter | 全部 verdicts | `arbiter_decision` | 确定性代码 |
| summarizer（v1.8） | run 结束时：人工反馈 + review findings（含是否被修复）+ run 结果 + 相关已有记忆 | 记忆操作：新增 / 更新 / 退役，每条标注 global / project / agent 层（§9.1） | `cheap` |

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

auto 模式的 override 白名单由项目模型目录和 reviewer 档位约束取代；目录有至少两个不同 model id 时，correctness 和 arch reviewer 必须使用不同 model id（不同 alias 不代表不同模型）。manual 模式同样校验模型多样性。

### 7.3 Retry（retry = 3）

`num_retries = 3` 指同一次逻辑 LLM 调用的额外重试次数（最多 4 次请求）。仅瞬时错误（429 / 5xx / 连接 / 读超时 / 空响应）重试；401/403、上下文超长、内容拒绝、预算超限不重试。结构化输出修复独立预算 `max_repairs: 2`（Pydantic 错误原文回灌）。重试耗尽后最多换 1 个 fallback 模型。每次 attempt 前预留预算（并行请求共享预留量）；网关返回的 usage 逐次即时记账，包括空响应、拒绝与 JSON 修复失败。没有 usage 的传输失败无法准确计费，不伪造 token；每次逻辑调用一个 `step_id`，所有 attempt 挂同一 step。

### 7.4 Embedding 与 Rerank（v1.9：本地默认，远程可选，ADR-030）

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | 远程 OpenAI 兼容接口 | 在 Settings 填写 `AGENTLAB_EMBEDDING_BASE_URL`（及 Key）时使用，例如 OpenAI `text-embedding-3-small`，或本机 Ollama（`http://localhost:11434/v1`，Key 可留空） |
| 2（默认） | 本地进程内模型 | 未配置远程时使用；远程失败也回退本地，60 秒后再试远程。进程内 CPU 推理、首次下载模型；不需要任何 key 或额外服务 |
| 3 | 关键词检索 | 两者都不可用时降级（ADR-024），不影响 run |

- **模型（已实测）**：FastEmbed 0.7.4；默认 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`（384 维、多语言、Apache-2.0、约 220 MB）与 `BAAI/bge-reranker-base`（中英文、MIT、约 1 GB）。固定 CPUExecutionProvider，首次使用下载至 `.agentlab/models`；启动不下载。远程 URL 只覆盖 embedding，rerank 当前始终本地，可用 `rerank_enabled: false` 关闭；远程 rerank 接口尚未实现。
- **维度固定**：pgvector 索引维度由所选模型决定；更换模型须用现有「重建向量」功能重建全部向量。`memory.embedding_model + embedding_version + embedding_dimensions` 必须落库。
- **性能**：下载、模型初始化、embedding 与 rerank 都由后台线程执行，锁定单模型推理并限制 CPU 线程数；长中文块再按 400 字分窗，embedding 平均池化、rerank 取各窗最大分，避免尾部静默截断。
- **检索（当前）**：Python BM25 / cosine → RRF 候选 → 本地 rerank top-k，pinned 候选优先保留。Postgres JSON 持久化向量与维度元数据；`pgvector HNSW / tsvector` SQL 查询仍是后续工作。项目仍可选择 off / keyword / hybrid，新项目默认 hybrid，无需配 key；已有显式 keyword / off 设置保持不变。
- **开源**：用户 `docker compose up` + 启动后端即可使用向量检索，无需申请 embedding key。

---

## 八、预算与熔断（确定性中间件，非 agent）

三道闸：
1. LiteLLM virtual key（每 project 一把）—— `max_budget` / `rpm_limit` / 模型白名单（S2 起）。
2. 应用层熔断中间件（ADK `before_model_callback` / raw runtime 调用前）—— 估算成本，超 run 预算直接短路，run 置 `WAITING_HUMAN`。
3. per-run 软预算 —— `run.budget_cents`，80% 告警，实际 usage 达到预算后，在下一批付费调用前暂停；已返回的成功结果先保存。
4. root 会话单轮上限（v1.6）—— 单轮预算 `budget.ask.max_turn_cents`；超限时停止并在回复中说明。（v1.10）原「每轮最多 8 次工具调用」已取消，Root 与 run 内所有 agent 都只受预算约束。会话花费计入项目账目。

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
| Global 个人知识 | `global` | 跨所有 project | 所有 agent | 用户上传 PDF / Markdown / txt（切块 + embedding）；用户手写 note；（v1.8）summarizer 写入你的偏好与跨项目重要经验 | Yes（内存 / Postgres） |
| Project | `project` | 单个 project | 该 project 的所有 agent | 用户手写 note；（v1.8）summarizer 写入项目经验 | Yes（内存 / Postgres） |
| Agent 本地 | `agent:<role>` | `project × role` | 仅该 role | 用户手写 note；（v1.8）summarizer 写入角色经验 | Yes（内存 / Postgres） |

每次调用 agent 前，Driver 通过 `RunHooks.context_for` 检索 `global ∪ project ∪ agent:<self>`，top-6 注入 `AgentInput.context.memory`。检索：BM25 + 向量（v1.9：默认本地 embedding，可改用远程接口，§7.4）→ RRF；embedding 失败自动降级为纯关键词，且 memory 任何异常都不会中断 run。扫描版 PDF（无文字层）会被拒绝并提示。

**Project 进度**：project-planner（root 模型）把 project 目标拆成 phase → step；每个 step 可一键发起 run，run DONE 自动把 step 标为 done，失败/取消标 blocked；用户也可手动改状态（ADR-021）。

旧命名空间 `shared` 由 `project` 取代；记忆归属 `project × role`。版本化非覆盖：`valid_from / valid_to / superseded_by`，项目存在期间不物理删除单条记忆；（v1.8）删除项目时其 project / agent 记忆随项目 schema 一起物理删除（§9.1）。检索：`pgvector HNSW top-50 ∪ tsvector BM25 top-50 → RRF → rerank top-8`。

### 9.1 Summarizer 与项目删除（v1.8，ADR-028）

**目的**：把你在 run 中给的反馈和 reviewer 反复指出的问题总结成经验，供以后的 run 检索使用；重复的合并，过时的退役。

| 项 | 决定 |
|---|---|
| 何时运行 | 每个 run 结束时运行一次（批准 DONE、打回后终止、abort 均触发）。不按迭代运行：中间轮次的 finding 常被下一轮修复，run 结束时信息才完整、只需一次调用。不设每日定时任务，去重在写入时完成。 |
| 读什么 | ① 人工反馈：reject 反馈、Ask Me 回答、审批附带说明；② review findings（blocking / major），并标出后续是否被修复、是否反复出现；③ run 结果（DONE / 终止原因）；④ 与以上内容相关的已有记忆（按目标层检索 top-k），用于去重。不读完整 diff 与代码。 |
| 写到哪层 | 每条经验由 summarizer 标注层级：**global** = 与你相关的偏好、习惯、跨项目都适用的高优先级经验；**project** = 本项目的约定与教训（默认）；**agent:\<role\>** = 只对某个角色有用的经验。global 条目来源标为 `summarizer`，在 memory 页面可查看、删除；prompt 明确禁止把项目代码细节、私有文档内容写入 global。 |
| 输出 | 结构化记忆操作列表：`add`（新条目）/ `update`（新条目取代旧条目，旧条目写 `superseded_by`）/ `retire`（旧条目写 `valid_to`，不再参与检索）。只能引用本次提供给它的已有条目 id，越权的层或 id 由确定性代码拒绝。 |
| 保护 | `pinned` 条目不会被更新或退役；用户上传的文档（`kind=document`）不在 summarizer 可改范围内。 |
| 预算与计量 | 使用 run 之外的小额独立预算（同 project-planner 做法），失败只记录日志，不改变 run 结果（同 ADR-024 降级原则）；用量写入 `usage_ledger`，Monitor 中显示为 `summarizer`。 |
| 取代旧规则 | summarizer 接入后，移除现有确定性写入（「Flagged in run …」reviewer 笔记与「Run X approved」项目笔记），避免重复。 |
| 暂不做 | 对话（root 会话）中的偏好总结；后续按需在会话结束时加同样的流程。 |

**删除项目**（v1.8 已实现）：

- `DELETE /projects/{id}` + 控制台删除按钮，需二次确认；项目有未结束的 run 时拒绝删除。
- 删除范围：`proj_<id>` schema（项目记忆、agent 记忆、对话、run、审批、事件等）、`project_schema` / `run_directory` 路由登记、`.agentlab` 中该项目的快照与对象、进程内缓存（记忆、事件订阅）。
- 不删除：用户 workspace 中的代码文件；已写入 global 的经验（这正是 global 的用途）；`usage_ledger` 流水（Monitor 跨项目累计，保留 `project_id` 仅作追溯）。
- 删除不可撤销；需要保留时先用 `pg_dump -n proj_<id>` 导出（§10）。

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
memory     (id, project_id NULL for global, namespace, kind [document|note|episodic|semantic|procedural], text, source, embedding vector(<所选模型维度>), embedding_model,
            embedding_version, source_run_id, valid_from, valid_to, superseded_by, pinned, tsv)
approval   (id, run_id, reason, payload jsonb, status, decided_by, decided_at)
event      (id, run_id, seq, ts, type, actor, payload jsonb)   -- v1.1 新增：可视化与回放的唯一事件流
thread     (id, project_id NULL, title, created_at)                             -- v1.6：对话
message    (id, thread_id, seq, author user|assistant|system, kind, text, run_id NULL,
            turn_id NULL, sources jsonb, created_at)                           -- v1.6：逐条存储，替代整段 JSON
root_turn  (id, thread_id, user_message_id, intent, tool_calls jsonb,
            prompt_ref, response_ref, tokens, cost_cents, created_at)          -- v1.6：可回放、可计费
usage_ledger (id, ts, role, model_alias, model, tokens_in, tokens_out, cost_cents,
            source run|turn|planning, ref_id, project_id NULL)                -- v1.7：Monitor 用，存于 public
```

- v1.1 新增 `event` 表：Office Floor、Run 树、TUI 都只消费这条事件流（SSE），见 §15.3。
- `prompt_ref / response_ref / content_ref` 指向 blob 存储（本地文件，sha256 寻址），DB 不存大文本。
- v1.6：对话事件（`message.created`、`message.delta` 流式输出、`turn.finished`）与 run 事件共用 SSE，按 `thread_id` 订阅；任务进度消息由 run 事件确定性生成。`project_id` 为 NULL 的对话存于 `public`，其余存于各项目 schema。
- 隔离：单 Postgres 实例，每 project 一个 schema（`proj_<id>`）。导出 = `pg_dump -n schema`。
- v1.7：`usage_ledger` 是跨项目的用量流水，放在 `public`（与模型目录等共享元数据同级）。每次拿到模型返回的 usage 时追加一行（与现有记账同一位置），只追加不修改；Monitor 直接对它按 `role` 汇总。保留 `project_id` 列只为以后需要时可追溯，Monitor 界面不按 project 拆分。

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
| root 会话（v1.6） | 回答时只读项目文件，不改代码；上网搜索由模型 / 网关自带能力完成（§2.5.3） |

写 workspace 外或秘密文件的尝试会暂停并生成审批；批准仅恢复到 Coder，用新反馈生成合法修改，不授权突破 workspace 边界。只有 signoff 批准才能完成项目 step；有 Gate 时要求 FULL Gate 通过，无 Gate 时审批须标明未经过自动测试。

容器运行时：Colima（`colima start --cpu 4 --memory 8`）+ docker CLI + docker-compose。

---

## 十二、技术选型总表

| 层 | 选择 |
|---|---|
| 编排 | 自研 Loop Driver（Python 3.12+） |
| Agent 运行时 | Google ADK（Python）；raw / fake 兜底 |
| 模型网关 | 单一 OpenAI 兼容 endpoint；LiteLLM Proxy（S2 起） |
| 存储 | Postgres 16 + pgvector；SQLAlchemy 2 + Alembic |
| Embedding / Rerank | 本地进程内多语言小模型（默认，v1.9）；远程 OpenAI 兼容接口（可选） |
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
| v1（交互） | **对话窗口为主入口（v1.6）**：root 回复流式显示、来源引用、任务进度消息与内联审批卡片；审批卡点（approve / reject+反馈）、恢复暂停的 run、调整 budget 与 max_iter |
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
| `assets/tilesets/*`, `assets/maps/*.tmj` | 地图与素材 | **LimeZu 许可，必须署名；禁止再分发，开源前替换（§15.6）** |
| `assets/fonts/*` | Press Start 2P / Inter / JetBrains Mono | OFL 1.1 |
| `i18n/locales/{en,zh-CN}.json` 的 `office.*` 段 | 场景文案 | 只保留用到的 key |

不移植：语音（realtime/freeflow、RealtimeMichaelToggle、CostHud）、PTY/xterm、Electron main/preload、hire/onboarding（AddAgentModal、OnboardingWizard）、Slack/webhook 触发器、Skills/Workers、更新器、SettingsModal。

**精简版控制台（ADR-022）**：munder 的 CommandCenterPanel（13 个标签、大半依赖 PTY）不整体移植，改为右侧 8 个标签：runs / project / tasks / ask me / memory / graph / activity / settings（v1.6 增加 chat，v1.7 增加 monitor）。点任意头像或卡片在顶部展开 AgentDetail（activity / tools / messages）。

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

### 15.5 Monitor：按 agent 统计 token（v1.7，ADR-027）

**目的**：一眼看出每个 agent 累计用了多少 token、花了多少钱，便于决定给谁换模型、怎么分工。

**范围**：
- 按 **agent（角色）** 汇总，**不区分 project**：所有项目、所有对话、所有 run 的用量合在一起。
- 角色来自 `config/agents/*.yaml`，新增角色（例如以后的 researcher）会自动出现，不改代码。当前对应关系：

| 你习惯的叫法 | 当前角色 |
|---|---|
| root | `root`（对话）、`supervisor`（auto 分派）、`project-planner`（项目规划） |
| researcher | 暂无独立角色；root 的检索与上网搜索计入 `root` |
| developer | `coder`；`planner` 单独一行 |
| reviewer | `correctness-reviewer`、`arch-reviewer`、`test-style-reviewer`，另显示 reviewer 合计 |
| worker（其他执行类 agent） | `summarizer` 等其余 `kind: worker` 的角色，各自一行 |

`arbiter` 是确定性代码，不消耗 token，不显示。

**显示内容**（控制台新增 `monitor` 标签）：

| 列 | 含义 |
|---|---|
| Agent | 角色名（reviewer 另有合计行） |
| 调用次数 | 拿到 usage 的模型调用次数（含重试、JSON 修复与 fallback） |
| 输入 / 输出 / 总 token | 累计 token |
| 费用 | 按 `models.yaml` 价格估算的累计费用 |
| 模型 | 该角色实际用过的模型（可能多个） |

另附一个按总 token 排序的横向条形图；顶部显示全部 agent 的总计。打开标签时刷新，任务运行中每几秒刷新一次。

**口径**：
- 数据来源唯一：`usage_ledger`（§10）。所有拿到 usage 的地方（run 内的 agent 调用、root 对话与上网搜索、项目规划）都写同一张表。
- 失败但网关返回了 usage 的调用也计入；没有返回 usage 的中断请求无法计量，单独显示「未计量调用」次数。
- 不新增限制或告警，只做展示；预算仍由 §8 负责。
- 已实现：base scope Alembic 迁移与一次性回填，run / root（含上网搜索）/ project-planner 逐调用流水，跨项目汇总 API 和控制台汇总卡片、agent 明细表、条形图，每 3 秒刷新；费用从 cents 转为美元显示，并标明估算。`metered` 区分已返回 usage（包括零 token）与未计量请求；`calls` 默认为 1，历史汇总行使用旧记录的 attempt_count。
- 历史精度：有 attempt 记录的 run 优先回填逐调用数据，避免与 step 重复；其余回填 step / root_turn / planning 的累计 token、费用和已知调用数。旧对话的模型名、各 attempt 是否返回 usage 可能缺失，模型显示 `unknown`，无法精确重建历史未计量次数。新调用按实际 usage 状态记录。
- 升级顺序：revision 仅创建 base scope 流水表；所有项目 schema 达到 head 后，在同一升级事务中统一回填，并在 base.state_record 保存一次性标记。因此可从 p2_recovery 跨版本升级，项目失败时连同流水/标记一起回滚。
- 记账入口统一为 record_usage：UsageRecorder 同时处理预算与带 call ID 的流水，支持未直接记账的 runtime 返回值；元数据不进入 step/root 的 Usage JSON。后续保存失败时保留已返回的 provider 用量，不能降格为零 token 未计量请求。
- 崩溃恢复：启动及 run 恢复/中断审批时补记无 usage 的 attempt，call ID 去重；启动补记先取得执行锁，跳过仍在其他进程执行的 run、对话和规划。Monitor 使用 SQL GROUP BY role，内存后端维护增量汇总及嵌套事务撤销日志，不复制历史流水。

### 15.6 开源素材与 IP 清理（v1.9，ADR-031）

**目的**：开源仓库中不包含任何无权再分发的素材或影视 IP。范围不仅是 LimeZu 素材，而是所有可能侵权的内容。

**现状盘点（2026-10-10 代码扫描）**

| 类别 | 现有内容 | 位置 | 问题 |
|---|---|---|---|
| 办公室素材 | LimeZu Modern Interiors 的 3 张 16×16 tileset：`interiors.png`、`office-tileset.png`、`a5-office-floors-walls.png` | `ui/src/assets/tilesets/` | 许可明确禁止再分发（"YOU CAN'T … DISTRIBUTE THE ASSET"） |
| 地图 | `office.tmj`、`brooklyn99.tmj`（来自 shahar061/the-office，基于 LimeZu tileset） | `ui/src/assets/maps/` | 依赖 LimeZu 图块；地图名使用剧名 |
| 主题 | `office`、`brooklyn99` 主题及主题选择器 | `scene/office/themeRegistry.ts`、`OfficeThemePicker.tsx`、i18n | 使用《The Office》《Brooklyn Nine-Nine》剧名 |
| 角色 | Michael / Jim / Pam / Dwight / Kevin / Angela / Oscar / Stanley / Phyllis / Creed / Meredith / Toby / Ryan / Andy 等；简介如 "World's best boss"、"Assistant (to the) RM" | `scene/office/cast.ts`、`portraitArt.ts`（按角色 likeness 绘制）、`scene/adapter/mapping.ts` | 剧中角色名、身份与形象（人物像素图虽为程序原创绘制，但按剧中人物造型设计） |
| 台词 | 茶水间对话与思考气泡：剧中台词与梗（如 "that's what she said"、"identity theft is not a joke"、"Dunder Mifflin, this is Pam"、Schrute Farms 等） | `scene/office/cafeteriaLines.ts`、`ThoughtBubble.ts` | 直接引用剧中台词与虚构公司名 |
| 界面文案 | 默认 root 名 `Michael`（`DEFAULT_GOD_NAME`）；i18n key 与文案 `dispatchViaMichael`、`michaelDecides`、`sentToMichael`、`askMichael`；代码注释中的 Dunder Mifflin / Scranton | `shared/godIdentity.ts`、`i18n/locales/*.json`、多处注释 | 剧中角色名与公司名 |

**不需要替换**：munder-difflin 的 MIT 代码与署名（MIT 要求保留版权声明，`THIRD_PARTY_NOTICES.md` 中的上游仓库名属于署名，不是本项目品牌）；Press Start 2P / Inter / JetBrains Mono 字体（OFL 允许再分发）。

**替换方案**

| 类别 | 方案 |
|---|---|
| 办公室素材 | **CC0 拼装为主**：2dPig「Pixel Office」（CC0，俯视办公家具 / 电脑 / 植物，非网格 tileset）+ Kenney「Roguelike Indoor Pack」（CC0，室内地板 / 墙 / 通用家具）。用 Tiled 重画地图，补显示器亮屏版本（`DeskScreen.ts` 需要亮 / 暗两种），统一配色。若两套风格无法统一，改为与人物相同的程序绘制方式自绘家具。备选：Masalimov Ilnur「Pixel Office」（CC-BY 4.0，32×32，需署名、需调整比例）。不可用：Donarg、LimeZu Modern Office、Maru、GameDevMarket 等禁止再分发的包。 |
| LimeZu 可选皮肤 | 仓库只附带 CC0 默认素材；已购买 LimeZu 的用户把自己的文件放到指定目录后自动加载，仓库与发布包中不含 LimeZu 文件。 |
| 主题 | 删除 `office` / `brooklyn99` 两个影视主题，改为原创主题（名称、地图、配色均原创），主题选择器保留。 |
| 角色 | 改为与 agent 角色对应的原创人物（名称、造型、配色、简介均原创），沿用 `portraitArt.ts` 的程序绘制方式；不再以任何真实或影视人物为原型。 |
| 台词 | 删除剧中台词与梗，改写为原创的通用办公 / 编程闲聊。 |
| 界面文案 | 默认 root 名改为中性名称（如 `Root`）；i18n key 与文案、代码注释去除剧中人物名与公司名。 |

**验收**
- 仓库与 UI 构建产物（`ui/dist`）中不含 LimeZu 图片与基于它的地图。
- 全仓库搜索剧名、角色名、公司名、台词（The Office / Brooklyn Nine-Nine / Dunder Mifflin / Scranton / Michael / Dwight 等）无命中，`THIRD_PARTY_NOTICES.md` 中的上游署名除外。
- 每个第三方素材在 `ui/src/assets/ATTRIBUTION.md` 与 `THIRD_PARTY_NOTICES.md` 中列出来源、作者与许可（CC0 也记录来源）。
- 未放入 LimeZu 文件时，Office Floor 用默认素材正常显示；放入后切换为 LimeZu 皮肤。

---

## 十六、开发 Phase / Steps（v1.2 更新：按实际进度重排）

图例：`[x]` 完成并有测试 · `[~]` 部分完成 / 已有骨架未接线 · `[ ]` 未开始 · `[!]` 阻塞（等用户）

### 16.0 进度总览

| Phase | 内容 | 状态 | 说明 |
|---|---|---|---|
| P0 | 架构骨架 | **完成** | 2026-10-09；fake 模型下 loop 端到端跑通，UI 可视化可演示 |
| P1 | S0 Walking Skeleton（接真实 LLM + Docker 沙箱） | **已完成** | 网关已配置，Python 固定任务验证通过 |
| P2 | S1 持久化 + 断点续跑 | 已完成 | PostgreSQL / Alembic / CLI 恢复 / kill -9 验证 |
| P2.5 | Root 会话层：回答 / 澄清 / 任务分流（v1.6，§2.5） | 已完成 | 工具循环、逐条消息、SSE、共享 run service、进度 / 审批 / 总结；fake 与真实网关验收 |
| P3 | S2 评审团真实化 + HIL 完整 | 部分 | 并行 / 仲裁逻辑、ASK ME 回答流已完成；Raw 工具白名单已强制执行；外部 MCP（GitHub、Fetch）已接入（v1.10，§16.6）；ADK 尚未完成 |
| P4 | S5a 可视化 v0 | **完成** | Office Floor、Monitor、Gate 诊断表与 FastAPI 生成 TS 类型均已接线 |
| P5 | ~~S3 多语言 Gate~~ → Gate 可选（v1.9，ADR-029） | 完成 | 取消 TS / Java / C++ 镜像；改为无 Gate 时跳过 GATING，终审标明未经过自动测试 |
| P6 | S4 Memory + Project 化 | **部分（提前）** | 三层记忆版本与项目设置已落 Postgres；项目私有文档、embedding model/version/dimensions 元数据、关键词/混合选择和 YAML 配置导入导出已接线；summarizer 与删除项目已完成（v1.8，§9.1）；本地 embedding / rerank 已完成（v1.9，§7.4）；pgvector 索引与完整记忆导入导出未做 |
| P7 | S5b 可视化 v2 + 可观测 | 部分 | Memory Graph 已接 agent 记忆；React Flow / Monaco / 回放 / Langfuse 未做 |
| P8 | S6 Eval | 基线完成 | 10 个固定修复 + 5 条 Root 对话；agentlab eval 输出评分卡；fake 不代表模型语义质量 |

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
| summarizer 角色 | 已在 `on_finished` 调用，结构化 MemoryOps + 三层归属校验 + pinned/document 保护；独立 25c 预算与 usage 流水，失败降级 | 已完成 |
| 删除项目 | DELETE API + 控制台确认按钮；清除项目 schema、路由、缓存与快照，独占 blobs 删除、共享引用保留；未结束 run 拒绝删除 | 已完成 |
| 工具白名单 `tool_grants` | 已强制执行：Coder 读写 / Gate，其余角色只读 / 记忆 | P3 |
| 危险操作卡点 `dangerous_ops_require_approval` | 工作区越界写已走审批；（v1.10）MCP 写操作（建 PR、评论等）须在对话中批准后才执行（§16.6）；agent 本身仍不能执行 shell / git 写命令 | P3 |
| `AdkRuntime` | 仅占位，调用即 NotImplementedError | P3 |
| Gate 镜像 | Python 镜像与 Docker Gate 已实测；其余语言不再建镜像，无 Gate 时跳过（v1.9，ADR-029） | P5 |
| Gate 诊断表、成本看板 | file:line / code / message / 日志尾部与 Monitor 已接线 | 已完成 |
| `step.prompt_ref / response_ref` | prompt / response 内容寻址并落库；逐 attempt 可追溯 | 已完成 |
| UI 类型 | FastAPI OpenAPI 导出 + openapi-typescript；核心模型及请求类型改为生成类型，提供 check:api | 已完成 |

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

#### P2.5 · Root 会话层（v1.6，约 2 天）
目标：在对话中提问能直接得到回答；提出编码需求时 root 把任务分给 multi-agent 团队，进度与审批都回到对话里（§2.5）。

- [x] 对话消息逐条落库（`thread` / `message` / `root_turn`），支持 user / assistant / system 三种作者
- [x] `config/agents/root.yaml` + `prompts/root.md`：输出 `RootTurn`，模型跟随项目 root
- [x] root 能力：读项目文件、检索记忆、任务进行中查看进度与 diff
- [x] 上网搜索：先用 `agentlab ping` 确认网关是否支持模型自带搜索；支持就打开，不支持时 root 如实说明
- [x] 默认上限：单轮预算（v1.10 取消原 8 次工具调用上限）
- [x] 回复流式输出；任务进度消息由 run 事件自动生成；审批卡片显示在对话中；任务结束由 root 总结
- [x] UI：对话窗口为主入口

验收（加入 P8 评测集）：
- 「这个仓库的入口文件是哪个？」→ 直接回答并引用文件，不创建任务
- 「上传的文档里关于 X 是怎么说的？」→ 直接回答并引用记忆
- 「今天天气怎么样？」→ 网关支持搜索时回答并附来源；不支持时说明无法获取，不编造
- 「把 calc.add 修好让测试通过」→ 分配为任务，进度与审批出现在对话中
- 「帮我看看这个函数」→ 先回答或问一句，不直接改代码

#### P3 · S2 评审团真实化 + HIL（2–3 天）系统真正形态
- [x] 3 个 reviewer 并行、互相不可见（fake 下验证）
- [x] Arbiter 冲突打包升级（fake 下验证）
- [x] 审批流：approval 表结构 + API 审批
- [x] 3 个 reviewer 用不同模型 ID 真实运行（gpt-6-astra / gpt-6.1-sol / gpt-6-sol，2026-10-10）
- [ ] supervisor 接入：仅在 policy 允许处做调度 / override 决策，决策写 `routing_reason`
- [x] Raw function calling 工具层 + `tool_grants` 强制；Coder 读写 / Gate，其他角色只读 / 记忆；越界写仍走 approval。外部 MCP 接入见 §16.6（v1.10）
- [ ] LiteLLM Proxy + per-project virtual key
- [ ] `AdkRuntime`（ParallelAgent + before_model_callback 熔断）
- 演示：一个带安全隐患的改动，三方结果并排展示

#### P4 · S5a 可视化 v0 收尾（0.5–1 天）
- [x] SSE 事件流、Office Floor 接事件流、Run 列表 / 时间线、评审对比、审批横幅
- [x] Gate 诊断表（file:line、code、message）
- [x] Monitor 模块（v1.7，§15.5）：`usage_ledger` 落库（迁移 + 在现有记账点追加写入）、`GET /monitor/usage` 按角色汇总、控制台 `monitor` 标签（表格 + 条形图）；历史 run 的 step 与 root_turn 用量一次性回填
  - 验收：跑一个 fake 任务 + 一轮对话后，root / planner / coder / 三个 reviewer 的调用次数与 token 和 step、root_turn 记录一致；跨两个项目的数据合并显示
- [x] openapi-typescript 生成类型，替换手写类型

#### P4.5 · 终审报告（v1.10，ADR-032）
到达 signoff 时，用确定性代码（不调用模型）生成一份简短报告，显示在审批卡片与对话总结中，只包含三项：
1. **任务目标与验收标准**：run 目标 + planner 计划中的验收标准
2. **自动检查**：FULL Gate 通过；或「未经过自动测试」（`automated_checks: not_run`）
3. **未解决的 findings**：最后一轮评审中各 reviewer 仍保留的 findings（signoff 时不含 blocking / major，通常为 minor / nit）；没有则显示「无」

- [x] 生成报告并随 signoff 审批保存；审批卡片与对话总结显示
- 验收：有 Gate / 无 Gate 各跑一个 fake 任务到 signoff，报告三项内容与 plan、Gate 结果、最后一轮 verdict 一致
- 不做：费用、模型、迭代明细（Monitor 与 run 时间线已有）；联网 / Git 危险操作审批（目前没有任何 agent 工具能执行命令、联网或操作 Git，待以后新增 shell / MCP 工具时再做）

#### P5 · Gate 可选（v1.9，ADR-029；取代原「S3 多语言 Gate」）
- ~~`docker/` 下 node / jdk / cpp 镜像；实测 TypeScript → Java → C++~~（取消）
- [x] 找不到匹配 Gate 时不报错：CODING 直接进入 REVIEWING，不跑 FULL Gate
- [x] signoff 审批记录 `automated_checks: not_run`；终审卡片与对话总结明确标出「未经过自动测试」
- [x] 移除 TS / Java / C++ Gate YAML 与相关文档；Python Gate 保持不变
- [x] Coder prompt：有 Gate 时使用，无 Gate 时不假装已测试
- 验收：在一个 Go 仓库（无 Gate）上创建 run 成功，经评审到达 signoff 并显示未测试标记；Python 仓库行为与之前一致（fast / FULL Gate 照常）
- 以后按需：项目设置中的自定义检查命令（本机环境执行），不在当前计划内

#### P6 · S4 Memory + Project 化（2–3 天）
- [x] memory / blackboard 表（DDL）
- [x] 三层作用域 global / project / agent，Driver 注入（内存版）
- [x] Global 文档上传（PDF / md / txt）+ 切块 + 网关 embedding + BM25∪向量 RRF（内存版）
- [x] project-planner 生成 phase/step；run 完成自动更新进度
- [ ] 把以上三块落到 Postgres（`memory` 表 + pgvector HNSW + tsvector；`project` 表加 phases JSONB）
- [x] summarizer 接入（v1.8，§9.1）：run 结束时读人工反馈 + review findings + 相关已有记忆，输出 add / update / retire 操作并按 global / project / agent 分层写入
  - prompt 与输出 schema（`MemoryOps`）；确定性校验层级、条目 id 归属与 pinned / document 保护
  - 在 `on_finished` 调用，独立小额预算，失败降级不影响 run；用量计入 `usage_ledger`
  - 移除「Flagged in run …」与「Run X approved」两条确定性写入
  - 验收：同一问题在两个 run 中被指出 → 只留一条经验（第二次为 update）；你的 reject 反馈中的偏好进入 global，项目约定进入 project；pinned 条目不被改动；summarizer 失败时 run 仍正常结束
- [x] 删除项目（v1.8，§9.1）：`DELETE /projects/{id}` + 控制台按钮（二次确认）；有未结束 run 时拒绝；删除项目 schema、路由登记、`.agentlab` 快照与对象、进程内缓存；保留 workspace、global 记忆与 `usage_ledger`
  - 验收：删除后该项目的 project / agent 记忆不再出现在任何检索与列表中，其他项目与 global 不受影响；Postgres 与内存两种 Store 行为一致
- [x] 本地 embedding（v1.9，§7.4、ADR-030）：未配置远程接口时默认使用进程内多语言模型，后台线程执行；远程接口 Key 改为可选（支持本机 Ollama）
- [ ] pgvector HNSW 索引 + tsvector，替换 Python 内的 cosine / BM25 计算；维度随所选模型
- [x] rerank：本地中英文模型（默认），不可用时保留融合排序；远程 rerank 接口留待后续
  - 验收：全新环境不填任何 embedding 配置，上传中文文档后混合检索返回向量命中；填写远程接口后改用远程；两者都不可用时降级为关键词且 run 不受影响
- [ ] `pin_memory` 工具
- [x] per-project schema，既有数据一次性迁移；`pg_dump -n` 导出/数据库级恢复验证
- [ ] 完整项目导入 UI/CLI（目录注册、共享依赖与 blobs/snapshots 一起恢复）
- 演示：第二个 project 复用第一个 project 沉淀的经验

#### P7 · S5b 可视化 v2 + 可观测（2–3 天）
- [~] Memory Graph 已移植（等 P6 提供数据）
- [ ] React Flow step 树、Monaco diff、iteration 回放
- [ ] Langfuse（OTel）

#### P8 · S6 Eval（持续，P1 起就开始积累）
- [x] 10 个固定回归任务 + 5 条 Root 对话；`agentlab eval` 输出评分卡
- 评分卡结构（摘自 homerail `scorecard.ts`，无需再查原 repo）：每项 check = `{name, passed, severity(hard|soft), gate, source_type, detail}`；汇总 = `{run_id, passed, verdict, score, total, hard_error_count, soft_warning_count, blind_spot_count, categories: {name: passed}}`；任一 hard 失败即 FAIL，soft 只计数；CLI 退出码 = passed ? 0 : 1，便于 CI

#### P9 · 开源前素材与 IP 替换（v1.9，§15.6、ADR-031）
- [ ] 办公室素材：下载并核对 2dPig Pixel Office 与 Kenney Roguelike Indoor 的实际内容与许可文件，拼装 CC0 tileset；风格不统一时改为程序绘制家具
- [ ] 重画地图并补显示器亮屏图块；删除 LimeZu tileset 与 `office.tmj` / `brooklyn99.tmj`
- [ ] LimeZu 可选皮肤：用户自备文件放入指定目录后加载，仓库与构建产物不含 LimeZu 文件
- [ ] 主题：删除影视主题，新增原创主题
- [ ] 角色：原创人物名称、造型、配色、简介，替换 `cast.ts` / `portraitArt.ts` / `mapping.ts` 中的剧中角色
- [ ] 台词：重写 `cafeteriaLines.ts` 与思考气泡文案
- [ ] 界面文案：默认 root 名改为中性名称；清理 i18n key、文案与代码注释中的剧名 / 角色名 / 公司名
- [ ] 更新 `ATTRIBUTION.md` / `THIRD_PARTY_NOTICES.md`
- 验收：见 §15.6

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
| 创建 project → 配置 agent | 新建表单与控制台均可选 auto/manual、root、模型目录、各角色任务、budget/max_iter、检索模式/k | manual 必须绑定全部 worker，禁用 fallback；project-planner 使用项目 root。角色集合固定，summarizer 在 run 结束时独立调用 |
| auto → run → 恢复 | supervisor 输出 Dispatch，限制在模型目录与 reviewer tier 范围；artifact、分配、输入与 run 配置一起 checkpoint | fake E2E 和 Postgres 重建 Services 验证；本轮新增调度尚未做真实网关验收 |
| 左侧 project → 对话 → run | 逐条消息与 RootTurn 持久化；最近 20 条历史 + 项目信息 + 记忆；回答 / 澄清 / 任务分流 | project/thread 归属先验证；编码任务复用 run service，进度 / 审批 / 总结回到对话。项目外可聊天 |
| 切换 project | 清空 active run/thread、事件、telemetry、审批、任务、选择和答案草稿；重新加载项目 roster 与 runs | Vitest 与浏览器验证；异步响应守卫，组件唯一 key；私人便签按 project × role 分开 |
| 同 workspace 多 run | （v1.10 起）每个 run 自动使用独立 worktree，同一仓库可并行多个 run，不再返回 409（§16.5）。v1.9 及以前：未完成 run 占用 workspace，新 run 返回 409 | 创建 run 时在 workspace 锁内检查。禁止重叠 project；外部编辑器/进程不受此锁约束 |
| 人工终审 | 控制台可查看实际 diff、plan、dispatch、review、Gate 等 artifacts；审批保留 budget/max_iter 与错误反馈 | 浏览器看到 calc.py 的实际代码变化；纯文本 viewer，Monaco/回放仍未实现 |
| memory 文档 | global 明确共享；project 上传/替换/移除仅影响本项目，保留历史版本；agent 私有记忆需 project | 相同文档名跨项目隔离测试，移除文档不误删同 source 的 note |
| RAG | 项目选择 off / keyword / hybrid，新项目默认 hybrid；检索按项目与角色授权范围，失败降级 | 混合检索的向量仍在 Python 中做 cosine + BM25/RRF；Postgres 持久化不等于已使用 pgvector HNSW |
| embedding 配置 | 独立 embedding URL/Key 保存至本机 .env；模型/维度/version 在 models.yaml；可测试接口、重建共享知识与项目/agent 记忆向量 | 有凭据不等于可用：只有实际调用成功才 ready；v1.9 起默认改用本地 embedding（§7.4），真实向量验收不再依赖外部服务 |
| 配置即代码 | 控制台支持项目设置 YAML 导出/校验导入，适合提交 Git；run 固化完整配置 | 全局模型能力/价格仍在 config/*.yaml，项目选项是持久化运行数据。导入不改变已存在 run |

本轮检查可复现：后端 `tests/unit/test_project_experience.py`、Postgres `test_project_dispatch_and_conversation_survive_postgres_restart`，前端 `store.test.ts`；浏览器在隔离 fake 服务验证了创建 auto/manual 项目、对话启动、审批、实际 diff 和项目切换。测试 workspace 与 UI 服务数据不写入生产项目。

剩余需要产品确认或外部资料：
- ~~用户提供可调用的 embedding URL、Key、model ID、维度~~ v1.9 改为本地默认 embedding（ADR-030），远程接口可选；pgvector 索引维度随所选本地模型确定。
- 项目已统一使用 `proj_<id>` schema（包括既有项目/default run），共享知识和路由目录留在 public；数据库使用同一连接账号，schema 隔离不等于独立数据库账号权限。
- 当前已启用跨厂商路由：planner / coder 的 Opus worker 别名通过 Anthropic 执行，其余角色按模型策略路由；Monitor 的模型列记录实际使用的模型，可同时显示多个厂商。
- ADK、工具白名单执行、危险操作审批、memory pin UI、全量 memory 导入导出、Monaco/iteration 回放仍是后续工作；其他语言 Gate 镜像已取消（v1.9，ADR-029）。当前不会开放任意 agent 工具来绕过安全边界。

## 16.5 每个 run 独立 worktree（v1.10，ADR-033）

**目的**：同一仓库同时进行多个任务；一个等待审批的任务不再挡住新任务，两个任务也不会互相覆盖文件或污染彼此的 diff。

| 阶段 | 行为 |
|---|---|
| 创建 run | 在 `.agentlab/worktrees/<run-id>` 执行 `git worktree add`，分支 `agentlab/<run-id>`，从你当前的 `HEAD` 开始；**同时复制你未提交的改动**（已跟踪文件的 diff + 未被忽略的未跟踪文件），让 agent 看到和你本地一致的代码，然后提交一次作为该 run 的基线。`run.workspace` 指向这个 worktree |
| 执行 | agent 只修改 worktree；workspace 锁按 worktree 路径生效，不同 run 互不阻塞 |
| 批准 signoff | 把 worktree 中「基线 → 最终」的改动用 `git apply --check` 检查后应用到你当前的工作目录，**不提交**（与旧行为一致，由你自己 commit）。冲突时**不改动任何文件**，返回 409，signoff 保持待审批，提示冲突文件与分支名；你手动合并该分支后再次批准即可完成（已手动应用的改动会被识别） |
| 结束 | DONE 或 CANCELLED 后删除 worktree 与 `agentlab/<run-id>` 分支；中止的 run 不会影响你的工作目录 |

- 只在通过 API / 对话 / 项目 step 创建 run 时启用；CLI `agentlab run`、`smoke`、`eval` 仍在给定目录中直接运行。
- 仓库没有任何 commit 时（无法建 worktree）退回原来的就地运行方式，旧的 workspace 锁仍然生效。
- 限制：被 `.gitignore` 忽略的文件（如 `node_modules`、`.env`）不会复制到 worktree，需要依赖这些文件运行的检查无法在 worktree 中执行；Python Gate 的依赖预装在镜像中，不受影响。
- 实现：`src/agentlab/adapters/worktree.py`（创建 / 应用 / 清理），`GitWorkspace.isolation` 随 checkpoint 保存，重启恢复后照常应用与清理。
- 验收：同一项目连续创建两个 run 均成功且 workspace 不同；你未提交的文件出现在 worktree 中；批准前你的仓库不变，批准后改动以未提交状态出现；你在同一处修改后批准返回 409 且文件不变；中止后 worktree 与分支被删除（`tests/unit/test_worktree_runs.py`）。

## 16.6 MCP 工具服务器（v1.10，ADR-034）

**目的**：Root 与 planner 能直接读取 GitHub 仓库 / 分支 / 文件 / PR 与网页内容来核验信息；会改变外部状态的操作必须经过用户批准。

| 项 | 决定 |
|---|---|
| 配置 | `config/mcp.yaml`（严格校验，未知字段报错）：每个 server 声明 `command` / `args` / `env` / `roles` / `read_only_tools`；`${VAR}` 从 `.env` 或环境变量读取 |
| 已接入 | **github**：`docker run -i --rm ghcr.io/github/github-mcp-server`（46 个工具，27 个只读）；token 取 `GITHUB_PERSONAL_ACCESS_TOKEN`，未设置时取 `gh auth token`。**fetch**：`uvx mcp-server-fetch`（读取任意 URL） |
| 启动 | 首次使用时启动并在进程内常驻（首次可能拉取镜像 / 下载包，最长 90 秒）；启动失败只记日志，Root 与 run 照常运行；状态见设置页「MCP 工具服务器」与 `GET /mcp/status`；后端关闭时一并关闭 |
| 权限 | 工具带 `readOnlyHint` 或列在 `read_only_tools` 中 → 直接执行；其余工具（建 PR、发评论、推送等）→ 不执行，在对话中插入「允许 / 拒绝」卡片（`tool_approval`），用户允许后才执行并把结果写回对话（`tool_result`）；每个请求只能决定一次 |
| 使用范围 | Root：只读工具 + 需批准的写工具；planner：只读工具（通过 `RunHooks.external_tools` 注入）；coder 与 reviewer 不使用 |
| 结果大小 | 工具返回超过 16 KB 时截断（沿用工具层统一上限）；工具次数不限，只受预算约束（ADR-033） |

- 联网搜索仍使用网关自带的 `web_search`；换 Root 模型后需运行一次 `uv run agentlab ping --search` 重新探测（v1.10 发现：Root 换成 gpt-6.1-sol 后因缺少探测记录而关闭了搜索）。
- 测试不会启动真实 server（`tests/conftest.py` 的 `no_mcp_servers`）；`tests/unit/test_mcp_tools.py` 覆盖只读直接执行、写操作等待批准、拒绝不执行、只能决定一次、planner 只拿只读工具、配置严格校验。
- 真实验收（2026-10-10）：Root 通过 GitHub 工具读出 `Elyon0517/multi-agent-platform` main 的最新 commit（`75e3011` update readme file），并通过 fetch 读取 example.com 标题。

## 16.7 开发能力补强（v1.11，ADR-035）

**背景**：真实任务「参考 a2ui-crm 把 MVP 接入 crm-frontend 的 AI Coach」连续 6 轮空 diff，花费约 417 美分。原因叠加：计划被上一个任务的调查内容带偏（要求先跑 shell 命令、能力不足就停止）；coder 读不到参考仓库；TypeScript 项目没有 Gate、coder 不能跑测试，而 reviewer 每轮因缺少测试输出给 BLOCK；空 diff 仍被送去三方评审；coder 无法说明为什么没改。

| 项 | 决定 |
|---|---|
| 空交付 | coder 结束时工作区没有任何改动 → 不送评审，立即暂停（`no_changes`），显示 coder 在 `CoderOutput.blocked_reason` 中写的原因；批准 = 原样重试，退回修改 = 带反馈重试，中止 = 结束 |
| 停止 | `POST /runs/{id}/cancel` 可在任意未结束状态（包括执行中）停止任务：取消执行中的协程、把被打断的模型调用记为未计量、关闭待审批、清理 worktree。对话输入框为空且本对话有未结束任务时，发送按钮变为 **■ 停止**（参照 Claude / Codex） |
| 权限总表 | **coder**：读写工作区文件、代码全文搜索、Git 只读（status / branch / log / diff / show，含其他分支）、记忆、项目检查命令（`gate_run`）、GitHub / 网页只读。**reviewer × 3 与 planner**：广泛只读（文件、代码搜索、Git 只读、记忆、GitHub / 网页只读），不能写文件、不能执行命令。**Root**：只读 + GitHub 写操作（开 PR、评论等，需在对话中批准），不直接写代码。「外部写操作」仅指 GitHub 等外部系统，不影响 coder 写本地代码 |
| 项目检查命令 | 项目设置新增 `check_commands`（每行一条，最多 10 条），作为该项目的 Gate：在任务 worktree 中用本机工具链执行（不进 Docker）；coder 可通过 `gate_run` 自行运行，终审前 FULL 检查必须通过。worktree 自动链接仓库中被忽略的 `node_modules`，链接不会被应用回去 |
| 评审规则 | 三个 reviewer 的提示词明确：仅因缺少自动检查或命令输出不能给 blocking / major；报告问题前用只读工具核实上下文 |
| 按钮文案 | 「拒绝」改为「退回修改」：它会带着反馈继续执行，结束任务请用「中止」或「停止」 |

- 只放进能在 main 上通过的命令，否则每次终审都会被已有失败挡住。例：crm-frontend 的 `npm test`（95 个文件、529 个测试在 main 上全部通过）；`tsc` 在 main 上已有约 124 个错误，不适合作为检查。
- 使用建议：重新开始任务时开新对话，避免旧对话里的调查与审批内容被带进新计划。
- 测试：`tests/unit/test_dev_capabilities.py`（空交付暂停且不调用 reviewer、执行中停止并清理 worktree、检查命令在 worktree 中运行并能看到 `node_modules`）；`tests/unit/test_role_permissions.py`（reviewer / planner 广泛只读且不能写，coder 可读写）。

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
| **会话入口（v1.6）** | OpenAI Codex CLI、Claude Code | 单一会话入口；先只读探索再行动；只读与写操作分级授权；风险操作需用户批准；回复中引用文件位置 |

---

## 十八、风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| ADK 无图级 checkpoint | 复杂回放受限 | Loop Driver 自管状态机 + artifact 内容寻址 |
| ADK HIL 需手写样板 | 开发成本 | HIL 走 `approval` 表 + run 状态 |
| ADK 版本迭代快 | 升级痛 | `AgentRuntime` 接口隔离；保留 raw runtime |
| ~~C++ Gate 构建慢~~ | ~~每轮几分钟~~ | v1.9 取消多语言 Gate，不再适用 |
| 无 Gate 的项目缺少客观检查（v1.9） | 代码可能无法编译或测试失败，仅靠评审发现不了 | 终审明确标出「未经过自动测试」，由人工决定是否批准；以后可加项目自定义检查命令 |
| 本地 embedding 模型（v1.9） | 首次下载几百 MB；CPU 推理较慢；换模型需重建向量 | 后台线程执行、失败降级为关键词；模型与维度落库，提供重建功能 |
| 三个 reviewer 成本高 | 烧钱 | Gate 前置 + 第三 reviewer 廉价档 + 硬预算 |
| 多模型结构化输出格式不一 | 解析失败 | Pydantic + `max_repairs=2` + 能力矩阵降级 ReAct |
| 云端全量依赖 | 断网即停摆 | retry=3 + fallback + run 可暂停续跑 |
| Reviewer 无限挑 nit | 永不收敛 | `blocking + major == 0` 即 signoff |
| 单网关单 key（v1.1） | 网关限流影响所有角色 | 角色级 RPM 配置 + 预算中间件；reviewer 并发可配 |
| munder 移植代码量大（~5.6k 行场景 + 组件） | 维护负担 | 只改数据适配层，场景代码尽量保持原样便于对照上游 |
| LimeZu 素材许可（v1.1） | 开源分发受限（"不可再分发素材"） | v1.9 决定：开源前替换为 CC0 / 自绘素材，LimeZu 仅作用户自备的可选皮肤（§15.6） |
| 影视 IP（v1.9） | 《The Office》《Brooklyn Nine-Nine》剧名、角色名与形象、台词可能涉及商标 / 版权 | 开源前全部替换为原创主题、角色与文案（§15.6、P9） |
| root 意图误判（v1.6） | 问题被当成任务，或任务被当成问题 | 用户可以直接说「只回答」或「直接改」；即使误开任务，也要经过 Gate、评审与人工终审才会完成 |
| 会话成本累积（v1.6） | 频繁提问持续花费 | 默认单轮预算（v1.10 起不限工具调用次数）；会话花费计入项目账目 |

---

## 十九、待办与开放问题

- [x] 网关 URL / key 与模型 id 已配置，P1 已验证；更多模型由用户后续补充。
- [x] ~~网关是否提供 embedding 端点？~~ v1.9 改为本地默认 embedding，远程接口可选（ADR-030）
- [x] ~~C++ Gate 的 GTest 发现策略；Java 项目 Maven 与 Gradle 优先级~~ v1.9 取消多语言 Gate，不再需要（ADR-029）
- [x] （v1.9）本地 embedding / rerank 模型与库已确定并实测：FastEmbed 0.7.4，multilingual MiniLM（384 维）+ BAAI/bge-reranker-base；Apple Silicon CPU 上传与检索 smoke 通过（§7.4）
- [ ] 是否需要"同一 reviewer 跑两次取一致性"（成本翻倍，先不做）
- [x] （v1.6）`agentlab ping --search` 实测 Responses `web_search` 可用；Chat 无搜索证据，不启用
- [x] （v1.6）root 每轮使用默认单轮预算；（v1.10，用户决定）取消工具调用次数上限，自主开发只由预算约束
- [ ] 开源前清单：移除个人路径、示例 config、LICENSE、最小可复现 demo repo、**素材与影视 IP 替换（v1.9 已定方案，§15.6、P9）**
- [ ] 是否给其他人使用 / 开源：未决定。若决定分发，按 §20 的打包方案排期

---

## 二十、可能的打包与分发方案（备选，未排期）

> 状态：**仅记录方案，不在开发计划内**。是否给其他人使用尚未决定；决定分发时再排期，并先完成 P9（§15.6 素材与 IP 替换）与 §19 开源前清单。

**目标**：其他用户在自己电脑上安装一份独立的系统，使用自己的 LLM key、自己的数据库与记忆，并在**经过允许后**读写自己本机的项目文件夹进行开发。各用户之间不共享任何数据。

**为什么不把整个系统装进 Docker**

| 问题 | 说明 |
|---|---|
| 无法运行中授权文件夹 | 容器能看到哪些本机文件夹在启动时固定，无法在使用中「询问并允许」访问新项目，只能改配置重启 |
| 缺少用户的开发环境 | 容器内没有用户本机的 Go / Node / Python 版本与依赖，agent 无法用它们检查改动 |

**推荐形态：后端装在本机，只有 Postgres 用 Docker**（与 Claude Code 类似：程序在用户电脑上运行，访问范围由应用内授权控制）

```
用户电脑
├── agentlab（本机安装：后端 + 界面，http://127.0.0.1:8765）
│     ├── 只读写用户授权过的项目文件夹
│     └── 使用用户本机的 git 与开发工具
└── Docker：仅 Postgres（由 agentlab 启动与管理）
```

**用户流程**
1. 安装：`uv tool install agentlab`（或 `pipx`）；本机需有 Docker。
2. 启动：`agentlab up` —— 检查 Docker、启动 Postgres 容器、执行迁移、启动服务并打开浏览器。
3. 添加项目：在项目目录执行 `agentlab open .`（在哪个目录执行即表示授权该目录），或在界面填写路径并在确认框中允许「agent 读写此文件夹」。
4. 在界面填写自己的 LLM key 后使用。

**授权与安全**
- 只有授权过的文件夹可以作为项目 workspace；后端保存授权列表并校验每个项目路径。
- 沿用现有边界：写出 workspace 或碰到秘密文件时暂停并转为审批。
- 删除项目只删除系统内记录，不删除用户代码。
- 授权可在设置中撤销；服务只监听 `127.0.0.1`。

**需要实现的内容（届时排期）**

| 项 | 内容 |
|---|---|
| 打包 | 前端构建产物打进 Python 包，由 FastAPI 提供页面（单端口）；发布到 PyPI |
| `agentlab up` | 检查 Docker、启动并管理 Postgres 容器、自动迁移、启动服务、打开浏览器 |
| 文件夹授权 | `agentlab open <path>`、界面确认框、授权列表的存储与校验、撤销 |
| Gate | 保持可选（ADR-029）；以后的「自定义检查命令」直接使用用户本机工具链 |
| 首次使用 | 界面引导填写 LLM key；embedding 默认本地（ADR-030），无需额外 key |

**不采用的方案**：全部装进 Docker（原因见上）；桌面应用（Electron / Tauri + 内嵌 Postgres，工作量大，且 ADR-015 已决定不做 Electron）。

---

## 附录：决策记录（ADR 摘要）

| # | 决策 | 日期 | 理由 |
|---|---|---|---|
| ADR-001 | 编排用「自研 Loop Driver + Google ADK 执行层」 | 2026-10-09 | ADK 的 ParallelAgent、Callbacks、MCP 契合度高；checkpoint 短板由自研状态机补齐 |
| ADR-002 | Python 后端 + TypeScript 前端 | 2026-10-09 | ADK 生态为 Python；前端仅作观察窗 |
| ADR-003 | 不跑本地模型，全部云端 API（v1.9：LLM 仍如此；embedding / rerank 例外，见 ADR-030） | 2026-10-09 | 降低硬件与运维负担 |
| ADR-004 | 客观 Gate 前置于 LLM 评审 | 2026-10-09 | 砍掉 60–70% 无效评审轮次 |
| ADR-005 | `blocking + major == 0` 即 signoff | 2026-10-09 | 防止多 reviewer 在 nit 上死循环 |
| ADR-006 | 熔断用确定性中间件，不用 agent | 2026-10-09 | 非确定性的熔断等于没有熔断 |
| ADR-007 | LLM retry = 3（额外重试，共 4 次请求），仅瞬时错误 | 2026-10-09 | 区分可重试与不可重试；JSON 修复独立预算 |
| ADR-008 | 支持 Python / TS / Java / C++，Gate 做适配器（v1.9 被 ADR-029 取代） | 2026-10-09 | 目标代码库多语言 |
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
| ADR-025 | 新增 Root 会话层：每条用户消息先由 root 判断 回答 / 澄清 / 任务；回答走只读工具直接回复，任务交给收敛 Loop，进度与审批回到对话 | 2026-10-10 | 用户要求：对话应能直接得到回复，编码需求再分配任务（参照 Codex / Claude Code）；root 不自行编码，保留 Gate、多模型评审与人工终审 |
| ADR-026 | 上网搜索直接使用模型 / 网关自带的搜索能力，不单独接搜索服务 | 2026-10-10 | 用户要求保持简单；系统重点是 multi-agent 分工，而不是增加限制 |
| ADR-027 | 新增 Monitor 模块：按 agent 汇总累计 token 与费用，跨项目合并；数据来自 `public.usage_ledger` 单一流水表 | 2026-10-10 | 用户要求只按 agent 区分、不分 project；单表追加写入，比每次扫描所有项目 schema 简单、快 |
| ADR-028 | summarizer 在每个 run 结束时运行一次，读人工反馈与 review findings，输出 add / update / retire 并自行标注 global / project / agent 层；去重在写入时完成，不设定时任务；新增删除项目，项目 / agent 记忆随项目 schema 删除，global 与 usage 流水保留；对话偏好总结暂不做 | 2026-10-10 | 用户决定：以总结经验为主，偏好与高优先级经验进 global、其余进 project / agent；需要去重退役，且项目记忆随项目删除。按 run 而非按迭代或按天，信息完整、调用最少、无需调度器 |
| ADR-029 | Gate 改为可选：有匹配的 Gate 就运行，没有就跳过 GATING 与 FULL Gate，由评审 + 人工终审收敛，终审标明 `automated_checks: not_run`；取消 TS / Java / C++ Gate 镜像（取代 ADR-008） | 2026-10-10 | 用户要求：任务可能是任何语言（如 Go），不应因缺少语言配置而无法运行；参照 Claude Code 不预先为语言准备工具链。保留 Python Gate；自定义检查命令以后按需再做 |
| ADR-030 | embedding / rerank 默认使用本地进程内中文小模型；Settings 的远程 OpenAI 兼容 URL 覆盖 embedding（Key 可选），远程失败回退本地；都不可用时降级为关键词，rerank 失败保留 RRF（ADR-003 的例外；远程 rerank 暂未实现） | 2026-10-10 | 用户要求其他用户能快速上手、不必申请 key；本地小模型 CPU 即可运行，比额外容器（如 TEI）少一个服务、无 Apple Silicon 镜像兼容问题 |
| ADR-031 | 开源前替换所有可能侵权的内容：LimeZu tileset 与地图改为 CC0 拼装（2dPig + Kenney）或自绘，LimeZu 仅作用户自备的可选皮肤；删除《The Office》《Brooklyn Nine-Nine》主题、角色、台词与相关文案，改为原创；保留 munder-difflin MIT 署名与 OFL 字体 | 2026-10-10 | 用户决定：办公室与人物、影视主题等任何可能侵权的内容都要替换。LimeZu 许可禁止再分发；剧名、角色与台词属于权利人 |
| ADR-032 | signoff 时生成确定性终审报告，只含任务目标与验收标准、自动检查结果（或未经过自动测试）、最后一轮未解决的 findings | 2026-10-10 | 用户要求精简：审核时只看这三项；不调用模型，内容不会编造 |
| ADR-033 | 每个 run 使用独立 Git worktree（携带未提交改动作为基线）；批准 signoff 时用 `git apply` 把该 run 的改动应用到用户工作目录且不提交，冲突则停下并保持待审批；结束后清理 worktree 与分支。同时取消工具调用次数上限，只保留预算约束 | 2026-10-10 | 用户要求在同一项目中并行多个任务，旧的「一个工作区一个未完成 run」规则会被等待审批的任务卡住；用户选择「独立 worktree + 自动合并（有冲突就停下）」。用 `git apply` 而不是 merge commit，保持改动未提交、由用户自己 commit 的旧习惯，并能干净地处理用户未提交的工作 |
| ADR-034 | 接入 MCP（Model Context Protocol）工具服务器：GitHub 与 Fetch，配置在 `config/mcp.yaml`；只读工具自动允许、写操作在对话中批准后执行；Root 与 planner 可用，planner 仅只读 | 2026-10-10 | 用户要求像 Codex / Claude Code 一样具备 GitHub 与网页访问，并在需要时请求权限；用户选择「只读自动允许，写操作才问」和「Root + planner」 |
| ADR-035 | 空交付立即暂停并显示 coder 的原因；任务可随时停止（对话中发送按钮变为停止）；coder 获得只读 GitHub / Fetch；项目可配置检查命令作为 Gate，在 worktree 中用本机工具链运行并链接 `node_modules`；reviewer 不得仅因缺少检查输出而阻止 | 2026-10-11 | 真实任务 6 轮空 diff、约 417 美分；用户要求「适当开放权限，让多 agent 能真正帮我开发」，并要求像 Claude / Codex 一样提供停止按钮 |


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


### 16.1i · 项目 schema 与调度修正（2026-10-10）

- 项目有效模型目录包含 ≥2 个不同 model id 时，auto Dispatch 和 manual 配置都要求 correctness/arch reviewer 的 model id 不同；alias 不算多样性。单模型目录仍可运行。auto override 由模型目录、reviewer 档位与此规则约束，root 输入包含可用模型 ID/档位和 reviewer 档位上限。
- `/roster?run_id=...` 使用该 run 的 checkpoint 配置，反映已保存的实际 Dispatch，不受之后编辑项目设置影响；切换/取消选择 run 会重载对应 roster。
- global 文档上传会尝试生成 embedding，不再依赖 project；未配置或调用失败仍降级。项目文档按项目 hybrid 设置生成向量，支持手动重建。
- `agentlab.db.isolation` 是可重复执行的一次性迁移入口，db-upgrade/启动也会检查。所有已有项目统一迁移，不存在新旧双轨运行路径。锁旧表、复制完整记录、逐表核对行数和内容，任何失败回滚；只读 `legacy_projects` 保留旧数据，不自动删除。public 中空的旧项目表作为建表模板，触发器禁止旧客户端再次写入项目数据。
- `proj_<id>` 包含 project/agent_def/run/iteration/step/artifact/blackboard/memory/approval/event/run_checkpoint/state_record。项目记忆、对话、Dispatch、attempt、规划调用账目均按归属迁移。public 保留全局知识、共享记录、project_schema/run_directory 路由元数据；模型目录仍以 YAML 为准。项目内外键、serial 序列与 ownership CHECK 不依赖其他项目。
- 本地迁移：既有 4 个 default run、9 个 iteration、28 个 step、33 个 artifact、4 条 memory、4 个 approval、163 个 event、4 个 checkpoint、8 个 state_record 全部迁入 `proj_default`；完整记录比对通过。真实 run `6b2e0c696274` 保持 WAITING_HUMAN/signoff，cost=5.4875c，恢复 driver 成功。
- `pg_dump -n proj_default` 已在临时数据库恢复，并核对 4 run / 163 event / 4 checkpoint。恢复到新环境仍需共享 vector 扩展、路由目录注册与 `.agentlab` 中的对象/内容文件；完整导入工具尚待实现。后续 Alembic 结构变更通过下述 schema 版本机制同步，不能只更新 public 模板。

本轮验证：后端 183 项（包含 17 个持久化集成用例）、前端 19 项，ruff/mypy/config-check/UI build 全部通过；新增模型 ID 多样性、global 上传 embedding、frozen roster、既有数据迁移/只读备份/失败回滚测试。


### 16.1j · 各项目结构迁移与访问边界

- 每个项目 schema 记录独立的 `alembic_version`。新项目从基础模板克隆时复制其当前版本；升级前，没有版本表的既有项目先按升级前的基础版本登记，随后补跑到 head。
- db-upgrade/启动在同一事务内升级基础 schema 和 project_schema 登记的全部项目；任意项目失败，所有表结构和版本号一起回滚。迁移锁与项目创建共享锁协调，避免升级期间克隆到半更新模板；legacy_projects 只读备份不参与升级。
- 迁移脚本的未限定表名通过目标 schema 的 search_path 解析；共享目录、全局元数据、扩展等仅基础 schema 执行的操作，必须使用 `op.get_context().config.attributes["migration_scope"] == "base"` 判断。新增项目表也必须更新 isolation.TABLES 克隆清单。基础 schema 的项目表是只读空模板，项目数据回填也需限制在 project scope。不得在 revision 中手工 COMMIT 或启用 autocommit，破坏跨 schema 原子性。
- 回归验证：先创建两个项目（其中一个模拟旧版无版本表），再增加 run 列，确认已有项目与随后新建项目均有新列和一致版本；模拟某项目升级失败，确认基础/全部项目的列和版本完整回滚。
- **访问控制边界：物理 schema 用于项目数据归档、导出和删除范围管理；访问控制仍由应用层按 project_id/角色过滤。** 当前使用同一数据库账号，records()/list_runs() 会遍历项目 schemas，PersistentMemoryStore 会把各项目记忆加载到同一进程后再按授权范围检索；数据库权限没有阻止跨项目读取。这不是数据库账号级隔离，也不是独立进程隔离。

本轮验证：后端 184 项，包含 18 项持久化集成测试；ruff、mypy、config-check 通过。前端代码未改动。


### 16.1k · 迁移范围守护

revision 统一导入 `agentlab.db.migration_scope.is_project_scope()`；基础表操作必须先在项目范围下 return，再使用 `base_table("表名")` 得到限定 schema 的 SQL 标识符。`base_table` 在项目范围下调用会报错，防止辅助函数被误用。共享 vector 扩展仅在 base scope 创建。

env.py 实际读取 migration_scope；项目范围执行前后比较基础 schema 的表/列/默认值/约束/索引/触发器定义，发现变化即报错，由外层事务整体回滚。它不能拦住绕过辅助函数的任意共享表 UPDATE；基础数据迁移仍必须遵守 scope 与限定 schema 约定。

守护测试从空项目 schema 重放当前 upgrade head，要求基础表结构及路由目录数据不变；并注入一条未限定 schema 的 ALTER TABLE run_directory，验证环境守护检测和回滚。GitHub Checks 配置 PostgreSQL/pgvector，确保此集成测试在 CI 中执行，不因未提供数据库 URL 而跳过。


### v1.6 实现验收（2026-10-10）

- Root：最多 8 次工具调用，单轮预算 100c；工具前预算检查，prompt / response blob、工具调用 / 返回与 usage 可回放。搜索工具费用由 `budget.ask.web_search_cents` 配置，模型价格仍为原有估算。
- PostgreSQL：新增 `thread` / `message` / `root_turn` 表；保留旧 JSON 备份并迁移消息。`root_alignment` 修复既有项目 schema 缺少 `run.thread_id` 的历史漂移；所有项目迁移均通过基础 schema 守护。
- API：Root 回答 / 澄清不创建 run；任务复用 `create_run_service`；工作区占用由 assistant 解释。项目外 `/threads` 只聊天，修改要求选项目。
- UI：项目 / 全局聊天、增量回复、Markdown 来源、run 进度与内联 approve / reject / abort；浏览器验证收到 Root 回复。
- 真实 Root：文件入口 / 上传设计记忆 / 芝加哥天气附 NWS 来源 / 明确修复任务 / 模糊检查请求，五条均符合预期。
- 真实三模型 smoke：run `f8debe5af7cd`，1 轮到 signoff，Docker FULL Gate 通过，测试保持不变；Coder 实际调用 `workspace_write`、`gate_run`，工具事件与结果 blob 已保存。未自动批准。
- `gpt-5.6-luna`、`gpt-5.6-terra` 网关探测返回 503，第三 reviewer 使用已验证的 `gpt-6-sol`。
- P3 尚余 LiteLLM virtual key、ADK runtime 等未包含在本次实现。
- 最终自动验证：199 项 Python（含真实 PostgreSQL）、19 项 Vitest、UI production build、Ruff、mypy 全部通过；固定评分卡 15/15（fake blind spots 明确为 15），见 `evals/baseline-scorecard.json`。


### P6 §9.1 实现与验证（2026-10-10）

- `MemoryOps` 提案在 run 终态触发一次；输入包含审批反馈与 review findings 的重复/后续消失信息，不读取完整 diff 或代码。后续 review 未再提出只标记为推断修复，不声称代码已验证修复。
- global / project / agent 分层检索相关已有记忆；update 生成新版本并写 `superseded_by`，retire 写 `valid_to`；无权引用的 id/namespace、pinned 和 document 更新/退役被拒绝。旧两条固定写入已移除。
- 单独 25c 预算，调用与操作留存审计记录，用量写入 Monitor 的 summarizer；失败记录日志和 failed 状态，不改变 run 结果。
- 项目删除与 run 创建/完成、对话调用互斥；终态以外的 run 返回 409。Postgres DROP schema + 清除两张路由登记表；内存 Store 删除对应对象；保留 workspace、global 与 usage ledger。
- 清除项目快照、事件订阅、driver 与记忆缓存、项目独占 blob；其他 run 与全局/其他项目对话所引用的共享 blob 保留。另一个持久化记忆缓存刷新后也不会返回已删除项目条目。
- 验证：结构化 summarizer fake 覆盖反馈分层、跨 run update、退役、越权/保护、失败降级与计量；项目删除在内存与本地 PostgreSQL Store 上均通过。真实模型归纳质量尚未做在线评测。
- 最终验证：226 项 Python unit、32 项持久化测试（含真实 PostgreSQL）、27 项 Vitest、UI production build、Ruff、mypy 均通过。新增 `p6_summarizer` 迁移扩展 usage ledger 的来源约束；既有项目 schema 升级与 base schema 隔离回归通过。


### Gate 可选、P4 收尾与 Summarizer 质量回归（2026-10-10）

- 本节取代原 §4 / P5 多语言 Gate 计划：仅保留内置 Python Gate；TS / Java / C++ YAML 与镜像计划、CTest 和 Maven/Gradle 的待定问题取消。无匹配 Gate 时 CODING 直接进入 REVIEWING，仍需 reviewer 收敛与人工终审，不产生伪造的 Gate pass。
- signoff 的 `automated_checks` 明确区分 `passed` / `not_run`；终审卡片、对话审批与总结标注「未经过自动测试」。checkpoint 保留 gate=None，内存 / Postgres 恢复后行为一致。项目自定义本机检查命令暂不实现。
- P4 收尾完成：run API 返回完整 FAST / FULL 检查报告；UI 按 file:line / code / message 显示诊断与失败日志尾部，pytest 解析包含断言位置。核心前端 API 模型与请求类型来自 FastAPI OpenAPI，`gen:api` 本地生成、`check:api` 检测类型漂移。
- 新增三项 summarizer 质量用例：重复问题版本化合并、个人偏好进入 global、项目约定留在 project；另检验 pinned/document 不变。沿用生产 on_finished hook；fake 标明 blind spots，raw 调用真实配置网关。固定回归是合成反馈/findings，不涉及完整编码任务。
- 真实网关评测 3/3，通过结果保存在 `evals/memory-scorecard-real.json`；fake 全基线为 18/18（blind spots=18）。验证覆盖 231 项 Python unit、34 项持久化测试（含 PostgreSQL）、29 项 Vitest；UI production build、Ruff、mypy 与 OpenAPI 类型漂移检查通过。


### 本地 Memory 模型实现与验证（2026-10-10，ADR-030）

- 默认 FastEmbed CPU：多语言 MiniLM 384 维 + 中英文 BGE base rerank，模型按需下载、缓存于 `.agentlab/models`。下载、初始化与推理都在线程中；长中文块再分窗，避免尾部截断。
- Settings URL 覆盖 embedding，Ollama Key 可空；远程失败回退本地并冷却 60 秒，本地失败回退关键词；rerank 失败保留 RRF。远程 rerank 尚未实现。
- 模型 / 版本 / 维度不兼容的向量不参与融合，重建保留 id、历史与 pinned 文本；Memory 面板展示后端、有效向量数和 rerank 状态。pgvector SQL 索引仍待开发，目前查询在 Python 中完成。
- 验证：后端完整单测 237 项通过，后续新增覆盖包含在 20 项针对性测试中；持久化完整 34 项与新增 384 维重载 2 项通过；前端 29 项、构建、OpenAPI 生成一致性、ruff / mypy 通过。
- Apple Silicon 真实模型 API smoke：空 env、中文上传、中英文检索 3/3；脚本 `scripts/check_local_memory.py`，报告 `evals/local-memory-scorecard-real.json`。这不是质量 benchmark；报告保留先前模糊问句排序不佳的观察。
