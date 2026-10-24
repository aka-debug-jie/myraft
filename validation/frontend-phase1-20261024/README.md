# Phase 1 验收与比较

本轮基线 `c9bf336`，生产实现 `3fe7188`。这是 **Hero/KPI 与交互修复阶段**，不代表 Phase 2 节点视觉或整套课程重新验收完成。源文件和实际二进制摘要见 [build.json](build.json)。用户原有设计文档保持未提交状态、内容未改。

## 实际结果

| 项目 | 结果 | 证据 |
|---|---|---|
| 最小缺陷复现 | 原版6类检查全部失败，证明问题存在 | [基线](baseline-bugs.json) |
| 修复及KPI浏览器检查 | 12 PASS | [结果](ui-phase1.json) |
| 类型 / 构建 / 单元测试 | PASS，26项单测 | [输出](checks/unit-final.txt)、[构建](checks/build-final.txt) |
| 现有布局及交互 | 30组合 + 7组 PASS | [结果](ui-regression.json) |
| 逐帧及切换生命周期 | 两版各60次更新无丢边；SSE始终1，预热后DOM和监听器数量不增长 | [结果](lifecycle.json) |
| 真实11节点操作 | SVG/Flow各1次；2101命令、校验、检查点、故障重选、再提交3条、原盘恢复、历史校验及导出通过；22节点独立算术检查通过 | [结果](real-eleven/results.json) |
| 真实KPI对照 | SVG/Flow × 11/100节点，4次逐字段对照通过 | [结果](visual/results.json) |
| 异常视觉状态 | 加载、空、断线、过期、多Leader、身份异常，6个合成场景通过 | 同上 |
| 预览权限与进程保护 | 原11/100节点实例不变；写方法仍403 | [结果](preview-check.json) |
| Windows原生、Safari/Firefox、长时运行 | NOT RUN，不沿用旧PASS | 本轮边界 |

Go、协议、API/client、几何与两个实际渲染器文件未修改。本轮没有新增100节点故障/吞吐实验，100节点的结论限于真实展示和KPI来源核对。

## 性能口径

同机、同视口、同合成帧序列，每种渲染器三轮。显示确认耗时包含两次 requestAnimationFrame，并不是纯CPU耗时；拖动记录帧间隔。本轮门槛是三轮中至少两轮P95高于基线20%时必须定位，实际没有触发。

| 100节点更新 P95 | 基线三轮 ms | Phase 1 三轮 ms |
|---|---|---|
| SVG | 32.2 / 32.3 / 32.9 | 32.2 / 32.3 / 32.2 |
| Flow | 32.6 / 32.9 / 32.6 | 35.6 / 32.5 / 33.6 |

拖动各组合也通过配对门槛；100节点Flow基线和本轮均约33ms，没有把它写成16ms。原记录、长任务、堆、CPU和CSV在 [performance](performance/summary.csv)，比较判定见 [performance-comparison.json](performance-comparison.json)。小样本不构成稳定加速或可靠P99结论。

## 截图

- [真实11节点桌面](visual/real-svg-11-1440-dark.png) · [真实100节点桌面](visual/real-svg-100-1440-dark.png)
- [1920宽度](visual/real-svg-100-1920-dark.png) · [手机390宽度](visual/real-svg-11-390-dark.png)
- [浅色](visual/real-svg-11-light.png) · [投影](visual/real-svg-11-projection.png) · [检查器](visual/real-svg-11-inspector.png)
- [加载](visual/synthetic-loading.png) · [空会话](visual/synthetic-empty.png) · [断线](visual/synthetic-disconnected.png) · [过期](visual/synthetic-stale.png) · [多Leader](visual/synthetic-multiple-leaders.png) · [身份异常](visual/synthetic-identity.png)

`real-*` 为真实只读集群；`synthetic-*` 为测试拦截数据，不是生产演示模式。原始证据在 `.tools/frontend-phase1-20261024/` 保留；公开副本只对主机路径和末尾空行作明确处理。

开发过程的测试脚本错误与加载截图清理警告也保留，未冒充产品缺陷；最终视觉脚本使用等待式路由清理，最终结果及页面错误数见 visual/results.json。没有通过延长任意睡眠或放松协议断言获得PASS。
