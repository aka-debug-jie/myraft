# Windows 11 课堂使用

本阶段控制台首页改为全屏拓扑。鼠标靠近左边缘，或点击左上角菜单，展开六个工作区；键盘可用 Tab、Ctrl+K 和 Escape。点击节点打开详情；导航与详情覆盖画布，不改变节点排列。拖动空白平移，滚轮或双指缩放，右上角“适合”恢复视图。主题和投影开关在导航内；投影模式仍可再次打开导航退出。

绿色包面向 Windows 11 x64。解压到可写的新目录，支持中文和空格；不要直接在 ZIP 浏览窗口中运行。节点与 Web Console 已预编译，普通演示无需 Go、Python、Node.js，也不需要联网。旧实验目录不会自动删除。

## 11 个独立终端

1. 双击包根目录 `Start-Terminals.cmd`。默认在 `runs/classroom` 建立一次固定 11 成员配置，弹出每节点窗口；窗口标题为 `MyRaft Node ID`，每行事件含 node、term、role。已有实验重启复用原配置。
2. 在包的 `project` 目录打开 PowerShell，执行（这是终端版实验，和 Web 创建的会话各自独立）：

   ```powershell
   .\raft-node.exe -config ..\runs\classroom\nodes.json -demo 2101 -seed 42 -timeout 60s
   .\raft-node.exe -config ..\runs\classroom\nodes.json -verify
   .\raft-node.exe -config ..\runs\classroom\nodes.json -status-all -format table
   ```

3. 从状态表找 Leader，关闭对应节点窗口；保持至少 6/11 节点存活。Follower 关闭不必换届。观察新的 `leader_elected`，再发送新命令。已受理但未确认的请求不要自动重发。
4. 用原 ID 恢复该节点，例如原 Leader ID 为 3：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo.ps1 -RunDir "..\runs\classroom" -Action restart -NodeID 3
   .\raft-node.exe -config ..\runs\classroom\nodes.json -verify
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo.ps1 -RunDir "..\runs\classroom" -Action stop-all
   ```

   `NodeID 3` 仅为示例，须替换为实际关闭的 ID。也可运行 `demo.bat ..\runs\classroom` 进入菜单。
5. 全部停止后再双击入口会恢复原日志。新成员数量要换一个新实验目录，不能覆盖旧配置。自定义非连续 ID：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1 -UsePrebuilt -Config "C:\课程实验\原配置.json" -RunDir "C:\课程实验\新实验目录"
   ```

每个节点文本输出在实验目录 `logs/node-ID.log`；持久日志在 `data/node-ID-log.wal`，不要手动编辑或删除。出现 `output_dropped` 时表示普通展示事件曾丢弃，Status 也显示计数；WAL 的持久化不使用可丢队列。

**验收边界：本轮以自动化验证启动/停止/恢复；新版本未在已登录桌面执行可见窗口和真人关窗，见 acceptance-next.md。原版用户提供的自动桌面关窗记录与新版本验收分开；这份操作说明本身不构成通过证据。**

## 六页 Web Console

双击包根目录 `Start-Console.cmd`，浏览器打开终端打印的 `http://127.0.0.1:8080`。在“会话与设置”明确启用本机控制，再创建 11 节点会话。不要在已经占用端口的终端实验中重复启动相同节点。

- 总览：提交 2101 条命令、查看节点角色与三个索引；受理、提交、全部应用及完整校验分别显示。
- 日志实验室：勾选节点，按索引读取真实有界窗口，比较 term/command/noop 和提交/应用状态。
- 故障与时间线：停止需要二次确认。恢复原节点后等待追赶，再执行校验。没有网络分区注入器，分区按钮不可用。
- 性能实验：调用真实 Python runner；需要下节工具。表单参数不会被实时刷新重置，图表按源码、平台、规模、工作量、场景和批次分组。
- 一致性证据：先保存检查点；重选及恢复后分别执行“校验当前”和“校验历史”，导出 ZIP 原始证据。
- 会话与设置：新成员集合创建新实验；只停止本控制器真正拥有的进程。关闭浏览器不会终止集群，结束演示先停止节点，再在控制台终端按 Ctrl+C。

默认本机同源访问，禁止映射到公网。Web 管理的会话和终端脚本的会话拥有不同的进程所有权，不能通过 Web 接管外部终端进程。只读观察终端集群可以从 `project` 运行：

```powershell
.\raft-console.exe -config ..\runs\classroom\nodes.json -listen 127.0.0.1:8081
```

大整数显示保留原始数值；浏览器不支持精确 JSON 数字来源时，对超范围值会报错，不静默舍入。建议使用当前系统 Edge 或 Chrome。

## 规模实验与报告

