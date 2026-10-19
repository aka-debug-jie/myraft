# MyRaft：固定成员 Raft 日志复制状态机

在原有 Go 选举项目上扩展，保留 `config / raft / rpc` 结构、JSON 配置、TCP `net/rpc`、选举重试、终端/文件双输出。新增持久化日志复制、当前任期多数派提交、算术状态机、冲突修复、节点恢复和规模实验。只依赖 Go/Python 标准库。

默认配置只监听 `127.0.0.1`。RPC 没有认证、TLS 或不可信客户端防护；仅在本机或受信任的隔离网络运行，不要将端口映射或开放至公网。详见 [安全说明](SECURITY.md)。

[课程报告](docs/report.md) · [RPC 调用图](docs/rpc-flow.svg) · [实验记录与版本边界](validation/README.md) · [收尾修复说明](docs/closure.md) · [终端演示与性能测量](docs/ux.md) · [存储与测试结果修复](docs/storage-safety.md)

## 环境与构建

共享配置现在必须含明确的 `cluster_id`。`-generate-config` 为新实验生成一次随机 ID，所有节点使用同一文件；网络代理/地址变化不改变成员身份。没有配置文件启动时，所有节点必须传相同的 `-cluster-id`。不同实验请生成新配置，不能复用同一集群身份。

旧版本数据缺少身份时会拒绝恢复，不会自动认领或擦盘。先停掉全部旧节点，保存原 `nodes.json`，仅为该原配置增加一个共同的 `cluster_id`（如 `classroom-2026`，保持原成员 ID 不变）。然后对每个有旧数据的节点显式认领：

```powershell
.\raft-node.exe -config demo-runs/classroom/nodes.json -data-dir demo-runs/classroom/data -id 1 -claim-legacy
```

将 `-id` 换为各原节点 ID。命令只读审计旧 WAL、核对已提交摘要，将原始元数据/WAL 和审计清单同步备份至数据目录的 `node-ID-claim-*`，然后绑定身份；认领本身不修剪 WAL。正常启动再恢复。该操作是使用者对“这是原配置”的明确声明；没有历史身份的数据无法自动证明原成员集合。错误身份、损坏数据或备份失败都会拒绝认领，不覆盖已绑定身份。

