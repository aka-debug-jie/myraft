# 性能与沉浸式控制台

性能矩阵测量版本为 `88bd633`，最终代码为 `ef130d9`；后者仅撤除实验进度读取中的重复复制，并修复打包时二进制读取两次的问题。Raft、静态页面及只读采集路径与测量版相同。基线为 `2de62ea2c8d4fc48d0c47035317a7fe34bc6b242`。原课程报告、验收目录及原正式 ZIP 保持不变。新证据位于 [perf-next-20261020](../validation/perf-next-20261020/README.md)，新版本验收单独记录在 [acceptance-next.md](acceptance-next.md)。

## 实际修改

核心只保留两项局部优化。完整 Status 在同一次节点锁内捕获字段、revision 和必要日志副本，再在锁外计算完整或历史摘要；复制日志修复可以复用原数组，因此不能只保存旧 slice。Summary 和全部提交后的当前状态仍走零日志拷贝路径。已提交哈希改为把日志元素指针交给同一个标准库 JSON Encoder，减少值装箱；字段顺序、整数编码、逐条换行、SHA-256 和 WAL v2 均不变。空日志、极值、分批哈希、并发后缀覆盖和恢复均有回归。

没有移动 WAL/提交元数据的 Sync，没有提前应答，也没有改变多数派、当前任期提交、固定身份或不确定写入不重试规则。批次默认仍为 128。未增加 ConflictTerm、group commit 或新的 worker 生命周期机制；本轮证据不支持为它们增加协议复杂度。

审查中曾怀疑实验进度读取会修改 SSE 已发布对象；探针只证明输入 map 会被修改。复核确认原发布路径已有 JSON 深拷贝，因此撤除了新增的重复复制和不必要测试，保留原发布隔离。开发探针记录保留，但不作为生产竞态或数据丢失证据。另将 EXE 校验与打包改为复用同一次读取的字节，并用受控替换测试验证精确绑定；未发现旧包实际发生替换。

## 界面与使用

首页是固定成员拓扑舞台，节点按 ID 固定位置；换届只更新角色和逻辑边。3–15 节点采用环形，更多节点采用适应视口的网格，支持平移、缩放、适配与聚焦。边依据同任期节点报告的领导关系绘制，不表示实测链路或心跳。动效只来自去重后的节点事件；事件缺口可见，后台恢复不补播积压动画。

鼠标移到左侧边缘展开导航；也可点击菜单按钮或用 Tab 进入。Ctrl+K 查找节点，Escape 关闭详情或导航。导航可以临时固定，始终覆盖画布。点击节点查看三个索引、Term、x、采样年龄和受控操作。日志矩阵、故障时间线、实验曲线、当前验证、历史检查点和会话管理保留真实后端调用。

控制台仍默认只读。`GET /api/session` 增加 `experiment_dependencies`，报告源码、Go 和 Python 是否可定位；这不是版本兼容或构建成功认证。运行实验前再次检查，缺失时返回 `environment_unavailable`，不创建实验子进程。普通演示不依赖 Go/Python；规模实验仍需要它们，页面和快速说明给出配置方式。

## 测量口径

Linux 使用 Go 1.27.2、Python 3.12.7；Windows 11 虚拟机使用 Go 1.26.3、Python 3.13.12、8 vCPU/8 GiB。虚拟机沿用原有页面文件配置，本阶段没有调整。两个平台分别比较，不能跨平台计算加速倍数。

真实多进程延迟每组预热 20 次，再发起 200 次独立请求，每次 64 条命令，重复三轮。测量包含 TCP 建连和 Generate 到提交回复，不含发现 Leader、CLI 启动及全体验证。请求不自动重试；逐请求 JSONL 保留中断前数据。P50/P95 只针对成功请求，失败、中断及未执行另记；比较表使用每轮分位数的中位数与范围，不声称可靠 p99。

0 浏览器组仍运行共享采集器，另有采集器关闭组。1/5/10 个浏览器各自接收 SSE，但不各自采集节点。资源文件记录本轮节点与控制器的 CPU、RSS/Windows working set，以及可取得的线程/句柄信息；不包含浏览器和临时 probe，窗口包含预热。进程 RSS 相加可能重复计算共享页。

