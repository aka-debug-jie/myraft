# 本轮深度审查证据

基线 `05800e7`，候选为未提交的本地修复。完整说明见 [审查报告](../../docs/frontend-deep-audit.md)。本目录是独立新增证据，未覆盖旧课程、Windows 或 Phase 2–4 记录。

- `source-manifest.json`：工具链、候选源码及实际二进制摘要，明确 dirty 状态；用户设计文档只记录未变的摘要。
- `client-before.txt` / `client-after.txt`，`recovery-before/` / `recovery-after/`：三类实际前端缺陷的失败用例与修复回归；before 的 FAIL 为有意保留的旧版复现。
- `collector-before.txt` / `collector-after.txt`：真实 TCP 慢前缀/健康尾节点复现与回归。
- `cleanup-before.txt` / `python-final.txt`：FakeProcess 故障注入、终止顺序及全部 Python 回归。
- `go-test.jsonl` / `go-race.jsonl`：完整机器可读结果；普通运行默认跳过 opt-in soak。
- `layouts/`、`phase1-regression/`、`phase234-regression/`、`lifecycle/`：合成浏览器、几何和生命周期检查。
- `real-clusters/`：真实 11/100 节点四组流程、回执、固定历史检查点、独立算术结果及截图。没有复制原始 WAL、凭据或完整导出 ZIP。
- `performance-final-before/` / `performance-final-after/`：相同修订后脚本、各三轮；`performance-summary.json` 为原始值重算。
- `profile-before-r2/`：V8 CPU profile；`decode-bench.*` 为精确解码微基准。`.mjs` 内 `<WORKSPACE>` 路径需替换为本地源码路径后运行。
- `performance-negative/`：人为禁用 SSE 更新后的预期 FAIL；`performance-negative.log` 表示检查器成功拒绝无更新反例，不是产品失败。
- `memory-500.json`：两渲染器 500 次开关详情的 GC 后资源样本；`memory_probe.py` 中 URL 需替换为本地测试服务。
- `raft-soak-100.txt`：首次额外资源检查因端口占用 FAIL；`port-collision.json` 给出并行实验竞争证据。
- `raft-soak-100-diagnostic.txt`：隔离重跑 20 次恢复、180 秒 PASS；`soak-diagnostic.go` 仅在失败分支额外采集 `/proc/net/tcp`，断言不变。

路径已脱敏为 `<WORKSPACE>` / `<HOME>`。完整原始数据、二进制、WAL 与实验目录仅保存在本机 `.tools/frontend-deep-audit-20261024/`。`SHA256SUMS.txt` 校验此目录全部其他文件，不能将本目录的合成 PASS 当成真实 Raft 或 Windows 验收。