本轮 Linux 验证使用 Go 1.27.2、Python 3.12.7；Win11 兼容性验收使用既有 Go 1.26.3、Python 3.13.12。优先选择官方当前受支持的工具链与补丁；未降低 go.mod 的语言版本要求。先从 [Go 官网](https://go.dev/dl/) 和 [Python 官网](https://www.python.org/downloads/) 安装工具并加入当前终端 PATH，然后在本仓库根目录执行命令。此公开源码版不附带工具安装包、预编译程序或虚拟机。

```powershell
go fmt ./...
go vet ./...
go test -count=1 ./...
go build -o raft-node.exe .
python scripts/smoke_test.py --nodes 3 11
python -m unittest discover -s scripts -p 'test_*.py'
```

Windows 的 Go 竞态检测另外需要兼容的 C 编译器；不具备工具链时不要把未执行写成通过。Linux 可用 `go test -race ./...`；二进制名称改为 `raft-node`。

## 11 节点现场演示

可选本机控制台保留原 CLI 和独立终端。先构建节点与控制台，在新目录生成配置并按原方式启动节点，然后以只读模式登记该配置：

```powershell
go build -o raft-node.exe .
go build -o raft-console.exe ./cmd/dashboard
.\raft-console.exe -config demo-runs/classroom/nodes.json
```

浏览器打开 `http://127.0.0.1:8080`。共享采集器每轮 Summary、最多 8 路并发且不重叠；所有浏览器共享快照。日志页按需读取最多 256 条真实条目，SSE 的缺口和丢弃计数明确显示；断线不会进入演示数据。默认只读，网络分区按钮明确不可用。控制台不会扫描或修改 WAL，关闭浏览器不会停止集群。

需要由页面创建新实验并控制节点时，运行 `raft-console.exe -node-bin .\raft-node.exe -allow-control`，再在“会话与设置”明确启用控制，创建 11 节点会话。每个会话保存独立配置、身份、数据和程序副本；新规模创建新会话，先停止当前自有节点再切换。停止操作核对本控制器持有的进程句柄、程序、参数及启动记录，不根据浏览器传入 PID 操作。控制器重启不凭旧 PID 接管进程，未完成写入保留为结果未知，不自动重发；正常关闭控制器会停止其自有节点并保留数据。

总览的“已提交”只来自实际 Generate 回执；全体应用、当前收敛校验、历史检查点校验分别显示。保存检查点后，故障重选/恢复可对同一 index/hash/x 再验证。验证与新采样冲突时标记为过期，不让旧的通过覆盖已知的新状态。

双击 `start.bat`，直接回车采用 11 个节点。启动脚本先编译一次，新目录生成 JSON，已有目录复用保存的固定成员，再按 JSON 中的 ID/地址打开独立节点终端并依次报告进程启动、节点可达、观察到一致 Leader。此时没有自动提交算术命令。每次默认建立新的实验目录。

也可以指定已有配置，支持非连续 ID：

```powershell
.\start.bat C:\Raft\nodes.json
```

终端最后会打印实际配置路径和数据目录。为便于复制后续命令，下面使用固定路径建立一次演示：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1 -Nodes 11 -RunDir demo-runs/classroom
```

使用同一目录再次启动会恢复该轮数据；省略 `-Nodes` 会沿用原数量（例如仍为 3）。显式节点数或配置与已存成员冲突时会报错，应换新目录；有数据却缺少配置时会拒绝猜测。首次传入外部配置也会保存到运行目录的 `nodes.json`。启动状态检查失败会停止本轮启动的进程并保留数据与诊断。要做全新实验请换目录，运行中不要删除数据。

## 终端总览与演示菜单

```powershell
.\raft-node.exe -config demo-runs/classroom/nodes.json -status-all -format table
.\raft-node.exe -config demo-runs/classroom/nodes.json -status-all -format table -watch 1s
.\demo.bat demo-runs/classroom
```

表格按节点 ID 排序，显示本地角色、任期、Leader ID、日志/提交/应用索引、命令数、x 和错误。它使用轻量状态查询，不计算完整日志或历史前缀，因此不能代替 `-verify`。默认 JSON 格式与原完整校验不变；可选 `-watch` 的 JSON 输出为一行一个数组。刷新请求串行执行，查询结束后再等待指定间隔；Ctrl+C 停止观察，活动查询最多再等待约 2 秒。表格不使用 ANSI 控制字符，支持输出重定向。

普通展示日志通过容量 256 的队列交给单消费者，队列满时丢弃并在 Status 的 `dropped_events` 中计数；不会阻塞 Raft 的互斥锁。另有 256 条内存事件环，EventRange 返回缺口标记。永久阻塞且不可关闭的外部 Writer 可能保留一个消费者直到该 Writer 返回或进程退出；Stop 最多额外等待普通输出 100 ms。WAL 与提交元数据的同步没有改为可丢队列。

提交入口用最多 8 路 Summary 发现，观察到匹配配置身份的 Leader 后即发起请求，不等待慢 Follower。它不把观察到的角色当作多数派授权；未知写入仍不自动重发。LogRange 是只读分页 RPC，默认 128、上限 256，返回复制后的条目与节点/集群/实例身份、任期、revision 及提交/应用索引。

菜单提供状态、刷新、生成、验证、停止指定节点、恢复节点和停止本会话全部节点。启动检查只表示观察到了 Leader；只有命令回复 `accepted=true, committed=true` 且没有错误时，菜单才显示 COMMITTED。未确认的写入不会自动重试。停止使用强制终止来模拟故障，保留配置和数据；恢复使用原 ID/目录，追赶完成后再验证。

也可直接调用动作，适合课堂脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo.ps1 -RunDir demo-runs/classroom -Action generate -Count 2101 -Seed 42
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo.ps1 -RunDir demo-runs/classroom -Action stop -NodeID 3
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo.ps1 -RunDir demo-runs/classroom -Action restart -NodeID 3
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo.ps1 -RunDir demo-runs/classroom -Action verify
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo.ps1 -RunDir demo-runs/classroom -Action stop-all
```

`session.json` 保存本次启动的节点 PID、启动时间、程序和配置摘要及参数。进程控制会核对身份，避免 PID 被复用后误操作其他进程；不会按程序名批量停止节点。配置或程序已改变时拒绝控制，先停止本会话再重新构建。旧目录没有 session.json 时，先使用 start.ps1 正常启动建立会话。退出菜单会保留节点运行，结束演示请选择停止全部。

## 生成并验证 2101 条命令

在另一个 PowerShell 窗口中运行：

```powershell
.\raft-node.exe -config demo-runs/classroom/nodes.json -demo 2101 -seed 42 -timeout 60s
.\raft-node.exe -config demo-runs/classroom/nodes.json -status-all
.\raft-node.exe -config demo-runs/classroom/nodes.json -verify
```

第一条客户端命令寻找 Leader，Leader 使用固定种子生成**恰好 2101 条算术命令**，经日志复制取得多数派并持久化提交位置后才返回 `accepted=true, committed=true`。回复中的 `last_index` 可用于 `-verify -target-index N` 检查这批命令的固定目标。Follower 的提交传播可能稍晚，短暂验证失败时可稍后重复只读 `-verify`。

每个任期新 Leader 会追加一个内部 `noop`，它不改变 x，也不计入 `committed_commands`。所以提交索引通常大于算术命令数。x 初始为 0，支持 add/sub/mul/div/mod；Go 整数除法向零截断，余数与被除数同号。生成器每 16 条以模 997 限制范围，乘数不超过 3，避免实验发生无意义溢出。

`-verify` 要求全部配置节点可达、日志全部提交并应用，且完整日志 SHA-256、已提交前缀 SHA-256、索引、命令数和 x 均一致；不能只看 x。摘要比较的是逻辑日志；WAL 中保留的历史替换记录可能不同，不应直接比较各节点整个 WAL 文件的字节哈希。节点运行日志包含 node、term、role、index 和关键事件，不打印重复心跳。

若提交超时、连接中断或接受后失去领导权，客户端会说明结果不确定。该版本没有客户端请求去重，**不要自动重试同一批算术写入**；先通过状态和日志确定结果。新的 seed 不等于幂等请求 ID。

## 故障重选与重启

从 `-status-all` 找到 Leader，关闭其终端，保持至少 6/11 节点在线。观察 `leader_elected`，再提交一批命令并检查存活节点。全部配置节点未恢复前，`-verify` 会明确报告离线，不会静默忽略。

用原 ID、配置和数据目录重新启动已关闭节点，例如原 ID 为 3：

```powershell
.\raft-node.exe -id 3 -config demo-runs/classroom/nodes.json -data-dir demo-runs/classroom/data -log-dir demo-runs/classroom/logs
.\raft-node.exe -config demo-runs/classroom/nodes.json -verify
```

它先恢复本地已提交状态，再补齐后续日志。旧 Leader 失去多数派后可能暂时仍显示 Leader，但不能成功提交新命令。少数派本地显示 Candidate/Leader 与“取得多数派并提交”不同。

## 空节点追赶和日志分歧

空节点是预先登记、从未启动的固定成员，不是动态增加成员，也不应通过删除既有成员投票记录模拟正常恢复。以下脚本先在其他节点提交 2101 条命令，再启动预留空节点，并核对日志摘要和执行状态：

```powershell
python scripts/benchmark.py --nodes 11 --entries 2101 --rounds 1 --scenarios catchup
```

合法分歧夹具保留 129 个索引的共同已提交前缀（1 个 noop 加 128 条算术命令），两个未提交分支分别只有少数副本。中立节点提供后续选举所需的额外投票但不接收分支日志。任意未提交尾部均可能被合法新 Leader 丢弃，这不是已提交数据丢失。

```powershell
python scripts/benchmark.py --nodes 11 --entries 2101 --rounds 1 --scenarios divergence
```

底层 `-prepare-divergence -demo 2101 -seed 42 -data-dir PATH` 只用于空离线实验目录，不能对运行中的数据目录操作。日志修复由正常 Raft 完成，不在运行时覆盖节点文件或直接复制 x。

## 10/20/50/100 节点实验

```powershell
python scripts/benchmark.py --nodes 10 20 50 100 --entries 2101 --rounds 5 --seed 42 --timeout 120
```

四场景：`election`、`failover`、`catchup`、`divergence`。支持 `--scenarios` 选择场景、`--output PATH` 指定新的结果目录。每轮独立目录、动态空闲端口，串行运行集群；脚本在成功或失败后清理本轮节点。清理仍失败时记录并停止后续实验。每个节点进程使用 GOMAXPROCS=1。

入口会在本轮输出目录构建一次当前源码，并记录 Git 提交、dirty 状态、源码/二进制 SHA-256 和实际 Go/Python 版本，避免复用过期的根目录程序。旧版本 80 轮记录保持原样；本轮结果在 `validation/closure-20261019`。

结果包括逐轮 JSON/CSV、汇总 JSON、配置、节点输出、最终状态和分歧夹具清单。失败轮次保留，不计入成功耗时均值；中断与清理失败单独记录，并停止后续轮次。`query-nodes.json` 只是存活节点的客户端查询列表，节点进程始终使用完整的 `nodes.json` 作为固定成员集合。

计时口径：

- 初次选举：首进程启动前至两次一致的 Leader 观测；包含启动/轮询成本。另报 Leader 内部 `election_ms`。
- 故障恢复：开始终止节点至新 Leader 的新命令提交成功；另报新 Leader 被观察到的时间和本地选举耗时。
- 空节点追赶：启动空节点前至固定目标日志和状态全部一致。
- 分歧同步：新 Leader 当选至确认全部日志一致后的最后一次 Leader 查询，以该进程单调时钟的 `leader_age_ms` 表示观测上界；另报启动至同步完成耗时。

故障与追赶前先保存已提交的 index/hash/x；新 Leader 提交、旧节点恢复及空节点追赶后必须匹配同一个历史检查点。`-verify` 本身比较当前节点状态；跨时间保护由实验保存的检查点额外验证。

快照查询最多 16 路并发，连续两次一致观测之间等待 100 ms。所有外部结果包含轮询和查询开销，不能当作协议瞬时延迟；单机多进程虚拟机数据不能代替物理多机网络结果。

## 数据、实现与限制

每节点保存 `node-ID-state.json`（term/votedFor/commitIndex/已提交前缀哈希）和 `node-ID-log.wal`。WAL v2 对长度/负载校验值构成的帧头和负载分别做 CRC 校验；追加一条逻辑后缀替换记录完成追加或冲突修复。日志先 Sync，提交元数据再同步替换，最后执行状态机。重启验证已提交前缀哈希后才重放，防止缺失后缀替换记录时恢复出旧日志。不完整末尾帧可恢复，完整帧损坏拒绝启动。

节点在读取或创建数据前独占 `node-ID.lock`，防止同一 ID、同一目录被两个实例同时写入；不同 ID 仍可共用目录。停止或进程异常退出会由操作系统释放所有权，锁文件保留，文件存在不表示节点仍在运行。运行中不要删除锁文件、替换或移动数据目录；升级前先停止旧版节点，旧版不会遵守这项锁约定。此保证针对本机文件系统上的协作进程，未验证 NFS/SMB。直接使用 Go API 时，成功 `NewNode` 后必须调用 `Stop`，即使 `Start` 失败；并发 `Stop` 均等待资源释放后返回。

WAL 写入与恢复使用相同的 32 MiB 单帧 JSON 负载上限。超限追加在写 WAL 前拒绝，不改变日志、提交或应用状态，节点仍可接受后续正常请求；更高任期仍按协议处理。原 WAL v2 格式和已有数据不变。smoke 测试只在进程及资源清理完成后写入最终结果；清理失败记录 FAIL，原始失败或中断保留其诊断。

核心文件：`raft.go` 选举/生命周期；`log.go` 复制/提交/客户端等待；`storage.go` 持久化；`state_machine.go` 确定性计算；`fixture.go` 离线实验历史；`rpc.go` 消息类型；`main.go` CLI；`scripts/benchmark.py` 实验；`docs/report.md` 报告及 `docs/rpc-flow.svg` 调用图。

不提供动态成员、日志压缩/快照、请求 exactly-once、线性一致读 API、生产级安全或整机断电耐久性保证。网络 RPC 不持互斥锁；为保持存储顺序，磁盘 Sync 仍在节点锁内。WAL 不压缩，长期运行会增长。命令行服务默认选举窗口 3–6 秒、心跳 150 ms、peer RPC 超时 1 秒，可通过 `-election-min`、`-election-jitter`、`-heartbeat`、`-rpc-timeout` 明确设置。每节点一个心跳定时器，只有 Leader 唤醒复制任务；每 peer 复用独占 TCP 连接，错误后重连，角色降级后关闭；投票 RPC 每个 peer 同时最多一个，避免跨任期堆积。尚无 WAN 性能结论。

`--timeout` 是每次收敛等待或写入的预算，不是包含多阶段的整场景总时限。恢复验证通过后才修剪不完整 WAL 尾帧。原始选举元数据可直接读取；开发中生成的 WAL v1 实验目录按旧版本保留，正式版本只使用 WAL v2，不能混用。

## 公开版本说明

公开目录采用独立 Git 历史，只包含源代码、测试、文档和脱敏结果。未包含原始课程压缩包、虚拟机、账户配置、原始日志、节点数据或工具安装包。`validation/benchmark` 与 `validation/source-sha256.json` 属于 81723b8 的原始测量，不代表本轮修改后的代码。新源码与新实验的对应关系见 [实验来源](validation/README.md)。未为原有代码补写或推定许可证。

## 本轮补充回归与报告

```powershell
go test -race ./raft -run 'TestElectionDeadlineEvents|TestGenerateReplyReuse|TestIncrementalCommittedHash|TestPartitionRepairs' -count=3
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_start.ps1 -WorkRoot demo-runs/launcher-check-new
python scripts/render_report.py --benchmark validation/closure-20261019/benchmark --validation validation/closure-20261019/checks.json
```

Windows 未配置 C 编译器时跳过 `-race` 并明确记录。启动验收需要新的 WorkRoot；它保留本轮文件并只清理自己的进程。分区测试使用测试专用 TCP 代理，不修改运行节点的 peers；少数派旧 Leader 可仍显示 Leader，但不得提交。计时器单元测试不构成所有网络条件下的活性证明。

报告从输入环境和逐轮记录重新统计；缺失字段写“未记录”，历史故障另列。原报告保留为 [report-81723b8.md](docs/report-81723b8.md)。

## 复制批次比较与 SVG 图表

默认复制批次仍为 128。节点可用 `-batch-size 64` 等值明确设置，范围 1..4096；固定成员和提交条件不变。实验入口支持同一构建的配对比较：

```powershell
python scripts/benchmark.py --nodes 11 --entries 2101 --rounds 3 --batch-sizes 64 128 256 --scenarios replication catchup --output .test-output/batch-comparison
python scripts/visualize.py --input .test-output/batch-comparison --output figures/batch-comparison
```

新增 replication 场景测量从发起命令到确认提交的外部耗时，并另外记录全部节点应用完成的观测耗时；原四场景仍是默认值。结果按场景、节点数、批次分别汇总，不混合不同批次。每个实验保存 events.json，使用从首进程启动前开始的单调时钟偏移记录实际观测事件。

图表脚本只依赖 Python 标准库，生成 performance.svg、timeline.svg 和 index.md。柱高是成功轮次均值、线段为最小至最大值，标注成功/尝试次数；失败不会算作 0 秒。时间线直接读取 events.json，不从旧日志猜测时间；缺少事件时明确标为未记录。输出目录必须新建，避免覆盖已有图。

本轮新增验收入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_demo.ps1 -WorkRoot demo-runs/demo-acceptance-new
go test ./raft -run '^$' -bench 'BenchmarkStatus|BenchmarkSummary' -benchtime=200ms -count=3
go test ./raft -run '^$' -bench BenchmarkBatchReplication -benchtime=1x -count=3
```
