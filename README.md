# MyRaft：固定成员 Raft 日志复制状态机

在原有 Go 选举项目上扩展，保留 `config / raft / rpc` 结构、JSON 配置、TCP `net/rpc`、选举重试、终端/文件双输出。新增持久化日志复制、当前任期多数派提交、算术状态机、冲突修复、节点恢复和规模实验。只依赖 Go/Python 标准库。

默认配置只监听 `127.0.0.1`。RPC 没有认证、TLS 或不可信客户端防护；仅在本机或受信任的隔离网络运行，不要将端口映射或开放至公网。详见 [安全说明](SECURITY.md)。

[课程报告](docs/report.md) · [RPC 调用图](docs/rpc-flow.svg) · [实验记录与版本边界](validation/README.md) · [本轮修复说明](docs/closure.md)

## 环境与构建

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

双击 `start.bat`，直接回车采用 11 个节点。启动脚本先编译一次，新目录生成 JSON，已有目录复用保存的固定成员，再按 JSON 中的 ID/地址打开独立节点终端并核对进程及 Status。每次默认建立新的实验目录。

也可以指定已有配置，支持非连续 ID：

```powershell
.\start.bat C:\Raft\nodes.json
```

终端最后会打印实际配置路径和数据目录。为便于复制后续命令，下面使用固定路径建立一次演示：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1 -Nodes 11 -RunDir demo-runs/classroom
```

使用同一目录再次启动会恢复该轮数据；省略 `-Nodes` 会沿用原数量（例如仍为 3）。显式节点数或配置与已存成员冲突时会报错，应换新目录；有数据却缺少配置时会拒绝猜测。首次传入外部配置也会保存到运行目录的 `nodes.json`。启动状态检查失败会停止本轮启动的进程并保留数据与诊断。要做全新实验请换目录，运行中不要删除数据。

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
