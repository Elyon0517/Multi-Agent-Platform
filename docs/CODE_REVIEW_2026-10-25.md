# 代码逻辑审查（2026-10-25）

本次检查覆盖运行创建与恢复、循环状态机、审批与版本绑定、工作区隔离、事件流、知识上传和前端状态同步，并执行现有离线检查。以下 3 个问题均通过独立、临时目录中的复现验证。下文记录首次审查时的触发条件；这 3 个问题现已修复，修复方式与回归验证见文末。

## 1. [P1] 通过 `/resume` 恢复的运行无法通过取消接口停止

位置：`src/agentlab/api/app.py:483–491`；取消流程见同文件 `426–444`。

`resume()` 直接 `await driver.run(run_id)`，没有像 `spawn()` 那样把执行任务登记到 `run_tasks`。取消接口只会对 `run_tasks` 中的任务调用 `cancel()`。因此恢复中的运行仍然持有 run 锁，取消接口随后调用 `driver.cancel()` 时得到 `RunBusy`，返回 409；模型调用或检查命令继续执行。

复现步骤：

1. 使用临时仓库和 fake runtime 创建一个处于 PLANNING 的运行。
2. 将 planning handler 替换为通过 `asyncio.Event` 可观察的阻塞协程，避免真实模型调用。
3. 通过 ASGI 客户端并发发起 `POST /runs/{id}/resume`，等待 handler 开始。
4. 发起 `POST /runs/{id}/cancel`。

实际结果：取消返回 **409**，resume 请求仍在执行。普通 `/runs` 创建任务时会使用 `spawn()`，没有这个登记遗漏。

建议：将恢复执行也纳入统一的任务登记与清理流程；若需要保留 resume 等待结果的接口语义，可等待已登记的 task。增加“恢复期间取消”的 API 回归测试，验证执行协程实际收到取消，状态落到 CANCELLED。

## 2. [P2] 报告修订没有工作区占用检查，会留下无法启动的活动运行

位置：`src/agentlab/core/loop/driver.py:237–263`；API 入口 `src/agentlab/api/app.py:471–481`。

`revise_report()` 只锁定当前 run，不获取 workspace 锁，也不调用 `_check_workspace_available()`。同一工作区另有任务执行时，它仍会重新创建快照、增加修订计数并将已完成的报告切换为 CODING。API 随后调用 `spawn()`，而 `Driver.run()` 获取 workspace 锁时才失败。该异常发生在 `_run()` 的错误转审批逻辑之外，因此只记录后台失败日志，报告保留 CODING，既没有运行中的协程，也没有等待审批记录。

复现步骤及结果：

1. 以 fake runtime 生成一个 DONE 的只读报告 A。
2. 在同一工作区创建另一个 PLANNING 运行 B。
3. 修订 A：成功返回，此时同一工作区同时存在 B/PLANNING 和 A/CODING。
4. 持有 B 执行时使用的 workspace 锁，尝试执行 A：抛出 **RunBusy**，A 的持久化状态仍为 **CODING**。

建议：在修改报告修订状态前，获取与 create/run 相同的 workspace 锁，并检查其他活动运行；忙碌时返回 409，保持报告 DONE、修订计数和快照不变。增加同工作区活动运行与报告修订并发的测试。

## 3. [P2] 当前模式没有检查项时，Gate 将零检查结果标记为通过

位置：`src/agentlab/adapters/gates/config_gate.py:78–87`；配置定义 `src/agentlab/core/config.py:135–146`。

`GateCfg.steps` 和 `GateStepCfg.modes` 可以为空，也没有验证 FAST/FULL 的模式覆盖。`ConfigGate.run()` 遍历匹配项后无条件返回 `passed=True`。如果配置只包含 FAST 检查，FULL 阶段将执行零条命令，却被最终 signoff 报告归为自动检查通过。

复现配置：

```yaml
language: python
image: unused
markers: [pyproject.toml]
steps:
  - name: test
    argv: ["false"]
    timeout_s: 1
    modes: [fast]
```

调用 `gate.run(workspace, GateMode.FULL)` 的实际结果：

```text
passed=True, steps=[], failed_at=None
```

此配置下 FULL 阶段的零检查“通过”已复现；仓库默认 Python Gate 同时包含 FAST 和 FULL 检查，不会直接触发这一配置边界。

建议：配置加载时验证预期模式覆盖；运行时也明确处理零匹配检查项，拒绝执行或记录为未运行，避免将其呈现为检查通过。增加空 steps、空 modes 和只有 FAST 检查的回归测试。

## README 更新

- 顶部加入中英文 Alpha 状态与欢迎共创说明。
- 新增 Contributing 章节和导航入口：Issue 信息、Fork/分支、开发环境、检查、提交、PR base/head、Draft PR 和 review 流程。
- 明确不应提交密钥、私有代码和个人数据。
- 对照 `complete_in_place` 实现，修正默认当前 checkout 模式自动完成、worktree 模式人工审批的说明；这是现有行为的文档修正。

## 验证与边界

- 后端：`ruff check src tests` 通过；`mypy src` 通过（90 个源码文件）；`agentlab config-check` 通过。
- 前端：Vitest 16 个文件、77 项测试通过；API 类型检查、TypeScript 与生产构建、分发产物检查通过。
- 浏览器：Playwright 2 项通过、2 项跳过（历史截图对比和显式启用的 showcase）。
- 三个问题均使用临时仓库/内存 store/fake runtime 复现，没有改动用户项目数据。
- 后端：`pytest -q` 完成，**407 项通过、40 项跳过**，耗时 260.87 秒。跳过项包含未配置数据库的 PostgreSQL 测试和未显式启用的真实模型测试。

本次没有配置 `AGENTLAB_TEST_DATABASE_URL`，PostgreSQL 专用测试未执行，也未发起真实付费模型调用。单元测试和静态检查不能证明所有并发及外部服务路径均无问题。

## 修复记录

1. **恢复执行可取消**：`spawn()` 返回已登记的执行 task，`resume()` 等待这个 task，保留原来等待最终运行结果的接口语义；重复恢复请求在替换 driver 或 task 前返回 409，取消请求仍能找到原执行任务。取消接口正常返回 CANCELLED，正在等待的 resume 请求返回明确的 409 取消说明；请求本身被取消时保留 asyncio 取消语义。
2. **报告修订互斥**：修订流程先持有 run/workspace 锁，再检查其他活动运行；工作区忙碌时直接拒绝，不增加修订计数、不重置快照、不改变报告状态和历史产物。
3. **零检查不再通过**：配置校验拒绝空 `steps` 和空 `modes`；运行时针对没有匹配当前模式的检查项抛出明确错误，由现有运行错误处理流程暂停任务，不生成检查通过的 signoff。

新增 `tests/unit/test_review_fixes.py`，共 8 个测试用例。包含取消恢复任务及重复恢复、正常恢复结果兼容性、两种工作区占用情况、FAST/FULL 零匹配检查以及两种空配置。

修复后针对新增回归和相关 API/报告/Gate 测试：**21 项通过**。Ruff、mypy、配置检查和前端 API 类型一致性检查均通过。取消响应处理调整后，8 项新增回归再次通过；完整后端回归完成：**415 项通过、40 项跳过**，耗时 242.45 秒。
