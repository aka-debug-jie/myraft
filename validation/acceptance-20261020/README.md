# 2026-10-20 原课程最终验收证据

源码起点cc7c185；协议修复5c64031，主要实测基准61ed114。当前生产源码与Win11原生构建收据逐文件对应；之后的报告、打包辅助脚本与证据整理不是该次测量源码。无远端推送。

- benchmark：Linux 10/20/50/100 × election/failover/replication/catchup/divergence ×3轮，60/60 PASS；含每轮完整逻辑日志与独立算术核查。
- pilot-11：11节点2101算术命令，提交/故障/空节点/分歧4/4 PASS。noop另计；所有在线节点的完整hash、commit、apply、命令数和x一致。
- windows-scale：原生Win11四规模选举/分歧共24轮，23 PASS、1 FAIL；失败位于100节点分歧r1，runtime启动分配失败。失败完整保留。
- windows-capacity-retest：增加测试VM的P盘页面文件后，100节点选举/分歧各3轮，6/6 PASS。容量变化和采样单列，不能混合均值。额外单轮memory-probe诊断通过不纳入上述统计。
- browser-real-second、grid-real：真实Chromium关键按钮/表单/11节点恢复历史/取消导出及100节点网格截图；首次browser-real失败是取消测试错误期待独立回执，实际取消成功，修正测试后重跑。
- ui-*：明确合成输入的浏览器交互和整数精度回归，不是Raft实验。
- node-output：11个stdout与文件双输出样本，checks.json逐节点核对关键字段/执行事件。
- routing-red/race：真实TCP错误路由的修复前失败及修复后race回归。package-red/green为打包来源绑定的合成回归，不是旧包已损坏的证据。
- native-build-receipt.json：原生源码集合及两个受测EXE摘要绑定；VM重建结果与此前受测程序相同。文件SHA只能核对已记录工件，不能提供第三方签名认证。

results.json、results.csv、summary.json的数值逐字节保留。environment.json只缩短本机输出路径；last-status.json移除process_id，未改共识/计时字段。部分转录隐去宿主机绝对工作区路径。WAL、完整进程日志与私有开发环境仍保存在本机独立 .tools/acceptance-20261020，未复制进公开目录。

人工可见终端关窗按使用者本轮决定NOT RUN；Windows race缺C工具链NOT RUN；另一台老师统一Win11尚未验收。各项标准与操作见../../docs/acceptance-a-g.md。旧81723b8的80轮和此前closure/console记录均未改动。
