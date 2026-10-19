# Console 与运行保护：独立验收记录

本轮从干净的 `8d856970726a72a723c19d8cc077ff938ccf54c6` 开始。本目录只含本轮新记录，不改写 81723b8 的 80 轮或 closure/ux/safety 记录。实际测量源码、交付源码分别记录；没有用新摘要覆盖旧数据。

## 来源与完成情况

- Linux：Go 1.27.2、Python 3.12.7。`release-checks` 保存 fmt/vet/test/build/race/Python 的实际输出；27 项 Python 回归通过。
- Win11 虚拟机：Go 1.26.3、Python 3.13.12。`windows-native.txt` 为原生构建、Go/Python、3/11 smoke、启动和菜单恢复的实际输出。Python 27 项中 1 项 Linux /proc 进程组检查跳过，其余通过。未配置 Windows race 的 C 工具链。
- 原生 Windows HTTP 控制台另完成 11 节点创建、2101 条命令、停机恢复、历史前缀校验、ZIP 下载/摘要验证。`windows-console.json` 保留真实回执；校验时 passed，之后停机使共享观测标记 stale，二者不混淆。
- Linux Chromium 真浏览器：11 节点、2101 条命令后故障重选/旧节点恢复/历史检查点、双击与停机确认、独立实验、取消及导出；另有真实 100 节点网格。`browser` 保存原始记录，截图在 `docs/console-screenshots`。
- 可选 UI 状态测试 5 项通过；synthetic 夹具覆盖 loading/empty/断线/过期/100-node renderer，仅验证 UI，不计入协议通过数。
- 慢 SSE writer 测试检查采集不阻塞、队列有界、丢弃可见与写期限；它使用可控 writer。并非对所有浏览器/网络条件的压力认证。

## 版本绑定

- `benchmark/environment.json` 记录测量 HEAD `3125864`、dirty 状态、源码/二进制摘要及参数；本轮 16 个场景共用一次独立构建。
- `delivery-source-sha256.json` 是交付代码摘要；`measurement-to-delivery-diff.json` 明示测量后仅浏览器验收脚本增加 Windows 平台拒绝提示，协议、持久化、实验 runner 与控制台生产代码未变。新增慢 SSE 测试另在 Linux 全套检查中执行。
- `windows-source.json` 是传入虚拟机的源包逐文件摘要与归档摘要。归档创建于 `3125864` 提交前几秒，内容与该提交对应生产源码一致；其记录的旧 HEAD 不被篡改。
- 原始节点数据、程序、CSRF、账户凭据、私有压缩包不纳入此目录；路径以占位符脱敏。完整本地运行目录仍保留。

## 规模回归（每组合一轮）

固定配置，2101 条命令，batch=128、seed=42；Linux 单机多进程。时间口径见 README 与 environment.json，成功/失败/中断按逐轮记录计数。

|节点数|选举观测 s|故障至新写入提交 s|空节点追赶 s|新 Leader 后分歧收敛观测上界 s|结果|
|---:|---:|---:|---:|---:|---|
|10|3.352|3.452|0.386|0.427|4/4 PASS|
|20|3.382|3.359|0.258|0.451|4/4 PASS|
|50|3.352|3.331|0.287|0.417|4/4 PASS|
|100|3.363|3.296|0.450|0.414|4/4 PASS|

共 16/16 PASS，0 失败、0 中断。这一轮验证规模和功能，不是稳态吞吐或尾延迟统计。失败注入/主动取消另有单独记录，不能删去后混作全部实验均无中断。

## 比较与问题复现

- 普通输出阻塞探针、误配置分叉探针和慢 Follower 探针已在 Go 1.27.2 的隔离 8d85697 源码重现；原探针 PASS 表示发现问题。本轮对应修复测试已转为安全断言。
- worker 比较的 before 文本故意 FAIL：100 节点选举前额外 10,200 goroutine；after 三次均 300。只报告计数变化；启动时间样本少且受缓存/运行顺序影响，不声称稳定启动提速。
- Win11 首次 Go 测试失败记录单独保留为 `windows-initial-failure.txt`。墙钟粒度导致旧验证显示通过；用序号修复后确定性回归和 Win11 全套重测通过。
- `verification-clock-before.txt` 是修复前的预期失败，after 为修复后 10 次 race 重复通过；不能把这些复现日志当作未修复的发布失败。
- 1/5/10 实际浏览器的五轮采集各 55 次节点观测 RPC；全部节点 RPC 395/385/395 包括心跳相位差。0/10 浏览器的 256 命令提交各 6 次，外部观测中位数 0.228/0.239 秒；含 100ms 任务轮询，两组采集器均开启，不报告 p99 或稳定收益百分比。

尚未执行：另一台统一 Win11 主机、多机/WAN、原生 Windows 浏览器矩阵、Windows race、控制器崩溃后全部后代必回收。限制详见 docs/console.md。