**演示免开发环境，重新运行规模实验需要 Go 和 Python。** 从 Go 官网 `https://go.dev/dl/` 安装 Go 1.26.3 或更高版本；从 Python 官网 `https://www.python.org/downloads/windows/` 安装 Python 3.12 或更高版本并勾选加入 PATH。关闭后重新打开终端，运行 `go version` 和 `python --version` 确认。无需 pip 依赖，也不需要 Node.js。

双击 `Run-Experiments.cmd`，执行 10/20/50/100 节点、每场景三轮、2101 条命令的五场景矩阵。运行前确保可用磁盘空间；脚本每次新建独立目录，构建一次当前源码，记录源码/二进制摘要与工具版本，自动清理本轮进程。不要将旧 PASS 填入新报告。手动命令：

```powershell
python scripts/benchmark.py --nodes 10 20 50 100 --rounds 3 --entries 2101 --seed 42 --scenarios election failover replication catchup divergence
```

空节点是原配置中预留但延迟启动的成员；分歧实验在启动前建立合法共同提交前缀及不同未提交尾部。同步计时均以实际完整状态检查为结束，不以当选代替收敛。独立 Python 参考在停止后只读重放 WAL 核对算术结果，不计入协议耗时。

正式报告为 `project/docs/report.md`，调用图为 `rpc-flow.svg`，每项验收与证据路径在 `acceptance-a-g.md`。`validation` 保留历次来源，新旧结果不可混合；原 80 轮记录未改动。包内 `SHA256SUMS.txt` 可用 PowerShell `Get-FileHash -Algorithm SHA256` 对照。老师另一台统一 Win11 主机尚须按本说明复验。

100节点是多进程压力实验，需要足够的系统提交内存与磁盘空间。本测试VM曾在8GiB RAM、C盘仅约90MiB空闲时出现一次runtime启动分配失败；P盘增加页面文件后单独重测通过。该环境改动记录在报告中，交付程序不会替你修改系统页面文件；不要忽略失败记录或在缺资源时宣称通过。


## 性能实验的依赖

演示用预编译程序不需要 Go/Python。规模实验需要 Go（最低 go.mod 版本为 1.26.3）与 Python 3.12 或更高；控制台会检查源码、Go 的 go.mod 下限及 Python 版本，缺失或版本不足时显示“实验环境未就绪”，不会把它当作 Raft 协议失败。将可信便携 Go 的 bin 和 Python 目录加入本次终端 PATH，再启动控制台；也可使用 `-python` 指定 Python 可执行文件。环境变量变更后应重启控制台。无需安装 Node.js。

浏览器压力测试脚本另需 Playwright/Chromium，这是开发验证依赖。只运行 `--browsers 0` 不需要它，也不能据此宣称完成浏览器测试。新测量、来源与限制见 [性能说明](performance-next.md)；新版本结果见 [验收说明](acceptance-next.md)。


版本检查结果由浏览器共享缓存60秒，实际启动规模实验前强制刷新；版本满足不等于本轮构建或实验已经成功。工具调整后可重启控制台重新检查。

本版新建 Web 会话使用标题隔离；独立终端仍显示节点 ID。已有 Web 会话恢复时保留会话内原节点程序，不会自动替换成新版，因此旧节点仍可能改写宿主标题。确认窗口身份应同时核对会话和进程，不只看标题。


## 本版前端操作

右上角“演示流程”按准备集群、提交与应用、校验与检查点、故障恢复、历史核查提供入口；高级参数折叠，六个工作区保留。默认11节点、2101条算术命令、种子42。

底部任务栏持续显示最近操作。命令受理、提交、全体应用与完整校验是不同阶段；恢复进程后仍需等待追赶并执行历史校验。重新保存已有检查点需要确认，故障实验通常保留原检查点。

请求期间按钮即时显示忙碌。会话变化会关闭旧确认框；请求结果未知时不会自动重发，先查看任务和当前状态。断线时节点状态标为未知。页面重新连接成功后自动重新确认控制器身份。

六页支持浏览器前进、后退和刷新恢复当前页面。表单输入期间实时状态仍更新，草稿和光标保持；草稿仅存于当前页面会话内，不跨控制器重启保存。节点可用鼠标、触摸或键盘选择；画布聚焦后方向键平移，Tab聚焦的节点会进入视口。

新版100节点采用左右矩阵和中心Leader，默认展示全部已观测Leader关系。选择节点提亮对应路径，“关系聚焦”可筛选，其显示数量见关系说明；这些线不代表实测链路或复制确认。小屏用“适合”看整体，“聚焦”恢复可读大小。首页底部操作条提示课堂下一步，完整流程仍可展开。只读预览入口不开放操作。完整说明与本轮验收范围见 `frontend-enterprise.md`。
