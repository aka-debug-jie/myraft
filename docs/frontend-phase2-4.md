# Phase 2–4：拓扑视觉、详情与验收

基线 `55f37ea`。Phase 2 实现为 `6db7b46`，Phase 3 生产实现为 `0fb03aa`；后续提交收录 Phase 4 测试、文档和证据。SVG 为主入口，Flow/compare 继续共用模型与展示规则。未推送、未发布交付 ZIP；未提交的设计文档保持原样。

## 实际修改

- **拓扑**：Leader 改为暖金内环，Follower 使用状态弧；候选、不可达、未知、身份错误分别表达。按投影后的直径选择点、编号或完整角色/任期，放大后可以重新显示标签。选中轮廓限制在节点内，不改节点半径、固定槽位或路由算法。
- **关系**：鼠标和键盘焦点均可突出一条完整报告路径；Leader 显示报告数量摘要，不全亮。失效的悬停关系不再使其他边一直暗化。轨道是无交互装饰，不带节点/关系标记。颜色和透明度短过渡，不模拟流量，不持续呼吸。
- **检查器**：单一面板状态管理节点、证据、任务，避免并开重叠；明确区分节点数据未知与零进度。任务受理、提交确认和当前会话验证各自呈现，原始回执可展开。
- **手机**：点节点先看关系，点击“查看详情”才进入全屏。Portal 保持底层画布尺寸、选择、缩放和平移。返回保留上下文；Escape 清选并回原画布节点。确认框取消及禁用触发器都有可用焦点落点，背景快捷键不会抢走焦点。
- **错误**：未知写入提示在当前可见面板内展示，不能随手关闭，不新增重试；一般错误保留简短提示和展开诊断。

主要修改位于 `frontend/src/App.tsx`、`app.css`、`components/NodeBadge.tsx`、`nodePresentation.ts`、`TopologyPanel.tsx` 和两个渲染器。Go、API/client、操作授权、SSE、回执合并、中心确认模型、几何及 Raft 持久化代码均以摘要核对未变。原版日志、故障、性能、会话设置入口通过真实只读导航检查，继续使用原有实现。

## 实际验证

全部记录见 [本轮证据目录](../validation/frontend-phase234-20261024/README.md)。

| 验证 | 实际结果 |
|---|---|
| TypeScript、生产构建、前端单元 | PASS，28 项单元测试 |
| 3/11/20/50/100 × SVG/Flow × 三视口 | PASS，30 个布局组合；7 组原交互回归 |
| 新交互 | PASS，9 组，含手机焦点、未知写入、三态回执及反复开关详情 |
| Phase 1 保留回归 | PASS，12 组，含精确 int64、菜单、回执合并及中等宽度 |
| 中等宽度与旧版入口 | PASS，16 个布局/检查器组合、4 个旧版入口；另存 compare 截图 |
| 普通动效、减少动态 | PASS；每种模式下两渲染器各检查 60 次更新及 60 帧选举/离线/恢复状态变化，无丢边或角色错帧 |
| Go 格式只读检查、vet、build | PASS，Go 源码未修改 |
| Go test / race | 各 PASS 90 个顶层、52 个子用例；各跳过 1 个长期运行用例 |
| Python | PASS，44 项 |
| 真实集群 | 11/100 节点 × SVG/Flow，4 组 PASS，222 个节点通过独立算术参考 |
| 本轮 Windows 原生、真实手机、Safari/Firefox、长时压力 | NOT RUN |

真实流程包含：创建会话、双击只产生一次 2101 命令提交、完整校验、检查点、取消停止不发请求、停止 Leader、重选、再提交 3 条命令、原盘恢复、当前及固定历史前缀验证、导出摘要验证。每组最终均为 2104 条算术命令；内部 noop 不计入命令数。测试节点全部清理，配置/WAL/日志及导出保存在本轮独立原始目录。

`real-clusters/results.json` 保存各组原始回执与结果。重选耗时是本脚本“确认停止前→观察到新 Leader 且控制器不忙”的外部窗口，不是 Raft 内部选举时间，也不用于替换原课程性能矩阵。

