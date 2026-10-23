# Windows 运行修订与独立复验

本版从 `f5e546c75916c4e118b0c1d49ab256a3ac559546` 独立实现，Go 程序提交为 `aa140cb65017bcd218b1ec26caf862d555c88961`，打包检查为 `8833e5c`（测试编辑修正 `a508cfa`）。没有取得外部 r2 的 ZIP、补丁或原始 traceback，因此不声称合并或独立验收了外部 r2。原正式 ZIP、课程报告与历史数据保持不变。

## 修改与最小复现

|问题|复现及处理|对应文件|
|---|---|---|
|Web 子节点覆盖宿主标题|原版 Windows 控制台 API 探针观察到 HOST 标题变为 MyRaft Node 1。新控制器仅给自有子进程设置 `MYRAFT_NO_CONSOLE_TITLE=1`，新节点据此跳过改标题；普通终端默认行为保留。|`main.go`、`cmd/dashboard/processes.go`|
|版本存在性被当作环境合格|最小测试证明旧版把 Python 3.10.11 判为 ready。现读源码 go.mod 的 Go 下限、检查 Python ≥3.12；分别报告 missing/unsupported/error/ready，未探测项为 not_checked。|`cmd/dashboard/dependencies.go` 及测试|
|慢版本命令可能占住控制器锁|版本探测移出 d.mu，独立锁共享一分钟缓存；并发浏览器共享一次检查。实验启动前强制刷新。测试覆盖过期并发、实际 deadline、快照锁可用及缓存过时后拒绝启动。|`http.go`、`server.go`、`experiments.go`|
|取消测试计时混入准备阶段|诊断仅给 go version 前增加 1.6 秒准备延迟，原测试因总耗时 1.894 秒而失败；相同延迟下新测试通过。改为保存 runner 自己的退出状态，再做测试兜底清理，验证中断、进程回收、sentinel 存活及未产生成功二进制。|`scripts/test_cancel.py`|

未更改 config/raft/rpc 生产文件；逐文件摘要对照见 `source-and-counts.json`。WAL v2、必要 Sync、固定成员、多数派提交和未知写入不重试保持原实现。`catchup_verified=false` 继续表示恢复回执尚未完成一致性校验，随后通过当前/历史验证确认。

### 兼容与计时边界

没有给托管节点新增必传 CLI 参数：旧会话执行其原先保存的节点程序，额外参数会使原版退出。原生实测已用新控制器恢复旧控制器创建的三节点会话，原二进制摘要不变，256 条命令及原 index=257 的 hash/x 保持。

旧会话保留旧节点版本；旧程序不识别环境开关，仍可能改标题。本版新建会话使用新节点，可避免该问题。不要仅凭窗口标题认定进程身份，不同会话也可能有相同节点 ID。

一次实际版本探测共享 3 秒 context，管道收尾 WaitDelay 为 100ms；这不是 HTTP 总耗时承诺，等待另一次探测的锁不计入该 context。快照、SSE 和协议监控不使用探测锁。GOTOOLCHAIN=local 仅作用于探测子进程，避免页面检查自动下载工具链。运行实验前刷新版本，ready 只说明版本条件满足，不证明构建、磁盘容量或实验已成功。探测准备阶段尚未创建取消文件，页面取消将在 runner 阶段可用；关闭控制器可取消进行中的探测。

取消耗时从“发出标记写入请求”到捕获中断计算，包含写标记的文件操作；没有用它宣称总流程小于 1.5 秒。测试先捕获 runner 回收状态，再做兜底清理，避免测试自己清理后误报 runner 成功。模拟构建仍为原来的 2 秒，没有靠延长模拟任务让测试通过。

## 证据入包检查

复核发现 `.gitignore` 的日志规则会使部分已整理证据不进入 Git 清单，而打包器使用该清单。本轮新清单中207份文件及旧性能清单中17份日志曾命中忽略规则；按已校验的清单精确加入，不笼统加入原始实验目录。旧17份日志字节不变，原ZIP不重写。

打包器现在拒绝证据文件缺失或交付摘要不符。回归先证明旧实现可生成缺日志的包，随后覆盖缺失、内容变化、完整入包和禁止覆盖旧ZIP。新增测试编辑时曾错误复制一个代码块，导致覆盖断言没有调用函数；原失败保留在 `python-final.txt` / `native-python-final.log`，修正测试后两平台全套通过，未改动节点程序或放宽断言。

## 本轮实际验证

所有证据在 [windows-review-20261021](../validation/windows-review-20261021/README.md)。

