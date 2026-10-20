# 原课程 a～g 最终验收

本轮起点：`cc7c185819e26ea87c7ff0793c072a3d340a7df2`，初始工作区干净。原题从提供的 `myraft.zip/myraft/readme.txt` 逐字核对。以前版本的 PASS 不代替本轮验收；本表将在实际验证后填写结果。

| 项 | 原题要求 | 现有实现及满足条件 | 本轮缺口与验证操作 | 本轮结果 |
|---|---|---|---|---|
| a | 超过10个 Node，每个独立 Terminal，Shell 启动，ID/addr 读文本 | `start.bat`、`scripts/start.ps1`、`session.ps1`，JSON 固定成员、恢复保护 | 绿色版免构建入口；Win11 11个可见窗口、关窗退出、原目录恢复；中文/空格及非连续ID | NOT RUN |
| b | 随机关闭节点后重选；10/20/50/100选举时间 | `raft.go`、`rpc.go`；benchmark election/failover | 修复错误路由重复计票；记录停止ID/角色/时间/多数派；四规模三轮，区分选举与新写入恢复计时 | NOT RUN |
| c | 超过2000条随机算术日志，执行结果一致 | `log.go`、`state_machine.go`，Generate、完整索引/摘要校验 | 11节点2101条非noop命令，独立算术参考，CLI和Web真实验证 | NOT RUN |
| d | 本地日志、宕机读取、空节点同步耗时 | WAL v2、`storage.go`、恢复/空节点实验及历史检查点 | 同身份恢复；预登记空节点延迟启动；保存起止/前后状态/目标/追赶条目及前缀证据 | NOT RUN |
| e | 所有节点日志不一致后同步；10/20/50/100分别统计 | `fixture.go`合法共同提交前缀、各异长度、真实AppendEntries | 启动前逐节点长度/末term/摘要清单；四规模三轮到完整收敛，单列选举后及总耗时 | NOT RUN |
| f | Terminal可读输出并写文本文件 | `events.go`有界普通输出、每节点日志、Status丢弃计数 | 真实演示核对关键事件/文件；明确输出丢失提示，保留持久化同步保证 | NOT RUN |
| g | RPC函数调用图片、主要结构体、局部优化 | `docs/report.md`、`rpc-flow.svg` | 根据本轮结果生成正式报告/图，校正首次Leader才启worker生命周期，保留旧来源 | NOT RUN |

新证据暂存工作区 `.tools/acceptance-20261020/`，可分发记录将整理至 `validation/acceptance-20261020/`。Windows 人工关窗与自动关闭窗口分别记录，不相互冒充。
