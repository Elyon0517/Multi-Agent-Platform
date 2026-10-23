# UI 实现替换与验收（2026-10-23）

## 范围与结论

本次从 `1d0ee77` 开始，替换历史上由 `munder-difflin` 和 `the-office` 移植的前端实现。
当前生产代码不再使用这些移植实现；没有通过改名、格式化或删除来源注释来替代重写。
Python Root、状态机、SDK Coding/Review、revision、EditJournal 和恢复机制未改动。

保留的是与现有应用兼容所必需的接口、事件字段、持久化键、主题/角色 ID、地图坐标和视觉参数。
`design/appearance.json` 明确记录原有配色、尺寸、字体与间距参数，新的样式生成器据此维持界面。
重新实现的图标、角色绘制和动画维持像素风格；不把“保留界面布局”表述为逐像素相同。

## 实现清单

| 范围 | 当前实现 |
| --- | --- |
| 地图、碰撞、坐标、图块 | 地图建立单次索引；独立解析图层、出生点、区域与图集；字符层排序 |
| 寻路、相机 | 整数格 A*；按经过时间平滑缩放/移动，限制地图边缘，支持自动取景和临时聚焦 |
| 角色、精灵、画像 | 显式移动/入座状态；项目角色配色；独立像素缓冲绘制与纹理上传，失败可重试 |
| 气泡、交接消息、显示器 | 共用标签布局与生命周期；消息弧线/完成状态由 tick 驱动；独立显示器叠层 |
| 场景调度 | Store 驱动进出场、异步座位预留、离场释放、主题重建、暂停渲染、GPU 重试与资源清理 |
| 任务板 | 阻塞/待办分栏、在岗任务桌面便签、已完成归档；无在岗负责人时退回墙上，不丢失任务标记 |
| 像素控件、角色卡片 | 独立 React 实现；保留外框尺寸、选择、键盘激活、重命名、备注、拖动排序和上下文条 |
| 看板、详情、消息线程 | 独立解析/渲染；任务状态写入仍通过现有 bridge；保留问答/依赖历史、展开与回复 |
| Markdown、图片 | 独立链接解析及 AST 处理；保留 GFM、卡片换行、项目图片、URL 回收和不执行 HTML |
| Telemetry、异步读取 | 独立 reducer；丢弃过期快照，去重重放的工具结果；取消挂载后不再采用请求结果 |
| 样式、语言 | 新样式生成器与全局规则；只保留当前 UI 使用的语言目录，删除旧桌面端未使用的文案 |

删除当前页面没有调用的 `SeatPool`、`SpriteAdapter`、`AskMeTab`、`askMeOrder`、
`MemoryGraphPanel`、`memoryGraph/*` 以及旧 `design/theme.ts`。
旧场景中已停用的环境活动调度不带入新场景。提问板打开现有 Root 对话审批入口，不再切到已无页面的旧 human 标签。
原创 atlas、两套地图、角色身份/配色和原创对白保留；字体仍按原作者和 SIL OFL 署名。

## 来源复查

使用以下参考快照核对原来的来源清单和当前实现：

- `chaitanyagiri/munder-difflin`：`51a628e8918d9c808a4a99839acaf66fbea42e7e`。
- `shahar061/the-office`：`9a11be793321f19bf07e93a407e2dbaffe6151d7`。
- 改造前本仓库：`1d0ee772448ca7c80d1441dfa9d60010870d4886`。

参考仓库仅位于工作区外，用于审计；没有将它们加入本仓库依赖、构建输入或发行包。
先按旧 `THIRD_PARTY_NOTICES.md` 的清单逐模块检查替换/删除，再进行 token 扫描。
扫描跨文件名检查连续 120 个 token 的匹配，排除 TypeScript 的 import/export、interface/type
声明；这些互操作声明不能用于判断实现是否被复制。
对 85 个当前生产文件与 342 个参考源码文件运行后，结果为 **0 个匹配文件**。

复查命令（参数是固定快照的本地源码目录）：

```sh
node scripts/audit_ui_sources.mjs \
  /path/to/munder-difflin/src/renderer/src \
  /path/to/munder-difflin/src/shared \
  /path/to/the-office/src/renderer/src
```

该扫描是防止重新引入旧实现的辅助手段，不能单独证明独立实现，更不是法律结论。
当前结论同时依赖模块清单、实现审查、资源检查和运行回归。
旧 Git 提交及历史审计/ADR 保留真实来源记录；没有重写 Git 历史。

## 回归与界面验收

```sh
npm --prefix ui ci
npm --prefix ui test
npm --prefix ui exec -- playwright install chromium
npm --prefix ui run test:e2e
npm --prefix ui run build
npm --prefix ui run check:distribution
npm --prefix ui run check:api
```

新增覆盖包含：障碍绕行/不可达、地图坐标/碰撞与出生点、帧率变化后的相机结果、任务便签退回墙面、
消息结束、GPU 重试与取消、重命名重复提交/IME/失败、卡片键盘操作与子控件事件、
主题切换保留 roster、问答历史、Markdown 链接/HTML/远程图片保护、延迟请求丢弃、图片 URL 生命周期和用量去重。

浏览器用例不调用真实模型：API 路由使用固定夹具，仅运行真实 React/Pixi 页面与浏览器交互。
覆盖两套房间、反复主题切换/场景卸载重建、窄屏、角色退出重返、重命名和任务详情。

另外将 `1d0ee77` 的 UI 单独在本地提供服务，运行可选对照验收：

```sh
BASELINE_UI_URL=http://127.0.0.1:5179 npm --prefix ui run test:e2e
```

对照用例检查办公室区域、canvas、首张角色卡片的尺寸与位置及关键配色/字体参数，保存前后截图供人工检查。
不随当前发行版打包旧实现。未设置 `BASELINE_UI_URL` 时，只跳过这一迁移专用用例。
浏览器截图在忽略的 `ui/test-results/` 下，CI 已接入常规浏览器交互回归。

本次验证结果：77 项单元/组件回归通过；3 项浏览器验收通过（含改造前版本对照）；
TypeScript、生产构建、API 合同检查及 `git diff --check` 通过。
发行检查验证了 34 个构建文本文件、字体署名及依赖许可证，未发现退役来源/素材的引用。
