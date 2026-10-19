# 终端演示与有限性能测量

本轮从 fd7e8d0 的干净工作区开始；保留原 80 轮和收尾 16 轮结果。

- `windows-batches`：Win11 虚拟机、8 逻辑 CPU、Go 1.26.3、Python 3.13.12。11 节点、2101 命令，64/128/256 批次在提交和空节点追赶场景各重复三次，共 18/18 PASS。同一二进制、配对种子 42–44、逐节点 GOMAXPROCS=1，顺序执行。
- `linux-functional`：本轮默认 128 批次、3/11 节点原四场景，共 8/8 PASS。每个场景都有实际单调时钟事件记录。
- `microbenchmarks.json`、`status-*.txt`、`batch-allocations.txt`：Linux Go 1.27.2，三次重复。Status 测量是函数调用；模拟写入线程仅测锁等待。复制分配量在单个 Go 进程内运行三个真实 TCP 节点，计时至 Generate 多数派提交，计入后台副本活动；不是峰值 RSS，也不是 Win11 内存测量。
- `checks.json`：本轮检查与未执行项。
- `source-verification.json`：Win11 导出源码与测量文件逐项核对。后续仅对演示控制脚本增加 UTF-8 读取并复测，未覆盖测量时的摘要。Go 和 benchmark.py 与测量源码一致。

环境文件中的实际输出目录已改为相对标签；源码和二进制摘要保留。Win11 测试目录没有 Git，因此 guest 的 git 字段如实为空；export_context 记录宿主机导出起点及 dirty 状态。原始数据与进程日志仍保留在各平台独立实验目录，未公开含本机路径的系统转录或 session.json。

性能图和事件时间线见 `docs/figures/ux-batches` 与 `docs/figures/ux-functional`。图表只统计成功轮次，标记成功/尝试数；事件来自 events.json，并非从日志猜测的协议瞬时发生时刻。