|检查|结果|证据|
|---|---|---|
|Linux fmt / vet / build|PASS|`fmt.txt`、`vet.txt`，真实浏览器使用本轮构建|
|Linux Go 与 race|PASS|各 90 个顶层、52 个子用例；1 个可选长测跳过|
|Linux Python|PASS|最终44项，`python-final-fixed.txt`|
|Linux 3/11 节点 smoke|PASS|故障、恢复、少数派检查，`linux-smoke/`|
|六页真实浏览器流程|PASS|11 节点 2101 条、双击抑制、重选/恢复、历史校验、实验/取消/导出；`real-console/`|
|共享采集|PASS（列明范围）|1/5/10 浏览器各观察五轮，monitor RPC 均为 55；不是慢浏览器压力认证|
|Windows 原生 Go|PASS|90 顶层、52 子用例、1 长测跳过；`windows/native-go-tests.jsonl`|
|Windows Python|PASS|最终44项中43通过、1个Linux专用项跳过；`native-python-fixed.log`，Python源码摘要与交付一致|
|Windows 取消测试|PASS|空载与四个 CPU 工作进程负载下各三轮；`windows/cancel-load/`|
|Windows 3/11 节点 smoke|PASS|`native-additional.log`、`windows/smoke/`|
|新节点默认标题 / 托管标题隔离|PASS（API）|默认仍设置 MyRaft Node 1；新控制器管理 11 节点及恢复后 HOST 标题不变；不等同可见桌面|
|旧会话兼容与历史前缀|PASS|`windows/console-check/`，旧二进制保留，历史不匹配为 0|
|11 节点配对故障恢复|PASS|六轮，旧/新各三轮，2101 初始命令；`windows/paired-failover/`|
|新绿色包启动/恢复/导出|PASS（候选归档）|候选 SHA `3df5b67a…1b3609`，3687 项摘要一致；无 Go/Python PATH 下两个入口、11/2101、故障/恢复/历史/导出通过，进程清理为0；`portable-candidate/`。最终 ZIP 由包旁 `.acceptance.json` 绑定|
|可见桌面 / 真人关窗|NOT RUN|当前 VM 没有已登录桌面；SYSTEM 控制台 API 和自动启动不替代此项|
|Windows race|NOT RUN|未配置 C 工具链|
|本版四规模矩阵 / 长时压力|NOT RUN|本轮只做针对性回归；旧版本矩阵与长测不冒充本版结果|

本轮不声称原课程 a～g 在新目标电脑全部通过，也没有把测试清单数量当成 a～g 的数量。

## 故障恢复对照

Win11 虚拟机同一 Go 1.26.3 / Python 3.13.12，固定 11 成员，初始 2101 条命令，batch=128，节点 GOMAXPROCS=1；election min/jitter 各 3 秒，heartbeat=150ms，RPC timeout=1 秒。按 AB/BA/AB 交替，配对 seed 为 42/43/46，这三组均只停止 Leader。每次新目录，保留所有结果及历史检查点，停止后独立重放 WAL 核对算术。

默认 `--rounds 3 --seed 42` 并非三次同样的故障：seed 44 会额外停止三个 Follower。本轮没有混用这组条件。

|版本|指标|样本数|均值|中位数|最小|最大|
|---|---|---:|---:|---:|---:|---:|
|原版 f5e546c|当选者内部 election_ms（ms）|3|147.133|144.976|142.250|154.172|
|原版 f5e546c|故障开始→外部确认 Leader（s）|3|4.044|3.911|3.634|4.588|
|原版 f5e546c|故障开始→新写入确认（s）|3|4.222|4.071|3.849|4.745|
|修订 aa140cb|当选者内部 election_ms（ms）|3|138.693|136.412|130.675|148.991|
|修订 aa140cb|故障开始→外部确认 Leader（s）|3|3.887|3.974|3.686|4.003|
|修订 aa140cb|故障开始→新写入确认（s）|3|4.039|4.143|3.828|4.148|

内部 election_ms 从当选者最后一次候选阶段开始计时，不包含故障检测等待或前面失败的选举轮次。外部确认要求两次一致的活节点状态查询，包含进程终止、CLI 启动和轮询；新写入在发现 Leader 后才发起，因此该计时不是最早可服务时刻。

本机这六次未出现约 12 秒恢复；但外部 r2 的 12.812/12.922 秒来自另一宿主机与原生关窗路径，未取得原始记录，原因仍不能确认。本轮使用后台进程终止，不能替代关窗。三轮只是诊断，不支持稳定加速、可靠 p95/p99 或所有负载无退化的结论；两版均值和中位数的方向也并非完全相同。

复现每个版本时采用独立源码目录，按上述顺序分别执行（把 SEED 替换为配对值，输出目录不可复用）：

```powershell
python scripts/benchmark.py --nodes 11 --batch-sizes 128 --entries 2101 --rounds 1 --seed SEED --scenarios failover --timeout 60 --output 独立输出目录
```

## 环境失败与证据纠正

首次 Windows Go 回归在链接阶段报 `There is not enough space on the disk`。容量检查显示 C 盘只剩约 15 MB，P 盘仍有约 55 GiB。SYSTEM 下 Go 使用 GetTempPath2；仅设置 TEMP/TMP 没有改变 C 盘系统临时目录。[微软接口说明](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-gettemppath2w)指出，此时应通过进程环境 SystemTemp 指定受限目录。

本轮只创建 P 盘独立临时目录，限制为 SYSTEM/Administrators 访问，并为本次子进程设置 SystemTemp/GOTMPDIR/TEMP/TMP。实际 API 返回路径已核验；没有改机器级环境、扩容、删除数据或改变程序代码。随后同一源码通过原生回归。首次失败原样保留，不能当作一次被隐藏的协议失败。

本地实物确认：旧课程包为 17,103,012 字节、SHA `596bddfb…`；原沉浸式包为 23,967,060 字节、SHA `1a04080e…`。这支持外部报告把旧包字节数抄入新包行的解释，但外部三份副本、189 个文件及三个 Python errors 的逐项归因没有在本机独立复核。本轮拒绝低版本的测试使用可控版本工具替身；实际 Python 回归环境为 Linux 3.12.7、Windows 3.13.12。

## 保留的限制

没有新增快照压缩、动态成员、请求去重或线性一致读。原有日志增长、旧 Leader 留存 peer worker、永久阻塞普通输出 sink 的边界没有在本轮重构。协议生产文件未改，但本轮有限回归不能证明所有故障下无缺陷。原包与外部 r2 结果不自动升级本版的 NOT RUN 项。

最终 ZIP 与候选使用相同节点/控制台字节；差异为补充本轮候选验收文档和证据。最终归档将在另一新目录复验，实际结果记录在包旁同名 `.acceptance.json`，不将自身 ZIP 摘要写回该 ZIP。缺少回执时，不把候选验证冒充最终精确归档验证。
