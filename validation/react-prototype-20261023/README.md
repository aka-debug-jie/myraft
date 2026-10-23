# React 原型验收 · 2026-10-23

基线 `6ae0cfe`；被测最终生产代码提交 `1e099e66eaab77e0829deeed00c1b57f91aaf831`。编译器内嵌的 Git 信息、67 个生产输入摘要和实际二进制摘要见 [build.json](build.json)。后续仅补充测试、文档和证据，最终源码是否对应本轮产物可逐文件核对。Go 生产代码和原六页资源未修改。

本轮环境：Linux x64，Go 1.27.2、Node 24.22.1、Python 3.12.7、Playwright Chromium；真实节点使用 `GOMAXPROCS=1`。原始运行目录保留在 `.tools/react-prototype-20261023/`；公开副本中的主机绝对路径已脱敏，原始/交付摘要对应 [provenance.json](provenance.json)。

## 已执行检查

| 检查 | 结果 | 证据 |
|---|---|---|
| TypeScript、生产构建、单元测试 | PASS，17 项；包含 DOM 端点失效的库契约复现与固定端点对照 | [测试输出](checks/typescript-tests.txt)、[构建](checks/vite-build.txt) |
| Go fmt / vet / test / build | PASS，90 顶层 + 52 子测试；1 项可选长时测试 SKIP | [Go](checks/go_test.json) |
| Linux race | PASS，同上；1 项可选长时测试 SKIP | [race](checks/go_race.json) |
| Python 标准库回归 | 44 PASS | [输出](checks/python.txt) |
| 原版浏览器回归 | 24 PASS、1 项 GET-only live SKIP；本轮另有真实验收 | [输出](checks/legacy-ui.txt) |
| 原 3/11 节点 smoke | PASS，故障、重启及少数派检查 | [输出](checks/smoke.txt) |
| 合成布局和几何 | 30 PASS：3/11/20/50/100 × SVG/Flow × 三视口；无节点重叠、越界、遮挡、穿节点及稳定单 Leader 边交叉 | [逐项结果](ui/results.json) |
| 交互与异常 | 7 组 PASS，含键盘、筛选、触控、只读、旧作用域、未知写入、懒加载失败 | [逐项结果](ui/results.json) |
| 真实集群 | 4 组 PASS；SVG/Flow 各 11/100 节点，222 个节点通过独立算术参考 | [原始结果](real/results.json) |
| Windows x64 交叉构建 | PASS；没有据此认定 Windows 实操通过 | 见 checks.json |
| Windows 原生 / Safari / Firefox / 长时运行 | NOT RUN | 当前阶段边界 |

真实四组都完成：浏览器创建会话→2101 条命令（双击仅一次提交）→完整校验→检查点 index=2102→取消停止不执行→确认停止 Leader→重选→再提交3条→原数据恢复→历史和当前校验→导出核对。每组停止后原 WAL、配置和记录保留，测试监听端口为0。

| 渲染器 | 节点 | 停止确认至外部观察新 Leader | 独立算术节点 | 检查点 |
|---|---:|---:|---:|---|
| SVG | 11 | 3.633 s | 11 PASS | 2102，index/hash/x 保持 |
| SVG | 100 | 4.166 s | 100 PASS | 同上 |
| React Flow | 11 | 4.422 s | 11 PASS | 同上 |
| React Flow | 100 | 4.118 s | 100 PASS | 同上 |

以上为单次课堂流程，不是选举性能统计，也不据此判断渲染器影响重选速度。每组三轮采集下，1/5/10 浏览器分别都是 11 节点33次、100 节点300次监控 RPC。

## 同环境小样本比较

100节点、每轮120次状态更新、每种渲染器3轮：

| 渲染器 | 三轮显示确认 P95 | 每轮浏览器任务 CPU 总量 | 首次节点就绪中位数 | 首次检查器打开中位数 |
|---|---|---|---:|---:|
| SVG | 32.1 / 32.2 / 32.2 ms | 1304–1314 ms | 262 ms | 451 ms |
| React Flow | 32.9 / 32.7 / 32.8 ms | 2185–2204 ms | 304 ms | 544 ms |

显示确认等待两次 requestAnimationFrame，不是纯函数执行时间；首次检查器包含自动化点击和等待开销，不是标准 Web Vitals TTI。11/100节点拖动12轮的帧间隔 P95 为16.7–16.8ms。JS 首屏为 SVG 约297KB、React Flow 再按需加载约180KB；Vite 估算 gzip 约95KB和额外58KB，不代表当前 HTTP 服务已启用压缩。见 [更新 CSV](performance/update-summary.csv)、[更新原记录](performance/update-and-switch.json)、[首屏与拖动](performance/first-interaction-and-drag.json)。

修复后的60次逐帧更新均保留99条有效关系。预热两轮后再做8轮切换，SVG 的 DOM/监听器固定为1311/294，Flow为1821/606，SSE一直为1；强制GC后的堆有小幅波动，不能外推长期无泄漏。见 [生命周期记录](performance/lifecycle.json)。早期未预热的诊断值保留在更新记录中，不能直接拿懒加载后的堆增长判定泄漏。

## 截图与修复边界

| 场景 | 旧版 | SVG | React Flow |
|---|---|---|---|
| 11节点桌面 | [旧版](screenshots/baseline-6ae0cfe-11-1440.png) | [真实](real/svg-11/overview-1440.png) | [真实](real/flow-11/overview-1440.png) |
| 100节点桌面 | [旧版](screenshots/baseline-6ae0cfe-100-1440.png) | [真实](real/svg-100/overview-1440.png) | [真实](real/flow-100/overview-1440.png) |
| 手机100节点 | [旧版](screenshots/baseline-6ae0cfe-100-390.png) | [真实聚焦](real/svg-100/focus-390.png) | [真实聚焦](real/flow-100/focus-390.png) |
| 浅色 / 投影 | — | [浅色](screenshots/verified-100-svg-light.png) | [投影](screenshots/verified-100-flow-projection.png) |

旧版截图使用相同合成帧；表中新版“真实”来自真实验收集群。截图和 API 原记录分别标明来源。

开发过程失败记录保留在 development：手机工具条遮挡、键盘动画帧等待、懒加载就绪等待，以及一次旧 Flow 30秒等待超时。独立探针确认了实际模型99条、画面0条的短暂丢边；已通过显式端点元数据修复，并增加逐帧回归。旧30秒超时未稳定复现，不能声称已完整证明其全部原因，更不能用重跑绿推断所有长期情形。

本阶段停在两版选型处；原六页继续可用，其余五页尚未迁移成 React。没有新增 Windows ZIP、没有推送远端、没有覆盖课程历史结果。
