# 空采样时间补丁证据（2026-10-24）

- `sample-before`：保留原版失败。6 个真实空控制器场景显示约 639 亿秒；另 3 个合成检查因原版等待文案不同而失败，不代表另外发现 3 个协议缺陷。
- `sample-after`：同一服务端零时间，SVG / Flow / compare × 桌面 / 手机，共 6 项真实空控制器通过（等待实际 SSE）；另外 3 项非法/过期时间合成回放通过。
- `phase1` 12 项、`recovery` 6 项合成 UI 回归通过。`layouts` 包含 30 个布局组合与 7 项交互检查，本轮跳过性能测量。
- `readonly-scope-test.txt` 是新增 HTTP 矩阵的首次通过输出；最终完整 Go / race 回归亦包含该测试，空会话额外覆盖 AllowControl=true 但未显式启用。
- 前端 36 项单元测试、Go 普通及 race 各 156 项通过（含子测试）/ 1 项可选长时测试跳过；Python 46 项通过。
- 原始失败记录保留，文本只将工作区绝对路径替换为 `<workspace>`；摘要在 `provenance.json`。
- Windows 原生验证以新 Release 随包 acceptance JSON 为准，不沿用原包的实机成绩。未运行长期压力与性能矩阵。
