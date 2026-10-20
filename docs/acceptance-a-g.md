# 原课程 a～g 最终验收

原文见 [original-requirements.txt](original-requirements.txt)，来自提供的 `myraft.zip/myraft/readme.txt`。起点为干净的 `cc7c185`；核心修复和实验基准为 `61ed114`。历史 81723b8 的80轮、此前报告和旧ZIP均保留。没有推送远端。

**总状态：a 尚有人工操作未验收，b～g 的列明自动化操作通过；不得称为七项全部 PASS。** 使用者于本轮明确选择“先完成自动化，人工验收暂记 NOT RUN”。后台创建11个进程不等于11个可见Terminal。

| 项 | 最终状态 | 实际通过范围 | 未执行/限制 |
|---|---|---|---|
| a | **NOT RUN（人工部分）** | Win11预编译入口、11独立进程、中文/空格路径、非连续ID、原配置/数据恢复、成员变更拒绝、所有权停止 | 未登录桌面，11个可见窗口及人工点X未执行 |
| b | **PASS** | 四规模三轮初选/故障恢复、少数派不能提交、旧Leader恢复、成员路由别名不能构成虚假多数 | 单机TCP；不宣称所有网络下的活性 |
| c | **PASS** | 11节点2101条算术命令及完整日志/状态核对、独立Python参考、CLI与真实Web操作 | noop不计入命令数；未知写入不自动重试 |
| d | **PASS** | 原盘恢复与预登记空节点追赶、固定历史index/hash/x未变、起止/条目/摘要证据 | 固定成员延迟启动，不是动态扩容 |
| e | **PASS（保留失败与复验）** | Linux四规模各三轮12/12；Win11四规模初测含1失败，容量调整后100节点分歧3/3复验通过 | 不合并不同页面文件环境；14.6秒慢轮保留 |
| f | **PASS（输出自动核查）** | 11节点独立stdout/文本日志、关键事件/字段及有界丢弃提示 | 可见Terminal的人工观感属于a未验收部分；永久卡死sink有限制 |
| g | **PASS** | 正式报告、最新RPC SVG、结构体/调用链/安全规则/性能实测/失败来源 | 未执行项与数据环境明确列出 |

以下所有证据路径均相对项目根目录；公共根为 `validation/acceptance-20261020/`，完整本地原始材料位于交付工作区 `.tools/acceptance-20261020/`。

## a. 多节点与独立终端

原题：“node并发运行的数量超过10个，每个node对应一个terminal……所有节点的id和addr配置从文本文件读入”。

源码/入口：`Start-Terminals.cmd`、`start.bat`、`scripts/start.ps1`、`session.ps1`、`demo.ps1`、`console_windows.go`。绿色包根入口按保存的JSON启动；原源码入口仍可构建。窗口标题标明Node ID，事件标明term/role。`-UsePrebuilt` 不调用Go。

实际操作：Win11新目录运行 `test_start.ps1 -UsePrebuilt`，使用中文/空格路径与7/19/42非连续ID；原3节点目录省略Nodes重启仍为3，显式11或不同成员/cluster_id拒绝且原配置不变；2101条命令停止后恢复。`test_demo.ps1`启动11独立进程、停止Leader、提交新命令、恢复原节点并核对历史；尝试操作另一会话的PID/不同启动时间均被拒绝，结束无本轮节点残留。

结果：上述自动化 PASS，见 `windows-launcher-retry.txt`、`windows-test.txt`。首轮夹具因中文目录替换遗漏一个构造路径失败，修正测试路径后使用新目录重跑；未改协议或放宽断言。

待人工：登录Win11，双击包根 `Start-Terminals.cmd`，确认11个 `MyRaft Node ID` 可见窗口；从状态表确认Leader后点对应窗口X，确认该进程退出、其余多数派重选；用菜单恢复原ID，再执行完整验证。**此操作NOT RUN，需老师/使用者实际补验。**

## b. 选举、重选与多数派

