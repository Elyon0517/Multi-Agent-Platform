# 真实 SDK 最小端到端联调记录

本次使用真实 Codex SDK、Claude Agent SDK 和独立 PostgreSQL 测试容器执行；没有伪造模型回复或 Reviewer Verdict。
联调从现有 Driver 的任务入口开始，Planner 保留原 RawRuntime；未改 Root 会话服务、阶段状态机、Gate 策略或多 Reviewer 配置。

## 验证结果

- 自动真实联调：`2 passed in 102.05s`。
- SDK 及恢复回归：45 项通过，含 PostgreSQL JSONB 恢复测试。
- Ruff、MyPy、`git diff --check` 通过。
- Codex SDK `0.163.0`，原生会话实际模型 `gpt-6.1-sol`。
- Claude Agent SDK `0.2.173`，模型 `claude-opus-5-5`；原生 SDK 实际通过已有 Anthropic 网关完成请求。
- Codex 使用已有 CLI 登录。Claude 认证仅在联调子进程中显式映射；未修改用户 `.env` 或全局 SDK 配置。

## 完整链路与已完成结果恢复

运行 ID：`678b97621220`，最终状态：`DONE`。

受控任务为整数 `clamp(n)`，完整要求是约束到 `[0, 10]` 并更新 README。
测试夹具故意要求 Coder 首轮只实现下界，Gate 也只覆盖下界和中间值，以确保可以实际观察审查后的修复。
Claude 收到完整验收条件，独立返回真实 findings；没有由测试替换 Verdict。

| 阶段 | 实际结果 |
| --- | --- |
| Codex 首次 Coding | 修改 README 和 clamp 实现，只处理下界 |
| 写入中断 | SDK 结果已持久化，第一份文件 applied、第二份 pending 时进程退出，退出码 86 |
| 新进程恢复 | 从 PostgreSQL 恢复并应用待写文件，未重新调用首轮 Codex |
| Gate | 首轮 FAST 通过 |
| Claude Review | `REQUEST_CHANGES`：发现上界未实现及文档与完整要求矛盾 |
| Codex 修复 | 实现上界并修正文档 |
| Gate / Claude 再审查 | FAST 通过、`APPROVE` |
| 完成检查 | FULL Gate 通过，signoff 绑定最终 revision |
| signoff | 测试脚本以 `sdk-integration-fixture` 身份批准，仅作用于测试仓库，状态 DONE |

初审 revision：`40013212f34888f6d1e49d6678a4bf95ab2d7061d9b1d50e5febe2417c2823d7`。

修复后 revision：`c1602c0063166b9b8730f8037d4d360a0df235b2e6c166ca19d3b021e52363f8`。

调用记录与用量账本确认只有两次 Codex（初次实现、修复）和两次 Claude Review；恢复没有增加重复调用。
Gate 结果、Verdict 和 signoff 均匹配各自 revision。夹具原测试文件未修改；最终额外断言 `clamp(-3)=0`、`clamp(4)=4`、`clamp(18)=10`。

详细本地证据：`.agentlab/sdk-live/pytest-verified/test_real_sdk_review_repair_an0/result.json`。

## SDK 执行中的未知中断

运行 ID：`37acca2e6375`。

真实 SDK 已返回 session/turn ID、完成状态尚未知时退出进程，退出码 87。
新进程恢复进入 `interrupted_call`；批准继续后，既有未知调用仍被拒绝重放，错误标识为
`harness_interrupted_requires_replan`。验证只有原调用记录，没有新 SDK 调用，没有 EditJournal 写入，正式文件保持原样。
最后由测试脚本取消该测试任务。

详细本地证据：`.agentlab/sdk-live/pytest-verified/test_real_sdk_running_interrup0/unknown_interruption.json`。
这里验证的是未知执行的安全暂停，不声称可以续接执行到一半的 SDK turn。

## 本次发现并修复的接入问题

PostgreSQL JSONB 会重排对象键。旧实现将非规范化 Prompt 文本的哈希纳入 invocation ID，导致语义相同的输入在
恢复后可能生成新 ID，从而错误地再次调用 SDK。真实中断验证复现了这个问题；仅内存存储的测试没有暴露它。

修复仅涉及 Harness 接入层：

1. 实际 Prompt 使用固定排序的 JSON 序列化，恢复前后字节一致。
2. 同一 Coder 写入 scope 已有调用时，即使 Prompt/配置指纹变化，也拒绝创建另一调用；旧格式 checkpoint 同样保护。
3. 记录 Reviewer iteration，限制相同 revision/轮次的重复调用。
4. 增加对象键重排、指纹变化与实际 PostgreSQL 未知调用恢复的回归测试。

未引入新的阶段期限、终止策略或多个 SDK Reviewer。

## 重复执行

安装 `.[harness]`，准备明确可丢弃的 PostgreSQL 数据库，并配置现有网关和 SDK 认证后执行：

```sh
AGENTLAB_LIVE_SDK=1 AGENTLAB_TEST_DATABASE_URL=<disposable-postgres-dsn> \
  uv run --extra harness pytest -s tests/live/test_live_sdk_handoff.py
```

真实模型调用会产生用量，默认测试运行会跳过这两个用例。
底层分阶段入口为 `scripts/check_sdk_handoff.py`，测试专用超时不改变生产阶段策略。
测试数据库容器在验证和证据导出后清理；本地 JSON 证据保留。
