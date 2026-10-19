# 三项审查发现的修复

基线为 `18d1e4b`。本轮只修复数据文件重复打开、WAL 帧大小限制不一致、smoke 在清理完成前发布 PASS；固定成员、CLI、net/rpc、WAL v2、日志哈希、提交规则和必要 Sync 保持原有语义。完整 Status 的性能优化不在本轮范围内。

| 问题与触发边界 | 修改 | 回归 |
|---|---|---|
| 同 ID、同 DataDir 的两次 NewNode 都能成功，独立文件偏移可以互相覆盖；这是重复实例触发，不是正常单实例协议反例 | 读任何元数据/WAL 前持有 `node-ID.lock`；Unix 使用非阻塞 flock，Windows 使用禁止共享的文件句柄；关闭 WAL 后释放锁 | 同进程/独立进程重复打开拒绝，不同 ID 或目录可用；强杀子进程后恢复；构造失败释放、Start 失败仍持有、Stop 后重开、目录别名 |
| 600,000 条合法追加形成超过 32 MiB 的帧，基线应答成功但重启拒读；内置 Leader 批次不会触发 | 读写统一使用 `maxWALPayload`；序列化后、写 WAL 前拒绝超限帧 | 既有 WAL、日志和已提交状态不变；随后正常追加、停止、恢复成功 |
| smoke 先写 PASS 再清理，清理抛错后文件仍为 PASS | 场景 finally 中先清理进程、关闭资源，再保存最终结果；成功文本最后输出 | 完整 scenario 路径模拟清理失败、成功、启动失败和中断；原 kill/wait 异常与后续进程清理测试保留 |

`raft.go` 同时补齐 Stop 的完成等待：第二个调用必须等待第一个调用完成文件释放。回归用受控阻塞的连接关闭，让第一个 Stop 暂停，再确认第二个不会提前返回。构造失败的清理由 `loadState` 集中负责，按 WAL → 锁的顺序关闭。

锁文件不会删除；进程死亡后由操作系统释放句柄，新进程可直接打开同一文件。锁按节点而非整个目录设置，不妨碍课程多节点共用 DataDir。不要在运行中删除/替换锁文件或移动目录。旧版程序不遵守锁约定，升级需先停止旧节点。本轮不宣称防护不合作进程、网络文件系统或整机断电。

平台实现包括 Linux、macOS、常见 BSD 和 Windows；其他平台在构造节点时明确拒绝，避免静默无锁运行。实际运行与交叉构建范围分别记录在 [验证记录](../validation/safety-20261019/README.md)。Windows 使用系统文件句柄排他，不需要管理员权限或第三方依赖；运行目录应使用正常长度的本机路径。

超限 RPC 仍可能合法更新任期、Leader 和选举期限，因此“拒绝不改变状态”仅指日志、WAL、提交和状态机应用；该限制也不是不可信 RPC 的内存防护。节点应继续只在本机或受信任网络使用。

可复现命令（仓库根目录）：

```shell
go vet ./...
go test -count=1 ./...
go test -race ./...
go test -race ./raft -run 'TestNodeStorage|TestConcurrentStopWaits|TestOversizedAppend' -count=3
go build -o raft-node .
python -m unittest discover -s scripts -p 'test_*.py'
python scripts/smoke_test.py --nodes 3 11
```

Windows 构建输出改为 `raft-node.exe`；缺少 C 编译器时不运行 race，并明确记录未执行。启动脚本/11 节点验收沿用 README 的 `test_start.ps1`、`test_demo.ps1`，必须使用新的 WorkRoot。三项回归在基线上的失败和修复后的结果单独保存，不用旧版本的 PASS 代替本轮验证。
