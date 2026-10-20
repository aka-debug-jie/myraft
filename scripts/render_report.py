"""Render the course report from recorded benchmark JSON, without third-party dependencies."""
import argparse
import json
from pathlib import Path
from itertools import product

from benchmark import summarize

ROOT = Path(__file__).resolve().parents[1]
NAMES = {'election': '初次选举（外部观测）', 'failover': '故障至新写入提交',
         'replication': '命令提交（外部观测）', 'catchup': '空节点追赶', 'divergence': '当选至分歧修复观测'}


def _field(mapping, key):
    value = mapping.get(key) if isinstance(mapping, dict) else None
    return '未记录' if value is None or value == '' else str(value)


def _source_label(path):
    source = Path(path).resolve()
    try:
        return source.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return source.name


def _counts(rows, environment):
    groups = {}
    interrupted_states = {'INTERRUPTED', 'ABORTED', 'CANCELLED', 'STOPPED'}
    for row in rows:
        key = (row['nodes'], row['scenario'], row.get('batch_size', 128))
        state = str(row.get('result', '')).upper()
        group = groups.setdefault(key, {'attempted': 0, 'passed': 0, 'failed': 0, 'interrupted': 0})
        group['attempted'] += 1
        if state == 'PASS':
            group['passed'] += 1
        elif state in interrupted_states:
            group['interrupted'] += 1
        else:
            group['failed'] += 1

    arguments = environment.get('arguments', {}) if isinstance(environment, dict) else {}
    nodes, scenarios, rounds = arguments.get('nodes'), arguments.get('scenarios'), arguments.get('rounds')
    batches = arguments.get('batch_sizes', [128])
    planned = None
    if isinstance(nodes, list) and isinstance(scenarios, list) and isinstance(rounds, int) and rounds >= 0:
        planned = len(nodes) * len(scenarios) * len(batches) * rounds
    if planned is None:
        for group in groups.values():
            group['unexecuted'] = '未记录'
        unexecuted = None
    else:
        for key in product(nodes, scenarios, batches):
            groups.setdefault(key, {'attempted': 0, 'passed': 0, 'failed': 0, 'interrupted': 0})
        unexecuted = 0
        for (node_count, scenario, batch), group in groups.items():
            expected = rounds if node_count in nodes and scenario in scenarios and batch in batches else 0
            group['unexecuted'] = max(0, expected - group['attempted'])
            if expected:
                unexecuted += group['unexecuted']
    return groups, planned, unexecuted


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--benchmark', type=Path, required=True)
    p.add_argument('--validation', type=Path, required=True)
    p.add_argument('--output', type=Path, default=ROOT / 'docs' / 'report.md')
    args = p.parse_args()
    rows = json.loads((args.benchmark / 'results.json').read_text(encoding='utf-8-sig'))
    environment_path = args.benchmark / 'environment.json'
    environment = json.loads(environment_path.read_text(encoding='utf-8-sig')) if environment_path.exists() else {}
    validation = json.loads(args.validation.read_text(encoding='utf-8-sig'))
    summary = summarize(rows)
    table = ['| 节点数 | 场景 | 通过/尝试 | 均值/s | 中位数/s | 最小/s | 最大/s | 本地选举均值/ms |',
             '|---:|---|---:|---:|---:|---:|---:|---:|']
    for item in summary:
        nums = [item.get(k) for k in ['mean_seconds', 'median_seconds', 'min_seconds', 'max_seconds', 'mean_local_election_ms']]
        values = ' | '.join(('—' if i == 4 else '未测得') if value is None else f'{value:.3f}'
                            for i, value in enumerate(nums))
        table.append(f"| {item['nodes']} | {NAMES.get(item['scenario'], item['scenario']) + (f' / batch {item["batch_size"]}' if 'batch_size' in item else '')} | {item['passed']}/{item['attempts']} | {values} |")

    timing_metrics = {
        'election_observed_seconds': '外部选举观测（s）',
        'initial_election_observed_seconds': '初次选举外部观测（s）',
        'initial_local_election_ms': '初次本地 election_ms（ms）',
        'service_restored_seconds': '故障后写入服务恢复（s）',
        'startup_to_sync_seconds': '启动至同步（s）',
    }
    timing_table = ['| 节点数 | 场景 | 指标 | 均值 | 中位数 | 最小 | 最大 |',
                    '|---:|---|---|---:|---:|---:|---:|']
    for item in summary:
        scenario_label = NAMES.get(item['scenario'], item['scenario'])
        if 'batch_size' in item:
            scenario_label += f" / batch {item['batch_size']}"
        for metric, label in timing_metrics.items():
            values = [item.get(f'{aggregate}_{metric}') for aggregate in ('mean', 'median', 'min', 'max')]
            if all(value is None for value in values):
                continue
            rendered = ' | '.join('未测得' if value is None else f'{value:.3f}' for value in values)
            timing_table.append(f"| {item['nodes']} | {scenario_label} | {label} | {rendered} |")
    if len(timing_table) == 2:
        timing_table.append('| 未记录 | 未记录 | 未记录 | 未测得 | 未测得 | 未测得 | 未测得 |')

    groups, planned, unexecuted = _counts(rows, environment)
    nodes = sorted({row['nodes'] for row in rows})
    scenarios = sorted({row['scenario'] for row in rows})
    scenario_names = '、'.join(NAMES.get(scenario, scenario) for scenario in scenarios) or '未记录'
    node_names = '、'.join(map(str, nodes)) or '未记录'
    round_counts = sorted({group['attempted'] for group in groups.values()})
    rounds_display = '、'.join(map(str, round_counts)) if round_counts else '未记录'
    outcome_counts = {
        'passed': sum(group['passed'] for group in groups.values()),
        'failed': sum(group['failed'] for group in groups.values()),
        'interrupted': sum(group['interrupted'] for group in groups.values()),
    }
    groups_table = ['| 节点数 | 场景 | 实际轮数 | 通过 | 失败 | 中断 | 未执行 |',
                    '|---:|---|---:|---:|---:|---:|---:|']
    for (node_count, scenario, batch), group in sorted(groups.items()):
        label = NAMES.get(scenario, scenario) + (f" / batch {batch}" if any("batch_size" in r for r in rows) else "")
        groups_table.append(f"| {node_count} | {label} | {group['attempted']} | {group['passed']} | {group['failed']} | {group['interrupted']} | {group['unexecuted']} |")
    if not groups:
        groups_table.append('| 未记录 | 未记录 | 0 | 未记录 | 未记录 | 未记录 | 未记录 |')

    checks_data = validation.get('checks') if isinstance(validation, dict) else None
    checks = '\n'.join(f"| {key} | {value} |" for key, value in checks_data.items()) if isinstance(checks_data, dict) and checks_data else '| 未记录 | 未记录 |'
    timings = environment.get('timings_ms') if isinstance(environment, dict) else None
    timing_text = '、'.join(f'{key}={value} ms' for key, value in timings.items()) if isinstance(timings, dict) and timings else '未记录'
    arguments = environment.get('arguments', {}) if isinstance(environment, dict) else {}
    measurement = _field(environment, 'measurement')
    go_version = environment.get('go_version', environment.get('go')) if isinstance(environment, dict) else None
    python_version = environment.get('python_version', environment.get('python')) if isinstance(environment, dict) else None
    plan_text = '未记录' if planned is None else f"{planned} 轮"
    unexecuted_text = '未记录' if unexecuted is None else f"{unexecuted} 轮"
    env_summary = (
        f"平台：{_field(environment, 'platform')}；Go：{'未记录' if go_version is None else go_version}；"
        f"Python：{'未记录' if python_version is None else python_version}；"
        f"逻辑 CPU：{_field(environment, 'logical_cpus')}；节点 GOMAXPROCS：{_field(environment, 'node_gomaxprocs')}。"
    )
    args_summary = '；'.join(f"{key}：{_field(arguments, key)}" for key in ('entries', 'seed', 'timeout')) if isinstance(arguments, dict) else '未记录'
    reproduction = None
    if planned is not None:
        reproduction = 'python scripts/benchmark.py --nodes ' + ' '.join(map(str, arguments['nodes']))
        reproduction += ' --scenarios ' + ' '.join(map(str, arguments['scenarios']))
        reproduction += f" --rounds {arguments['rounds']}"
        if 'batch_sizes' in arguments:
            reproduction += ' --batch-sizes ' + ' '.join(map(str, arguments['batch_sizes']))
        for key in ('entries', 'seed', 'timeout'):
            if key in arguments:
                reproduction += f" --{key} {arguments[key]}"
    text = f'''# 基于 Go 的固定成员 Raft 日志复制状态机

## 1. 目标与已有基础

项目在原 `myraft.zip` 的选举实现上扩展，保留固定成员 JSON 配置、Follower/Candidate/Leader 状态、随机选举、心跳、故障重选、term/votedFor 恢复、TCP net/rpc 和终端/文件双输出。新增日志匹配、批量复制、多数派提交、状态机执行、日志恢复、追赶与可复现实验。全部实现使用 Go/Python 标准库。

课程 a 项由配置驱动的 11 节点独立终端启动脚本覆盖；b 项由初选与随机宕机实验覆盖；c 项由 2101 条算术命令复制和日志摘要检查覆盖；d 项由预配置空节点追赶覆盖；e 项由合法未提交分歧夹具覆盖；f 项由统一运行事件输出覆盖；g 项由本报告及 SVG 调用图覆盖。实现与实际验证的边界分别说明，不把脚本具备功能等同于已经进行人工桌面验收。

## 2. 数据结构与角色转换

`Node` 保留原互斥锁、节点配置、任期、投票记录、角色、选举期限、连接集合和停止通道。新增日志切片、commitIndex、lastApplied、x，以及 Leader 专用 nextIndex/matchIndex。commitIndex 是已知提交的最高索引，lastApplied 是已执行的最高索引；nextIndex 是下一条待发送索引，matchIndex 是该 peer 已确认匹配的最高索引。角色和 x 不单独持久化，x 从已提交日志重建。索引 0 是内存哨兵；LogEntry 包含 Index、Term、Command，Command 使用 Op 和 int64 Value。

Follower 超时后增加任期、持久化对自己的投票并转为 Candidate。收到多数有效选票后，节点持久化一个本任期 noop，进入 Leader 并开始复制。更高任期的消息使节点持久化新任期并回到 Follower；同任期合法 Leader 的追加请求也会使 Candidate 跟随。单独更新任期不会延后选举期限；授予投票、收到非过期 Leader 的 AppendEntries（即使前缀不匹配）等协议事件才重置期限。一次任期最多投一名候选者。少数派可能不断竞选，失联旧 Leader 也可能暂留本地 Leader 角色，但两者都不能绕过多数派提交。

`Start` 启动 `acceptLoop` 与 `electionLoop`。每节点的 `electionLoop` 有一个选举轮询 ticker 和一个心跳 ticker；心跳 ticker 仅在节点为 Leader 时调用 `kickPeersLocked`，不是每个 peer 各自使用 ticker。首次执行 `becomeLeaderLocked` 时，先追加当前任期 noop，再切换为 Leader 并调用 `startReplicationLocked`；该函数按 peer 懒启动一个串行 `heartbeatLoop`，后续任期复用同一批 worker。`Stop` 关闭连接并等待这些 worker 退出后再关闭 WAL。另有在途投票调用上限，避免跨任期重复堆积。所有网络请求在锁外执行，发出前复制消息所需日志切片。状态和存储顺序由节点锁保护，磁盘 Sync 仍在锁内。

## 3. RPC 调用与关键算法

![RPC 调用关系](rpc-flow.svg)

图为独立 SVG，可直接插入报告。`RequestVote`、`AppendEntries` 和兼容旧客户端的 `Heartbeat` 均先以 `TargetID`、`ClusterID`、成员摘要执行 `checkTarget`，再处理任期。投票回复和追加回复通过 `matchesReply` 核对预期成员 ID（wire 回复字段为 `NodeID`）、集群 ID 和成员摘要，之后才处理更高任期或计入投票/复制进度。地址只负责路由，不作为成员身份。

RequestVote 比较候选人的最后日志任期，再比较最后索引。日志过旧的候选者不能得到该节点选票。AppendEntries 检查 prevLogIndex/prevLogTerm，拒绝不匹配前缀并返回冲突位置。Leader 根据回复回退 nextIndex，再按配置批量发送日志。Follower 跳过已相同的条目，只替换首次冲突后的未提交后缀，不因空心跳或重复请求而删除额外尾部。

`Options.BatchSize` 控制 AppendEntries 每批上限，默认 128，允许配置范围为 1..4096。Leader 计算取得多数副本的索引 N，只在 log[N].Term 等于当前任期时直接提交；旧任期条目通过提交当前任期 noop 或命令间接提交。Follower 的提交上限为 min(LeaderCommit, PrevLogIndex + len(Entries))，不能把本地额外尾部当作已经与 Leader 匹配。已提交前缀不可覆盖，迟到回复只有在请求任期仍等于当前 Leader 任期时才能改变复制进度。

客户端 `Generate` 先将命令追加到 WAL 并 `Sync`，随后返回 `Accepted`；Leader 收到多数副本确认后，仅对当前任期索引推进提交。`commitLocked` 先同步保存 commitIndex 与摘要，再更新内存 commitIndex、应用状态机、通知等待者，Generate 醒来后才返回 `Committed`。写入超时或连接中断时，结果可能未知；没有请求去重 ID，因此不能自动重试可能已接受的命令。只有明确的未接受 not leader 回复允许重新发现 Leader。完整 `Status` 与历史目标索引校验由诊断/验收路径单独执行；监控 Summary 不包含完整日志或历史前缀校验。

## 4. 状态机与持久化

x 初值为 0，按已提交日志顺序执行 add/sub/mul/div/mod；除数和模数不能为零。Go 整数除法向零截断，余数与被除数同号。固定种子生成的命令每隔 16 条先模 997，乘数最大 3，控制数值范围。每次 Generate 2101 产生恰好 2101 条算术命令；内部 noop 不计入算术命令数。

每节点保存一个元数据 JSON（term、votedFor、commitIndex、已提交前缀哈希）和一个命令 WAL。WAL v2 帧对长度/负载校验值构成的帧头以及 JSON 负载分别校验 CRC，记录一次逻辑后缀替换；普通追加无需重写全部历史日志。已提交前缀 SHA-256 只编码新增提交条目，保持原 JSON 编码和逐条换行；恢复时重建。元数据保存失败后不发布新提交索引或摘要，节点停止服务，不能再次使用已推进的累积状态。一致性摘要针对回放后的逻辑日志，不要求不同节点的 WAL 历史字节完全相同。写入顺序为日志 Sync → 更新内存日志；提交顺序为元数据保存并同步 → 更新 commitIndex 与提交摘要 → 顺序应用 → 通知等待者，Generate 随后确认 Committed。复制成功应答不会早于所需日志落盘。

恢复先完整回放 WAL，再检查最终 commitIndex 和已提交前缀哈希，从 x=0 仅重放已提交前缀。只有恢复验证通过才允许修剪短尾，避免损坏的后缀替换记录导致旧已提交内容复活。未提交尾部保留，但不执行。末尾不完整帧可以截回完整边界，完整帧校验错误或非法元数据会拒绝启动。没有日志压缩或快照；本实现验证进程崩溃恢复，不声称整机断电或磁盘永久损坏的耐久性。

独立算术参考由 `scripts/arithmetic_reference.py` 在实验节点停止后只读解析 WAL 与元数据，并用 Python 独立重算算术状态和摘要；它是实验验算，不是第二个 Raft，也不会修复实验文件。分歧 fixture 的 `fixture.json` 另记录每个节点启动前的 log index/term/hash、commit index/hash 与 x，作为逐节点初始 manifest。

## 5. 实验设计

实验环境依据输入记录填写：{env_summary}环境计时参数：{timing_text}。输入数据目录为 `{_source_label(args.benchmark)}`；节点为单机多进程并通过本机 TCP 通信，因此结果不能外推为真实多机或广域网性能。

计划参数：节点规模 {', '.join(map(str, arguments.get('nodes', []))) if isinstance(arguments, dict) and isinstance(arguments.get('nodes'), list) and arguments.get('nodes') else '未记录'}；场景 {', '.join(map(str, arguments.get('scenarios', []))) if isinstance(arguments, dict) and isinstance(arguments.get('scenarios'), list) and arguments.get('scenarios') else '未记录'}；每场景计划轮数 {_field(arguments, 'rounds')}；命令数、种子、超时分别为 {args_summary}。输入记录的测量口径：{measurement}。缺少对应输入字段时显示“未记录”。

初次选举从首进程启动前计至两次一致的 Leader 观测，另记录初次外部观测 `initial_election_observed_seconds` 和 Leader 本地 `initial_local_election_ms`。本地计时从自投票持久化后进入 Candidate 开始，到当前任期 noop 落盘并成为 Leader 结束，不包含此前随机选举超时。故障恢复在提交输入所设命令数后，按种子终止 Leader 和部分 Follower，始终保留多数派；`election_observed_seconds` 计至新 Leader 被观察到，`service_restored_seconds` 计至新 Leader 成功提交一条新命令。原 `elapsed_seconds` 口径保留为故障开始至该写入提交。随后重启旧节点并验证追赶。空节点实验预留一个从未启动的配置成员，在其余节点提交输入所设命令数并停止写入后启动它，计至固定目标日志和状态一致；分歧场景另记录 `startup_to_sync_seconds`。

分歧夹具的共同已提交前缀为 129 个索引（term 1 noop 加 128 条算术命令）。A/B 两组分别保存 term 2/3 的不同长度未提交分支，各组均不足多数；中立节点保留共同前缀，可投票但不接收后续分支。`fixture.json` 保存每个节点各自的初始索引、末项任期、日志摘要、提交索引/摘要及 x，不以单一全局值代替节点初始状态。偶数节点时 term 2 还可从 B 中取得一张选票而不向该节点复制日志。这种历史不要求互相矛盾的已提交数据。启动后由正常 Raft 修复，并核对共同前缀的 hash/x 不变。未提交尾部可能合法丢弃，因此该场景的最终算术条目数不保证等于预置的最长分支。

分歧同步时间由新 Leader 的单调时钟 leader_age_ms 得到，终点是确认一致后的最后一次查询，因此为包含观测开销的上界；另保存启动到完成时间。故障重选和空节点场景额外在事件前保存固定 index/hash/x，并在新提交、旧节点恢复和空节点追赶后核对同一个历史前缀。全部场景同时比较完整日志哈希、已提交哈希、提交/应用索引、算术命令数和 x，不能仅凭最终 x 判定一致。

## 6. 实际结果

输入记录共 {len(rows)} 轮，实际节点数为 {node_names} 节点，实际场景为 {scenario_names}；各组实际轮数为 {rounds_display} 轮。通过 {outcome_counts['passed']} 轮，失败 {outcome_counts['failed']} 轮，中断 {outcome_counts['interrupted']} 轮；计划轮数为 {plan_text}，未执行 {unexecuted_text}。节点/场景分组计数如下。统计表由输入 results.json 调用 benchmark.summarize 重算，仅以通过轮次计算时长统计。数据来源目录：`{_source_label(args.benchmark)}`。

{chr(10).join(groups_table)}

{chr(10).join(table)}

### 分项计时

以下指标分别按各组通过轮次计算；“未测得”表示该场景没有对应记录，不代表零耗时。

{chr(10).join(timing_table)}

观测耗时包含进程启动、磁盘同步、调度与查询成本，不能把曲线变化全部归因于 Raft 网络通信。本地 election_ms、外部选举观测、故障后写入服务恢复和启动至同步分别使用不同起止点，按分项计时表分别报告；本报告只描述上述输入记录，不据此给出生产系统尾延迟保证。监控轮询中的 Summary 与 EventRange 共享采样周期；LogRange 仅在需要查看日志时按范围读取，单次最多返回 256 项。Summary、完整 Status 与历史目标索引校验是不同观测路径，不把监控摘要当作完整一致性验收。

## 7. 测试与优化过程

验证清单取自输入文件 `{_source_label(args.validation)}`；缺少清单字段时显示“未记录”。

| 检查 | 实际结果 |
|---|---|
{checks}

## 历史开发记录（不属于本轮输入结论）

以下内容是历史故障与修复记录，不构成本轮实验环境、结果或验证结论。开发中曾记录初版失败与中断：每 peer 定时器造成非 Leader 的多余唤醒，短连接心跳产生较多 TIME_WAIT；旧环境诊断曾观测约 24698 个 TIME_WAIT 连接、约 71% CPU 负载。原始日志还记录了 `runtime: createevent failed; errno=1450` 和 `fatal error: runtime.semacreate`，表明旧 Windows 运行中出现过系统资源分配失败。这些证据不能单独定位到临时端口、内核事件或其他具体资源。后续版本统一每节点心跳定时器、复用每个复制任务的 TCP 连接，并在成功调用后清除 deadline，避免 net/rpc 后台 reader 空闲超时；还调整过服务时限和进程调度参数，并给每 peer 的投票调用加上在途上限。多项改变同时发生，不能把旧版与后续性能差异单独归因于某一项优化。

历史复核还修复过 WAL 长度字段损坏误判短尾以及停止失败时丢失进程句柄的问题，并加入已提交后缀替换记录损坏/缺失和真实 RPC 超时重连的测试。未完成或被中断的旧轮次不计为通过。以上历史信息与本轮结果输入分开记录。

## 8. 复现与局限

按项目 README 安装所需工具并运行格式检查、静态检查、单元测试、构建、集成与 Python 回归。演示使用项目提供的启动脚本，并按 README 给出的配置和数据目录运行节点及状态机命令。{('本轮参数对应的复现命令：' if reproduction else '计划参数未记录，未生成具体复现命令。')}

{('```\n' + reproduction + '\n```') if reproduction else ''}

使用原配置/ID/数据目录重启关闭节点，不删除投票记录。重新运行时应使用目标环境的输入参数和环境记录；本轮数值不能替代其他环境的测量。

当前没有动态成员、快照压缩、客户端 exactly-once、业务线性一致读、真实多进程分区注入框架或生产安全机制；旧 Leader 在失去多数时可能保留本地角色，但不能提交。WAL 持续增长，文件系统 Sync 成本仍影响大规模性能。

## 参考

Diego Ongaro and John Ousterhout. *In Search of an Understandable Consensus Algorithm (Extended Version)*，Figure 2 与第 5 节：https://raft.github.io/raft.pdf 。实现以原项目和课程 a–g 要求为基础，报告中的实验结论仅对应记录的实测版本；公开的脱敏结果与源码对应关系见 `validation/README.md`。
'''
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding='utf-8')
    print(args.output)


if __name__ == '__main__':
    main()