原题：“选举具备重选功能……随机关闭某几个node对应的terminal……统计节点数为10、20、50、100时的选举时间”。

对应：`raft.go`、`log.go`、`rpc/rpc.go`、`routing_test.go`、`partition_test.go`、`scripts/benchmark.py`。

操作：Linux四规模分别执行election和failover三轮；后者在提交2101条后保存检查点，按seed停止Leader与部分Follower，始终保留多数，记录ID、事前role/term、停止起止、剩余人数和quorum；分别观测新Leader和新命令提交，再恢复原节点并核对旧前缀。真实TCP分区测试保持旧Leader存活于少数派，验证不能提交并在恢复后修复冲突。额外错误路由用例先证明五成员配置仅两实际节点时旧版错误计数，再证明修复后拒绝。

结果：Linux初选12/12、故障恢复12/12 PASS；Go/race与3/11节点smoke通过。Win11四规模初选12/12 PASS，增加页面文件后100节点初选另3/3 PASS。原生与Linux计时不混合。

证据：`benchmark/results.json`、`summary.json`，各 `failover-N-rR/result.json`/`events.json`/`checkpoint.json`；`routing-red.txt`、`routing-race.txt`、`critical-repeat.txt`、`smoke-linux.txt`、`windows-scale/`。外部初选、内部election_ms、故障到Leader被观察、故障到写入提交均有独立字段和统计。

## c. 2101 条命令与独立算术核查

原题：“log entry数量超过2000条……每个节点设置一个本地变量x（初始值为0）……判断结果是否相等”。

对应：`state_machine.go`、`log.go`、CLI `-demo 2101 -seed 42` / `-verify`、Web总览/日志/证据页、`scripts/arithmetic_reference.py`。

操作：11节点CLI真实提交2101条非noop命令，等全体完成后比较完整log_hash、committed_hash、LastLogIndex、CommitIndex、LastApplied、committed/applied_commands、x。停止进程后，独立Python只读校验WAL双CRC、后缀替换、JSON摘要字节定义及int64算术，重新比较上述字段；两个节点同报错误x的反例必须被参考计算拒绝。Web通过实际按钮完成同样2101条，并保存历史检查点。

结果：`pilot-11/replication-11-r1/` PASS，seed42的算术命令数2101，初始提交索引2102（含1个noop），x=0。全体独立参考PASS。真实Web额外故障后写入及12次负载小测使最终索引增大，不将其截图误说成“恰好2101”的最终状态。

证据：该轮 `last-status.json`、`arithmetic-reference.json`、`result.json`，`browser-real-second/results.json`/各页PNG、`windows-console-result.json`、`windows-console-operations.json`。

## d. 本地持久日志、原盘恢复、空节点追赶

原题：“把日志条目写入本地文件……节点宕机后再从文件读出……本地日志为空的节点日志同步到最新状态消耗的时间”。

对应：`storage.go`（WAL v2、身份、投票和提交元数据）、`identity_test.go`、`benchmark.py` failover/catchup、Windows demo恢复。

操作：原盘故障恢复使用同一ID/成员/cluster_id/目录，比较故障前固定index/hash/x；空节点在原配置预登记但未启动，先确认没有该节点的state/WAL，再在其他节点提交2101条后启动。记录before index/hash/x、UTC及单调时钟起止、目标索引、实际追赶条目和after完整hash/x；保留原历史检查点独立核验。

结果：11节点pilot故障恢复/空节点各PASS；Linux四规模空节点12/12 PASS；Win11菜单与HTTP停止/恢复/历史核查PASS。正常重启不丢已有提交、不重复执行；未提交尾部只在真实Raft冲突修复中被替换。

证据：`pilot-11/catchup-11-r1/`、`pilot-11/failover-11-r1/`、`benchmark/catchup-*`、`windows-launcher-retry.txt`及原生HTTP操作回执。每轮最终WAL均通过独立算术核查。

## e. 全部节点初始日志各异的收敛实验

