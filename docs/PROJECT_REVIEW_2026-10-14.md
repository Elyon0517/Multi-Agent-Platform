# 项目审查与素材替换记录 — 2026-10-14

审查基线：`main` / `e939ae5`。执行 `git fetch origin` 后，`git rev-list --left-right --count HEAD...origin/main` 返回 `0 0`，工作区初始无修改。实施分支：`codex/project-review-original-assets`。

范围：仓库结构与配置扫描、核心任务状态机与人工审批、工作区/分支隔离、Root 对话与 MCP 工具授权、存储与删除、事件流、前端 API/状态桥接、办公室渲染、所有受版本控制的媒体/字体、构建与许可证分发。重点读取高风险执行路径，结合现有测试；这不是逐行无缺陷保证，也不包含未提供的部署系统。

## 初始发现（以下五项功能问题已修复）

### [P1] 外部工具执行中可删除所属聊天，产生已执行但无法记录的结果

位置：`src/agentlab/api/app.py:322` 与聊天删除路径 `:285`；项目删除路径 `src/agentlab/bootstrap.py:59`。

`decide_tool` 仅持有 `tool-approval:{id}` 锁，在 `await svc.mcp.call(...)` 期间没有持有 `turn:{thread_id}` 锁。聊天/项目删除只检查 turn/thread/run 锁，不检查正在执行的工具。另一请求能成功删除聊天；外部写入仍完成，随后保存结果到已经不存在的聊天时返回 500。

用 ASGI 客户端与内存存储、本地 FakeHub 复现（未调用真实外部服务）：创建全局聊天和待审批工具 → 启动允许执行请求 → FakeHub 暂停工具调用 → DELETE 聊天 → 释放工具。结果：`thread_delete=200`、`approval_response=500`、`external-write-completed`、`threads_remaining=0`。

建议：工具审批执行、聊天删除与项目删除使用同一生命周期锁；执行前确认聊天存在，运行中拒绝删除。新增包含上述交错顺序的回归测试。

### [P1] 工具外部写入先执行，执行状态后保存，异常重启可能重复写入

位置：`src/agentlab/api/app.py:335–340`。

数据库中的状态在远端操作完成前一直是 `pending`。若远端写入成功、进程却在保存 `done` 前退出，下次允许同一审批会再次调用该工具；执行锁只防同时执行，无法证明前一次已经完成。任务 run 的 interrupted-call 恢复机制未覆盖此 MCP 审批路径。此项为代码执行顺序分析，未通过真实外部服务触发。

建议：调用前持久化 `executing` 状态，崩溃恢复转为 `unknown_outcome`，要求核对外部结果后处理；支持工具幂等键时使用稳定审批 ID，不自动重试未知结果。

### [P1，开发服务暴露时] 前端开发工具链有已知漏洞

位置：`ui/package.json:31–32`、`ui/package-lock.json`。

本次 `npm audit --json` 报告 6 个受影响依赖：critical 2、high 1、moderate 3。包括 Vitest、tinypool、Vite、esbuild、vite-node、@vitest/mocker。直接依赖 Vite/Vitest 的建议修复涉及主版本升级，不能视为可无条件应用的补丁。`vitest run` 没有启用 UI 服务，漏洞分级不等同于当前运行已被利用；部分路径依赖开发/UI 服务暴露或不可信 worker 配置。生产浏览器包与这些开发工具的风险应分开判断。

建议：在独立变更中升级兼容的 Vite、React 插件、Vitest 并复测；在升级前保持开发服务仅供本机使用。审计结果可用 `npm --prefix ui audit` 复查，数量随上游数据库变化。

### [P2] Docker Gate 只遮蔽根目录 `.env*`，嵌套凭据仍进入容器

位置：`src/agentlab/adapters/sandbox/docker.py:33–37`。

使用 `cwd.glob('.env*')` 只覆盖仓库根目录，而整个工作区会通过读写 bind mount 挂载。像 `backend/.env`、`services/api/.env.local` 等文件没有遮蔽，Gate 测试代码可以读取。环境变量清洗无法阻止读取这些文件；即使 `--network none`，也可以通过 stdout/stderr 进入 Gate 报告。此项用挂载参数检查确认，未运行恶意容器或读取真实凭据。

