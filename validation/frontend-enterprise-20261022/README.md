# 中心拓扑与课堂操作：本轮证据

基线3ed2d827；前端工作区修订。生产静态文件与部署二进制绑定见 `build.json`，结果汇总见 `summary.json`，文件摘要见 `SHA256SUMS.json`。

- `go-tests.jsonl` / `race-tests.jsonl`、`python.txt`、`smoke.txt`：实际回归输出。
- `ui-release.txt`：25个浏览器用例，24通过、1个live-only跳过。
- `topology-release/` / `stage-release/`：合成几何、状态确认与画布测试；不代表共识验证。
- `real-11/`：真实六页流程、故障恢复、历史检查点和共享采集。
- `real-100-release/`：100节点2101条命令、独立WAL算术参考、真实桌面/手机截图。
- `real-guided/`：真实课堂操作条提交、重选、恢复及固定历史验证。
- `preview-real.png` / `preview-check.json`：部署后的只读Tailscale入口。

原始运行材料和初次失败输出保留在交付工作区 `.tools/frontend-enterprise-20261022/`。这里的文本已把工作区绝对前缀替换为 `<workspace>`，不改测量数字；截图保持原样。

本轮未跑新版本Windows原生/可见桌面、Windows race、老师电脑、完整规模矩阵和长时压力。历史证据未回写；没有自动推送或发布。
