# 交互修复证据 · 2026-10-23

基线284c085；本目录为新一轮结果，不覆盖旧验收。

- `delivery-matrix/results.json`、`real/n*/`：真实五规模、三视口、2101+3条命令、重选、恢复、固定前缀、独立算术参考和截图。
- `delivery-classroom/results.json`、`classroom/`：真实11节点六页操作、实验取消/导出/共享采集及截图。
- `delivery/groups/`：合成35组合的逐组节点、字体、路径检查与最终结果。代码明确检查同目标中心端口之间净距，非仅节点距离。
- `delivery/interactions/`、`interaction-screens/`：12项组合状态回归及截图。
- `baseline-claims.json`、`before/`、`first-browser.txt`、`legacy-first.txt`、`group-first/`：复现和中间失败，不能当成最终PASS。
- `go-*.jsonl`、`python.txt`、`smoke.txt`、`smoke-results/`：实际Go、race、Python、smoke输出。
- `topology.txt`、`stage-v2.txt`、`render/render.json`：合成几何、交互、渲染耗时，不是协议性能数据。
- `build.json`：实际二进制与生产源码摘要；`provenance.json`：复制前后摘要及路径脱敏说明；`SHA256SUMS`：交付文件校验清单。

仅替换文本中的用户目录/工作区前缀；截图未编辑，原始文件留在本机 `.tools/frontend-interactions-20261023`。Windows及人工操作本轮NOT RUN。详细范围与限制见 [修复说明](../../docs/frontend-interactions.md)。
