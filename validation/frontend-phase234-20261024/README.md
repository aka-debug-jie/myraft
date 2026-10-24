# Phase 2–4 证据索引

日期：2026-10-24。基线 `55f37ea`；生产实现 `6db7b46`、`0fb03aa`。`build.json` 绑定生产文件与实际控制台/节点二进制摘要，`baseline.json` 保存修改前受保护文件摘要。Go、API/client、操作规则、SSE、模型、几何及用户设计文档均未改。

## 可核查结果

| 内容 | 证据 |
|---|---|
| 汇总（不是替代原始结果的自述） | `checks.json` |
| 修改前 26 单测、30 布局及交互 | `baseline/` |
| Phase 2 截图、28 单测、布局和逐帧 | `phase2/` |
| 最终布局、标签包络、Phase 1 与新增交互 | `final/` |
| 普通动效及减少动态、60 更新与60状态变化 | `lifecycle/normal.json`、`lifecycle/reduced.json` |
| 40 次指针面板循环及资源样本 | `final/interactions.json` |
| 200 次页内开关、原始堆数据与限制 | `lifecycle/memory-probe.json`、`lifecycle/assessment.json`、`lifecycle/memory_probe.py` |
| Go 普通/race、Python、前端、构建原始输出 | `regression/` |
| 真实 11/100 × SVG/Flow；独立算术、故障、恢复、前缀、导出 | `real-clusters/results.json` 与各子目录回执/截图 |
| 真实 KPI 与暗色/浅色/投影/手机；合成异常分别标记 | `visual/results.json`、`visual/` |
| 中等宽度检查器与原版入口、compare | `preview-visual/` |
| 同场景前后图 | `comparison/before-11.png`、`after-11.png`、`before-100.png`、`after-100.png` |
| 三轮性能原始数据及 CSV | `performance/`、`performance-comparison.json` |
| 预览原实例保留、实际新资源、只读权限 | `preview-check.json` |

布局矩阵：3/11/20/50/100 节点 × SVG/Flow × 1440×900、1920×1080、390×844。中等宽度补查800/1024，包含检查器打开状态。合成数据仅由测试拦截提供，生产页面没有 demo 回退。

真实四组流程全部通过；每组先执行 2101 条算术命令，故障重选后再执行3条，最终2104条，noop不计入命令数。每组历史检查点保持 index=2102，并逐节点比对相同前缀hash/x。222个节点通过独立算术参考。1/5/10浏览器均不增加共享采集轮次中的节点RPC总量。本轮实验进程已清理；原始WAL/日志保留在工作区 `.tools/frontend-phase234-20261024/real-clusters/`。

## 失败与边界

- `failures/baseline-contract.json`：新合同在旧版6组检查中5组不满足，包含本轮明确改变的手机选择流程，不把它们全部称为旧版协议缺陷。
- `failures/early-focus-assertion.json`：补充测试曾在Radix完成关闭焦点恢复前立即取值，2项失败；同一生产二进制改为等待准确的原节点焦点后通过，没有添加任意睡眠或放宽焦点目标。
- 浅色初次截图捕获了颜色过渡中间帧，原始图片留在本地 `visual/` 原始目录；本目录 `visual/` 使用明确结束有限动画的截图。正常动效另做逐帧验收。
- 性能脚本最初的测试路由回调参数绑定错误已修正；最终前后比较使用同一份修正脚本。独立审查摘要见 `reviewer-probes.json`，它不替代本目录可复现测试与真实记录；源码摘要差异来自后续格式化，内嵌页面摘要一致。
- 单 Leader 几何矩阵与异常状态语义分开检查；没有为任意多 Leader 图开发新路由算法。
- 堆样本并非恒定；首次使用和有限循环存在增长，DOM/监听器没有逐次累积。没有做长期堆保持路径认证。
- Windows原生、真实手机、Safari/Firefox和长期压力均为 NOT RUN；没有沿用旧成绩补齐本轮。

文本副本中的本机绝对路径统一替换为 `<WORKSPACE>` / `<HOME>`；原始数据未改，保留在 `.tools/frontend-phase234-20261024/`。未将会话CSRF凭据、原始WAL或导出ZIP复制进本目录。`SHA256SUMS.txt` 校验这里的交付证据副本，不替代原始ZIP摘要。
