# Windows 运行修订证据

基线 f5e546c；本轮独立代码 aa140cb。外部 r2 未取得，不混用其测试结论。详见 [修订说明](../../docs/windows-review-20261021.md)。

- `dependency-red.txt`：原版接受 Python 3.10 的失败测试；`dependency-green.txt` / `dependency-race.txt`：修复后定向回归。
- `cancel-old-red.*` 与 `cancel-new-delayed-green.*`：同样的 1.6 秒准备延迟下，原总耗时断言失败，新机制测试通过。延迟仅用于诊断。
- `go-tests.jsonl`、`race-tests.jsonl`、`windows/native-go-tests.jsonl`：各 90 顶层、52 子用例通过，1 个可选长测跳过。
- `native-build.log` / `native-go-tests-first.jsonl`：保留首次系统临时盘空间不足；`native-build-retry.log`：进程局部临时目录调整后通过，同源码。
- `windows/paired-failover/`：6 个真实进程故障实验，AB/BA/AB，同参数、每版三轮；所有结果、源摘要、事件、检查点与独立算术核查均保留。
- `windows/console-check/`：新节点11/2101与标题隔离、旧会话3/256恢复、旧二进制摘要及同一历史前缀。
- `windows/cancel-load/`：空载与4个CPU工作进程负载，各3轮。
- `real-console/`：Linux真实六页截图和操作，不是Windows可见桌面验收。
- `source-and-counts.json`：完整生产源码集合与原生回执一致，config/raft/rpc生产文件与基线相同。
- `provenance.json`：原始/交付摘要；本机路径缩写、JSON进程ID移除。原始WAL和完整实验目录留在隔离测试目录。

新包最终实操由包旁 `.acceptance.json` 绑定精确ZIP；封装前的文档不能代替该回执。可见桌面、真人关窗、Windows race及本版完整规模/长期压力仍按各自范围记录。

最终打包回归：`package-evidence-red.txt` 证明旧打包器漏证据仍能成功；`python-final-fixed.txt` 和 `native-python-fixed.log` 分别为最终全套44项通过（Windows 1项跳过）。测试编辑中间失败保留在 `python-final.txt` / `native-python-final.log`。`packaging-python-source-sha256.json` 绑定最终Python文件。打包时要求本目录及旧目录的provenance所列文件全部进入Git清单并匹配摘要。
