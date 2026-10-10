# 验收清单：多模型交接与 Office 可视化

在开始 Monitor 模块（P4）之前，用这份清单确认基础功能可用。自动化部分离线即可运行；真实模型部分会产生少量费用。

## 一、自动化测试（离线，不花钱）

```bash
uv run pytest -q tests/unit/test_acceptance_cross_provider.py
```

| 测试 | 检查什么 |
|---|---|
| `test_claude_builds_and_gpt_reviews_the_claude_diff` | planner / coder（Claude）写的计划和代码，真的交到了 GPT reviewer 手里；每个角色用的模型和厂商正确 |
| `test_claude_outage_falls_back_to_gpt_root` | Claude 不可用时，planner 自动改用 GPT（root），任务仍能完成 |
| `test_missing_claude_key_pauses_instead_of_hanging` | 没填 Claude key 时，run 暂停并显示 `provider_credentials_missing`，不会卡住 |
| `test_current_catalog_mixes_providers_where_it_matters` | 当前 `config/models.yaml` 里，写代码与评审确实同时用到 GPT 和 Claude |

```bash
cd ui && npx vitest run src/scene/adapter/floorLifecycle.test.ts
```

| 测试 | 检查什么 |
|---|---|
| planner → coder → gate → 三个 reviewer → 审批 | 每一步只有正在工作的 agent 出现在 Office；完成后离开；三个 reviewer 同时出现、逐个离开；结束后全部空闲 |
| 显示实际模型 | agent 完成后显示实际回答的模型名 |
| Root 常驻 | Root 一直在座位上；对话回答时显示为思考中 |
| 暂停时清场 | run 中途暂停（预算、执行错误）时，未完成的 agent 应离开 Office（已修复并通过回归测试） |

## 二、真实模型（需要两个 key，约几美分）

```bash
uv run agentlab ping
```

预期：每个别名一行 `"ok": true`，且至少一行 `"provider": "anthropic"`、一行 `"provider": "openai"`。

```bash
AGENTLAB_LIVE=1 uv run pytest -q -s tests/live
```

预期：打印每个 step 的角色、厂商和模型；run 停在 `signoff`；planner、coder 和三个 reviewer 都参与；`openai` 和 `anthropic` 都出现；没有 `fallback_from_`（否则说明 Claude 实际没被调用）。

## 三、可视化演示脚本（不花钱，只需看界面）

```bash
uv run python scripts/showcase.py
```

```bash
cd ui && npm run dev
```

先停掉 `agentlab serve`（脚本占用同一端口 8765），然后打开 `http://localhost:5173/?follow=1`。`follow` 让界面自动切换到最新的 run。脚本启动真实 API、Driver、Gate 和事件流，只把模型回复换成带延时的剧本，模型名来自 `config/models.yaml`。终端会逐个打印场景和「应该看到什么」。

| 场景 | 看什么 |
|---|---|
| S1 正常流程 | Claude 的 planner、coder（调用工具时显示工作中）→ Gate → 三个 reviewer 同时出现、逐个离开（GPT / Claude 混合）；同一 workspace 再开 run 被拒（终端显示 409） |
| S2 Gate 失败 + 评审要求修改 | Gate 变红，coder 回来重做；下一轮 arch-reviewer 提意见；第三轮通过 |
| S3 Claude 故障 | planner 重试变慢，最后用 GPT 完成（显示 GPT 模型名），coder 仍是 Claude |
| S4 预算中途暂停 | 三个 reviewer 出现后立即暂停，必须全部离开；提高预算后重新出现 |
| S5 评审意见矛盾 | arbiter 进入升级状态；人工反馈后 coder 重做，再次评审通过 |
| S6 写出 workspace | coder 暂停并离开；run 被中止，全部空闲 |
| S7 震荡 | 同样的错误修改两次，Gate 两次失败后升级，run 被中止 |

常用参数：`--only S2,S5` 只跑部分场景；`--speed 2` 加速；`--manual` 不自动审批，由你在界面点批准 / 反馈 / 中止。

## 四、界面目测（真实模型）

启动：

```bash
uv run agentlab serve
```

```bash
cd ui && npm run dev
```

在浏览器打开 `http://localhost:5173`，建一个指向小型 Python 仓库根目录的项目（可复制 `evals/tasks/py-fix-subtract` 到 `~/.agentlab-workspaces/` 下并 `git init`），在对话里依次发送：

| # | 发送的消息 | 应该看到 |
|---|---|---|
| 1 | 「这个仓库的入口文件是哪个？」 | 只有 Root 在思考，然后直接回复并附文件来源；没有其他 agent 出现，没有新 run |
| 2 | 「把 subtract 修好，让测试通过」 | Root 回复任务确认 → Planner 出现、完成后离开 → Coder 出现（调用工具时显示工作中）→ Gate 出现 → 三个 reviewer 同时出现、逐个离开 → 对话里出现进度消息和审批卡片、总结 |
| 3 | 在 2 进行中问「现在到哪一步了？」 | Root 回答当前阶段（只读），不打断任务 |
| 4 | 点审批卡片的「批准」 | 所有 agent 回到空闲，Office 只剩 Root；项目 step 打勾 |
| 5 | 点 agent 卡片 | 每个 agent 显示实际用的模型：planner / coder 为 Claude，arch / test-style reviewer 为 GPT |

需要 2–3 个以上 agent 的任务可以用第 2 条；想看更多轮迭代，可以让任务带一个容易被 reviewer 提意见的要求，例如「给 subtract 加类型检查和负数测试」。

## 已修复的回归

- run 进入 `WAITING_HUMAN` 时，仍在 `thinking` / `working` 的 agent 会回到 idle 并离开 Office；已完成 agent 的模型名与审批等待状态保留。`floorLifecycle.test.ts` 的四项测试均通过。
- 人物头顶显示 agent 名称（Root、Planner、Coder、各类 Reviewer），迭代次数与模型信息保留在详情中。

可视化脚本的完整启动、备用端口和停止步骤见 [README](../README.md#scripted-office-acceptance-offline)。
