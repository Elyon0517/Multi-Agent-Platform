# Multi-Agent Platform

[English](README.md) · **简体中文**

**一个对话入口，一支经过评审的团队，最终由你决定。**

与 Root 智能体讨论本地仓库：问题可以直接回答，开发任务则交给规划、编码、自动检查和评审流程，
并在像素办公室中展示进度。可使用原始 API 运行时的多模型评审，也可选择 Codex SDK 编码、Claude Agent SDK 评审。

Python 3.12+ · Node 22.12+ · Alpha 早期版本

如果这个项目对你有帮助，欢迎点一个 Star ⭐

[架构](#架构) · [安装](#安装) · [使用](#使用) · [SDK 工作流](#原生-sdk-工作流) · [测试](#测试) · [参与贡献](#参与贡献) · [设计文档](docs/DISCOVERY.md) · [验收清单](docs/ACCEPTANCE.md)

> **欢迎一起共创！** 项目目前仍处于 Alpha 阶段，功能、交互和文档都还在完善。
> 无论是反馈问题、修复缺陷、补充测试和文档，还是提出设计想法，都非常欢迎。
> 参与方式见[贡献指南](#参与贡献)。

## 看团队如何完成任务

<a href="docs/screenshots/office-review.png">
  <img src="docs/screenshots/office-review.png" alt="像素办公室中的智能体正在评审一次真实的离线任务" width="960">
</a>

*评审进行中的界面。点击截图可查看原始尺寸。*

**给团队一个有问题的函数，观察它如何检查、修改、评审并完成交付。**

演示从错误的 `add()` 实现开始：真实的 pytest 检查发现问题，编码智能体修复代码，架构评审提出补充文档字符串，
下一轮评审再通过最终改动。

<details>
<summary>查看完成后的任务与检查历史</summary>

<a href="docs/screenshots/completed-run.png">
  <img src="docs/screenshots/completed-run.png" alt="已完成任务中的失败检查、通过检查和评审结果" width="960">
</a>

</details>

截图来自真实 API 和控制台。模型回复使用预设脚本，pytest、文件编辑、版本校验和事件流在本地真实执行。
界面上的用量和费用来自预设回复与配置费率，不代表真实计费；演示不会调用付费模型。
该演示在指定工作区中完成修改，不能据此认定已验证需要人工确认的隔离交付流程。

### 无需密钥，复现同一个演示

```bash
uv sync
uv run python scripts/showcase.py --only S2 --speed 2
# 在另一个终端中执行：
cd ui
npm ci
npm run dev
# 打开 http://localhost:5173/?follow=1
```

运行连接真实 API 的浏览器检查并重新生成截图：

```bash
cd ui
npx playwright install chromium
npm run test:showcase
```

更多说明见[截图复现步骤与验证范围](docs/SHOWCASE.md)。

## 主要能力

- **统一入口。** 所有消息先交给 Root，由它决定直接回答、追问，还是把任务交给团队。回答问题时可以使用只读文件、Git、记忆和搜索工具。
- **迭代收敛。** 规划与编码持续迭代，直到配置的评审者不再提出阻断或重大问题，或流程暂停等待你处理。
- **确定性控制。** 版本校验、重试、收敛判断、振荡检测、路由和审批均由 Python 代码控制。
- **交付评审。** 工作树模式需要人工确认后才集成改动；直接修改当前检出的模式在检查和评审后自动完成。交付报告列出目标、验收标准、自动检查情况与未解决问题。
- **可积累的记忆。** 支持全局、项目和智能体级记忆。总结智能体将反馈和评审发现转为带版本的经验；可上传 PDF、Markdown 或文本用于检索。
- **本地优先。** 仓库保留在本机，默认使用本地 CPU 模型完成向量嵌入和重排；语言模型调用会发送至配置的模型服务。
- **过程可观察。** 像素办公室、运行时间线、检查诊断，以及按智能体统计用量的监控面板。

## 架构

```mermaid
flowchart TD
  You[用户] <--> Root[Root 对话]
  Root --> Planner[规划] --> Coder[编码]
  Coder --> Gate{已配置的自动检查}
  Gate -- 失败 --> Coder
  Gate -- 通过或未配置 --> Review[代码评审]
  Review --> Arbiter{仲裁}
  Arbiter -- 请求修改 --> Coder
  Arbiter -- 工作树交付 --> Human[人工确认]
  Arbiter -- 当前检出目录 --> Done[完成]
  Human --> Done
  Done --> Memory[总结与记忆]
```

Root 可以直接回答问题；编码任务进入上述循环。原始 API 运行时使用多模型评审小组，
可选的 SDK 工作流使用一个 Claude 评审者。

| 层级 | 职责 | 位置 |
|---|---|---|
| 界面 | 对话、办公室、时间线、审批、记忆和用量监控 | `ui/`，React、Vite、Pixi.js |
| API | REST 与 SSE 事件流，为界面提供统一数据 | `src/agentlab/api/`，FastAPI |
| Root 会话 | 意图路由、只读工具、流式回复 | `src/agentlab/core/session/` |
| 循环驱动 | 状态机、收敛、振荡检测、仲裁与检查点 | `src/agentlab/core/loop/` |
| 模型调用 | 角色与模型别名路由、重试、回退、结构化输出修复 | `src/agentlab/core/llm/`、`config/model_policy.yaml` |
| 运行时 | 原始 API、可选的原生 SDK、离线模拟 | `src/agentlab/adapters/runtime/` |
| 自动检查与沙箱 | 可选的客观检查，内置 Python 检查，支持 Docker 或本地执行 | `src/agentlab/adapters/gates/`、`docker/` |
| 存储 | PostgreSQL 按项目隔离 schema、内容寻址文件、Git 快照 | `src/agentlab/adapters/store/`、`.agentlab/` |
| 记忆 | BM25 与向量混合检索、重排、总结和版本记录 | `src/agentlab/core/memory/` |

**运行状态：** `PLANNING → CODING → GATING → REVIEWING → ARBITRATING → WAITING_HUMAN → DONE`。
没有匹配检查配置的项目跳过 `GATING`。失败、冲突和振荡会暂停在 `WAITING_HUMAN`。
工作树模式的编码交付需要人工确认；当前检出目录模式自动确认交付。只读报告可以直接完成。

代码差异、检查结果、评审结果和交付审批绑定到相同的源码版本。检查、评审或等待审批期间文件发生变化，
运行会以 `workspace_changed` 原因暂停；点击批准后保留当前文件，重新检查并重新评审。
仅在源码版本仍匹配时复用部分评审结果。没有版本绑定的旧运行同样需要重新验证。

编码交付和 `workspace_write` 工具会在写入前持久化操作，记录原始与目标 SHA-256 哈希。
恢复时识别已完成的写入、继续待完成操作；若与人工改动冲突，则暂停为 `edit_conflict`。
批准会重新核对操作；拒绝并提供反馈会从当前文件重新编码。缺少写入基线的旧编辑缓存需要重新规划。

**设计原则：**

1. 确定性逻辑留在代码中：版本校验、收敛、重试与路由。
2. 配置即代码：智能体、提示词、路由、SDK 和自动检查由 `config/` 下严格校验的 YAML 定义。
3. 先做便宜的检查：配置了检查时，先构建、检查类型、检查代码风格并运行测试，再调用模型评审。
4. 保留可追溯记录：步骤、提示词、回复、产物与事件均持久化并按内容寻址。

**仓库目录：**

| 路径 | 内容 |
|---|---|
| `config/` | 模型、角色路由、重试、用量配置、智能体、提示词、自动检查与策略 |
| `src/agentlab/core/` | 不依赖框架的核心逻辑与端口定义 |
| `src/agentlab/adapters/` | 运行时、沙箱、检查、存储等可替换实现 |
| `src/agentlab/api/`、`src/agentlab/cli/` | FastAPI 服务与 `agentlab` 命令行 |
| `src/agentlab/db/` | 数据库迁移与按项目隔离 |
| `ui/` | Web 控制台 |
| `evals/`、`tests/`、`scripts/` | 回归任务、评分、测试、演示与冒烟脚本 |
| `docs/` | [设计与路线图](docs/DISCOVERY.md)、[验收清单](docs/ACCEPTANCE.md)、[SDK 验收记录](docs/SDK_HANDOFF_ACCEPTANCE.md) |

## 安装

### 环境要求

- Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)
- Node.js 22.12+（22.x）、24.x 或 26+，以及 npm
- 使用 PostgreSQL 时需要 Docker；macOS 未安装 Docker Desktop 时可使用 `colima start --cpu 4 --memory 8`
- 兼容 OpenAI API 的模型网关；调用 Claude 时可另配兼容 Anthropic 的服务

### 1. 离线体验：无需密钥和数据库

```bash
uv sync
uv run agentlab config-check
uv run agentlab demo
```

`demo` 使用预设模型回复和内存存储运行完整循环。

### 2. 配置模型

```bash
cp .env.example .env
```

| 环境变量 | 用途 |
|---|---|
| `AGENTLAB_LLM_BASE_URL`、`AGENTLAB_LLM_API_KEY` | GPT 模型别名使用的 OpenAI 兼容网关 |
| `AGENTLAB_ANTHROPIC_BASE_URL`、`AGENTLAB_ANTHROPIC_API_KEY` | Claude 模型别名使用的 Anthropic Messages API，可带或不带 `/v1` 后缀 |
| `AGENTLAB_DATABASE_URL` | PostgreSQL 连接；留空时使用临时内存存储 |
| `AGENTLAB_EMBEDDING_BASE_URL` | 可选的远程向量嵌入服务；留空时使用本地 CPU 模型 |

模型别名定义在 `config/models.yaml`，角色分配在 `config/model_policy.yaml`；切换模型只需修改 YAML。
也可以在控制台的设置页填写密钥，密钥会脱敏显示并保存到 `.env`。

检查各个模型别名：

```bash
uv run agentlab ping
```

使用中转服务时，Claude 别名需要对应的服务地址，以及允许直接调用 API 的分组密钥；仅限特定客户端使用的密钥会被拒绝。

### 3. 启动数据库与服务

```bash
docker compose up -d postgres
uv run agentlab db-upgrade
uv run agentlab serve            # http://127.0.0.1:8765
```

### 4. 启动控制台

```bash
cd ui
npm ci
npm run dev                      # http://localhost:5173
```

开发服务器将 `/api` 代理到 `127.0.0.1:8765`。使用其他端口时设置 `AGENTLAB_API_TARGET`。

### 5. 可选：构建 Python 自动检查镜像

```bash
docker build -t agentlab/gate-python:latest docker/gate-python
```

Python 项目在每轮执行 FAST 检查，交付前执行 FULL 检查；Docker 容器离线运行，工作区只读。
项目也可以配置检查命令。没有匹配检查配置的项目在交付报告中标记为未经过自动测试。

## 使用

1. 在左侧栏点击新建项目，填写名称、目标与本地 Git 仓库根目录。选择文件夹会打开 macOS 文件夹选择器。
   项目规划智能体生成阶段与步骤，模型配置在同一对话框中设置。
2. 在项目对话中与 Root 交流。可以问“当前分支有哪些未提交改动”，也可以要求“修复 calc.add，让测试通过”。
   用“只回答，不修改”或“直接修改”表达意图。
3. 通过办公室、时间线与检查诊断查看进展；对话中也会出现任务进度和审批。
4. 运行暂停时，可以批准、拒绝并提供反馈，或中止。工作树交付需要人工确认；当前检出目录模式在检查与评审后自动完成。
5. 在记忆页上传全局或项目文档、测试检索并重建向量；监控页显示跨项目的智能体累计用量与估算费用。
6. 控制台顶部的智能体配置对话框可修改项目调度模式、模型与检索设置，并支持 YAML 导入导出。

默认直接修改所选仓库当前分支，包括 `main` 或 `master`，改动会立即出现在编辑器中，运行不会自行提交或推送。
需要隔离并行任务时，显式选择工作树模式；该模式使用内部记录提交，并在人工确认后把改动应用回原工作区。

常用命令：

```bash
uv run agentlab status                 # 查看持久化运行状态
uv run agentlab show RUN_ID            # 查看时间线、产物和待处理审批
uv run agentlab resume RUN_ID          # 重启或进程中断后继续
uv run agentlab decide RUN_ID approve  # 在终端处理审批
```

## 原生 SDK 工作流

安装固定版本的可选 SDK 依赖，并按进程或任务启用：

```bash
uv sync --extra harness
uv run --extra harness agentlab run 'Fix the failing test' --workspace /absolute/path/to/repo --runtime sdk
# 启动 API 与界面所需的服务：
AGENTLAB_RUNTIME=sdk uv run --extra harness agentlab serve
```

Root、调度、规划与总结继续使用原始模型网关。编码使用 `openai-codex`，单个正确性评审者使用
`claude-agent-sdk`；SDK 失败时不会回退到原始 API。原生模型 ID 在 `config/harness.yaml` 中配置，
独立于原始模型别名与调度分配；恢复时复用冻结的运行配置。原始 API 和模拟运行时保持原有评审配置。
此工作流支持编码任务，不支持自定义证据契约工具。

SDK 认证独立于 `AGENTLAB_LLM_*`。启动前设置 `OPENAI_API_KEY`（或登录原生 Codex CLI）与
`ANTHROPIC_API_KEY`。Codex 登录的 `auth.json` 会复制到私有调用目录，但不复制用户与项目的 Codex 配置。
Claude 使用私有配置目录，不继承用户或项目的设置、MCP 服务、技能和插件。安装依赖、创建服务不会调用付费 SDK。

**隔离与交付。** 编码智能体在 `AGENTLAB_DATA_DIR/harness/` 的持久化私有副本中工作。
副本包含允许携带的未提交与未跟踪源码，拥有独立 Git 元数据，并从绑定版本的不可变 Git 对象构建。
依赖、缓存、凭据与原生 SDK 项目配置会排除。Codex 使用工作区写入沙箱，不开放网络或额外临时写入根目录。
这个最小工作流不在副本中安装依赖；产物提升到权威工作区后，再运行现有自动检查。

文本新增与替换经过编辑日志与前后哈希校验。不支持的删除、重命名、二进制改动、可执行位变化、符号链接、
嵌套仓库和保留路径在提升前拒绝；未修改的二进制文件会保留在副本中。

Claude 使用另一个绑定源码版本的只读副本。仅允许读取、匹配路径、搜索和 SDK 结构化输出工具，
工具钩子限制源码读取范围。最终评审结果在本地校验，并由驱动器绑定身份和版本。
缺失、格式错误或失败的评审不能批准运行；自动检查、仲裁与人工确认流程保持不变。

**中断恢复。** 调用与会话 ID、输入版本、SDK 版本、源码和输出清单、标准化结果与检查点一同保存。
已完成调用会复用结果，避免再次调用模型；部分提升仅继续编辑日志中待处理的操作，并保留冲突的人工改动。
已完成但尚未标准化的 SDK 回复，在冻结副本未变时也可恢复。

调用前会再次校验副本与源码清单；导出文件逐个核对字节哈希，并通过文件存储和编辑日志保留 UTF-8 换行。
旧版缺少迭代号的评审记录，在输入指纹变化时也会阻止对同一版本重新发起调用。
**终止状态未知的执行不会自动恢复或重放。** 系统会暂停等待处理；拒绝并提供反馈才能创建新的隔离尝试，
仅点击批准不会重新打开状态未知的写入执行。原生会话数据和副本保留用于诊断；会话 ID 本身不是文件系统检查点。
此集成不额外引入阶段截止时间、终止策略或多个 SDK 评审者。

**用量。** 每个 SDK 调用通过现有账本记一次用量。Claude 报告的费用为估算；Codex 在此集成中提供 token 数，
没有实际账单金额，当前数值费用字段保留为不可用或零。缺少最终用量的中断调用会明确标为未计量。

参考：[Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)、[Claude Agent SDK for Python](https://code.claude.com/docs/en/agent-sdk/python)。
真实 SDK 交接、进程中断恢复和 JSONB 身份回归的验证见 [SDK 验收记录](docs/SDK_HANDOFF_ACCEPTANCE.md)。

## 测试

```bash
# 后端：测试、代码风格与类型检查
uv run pytest -q
uv run ruff check src tests
uv run mypy src

# PostgreSQL 集成测试：仅使用可丢弃的测试环境，不要使用应用数据表
AGENTLAB_TEST_DATABASE_URL=postgresql://agentlab:agentlab@localhost:5432/agentlab uv run pytest -q tests/integration

# 前端：测试、API 类型检查、生产构建与分发检查
npm --prefix ui test
npm --prefix ui exec -- playwright install chromium
npm --prefix ui run test:e2e
npm --prefix ui run check:api
npm --prefix ui run build
npm --prefix ui run check:distribution
```

修改 API 后，用 `npm --prefix ui run gen:api` 重新生成前端类型。
CI 在 PR 和向 `main` 推送时运行后端与前端检查。

**离线可视化验收。** `scripts/showcase.py` 使用固定模型回复，通过真实 API、驱动器和事件流演示七种场景：
正常交付、检查与评审返工、服务故障回退、预算暂停、评审冲突、工作区越界和振荡。

```bash
uv run python scripts/showcase.py          # 占用 8765 端口，先停止 agentlab serve
npm --prefix ui run dev                    # 打开 http://localhost:5173/?follow=1
```

可选参数：`--only S2,S5`、`--speed 2`、`--manual`（手动处理审批）。
使用 `--port 8766` 时，同时设置 `AGENTLAB_API_TARGET=http://127.0.0.1:8766`。

**真实模型测试，会产生少量费用：**

```bash
uv run agentlab smoke --trials 3                  # Docker 中的固定 Python 修复任务，停在交付确认处
uv run agentlab eval                              # 回归任务、Root 对话与评分
AGENTLAB_LIVE=1 uv run pytest -q -s tests/live    # 跨服务商交接
uv run python scripts/check_local_memory.py       # 本地嵌入上传与检索
```

**原生 SDK 集成测试，需要显式启用并会调用真实模型：**

```bash
uv sync --extra harness
AGENTLAB_LIVE_SDK=1 AGENTLAB_TEST_DATABASE_URL=<disposable-postgres-dsn> \
  uv run --extra harness pytest -q -s tests/live/test_live_sdk_handoff.py
```

按前述步骤提供网关与原生 SDK 认证。测试使用临时仓库和可丢弃数据库，覆盖评审驱动的修复、交付确认和进程中断恢复。

恢复逻辑修复后的本地后端回归为 **415 项通过、40 项按环境条件跳过**，未启用 PostgreSQL 和真实模型测试。
见[审查与修复记录](docs/CODE_REVIEW_2026-10-25.md)。
较早的真实 SDK 验收中，两种原生场景均通过；该记录早于最终隔离修复。
后续隔离修复由离线回归覆盖不可变副本、防篡改、导出哈希、旧评审重放保护和 CRLF 保留。
真实运行证据与认证方法见 [SDK 验收记录](docs/SDK_HANDOFF_ACCEPTANCE.md)。

完整验证范围与预期结果见[验收清单](docs/ACCEPTANCE.md)。

## 当前限制

- 面向个人本地使用的 Alpha 软件；API 绑定 `127.0.0.1`，没有身份认证。
- 内置自动检查覆盖 Python，其他项目需要自行配置检查命令。
- 向量排序在 Python 中完成，pgvector SQL 索引仍在规划中。
- 项目 schema 用于数据分离、导出和删除；访问控制依赖应用层过滤。
- ADK 运行时与 LiteLLM 虚拟密钥尚未实现。

路线图见[设计文档](docs/DISCOVERY.md)第 16 节。

项目对话与任务 Markdown 预览中的图片从所选项目目录读取，支持 PNG、JPEG、GIF、WebP、BMP、ICO、AVIF、SVG，
大小不超过 10 MiB。不预览符号链接路径和凭据文件。

中断的外部工具调用必须核对外部结果后再处理；确认完成或关闭记录都不会重新执行工具。
Docker 检查会屏蔽嵌套环境文件、密钥与凭据目录。本地沙箱直接在宿主机执行，不提供此类文件系统隔离。

## 参与贡献

欢迎第一次参与开源的朋友。小修复和文档改进可以直接提交 PR；较大功能或架构调整建议先开 Issue 讨论范围。
Issue 和 PR 均可使用中文或英文。

### 反馈问题与提出建议

在 [Issue 页面](https://github.com/Elyon0517/Multi-Agent-Platform/issues/new)说明预期行为、实际行为、复现步骤、
操作系统和运行时版本。适当提供最小示例、脱敏日志或截图。
发布前请移除 API 密钥、`.env` 内容、私有仓库代码和个人数据。
功能建议请说明要解决的问题，以及建议如何改善使用体验。

### 提交 PR

1. 在 GitHub 上 Fork 仓库，再克隆自己的 Fork，并添加上游仓库：

   ```bash
   git clone https://github.com/<your-username>/Multi-Agent-Platform.git
   cd Multi-Agent-Platform
   git remote add upstream https://github.com/Elyon0517/Multi-Agent-Platform.git
   git fetch upstream
   git switch -c contribute/describe-your-change upstream/main
   ```

   将 `<your-username>` 替换为自己的 GitHub 用户名。有仓库写入权限时，也可以直接在原仓库建立分支。
2. 按[安装步骤](#安装)准备环境，使用 `uv sync` 安装开发依赖；涉及界面时执行 `npm --prefix ui ci`。
   无需模型凭据的离线演示适合入门。
3. 每个 PR 聚焦一个改动。修复行为问题时补充回归测试，更新相关文档并遵循现有代码风格。
   修改 API 后，按[测试说明](#测试)重新生成前端类型。
4. 运行相关检查。后端应通过 pytest、Ruff、mypy；前端应通过测试、API 类型校验与生产构建。
   若跳过某项检查，请说明原因。真实模型测试需要显式启用且可能收费，并非每次贡献都需要运行。
5. 提交并推送分支：

   ```bash
   git add <changed-files>
   git commit -m "Describe the change"
   git push -u origin contribute/describe-your-change
   ```

6. 在 GitHub 点击“Compare & pull request”，或进入 [PR 比较页面](https://github.com/Elyon0517/Multi-Agent-Platform/compare)。
   目标分支选原仓库的 `main`，来源选自己的 Fork 与分支。使用清晰标题，说明问题、修改后的行为和验证方式。
   关联 Issue，例如 `Fixes #123`；界面改动请附截图。希望先讨论时可以提交 Draft PR。
7. 根据评审意见继续提交到同一分支，PR 会自动更新。等待仓库检查与维护者评审后再合并。

还不确定从哪里开始？可以先改进文档、复现问题或补充测试，也欢迎开 Issue 讨论想法。

## 致谢

工作区可视化与界面组件采用本项目编写的实现。工作区地图素材、地图、虚构角色和对话为本项目原创。
原创美术与角色绘制代码的 MIT 声明位于 `ui/src/assets/LICENSE.txt`；打包字体属于第三方资源，使用 SIL OFL 许可。

替换范围与来源审计见[界面替换验收](docs/UI_REPLACEMENT.md)。
完整来源见 [第三方声明](ui/THIRD_PARTY_NOTICES.md)与[素材来源](ui/src/assets/ATTRIBUTION.md)。
生产构建在 `THIRD_PARTY_NOTICES.txt` 中包含素材与字体许可，在 `DEPENDENCY_LICENSES.md` 中包含打包依赖许可。

## 来源、版权与署名

原始项目：[Elyon0517/Multi-Agent-Platform](https://github.com/Elyon0517/Multi-Agent-Platform)，
维护者为 [Elyon0517](https://github.com/Elyon0517)。项目代码采用 [MIT 许可证](LICENSE)，
同时受各文件与第三方声明约束。再分发时须保留适用的版权与许可声明。

撰写文章、制作演示或衍生项目时，欢迎注明原项目并附链接；这是礼貌性的署名请求，不构成对现有开源许可的附加限制。
详见[版权与第三方边界](COPYRIGHT.md)和[引用元数据](CITATION.cff)。