建议：使用排除敏感文件的执行快照或递归遮蔽策略，并检查嵌套仓库、符号链接与生成的报告；为嵌套 `.env` 补测试。LocalSandbox 是直接本机执行，其隔离能力本来就不同，应清楚标注。

### [P2] Markdown 本地图片加载入口尚未实现

位置：`ui/src/bridge.ts:126`、`ui/src/hooks/useWorkspaceImage.ts`、`ui/src/markdown/MarkdownPreview.tsx`。

`readBinary` 无条件返回 `unsupported`。因此用户报告/文档中的本地截图只能显示图片占位符，无法通过现有 hook 加载。新办公室图集通过 Vite/Pixi 正常加载，不经过此入口。

建议：实现带项目边界校验、类型和大小限制的只读图片 API，接上 bridge，再验证路径穿越/符号链接；或在文档中明确当前不支持本地图片预览。

## 逐项修复结果

1. **工具执行与删除并发**：审批执行全程持有聊天 turn 锁与审批锁，先检查聊天归属；与聊天删除、项目删除和消息回答共享生命周期锁。内存与 PostgreSQL 回归测试均验证执行中删除返回 409，工具仅调用一次，结果正确保存。
2. **异常后的重复执行**：远端调用前提交 `executing` 标记；取消、传输异常或重启恢复为 `unknown_outcome`，无法再次 allow。结果与聊天通知在同一事务中保存；远端成功而本地保存失败时，仍保留 executing 标记并在恢复时拒绝重放。只允许用户核实后 `confirm_done`，或 `close_unknown` 关闭记录，两种操作均不调用工具。恢复跳过仍持有锁的活跃调用，聊天满 1000 条也能保存审批结果。前端展示执行/完成/未知状态，并提供核实与关闭按钮。
3. **开发依赖漏洞**：升级到 Vite 8.3.4、Vitest 5.0.4、React 插件 6.1.2，更新锁文件，当前 `npm audit` 为 0。测试、开发服务器和生产构建均验证。Node 要求更新为 22.12+ 的 22.x、24.x 或 26+。[Vite 迁移说明](https://vite.dev/guide/migration)、[Vitest 迁移说明](https://vitest.dev/guide/migration/)。
4. **嵌套凭据暴露**：Docker 递归检查各层目录，遮蔽 `.env*`、密钥、凭据文件及 `.git`/SSH/云凭据目录；处理内部符号链接别名与循环链接，敏感链接逃出工作区时拒绝启动。文件使用空设备遮蔽，目录使用只读空 tmpfs；Docker CSV 挂载参数正确处理逗号路径。真实 Docker 验证测试凭据不能读出、宿主文件未被修改，正常工作区输出仍能写回。`.env.example` 保留为模板。LocalSandbox 仍是直接本机执行，README 明确这一边界。
5. **本地图片预览**：新增 `/projects/{project_id}/images?path=...`，只接受注册项目 ID 与相对图片路径；逐级目录描述符和 `O_NOFOLLOW` 阻止符号链接逃逸/替换，拒绝凭据路径、非普通文件、错误类型、超 10 MiB 文件与带 DTD 的 SVG。响应带 nosniff、attachment 与 sandbox CSP。bridge 接上二进制 API，聊天与任务 Markdown 使用项目 ID 预览图片，取消请求和卸载时释放 blob URL。真实 Chrome 验证 PNG/SVG 解码成功、未知结果核实与正常审批完成、切换会话释放图片 URL，无 page error。

同时解决初始构建体积建议：办公室渲染与 Pixi Texture 按需加载，Project/Memory/Monitor/Settings 视图拆分。主入口由初始约 1,023 KB 降至 **421 KB**（gzip 约 **128 KB**），所有单独 chunk 均低于默认 500 KB 阈值。

**最终验证**：后端完整回归 **344 passed**（298 单元 + 46 集成，无跳过），前端 **48 passed**；Ruff、MyPy（84 个源码文件）、OpenAPI 契约检查、TypeScript 与 Vite 生产构建全部通过；`npm audit` **0 vulnerabilities**。真实 Docker 的遮蔽验证与 Chrome 的图片/审批/懒加载验证通过，所有 chunk 均低于 500 KB。

初始验证列表保留为审查基线，并不代表修复后的状态。真实数据库测试使用独立的临时 PostgreSQL 容器，测试结束后销毁，不接触用户现有数据库；外部 MCP 写入均由 FakeHub 模拟，未调用真实外部服务或计费模型。

## 本次已实施的素材清理

LimeZu 官方页面许可明确禁止把素材再分发给他人，购买使用许可不能作为公开提交原始图集的依据。[官方许可](https://limezu.itch.io/moderninteriors)。旧源码自身也记录了再分发限制。仓库没有可独立核验的购买凭证；本次不再依赖购买声明。

- 删除 `interiors.png`、`office-tileset.png`、`a5-office-floors-walls.png` 及旧许可文件。
- 删除两张旧 Tiled 地图；替换为从源码生成的原创 Studio / Atrium 地图和 `workspace.svg` 图集。
- 图集、地图均由 `scripts/generate_office_assets.py` 生成，没有第三方图片输入、描摹或重着色。保留 16×16 网格、16 个工作座位、茶水间、显示器亮灭和活动锚点；两套地图全部关键站位可从入口寻路到达。
- 15 个角色替换为原创虚构人物：重新设定名称、发型/服装组合、肤色/配色与简介，没有影视/真实人物参考。
- 茶水间对白整文件重写；移除影视主题卡片、角色相关 key 和显式台词/梗，默认协调者名改为 `Root`。保留用户已经自定义的名字与顺序；未知/旧主题配置回退到 `studio`。
- 保留有效的 MIT 上游代码署名与 OFL 字体，并补全直接来源代码的 ISC 完整声明。[MIT 原文](https://raw.githubusercontent.com/HarnessMD/munder-difflin/main/LICENSE)、[ISC 原文](https://raw.githubusercontent.com/shahar061/the-office/main/LICENSE)。原创 artwork 使用单独 MIT 许可，没有替用户给整个项目新增总许可证。
- README 的远端图片徽章改为纯文本版本说明，消除额外图片外链；CSS 游标与内联 SVG 为许可代码中的几何绘制，纳入出处清单。
- Vite 构建自动输出 `THIRD_PARTY_NOTICES.txt`，包含代码、原创素材和字体的许可全文，避免源码带有声明而发布包遗漏。

完整当前素材清单及出处：`ui/src/assets/ATTRIBUTION.md`。仅保留三份 OFL 字体、一张原创 SVG 和两张原创地图；旧来源名称出现在依法保留的代码署名与历史说明中，不是当前产品主题。

**Git 历史边界**：当前工作树及新构建产物已清理，但旧图集、地图与旧角色/台词仍存在于先前提交中。彻底清理可分发 Git 历史需要另行重写远端历史并处理旧标签、release、fork、缓存与克隆。此次没有执行破坏性的历史重写或 force-push；不能将这次删除描述为 GitHub 历史已经清理。可先发布当前干净源码快照；公开历史重写前应保存备份、列出受影响 refs 和旧素材路径，再协调现有克隆。

## 初始审查时的验证与限制

- 后端单元测试：277 passed；Ruff `src tests` 通过；MyPy 检查 82 个源码文件通过。
- 集成测试：12 passed、30 skipped；跳过项需要 `AGENTLAB_TEST_DATABASE_URL` 的可丢弃 PostgreSQL，未验证真实数据库迁移与并发路径。
- 前端：43 tests passed，TypeScript 与 Vite 生产构建通过。新增检查涵盖两套地图所有活动站位的连通性、显示器图块、15 个角色可见步行动画、退休素材/引用检测和偏好迁移。
- 原创素材重复生成的 SHA-256 全部一致。
- Chrome 实际 Pixi WebGL 渲染两套地图和 15 个角色，无 page error；另外执行应用内主题切换烟测，API 使用本地 mock，不访问真实项目/模型/MCP 服务。
- 构建目录已移除旧图片，包含原创 SVG、OFL 字体和完整许可声明。主前端 chunk 仍约 1 MB（gzip 约 333 KB），建议后续按视图拆包。
- 未调用计费模型、真实外部写工具、真实数据库或 Docker Gate；未升级存在主版本兼容影响的依赖。初始变更仅包括素材清理与审查报告；随后五项功能发现已按上方「逐项修复结果」完成修复。