截图包含暗色、浅色、投影、手机详情、比较模式和六种异常/空状态。截图使用稳定动画终态；普通动效正确性另以逐帧检查证明。几何检查覆盖节点命中、边界、标签、装饰包络、穿节点及正常单 Leader 场景的非法交叉，不把任意异常关系图承诺成新的路由算法。

## 同机性能比较

同一台 Linux 主机、相同脚本和帧序列、1440×900、普通动效，各三轮。下表为每轮更新显示确认 P95，单位 ms；测量包含两次 requestAnimationFrame，不是纯 CPU 耗时或 Raft 提交延迟。

| 100 节点 | 基线三轮 | 新版三轮 |
|---|---|---|
| SVG | 32.2 / 32.2 / 32.4 | 32.2 / 32.2 / 32.3 |
| Flow | 32.6 / 34.6 / 32.6 | 33.3 / 32.7 / 32.6 |

11/100 节点拖动帧 P95 为约 16.7–16.8ms，没有组合触发“多数轮次退化超过 20%”门槛。首次打开详情、长任务、CPU、堆和静态资源大小也保留原始值，不据三轮短测宣称稳定加速或可靠 P99。

真实集群中，1/5/10 浏览器各跨三轮稳定采集：11 节点始终 33 次监控 RPC，100 节点始终 300 次，未按浏览器数放大。校验和事件读取同样属于监控计数，不能解释成 Raft 吞吐。

手机详情另检查每渲染器 40 次真实指针开关，并用页内 DOM 点击补测 200 次，区分测试驱动器分配。首次 Portal 使用会注册一组事件委托；后续节点与监听器数量不累积，SSE 始终为 1。堆并非完全不变：页内补测第 20→200 次分别增加约 0.59MB（SVG）、0.81MB（Flow）；记录保留，不能据此证明零泄漏，也不能仅凭短时增长就认定存在无界泄漏。

## 复现与预览

使用项目支持的 Node 24 和 Go 工具链，在 `frontend/` 执行 `npm ci`、`npm test`、`npm run build`，再回仓库根执行：

```bash
go build -o raft-node .
go build -o raft-console ./cmd/dashboard
./raft-console -listen 127.0.0.1:8080 -data-root runs/review -node-bin ./raft-node -source-dir . -allow-control
```

浏览器进入 `/prototype/?renderer=svg`，本机需要明确启用控制后才能创建/操作会话；Flow/compare 可在页面切换。原版六页仍在 `/`。

自动化脚本均要求新的输出目录：

```bash
python scripts/prototype_ui_test.py --url http://127.0.0.1:8080 --output runs/ui-new --skip-performance
python scripts/phase234_ui_test.py --url http://127.0.0.1:8080 --output runs/interactions-new
python scripts/prototype_lifecycle.py --url http://127.0.0.1:8080 --output runs/lifecycle-new --motion no-preference
python scripts/phase234_performance.py --url http://127.0.0.1:8080 --output runs/performance-new
python scripts/prototype_acceptance.py --dashboard ./raft-console --node ./raft-node --output runs/real-new --counts 11 100
```

浏览器脚本需 Python 和 Playwright/Chromium。普通运行仍仅需 Go 编译产物及内嵌静态文件。

- [11 节点只读预览](http://100.108.139.80:8081/prototype/?renderer=svg&review=phase234)
- [100 节点只读预览](http://100.108.139.80:8082/prototype/?renderer=svg&review=phase234)

两个预览只替换控制器程序，111 个节点实例和原配置均保持一致；代理 POST/PUT/DELETE 仍返回 403。预览复用原有数据，真实自动化验收另用独立会话，不把两者混为同一次实验。

## 限制

- 100 节点手机总览中的微点用于定位，不是每个都有 44px 触控面积；使用搜索、缩放和“查看详情”连续操作。
- 本轮没有将其余工作区完整迁移到 React，也没有发布新 Windows 交付包或改变历史验收状态。
- 当前预览使用已有临时用户服务，不保证主机重启后自动恢复。已在本机通过 Tailnet 地址核对，未代替用户操作电脑实测。
- 资源检查是有限循环和短时实验；堆内存原始样本单独保存，不将监听器/DOM 稳定等同于所有对象零泄漏或长期稳定认证。