原题：“当所有节点日志不一致时，新当选leader同步日志花费的时间（节点规模为10、20、50、100时分开统计）……初始时给每个节点不同数量的日志”。

对应：`fixture.go`、`fixture_manifest_test.go`、`benchmark.py` divergence；`visualize.py`和报告。

操作：离线新目录构造129索引共同提交前缀（noop+128条算术），两条未提交分支各不足多数。每节点长度唯一，启动前保存id/last_log_index/last_log_term/log_hash/commit/hash/x；启动后仅正常选举和AppendEntries修复。结束必须所有日志尾部、完整摘要、提交/应用索引及状态一致，原共同前缀不变，再独立读WAL验算。

结果：Linux四规模×3轮全部12/12 PASS，12份manifest逐项核对长度唯一。Win11初测10/20/50各3/3，100为2/3；失败为状态CLI运行时启动分配异常。测试VM增加P盘页面文件后100节点独立新目录3/3 PASS。原失败不删除；新环境分歧耗时1.454155、1.399812、14.626575秒，慢轮未剔除。

证据：`benchmark/divergence-N-rR/data/fixture.json`、每轮result/status/reference；`figures/performance.svg`、`windows-scale/divergence-100-r1/result.json`、`windows-capacity-retest/`、`windows-failure.txt`及资源采样。`elapsed_seconds` 是当选至全收敛观测上界，`startup_to_sync_seconds`另计，不能当选即宣布同步完成。

## f. 终端信息与独立文本记录

原题：“显示的信息清晰友好……terminal端显示的执行信息，要求写入文本文件……清晰的格式”。

对应：`main.go`的stdout/文件双输出、`events.go`容量256队列和单消费者、`display.go`状态表。

操作：真实11节点每节点stdout和 `logs/node-ID.log`逐一核对node/term/role、恢复/领导关系/复制/提交/应用事件，展示表格的三个索引与x。测试阻塞sink时仍能Status、持久提交2101条及有界Stop，拥塞后出现 `output_dropped` 文本提示和Status计数。

结果：11节点双输出检查全部PASS，见 `node-output/checks.json`及22份文本样本；普通监控输出不阻塞协议锁，WAL/提交元数据Sync仍先于成功应答。永久阻塞的外部Writer可能保留一个消费者直到返回/退出，进程停止前最后一批展示事件不保证全部落入文本文件；它不影响WAL安全。窗口人工可读性见a的NOT RUN。

## g. 报告、结构体与RPC图

原题：“rpc相关函数间相互调用关系的图片……主要结构体的设计思路，可能的局部优化方案”。

对应：`docs/report.md`、`docs/rpc-flow.svg`、`scripts/render_report.py`。报告列明角色、Node/LogEntry/Command、双向RPC身份、选举/复制/提交/冲突/恢复、当前任期多数派、固定前缀及持久化先后；图对应首次Leader才创建worker、后续任期复用，监控与按需验证分开。

结果：报告主要统计来自本轮results/环境重算，Win11补充表从各自summary生成，失败与容量变更单列；SVG已解析并实际渲染检查。旧报告另存report-cc7c185.md，原80轮不作为新版本PASS。PASS。

## 回归与绿色包补充

Linux：fmt/vet/build PASS；Go test和race各77顶级测试、42子用例PASS；关键身份/计时器/分区race再重复3次PASS；Python34 PASS；3/11节点smoke PASS。合成UI8 PASS、1 live项SKIP，真实浏览器由独立E2E通过。Win11 Go vet/test/build、32项Python（1个Linux专用SKIP）、3/11 smoke、启动/菜单/HTTP恢复通过；包辅助脚本新增测试在Linux通过。Windows race缺C工具链NOT RUN。

绿色包将在独立的新Win11目录解压后执行校验、免Go/Python PATH演示及原目录恢复；具体收据见 `portable-check.json`。**本文件生成时该包级测试尚待执行；在收据产生前不将包级项目标PASS。** 不影响上文已经实测的协议条目。另一台老师统一Win11系统尚未实测。