CPU、mutex、block、heap profile 与延迟运行分开。微基准 profile 可能包含准备和收尾；CPU profile 不能单独证明磁盘等待。原 `sync-only` 基准包含整个元数据保存流程，不是单独的 fsync。

## 已测到的局部收益与边界

同机三次纯编码对照中，21010 条日志的旧值编码为 12.68–12.91 ms、约 2.02 MB、42022 次分配；元素指针编码为 8.16–8.34 ms、131 B、1 次分配。这是编码路径的测量，不是整个系统的加速倍数。

在 GOMAXPROCS=2 的完整 Status 竞争微基准中，旧版一次查询约 25.6–31.5 ms，新版约 8.45–9.40 ms，日志相关分配约从 2.02 MB 降至 0.84 MB。其 writer 仅尝试获取锁，锁等待指标不能当作真实写入 P95。Summary 仍为零分配。

本机目标数据盘上，128 条记录的 WAL JSON 编码约 38.5–39.1 μs，原始帧 Write+Sync 约 423–445 μs，其中 Sync 约 414–433 μs；完整元数据保存约 514–530 μs。Win11 对应保存成本明显不同，原始记录单列。磁盘同步仍是限制之一。

真实请求的 P95 有升有降，不能声称所有规模均稳定加速。对开发测量中超过 5% 的退化组合，额外进行交替版本顺序复测，保留全部结果。采用这两项修改的依据是可重复的局部分配、计算与锁占用改善，而不是筛选最快轮次。

基线与候选均完成 11 节点 30 次停止恢复，以及 100 节点在 30 分钟运行内完成 20 次停止恢复观察。后半段固定日志量观察未见持续增长；所有节点 Stop 后 goroutine 回到测试前数量。另有三个节点都保持存活、经真实 TCP 投票换届 30 次的 worker 回归。长测是单 Go 进程内的真实 TCP，不能替代多进程 RSS，也不等同于整机断电验证。

## 复现

先使用同一工具链分别保存两个版本的源码目录，保持生产文件不变。每次指定新的输出目录：

```powershell
python scripts/performance.py --source C:\Raft\baseline --output C:\Raft\runs\before --nodes 11 50 100 --browsers 0 1 5 10 --rounds 3
python scripts/performance.py --source C:\Raft\candidate --output C:\Raft\runs\after --nodes 11 50 100 --browsers 0 1 5 10 --rounds 3
python scripts/compare_performance.py --baseline C:\Raft\runs\before --candidate C:\Raft\runs\after --output C:\Raft\runs\comparison
```

浏览器测量额外需要测试工具 Playwright 与 Chromium；它不是节点或控制台的运行依赖。没有该工具时用 `--browsers 0`，不可把它标成浏览器验收通过。`--no-collector --browsers 0` 单独测采集器关闭组。CPU/内存采样支持 Linux 与 Windows，其他平台未取得的字段明确缺失。

```powershell
go test ./raft -run '^$' -bench 'Benchmark(EntryHashEncoding|PersistenceStages|StatusRead)$' -benchmem -count=3
python scripts/benchmark.py --nodes 11 --batch-sizes 64 128 256 512 --entries 2101 --rounds 3 --scenarios replication catchup divergence --output .test-output/new-batches
$env:RAFT_SOAK_NODES='100'
$env:RAFT_SOAK_ROTATIONS='20'
$env:RAFT_SOAK_DURATION='30m'
go test ./raft -run '^TestResourceSoak$' -v -count=1 -timeout 40m
```

## 保留的限制

WAL 与内存日志没有快照压缩；当过 Leader 的存活节点保留 peer worker，长期轮换理论上仍可达到 N×(N−1)。永久阻塞的展示 Writer 可留下一个消费者，Stop 本身有界。完整验证仍需复制和扫描所需日志，不能作为高频业务读取接口。

本轮主机没有完全隔离其他活动，虚拟机与 Linux 共用物理存储；小幅延迟差异尤其需要谨慎解释。没有提供请求去重、业务线性一致读、动态成员或不可信网络认证。Windows race、登录桌面的可见终端/真人关窗、老师统一电脑与无开发工具环境的规模实验未自动转成 PASS。
